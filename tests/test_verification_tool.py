import copy
import unittest

from gold_analyst.tools import SubmitVerificationTool, ToolContext


class SubmitVerificationToolTests(unittest.TestCase):
    def context(self):
        run = {
            "input": "核验黄金调查",
            "evidence": [
                {"id": "E1", "kind": "source", "url": "https://reuters.com/a"},
                {"id": "E2", "kind": "source", "url": "https://bloomberg.com/b"},
            ],
            "findings": [{
                "task_id": "cause",
                "agent": "cause",
                "facts": [
                    {"fact_id": "cause.fact_1", "name": "美元走弱"},
                    {"fact_id": "cause.fact_2", "name": "地缘风险"},
                ],
                "evidence_ids": ["E1"],
            }],
            "usage": {"input_tokens": 0, "output_tokens": 0, "tool_calls": 0, "search_requests": 0},
        }
        return ToolContext(run=run, emit=lambda *args: None)

    def result(self):
        return {
            "fact_results": [
                {
                    "fact_id": "cause.fact_1", "verdict": "supported", "reason": "有原始来源",
                    "supporting_evidence_ids": ["E1", "E2"],
                    "contradicting_evidence_ids": [], "unresolved": [],
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

    def test_cause_with_unreferenced_new_article_is_rejected_for_correction(self):
        missing_new_source = self.result()
        missing_new_source["fact_results"][0]["supporting_evidence_ids"] = ["E1"]
        with self.assertRaisesRegex(ValueError, "E2"):
            SubmitVerificationTool(self.context()).execute(**missing_new_source)

    def test_cause_without_any_new_article_is_downgraded_instead_of_retried(self):
        missing_new_source = self.result()
        missing_new_source["fact_results"][0]["supporting_evidence_ids"] = ["E1"]
        context = self.context()
        context.run["evidence"] = [context.run["evidence"][0]]
        result = SubmitVerificationTool(context).execute(**missing_new_source)
        self.assertEqual(result["fact_results"][0]["verdict"], "partial")
        self.assertIn("URL 不同的新文章", result["fact_results"][0]["reason"])

    def test_same_domain_different_article_can_corroborate_cause(self):
        same_domain = self.result()
        same_domain["fact_results"][0]["supporting_evidence_ids"] = ["E1", "E2"]
        context = self.context()
        context.run["evidence"][1]["url"] = "https://www.reuters.com/another"
        result = SubmitVerificationTool(context).execute(**same_domain)
        self.assertEqual(result["fact_results"][0]["verdict"], "supported")

    def test_same_canonical_article_does_not_count_as_corroboration(self):
        duplicate_article = self.result()
        duplicate_article["fact_results"][0]["supporting_evidence_ids"] = ["E1", "E2"]
        context = self.context()
        context.run["evidence"][1]["url"] = "https://www.reuters.com/a?utm_source=test"
        result = SubmitVerificationTool(context).execute(**duplicate_article)
        self.assertEqual(result["fact_results"][0]["verdict"], "partial")
        self.assertIn("URL 不同的新文章", result["fact_results"][0]["reason"])

    def test_market_supported_reuses_official_evidence(self):
        context = self.context()
        context.run["findings"] = [{
            "task_id": "market", "agent": "market", "evidence_ids": ["E1"],
            "facts": [{"fact_id": "market.fact_1", "name": "收盘价"}],
        }]
        context.run["evidence"] = [{
            "id": "E1", "kind": "official_market_data", "source_tier": 1,
            "url": "https://www.sge.com.cn/sjzx/mrhqsj",
        }]
        result = {
            "fact_results": [{
                "fact_id": "market.fact_1", "verdict": "supported", "reason": "官方数据完整",
                "supporting_evidence_ids": ["E1"], "contradicting_evidence_ids": [], "unresolved": [],
            }],
            "conflicts": [], "unresolved": [],
        }
        self.assertEqual(SubmitVerificationTool(context).execute(**result)["status"], "passed")
