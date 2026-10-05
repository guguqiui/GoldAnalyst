import unittest

from gold_analyst.schemas import TaskPlan
from gold_analyst.tools import SubmitFindingTool, ToolContext


class MultiAgentSchemaTests(unittest.TestCase):
    def context(self):
        run = {
            "input": "调查黄金上涨",
            "evidence": [{"id": "E1", "title": "上金所"}],
            "usage": {"input_tokens": 0, "output_tokens": 0, "tool_calls": 0, "search_requests": 0},
        }
        return ToolContext(run=run, emit=lambda *args: None)

    def test_task_plan_expresses_dependencies(self):
        plan: TaskPlan = {
            "question": "最近黄金上涨了多少，为什么上涨",
            "market": "china_spot",
            "time_intent": {
                "mode": "date_range", "anchor_date": "2026-10-04",
                "window_value": 0, "window_unit": "none", "comparison": "range_start",
            },
            "time_range": {"start": "2026-09-04", "end": "2026-10-04"},
            "tasks": [
                {"id": "market", "agent": "market", "goal": "计算涨幅", "depends_on": []},
                {"id": "verify", "agent": "verification", "goal": "核验", "depends_on": ["market"]},
            ],
        }
        self.assertEqual(plan["tasks"][1]["depends_on"], ["market"])

    def test_submit_finding_returns_structured_specialist_output(self):
        result = SubmitFindingTool(self.context()).execute(
            task_id="market",
            agent="market",
            status="supported",
            summary="已核对涨幅",
            facts=[{"name": "涨幅", "value": "5.20", "unit": "%", "note": "使用起止价格计算"}],
            evidence_ids=["E1"],
            unresolved=[],
        )
        self.assertEqual(result["facts"][0]["fact_id"], "market.fact_1")
        self.assertEqual(result["facts"][0]["value"], "5.20")
        self.assertEqual(result["evidence_ids"], ["E1"])

    def test_fact_ids_are_assigned_in_stable_order(self):
        result = SubmitFindingTool(self.context()).execute(
            task_id="cause",
            agent="cause",
            status="supported",
            summary="两条原因",
            facts=[
                {"name": "美元", "value": "走弱", "unit": "", "note": "来源"},
                {"name": "利率", "value": "下降", "unit": "", "note": "来源"},
            ],
            evidence_ids=["E1"],
            unresolved=[],
        )
        self.assertEqual(
            [fact["fact_id"] for fact in result["facts"]],
            ["cause.fact_1", "cause.fact_2"],
        )

    def test_invalid_fact_shape_is_rejected_before_assigning_id(self):
        with self.assertRaisesRegex(ValueError, "name、value、unit 和 note"):
            SubmitFindingTool(self.context()).execute(
                task_id="cause",
                agent="cause",
                status="supported",
                summary="不完整事实",
                facts=[{"name": "美元", "value": "走弱", "unit": ""}],
                evidence_ids=["E1"],
                unresolved=[],
            )

    def test_submit_finding_rejects_unknown_evidence(self):
        with self.assertRaisesRegex(ValueError, "不存在的证据"):
            SubmitFindingTool(self.context()).execute(
                task_id="market",
                agent="market",
                status="supported",
                summary="错误引用",
                facts=[],
                evidence_ids=["E99"],
                unresolved=[],
            )

    def test_submit_finding_is_not_in_single_agent_registry_yet(self):
        from gold_analyst.server import new_run
        from gold_analyst.tools import create_tool_registry

        registry = create_tool_registry(new_run("live", "黄金", "source_first"), lambda *args: None)
        self.assertNotIn("submit_finding", registry.names)
