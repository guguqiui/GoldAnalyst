import copy
import json
import unittest
from types import SimpleNamespace as NS

from gold_analyst.agent_specs import MARKET_AGENT, VERIFICATION_AGENT
from gold_analyst.server import new_run
from gold_analyst.specialist import build_specialist_prompt, run_specialist


def call(name, arguments):
    return NS(type="function_call", name=name, arguments=json.dumps(arguments), call_id="call1")


class FakeClient:
    def __init__(self, responses):
        self.items = iter(responses)
        self.requests = []
        self.responses = self

    def create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        return next(self.items)


class SpecialistTests(unittest.TestCase):
    def test_market_specialist_uses_own_prompt_tools_and_finding_output(self):
        finding = {
            "task_id": "market",
            "agent": "market",
            "status": "insufficient",
            "summary": "尚缺少起止价格",
            "facts": [],
            "evidence_ids": [],
            "unresolved": ["需要明确日期"],
        }
        response = NS(
            output=[call("submit_finding", finding)],
            usage=NS(input_tokens=10, output_tokens=5),
            status="completed",
        )
        client = FakeClient([response])
        task = {"id": "market", "agent": "market", "goal": "计算涨幅", "depends_on": []}

        child = run_specialist(
            new_run("multi", "最近黄金上涨了多少", "source_first"),
            task,
            MARKET_AGENT,
            lambda *args: None,
            client,
        )

        self.assertEqual(child["finding"]["task_id"], "market")
        self.assertEqual(child["review_status"], "专业发现待独立核验")
        self.assertEqual(child["strategy"], "market")
        self.assertEqual(child["strategy_version"], "market-v1")
        request = client.requests[0]
        self.assertEqual({tool["name"] for tool in request["tools"]}, set(MARKET_AGENT.allowed_tools))
        self.assertNotIn("submit_report", {tool["name"] for tool in request["tools"]})
        self.assertIn(MARKET_AGENT.instruction, request["instructions"])

    def test_specialist_prompt_has_shared_and_role_specific_rules(self):
        prompt = build_specialist_prompt(MARKET_AGENT)
        self.assertIn("待核验数据", prompt)
        self.assertIn("calculate_change", prompt)

    def test_verifier_receives_findings_and_returns_verification_result(self):
        findings = [{
            "task_id": "market",
            "agent": "market",
            "status": "supported",
            "summary": "金价区间涨幅已计算",
            "facts": [{
                "fact_id": "market.fact_1", "name": "涨幅", "value": "5.2", "unit": "%", "note": "计算",
            }],
            "evidence_ids": ["E1"],
            "unresolved": [],
        }]
        submitted_verification = {
            "fact_results": [{
                "fact_id": "market.fact_1", "verdict": "supported", "reason": "已重新计算",
                "supporting_evidence_ids": ["E1"], "contradicting_evidence_ids": [], "unresolved": [],
            }],
            "conflicts": [],
            "unresolved": [],
        }
        response = NS(
            output=[call("submit_verification", submitted_verification)],
            usage=NS(input_tokens=8, output_tokens=4),
            status="completed",
        )
        client = FakeClient([response])
        task = {"id": "verification", "agent": "verification", "goal": "独立核验", "depends_on": ["market"]}

        child = run_specialist(
            new_run("multi", "最近黄金上涨了多少", "source_first"),
            task,
            VERIFICATION_AGENT,
            lambda *args: None,
            client,
            findings,
            [{"id": "E1", "kind": "calculation"}],
        )

        self.assertEqual(child["verification_result"]["status"], "passed")
        self.assertEqual(child["verification_result"]["fact_results"], submitted_verification["fact_results"])
        self.assertNotIn("finding", child)
        self.assertEqual(child["findings"], findings)
        request = client.requests[0]
        self.assertEqual({tool["name"] for tool in request["tools"]}, set(VERIFICATION_AGENT.allowed_tools))
        payload = json.loads(request["input"][0]["content"])
        self.assertEqual(payload["dependency_findings"], findings)

    def test_task_cannot_be_given_to_wrong_agent(self):
        task = {"id": "cause", "agent": "cause", "goal": "调查原因", "depends_on": []}
        with self.assertRaisesRegex(ValueError, "不能交给"):
            run_specialist(
                new_run("multi", "黄金为什么上涨", "source_first"),
                task,
                MARKET_AGENT,
                lambda *args: None,
                FakeClient([]),
            )
