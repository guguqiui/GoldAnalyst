import unittest

from gold_analyst.agent_specs import (
    AGENT_SPECS,
    CAUSE_AGENT,
    MARKET_AGENT,
    VERIFICATION_AGENT,
    AgentSpec,
    get_agent_spec,
)
from gold_analyst.models import ResearchBudget
from gold_analyst.server import new_run
from gold_analyst.tools import create_tool_registry


class AgentSpecTests(unittest.TestCase):
    def test_all_specialists_have_unique_roles_and_finding_output(self):
        self.assertEqual(set(AGENT_SPECS), {"market", "cause", "verification"})
        self.assertEqual(len({spec.name for spec in AGENT_SPECS.values()}), 3)
        for spec in (MARKET_AGENT, CAUSE_AGENT):
            self.assertEqual(spec.output_tool, "submit_finding")
            self.assertIn(spec.output_tool, spec.allowed_tools)
        self.assertEqual(VERIFICATION_AGENT.output_tool, "submit_verification")
        self.assertIn(VERIFICATION_AGENT.output_tool, VERIFICATION_AGENT.allowed_tools)

    def test_specialists_have_real_capability_boundaries(self):
        self.assertIn("calculate_change", MARKET_AGENT.allowed_tools)
        self.assertNotIn("search_sources", MARKET_AGENT.allowed_tools)
        self.assertIn("search_sources", CAUSE_AGENT.allowed_tools)
        self.assertNotIn("calculate_change", CAUSE_AGENT.allowed_tools)
        self.assertTrue(
            {"get_evidence", "search_sources", "read_url", "calculate_change"}
            <= VERIFICATION_AGENT.allowed_tools
        )
        self.assertNotIn("get_sge_data", VERIFICATION_AGENT.allowed_tools)

    def test_get_agent_spec_returns_stable_configuration(self):
        self.assertIs(get_agent_spec("market"), MARKET_AGENT)
        self.assertEqual(get_agent_spec("cause").prompt_version, "cause-v2")

    def test_market_reuses_price_pair_and_verifier_reuses_dependency_context(self):
        self.assertIn("不得为了取得 previous_rows 再查询相邻日期", MARKET_AGENT.instruction)
        self.assertIn("dependency_findings", VERIFICATION_AGENT.instruction)
        self.assertIn("行情事实若已有一级官方来源，不再重新取数", VERIFICATION_AGENT.instruction)
        self.assertIn("URL 不同的新文章", VERIFICATION_AGENT.instruction)
        self.assertIn("分别设计精确的 search_sources 查询", VERIFICATION_AGENT.instruction)
        self.assertIn("新生成的 Evidence ID", VERIFICATION_AGENT.instruction)
        self.assertIn("get_evidence", VERIFICATION_AGENT.instruction)
        self.assertIn("最多提交3条", CAUSE_AGENT.instruction)

    def test_each_spec_can_build_its_exact_tool_registry(self):
        for spec in AGENT_SPECS.values():
            registry = create_tool_registry(
                new_run("multi", "黄金调查", "source_first"),
                lambda *args: None,
                allowed_names=spec.allowed_tools,
            )
            self.assertEqual(registry.names, set(spec.allowed_tools))
            self.assertTrue(registry.get(spec.output_tool).terminal)
            self.assertNotIn("submit_report", registry.names)

    def test_output_tool_must_be_allowed(self):
        with self.assertRaisesRegex(ValueError, "输出工具"):
            AgentSpec(
                name="错误配置",
                role="market",
                prompt_version="test-v1",
                instruction="测试",
                allowed_tools=frozenset({"read_url"}),
                budget=ResearchBudget(),
            )
