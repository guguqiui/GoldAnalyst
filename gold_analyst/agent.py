"""参考 CoreCoder 的核心思路：模型 → 工具 → 模型；仅提供只读研究与计算工具。

阅读顺序：investigate() 的循环 → tools/base.py → tools/__init__.py → 各具体工具。
本文件自主调查；demo.py 则是明确标注的固定教学流程，不冒充模型运行。
"""
import json
import time
from .config import settings
from .prompts import SYSTEM, REVIEW, STRATEGIES
from .tools import create_tool_registry


def safe_error(exc):
    """不把 SDK 错误中的请求头或密钥输出到网页/报告。"""
    name = type(exc).__name__
    messages = {"AuthenticationError": "OpenAI Key 无效，请检查本地 .env。",
                "RateLimitError": "OpenAI 额度不足或请求受限，请检查账户额度后重试。",
                "APIConnectionError": "无法连接 OpenAI，请检查网络或 OPENAI_BASE_URL。",
                "APITimeoutError": "OpenAI 请求超时，可稍后重试。",
                "NotFoundError": "模型或 API 路径不可用，请检查 GOLD_MODEL 与服务地址。",
                "BadRequestError": "模型不支持当前 Responses/工具参数，请检查模型与接口配置。"}
    if name in messages:
        return messages[name]
    if isinstance(exc, (ValueError, ImportError)):
        text = str(exc)[:250]
        key = settings()["api_key"]
        return text.replace(key, "[密钥已隐藏]") if key else text
    return "运行失败：" + name + "。已保留此前取得的证据，可重试或检查网络。"


def investigate(run, emit, client=None):
    cfg = settings()
    if client is None:
        if not cfg["api_key"]:
            raise ValueError("请先在本地 .env 填写 OPENAI_API_KEY，或选择免 Key 教学演示。")
        from openai import OpenAI
        client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"], timeout=45, max_retries=0)
    strategy = STRATEGIES[run["strategy"]]
    run["model"] = cfg["model"]
    run["strategy_version"] = strategy["version"]
    tools = create_tool_registry(run, emit, client, cfg["model"])
    messages = [{"role": "user", "content": run["input"]}]
    draft = None
    started = time.monotonic()
    report_tool = tools.get("submit_report")

    def respond(instructions, inputs, schemas, choice="auto"):
        result = client.responses.create(model=cfg["model"], instructions=instructions,
            input=inputs, tools=schemas, tool_choice=choice, parallel_tool_calls=False,
            max_output_tokens=3000, store=False)
        run["usage"]["input_tokens"] += getattr(result.usage, "input_tokens", 0)
        run["usage"]["output_tokens"] += getattr(result.usage, "output_tokens", 0)
        if getattr(result, "status", "completed") != "completed":
            raise ValueError("模型输出未完成，不能将截断的回复作为核验结果")
        return result

    # 第七轮只允许收尾；限制总工具数与总调查时长，不让代理无限搜索。
    for round_number in range(7):
        finalize = round_number == 6 or run["usage"]["tool_calls"] >= 12 or time.monotonic() - started > 240
        emit("调查员", "整理现有证据并提交报告" if finalize else f"第 {round_number + 1} 轮：选择下一步调查")
        schemas = [report_tool.schema()] if finalize else tools.schemas()
        response = respond(SYSTEM + "\n调查策略：" + strategy["instruction"], messages, schemas,
                           {"type": "function", "name": "submit_report"} if finalize else "auto")
        messages.extend(response.output)
        calls = [item for item in response.output if item.type == "function_call"]
        if not calls:
            messages.append({"role": "user", "content": "请调用工具继续调查，或调用 submit_report 提交结构化结果。"})
            continue
        for call in calls:
            try:
                args = json.loads(call.arguments)
                if not isinstance(args, dict):
                    raise ValueError("工具参数必须为对象")
                selected_tool = tools.get(call.name)
                if selected_tool.terminal:
                    draft = selected_tool.execute(**args)
                    output = {"accepted": True}
                elif finalize or run["usage"]["tool_calls"] >= 12:
                    output = {"error": "工具预算已用尽，请提交报告，未解决事项写入 unresolved。"}
                else:
                    run["usage"]["tool_calls"] += 1
                    emit("调用工具", call.name, args)
                    output = selected_tool.execute(**args)
                    emit("工具完成", call.name)
            except Exception as exc:
                output = {"error": safe_error(exc)}
                emit("工具受阻", output["error"])
            messages.append({"type": "function_call_output", "call_id": call.call_id,
                             "output": json.dumps(output, ensure_ascii=False)})
        if draft:
            break
    if draft is None:
        raise ValueError("调查预算内未生成有效报告；已保留过程和证据，请缩小问题后重试。")

    emit("审核员", "独立检查证据、口径与结论")
    # 独立上下文：只看原始任务、证据与初稿，不继承调查员过程。
    review_input = json.dumps({"task": run["input"], "draft": draft, "evidence": run["evidence"]}, ensure_ascii=False)
    try:
        response = respond(REVIEW, [{"role": "user", "content": review_input}], [report_tool.schema()],
                           {"type": "function", "name": "submit_report"})
        calls = [x for x in response.output if x.type == "function_call" and x.name == "submit_report"]
        if not calls:
            raise ValueError("审核员没有提交有效报告")
        report = report_tool.execute(**json.loads(calls[0].arguments))
        run["review_status"] = "模型审核完成，仍需人工复核"
    except Exception as exc:
        report = draft
        report["review"] = "审核未完成；下列内容为调查初稿。" + safe_error(exc)
        run["review_status"] = "未审核初稿"
        emit("审核受阻", report["review"])
    run["report"] = report
    run["notice"] = "联网调查结果。模型审核不等于事实保证；证据、工具失败与未解决事项均已保留。"
    return run
