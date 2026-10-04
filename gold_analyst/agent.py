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
from .providers.llm import ModelResponse, ToolCall, ToolChoice, create_llm
from .persistence.local import save_llm_turn
from .models import DEFAULT_RESEARCH_BUDGET, ResearchBudget, RunState
from .prompts import SYSTEM, REVIEW, STRATEGIES
from .progress import activity
from .tools import Tool, create_tool_registry


def safe_error(exc: Exception) -> str:
    """不把 SDK 错误中的请求头或密钥输出到网页/报告。"""
    name = type(exc).__name__
    messages = {"AuthenticationError": "模型认证失败：API 模式检查 Key；Codex 模式重新运行 --login-codex。",
                "RateLimitError": "OpenAI 额度不足或请求受限，请检查账户额度后重试。",
                "APIConnectionError": "无法连接 OpenAI，请检查网络或 OPENAI_BASE_URL。",
                "APITimeoutError": "OpenAI 请求超时，可稍后重试。",
                "NotFoundError": "模型或 API 路径不可用，请检查 GOLD_MODEL / GOLD_CODEX_MODEL 与服务地址。",
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
    budget: ResearchBudget = DEFAULT_RESEARCH_BUDGET,
    review: bool = True,
    allowed_tools: set[str] | frozenset[str] | None = None,
) -> RunState:
    cfg = settings()
    persist_llm_trace = client is None
    llm = create_llm(cfg, client)
    strategy = STRATEGIES[run["strategy"]]
    run["model"] = cfg["model"]
    run["strategy_version"] = strategy["version"]
    tools = create_tool_registry(run, emit, llm.client, cfg["model"], allowed_tools)
    messages: list[object] = [{"role": "user", "content": run["input"]}]
    draft: dict[str, object] | None = None
    started = time.monotonic()
    report_tool = tools.get("submit_report")

    def emit_model_result(label: str, result: ModelResponse) -> None:
        """展示模型可观察的决定，不伪装成或泄露模型隐藏思维过程。"""
        calls = [{"name": call.name, "arguments": call.arguments} for call in result.tool_calls]
        if calls:
            names = "、".join(call["name"] for call in calls)
            emit("模型结果", f"{label}选择：{names}", {"tool_calls": calls})
        else:
            emit("模型结果", f"{label}没有返回工具调用", {"tool_calls": []})

    def respond(
        label: str,
        activity_stage: str,
        activity_message: str,
        instructions: str,
        inputs: list[object],
        tool_schemas: list[dict[str, object]],
        choice: ToolChoice = "auto",
    ) -> ModelResponse:
        request = {"instructions": instructions, "input": inputs, "tools": tool_schemas, "tool_choice": choice}

        with activity(emit, activity_stage, activity_message):
            result = llm.respond(instructions, inputs, tool_schemas, choice)
        run["usage"]["input_tokens"] += result.input_tokens
        run["usage"]["output_tokens"] += result.output_tokens
        if persist_llm_trace:
            try:
                sequence = len(run.setdefault("message_files", [])) + 1
                path = save_llm_turn(run["id"], sequence, label, cfg["model"], request, result)
                run["message_files"].append(path)
            except (OSError, ValueError) as exc:
                emit("本地记录受阻", f"本轮模型返回未能写入隐藏目录：{safe_error(exc)}")
        emit_model_result(label, result)
        return result

    def execute_research(index: int, call: ToolCall, tool: Tool) -> tuple[int, object]:
        """在线程中执行一个研究工具；异常转换成模型可读的工具结果。"""
        try:
            with activity(emit, "调用工具", call.name, call.arguments):
                output = tool.execute(**call.arguments)
            return index, output
        except Exception as exc:
            output = {"error": safe_error(exc)}
            emit("工具受阻", output["error"])
            return index, output

    # 前 budget.rounds 轮允许选择研究工具；最后一轮只允许提交报告。
    for round_number in range(budget.rounds + 1):
        finalize = (
            round_number == budget.rounds
            or run["usage"]["tool_calls"] >= budget.tool_calls
            or time.monotonic() - started > budget.duration_seconds
        )
        emit("调查员", "整理现有证据并提交报告" if finalize else f"第 {round_number + 1} 轮：选择下一步调查")
        active_schemas = [report_tool.schema()] if finalize else tools.schemas()
        phase = "生成报告" if finalize else "推理"
        phase_message = "根据现有证据组织结构化报告" if finalize else f"第 {round_number + 1} 轮：分析证据并规划下一步"
        response = respond(f"第 {round_number + 1} 轮", phase, phase_message,
                           SYSTEM + "\n调查策略：" + strategy["instruction"], messages, active_schemas,
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
            remaining = budget.tool_calls - run["usage"]["tool_calls"]
            allowed = research_indexes[:remaining]
            for index in research_indexes[remaining:]:
                outputs[index] = {"error": "研究工具总预算已用尽，请利用已有结果提交报告。"}
            run["usage"]["tool_calls"] += len(allowed)
            if len(allowed) == 1:
                index = allowed[0]
                result_index, result = execute_research(index, calls[index], resolved[index])
                outputs[result_index] = result
            elif allowed:
                with ThreadPoolExecutor(max_workers=min(budget.parallel_tools, len(allowed))) as pool:
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

    if not review:
        run["report"] = accepted_draft
        run["review_status"] = "候选报告待裁判审核"
        run["notice"] = "独立研究员候选报告；最终结论由裁判合并。"
        return run

    emit("审核员", "独立检查证据、口径与结论")
    # 独立上下文：只看原始任务、证据与初稿，不继承调查员过程。
    review_input = json.dumps({"task": run["input"], "draft": draft, "evidence": run["evidence"]}, ensure_ascii=False)
    try:
        response = respond("审核轮", "审核", "独立核对证据、口径和报告结论",
                           REVIEW, [{"role": "user", "content": review_input}], [report_tool.schema()],
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
