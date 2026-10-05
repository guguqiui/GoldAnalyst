"""协作式 Multi-Agent 的总入口。"""
from collections.abc import Callable

from ..agent import safe_error
from ..models import RunState
from ..persistence.local import save_llm_turn
from .judge import generate_final_report
from .planner import generate_task_plan
from .runner import run_task_plan
from .validation import validate_task_plan


def investigate_multi_workflow(
    run: RunState,
    emit: Callable[..., None],
    client: object | None = None,
) -> RunState:
    """按 Planner → Specialists → Verification → Judge 执行一次调查。"""
    emit("规划 Agent", "分解用户问题并生成任务依赖图")
    planning = generate_task_plan(run["input"], client)
    plan = planning.plan
    run["plan"] = plan
    run["usage"]["input_tokens"] += planning.response.input_tokens
    run["usage"]["output_tokens"] += planning.response.output_tokens
    if client is None:
        try:
            sequence = len(run.setdefault("message_files", [])) + 1
            path = save_llm_turn(
                run["id"], sequence, "规划轮", planning.model,
                planning.request, planning.response,
            )
            run["message_files"].append(path)
        except (OSError, ValueError) as exc:
            emit("本地记录受阻", f"规划模型返回未能写入隐藏目录：{safe_error(exc)}")
    validate_task_plan(plan)
    emit("规划结果", f"已生成 {len(plan['tasks'])} 个任务", {"plan": plan})

    run_task_plan(run, plan, emit, client)
    generate_final_report(run, emit, client)
    return run
