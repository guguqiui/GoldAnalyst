"""同花顺黄金新闻线索工具。"""
import re

from .base import Tool

NEWS_LIST = "https://invest.10jqka.com.cn/hj_list/"
SAMPLE_URL = "https://invest.10jqka.com.cn/20260824/c679225891.shtml"


class ListNewsTool(Tool):
    name = "list_news"
    description = "获取同花顺黄金新闻首页候选文章。"
    parameters = {"limit": {"type": "integer"}}

    def __init__(self, context, read_url_tool):
        super().__init__(context)
        self.read_url_tool = read_url_tool

    def execute(self, limit=10):
        limit = max(1, min(int(limit), 20))
        page = self.read_url_tool.execute(NEWS_LIST)
        seen, items = set(), []
        for link in page.get("links", []):
            if re.search(r"/20\d{6}/c\d+\.shtml", link["url"]) and link["url"] not in seen:
                items.append(link)
                seen.add(link["url"])
        return {
            "source_id": page["id"],
            "items": items[:limit],
            "note": "列表只提供线索。请读取选中文章，确认完整日期及转载来源。",
        }
