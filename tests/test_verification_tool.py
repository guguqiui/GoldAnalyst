import copy
import unittest

from gold_analyst.tools import SubmitVerificationTool, ToolContext


class SubmitVerificationToolTests(unittest.TestCase):
    def context(self):
        run = {
            "input": "核验黄金调查",
            "evidence": [{"id": "E1"}, {"id": "E2"}],
            "findings": [{
                "task_id": "cause",
                "facts": [
                    {"fact_id": "cause.fact_1", "name": "美元走弱"},
                    {"fact_id": "cause.fact_2", "name": "地缘风险"},
                ],
            }],
            "usage": {"input_tokens": 0, "output_tokens": 0, "tool_calls": 0, "search_requests": 0},
        }
        return ToolContext(run=run, emit=lambda *args: None)

    def result(self):
        return {
            "fact_results": [
                {
                    "fact_id": "cause.fact_1", "verdict": "supported", "reason": "有原始来源",
                    "supporting_evidence_ids": ["E1"], "contradicting_evidence_ids": [], "unresolved": [],
                },
                {
                    "fact_id": "cause.fact_2", "verdict": "insufficient", "reason": "缺少独立来源",
                    "supporting_evidence_ids": [], "contradicting_evidence_ids": [],
                    "unresolved": ["需要反向检索"],
                },
            ],
            "conflicts": [],
            "unresolved": ["cause.fact_2 待补证"],
        }

    def test_accepts_every_fact_once_and_derives_overall_status(self):
        result = SubmitVerificationTool(self.context()).execute(**self.result())
        self.assertEqual(result["status"], "partial")
        self.assertEqual([item["fact_id"] for item in result["fact_results"]], [
            "cause.fact_1", "cause.fact_2",
        ])

    def test_rejects_unknown_missing_or_duplicate_fact(self):
        unknown = self.result()
        unknown["fact_results"][1]["fact_id"] = "cause.fact_99"
        with self.assertRaisesRegex(ValueError, "不存在的 Fact"):
            SubmitVerificationTool(self.context()).execute(**unknown)

        missing = self.result()
        missing["fact_results"].pop()
        with self.assertRaisesRegex(ValueError, "遗漏了 Fact"):
            SubmitVerificationTool(self.context()).execute(**missing)

        duplicate = self.result()
        duplicate["fact_results"][1]["fact_id"] = "cause.fact_1"
        with self.assertRaisesRegex(ValueError, "不能重复核验"):
            SubmitVerificationTool(self.context()).execute(**duplicate)

    def test_rejects_unknown_or_overlapping_evidence(self):
        unknown = self.result()
        unknown["fact_results"][0]["supporting_evidence_ids"] = ["E99"]
        with self.assertRaisesRegex(ValueError, "不存在的证据"):
            SubmitVerificationTool(self.context()).execute(**unknown)

        overlap = copy.deepcopy(self.result())
        overlap["fact_results"][0]["contradicting_evidence_ids"] = ["E1"]
        with self.assertRaisesRegex(ValueError, "同时支持和反驳"):
            SubmitVerificationTool(self.context()).execute(**overlap)

    def test_supported_and_contradicted_require_matching_evidence(self):
        unsupported = self.result()
        unsupported["fact_results"][0]["supporting_evidence_ids"] = []
        with self.assertRaisesRegex(ValueError, "supported 时必须"):
            SubmitVerificationTool(self.context()).execute(**unsupported)

        contradicted = self.result()
        contradicted["fact_results"][0]["verdict"] = "contradicted"
        contradicted["fact_results"][0]["supporting_evidence_ids"] = []
        with self.assertRaisesRegex(ValueError, "contradicted 时必须"):
            SubmitVerificationTool(self.context()).execute(**contradicted)
