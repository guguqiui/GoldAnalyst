"""以本地文件保存多轮 Session，不依赖数据库。"""

import json
import os
from pathlib import Path
import re
import shutil
from threading import Lock

from ..persistence.local import LOCAL_ROOT, _atomic_json
from .models import Attempt, Message, Session


ID_PATTERN = re.compile(r"[0-9a-f]{16}")


class SessionStore:
    """保存 Session 元数据、追加式消息和每次 Attempt。"""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or LOCAL_ROOT / "sessions"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    @staticmethod
    def _validate_id(value: str) -> str:
        if not ID_PATTERN.fullmatch(value):
            raise ValueError("无效的 Session 或 Attempt ID")
        return value

    def _session_dir(self, session_id: str) -> Path:
        return self.base_dir / self._validate_id(session_id)

    def create_session(self, session: Session) -> Session:
        directory = self._session_dir(session.session_id)
        with self._lock:
            if directory.exists():
                raise ValueError("Session 已存在")
            (directory / "attempts").mkdir(parents=True)
            _atomic_json(directory / "session.json", session.to_dict())
        return session

    def get_session(self, session_id: str) -> Session | None:
        path = self._session_dir(session_id) / "session.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Session 文件格式错误")
        return Session.from_dict(data)

    def update_session(self, session: Session) -> None:
        path = self._session_dir(session.session_id) / "session.json"
        if not path.exists():
            raise ValueError("Session 不存在")
        with self._lock:
            _atomic_json(path, session.to_dict())

    def list_sessions(self) -> list[Session]:
        """按最近更新时间返回可用 Session；损坏的记录不阻断整个列表。"""
        sessions: list[Session] = []
        for path in self.base_dir.glob("*/session.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    sessions.append(Session.from_dict(data))
            except (OSError, ValueError, TypeError):
                continue
        return sorted(sessions, key=lambda item: item.updated_at, reverse=True)

    def delete_session(self, session_id: str) -> bool:
        """删除一个 Session 的元数据、消息和 Attempt。"""
        directory = self._session_dir(session_id)
        if not directory.exists():
            return False
        with self._lock:
            shutil.rmtree(directory)
        return True

    def append_message(self, message: Message) -> None:
        path = self._session_dir(message.session_id) / "messages.jsonl"
        if not (path.parent / "session.json").exists():
            raise ValueError("Session 不存在")
        line = json.dumps(message.to_dict(), ensure_ascii=False)
        with self._lock, path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def get_messages(self, session_id: str) -> list[Message]:
        path = self._session_dir(session_id) / "messages.jsonl"
        if not path.exists():
            return []
        messages: list[Message] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            if not isinstance(data, dict):
                raise ValueError("Message 文件格式错误")
            messages.append(Message.from_dict(data))
        return messages

    def create_attempt(self, attempt: Attempt) -> Attempt:
        session_dir = self._session_dir(attempt.session_id)
        if not (session_dir / "session.json").exists():
            raise ValueError("Session 不存在")
        attempt_id = self._validate_id(attempt.attempt_id)
        path = session_dir / "attempts" / attempt_id / "attempt.json"
        with self._lock:
            if path.exists():
                raise ValueError("Attempt 已存在")
            _atomic_json(path, attempt.to_dict())
        return attempt

    def get_attempt(self, session_id: str, attempt_id: str) -> Attempt | None:
        path = self._session_dir(session_id) / "attempts" / self._validate_id(attempt_id) / "attempt.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Attempt 文件格式错误")
        return Attempt.from_dict(data)

    def update_attempt(self, attempt: Attempt) -> None:
        path = (
            self._session_dir(attempt.session_id)
            / "attempts"
            / self._validate_id(attempt.attempt_id)
            / "attempt.json"
        )
        if not path.exists():
            raise ValueError("Attempt 不存在")
        with self._lock:
            _atomic_json(path, attempt.to_dict())
