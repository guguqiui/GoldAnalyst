"""执行 TaskPlan 之前的结构校验。"""
from ..schemas import AgentRole, TaskPlan


AGENT_ROLES: set[AgentRole] = {"market", "cause", "verification"}


def validate_task_plan(plan: TaskPlan) -> TaskPlan:
    """拒绝无法安全调度的任务图；通过时原样返回计划。"""
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

    return plan
