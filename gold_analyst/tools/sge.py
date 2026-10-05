"""上海黄金交易所历史行情工具。"""
from datetime import date, timedelta
import json
import re
from urllib.parse import urlencode

from .base import Tool
from .web import fetch, parse_html


LOOKBACK_DAYS = 14

DAILY_FIELDS = (
    "trade_date", "contract", "open", "high", "low", "close", "change",
    "change_percent", "weighted_average", "volume_kg", "turnover_cny",
    "open_interest_lots", "delivery_direction", "delivery_lots",
)
BENCHMARK_FIELDS = (
    "serial", "trade_date", "contract", "session", "round", "price",
    "bid_volume", "ask_volume", "supplemental_balance",
)


def _normalized_date(value: str) -> str:
    text = value.strip().replace("/", "-")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return ""
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return ""


def _market_rows(tables: object, category: str) -> list[dict[str, str]]:
    """只接受包含合法交易日期的数据行，不把表头和提示文案当行情。"""
    fields = BENCHMARK_FIELDS if category == "benchmark" else DAILY_FIELDS
    date_index = 1 if category == "benchmark" else 0
    result: list[dict[str, str]] = []
    if not isinstance(tables, list):
        return result
    for table in tables:
        if not isinstance(table, list):
            continue
        for raw_row in table:
            if not isinstance(raw_row, list) or len(raw_row) < len(fields):
                continue
            values = [str(value).strip() for value in raw_row[:len(fields)]]
            trade_date = _normalized_date(values[date_index])
            if not trade_date:
                continue
            values[date_index] = trade_date
            result.append(dict(zip(fields, values)))
    return result


def _has_price(row: dict[str, str], category: str) -> bool:
    value = row.get("price" if category == "benchmark" else "close", "").strip()
    try:
        return value not in {"", "-"} and float(value) > 0
    except ValueError:
        return False


class SGEDataTool(Tool):
    name = "get_sge_data"
    repeatable = True
    description = (
        "查询上金所历史行情。请求日无交易时自动返回此前最近交易日，并明确 requested_date 与 effective_date；"
        "daily 返回每日合约行情，benchmark 返回上海金基准价各轮次。"
    )
    parameters = {
        "trade_date": {"type": "string", "description": "YYYY-MM-DD"},
        "category": {"type": "string", "enum": ["benchmark", "daily"]},
        "contract": {
            "type": "string",
            "description": "必须指定同一合约；未指定品种的中国现货黄金问题使用 Au99.99，基准价使用 SHAU",
        },
    }

    def execute(self, trade_date, category, contract):
        requested = date.fromisoformat(trade_date)
        if requested < date(2024, 1, 1) or requested > date.today():
            raise ValueError("此历史数据入口仅查询 2024 年起且不晚于今天的日期")
        if category not in {"benchmark", "daily"}:
            raise ValueError("category 只能是 benchmark 或 daily")
        if not isinstance(contract, str) or not contract.strip():
            raise ValueError("contract 不能为空；未指定品种时 daily 使用 Au99.99，benchmark 使用 SHAU")
        contract = contract.strip()

        start = max(date(2024, 1, 1), requested - timedelta(days=LOOKBACK_DAYS))
        endpoint = "shanghaiAuAuto" if category == "benchmark" else "quotation_daily_new"
        query = urlencode({
            "start_date": start.isoformat(),
            "end_date": requested.isoformat(),
            "inst_ids": "",
            "p": "",
        })
        url = f"https://www.sge.com.cn/sjzx/{endpoint}?{query}"
        data, content_type, resolved_url = fetch(url)
        if "html" not in content_type and content_type:
            raise ValueError("上金所历史行情未返回 HTML 页面")
        parsed = parse_html(data, resolved_url)
        rows = _market_rows(parsed.get("tables"), category)
        contract_rows = [
            row for row in rows
            if row["contract"].casefold() == contract.casefold() and _has_price(row, category)
        ]
        available_dates = sorted({
            row["trade_date"] for row in contract_rows if row["trade_date"] <= trade_date
        })
        effective_date = available_dates[-1] if available_dates else ""
        previous_effective_date = available_dates[-2] if len(available_dates) >= 2 else ""
        selected = [row for row in contract_rows if row["trade_date"] == effective_date]
        previous_selected = [row for row in contract_rows if row["trade_date"] == previous_effective_date]
        fallback_applied = bool(effective_date and effective_date != trade_date)

        summary = {
            "requested_date": trade_date,
            "effective_date": effective_date,
            "previous_effective_date": previous_effective_date,
            "fallback_applied": fallback_applied,
            "category": category,
            "contract": contract,
            "unit": "人民币元/克",
            "rows": selected,
            "previous_rows": previous_selected,
            "comparison_ready": bool(selected and previous_selected),
        }
        if selected:
            text = "上金所结构化行情：" + json.dumps(summary, ensure_ascii=False)
        else:
            text = f"上金所在 {start.isoformat()} 至 {trade_date} 的查询结果中没有返回可解析的数据行。"
        evidence = self.context.add_evidence(
            title="上海黄金交易所历史行情",
            text=text,
            url=resolved_url,
            kind="source",
            published_at=effective_date or "无可用交易日",
            tables=[list(DAILY_FIELDS if category == "daily" else BENCHMARK_FIELDS)]
                   + [[row[field] for field in (DAILY_FIELDS if category == "daily" else BENCHMARK_FIELDS)]
                      for row in selected + previous_selected],
            source_domain="sge.com.cn",
            source_name="上海黄金交易所",
            source_tier=1,
            source_universe="china_spot",
            evidence_usage="primary",
        )
        return {
            **summary,
            "no_data": not selected,
            "evidence": evidence,
            "note": (
                "fallback_applied=true 表示请求日无可用行情，必须使用 effective_date 描述实际交易日。"
                "rows 与 previous_rows 已被工具锁定为同一 contract；comparison_ready=false 时不得计算涨跌。"
                "daily 的不同合约不可混用；benchmark 的每行只代表对应场次和轮次，不得擅称最终基准价。"
            ),
        }
