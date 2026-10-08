"""Session、Message 与 Attempt 的最小持久化模型。"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SessionStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class AttemptStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Session:
    """一段多轮对话；自身不保存大段消息正文。"""

    session_id: str = field(default_factory=lambda: uuid4().hex[:16])
    title: str = ""
    mode: str = "multi"
    strategy: str = "source_first"
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    last_attempt_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Session":
        values = dict(data)
        values["status"] = SessionStatus(str(values.get("status", "active")))
        return cls(**values)  # type: ignore[arg-type]


@dataclass
class Message:
    """Session 中一条用户或助手可见消息。"""

    session_id: str
    role: str
    content: str
    message_id: str = field(default_factory=lambda: uuid4().hex[:16])
    created_at: str = field(default_factory=_now)
    linked_attempt_id: str | None = None
    run_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Message":
        return cls(**data)  # type: ignore[arg-type]


@dataclass
class Attempt:
    """一条用户消息触发的一次调查运行。"""

    session_id: str
    prompt: str
    attempt_id: str = field(default_factory=lambda: uuid4().hex[:16])
    parent_attempt_id: str | None = None
    run_id: str | None = None
    status: AttemptStatus = AttemptStatus.PENDING
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    completed_at: str | None = None

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Attempt":
        values = dict(data)
        values["status"] = AttemptStatus(str(values.get("status", "pending")))
        return cls(**values)  # type: ignore[arg-type]

    def mark_running(self) -> None:
        self.status = AttemptStatus.RUNNING
        self.started_at = _now()

    def mark_finished(self, succeeded: bool) -> None:
        self.status = AttemptStatus.COMPLETED if succeeded else AttemptStatus.FAILED
        self.completed_at = _now()
