"""项目内部共享的数据结构；避免各模块把运行状态当作未知字典。"""
from typing import TypedDict


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
