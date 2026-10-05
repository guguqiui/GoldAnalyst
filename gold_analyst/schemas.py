"""Multi-Agent 之间传递的结构化数据协议。"""
from typing import Literal, TypedDict


AgentRole = Literal["market", "cause", "verification"]
TimeMode = Literal[
    "exact_date", "date_range", "latest_available", "rolling_window",
    "year_to_date", "unspecified",
]
TimeUnit = Literal["none", "day", "week", "month", "year"]
TimeComparison = Literal["none", "previous_trading_day", "range_start"]
FindingStatus = Literal["supported", "partial", "contradicted", "insufficient"]
VerificationStatus = Literal["passed", "partial", "failed", "insufficient"]
FactVerdict = Literal["supported", "partial", "contradicted", "insufficient"]


class TimeRange(TypedDict):
    start: str
    end: str


class TimeIntent(TypedDict):
    """模型识别语义，程序填充日期与比较口径后的统一时间协议。"""

    mode: TimeMode
    anchor_date: str
    window_value: int
    window_unit: TimeUnit
    comparison: TimeComparison


class PlanTask(TypedDict):
    id: str
    agent: AgentRole
    goal: str
    depends_on: list[str]


class TaskPlan(TypedDict):
    """编排器生成的任务图；depends_on 决定并行和先后顺序。"""

    question: str
    market: str
    time_intent: TimeIntent
    time_range: TimeRange
    tasks: list[PlanTask]


class FindingFact(TypedDict):
    """使用字符串保存值和单位，避免金额、日期被浮点数悄悄改写。"""

    fact_id: str
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


class FactVerification(TypedDict):
    """核验 Agent 对一条 Fact 的判定与可追溯证据。"""

    fact_id: str
    verdict: FactVerdict
    reason: str
    supporting_evidence_ids: list[str]
    contradicting_evidence_ids: list[str]
    unresolved: list[str]


class VerificationResult(TypedDict):
    """核验 Agent 的逐事实结果；总体 status 由程序汇总。"""

    status: VerificationStatus
    fact_results: list[FactVerification]
    conflicts: list[str]
    unresolved: list[str]
