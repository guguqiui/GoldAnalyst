import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from gold_analyst.evaluation import load_cases, match_case_for_run, save_evaluation, score_run
from gold_analyst.evaluation.runner import plan_jobs
from gold_analyst.evaluation.storage import default_evaluation_path


CASE_ID = "sge-2025-05-14-final-session-price"
SOURCE_URL = "https://www.sge.com.cn/sjzx/shanghaiAuAuto?start_date=2025-05-14&end_date=2025-05-14"


def correct_run():
    return {
        "report": {
            "title": "上海金午盘价格核验",
            "summary": "原说法混淆了第一轮价格与最终基准价。",
            "claims": [{
                "statement": "2025年5月14日SHAU午盘基准价为758.85元/克",
                "verdict": "有证据反驳",
                "reason": "758.85元/克是午盘第一轮价格；最终午盘基准价为758.55元/克。",
                "evidence_ids": ["E1"],
            }],
            "unresolved": [],
            "review": "日期、合约、场次、轮次和单位已经核对。",
        },
        "evidence": [{"id": "E1", "kind": "source", "url": SOURCE_URL}],
        "usage": {"tool_calls": 3, "search_requests": 1},
    }


class EvaluationLoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = load_cases()

    def test_all_reviewed_seed_cases_are_valid(self):
        self.assertEqual(len(self.cases), 7)
        self.assertEqual(len({case.id for case in self.cases}), 7)

    def test_machine_checks_allocate_exactly_100_points(self):
        for case in self.cases:
            self.assertEqual(sum(check["points"] for check in case.checks), 100, case.id)

    def test_case_is_matched_by_exact_normalized_task(self):
        case = next(case for case in self.cases if case.id == CASE_ID)
        run = {"input": "  " + case.task["input"] + "\n"}
        self.assertEqual(match_case_for_run(self.cases, run).id, CASE_ID)

    def test_unknown_freeform_task_is_not_matched(self):
        self.assertIsNone(match_case_for_run(self.cases, {"input": "预测明天的黄金价格"}))

    def test_batch_plan_skips_completed_case_and_strategy_pair(self):
        completed = {(self.cases[0].id, "source_first")}
        jobs = plan_jobs(self.cases, ["source_first"], completed)
        self.assertEqual(len(jobs), 6)
        self.assertNotIn((self.cases[0], "source_first"), jobs)

    def test_batch_plan_can_force_rerun(self):
        completed = {(case.id, "source_first") for case in self.cases}
        jobs = plan_jobs(self.cases, ["source_first"], completed, rerun=True)
        self.assertEqual(len(jobs), 7)


class DeterministicScorerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = next(case for case in load_cases() if case.id == CASE_ID)

    def test_correct_report_receives_full_score(self):
        result = score_run(self.case, correct_run())
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["critical_errors"], [])
        self.assertTrue(all(check["passed"] for check in result["checks"]))

    def test_first_round_as_final_is_capped(self):
        run = correct_run()
        claim = run["report"]["claims"][0]
        claim["verdict"] = "有证据支持"
        claim["reason"] = "上海黄金交易所页面显示SHAU午盘价格为758.85元/克。"
        result = score_run(self.case, run)
        self.assertLessEqual(result["score"], 49)
        self.assertEqual(result["score_cap"], 49)
        self.assertIn("FIRST_ROUND_AS_FINAL", result["critical_errors"])

    def test_unreferenced_primary_source_earns_no_evidence_points(self):
        run = correct_run()
        run["report"]["claims"][0]["evidence_ids"] = []
        result = score_run(self.case, run)
        evidence = result["dimensions"]["evidence_quality"]
        self.assertEqual(evidence, {"earned": 0, "possible": 25})

    def test_over_budget_run_loses_efficiency_points(self):
        run = copy.deepcopy(correct_run())
        run["usage"]["tool_calls"] = 13
        result = score_run(self.case, run)
        self.assertEqual(result["dimensions"]["efficiency"], {"earned": 0, "possible": 5})

    def test_search_configuration_failure_invalidates_run(self):
        run = correct_run()
        run["events"] = [{"stage": "工具受阻", "message": "联网搜索需要配置 OpenAI API Key"}]
        result = score_run(self.case, run)
        self.assertFalse(result["valid"])
        self.assertIsNone(result["score"])
        self.assertEqual(result["diagnostic_score"], 100)

    def test_score_record_is_saved_separately_from_run(self):
        run = correct_run()
        result = score_run(self.case, run)
        with TemporaryDirectory() as directory:
            run_path = Path(directory) / "run-123.json"
            run_path.write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
            output_path = Path(directory) / "score.json"
            saved_path = save_evaluation(self.case, run, result, run_path, output_path)
            saved = json.loads(saved_path.read_text(encoding="utf-8"))
            original = json.loads(run_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["score"], 100)
        self.assertEqual(saved["case_id"], CASE_ID)
        self.assertEqual(saved["evaluator_version"], "deterministic-1.0")
        self.assertEqual(original, run)

    def test_seed_report_maps_to_seed_results_folder(self):
        run_path = Path(__file__).resolve().parents[1] / "reports" / "seed" / "run-123.json"
        result_path = default_evaluation_path(run_path, self.case.id)
        expected = Path(__file__).resolve().parents[1] / "evals" / "results" / "seed"
        self.assertEqual(result_path.parent, expected)


if __name__ == "__main__":
    unittest.main()
