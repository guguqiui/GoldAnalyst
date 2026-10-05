import unittest
from unittest.mock import patch

from gold_analyst.orchestration.planner import PlanningResult
from gold_analyst.orchestration.workflow import investigate_multi_workflow
from gold_analyst.providers.llm import ModelResponse
from gold_analyst.server import new_run


class MultiAgentWorkflowTests(unittest.TestCase):
    @patch("gold_analyst.orchestration.workflow.generate_task_plan")
    @patch("gold_analyst.orchestration.workflow.generate_final_report")
    @patch("gold_analyst.orchestration.workflow.run_task_plan")
    def test_workflow_connects_plan_runner_and_judge_in_order(
        self, fake_runner, fake_judge, fake_planner,
    ):
        steps = []
        plan = {
            "question": "最近黄金为什么上涨",
            "market": "china_spot",
            "time_intent": {
                "mode": "unspecified", "anchor_date": "2026-10-05",
                "window_value": 0, "window_unit": "none", "comparison": "none",
            },
            "time_range": {"start": "", "end": ""},
            "tasks": [
                {"id": "cause", "agent": "cause", "goal": "调查原因", "depends_on": []},
                {"id": "verification", "agent": "verification", "goal": "独立核验", "depends_on": ["cause"]},
            ],
        }
        fake_planner.return_value = PlanningResult(
            plan=plan,
            response=ModelResponse(input_tokens=12, output_tokens=8),
            request={"input": "test"},
            model="test-model",
        )

        def run_tasks(run, plan, emit, client):
            steps.append("runner")
            self.assertEqual(plan, run["plan"])
            run["findings"] = [{"task_id": "cause"}]
            run["verification_result"] = {"status": "insufficient", "fact_results": []}
            return run

        def judge(run, emit, client):
            steps.append("judge")
            self.assertIn("verification_result", run)
            run["report"] = {"title": "最终报告"}
            return run

        fake_runner.side_effect = run_tasks
        fake_judge.side_effect = judge
        run = new_run("multi", "最近黄金为什么上涨", "source_first")
        events = []

        result = investigate_multi_workflow(run, lambda *args: events.append(args), object())

        self.assertEqual(steps, ["runner", "judge"])
        self.assertEqual(result["report"]["title"], "最终报告")
        self.assertEqual([event[0] for event in events], ["规划 Agent", "规划结果"])
        self.assertEqual([task["agent"] for task in run["plan"]["tasks"]], ["cause", "verification"])
        self.assertEqual(run["usage"]["input_tokens"], 12)
        self.assertEqual(run["usage"]["output_tokens"], 8)

    @patch("gold_analyst.orchestration.workflow.save_llm_turn", return_value=".local/messages/001.json")
    @patch("gold_analyst.orchestration.workflow.generate_task_plan")
    def test_invalid_plan_is_saved_before_validation_error(self, fake_planner, fake_save):
        fake_planner.return_value = PlanningResult(
            plan={
                "question": "调查黄金",
                "market": "china_spot",
                "time_intent": {
                    "mode": "unspecified", "anchor_date": "2026-10-05",
                    "window_value": 0, "window_unit": "none", "comparison": "none",
                },
                "time_range": {"start": "", "end": ""},
                "tasks": [{
                    "id": "verification", "agent": "verification",
                    "goal": "独立核验", "depends_on": [],
                }],
            },
            response=ModelResponse(input_tokens=12, output_tokens=8),
            request={"input": "test"},
            model="test-model",
        )
        run = new_run("multi", "调查黄金", "source_first")

        with self.assertRaisesRegex(ValueError, "至少有一个专业调查任务"):
            investigate_multi_workflow(run, lambda *args: None)

        fake_save.assert_called_once()
        self.assertEqual(run["message_files"], [".local/messages/001.json"])


if __name__ == "__main__":
    unittest.main()
