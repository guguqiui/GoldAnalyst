"""无网络、无 Key 的教学样例。所有价格与资料均为虚构，不是真实市场结论。"""
from .tools import ResearchTools
from .verification import validate_report

DEMO_CLAIM = "【虚构教学案例】上海金午盘基准价为 620 元/克，较早盘 625 元/克下跌，较上一交易日午盘 610 元/克上涨 2%。"


def demonstrate(run, emit):
    run["input"] = DEMO_CLAIM
    run["notice"] = "离线教学演示 · 所有价格和资料卡均为虚构；固定流程演示，不调用模型、不访问官网。"
    run["model"] = "未调用模型"
    run["strategy_version"] = "demo-fixed-1"
    tools = ResearchTools(run, emit)
    emit("拆解说法", "分别检查价格、早午盘比较、跨交易日涨跌幅")
    tools.evidence("教学新闻（虚构）", DEMO_CLAIM, kind="demo")
    emit("读取样例资料", "确认比较对象均为 SHAU 基准价、单位元/克，且区分早盘与午盘")
    tools.evidence("教学参考表（虚构，非交易所数据）",
                   "样例交易日 T：早盘 625.00，午盘 620.00。上一交易日 T-1：午盘 610.00。单位：元/克。合约：SHAU。",
                   kind="demo")
    emit("调用计算", "比较早盘 625.00 与午盘 620.00")
    first = tools.calculate_change("620", "625")
    emit("调用计算", "比较当前午盘 620.00 与上一交易日午盘 610.00")
    second = tools.calculate_change("620", "610")
    emit("审核", "发现新闻的 2% 与计算结果 1.64% 不一致")
    run["report"] = validate_report({
        "title": "一条新闻，三个可以核查的说法",
        "summary": "在虚构资料范围内，价格与下跌方向一致；跨交易日涨幅应为 1.64%，并非 2%。",
        "claims": [
            {"statement": "午盘基准价为 620 元/克", "verdict": "有证据支持",
             "reason": "与教学参考表午盘字段一致。此结论仅针对虚构样例。", "evidence_ids": ["E1", "E2"]},
            {"statement": "午盘价格较早盘下跌", "verdict": "有证据支持",
             "reason": f"620 − 625 = {first['difference']} 元/克，变动 {first['percent']}%。",
             "evidence_ids": ["E2", "E3"]},
            {"statement": "较上一交易日午盘上涨 2%", "verdict": "有证据反驳",
             "reason": f"(620 − 610) ÷ 610 × 100 = {second['percent']}%。按两位小数核验，与 2.00% 不符。",
             "evidence_ids": ["E2", "E4"]}],
        "unresolved": ["演示没有核验任何真实行情。切换到联网调查并配置 OpenAI Key，才能调查真实新闻。"],
        "review": "教学流程已检查比较口径与算术；未运行大模型审核。"}, run["evidence"])
    run["review_status"] = "教学规则检查，非模型审核"
    run["usage"]["tool_calls"] = 2
    return run
