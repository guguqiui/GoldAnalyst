import unittest

from gold_analyst.context import ContextBuilder, MAX_EVIDENCE_TEXT_CHARS
from gold_analyst.server import new_run
from gold_analyst.tools import ToolContext


class ContextBuilderTests(unittest.TestCase):
    def test_model_gets_compact_evidence_while_tools_keep_full_copy(self):
        parent = new_run("multi", "调查黄金", "source_first")
        parent["plan"] = {
            "market": "china_spot",
            "time_intent": {
                "mode": "exact_date", "anchor_date": "2026-10-05",
                "window_value": 0, "window_unit": "none",
                "comparison": "previous_trading_day",
            },
            "time_range": {"start": "2026-10-05", "end": "2026-10-05"},
        }
        task = {
            "id": "verification", "agent": "verification",
            "goal": "核验", "depends_on": ["cause"],
        }
        findings = [{
            "task_id": "cause", "agent": "cause", "status": "supported",
            "summary": "发现", "facts": [], "evidence_ids": ["E1", "E9"],
            "unresolved": [],
        }]
        full_text = "A" * (MAX_EVIDENCE_TEXT_CHARS + 2_000)
        context = ContextBuilder().build_specialist_context(
            parent, task, findings, [{
                "id": "E1", "title": "来源", "url": "https://example.com/a",
                "kind": "source", "text": full_text,
            }],
        )

        compact = context.payload["dependency_evidence"][0]
        self.assertLess(len(compact["text"]), len(full_text))
        self.assertIn("get_evidence", compact["text"])
        self.assertEqual(context.full_evidence[0]["text"], full_text)
        self.assertEqual(context.manifest["truncated_evidence_ids"], ["E1"])
        self.assertEqual(context.manifest["missing_evidence_ids"], ["E9"])

    def test_serialized_dependency_url_is_not_treated_as_user_url(self):
        run = new_run(
            "multi", '{"dependency_evidence":[{"url":"https://example.com/source"}]}',
            "source_first",
        )
        run["original_question"] = "调查黄金上涨原因"
        context = ToolContext(run=run, emit=lambda *args: None)

        self.assertFalse(context.is_target_url("https://example.com/source"))
        run["original_question"] = "请核验 https://example.com/source"
        self.assertTrue(context.is_target_url("https://example.com/source"))

    def test_specialist_context_includes_session_history(self):
        parent = new_run("multi", "第二个原因有什么证据？", "source_first")
        history = [
            {"role": "user", "content": "九月金价为什么下跌？"},
            {"role": "assistant", "content": "主要有三个原因。"},
        ]
        parent["conversation_history"] = history
        parent["plan"] = {}
        task = {"id": "cause", "agent": "cause", "goal": "继续调查", "depends_on": []}

        context = ContextBuilder().build_specialist_context(parent, task, [], [])

        self.assertEqual(context.payload["conversation_history"], history)


if __name__ == "__main__":
    unittest.main()
