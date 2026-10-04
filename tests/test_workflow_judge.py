import copy
import json
import unittest
from types import SimpleNamespace as NS

from gold_analyst.orchestration import generate_final_report
from gold_analyst.server import new_run


def call(name, arguments):
    return NS(type="function_call", name=name, arguments=json.dumps(arguments), call_id="judge-call")


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.requests = []
        self.responses = self

    def create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        return self.response


class WorkflowJudgeTests(unittest.TestCase):
    def prepared_run(self):
        run = new_run("multi", "最近黄金为什么上涨", "source_first")
        run["evidence"] = [{"id": "E1", "kind": "source", "source_tier": 2}]
        run["findings"] = [{
            "task_id": "cause", "agent": "cause", "status": "supported", "summary": "发现",
            "facts": [{
                "fact_id": "cause.fact_1", "name": "美元", "value": "走弱", "unit": "", "note": "来源",
            }],
            "evidence_ids": ["E1"], "unresolved": [],
        }]
        run["verification_result"] = {
            "status": "passed",
            "fact_results": [{
                "fact_id": "cause.fact_1", "verdict": "supported", "reason": "有原始来源",
                "supporting_evidence_ids": ["E1"], "contradicting_evidence_ids": [], "unresolved": [],
            }],
            "conflicts": [], "unresolved": [],
        }
        return run

    def test_judge_only_receives_submit_report_and_sets_final_report(self):
        report = {
            "title": "黄金上涨原因", "summary": "已核验", "review": "采用 cause finding",
            "unresolved": [], "claims": [{
                "statement": "已有证据支持", "verdict": "有证据支持", "reason": "原始来源",
                "evidence_ids": ["E1"],
            }],
        }
        response = NS(
            output=[call("submit_report", report)],
            usage=NS(input_tokens=7, output_tokens=3),
            status="completed",
        )
        client = FakeClient(response)

        result = generate_final_report(self.prepared_run(), lambda *args: None, client)

        self.assertEqual(result["report"]["title"], "黄金上涨原因")
        self.assertEqual(result["strategy"], "multi_agent_workflow")
        self.assertEqual(result["usage"]["input_tokens"], 7)
        request = client.requests[0]
        self.assertEqual([tool["name"] for tool in request["tools"]], ["submit_report"])
        self.assertEqual(request["tool_choice"], {"type": "function", "name": "submit_report"})
        payload = json.loads(request["input"][0]["content"])
        self.assertEqual(payload["verification_result"]["fact_results"][0]["fact_id"], "cause.fact_1")

    def test_judge_requires_verification_result(self):
        run = self.prepared_run()
        del run["verification_result"]
        with self.assertRaisesRegex(ValueError, "没有独立核验"):
            generate_final_report(run, lambda *args: None, FakeClient(None))


if __name__ == "__main__":
    unittest.main()
