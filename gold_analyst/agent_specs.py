"""专业 Agent 的职责、工具边界和预算配置。"""
from dataclasses import dataclass

from .models import ResearchBudget
from .schemas import AgentRole


@dataclass(frozen=True)
class AgentSpec:
    """一个可运行、可评测，也可被进化算法替换的 Agent 配置。"""

    name: str
    role: AgentRole
    prompt_version: str
    instruction: str
    allowed_tools: frozenset[str]
    budget: ResearchBudget
    output_tool: str = "submit_finding"

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.instruction.strip() or not self.prompt_version.strip():
            raise ValueError("Agent 名称、提示词版本和职责说明不能为空")
        if self.output_tool not in self.allowed_tools:
            raise ValueError("Agent 的输出工具必须包含在工具白名单中")


MARKET_AGENT = AgentSpec(
    name="行情研究员",
    role="market",
    prompt_version="market-v1",
    instruction=(
        "只负责确定黄金品种、时间范围、价格口径和涨跌幅。价格计算必须调用 calculate_change；"
        "无法确认品种或起止价格时，应在 unresolved 中说明，不得自行猜测。"
    ),
    allowed_tools=frozenset({"get_sge_data", "calculate_change", "read_url", "submit_finding"}),
    budget=ResearchBudget(rounds=5, tool_calls=10, parallel_tools=2, duration_seconds=180),
)


CAUSE_AGENT = AgentSpec(
    name="原因研究员",
    role="cause",
    prompt_version="cause-v1",
    instruction=(
        "只负责调查指定时间范围内黄金上涨或下跌的原因。优先读取原始机构资料，区分事实、"
        "相关性和推测；不得自行计算或编造行情涨幅。"
    ),
    allowed_tools=frozenset({"search_sources", "read_url", "submit_finding"}),
    budget=ResearchBudget(rounds=6, tool_calls=12, parallel_tools=3, duration_seconds=240),
)


VERIFICATION_AGENT = AgentSpec(
    name="独立核验员",
    role="verification",
    prompt_version="verification-v1",
    instruction=(
        "核验行情与原因研究员提交的发现：检查日期、品种、单位、计算、来源独立性和反面解释。"
        "可以补充检索或重新计算，但不得为了多数意见而忽略证据冲突。"
        "必须按 fact_id 逐条核验，每条 Fact 恰好返回一个结果。"
    ),
    allowed_tools=frozenset({
        "search_sources", "read_url", "get_sge_data", "calculate_change", "submit_verification",
    }),
    budget=ResearchBudget(rounds=6, tool_calls=12, parallel_tools=3, duration_seconds=240),
    output_tool="submit_verification",
)


AGENT_SPECS: dict[AgentRole, AgentSpec] = {
    spec.role: spec for spec in (MARKET_AGENT, CAUSE_AGENT, VERIFICATION_AGENT)
}


def get_agent_spec(role: AgentRole) -> AgentSpec:
    return AGENT_SPECS[role]
