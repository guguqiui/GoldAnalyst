"""使用确定性规则把用户问题转换成专业 Agent 任务图。"""
import re

from ..schemas import AgentRole, PlanTask, TaskPlan, TimeRange
from ..sources.router import select_universes


MARKET_PATTERNS = (
    "涨了多少",
    "跌了多少",
    "上涨多少",
    "下跌多少",
    "涨幅",
    "跌幅",
    "价格变化",
    "价格变动",
    "收益率",
    "起止价格",
)

CAUSE_PATTERNS = (
    "为什么",
    "原因",
    "驱动",
    "因素",
    "影响",
    "背景",
)


def _time_range(question: str) -> TimeRange:
    """只提取用户明确写出的 ISO 日期，不替用户猜测“最近”的范围。"""
    dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", question)
    if not dates:
        return {"start": "", "end": ""}
    if len(dates) == 1:
        return {"start": dates[0], "end": dates[0]}
    return {"start": dates[0], "end": dates[1]}


def _task(task_id: str, agent: AgentRole, goal: str, depends_on: list[str]) -> PlanTask:
    return {
        "id": task_id,
        "agent": agent,
        "goal": goal,
        "depends_on": depends_on,
    }


def create_task_plan(question: str) -> TaskPlan:
    """选择必要专家；专业任务可并行，核验任务等待所有专业发现。"""
    if not isinstance(question, str) or not question.strip():
        raise ValueError("调查问题不能为空")

    normalized = question.strip().casefold()
    needs_market = any(pattern in normalized for pattern in MARKET_PATTERNS)
    needs_cause = any(pattern in normalized for pattern in CAUSE_PATTERNS)

    # 无法识别的开放调查先交给来源研究员，不擅自要求行情计算。
    if not needs_market and not needs_cause:
        needs_cause = True

    market = select_universes(question)[0]
    time_range = _time_range(question)
    tasks: list[PlanTask] = []
    dependency_ids: list[str] = []

    if needs_market:
        tasks.append(_task(
            "market",
            "market",
            "确定黄金品种与时间范围，取得可核验的起止价格并计算变化",
            [],
        ))
        dependency_ids.append("market")

    if needs_cause:
        tasks.append(_task(
            "cause",
            "cause",
            "调查同一时间范围内的价格驱动因素，并为每项原因提供来源证据",
            [],
        ))
        dependency_ids.append("cause")

    tasks.append(_task(
        "verification",
        "verification",
        "独立核验前序发现的日期、品种、单位、计算、来源独立性与反面解释",
        dependency_ids.copy(),
    ))
    return {
        "question": question.strip(),
        "market": market,
        "time_range": time_range,
        "tasks": tasks,
    }
