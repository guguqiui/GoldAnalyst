import json
import unittest

from gold_analyst.runtime import ToolResultLedger, microcompact, readable_success_keys


class ContextWindowTests(unittest.TestCase):
    def test_microcompact_marks_only_old_results_as_lost(self):
        ledger = ToolResultLedger()
        messages: list[object] = []
        keys = []
        for index in range(4):
            call_id = f"call_{index}"
            arguments = {"url": f"https://example.com/{index}"}
            key = ledger.record_success(call_id, "read_url", arguments, {"text": "x" * 100})
            keys.append(key)
            messages.append({
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps({"text": "x" * 100}),
            })

        lost = microcompact(messages, ledger, char_limit=1, keep_recent=1)

        self.assertEqual(lost, set(keys[:3]))
        self.assertEqual(readable_success_keys(messages, ledger), {keys[3]})
        self.assertTrue(all(ledger.is_compacted(key) for key in keys[:3]))
        self.assertFalse(ledger.is_compacted(keys[3]))
        self.assertIn("tool_result_compacted", messages[0]["output"])

    def test_no_compaction_below_limit(self):
        ledger = ToolResultLedger()
        key = ledger.record_success("call_1", "read_url", {"url": "https://example.com"}, {"ok": True})
        messages = [{"type": "function_call_output", "call_id": "call_1", "output": '{"ok": true}'}]
        self.assertEqual(microcompact(messages, ledger, char_limit=1000, keep_recent=1), set())
        self.assertEqual(readable_success_keys(messages, ledger), {key})
