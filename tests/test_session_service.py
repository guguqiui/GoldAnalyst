import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gold_analyst import server
from gold_analyst.session import AttemptStatus, Message, SessionService, SessionStore, compact_history


class SessionServiceTests(unittest.TestCase):
    def service(self, directory: str) -> SessionService:
        return SessionService(SessionStore(Path(directory) / "sessions"))

    def test_initial_run_creates_user_message_and_pending_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            run = service.create_initial_run("multi", "分析九月金价", "source_first")

            session = service.store.get_session(run["session_id"])
            attempt = service.store.get_attempt(run["session_id"], run["attempt_id"])
            messages = service.store.get_messages(run["session_id"])
            self.assertEqual(session.last_attempt_id, run["attempt_id"])
            self.assertEqual(attempt.status, AttemptStatus.PENDING)
            self.assertEqual(attempt.run_id, run["id"])
            self.assertEqual([(item.role, item.content) for item in messages], [
                ("user", "分析九月金价"),
            ])

    def test_completed_run_updates_attempt_and_appends_compact_reply(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            run = service.create_initial_run("multi", "分析九月金价", "source_first")
            service.mark_running(run)
            run["status"] = "completed"
            run["report"] = {
                "title": "九月金价报告",
                "summary": "九月金价下跌。",
                "claims": [{"statement": "月内下跌", "verdict": "有证据支持"}],
                "unresolved": [],
            }
            service.finish_run(run)

            attempt = service.store.get_attempt(run["session_id"], run["attempt_id"])
            messages = service.store.get_messages(run["session_id"])
            self.assertEqual(attempt.status, AttemptStatus.COMPLETED)
            self.assertIsNotNone(attempt.started_at)
            self.assertIsNotNone(attempt.completed_at)
            self.assertEqual([item.role for item in messages], ["user", "assistant"])
            self.assertIn("九月金价下跌", messages[1].content)
            self.assertNotIn("run_id", messages[1].content)
            self.assertNotIn("evidence", messages[1].content)

    def test_failed_run_is_saved_as_failed_assistant_message(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            run = service.create_initial_run("multi", "失败调查", "source_first")
            service.mark_running(run)
            run["status"] = "failed"
            run["error"] = "测试错误"
            service.finish_run(run)

            attempt = service.store.get_attempt(run["session_id"], run["attempt_id"])
            messages = service.store.get_messages(run["session_id"])
            self.assertEqual(attempt.status, AttemptStatus.FAILED)
            self.assertIn("测试错误", messages[-1].content)

    def test_server_execute_records_the_assistant_message(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            run = service.create_initial_run("demo", "教学调查", "source_first")

            def complete_demo(active_run, emit):
                active_run["report"] = {
                    "title": "教学报告", "summary": "演示完成。",
                    "claims": [], "unresolved": [],
                }

            with (
                patch.object(server, "SESSION_SERVICE", service),
                patch.object(server, "demonstrate", complete_demo),
                patch.object(server, "save_run"),
            ):
                server.execute(run)

            messages = service.store.get_messages(run["session_id"])
            self.assertEqual(run["status"], "completed")
            self.assertEqual([item.role for item in messages], ["user", "assistant"])
            self.assertIn("演示完成", messages[-1].content)

    def test_followup_run_links_parent_and_carries_visible_history(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            first = service.create_initial_run("multi", "九月金价为什么下跌？", "source_first")
            service.mark_running(first)
            first["status"] = "completed"
            first["report"] = {
                "title": "原因报告", "summary": "主要有三个原因。",
                "claims": [{"statement": "美元走强", "verdict": "有证据支持"}],
                "unresolved": [],
            }
            service.finish_run(first)

            followup = service.create_followup_run(first["session_id"], "第二个原因是什么？")

            self.assertEqual(followup["parent_run_id"], first["id"])
            self.assertEqual([item["role"] for item in followup["conversation_history"]], [
                "user", "assistant",
            ])
            self.assertIn("主要有三个原因", followup["conversation_history"][1]["content"])
            attempt = service.store.get_attempt(followup["session_id"], followup["attempt_id"])
            self.assertEqual(attempt.parent_attempt_id, first["attempt_id"])

    def test_followup_waits_for_the_previous_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            run = service.create_initial_run("multi", "第一次调查", "source_first")
            with self.assertRaisesRegex(ValueError, "仍在运行"):
                service.create_followup_run(run["session_id"], "继续追问")

    def test_history_keeps_recent_content_with_a_character_budget(self):
        messages = [
            Message("a" * 16, "user", "旧" * 8_000),
            Message("a" * 16, "assistant", "新" * 8_000),
        ]
        history = compact_history(messages)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["content"], "新" * 8_000)

        oversized = compact_history([
            Message("a" * 16, "assistant", "超" * 15_000),
        ])
        self.assertEqual(len(oversized), 1)
        self.assertTrue(oversized[0]["content"].startswith("超"))
        self.assertIn("已截断", oversized[0]["content"])
