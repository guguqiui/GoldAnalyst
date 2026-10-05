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
    prompt_version="market-v2",
    instruction=(
        "只负责确定黄金品种、时间范围、价格口径和涨跌幅。价格计算必须调用 calculate_change；"
        "用户未指定中国现货黄金合约时使用 Au99.99。调用 get_sge_data 必须指定 contract，且只能比较"
        "该工具返回的同一合约 rows 与 previous_rows；comparison_ready=false 时不得计算涨跌。"
        "一次 get_sge_data 已同时返回当前和上一有效交易日，不得为了取得 previous_rows 再查询相邻日期。"
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
    prompt_version="verification-v3",
    instruction=(
        "按事实类型核验行情与原因研究员提交的发现。行情事实若已有一级官方来源，不再重新取数；"
        "只检查日期、品种、单位，并可用 calculate_change 复算。原因事实必须保留原始证据，"
        "再搜索并阅读至少一个与原证据不同域名的独立来源，才可判为 supported。"
        "必须先使用输入中的 dependency_findings 与 dependency_evidence；它们就是待核验上下文。"
        "搜索结果摘要只是线索，必须 read_url 后才能作为独立核验证据。"
        "可以重新计算，但不得为了多数意见而忽略证据冲突。"
        "价格比较必须确认两期数据的 contract 完全相同；不同合约之间不得计算涨跌。"
        "必须按 fact_id 逐条核验，每条 Fact 恰好返回一个结果。"
    ),
    allowed_tools=frozenset({
        "search_sources", "read_url", "calculate_change", "submit_verification",
    }),
    budget=ResearchBudget(rounds=6, tool_calls=12, parallel_tools=3, duration_seconds=240),
    output_tool="submit_verification",
)


AGENT_SPECS: dict[AgentRole, AgentSpec] = {
    spec.role: spec for spec in (MARKET_AGENT, CAUSE_AGENT, VERIFICATION_AGENT)
}


def get_agent_spec(role: AgentRole) -> AgentSpec:
    return AGENT_SPECS[role]
