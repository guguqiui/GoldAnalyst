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
from .runtime import ToolResultLedger, microcompact
from .tools import Tool, create_tool_registry


DYNAMIC_CONTEXT_CHAR_LIMIT = 60_000
KEEP_RECENT_TOOL_RESULTS = 3


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
    system_instructions: str | None = None,
    output_tool_name: str = "submit_report",
    output_key: str = "report",
) -> RunState:
    cfg = settings()
    persist_llm_trace = client is None
    llm = create_llm(cfg, client)
    strategy = STRATEGIES[run["strategy"]]
    instructions = system_instructions or SYSTEM + "\n调查策略：" + strategy["instruction"]
    if review and output_tool_name != "submit_report":
        raise ValueError("独立报告审核只支持 submit_report")
    run["model"] = cfg["model"]
    run["strategy_version"] = strategy["version"]
    tools = create_tool_registry(run, emit, llm.client, cfg["model"], allowed_tools)
    messages: list[object] = [
        dict(item) for item in run.get("conversation_history", [])
        if item.get("role") in {"user", "assistant"} and item.get("content")
    ]
    messages.append({"role": "user", "content": run["input"]})
    draft: dict[str, object] | None = None
    started = time.monotonic()
    output_tool = tools.get(output_tool_name)
    # 保存完整成功结果及 call_id 对应关系。当前尚未压缩 messages，因此重复调用
    # 只需提示模型读取前文；下一阶段会在结果消失后从该账本恢复。
    tool_ledger = ToolResultLedger()
    force_finalize_for_stall = False

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

    def execute_research(index: int, call: ToolCall, tool: Tool) -> tuple[int, object, bool]:
        """在线程中执行一个研究工具；异常转换成模型可读的工具结果。"""
        try:
            with activity(emit, "调用工具", call.name, call.arguments):
                output = tool.execute(**call.arguments)
            return index, output, True
        except Exception as exc:
            output = {"error": safe_error(exc)}
            emit("工具受阻", output["error"])
            return index, output, False

    # 前 budget.rounds 轮允许选择研究工具；最后一轮只允许提交结构化结果。
    for round_number in range(budget.rounds + 1):
        lost_keys = microcompact(
            messages,
            tool_ledger,
            char_limit=DYNAMIC_CONTEXT_CHAR_LIMIT,
            keep_recent=KEEP_RECENT_TOOL_RESULTS,
        )
        if lost_keys:
            emit("上下文压缩", f"已收起 {len(lost_keys)} 条较早工具结果；完整内容仍保存在运行账本中")
        finalize = (
            force_finalize_for_stall
            or round_number == budget.rounds
            or run["usage"]["tool_calls"] >= budget.tool_calls
            or time.monotonic() - started > budget.duration_seconds
        )
        emit("调查员", "整理现有证据并提交结果" if finalize else f"第 {round_number + 1} 轮：选择下一步调查")
        active_schemas = [output_tool.schema()] if finalize else tools.schemas()
        phase = "生成结果" if finalize else "推理"
        phase_message = "根据现有证据组织结构化结果" if finalize else f"第 {round_number + 1} 轮：分析证据并规划下一步"
        response = respond(f"第 {round_number + 1} 轮", phase, phase_message,
                           instructions, messages, active_schemas,
                           {"type": "function", "name": output_tool_name} if finalize else "auto")
        messages.extend(response.history_items)
        calls = response.tool_calls
        if not calls:
            messages.append({"role": "user", "content": f"请调用工具继续调查，或调用 {output_tool_name} 提交结构化结果。"})
            if tool_ledger.finish_round() and not force_finalize_for_stall:
                force_finalize_for_stall = True
                emit("调查停滞", "连续三轮没有取得新的工具结果，下一轮将整理现有证据并提交")
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
                        raise ValueError("终止型工具必须返回对象")
                    draft = cast(dict[str, object], candidate)
                    outputs[index] = {"accepted": True}
                except Exception as exc:
                    error = safe_error(exc)
                    outputs[index] = {"error": error}
                    emit("工具受阻", error)
            else:
                for index in terminal_indexes:
                    outputs[index] = {
                        "error": f"{output_tool_name} 不能与研究工具在同一批调用；请先读取本批结果，下一轮再提交。"
                    }

        research_indexes: list[int] = []
        for index, tool in resolved.items():
            if tool.terminal:
                continue
            call = calls[index]
            skip_reason = tool.skip_reason(**call.arguments)
            if skip_reason:
                outputs[index] = {
                    "skipped": True,
                    "reason": skip_reason,
                }
                emit("工具跳过", f"{call.name} 未执行：{skip_reason}", call.arguments)
                continue
            if tool_ledger.is_blocked(call.name, call.arguments):
                outputs[index] = {
                    "error": (
                        f"{call.name} 使用相同参数已经连续失败两次，本次不再执行。"
                        "请更换参数或来源；无法继续时将问题写入 unresolved。"
                    ),
                    "skipped": True,
                    "blocked": True,
                }
                emit("工具阻止", f"{call.name} 相同参数已连续失败，未再次执行", call.arguments)
                continue
            call_key = tool_ledger.key_for(call.name, call.arguments)
            if call_key is not None and tool_ledger.is_compacted(call_key):
                replay_allowed = tool.is_readonly and (
                    tool.deterministic or tool.replay_after_compaction
                )
                cached = tool_ledger.result_for_key(call_key) if replay_allowed else None
                if cached is not None:
                    replayed = json.loads(cached)
                    if isinstance(replayed, dict):
                        replayed["_context_replay"] = {
                            "restored": True,
                            "message": "完整结果已从本次运行账本恢复，未重新访问外部来源。",
                        }
                    else:
                        replayed = {"result": replayed, "_context_replay": {"restored": True}}
                    outputs[index] = replayed
                    tool_ledger.mark_restored(call.id, call_key)
                    emit("上下文复用", f"已恢复 {call.name} 的历史完整结果，未重新执行", call.arguments)
                    continue
                # 旧值已经不再对模型可见，且该工具不允许恢复；必须重新执行，
                # 不能落入下面的“查看前序 ToolMessage”分支。
                research_indexes.append(index)
                continue
            if call_key is not None and tool_ledger.has_succeeded(call.name, call.arguments):
                outputs[index] = {
                    "skipped": True,
                    "reason": (
                        f"{call.name} 使用相同参数已经成功执行；结果仍在本次对话的前序 "
                        "ToolMessage 中，请直接使用该结果继续分析。"
                    ),
                }
                emit("复用上下文", f"{call.name} 相同参数的结果仍在前文，未重复执行", call.arguments)
                continue
            research_indexes.append(index)
        if finalize:
            for index in research_indexes:
                outputs[index] = {"error": "调查预算已用尽，请提交结构化结果，未解决事项写入 unresolved。"}
        else:
            remaining = budget.tool_calls - run["usage"]["tool_calls"]
            allowed = research_indexes[:remaining]
            for index in research_indexes[remaining:]:
                outputs[index] = {"error": "研究工具总预算已用尽，请利用已有结果提交结构化结果。"}
            run["usage"]["tool_calls"] += len(allowed)
            if len(allowed) == 1:
                index = allowed[0]
                result_index, result, success = execute_research(index, calls[index], resolved[index])
                outputs[result_index] = result
                if success:
                    tool_ledger.record_success(
                        calls[index].id,
                        calls[index].name,
                        calls[index].arguments,
                        result,
                    )
                else:
                    tool_ledger.record_failure(calls[index].name, calls[index].arguments)
            elif allowed:
                with ThreadPoolExecutor(max_workers=min(budget.parallel_tools, len(allowed))) as pool:
                    futures = [pool.submit(execute_research, index, calls[index], resolved[index]) for index in allowed]
                    for future in futures:
                        result_index, result, success = future.result()
                        outputs[result_index] = result
                        if success:
                            tool_ledger.record_success(
                                calls[result_index].id,
                                calls[result_index].name,
                                calls[result_index].arguments,
                                result,
                            )
                        else:
                            tool_ledger.record_failure(
                                calls[result_index].name,
                                calls[result_index].arguments,
                            )

        for index, call in enumerate(calls):
            output = outputs.get(index, {"error": "工具调用未执行。"})
            messages.append({"type": "function_call_output", "call_id": call.id,
                             "output": json.dumps(output, ensure_ascii=False)})
        if draft:
            break
        if tool_ledger.finish_round() and not force_finalize_for_stall:
            force_finalize_for_stall = True
            emit("调查停滞", "连续三轮没有取得新的工具结果，下一轮将整理现有证据并提交")
    if draft is None:
        raise ValueError("调查预算内未生成有效结果；已保留过程和证据，请缩小问题后重试。")
    accepted_draft = draft

    if not review:
        run[output_key] = accepted_draft  # type: ignore[literal-required]
        if output_key == "report":
            run["review_status"] = "候选报告待裁判审核"
            run["notice"] = "独立研究员候选报告；最终结论由裁判合并。"
        else:
            run["review_status"] = "专业发现待独立核验"
            run["notice"] = "专业 Agent 中间产物；不能直接作为最终用户结论。"
        return run

    emit("审核员", "独立检查证据、口径与结论")
    # 独立上下文：只看原始任务、证据与初稿，不继承调查员过程。
    review_input = json.dumps({"task": run["input"], "draft": draft, "evidence": run["evidence"]}, ensure_ascii=False)
    try:
        response = respond("审核轮", "审核", "独立核对证据、口径和报告结论",
                           REVIEW, [{"role": "user", "content": review_input}], [output_tool.schema()],
                           {"type": "function", "name": "submit_report"})
        calls = [x for x in response.tool_calls if x.name == "submit_report"]
        if not calls:
            raise ValueError("审核员没有提交有效报告")
        report = output_tool.execute(**calls[0].arguments)
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
