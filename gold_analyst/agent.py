"""参考 CoreCoder 的核心思路：模型 → 工具 → 模型；仅提供只读研究与计算工具。

阅读顺序：investigate() 的循环 → tools/base.py → tools/__init__.py → 各具体工具。
本文件自主调查；demo.py 则是明确标注的固定教学流程，不冒充模型运行。
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from typing import cast

from .config import settings
from .llm import ModelResponse, ToolCall, ToolChoice, create_llm
from .models import RunState
from .prompts import SYSTEM, REVIEW, STRATEGIES
from .tools import Tool, create_tool_registry


MAX_RESEARCH_ROUNDS = 6
MAX_RESEARCH_TOOL_CALLS = 12
MAX_PARALLEL_TOOLS = 4


def safe_error(exc: Exception) -> str:
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


def investigate(
    run: RunState,
    emit: Callable[..., None],
    client: object | None = None,
) -> RunState:
    cfg = settings()
    if client is None:
        if not cfg["api_key"]:
            raise ValueError("请先在本地 .env 填写 OPENAI_API_KEY，或选择免 Key 教学演示。")
    llm = create_llm(cfg, client)
    strategy = STRATEGIES[run["strategy"]]
    run["model"] = cfg["model"]
    run["strategy_version"] = strategy["version"]
    tools = create_tool_registry(run, emit, client, cfg["model"])
    messages: list[object] = [{"role": "user", "content": run["input"]}]
    draft: dict[str, object] | None = None
    started = time.monotonic()
    report_tool = tools.get("submit_report")

    def respond(
        instructions: str,
        inputs: list[object],
        tool_schemas: list[dict[str, object]],
        choice: ToolChoice = "auto",
    ) -> ModelResponse:
        result = llm.respond(instructions, inputs, tool_schemas, choice)
        run["usage"]["input_tokens"] += result.input_tokens
        run["usage"]["output_tokens"] += result.output_tokens
        return result

    def execute_research(index: int, call: ToolCall, tool: Tool) -> tuple[int, object]:
        """在线程中执行一个研究工具；异常转换成模型可读的工具结果。"""
        try:
            emit("调用工具", call.name, call.arguments)
            output = tool.execute(**call.arguments)
            emit("工具完成", call.name)
            return index, output
        except Exception as exc:
            output = {"error": safe_error(exc)}
            emit("工具受阻", output["error"])
            return index, output

    # 前六轮允许模型一次选择多个研究工具；第七轮只允许提交报告。
    for round_number in range(MAX_RESEARCH_ROUNDS + 1):
        finalize = (
            round_number == MAX_RESEARCH_ROUNDS
            or run["usage"]["tool_calls"] >= MAX_RESEARCH_TOOL_CALLS
            or time.monotonic() - started > 240
        )
        emit("调查员", "整理现有证据并提交报告" if finalize else f"第 {round_number + 1} 轮：选择下一步调查")
        active_schemas = [report_tool.schema()] if finalize else tools.schemas()
        response = respond(SYSTEM + "\n调查策略：" + strategy["instruction"], messages, active_schemas,
                           {"type": "function", "name": "submit_report"} if finalize else "auto")
        messages.extend(response.history_items)
        calls = response.tool_calls
        if not calls:
            messages.append({"role": "user", "content": "请调用工具继续调查，或调用 submit_report 提交结构化结果。"})
            continue
        outputs: dict[int, object] = {}
        resolved: dict[int, Tool] = {}
        for index, call in enumerate(calls):
            try:
                resolved[index] = tools.get(call.name)
            except Exception as exc:
                outputs[index] = {"error": safe_error(exc)}

        terminal_indexes = [index for index, tool in resolved.items() if tool.terminal]
        if terminal_indexes:
            if len(calls) == 1:
                index = terminal_indexes[0]
                try:
                    candidate = resolved[index].execute(**calls[index].arguments)
                    if not isinstance(candidate, dict):
                        raise ValueError("报告工具必须返回对象")
                    draft = cast(dict[str, object], candidate)
                    outputs[index] = {"accepted": True}
                except Exception as exc:
                    error = safe_error(exc)
                    outputs[index] = {"error": error}
                    emit("工具受阻", error)
            else:
                for index in terminal_indexes:
                    outputs[index] = {
                        "error": "submit_report 不能与研究工具在同一批调用；请先读取本批结果，下一轮再提交。"
                    }

        research_indexes = [index for index, tool in resolved.items() if not tool.terminal]
        if finalize:
            for index in research_indexes:
                outputs[index] = {"error": "调查预算已用尽，请提交报告，未解决事项写入 unresolved。"}
        else:
            remaining = MAX_RESEARCH_TOOL_CALLS - run["usage"]["tool_calls"]
            allowed = research_indexes[:remaining]
            for index in research_indexes[remaining:]:
                outputs[index] = {"error": "研究工具总预算已用尽，请利用已有结果提交报告。"}
            run["usage"]["tool_calls"] += len(allowed)
            if len(allowed) == 1:
                index = allowed[0]
                result_index, result = execute_research(index, calls[index], resolved[index])
                outputs[result_index] = result
            elif allowed:
                with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_TOOLS, len(allowed))) as pool:
                    futures = [pool.submit(execute_research, index, calls[index], resolved[index]) for index in allowed]
                    for future in futures:
                        result_index, result = future.result()
                        outputs[result_index] = result

        for index, call in enumerate(calls):
            output = outputs.get(index, {"error": "工具调用未执行。"})
            messages.append({"type": "function_call_output", "call_id": call.id,
                             "output": json.dumps(output, ensure_ascii=False)})
        if draft:
            break
    if draft is None:
        raise ValueError("调查预算内未生成有效报告；已保留过程和证据，请缩小问题后重试。")
    accepted_draft = draft

    emit("审核员", "独立检查证据、口径与结论")
    # 独立上下文：只看原始任务、证据与初稿，不继承调查员过程。
    review_input = json.dumps({"task": run["input"], "draft": draft, "evidence": run["evidence"]}, ensure_ascii=False)
    try:
        response = respond(REVIEW, [{"role": "user", "content": review_input}], [report_tool.schema()],
                           {"type": "function", "name": "submit_report"})
        calls = [x for x in response.tool_calls if x.name == "submit_report"]
        if not calls:
            raise ValueError("审核员没有提交有效报告")
        report = report_tool.execute(**calls[0].arguments)
        if not isinstance(report, dict):
            raise ValueError("报告工具必须返回对象")
        run["review_status"] = "模型审核完成，仍需人工复核"
    except Exception as exc:
        report = accepted_draft
        report["review"] = "审核未完成；下列内容为调查初稿。" + safe_error(exc)
        run["review_status"] = "未审核初稿"
        emit("审核受阻", report["review"])
    run["report"] = report
    run["notice"] = "联网调查结果。模型审核不等于事实保证；证据、工具失败与未解决事项均已保留。"
    return run
