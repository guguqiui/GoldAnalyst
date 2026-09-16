"""项目内部共享的数据结构；避免各模块把运行状态当作未知字典。"""
from dataclasses import dataclass
from typing import TypedDict


@dataclass(frozen=True)
class ResearchBudget:
    """一次研究的资源上限；V2 可把这些参数作为策略基因的一部分。"""

    rounds: int = 6
    tool_calls: int = 12
    parallel_tools: int = 4
    duration_seconds: int = 240

    def __post_init__(self) -> None:
        if min(self.rounds, self.tool_calls, self.parallel_tools, self.duration_seconds) < 1:
            raise ValueError("研究预算参数必须全部为正整数")


DEFAULT_RESEARCH_BUDGET = ResearchBudget()


class Usage(TypedDict):
    input_tokens: int
    output_tokens: int
    tool_calls: int
    search_requests: int


class RunState(TypedDict, total=False):
    id: str
    mode: str
    input: str
    strategy: str
    strategy_version: str
    model: str
    created_at: str
    status: str
    events: list[dict[str, object]]
    evidence: list[dict[str, object]]
    usage: Usage
    report: dict[str, object]
    review_status: str
    notice: str
    error: str
    save_error: str
    duration_seconds: float
