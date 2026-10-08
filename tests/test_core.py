import copy
import json
import threading
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

from gold_analyst.agent import investigate, safe_error
from gold_analyst.demo import demonstrate
from gold_analyst.models import DEFAULT_RESEARCH_BUDGET, ResearchBudget
from gold_analyst.multi_agent import AGENT_TOOLSETS, investigate_multi, merge_candidates
from gold_analyst.server import new_run
from gold_analyst.sources.router import ranked_sources, select_universes
from gold_analyst.sources.universes import SOURCE_TIERS, SOURCE_UNIVERSES
from gold_analyst.tools import (
    Tool,
    ToolContext,
    ToolRegistry,
    create_tool_registry,
    parse_html,
    tool_call_key,
    validate_public_url,
)
from gold_analyst.tools.calculator import CalculateChangeTool
from gold_analyst.tools.sge import SGEDataTool
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

    def test_tier_four_cannot_be_the_only_support(self):
        result = validate_report(report(), [{"id": "E1", "kind": "source", "source_tier": 4}])
        self.assertEqual(result["claims"][0]["verdict"], "证据不足")
        self.assertIn("tier 4", result["validation_notes"][0])

    def test_tier_four_may_supplement_a_better_source(self):
        candidate = report(["E1", "E2"])
        evidence = [
            {"id": "E1", "kind": "source", "source_tier": 2},
            {"id": "E2", "kind": "source", "source_tier": 4},
        ]
        self.assertEqual(validate_report(candidate, evidence)["claims"][0]["verdict"], "有证据支持")

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

    @patch("gold_analyst.tools.web.fetch")
    def test_read_url_inherits_search_source_tier(self, fake_fetch):
        url = "https://sina.com.cn/gold"
        fake_fetch.return_value = (
            b"<html><h1>Gold clue</h1><article>This is a sufficiently long article body for testing provenance.</article></html>",
            "text/html",
            url,
        )
        registry = create_tool_registry(new_run("live", "黄金", "source_first"), lambda *a: None)
        read_url = registry.get("read_url")
        read_url.context.set_cached("source_meta:" + url, {
            "domain": "sina.com.cn", "source_name": "新浪财经", "tier": 4,
            "universe": "discovery_news", "usage": "clue_only",
        })
        item = read_url.execute(url)
        self.assertEqual(item["source_tier"], 4)
        self.assertEqual(item["evidence_usage"], "clue_only")

    def test_read_url_only_skips_the_same_excluded_article(self):
        run = new_run("live", "黄金", "source_first")
        run["excluded_source_urls"] = ["https://www.example.com/article/?utm_source=old"]
        read_url = create_tool_registry(run, lambda *a: None).get("read_url")

        self.assertIn(
            "前序 Agent",
            read_url.skip_reason(url="https://example.com/article") or "",
        )
        self.assertIsNone(read_url.skip_reason(url="https://example.com/another-article"))


