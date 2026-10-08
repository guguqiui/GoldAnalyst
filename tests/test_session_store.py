import tempfile
import unittest
from pathlib import Path

from gold_analyst.server_state import blank_run
from gold_analyst.session import Attempt, AttemptStatus, Message, Session, SessionStore


class SessionStoreTests(unittest.TestCase):
    def test_session_messages_and_attempt_survive_store_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "sessions"
            store = SessionStore(root)
            session = store.create_session(Session(title="九月黄金", mode="multi"))
            first = Message(session.session_id, "user", "九月金价为什么变化？")
            store.append_message(first)
            attempt = Attempt(session.session_id, first.content)
            store.create_attempt(attempt)

            reloaded = SessionStore(root)
            self.assertEqual(reloaded.get_session(session.session_id), session)
            self.assertEqual(reloaded.get_messages(session.session_id), [first])
            self.assertEqual(reloaded.get_attempt(session.session_id, attempt.attempt_id), attempt)

    def test_attempt_can_link_to_previous_attempt_and_run(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory) / "sessions")
            session = store.create_session(Session(title="追问"))
            first = store.create_attempt(Attempt(session.session_id, "第一次调查", run_id="a" * 16))
            second = store.create_attempt(Attempt(
                session.session_id,
                "继续解释第二个原因",
                parent_attempt_id=first.attempt_id,
                run_id="b" * 16,
                status=AttemptStatus.RUNNING,
            ))

            loaded = store.get_attempt(session.session_id, second.attempt_id)
            self.assertEqual(loaded.parent_attempt_id, first.attempt_id)
            self.assertEqual(loaded.run_id, "b" * 16)
            self.assertEqual(loaded.status, AttemptStatus.RUNNING)

    def test_sessions_do_not_share_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory) / "sessions")
            first = store.create_session(Session(title="A"))
            second = store.create_session(Session(title="B"))
            store.append_message(Message(first.session_id, "user", "只属于 A"))

            self.assertEqual(len(store.get_messages(first.session_id)), 1)
            self.assertEqual(store.get_messages(second.session_id), [])

    def test_list_and_delete_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory) / "sessions")
            first = store.create_session(Session(title="较早", updated_at="2026-01-01T00:00:00+00:00"))
            second = store.create_session(Session(title="较新", updated_at="2026-01-02T00:00:00+00:00"))

            self.assertEqual([item.session_id for item in store.list_sessions()], [
                second.session_id, first.session_id,
            ])
            self.assertTrue(store.delete_session(first.session_id))
            self.assertIsNone(store.get_session(first.session_id))
            self.assertFalse(store.delete_session(first.session_id))

    def test_run_can_reference_session_and_parent_run(self):
        run = blank_run(
            "multi", "继续追问", "source_first",
            session_id="a" * 16,
            parent_run_id="b" * 16,
        )
        self.assertEqual(run["session_id"], "a" * 16)
        self.assertEqual(run["parent_run_id"], "b" * 16)
