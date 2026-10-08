"""无循环依赖的运行状态构造函数。"""
from uuid import uuid4

from .models import RunState
from .persistence.reports import now


def blank_run(
    mode: str,
    task: str,
    strategy: str,
    run_id: str | None = None,
    session_id: str | None = None,
    parent_run_id: str | None = None,
) -> RunState:
    run: RunState = {
        "id": run_id or uuid4().hex[:16], "mode": mode, "input": task, "strategy": strategy,
        "created_at": now(), "status": "running", "events": [], "evidence": [],
        "usage": {"input_tokens": 0, "output_tokens": 0, "tool_calls": 0, "search_requests": 0},
    }
    if session_id:
        run["session_id"] = session_id
    if parent_run_id:
        run["parent_run_id"] = parent_run_id
    return run