class AgentTests(unittest.TestCase):
    def test_single_agent_receives_session_history_before_current_question(self):
        client = FakeClient([
            response(call("submit_report", report([]), 1)),
            response(call("submit_report", report([]), 2)),
        ])
        run = new_run("live", "第二个原因有什么证据？", "source_first")
        history = [
            {"role": "user", "content": "九月金价为什么下跌？"},
            {"role": "assistant", "content": "主要有三个原因。"},
        ]
        run["conversation_history"] = history

        investigate(run, lambda *a: None, client)

        self.assertEqual(client.requests[0]["input"][:2], history)
        self.assertEqual(
            client.requests[0]["input"][2],
            {"role": "user", "content": "第二个原因有什么证据？"},
        )

    @patch("gold_analyst.tools.web.fetch")
    def test_excluded_source_is_skipped_without_using_tool_budget(self, fake_fetch):
        run = new_run("live", "核验原因", "source_first")
        run["excluded_source_urls"] = ["https://example.com/original"]
        client = FakeClient([
            response(call("read_url", {"url": "https://www.example.com/original/?utm_source=test"}, 1)),
            response(call("submit_report", report([]), 2)),
            response(call("submit_report", report([]), 3)),
        ])
        events = []

        result = investigate(run, lambda *args: events.append(args), client)

        fake_fetch.assert_not_called()
        self.assertEqual(result["usage"]["tool_calls"], 0)
        skipped = [
            item for item in client.requests[1]["input"]
            if isinstance(item, dict)
            and item.get("type") == "function_call_output"
            and item.get("call_id") == "call1"
        ]
        self.assertIn("不能作为新增交叉核验证据", skipped[0]["output"])
        self.assertTrue(any(event[0] == "工具跳过" for event in events))

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
            for index in range(1, DEFAULT_RESEARCH_BUDGET.tool_calls + 2)
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
        self.assertEqual(run["usage"]["tool_calls"], DEFAULT_RESEARCH_BUDGET.tool_calls)
        self.assertEqual(len(run["evidence"]), DEFAULT_RESEARCH_BUDGET.tool_calls)
        self.assertEqual(len(outputs), DEFAULT_RESEARCH_BUDGET.tool_calls + 1)
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

    def test_identical_successful_call_uses_visible_previous_result(self):
        executions = []
        original_execute = CalculateChangeTool.execute

        def tracked_execute(tool, current, previous):
            executions.append((current, previous))
            return original_execute(tool, current, previous)

        client = FakeClient([
            response(call("calculate_change", {"current": "620", "previous": "610"}, 1)),
            response(call("calculate_change", {"previous": "610", "current": "620"}, 2)),
            response(call("submit_report", report(), 3)),
            response(call("submit_report", report(), 4)),
        ])
        with patch.object(CalculateChangeTool, "execute", tracked_execute):
            run = investigate(new_run("live", "重复计算", "scope_first"), lambda *a: None, client)

        duplicate_outputs = [
            item for item in client.requests[2]["input"]
            if isinstance(item, dict)
            and item.get("type") == "function_call_output"
            and item.get("call_id") == "call2"
        ]
        self.assertEqual(len(executions), 1)
        self.assertEqual(run["usage"]["tool_calls"], 1)
        self.assertEqual(len(run["evidence"]), 1)
        self.assertIn("前序 ToolMessage", duplicate_outputs[0]["output"])

    def test_identical_failed_call_may_retry(self):
        executions = []
        original_execute = CalculateChangeTool.execute

        def tracked_execute(tool, current, previous):
            executions.append((current, previous))
            return original_execute(tool, current, previous)

        client = FakeClient([
            response(call("calculate_change", {"current": "620", "previous": "0"}, 1)),
            response(call("calculate_change", {"current": "620", "previous": "0"}, 2)),
            response(call("submit_report", report([]), 3)),
            response(call("submit_report", report([]), 4)),
        ])
        with patch.object(CalculateChangeTool, "execute", tracked_execute):
            run = investigate(new_run("live", "失败重试", "scope_first"), lambda *a: None, client)

        self.assertEqual(len(executions), 2)
        self.assertEqual(run["usage"]["tool_calls"], 2)

    def test_third_identical_failure_is_blocked_without_using_budget(self):
        executions = []
        original_execute = CalculateChangeTool.execute

        def tracked_execute(tool, current, previous):
            executions.append((current, previous))
            return original_execute(tool, current, previous)

        bad_arguments = {"current": "620", "previous": "0"}
        client = FakeClient([
            response(call("calculate_change", bad_arguments, 1)),
            response(call("calculate_change", bad_arguments, 2)),
            response(call("calculate_change", bad_arguments, 3)),
            response(call("submit_report", report([]), 4)),
            response(call("submit_report", report([]), 5)),
        ])
        events = []
        with patch.object(CalculateChangeTool, "execute", tracked_execute):
            run = investigate(
                new_run("live", "连续失败", "scope_first"),
                lambda *args: events.append(args),
                client,
            )

        blocked_outputs = [
            item for item in client.requests[3]["input"]
            if isinstance(item, dict)
            and item.get("type") == "function_call_output"
            and item.get("call_id") == "call3"
        ]
        self.assertEqual(len(executions), 2)
        self.assertEqual(run["usage"]["tool_calls"], 2)
        self.assertIn("连续失败两次", blocked_outputs[0]["output"])
        self.assertTrue(any(event[0] == "工具阻止" for event in events))

    def test_compacted_readonly_result_is_restored_without_execution(self):
        executions = []
        original_execute = CalculateChangeTool.execute

        def tracked_execute(tool, current, previous):
            executions.append((current, previous))
            return original_execute(tool, current, previous)

        first_arguments = {"current": "620", "previous": "610"}
        client = FakeClient([
            response(*[
                call(
                    "calculate_change",
                    {"current": str(620 + index), "previous": "610"},
                    index + 1,
                )
                for index in range(4)
            ]),
            response(call("calculate_change", first_arguments, 5)),
            response(call("submit_report", report(), 6)),
            response(call("submit_report", report(), 7)),
        ])
        events = []
        with (
            patch.object(CalculateChangeTool, "execute", tracked_execute),
            patch("gold_analyst.agent.DYNAMIC_CONTEXT_CHAR_LIMIT", 1),
            patch("gold_analyst.agent.KEEP_RECENT_TOOL_RESULTS", 1),
        ):
            run = investigate(
                new_run("live", "压缩后重复计算", "scope_first"),
                lambda *args: events.append(args),
                client,
            )

        replay_outputs = [
            item for item in client.requests[2]["input"]
            if isinstance(item, dict)
            and item.get("type") == "function_call_output"
            and item.get("call_id") == "call5"
        ]
        self.assertEqual(len(executions), 4)
        self.assertEqual(run["usage"]["tool_calls"], 4)
        self.assertIn("_context_replay", replay_outputs[0]["output"])
        self.assertTrue(any(event[0] == "上下文压缩" for event in events))
        self.assertTrue(any(event[0] == "上下文复用" for event in events))

    def test_compacted_non_replayable_result_is_executed_again(self):
        executions = []

        def tracked_execute(tool, trade_date, category, contract):
            executions.append((trade_date, category, contract))
            return {"trade_date": trade_date, "category": category, "contract": contract}

        first_arguments = {"trade_date": "2026-09-27", "category": "daily", "contract": "Au99.99"}
        client = FakeClient([
            response(*[
                call("get_sge_data", {
                    "trade_date": f"2026-09-{27 + index:02d}",
                    "category": "daily",
                    "contract": "Au99.99",
                }, index + 1)
                for index in range(4)
            ]),
            response(call("get_sge_data", first_arguments, 5)),
            response(call("submit_report", report([]), 6)),
            response(call("submit_report", report([]), 7)),
        ])
        with (
            patch.object(SGEDataTool, "execute", tracked_execute),
            patch("gold_analyst.agent.DYNAMIC_CONTEXT_CHAR_LIMIT", 1),
            patch("gold_analyst.agent.KEEP_RECENT_TOOL_RESULTS", 1),
        ):
            run = investigate(new_run("live", "压缩后刷新行情", "scope_first"), lambda *a: None, client)

        self.assertEqual(len(executions), 5)
        self.assertEqual(run["usage"]["tool_calls"], 5)

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
        client = FakeClient(
            [response()] * DEFAULT_RESEARCH_BUDGET.rounds
            + [response(call("submit_report", report([]))), response(call("submit_report", report([])))]
        )
        events = []
        investigate(new_run("live", "未知", "counter_first"), lambda *args: events.append(args), client)
        final_index = DEFAULT_RESEARCH_BUDGET.rounds
        self.assertEqual(client.requests[final_index]["tool_choice"],
                         {"type": "function", "name": "submit_report"})
        model_results = [event for event in events if event[0] == "模型结果"]
        self.assertEqual(len(model_results), DEFAULT_RESEARCH_BUDGET.rounds + 2)
        self.assertEqual(model_results[final_index][2]["tool_calls"][0]["name"], "submit_report")

    def test_three_no_progress_rounds_force_early_submission(self):
        client = FakeClient([
            response(),
            response(),
            response(),
            response(call("submit_report", report([]), 4)),
            response(call("submit_report", report([]), 5)),
        ])
        events = []
        investigate(
            new_run("live", "无进展调查", "scope_first"),
            lambda *args: events.append(args),
            client,
        )

        self.assertEqual(
            client.requests[3]["tool_choice"],
            {"type": "function", "name": "submit_report"},
        )
        self.assertEqual(
            {tool["name"] for tool in client.requests[3]["tools"]},
            {"submit_report"},
        )
        self.assertTrue(any(event[0] == "调查停滞" for event in events))


