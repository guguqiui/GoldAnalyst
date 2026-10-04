import unittest

from gold_analyst.orchestration import create_task_plan, validate_task_plan


class TaskPlannerTests(unittest.TestCase):
    def roles(self, question):
        return [task["agent"] for task in create_task_plan(question)["tasks"]]

    def test_amount_question_selects_market_then_verification(self):
        plan = create_task_plan("最近黄金上涨了多少")
        self.assertEqual(self.roles(plan["question"]), ["market", "verification"])
        self.assertEqual(plan["tasks"][-1]["depends_on"], ["market"])

    def test_reason_question_selects_cause_then_verification(self):
        plan = create_task_plan("最近黄金上涨的主要原因是什么")
        self.assertEqual([task["agent"] for task in plan["tasks"]], ["cause", "verification"])
        self.assertEqual(plan["tasks"][-1]["depends_on"], ["cause"])

    def test_compound_question_runs_independent_specialists_before_verifier(self):
        plan = create_task_plan("最近黄金上涨了多少，为什么上涨")
        self.assertEqual([task["agent"] for task in plan["tasks"]], ["market", "cause", "verification"])
        self.assertEqual(plan["tasks"][0]["depends_on"], [])
        self.assertEqual(plan["tasks"][1]["depends_on"], [])
        self.assertEqual(plan["tasks"][2]["depends_on"], ["market", "cause"])

    def test_market_and_explicit_dates_are_preserved(self):
        plan = create_task_plan("计算 2026-09-01 到 2026-10-01 上海金涨幅")
        self.assertEqual(plan["market"], "china_spot")
        self.assertEqual(plan["time_range"], {"start": "2026-09-01", "end": "2026-10-01"})

    def test_relative_time_is_not_silently_invented(self):
        plan = create_task_plan("最近黄金上涨了多少")
        self.assertEqual(plan["time_range"], {"start": "", "end": ""})

    def test_unknown_open_question_defaults_to_cause_research(self):
        self.assertEqual(self.roles("调查一下黄金市场"), ["cause", "verification"])

    def test_empty_question_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "不能为空"):
            create_task_plan("  ")

    def test_generated_plan_passes_validation(self):
        plan = create_task_plan("最近黄金上涨了多少，为什么上涨")
        self.assertIs(validate_task_plan(plan), plan)

    def test_duplicate_task_id_is_rejected(self):
        plan = create_task_plan("最近黄金上涨了多少")
        plan["tasks"][1]["id"] = "market"
        with self.assertRaisesRegex(ValueError, "id 不能重复"):
            validate_task_plan(plan)

    def test_missing_dependency_is_rejected(self):
        plan = create_task_plan("最近黄金上涨了多少")
        plan["tasks"][-1]["depends_on"] = ["missing"]
        with self.assertRaisesRegex(ValueError, "不存在的任务"):
            validate_task_plan(plan)

    def test_dependency_cycle_is_rejected(self):
        plan = create_task_plan("最近黄金上涨了多少")
        plan["tasks"][0]["depends_on"] = ["verification"]
        with self.assertRaisesRegex(ValueError, "存在循环"):
            validate_task_plan(plan)

    def test_verifier_must_depend_on_every_research_task(self):
        plan = create_task_plan("最近黄金上涨了多少，为什么上涨")
        plan["tasks"][-1]["depends_on"] = ["market"]
        with self.assertRaisesRegex(ValueError, "依赖全部"):
            validate_task_plan(plan)
