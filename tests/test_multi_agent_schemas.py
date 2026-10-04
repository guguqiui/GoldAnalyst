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
        self.assertEqual(result["facts"][0]["value"], "5.20")
        self.assertEqual(result["evidence_ids"], ["E1"])

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