class MultiAgentTests(unittest.TestCase):
    def candidate(self, strategy, evidence, refs):
        run = new_run("live", "黄金说法", strategy)
        run["status"] = "completed"
        run["evidence"] = evidence
        run["report"] = report(refs)
        return run

    def test_merge_deduplicates_source_and_rewrites_references(self):
        first = self.candidate("source_first", [{"id": "E1", "title": "上金所", "text": "620",
            "url": "https://sge.com.cn/data?utm_source=x", "kind": "source", "retrieved_at": "now"}], ["E1"])
        second = self.candidate("scope_first", [{"id": "E1", "title": "同一页", "text": "620",
            "url": "https://sge.com.cn/data", "kind": "source", "retrieved_at": "now"}], ["E1"])
        evidence, candidates = merge_candidates([first, second])
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["researchers"], ["source_first", "scope_first"])
        self.assertEqual(candidates[0]["report"]["claims"][0]["evidence_ids"], ["E1"])
        self.assertEqual(candidates[1]["report"]["claims"][0]["evidence_ids"], ["E1"])

    @patch("gold_analyst.multi_agent.investigate")
    def test_three_researchers_are_isolated_and_one_may_fail(self, fake_investigate):
        barrier = threading.Barrier(3)

        seen_tools = {}

        def research(child, emit, client, budget, review, allowed_tools):
            barrier.wait(timeout=2)
            seen_tools[child["strategy"]] = allowed_tools
            if child["strategy"] == "counter_first":
                raise ValueError("候选失败")
            child["evidence"].append({"id": "E1", "title": child["strategy"], "text": "620",
                "url": "https://example.com/" + child["strategy"], "kind": "source", "retrieved_at": "now"})
            child["report"] = report(["E1"])
            child["usage"]["tool_calls"] = 1
            return child

        fake_investigate.side_effect = research
        client = FakeClient([response(call("submit_report", report(["E1"]), 9))])
        run = investigate_multi(new_run("multi", "黄金说法", "source_first"), lambda *a: None, client)
        self.assertEqual(len(run["candidates"]), 3)
        self.assertEqual([x["status"] for x in run["candidates"]].count("failed"), 1)
        self.assertEqual(len(run["evidence"]), 2)
        self.assertEqual(run["usage"]["tool_calls"], 2)
        self.assertIn("2/3", run["review_status"])
        self.assertEqual(seen_tools, AGENT_TOOLSETS)
        self.assertEqual(run["candidates"][0]["allowed_tools"], sorted(AGENT_TOOLSETS["source_first"]))


