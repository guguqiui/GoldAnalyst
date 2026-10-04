"""根据调查问题选择黄金来源候选集。"""

from .universes import SOURCE_UNIVERSES


# 这些是具体黄金品种；宏观驱动和新闻补充由后续规则追加。
MARKET_UNIVERSES = (
    "china_spot",
    "london_spot",
    "comex_futures",
    "gold_etf",
    "physical_retail",
)

CAUSE_KEYWORDS = (
    "为什么",
    "原因",
    "驱动",
    "上涨",
    "下跌",
    "涨价",
    "跌价",
    "影响",
)


def select_universes(question: str) -> list[str]:
    """返回问题需要使用的候选集名称，顺序就是搜索优先顺序。"""
    text = question.casefold()
    selected: list[str] = []

    for universe_name in MARKET_UNIVERSES:
        keywords = SOURCE_UNIVERSES[universe_name]["keywords"]
        if any(str(keyword).casefold() in text for keyword in keywords):
            selected.append(universe_name)

    # 中文用户只说“黄金”时，默认采用中国现货与上海金口径。
    if not selected:
        selected.append("china_spot")

    macro_keywords = SOURCE_UNIVERSES["macro_drivers"]["keywords"]
    needs_macro = any(keyword in text for keyword in CAUSE_KEYWORDS)
    needs_macro = needs_macro or any(str(keyword).casefold() in text for keyword in macro_keywords)
    if needs_macro:
        selected.append("macro_drivers")

    selected.append("discovery_news")
    return selected


def ranked_sources(question: str) -> list[dict[str, object]]:
    """合并所选候选集的来源；同一域名只保留优先出现的那一项。"""
    result: list[dict[str, object]] = []
    seen_domains: set[str] = set()
    for universe_name in select_universes(question):
        for source in SOURCE_UNIVERSES[universe_name]["sources"]:
            domain = str(source["domain"])
            if domain in seen_domains:
                continue
            seen_domains.add(domain)
            result.append({**source, "universe": universe_name})
    return result
