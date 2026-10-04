"""无需账号/联网：用模拟 HTTP 流测试 Codex 协议适配。"""
import base64
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

import httpx
from gold_analyst.providers.codex import CodexClient, CodexLoginError, get_credentials, has_login, token_storage
from gold_analyst.agent import investigate
from gold_analyst.config import public_settings, settings
from gold_analyst.providers.llm import create_llm
from gold_analyst.progress import activity
from gold_analyst.server import new_run
from gold_analyst.tools import create_tool_registry

REAL_HTTPX_CLIENT = httpx.Client


class CodexTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.output = [{"type": "function_call", "id": "fc_1", "call_id": "call_1",
                        "name": "calculate_change", "arguments": '{"current":"620","previous":"610"}',
                        "status": "completed"}]
        self.event_type = "response.completed"
        self.status = "completed"
        self.output_queue = []
        self.split_stream_output = ""

        def handle(request):
            self.requests.append(request)
            output = self.output_queue.pop(0) if self.output_queue else self.output
            result = {"id": "resp_1", "object": "response", "created_at": 0,
                      "status": self.status, "model": "gpt-5.5", "output": [] if self.split_stream_output else output,
                      "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}}
            event = {"type": self.event_type, "response": result, "sequence_number": len(output) + 1}
            data = 'data: {"type":"response.output_text.delta","delta":"partial"}\n\n'
            if self.split_stream_output == "done":
                for index, item in enumerate(output):
                    done = {"type": "response.output_item.done", "output_index": index,
                            "item": item, "sequence_number": index + 1}
                    data += "data: " + json.dumps(done) + "\n\n"
            if self.split_stream_output == "arguments":
                for index, item in enumerate(output):
                    added_item = {**item, "arguments": "", "status": "in_progress"}
                    added = {"type": "response.output_item.added", "output_index": index,
                             "item": added_item, "sequence_number": index * 3 + 1}
                    delta = {"type": "response.function_call_arguments.delta", "output_index": index,
                             "item_id": item["id"], "delta": item["arguments"],
                             "sequence_number": index * 3 + 2}
                    arguments_done = {"type": "response.function_call_arguments.done", "output_index": index,
                                      "item_id": item["id"], "name": item["name"],
                                      "arguments": item["arguments"], "sequence_number": index * 3 + 3}
                    for stream_event in (added, delta, arguments_done):
                        data += "data: " + json.dumps(stream_event) + "\n\n"
            if self.event_type:
                data += "data: " + json.dumps(event) + "\n\n"
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=data)

        def client_factory(**kwargs):
            kwargs["transport"] = httpx.MockTransport(handle)
            return REAL_HTTPX_CLIENT(**kwargs)

        self.token_patch = patch("gold_analyst.providers.codex.get_credentials", return_value=NS(access="test-token", account_id="test-account"))
        self.client_patch = patch("gold_analyst.providers.codex.httpx.Client", side_effect=client_factory)
        self.token_patch.start()
        self.client_patch.start()
        self.addCleanup(self.token_patch.stop)
        self.addCleanup(self.client_patch.stop)

    def test_tool_call_parsing_and_request_conversion(self):
        llm = create_llm({"provider": "codex", "model": "gpt-5.5", "api_key": "unused"})
        result = llm.respond("research", [{"role": "user", "content": "test"}], [], "auto")
        self.assertEqual(result.tool_calls[0].name, "calculate_change")
        self.assertEqual(result.tool_calls[0].arguments["current"], "620")
        self.assertEqual(result.input_tokens, 10)
        self.assertGreater(len(result.raw_response.model_dump()["stream_events"]), 1)
        request = self.requests[0]
        body = json.loads(request.content)
        self.assertEqual(str(request.url), "https://chatgpt.com/backend-api/codex/responses")
        self.assertEqual(request.headers["authorization"], "Bearer test-token")
        self.assertTrue(body["stream"])
        self.assertFalse(body["store"])
        self.assertNotIn("max_output_tokens", body)
        self.assertIn("reasoning.encrypted_content", body["include"])

    def test_rebuilds_tool_calls_when_completed_event_has_empty_output(self):
        self.split_stream_output = "done"
        llm = create_llm({"provider": "codex", "model": "gpt-5.5", "api_key": "unused"})
        result = llm.respond("research", [{"role": "user", "content": "test"}], [], "auto")
        self.assertEqual(len(result.history_items), 1)
        self.assertEqual(result.tool_calls[0].name, "calculate_change")
        self.assertEqual(result.raw_response.output[0].call_id, "call_1")

    def test_rebuilds_tool_call_without_output_item_done_like_vt(self):
        self.split_stream_output = "arguments"
        llm = create_llm({"provider": "codex", "model": "gpt-5.5", "api_key": "unused"})
        result = llm.respond("research", [{"role": "user", "content": "test"}], [], "auto")
        self.assertEqual(len(result.history_items), 1)
        self.assertEqual(result.tool_calls[0].name, "calculate_change")
        self.assertEqual(result.tool_calls[0].arguments, {"current": "620", "previous": "610"})

    def test_search_uses_same_codex_client_and_keeps_citations(self):
        self.output = [{"type": "message", "id": "msg1", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": "摘要", "annotations": [
                            {"type": "url_citation", "url": "https://sge.com.cn/gold", "title": "来源",
                             "start_index": 0, "end_index": 2}]}]}]
        run = new_run("live", "test", "source_first")
        registry = create_tool_registry(run, lambda *a: None, CodexClient(), "gpt-5.5")
        result = registry.get("search_sources").execute("黄金", 10)
        self.assertEqual(result["evidence"]["citations"][0]["url"], "https://sge.com.cn/gold")
        self.assertEqual(result["evidence"]["citations"][0]["tier"], 1)
        body = json.loads(self.requests[0].content)
        self.assertIsInstance(body["input"], list)
        self.assertNotIn("max_tool_calls", body)
        self.assertEqual(body["tools"], [{"type": "web_search"}])
        self.assertIn("web_search_call.action.sources", body["include"])

    def test_search_filters_the_target_link_from_citations(self):
        self.output = [{"type": "message", "id": "msg1", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": "摘要", "annotations": [
                            {"type": "url_citation", "url": "https://example.com/article", "title": "待核验原文",
                             "start_index": 0, "end_index": 1},
                            {"type": "url_citation", "url": "https://sge.com.cn/report", "title": "独立来源",
                             "start_index": 1, "end_index": 2}]}]}]
        run = new_run("live", "核验 https://example.com/article", "source_first")
        registry = create_tool_registry(run, lambda *a: None, CodexClient(), "gpt-5.5")
        result = registry.get("search_sources").execute("核验文章中的黄金说法", 10)
        self.assertEqual(result["evidence"]["citations"][0]["url"], "https://sge.com.cn/report")

    def test_search_filters_domains_locally_and_keeps_complete_sources(self):
        self.output = [
            {"type": "web_search_call", "id": "ws1", "status": "completed", "action": {
                "type": "search", "query": "黄金", "sources": [
                    {"type": "url", "title": "官方来源", "url": "https://www.sge.com.cn/gold"},
                    {"type": "url", "title": "不允许来源", "url": "https://other.example/gold"},
                ]}},
            {"type": "message", "id": "msg1", "role": "assistant", "status": "completed",
             "content": [{"type": "output_text", "text": "摘要", "annotations": []}]},
        ]
        run = new_run("live", "核验黄金数据", "source_first")
        registry = create_tool_registry(run, lambda *a: None, CodexClient(), "gpt-5.5")
        result = registry.get("search_sources").execute("黄金", 10)
        self.assertEqual(result["sources"][0]["url"], "https://www.sge.com.cn/gold")
        self.assertEqual(result["sources"][0]["tier"], 1)
        self.assertEqual(result["universes"], ["china_spot", "discovery_news"])
        body = json.loads(self.requests[0].content)
        self.assertEqual(body["tools"], [{"type": "web_search"}])
        self.assertIn("sge.com.cn", body["input"][0]["content"])
        self.assertNotIn("other.example", body["input"][0]["content"])
        self.assertNotIn("sina.com.cn", body["input"][0]["content"])

    def test_search_stops_before_tier_four_when_two_better_domains_exist(self):
        primary = [{"type": "message", "id": "msg1", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": "官方摘要", "annotations": [
                        {"type": "url_citation", "url": "https://sge.com.cn/gold", "title": "上金所",
                         "start_index": 0, "end_index": 2}]}]}]
        news = [{"type": "message", "id": "msg2", "role": "assistant", "status": "completed",
                 "content": [{"type": "output_text", "text": "媒体摘要", "annotations": [
                     {"type": "url_citation", "url": "https://reuters.com/gold", "title": "Reuters",
                      "start_index": 0, "end_index": 2},
                     {"type": "url_citation", "url": "https://sina.com.cn/gold", "title": "新浪",
                      "start_index": 2, "end_index": 4}]}]}]
        self.output_queue = [primary, news]
        run = new_run("live", "黄金上涨原因", "source_first")
        registry = create_tool_registry(run, lambda *a: None, CodexClient(), "gpt-5.5")
        result = registry.get("search_sources").execute("黄金上涨原因", 3)
        self.assertEqual([source["url"] for source in result["sources"]], [
            "https://sge.com.cn/gold", "https://reuters.com/gold",
        ])
        self.assertEqual(result["evidence"]["searched_tiers"], ["原始与专业来源", "大型财经媒体"])
        self.assertEqual(len(self.requests), 2)
        self.assertNotIn("sina.com.cn", json.loads(self.requests[1].content)["input"][0]["content"])

    def test_search_uses_tier_four_only_as_last_resort_clue(self):
        empty_primary = [{"type": "message", "id": "msg1", "role": "assistant", "status": "completed",
                          "content": [{"type": "output_text", "text": "未找到", "annotations": []}]}]
        empty_news = [{"type": "message", "id": "msg2", "role": "assistant", "status": "completed",
                       "content": [{"type": "output_text", "text": "仍未找到", "annotations": []}]}]
        clues = [{"type": "message", "id": "msg3", "role": "assistant", "status": "completed",
                  "content": [{"type": "output_text", "text": "聚合线索", "annotations": [
                      {"type": "url_citation", "url": "https://sina.com.cn/gold", "title": "新浪线索",
                       "start_index": 0, "end_index": 2}]}]}]
        self.output_queue = [empty_primary, empty_news, clues]
        run = new_run("live", "黄金上涨原因", "source_first")
        registry = create_tool_registry(run, lambda *a: None, CodexClient(), "gpt-5.5")
        result = registry.get("search_sources").execute("黄金上涨原因", 3)
        self.assertEqual(result["sources"][0]["tier"], 4)
        self.assertEqual(result["sources"][0]["usage"], "clue_only")
        self.assertEqual(len(self.requests), 3)
        self.assertIn("sina.com.cn", json.loads(self.requests[2].content)["input"][0]["content"])

    def test_incomplete_or_missing_completion_is_rejected(self):
        for event in ("response.incomplete", "response.failed", ""):
            self.event_type = event
            with self.assertRaisesRegex(ValueError, "未返回完整结果"):
                CodexClient().create(model="gpt-5.5", input="test")

    def test_agent_roundtrip_executes_tool_then_submits_and_reviews(self):
        report = {"title": "模拟核验", "summary": "计算结果", "unresolved": [], "review": "已核验",
                  "claims": [{"statement": "涨幅约 1.64%", "verdict": "有证据支持",
                              "reason": "工具计算", "evidence_ids": ["E1"]}]}
        submit = {"type": "function_call", "id": "fc_2", "call_id": "call_2",
                  "name": "submit_report", "arguments": json.dumps(report), "status": "completed"}
        self.output_queue = [self.output, [submit], [submit]]
        cfg = {"provider": "codex", "model": "gpt-5.5", "api_key": ""}
        events = []
        with tempfile.TemporaryDirectory() as directory, \
             patch("gold_analyst.agent.settings", return_value=cfg), \
             patch("gold_analyst.persistence.local.LOCAL_ROOT", Path(directory) / ".local"), \
             patch("gold_analyst.persistence.local.ROOT", Path(directory)):
            run = investigate(new_run("live", "核验涨幅", "source_first"), lambda *args: events.append(args))
        self.assertEqual(run["report"]["title"], "模拟核验")
        self.assertEqual(run["usage"]["tool_calls"], 1)
        second_input = json.loads(self.requests[1].content)["input"]
        self.assertTrue(any(item.get("type") == "function_call_output" for item in second_input))
        activities = [args[2] for args in events if len(args) == 3 and args[2].get("activity_id")]
        self.assertEqual(sum(item["state"] == "running" for item in activities), 4)
        self.assertEqual(sum(item["state"] == "completed" for item in activities), 4)


