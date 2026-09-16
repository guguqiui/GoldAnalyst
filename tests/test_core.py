import copy
import json
import threading
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

from gold_analyst.agent import investigate, safe_error
from gold_analyst.demo import demonstrate
from gold_analyst.models import ResearchBudget
from gold_analyst.server import new_run
from gold_analyst.tools import Tool, ToolContext, ToolRegistry, create_tool_registry, parse_html, validate_public_url
from gold_analyst.tools.calculator import CalculateChangeTool
from gold_analyst.verification import calculate_change, validate_report


def report(refs=None):
    return {"title": "测试", "summary": "计算核验", "review": "已检查", "unresolved": [],
            "claims": [{"statement": "涨幅 1.64%", "verdict": "有证据支持", "reason": "计算结果",
                        "evidence_ids": ["E1"] if refs is None else refs}]}


def call(name, arguments, number=1):
    return NS(type="function_call", name=name, arguments=json.dumps(arguments, ensure_ascii=False), call_id=f"call{number}")


def response(*calls):
    return NS(output=list(calls), usage=NS(input_tokens=10, output_tokens=5), status="completed")


class FakeClient:
    def __init__(self, responses):
        self.items = iter(responses)
        self.requests = []
        self.responses = self

    def create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        return next(self.items)


class VerificationTests(unittest.TestCase):
    def test_arithmetic_not_float(self):
        self.assertEqual(calculate_change("1004.41", "1005.59")["difference"], "-1.18")
        self.assertEqual(calculate_change("1004.41", "984.86")["percent"], "1.99")
        self.assertEqual(calculate_change("620", "610")["percent"], "1.64")

    def test_missing_or_invalid_prices(self):
        for v in ("0", "-1", "NaN", "Infinity", "missing"):
            with self.assertRaises(ValueError):
                calculate_change("620", v)

    def test_hallucinated_citation_rejected(self):
        with self.assertRaises(ValueError):
            validate_report(report(["E99"]), [{"id": "E1"}])

    def test_no_evidence_is_unknown(self):
        self.assertEqual(validate_report(report([]), [])["claims"][0]["verdict"], "证据不足")

    def test_news_cannot_verify_itself(self):
        result = validate_report(report(), [{"id": "E1", "kind": "news"}])
        self.assertEqual(result["claims"][0]["verdict"], "证据不足")

    def test_report_fields_required(self):
        bad = report()
        bad.pop("unresolved")
        with self.assertRaises(ValueError):
            validate_report(bad, [{"id": "E1", "kind": "source"}])

    def test_demo_is_explicit_and_consistent(self):
        run = demonstrate(new_run("demo", "", "source_first"), lambda *a: None)
        self.assertIn("虚构", run["notice"])
        self.assertEqual(run["usage"]["input_tokens"], 0)
        self.assertEqual(run["report"]["claims"][2]["verdict"], "有证据反驳")


class ParsingTests(unittest.TestCase):
    def test_chinese_encoding_and_article_body(self):
        data = '<meta charset="gbk"><h1>黄金新闻</h1><nav>导航</nav><div class="main-text">午盘基准价 620 元/克</div>'.encode("gbk")
        page = parse_html(data, "https://example.com")
        self.assertEqual(page["title"], "黄金新闻")
        self.assertIn("620", page["text"])
        self.assertNotIn("导航", page["text"])

    def test_table_preserves_auction_rounds(self):
        page = parse_html(b'<table><tr><th>RND</th><th>PRC</th></tr><tr><td>1</td><td>625</td></tr><tr><td>2</td><td>620</td></tr></table>', "https://www.sge.com.cn")
        self.assertEqual(len(page["tables"][0]), 3)
        self.assertNotIn("final_price", page)

    @patch("gold_analyst.tools.web.socket.getaddrinfo", return_value=[(None, None, None, None, ("127.0.0.1", 80))])
    def test_private_targets_blocked(self, _):
        with self.assertRaises(ValueError):
            validate_public_url("http://example.com/")

    def test_non_http_and_credentials_blocked(self):
        for url in ("file:///etc/passwd", "https://user:secret@example.com", "http://localhost:8000"):
            with self.assertRaises(ValueError):
                validate_public_url(url)


