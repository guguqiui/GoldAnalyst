"""Multi-Agent 之间传递的结构化数据协议。"""
from typing import Literal, TypedDict


AgentRole = Literal["market", "cause", "verification"]
FindingStatus = Literal["supported", "partial", "contradicted", "insufficient"]


class TimeRange(TypedDict):
    start: str
    end: str


class PlanTask(TypedDict):
    id: str
    agent: AgentRole
    goal: str
    depends_on: list[str]


class TaskPlan(TypedDict):
    """编排器生成的任务图；depends_on 决定并行和先后顺序。"""

    question: str
    market: str
    time_range: TimeRange
    tasks: list[PlanTask]


class FindingFact(TypedDict):
    """使用字符串保存值和单位，避免金额、日期被浮点数悄悄改写。"""

    name: str
    value: str
    unit: str
    note: str


class Finding(TypedDict):
    """专业 Agent 的产物；它不是面向用户的最终报告。"""

    task_id: str
    agent: AgentRole
    status: FindingStatus
    summary: str
    facts: list[FindingFact]
    evidence_ids: list[str]
    unresolved: list[str]


class VerificationResult(TypedDict):
    """核验 Agent 对前序 Finding 的接受、拒绝与冲突记录。"""

    status: FindingStatus
    accepted_task_ids: list[str]
    rejected_task_ids: list[str]
    independent_source_count: int
    conflicts: list[str]
    unresolved: list[str]