class ToolRegistryTests(unittest.TestCase):
    def test_tool_call_key_is_stable_and_parameter_sensitive(self):
        first = tool_call_key("search_sources", {"query": "黄金", "limit": 10})
        reordered = tool_call_key("search_sources", {"limit": 10, "query": "黄金"})
        changed = tool_call_key("search_sources", {"query": "黄金", "limit": 20})
        self.assertEqual(first, reordered)
        self.assertNotEqual(first, changed)

    def test_tool_call_key_normalizes_the_same_url(self):
        first = tool_call_key("read_url", {"url": "https://www.example.com/a/?utm_source=x"})
        same_article = tool_call_key("read_url", {"url": "https://example.com/a"})
        other_article = tool_call_key("read_url", {"url": "https://example.com/b"})
        self.assertEqual(first, same_article)
        self.assertNotEqual(first, other_article)

    def test_tool_call_key_refuses_unserializable_arguments(self):
        self.assertIsNone(tool_call_key("read_url", {"url": object()}))

    def test_tools_declare_context_reuse_policy(self):
        registry = create_tool_registry(new_run("live", "黄金", "source_first"), lambda *a: None)
        calculator = registry.get("calculate_change")
        self.assertTrue(calculator.is_readonly)
        self.assertTrue(calculator.repeatable)
        self.assertTrue(calculator.deterministic)
        reader = registry.get("read_url")
        self.assertTrue(reader.repeatable)
        self.assertTrue(reader.replay_after_compaction)
        self.assertFalse(registry.get("submit_report").is_readonly)

    def test_search_rejects_the_target_url_as_query(self):
        target = "https://example.com/article?a=1&utm_source=test"
        registry = create_tool_registry(new_run("live", target, "source_first"), lambda *a: None)
        with self.assertRaisesRegex(ValueError, "待核验链接不能作为搜索查询"):
            registry.get("search_sources").execute(
                "请搜索 https://example.com/article?a=1", 10,
            )

    def test_search_schema_only_asks_model_for_query_and_limit(self):
        registry = create_tool_registry(new_run("live", "黄金", "source_first"), lambda *a: None)
        schema = registry.get("search_sources").schema()
        self.assertEqual(schema["parameters"]["required"], ["query", "limit"])

    def test_registry_binds_all_tools(self):
        registry = create_tool_registry(new_run("demo", "", "source_first"), lambda *a: None)
        self.assertEqual(
            registry.names,
            {"read_url", "get_sge_data", "calculate_change", "search_sources", "submit_report"},
        )
        self.assertTrue(registry.get("submit_report").terminal)
        self.assertEqual(len(registry.schemas()), 5)

    def test_registry_enforces_tool_allowlist(self):
        registry = create_tool_registry(
            new_run("live", "测试", "scope_first"), lambda *a: None,
            allowed_names={"get_sge_data", "calculate_change", "submit_report"},
        )
        self.assertEqual(registry.names, {"get_sge_data", "calculate_change", "submit_report"})
        with self.assertRaisesRegex(ValueError, "未知工具"):
            registry.get("search_sources")
        with self.assertRaisesRegex(ValueError, "工具白名单包含未知工具"):
            create_tool_registry(new_run("live", "测试", "scope_first"), lambda *a: None,
                                 allowed_names={"not_a_tool"})

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


