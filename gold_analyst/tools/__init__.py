"""工具注册中心：新增工具后只需在这里实例化一次。"""
from collections.abc import Callable, Collection

from ..models import RunState
from .base import Tool, ToolContext, ToolRegistry
from .calculator import CalculateChangeTool
from .report import SubmitReportTool
from .search import SearchSourcesTool
from .sge import SGEDataTool
from .web import ReadURLTool, parse_html, validate_public_url


def create_tool_registry(
    run: RunState,
    emit: Callable[..., None],
    client: object | None = None,
    model: str | None = None,
    allowed_names: Collection[str] | None = None,
) -> ToolRegistry:
    """绑定工具；Multi-Agent 可用白名单形成真正的能力边界。"""
    context = ToolContext(run=run, emit=emit, client=client, model=model)
    read_url = ReadURLTool(context)
    tools = [
        read_url,
        SGEDataTool(context, read_url),
        CalculateChangeTool(context),
        SearchSourcesTool(context),
        SubmitReportTool(context),
    ]
    if allowed_names is None:
        return ToolRegistry(tools)
    allowed = set(allowed_names)
    known = {tool.name for tool in tools}
    unknown = allowed - known
    if unknown:
        raise ValueError("工具白名单包含未知工具：" + "、".join(sorted(unknown)))
    return ToolRegistry(tool for tool in tools if tool.name in allowed)


__all__ = [
    "Tool",
    "ToolContext",
    "ToolRegistry",
    "create_tool_registry",
    "parse_html",
    "validate_public_url",
]
