"""无循环依赖的运行状态构造函数。"""
from uuid import uuid4

from .models import RunState
from .storage import now


def blank_run(mode: str, task: str, strategy: str, run_id: str | None = None) -> RunState:
    return {"id": run_id or uuid4().hex[:16], "mode": mode, "input": task, "strategy": strategy,
            "created_at": now(), "status": "running", "events": [], "evidence": [],
            "usage": {"input_tokens": 0, "output_tokens": 0, "tool_calls": 0, "search_requests": 0}}
