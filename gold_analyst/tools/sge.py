"""上海黄金交易所历史行情查询工具。"""
from datetime import date
from urllib.parse import urlencode

from .base import Tool


class SGEDataTool(Tool):
    name = "get_sge_data"
    description = "查询上金所历史表格，核对日期与定价轮次；不提供实时行情。"
    parameters = {
        "trade_date": {"type": "string", "description": "YYYY-MM-DD"},
        "category": {"type": "string", "enum": ["benchmark", "daily"]},
    }

    def __init__(self, context, read_url_tool):
        super().__init__(context)
        self.read_url_tool = read_url_tool

    def execute(self, trade_date, category="benchmark"):
        parsed_date = date.fromisoformat(trade_date)
        if parsed_date < date(2024, 1, 1) or parsed_date > date.today():
            raise ValueError("此历史数据入口仅查询 2024 年起且不晚于今天的日期")
        if category not in {"benchmark", "daily"}:
            raise ValueError("category 只能是 benchmark 或 daily")
        endpoint = "shanghaiAuAuto" if category == "benchmark" else "quotation_daily_new"
        query = urlencode({"start_date": trade_date, "end_date": trade_date})
        item = self.read_url_tool.execute(f"https://www.sge.com.cn/sjzx/{endpoint}?{query}")
        return {
            "evidence": item,
            "requested_date": trade_date,
            "note": (
                "必须检查实际表格日期和合约。benchmark 可能列出多轮定价，不能自动把任意轮次当最终基准价；"
                "页面为空、日期不符或未确认最终轮次时应继续查上海金基准价栏目或判证据不足。非实时行情。"
            ),
        }