class LoginAndProgressTests(unittest.TestCase):
    def test_storage_does_not_import_shared_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "own.json"
            with patch("gold_analyst.providers.codex.TOKEN_PATH", path):
                storage = token_storage()
                self.assertEqual(storage.get_token_path(), path)
                self.assertFalse(storage._import_codex_cli)
                self.assertFalse(has_login())

    def test_expired_jwt_rejected_even_if_storage_expiry_is_future(self):
        payload = base64.urlsafe_b64encode(json.dumps({"exp": 1}).encode()).decode().rstrip("=")
        token = NS(access="x." + payload + ".x", expires=int((time.time() + 3600) * 1000), account_id="test")
        with patch("oauth_cli_kit.get_token", return_value=token):
            with self.assertRaises(CodexLoginError):
                get_credentials()

    def test_login_errors_do_not_expose_raw_exception(self):
        with patch("oauth_cli_kit.get_token", side_effect=RuntimeError("secret-token-value")):
            with self.assertRaises(CodexLoginError) as caught:
                get_credentials()
            self.assertNotIn("secret-token-value", str(caught.exception))

    def test_codex_config_does_not_require_api_key(self):
        with patch.dict(os.environ, {"GOLD_PROVIDER": "codex", "GOLD_CODEX_MODEL": "test-model", "OPENAI_API_KEY": ""}):
            with patch("gold_analyst.providers.codex.has_login", return_value=True):
                self.assertEqual(settings()["model"], "test-model")
                self.assertTrue(public_settings()["model_ready"])
                self.assertNotIn("api_key", public_settings())

    def test_success_and_failure_have_matching_activity_ids(self):
        events = []
        emit = lambda *args: events.append(args)
        with activity(emit, "工具", "test"):
            self.assertEqual(events[-1][2]["state"], "running")
        self.assertEqual(events[0][2]["activity_id"], events[1][2]["activity_id"])
        self.assertEqual(events[1][2]["state"], "completed")
        with self.assertRaises(ValueError):
            with activity(emit, "模型", "test"):
                raise ValueError("failed")
        self.assertEqual(events[-1][2]["state"], "failed")
        self.assertNotEqual(events[0][2]["activity_id"], events[-1][2]["activity_id"])
