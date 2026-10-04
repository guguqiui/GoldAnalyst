"""将专业 Findings 与核验结果整理为最终报告。"""
import json
from collections.abc import Callable

from ..agent import safe_error
from ..config import settings
from ..models import RunState
from ..persistence.local import save_llm_turn
from ..progress import activity
from ..prompts import WORKFLOW_JUDGE
from ..providers.llm import create_llm
from ..tools import create_tool_registry


def generate_final_report(
    run: RunState,
    emit: Callable[..., None],
    client: object | None = None,
) -> RunState:
    """强制 Judge 只读取已有产物，并通过 submit_report 提交报告。"""
    if not run.get("findings"):
        raise ValueError("Judge 之前没有专业 Findings")
    if not run.get("verification_result"):
        raise ValueError("Judge 之前没有独立核验结果")

    cfg = settings()
    tools = create_tool_registry(run, emit, client, cfg["model"], {"submit_report"})
    report_tool = tools.get("submit_report")
    payload = {
        "question": run["input"],
        "findings": run["findings"],
        "verification_result": run["verification_result"],
        "evidence": run.get("evidence", []),
    }
    inputs = [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
    tool_choice = {"type": "function", "name": "submit_report"}

    emit("裁判 Agent", "根据专业发现与独立核验生成最终报告")
    with activity(emit, "裁判", "整理已核验结论"):
        response = create_llm(cfg, client).respond(
            WORKFLOW_JUDGE,
            inputs,
            [report_tool.schema()],
            tool_choice,
        )
    run["usage"]["input_tokens"] += response.input_tokens
    run["usage"]["output_tokens"] += response.output_tokens

    if client is None:
        try:
            request = {
                "instructions": WORKFLOW_JUDGE,
                "input": inputs,
                "tools": [report_tool.schema()],
                "tool_choice": tool_choice,
            }
            sequence = len(run.setdefault("message_files", [])) + 1
            path = save_llm_turn(run["id"], sequence, "裁判轮", cfg["model"], request, response)
            run["message_files"].append(path)
        except (OSError, ValueError) as exc:
            emit("本地记录受阻", f"裁判模型返回未能写入隐藏目录：{safe_error(exc)}")

    calls = [call for call in response.tool_calls if call.name == "submit_report"]
    emit("模型结果", "裁判轮选择：" + "、".join(call.name for call in calls), {
        "tool_calls": [{"name": call.name, "arguments": call.arguments} for call in calls]
    })
    if not calls:
        raise ValueError("裁判 Agent 没有提交有效报告")

    report = report_tool.execute(**calls[0].arguments)
    if not isinstance(report, dict):
        raise ValueError("裁判报告必须为对象")
    run["report"] = report
    run["model"] = cfg["model"]
    run["strategy"] = "multi_agent_workflow"
    run["strategy_version"] = "3.0"
    run["review_status"] = "Multi-Agent 独立核验与裁判已完成，仍需人工复核"
    run["notice"] = "协作式 Multi-Agent 调查结果；模型裁判不等于事实保证。"
    return run
