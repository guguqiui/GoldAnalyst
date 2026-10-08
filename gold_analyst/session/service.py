"""把一次 Run 接到持久化 Session、Message 和 Attempt。"""

from datetime import datetime, timezone

from ..models import RunState
from ..server_state import blank_run
from .models import Attempt, AttemptStatus, Message, Session
from .store import SessionStore


MAX_HISTORY_CHARS = 12_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def format_assistant_message(run: RunState) -> str:
    """生成下一轮可读的紧凑回复，不复制网页正文和工具轨迹。"""
    if run.get("status") != "completed":
        return "调查未完成：" + str(run.get("error", "未知错误"))
    report = run.get("report") or {}
    lines = [
        str(report.get("title", "调查完成")),
        str(report.get("summary", "已完成调查，未生成摘要。")),
    ]
    claims = report.get("claims", [])
    if isinstance(claims, list) and claims:
        lines.append("核验结论：")
        for claim in claims:
            if isinstance(claim, dict):
                lines.append(
                    f"- {claim.get('statement', '')}：{claim.get('verdict', '证据不足')}"
                )
    unresolved = report.get("unresolved", [])
    if isinstance(unresolved, list) and unresolved:
        lines.append("仍需确认：" + "；".join(str(item) for item in unresolved))
    return "\n".join(lines)


def compact_history(messages: list[Message]) -> list[dict[str, str]]:
    """从最近消息向前保留历史；不把工具轨迹和证据正文放进下一轮。"""
    history = [
        {"role": message.role, "content": message.content}
        for message in messages
        if message.role in {"user", "assistant"} and message.content.strip()
    ]
    total = 0
    kept: list[dict[str, str]] = []
    for message in reversed(history):
        content = message["content"]
        remaining = MAX_HISTORY_CHARS - total
        if remaining <= 0:
            break
        if len(content) <= remaining:
            kept.append(message)
            total += len(content)
            continue
        if not kept:
            kept.append({**message, "content": content[:remaining] + "\n[…历史消息已截断…]"})
        break
    return list(reversed(kept))


class SessionService:
    """维护一次对话中 Run 与持久化记录之间的关系。"""

    def __init__(self, store: SessionStore | None = None) -> None:
        self.store = store or SessionStore()

    def create_initial_run(self, mode: str, prompt: str, strategy: str) -> RunState:
        session = self.store.create_session(Session(
            title=prompt.strip()[:80],
            mode=mode,
            strategy=strategy,
        ))
        run = blank_run(mode, prompt, strategy, session_id=session.session_id)
        user_message = Message(session.session_id, "user", prompt, run_id=run["id"])
        self.store.append_message(user_message)
        attempt = self.store.create_attempt(Attempt(
            session_id=session.session_id,
            prompt=prompt,
            run_id=run["id"],
        ))
        run["attempt_id"] = attempt.attempt_id
        session.last_attempt_id = attempt.attempt_id
        session.updated_at = _now()
        self.store.update_session(session)
        return run

    def create_followup_run(self, session_id: str, prompt: str) -> RunState:
        """在已有 Session 中创建新 Attempt，并携带裁剪后的可见历史。"""
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("追问内容不能为空")
        session = self.store.get_session(session_id)
        if session is None:
            raise ValueError("Session 不存在")
        previous = (
            self.store.get_attempt(session_id, session.last_attempt_id)
            if session.last_attempt_id
            else None
        )
        if previous is None:
            raise ValueError("Session 没有可以继续的上一轮调查")
        if previous.status in {AttemptStatus.PENDING, AttemptStatus.RUNNING}:
            raise ValueError("上一轮调查仍在运行，请等待完成后再追问")

        history = compact_history(self.store.get_messages(session_id))
        run = blank_run(
            session.mode,
            prompt.strip(),
            session.strategy,
            session_id=session_id,
            parent_run_id=previous.run_id,
        )
        run["conversation_history"] = history
        user_message = Message(session_id, "user", prompt.strip(), run_id=run["id"])
        self.store.append_message(user_message)
        attempt = self.store.create_attempt(Attempt(
            session_id=session_id,
            prompt=prompt.strip(),
            parent_attempt_id=previous.attempt_id,
            run_id=run["id"],
        ))
        run["attempt_id"] = attempt.attempt_id
        session.last_attempt_id = attempt.attempt_id
        session.updated_at = _now()
        self.store.update_session(session)
        return run

    def get_session_snapshot(self, session_id: str) -> dict[str, object] | None:
        """返回前端恢复对话所需的轻量数据，不内嵌完整 Run。"""
        session = self.store.get_session(session_id)
        if session is None:
            return None
        return {
            "session": session.to_dict(),
            "messages": [
                message.to_dict() for message in self.store.get_messages(session_id)
            ],
        }

    def list_sessions(self) -> list[dict[str, object]]:
        """返回侧栏所需的轻量 Session 列表。"""
        return [session.to_dict() for session in self.store.list_sessions()]

    def mark_running(self, run: RunState) -> None:
        attempt = self._attempt_for_run(run)
        if attempt is None:
            return
        attempt.mark_running()
        self.store.update_attempt(attempt)

    def finish_run(self, run: RunState) -> None:
        attempt = self._attempt_for_run(run)
        if attempt is None:
            return
        attempt.mark_finished(run.get("status") == "completed")
        self.store.update_attempt(attempt)
        self.store.append_message(Message(
            session_id=attempt.session_id,
            role="assistant",
            content=format_assistant_message(run),
            linked_attempt_id=attempt.attempt_id,
            run_id=run["id"],
        ))
        session = self.store.get_session(attempt.session_id)
        if session:
            session.updated_at = _now()
            self.store.update_session(session)

    def _attempt_for_run(self, run: RunState) -> Attempt | None:
        session_id = run.get("session_id")
        attempt_id = run.get("attempt_id")
        if not session_id or not attempt_id:
            return None
        return self.store.get_attempt(session_id, attempt_id)
