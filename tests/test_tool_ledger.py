import json
import unittest

from gold_analyst.runtime import ToolResultLedger
from gold_analyst.tools import tool_call_key


class ToolResultLedgerTests(unittest.TestCase):
    def test_keeps_full_result_and_call_identity(self):
        ledger = ToolResultLedger()
        arguments = {"url": "https://www.example.com/a?utm_source=test"}
        result = {"text": "金" * 25_000, "evidence_id": "E1"}

        key = ledger.record_success("call_1", "read_url", arguments, result)

        self.assertEqual(key, tool_call_key("read_url", {"url": "https://example.com/a"}))
        self.assertEqual(json.loads(ledger.result_for_key(key))["text"], result["text"])
        self.assertEqual(ledger.key_for_call("call_1"), key)
        self.assertEqual(ledger.result_count, 1)

    def test_only_a_recorded_success_is_considered_reusable(self):
        ledger = ToolResultLedger()
        arguments = {"current": "620", "previous": "610"}
        self.assertFalse(ledger.has_succeeded("calculate_change", arguments))

        ledger.record_success("call_1", "calculate_change", arguments, {"percent": "1.64"})

        self.assertTrue(ledger.has_succeeded("calculate_change", arguments))
        self.assertFalse(ledger.has_succeeded(
            "calculate_change", {"current": "621", "previous": "610"},
        ))

    def test_unserializable_result_is_not_recorded(self):
        ledger = ToolResultLedger()
        key = ledger.record_success("call_1", "read_url", {"url": "https://example.com"}, object())
        self.assertIsNone(key)
        self.assertEqual(ledger.result_count, 0)

    def test_two_identical_failures_block_until_success(self):
        ledger = ToolResultLedger()
        arguments = {"url": "https://example.com/a"}
        self.assertEqual(ledger.record_failure("read_url", arguments), 1)
        self.assertFalse(ledger.is_blocked("read_url", arguments))
        self.assertEqual(ledger.record_failure("read_url", arguments), 2)
        self.assertTrue(ledger.is_blocked("read_url", arguments))
        self.assertFalse(ledger.is_blocked("read_url", {"url": "https://example.com/b"}))

        ledger.record_success("call_3", "read_url", arguments, {"ok": True})

        self.assertEqual(ledger.failure_count("read_url", arguments), 0)
        self.assertFalse(ledger.is_blocked("read_url", arguments))

    def test_three_rounds_without_new_observation_are_stalled(self):
        ledger = ToolResultLedger()
        self.assertFalse(ledger.finish_round())
        self.assertFalse(ledger.finish_round())
        self.assertTrue(ledger.finish_round())

        ledger.record_success("call_1", "read_url", {"url": "https://example.com/a"}, {"text": "new"})
        self.assertFalse(ledger.finish_round())
        self.assertEqual(ledger.stalled_rounds, 0)

    def test_same_successful_result_is_not_a_new_observation_twice(self):
        ledger = ToolResultLedger()
        ledger.record_success("call_1", "search_sources", {"query": "黄金"}, {"sources": []})
        self.assertFalse(ledger.finish_round())
        ledger.record_success("call_2", "search_sources", {"query": "金价"}, {"sources": []})
        self.assertFalse(ledger.finish_round())
        self.assertEqual(ledger.stalled_rounds, 1)