class AgentTests(unittest.TestCase):
    def test_custom_research_budget_controls_final_round(self):
        client = FakeClient([
            response(),
            response(call("submit_report", report([]), 2)),
            response(call("submit_report", report([]), 3)),
        ])
        investigate(
            new_run("live", "小预算调查", "source_first"),
            lambda *a: None,
            client,
            ResearchBudget(rounds=1, tool_calls=2, parallel_tools=1, duration_seconds=30),
        )
        self.assertEqual(client.requests[1]["tool_choice"], {"type": "function", "name": "submit_report"})

    def test_multiple_tools_run_in_parallel(self):
        barrier = threading.Barrier(2)
        original_execute = CalculateChangeTool.execute

        def synchronized_execute(tool, current, previous):
            barrier.wait(timeout=2)
            return original_execute(tool, current, previous)

        client = FakeClient([
            response(
                call("calculate_change", {"current": "620", "previous": "610"}, 1),
                call("calculate_change", {"current": "625", "previous": "620"}, 2),
            ),
            response(call("submit_report", report(), 3)),
            response(call("submit_report", report(), 4)),
        ])
        with patch.object(CalculateChangeTool, "execute", synchronized_execute):
            run = investigate(new_run("live", "并行计算", "scope_first"), lambda *a: None, client)

        outputs = [
            item for item in client.requests[1]["input"]
            if isinstance(item, dict) and item.get("type") == "function_call_output"
        ]
        self.assertEqual(len(outputs), 2)
        self.assertTrue(client.requests[0]["parallel_tool_calls"])
        self.assertEqual(run["usage"]["tool_calls"], 2)
        self.assertEqual({item["id"] for item in run["evidence"]}, {"E1", "E2"})

    def test_parallel_batch_respects_total_tool_budget(self):
        batch = [
            call("calculate_change", {"current": str(620 + index), "previous": "610"}, index)
            for index in range(1, 14)
        ]
        client = FakeClient([
            response(*batch),
            response(call("submit_report", report(), 20)),
            response(call("submit_report", report(), 21)),
        ])
        run = investigate(new_run("live", "批量计算", "scope_first"), lambda *a: None, client)

        outputs = [
            item for item in client.requests[1]["input"]
            if isinstance(item, dict) and item.get("type") == "function_call_output"
        ]
        self.assertEqual(run["usage"]["tool_calls"], 12)
        self.assertEqual(len(run["evidence"]), 12)
        self.assertEqual(len(outputs), 13)
        self.assertIn("总预算已用尽", outputs[-1]["output"])
        self.assertEqual(client.requests[1]["tool_choice"], {"type": "function", "name": "submit_report"})

    def test_tool_result_returned_and_review_is_independent(self):
        client = FakeClient([response(call("calculate_change", {"current": "620", "previous": "610"})),
                             response(call("submit_report", report(), 2)),
                             response(call("submit_report", report(), 3))])
        run = investigate(new_run("live", "测试算术", "scope_first"), lambda *a: None, client=client)
        outputs = [x for x in client.requests[1]["input"] if isinstance(x, dict) and x.get("type") == "function_call_output"]
        self.assertEqual(outputs[0]["call_id"], "call1")
        self.assertIn("1.64", outputs[0]["output"])
        self.assertEqual(len(client.requests[2]["input"]), 1)
        self.assertEqual(run["usage"]["input_tokens"], 30)
        self.assertIn("模型审核完成", run["review_status"])

    def test_tool_failure_is_visible_to_model(self):
        r = report([])
        client = FakeClient([response(call("calculate_change", {"current": "620", "previous": "0"})),
                             response(call("submit_report", r, 2)), response(call("submit_report", r, 3))])
        run = investigate(new_run("live", "未知", "source_first"), lambda *a: None, client)
        outputs = [x for x in client.requests[1]["input"] if isinstance(x, dict) and x.get("type") == "function_call_output"]
        self.assertIn("error", outputs[0]["output"])
        self.assertEqual(run["evidence"], [])

    def test_invalid_review_keeps_draft_with_notice(self):
        client = FakeClient([response(call("submit_report", report([]))), response()])
        run = investigate(new_run("live", "未知", "source_first"), lambda *a: None, client)
        self.assertEqual(run["review_status"], "未审核初稿")

    def test_final_round_forces_submission(self):
        client = FakeClient([response()] * 6 + [response(call("submit_report", report([]))), response(call("submit_report", report([])))])
        investigate(new_run("live", "未知", "counter_first"), lambda *a: None, client)
        self.assertEqual(client.requests[6]["tool_choice"], {"type": "function", "name": "submit_report"})


class ToolRegistryTests(unittest.TestCase):
    def test_registry_binds_all_tools(self):
        registry = create_tool_registry(new_run("demo", "", "source_first"), lambda *a: None)
        self.assertEqual(
            registry.names,
            {"read_url", "list_news", "get_sge_data", "calculate_change", "search_web", "submit_report"},
        )
        self.assertTrue(registry.get("submit_report").terminal)
        self.assertEqual(len(registry.schemas()), 6)

    def test_duplicate_tool_names_rejected(self):
        class ExampleTool(Tool):
            name = "same"
            description = "测试"
            parameters = {}

            def execute(self):
                return {}

        context = ToolContext(new_run("demo", "", "source_first"), lambda *a: None)
        with self.assertRaises(ValueError):
            ToolRegistry([ExampleTool(context), ExampleTool(context)])


if __name__ == "__main__":
    unittest.main()
