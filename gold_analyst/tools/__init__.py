"""工具注册中心：新增工具后只需在这里实例化一次。"""
from .base import Tool, ToolContext, ToolRegistry
from .calculator import CalculateChangeTool
from .news import ListNewsTool, NEWS_LIST, SAMPLE_URL
from .report import SubmitReportTool
from .search import SearchWebTool
from .sge import SGEDataTool
from .web import ReadURLTool, parse_html, validate_public_url


def create_tool_registry(run, emit, client=None, model=None):
    """绑定一次调查需要的全部工具以及共享上下文。"""
    context = ToolContext(run=run, emit=emit, client=client, model=model)
    read_url = ReadURLTool(context)
    return ToolRegistry(
        [
            read_url,
            ListNewsTool(context, read_url),
            SGEDataTool(context, read_url),
            CalculateChangeTool(context),
            SearchWebTool(context),
            SubmitReportTool(context),
        ]
    )


__all__ = [
    "Tool",
    "ToolContext",
    "ToolRegistry",
    "create_tool_registry",
    "parse_html",
    "validate_public_url",
    "NEWS_LIST",
    "SAMPLE_URL",
]
