import copy
import json
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

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

        parent = new_run("multi", "最近黄金上涨了多少", "source_first")
        parent["plan"] = {
            "market": "china_spot",
            "time_intent": {
                "mode": "latest_available", "anchor_date": "2026-10-05",
                "window_value": 0, "window_unit": "none",
                "comparison": "previous_trading_day",
            },
            "time_range": {"start": "2026-10-05", "end": "2026-10-05"},
        }
        child = run_specialist(
            parent,
            task,
            MARKET_AGENT,
            lambda *args: None,
            client,
        )

        self.assertEqual(child["finding"]["task_id"], "market")
        self.assertEqual(child["review_status"], "专业发现待独立核验")
        self.assertEqual(child["strategy"], "market")
        self.assertEqual(child["strategy_version"], "market-v2")
        request = client.requests[0]
        self.assertEqual({tool["name"] for tool in request["tools"]}, set(MARKET_AGENT.allowed_tools))
        self.assertNotIn("submit_report", {tool["name"] for tool in request["tools"]})
        self.assertIn(MARKET_AGENT.instruction, request["instructions"])
        payload = json.loads(request["input"][0]["content"])
        self.assertEqual(payload["market"], "china_spot")
        self.assertEqual(payload["time_intent"]["mode"], "latest_available")
        self.assertEqual(payload["time_range"], {"start": "2026-10-05", "end": "2026-10-05"})

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
            [{
                "id": "E1", "kind": "official_market_data", "source_tier": 1,
                "url": "https://www.sge.com.cn/data",
            }],
        )

        self.assertEqual(child["verification_result"]["status"], "passed")
        self.assertEqual(child["verification_result"]["fact_results"], submitted_verification["fact_results"])
        self.assertNotIn("finding", child)
        self.assertEqual(child["findings"], findings)
        self.assertEqual(child["context_manifest"]["evidence_ids"], ["E1"])
        self.assertEqual(child["excluded_source_urls"], ["https://www.sge.com.cn/data"])
        request = client.requests[0]
        self.assertEqual(
            {tool["name"] for tool in request["tools"]},
            {"get_evidence", "calculate_change", "submit_verification"},
        )
        self.assertNotIn("get_sge_data", {tool["name"] for tool in request["tools"]})
        payload = json.loads(request["input"][0]["content"])
        self.assertEqual(payload["dependency_findings"], findings)

    @patch("gold_analyst.tools.web.fetch")
    def test_verifier_can_correct_a_missing_new_evidence_citation(self, fake_fetch):
        original_url = "https://reuters.com/original"
        new_url = "https://bloomberg.com/corroboration"
        fake_fetch.return_value = (
            b"<html><h1>Gold</h1><article>This independent article contains enough text to verify the cause fact.</article></html>",
            "text/html",
            new_url,
        )
        findings = [{
            "task_id": "cause", "agent": "cause", "status": "supported", "summary": "美元走弱",
            "facts": [{
                "fact_id": "cause.fact_1", "name": "美元走弱", "value": "推动金价", "unit": "事件", "note": "原因",
            }],
            "evidence_ids": ["E1"], "unresolved": [],
        }]
        missing_citation = {
            "fact_results": [{
                "fact_id": "cause.fact_1", "verdict": "supported", "reason": "已有交叉证据",
                "supporting_evidence_ids": ["E1"], "contradicting_evidence_ids": [], "unresolved": [],
            }],
            "conflicts": [], "unresolved": [],
        }
        corrected = copy.deepcopy(missing_citation)
        corrected["fact_results"][0]["supporting_evidence_ids"] = ["E1", "E2"]
        responses = [
            NS(output=[call("read_url", {"url": new_url})], usage=NS(input_tokens=8, output_tokens=4), status="completed"),
            NS(output=[call("submit_verification", missing_citation)], usage=NS(input_tokens=8, output_tokens=4), status="completed"),
            NS(output=[call("submit_verification", corrected)], usage=NS(input_tokens=8, output_tokens=4), status="completed"),
        ]
        client = FakeClient(responses)
        task = {"id": "verification", "agent": "verification", "goal": "独立核验", "depends_on": ["cause"]}

        child = run_specialist(
            new_run("multi", "黄金为什么上涨", "source_first"),
            task,
            VERIFICATION_AGENT,
            lambda *args: None,
            client,
            findings,
            [{"id": "E1", "kind": "source", "url": original_url}],
        )

        self.assertEqual(child["verification_result"]["status"], "passed")
        self.assertEqual(child["verification_result"]["fact_results"][0]["supporting_evidence_ids"], ["E1", "E2"])
        correction_input = client.requests[2]["input"]
        self.assertTrue(any("未引用已经读取" in item.get("output", "") for item in correction_input if isinstance(item, dict)))

    def test_verifier_does_not_invent_fact_when_findings_have_none(self):
        findings = [{
            "task_id": "market",
            "agent": "market",
            "status": "insufficient",
            "summary": "没有取得价格数据",
            "facts": [],
            "evidence_ids": ["E1"],
            "unresolved": ["请求日期没有可核验行情"],
        }]
        client = FakeClient([])
        events = []
        task = {"id": "verification", "agent": "verification", "goal": "独立核验", "depends_on": ["market"]}

        child = run_specialist(
            new_run("multi", "黄金价格是多少", "source_first"),
            task,
            VERIFICATION_AGENT,
            lambda *args: events.append(args),
            client,
            findings,
            [{"id": "E1", "kind": "source"}],
        )

        result = child["verification_result"]
        self.assertEqual(result["status"], "insufficient")
        self.assertEqual(result["fact_results"], [])
        self.assertIn("请求日期没有可核验行情", result["unresolved"])
        self.assertEqual(client.requests, [])
        self.assertIn("没有可核验 Fact", events[0][1])

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