class SourceUniverseTests(unittest.TestCase):
    def test_each_universe_has_ordered_unique_sources(self):
        self.assertEqual(SOURCE_TIERS[1], "交易所、监管机构、央行或产品发行人")
        self.assertEqual(SOURCE_UNIVERSES["china_spot"]["sources"][0]["domain"], "sge.com.cn")
        self.assertEqual(SOURCE_UNIVERSES["comex_futures"]["sources"][0]["domain"], "cmegroup.com")
        for universe in SOURCE_UNIVERSES.values():
            domains = [source["domain"] for source in universe["sources"]]
            self.assertEqual(len(domains), len(set(domains)))
            self.assertTrue(all(source["tier"] in SOURCE_TIERS for source in universe["sources"]))


class SourceRouterTests(unittest.TestCase):
    def test_generic_rising_gold_defaults_to_china_and_adds_macro(self):
        self.assertEqual(
            select_universes("最近黄金为什么上涨"),
            ["china_spot", "macro_drivers", "discovery_news"],
        )

    def test_explicit_markets_select_their_own_universe(self):
        self.assertEqual(select_universes("查看 XAU/USD 报价"), ["london_spot", "discovery_news"])
        self.assertEqual(select_universes("COMEX 黄金持仓变化"), ["comex_futures", "discovery_news"])
        self.assertEqual(select_universes("GLD ETF 持仓"), ["gold_etf", "discovery_news"])

    def test_ranked_sources_keep_first_domain_only(self):
        sources = ranked_sources("上海金上涨原因")
        domains = [source["domain"] for source in sources]
        self.assertEqual(domains[0], "sge.com.cn")
        self.assertEqual(len(domains), len(set(domains)))
        self.assertEqual(domains.count("pbc.gov.cn"), 1)


if __name__ == "__main__":
    unittest.main()
