"""执行 TaskPlan 之前的结构校验。"""
from datetime import date

from ..schemas import AgentRole, TaskPlan
from ..sources.universes import SOURCE_UNIVERSES


AGENT_ROLES: set[AgentRole] = {"market", "cause", "verification"}
TIME_MODES = {
    "exact_date", "date_range", "latest_available", "rolling_window",
    "year_to_date", "unspecified",
}
TIME_UNITS = {"none", "day", "week", "month", "year"}
TIME_COMPARISONS = {"none", "previous_trading_day", "range_start"}


def validate_task_plan(plan: TaskPlan) -> TaskPlan:
    """拒绝无法安全调度的任务图；通过时原样返回计划。"""
    if not isinstance(plan.get("question"), str) or not plan["question"].strip():
        raise ValueError("TaskPlan 的 question 不能为空")
    market = plan.get("market")
    if market not in SOURCE_UNIVERSES or market in {"macro_drivers", "discovery_news"}:
        raise ValueError(f"TaskPlan 使用了未知黄金市场：{market}")
    time_range = plan.get("time_range")
    if not isinstance(time_range, dict) or set(time_range) != {"start", "end"}:
        raise ValueError("TaskPlan 的 time_range 必须包含 start 和 end")
    if not all(isinstance(time_range[field], str) for field in ("start", "end")):
        raise ValueError("TaskPlan 的时间范围必须是字符串")
    time_intent = plan.get("time_intent")
    expected_intent_fields = {
        "mode", "anchor_date", "window_value", "window_unit", "comparison",
    }
    if not isinstance(time_intent, dict) or set(time_intent) != expected_intent_fields:
        raise ValueError("TaskPlan 的 time_intent 字段不完整")
    if time_intent["mode"] not in TIME_MODES:
        raise ValueError("TaskPlan 使用了未知的时间意图")
    if time_intent["window_unit"] not in TIME_UNITS:
        raise ValueError("TaskPlan 使用了未知的时间单位")
    if time_intent["comparison"] not in TIME_COMPARISONS:
        raise ValueError("TaskPlan 使用了未知的时间比较口径")
    if (
        not isinstance(time_intent["window_value"], int)
        or isinstance(time_intent["window_value"], bool)
        or time_intent["window_value"] < 0
    ):
        raise ValueError("TaskPlan 的时间窗口必须是非负整数")
    try:
        date.fromisoformat(time_intent["anchor_date"])
    except (TypeError, ValueError) as exc:
        raise ValueError("TaskPlan 的 anchor_date 必须是有效日期") from exc

    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("TaskPlan 必须至少包含一个任务")

    task_ids: list[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("每个任务都必须是对象")
        task_id = task.get("id")
        agent = task.get("agent")
        goal = task.get("goal")
        dependencies = task.get("depends_on")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("任务 id 不能为空")
        if agent not in AGENT_ROLES:
            raise ValueError(f"任务 {task_id} 使用了未知 Agent：{agent}")
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError(f"任务 {task_id} 的 goal 不能为空")
        if not isinstance(dependencies, list) or not all(isinstance(item, str) for item in dependencies):
            raise ValueError(f"任务 {task_id} 的 depends_on 必须是字符串数组")
        if len(dependencies) != len(set(dependencies)):
            raise ValueError(f"任务 {task_id} 包含重复依赖")
        task_ids.append(task_id)

    if len(task_ids) != len(set(task_ids)):
        raise ValueError("任务 id 不能重复")

    known_ids = set(task_ids)
    for task in tasks:
        missing = set(task["depends_on"]) - known_ids
        if missing:
            raise ValueError(f"任务 {task['id']} 依赖了不存在的任务：{'、'.join(sorted(missing))}")

    # 逐步删除已满足的依赖；最后有剩余就说明存在环。
    remaining = {task["id"]: set(task["depends_on"]) for task in tasks}
    completed: set[str] = set()
    while remaining:
        ready = {task_id for task_id, dependencies in remaining.items() if dependencies <= completed}
        if not ready:
            raise ValueError("任务依赖存在循环，无法开始执行")
        completed.update(ready)
        for task_id in ready:
            del remaining[task_id]

    verification_tasks = [task for task in tasks if task["agent"] == "verification"]
    if len(verification_tasks) != 1:
        raise ValueError("TaskPlan 必须且只能包含一个 verification 任务")
    research_ids = {task["id"] for task in tasks if task["agent"] != "verification"}
    if not research_ids:
        raise ValueError("verification 之前必须至少有一个专业调查任务")
    verification_dependencies = set(verification_tasks[0]["depends_on"])
    if verification_dependencies != research_ids:
        raise ValueError("verification 必须依赖全部专业调查任务")

    if any(task["agent"] == "market" for task in tasks):
        if not time_range["start"] or not time_range["end"]:
            raise ValueError("包含 market 任务时必须提供明确的 start 和 end 日期")
        try:
            start_date = date.fromisoformat(time_range["start"])
            end_date = date.fromisoformat(time_range["end"])
        except ValueError as exc:
            raise ValueError("market 时间范围必须使用有效的 YYYY-MM-DD 日期") from exc
        if start_date > end_date:
            raise ValueError("market 时间范围的 start 不能晚于 end")
        if time_intent["mode"] == "unspecified":
            raise ValueError("包含 market 任务时不能使用 unspecified 时间意图")

    return plan
