import unittest
from unittest.mock import patch

from gold_analyst.orchestration.workflow import investigate_multi_workflow
from gold_analyst.server import new_run


class MultiAgentWorkflowTests(unittest.TestCase):
    @patch("gold_analyst.orchestration.workflow.generate_final_report")
    @patch("gold_analyst.orchestration.workflow.run_task_plan")
    def test_workflow_connects_plan_runner_and_judge_in_order(self, fake_runner, fake_judge):
        steps = []

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


if __name__ == "__main__":
    unittest.main()
