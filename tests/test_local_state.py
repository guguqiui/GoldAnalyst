import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

from gold_analyst.local_state import save_llm_turn, save_local_run
from gold_analyst.storage import save_run


class LocalStateTests(unittest.TestCase):
    def test_saves_full_llm_turn_and_prepares_memory_folder(self):
        response = NS(
            history_items=[NS(type="function_call", name="search_sources", arguments='{"query":"黄金"}')],
            tool_calls=[NS(id="call1", name="search_sources", arguments={"query": "黄金"})],
            input_tokens=12,
            output_tokens=5,
            raw_response=NS(id="response_1", status="completed", output=[]),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("gold_analyst.local_state.LOCAL_ROOT", root / ".local"), \
                 patch("gold_analyst.local_state.ROOT", root):
                request = {"instructions": "调查", "input": [{"role": "user", "content": "黄金"}]}
                relative = save_llm_turn("run_1", 1, "第 1 轮", "test-model", request, response)
                payload = json.loads((root / relative).read_text(encoding="utf-8"))
        self.assertEqual(payload["label"], "第 1 轮")
        self.assertEqual(payload["message"]["agent"]["instructions"], "调查")
        self.assertEqual(payload["message"]["llm_raw_response"]["id"], "response_1")
        self.assertEqual(payload["message"]["llm_parsed"]["output"][0]["name"], "search_sources")
        self.assertEqual(payload["message"]["llm_parsed"]["tool_calls"][0]["arguments"]["query"], "黄金")
        self.assertEqual(payload["message"]["llm_parsed"]["usage"]["input_tokens"], 12)

    def test_rejects_run_id_that_could_escape_directory(self):
        with self.assertRaises(ValueError):
            save_llm_turn("../outside", 1, "test", "model", {}, NS())

    def test_report_is_saved_beside_messages(self):
        run = {"id": "run_2", "status": "completed", "report": {"title": "调查报告"}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("gold_analyst.local_state.LOCAL_ROOT", root / ".local"):
                save_local_run(run, "# 调查报告")
                run_dir = root / ".local" / "runs" / "run_2"
                self.assertEqual(json.loads((run_dir / "report.json").read_text())["title"], "调查报告")
                self.assertEqual((run_dir / "report.md").read_text(), "# 调查报告")
                self.assertEqual(json.loads((run_dir / "run.json").read_text())["status"], "completed")

    def test_normal_run_does_not_write_reports_folder(self):
        run = {"id": "run_3", "mode": "live", "created_at": "now", "report": {"title": "普通调查"}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("gold_analyst.local_state.LOCAL_ROOT", root / ".local"), \
                 patch("gold_analyst.storage.ROOT", root):
                path = save_run(run)
                self.assertEqual(path, root / ".local" / "runs" / "run_3" / "run.json")
                self.assertFalse((root / "reports").exists())

    def test_seed_run_is_also_written_to_reports_seed(self):
        run = {
            "id": "run_4", "mode": "live", "created_at": "now", "artifact_group": "seed",
            "report": {"title": "种子评测"},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("gold_analyst.local_state.LOCAL_ROOT", root / ".local"), \
                 patch("gold_analyst.storage.ROOT", root):
                path = save_run(run)
                self.assertEqual(path, root / "reports" / "seed" / "run_4.json")
                self.assertTrue(path.exists())
