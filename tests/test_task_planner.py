import copy
import json
import unittest
from datetime import date
from types import SimpleNamespace as NS

from gold_analyst.orchestration import create_task_plan, validate_task_plan
from gold_analyst.orchestration.planner import PLANNER_INSTRUCTIONS


def planner_client(
    agents,
    market="china_spot",
    start="2026-10-05",
    end="2026-10-05",
    mode=None,
    window_value=0,
    window_unit="none",
):
    resolved_mode = mode or ("date_range" if start != end else "exact_date")
    arguments = {
        "needs_market": "market" in agents,
        "needs_cause": "cause" in agents,
        "market": market,
        "time_intent": {
            "mode": resolved_mode,
            "anchor_date": end,
            "start": start,
            "end": end,
            "window_value": window_value,
            "window_unit": window_unit,
        },
    }
    call = NS(
        type="function_call",
        name="submit_task_plan",
        arguments=json.dumps(arguments, ensure_ascii=False),
        call_id="plan_1",
    )
    response = NS(output=[call], usage=NS(input_tokens=12, output_tokens=8), status="completed")

    class FakeClient:
        def __init__(self):
            self.responses = self
            self.requests = []

        def create(self, **kwargs):
            self.requests.append(copy.deepcopy(kwargs))
            return response

    return FakeClient()


class TaskPlannerTests(unittest.TestCase):
    def test_model_plan_is_converted_to_task_plan(self):
        client = planner_client(["market"], start="2026-09-01", end="2026-10-01")

        plan = create_task_plan("2026年10月1日黄金价格是多少", client)

        self.assertEqual([item["agent"] for item in plan["tasks"]], ["market", "verification"])
        self.assertEqual(plan["question"], "2026年10月1日黄金价格是多少")
        self.assertEqual(plan["time_range"], {"start": "2026-09-01", "end": "2026-10-01"})
        self.assertEqual(plan["time_intent"]["mode"], "date_range")
        self.assertEqual(client.requests[0]["tool_choice"], {
            "type": "function", "name": "submit_task_plan",
        })

    def test_compound_plan_can_run_two_specialists_before_verifier(self):
        plan = create_task_plan("上涨了多少，为什么", planner_client(["market", "cause"]))
        self.assertEqual([item["agent"] for item in plan["tasks"]], [
            "market", "cause", "verification",
        ])

    def test_model_cannot_remove_or_duplicate_verification_task(self):
        plan = create_task_plan("黄金价格是多少", planner_client(["market"]))
        verification = [item for item in plan["tasks"] if item["agent"] == "verification"]
        self.assertEqual(len(verification), 1)
        self.assertEqual(verification[0]["depends_on"], ["market"])

    def test_plan_without_a_research_agent_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "至少有一个专业调查任务"):
            create_task_plan("调查黄金", planner_client([]))

    def test_empty_question_is_rejected_before_model_call(self):
        with self.assertRaisesRegex(ValueError, "不能为空"):
            create_task_plan("  ", planner_client([]))

    def test_prompt_distinguishes_price_amount_from_price_causes(self):
        self.assertIn("价格是多少", PLANNER_INSTRUCTIONS)
        self.assertIn("上涨了多少", PLANNER_INSTRUCTIONS)
        self.assertIn("不得因为问题中出现“上涨”就自动选择 cause", PLANNER_INSTRUCTIONS)

    def test_recent_is_resolved_to_current_date_instead_of_model_guess(self):
        plan = create_task_plan(
            "黄金价格最近如何变化",
            planner_client(["market"], start="2024-06-10", end="2024-06-10"),
            today=date(2026, 10, 5),
        )
        self.assertEqual(plan["time_range"], {"start": "2026-10-05", "end": "2026-10-05"})
        self.assertEqual(plan["time_intent"]["mode"], "latest_available")
        self.assertEqual(
            plan["tasks"][0]["goal"],
            "查询黄金价格变化：截至 2026-10-05 的最近有效交易日，并与前一有效交易日比较",
        )

    def test_month_and_day_without_year_use_current_year(self):
        client = planner_client(["market", "cause"], start="2023-10-05", end="2023-10-05")
        plan = create_task_plan("10月5日黄金价格为什么变化", client, today=date(2026, 10, 5))

        self.assertEqual(plan["time_range"], {"start": "2026-10-05", "end": "2026-10-05"})
        self.assertEqual(plan["time_intent"]["mode"], "exact_date")
        self.assertIn("当前日期：2026-10-05", client.requests[0]["input"][0]["content"])

    def test_market_plan_cannot_keep_empty_dates(self):
        with self.assertRaisesRegex(ValueError, "anchor_date"):
            create_task_plan(
                "黄金某天的价格",
                planner_client(["market"], start="", end=""),
                today=date(2026, 10, 5),
            )

    def test_rolling_window_is_resolved_by_program(self):
        plan = create_task_plan(
            "查看最近10天黄金价格变化",
            planner_client(
                ["market"], mode="rolling_window", window_value=10, window_unit="day",
            ),
            today=date(2026, 10, 5),
        )
        self.assertEqual(plan["time_intent"]["mode"], "rolling_window")
        self.assertEqual(plan["time_range"], {"start": "2026-09-26", "end": "2026-10-05"})

    def test_duplicate_task_id_is_still_rejected_by_validator(self):
        plan = create_task_plan("黄金价格", planner_client(["market"]))
        plan["tasks"][1]["id"] = "market"
        with self.assertRaisesRegex(ValueError, "id 不能重复"):
            validate_task_plan(plan)


if __name__ == "__main__":
    unittest.main()
