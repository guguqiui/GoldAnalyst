import unittest

from gold_analyst.server import new_run
from gold_analyst.tools import GetEvidenceTool, ToolContext


class GetEvidenceToolTests(unittest.TestCase):
    def tool(self):
        run = new_run("multi", "核验证据", "source_first")
        run["evidence"] = [{
            "id": "E1",
            "title": "完整来源",
            "url": "https://example.com/a",
            "text": "金" * 25_000,
            "kind": "source",
        }]
        return GetEvidenceTool(ToolContext(run=run, emit=lambda *args: None)), run

    def test_returns_full_local_evidence_without_mutating_store(self):
        tool, run = self.tool()
        result = tool.execute("E1")
        self.assertEqual(len(result["text"]), 25_000)
        result["text"] = "changed"
        self.assertEqual(len(run["evidence"][0]["text"]), 25_000)
        self.assertTrue(tool.is_readonly)
        self.assertTrue(tool.repeatable)
        self.assertTrue(tool.deterministic)

    def test_rejects_unknown_evidence(self):
        tool, _ = self.tool()
        with self.assertRaisesRegex(ValueError, "不存在证据"):
            tool.execute("E99")
