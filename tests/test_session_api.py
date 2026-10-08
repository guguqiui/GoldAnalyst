import unittest
from unittest.mock import patch
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from gold_analyst import server
from gold_analyst.session import SessionService, SessionStore


class FakePool:
    def __init__(self):
        self.jobs = []

    def submit(self, function, run):
        self.jobs.append((function, run))


class SessionAPITests(unittest.TestCase):
    def test_session_snapshot_and_create_followup_run(self):
        with TemporaryDirectory() as directory:
            service = SessionService(SessionStore(Path(directory) / "sessions"))
            first = service.create_initial_run("multi", "九月金价为什么下跌？", "source_first")
            service.mark_running(first)
            first["status"] = "completed"
            first["report"] = {
                "title": "原因报告", "summary": "主要有三个原因。",
                "claims": [], "unresolved": [],
            }
            service.finish_run(first)
            pool = FakePool()
            old_service, old_pool, old_runs = server.SESSION_SERVICE, server.POOL, server.RUNS
            try:
                server.SESSION_SERVICE = service
                server.POOL = pool
                server.RUNS = {}
                snapshot = service.get_session_snapshot(first["session_id"])
                self.assertEqual(snapshot["session"]["session_id"], first["session_id"])
                self.assertEqual([item["role"] for item in snapshot["messages"]], [
                    "user", "assistant",
                ])

                with patch.object(
                    server, "public_settings", return_value={"model_ready": True},
                ):
                    run = server.create_followup_run(
                        first["session_id"], "第二个原因有什么证据？",
                    )

                self.assertEqual(run["session_id"], first["session_id"])
                self.assertEqual(run["parent_run_id"], first["id"])
                self.assertEqual(len(pool.jobs), 1)
                self.assertEqual(pool.jobs[0][1]["input"], "第二个原因有什么证据？")
            finally:
                server.SESSION_SERVICE = old_service
                server.POOL = old_pool
                server.RUNS = old_runs

    def test_delete_session_history_removes_session_and_run(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            service = SessionService(SessionStore(root / "sessions"))
            run = service.create_initial_run("multi", "调查金价", "source_first")
            service.mark_running(run)
            run["status"] = "completed"
            run["report"] = {"title": "报告", "summary": "完成", "claims": [], "unresolved": []}
            service.finish_run(run)
            run_dir = root / "runs" / run["id"]
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(json.dumps(run), encoding="utf-8")
            old_service, old_root, old_runs = server.SESSION_SERVICE, server.LOCAL_ROOT, server.RUNS
            try:
                server.SESSION_SERVICE = service
                server.LOCAL_ROOT = root
                server.RUNS = {run["id"]: run}
                self.assertEqual(server.delete_session_history(run["session_id"]), 1)
                self.assertIsNone(service.store.get_session(run["session_id"]))
                self.assertFalse(run_dir.exists())
                self.assertNotIn(run["id"], server.RUNS)
            finally:
                server.SESSION_SERVICE = old_service
                server.LOCAL_ROOT = old_root
                server.RUNS = old_runs


if __name__ == "__main__":
    unittest.main()
