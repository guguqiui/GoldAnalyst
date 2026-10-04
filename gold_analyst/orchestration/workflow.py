"""协作式 Multi-Agent 的总入口。"""
from collections.abc import Callable

from ..models import RunState
from .judge import generate_final_report
from .planner import create_task_plan
from .runner import run_task_plan


def investigate_multi_workflow(
    run: RunState,
    emit: Callable[..., None],
    client: object | None = None,
) -> RunState:
    """按 Planner → Specialists → Verification → Judge 执行一次调查。"""
    emit("规划 Agent", "分解用户问题并生成任务依赖图")
    plan = create_task_plan(run["input"])
    run["plan"] = plan
    emit("规划结果", f"已生成 {len(plan['tasks'])} 个任务", {"plan": plan})

    run_task_plan(run, plan, emit, client)
    generate_final_report(run, emit, client)
    return run
