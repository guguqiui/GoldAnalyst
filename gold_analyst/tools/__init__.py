"""工具注册中心：新增工具后只需在这里实例化一次。"""
from collections.abc import Callable, Collection

from ..models import RunState
from .base import Tool, ToolContext, ToolRegistry
from .calculator import CalculateChangeTool
from .finding import SubmitFindingTool
from .report import SubmitReportTool
from .search import SearchSourcesTool
from .sge import SGEDataTool
from .verification import SubmitVerificationTool
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
    tools = [
        ReadURLTool(context),
        SGEDataTool(context),
        CalculateChangeTool(context),
        SearchSourcesTool(context),
        SubmitReportTool(context),
        SubmitFindingTool(context),
        SubmitVerificationTool(context),
    ]
    if allowed_names is None:
        # Single-Agent 保持原工具集合；中间产物工具只能由专业 Agent 显式申请。
        specialist_outputs = {"submit_finding", "submit_verification"}
        return ToolRegistry(tool for tool in tools if tool.name not in specialist_outputs)
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
    "SubmitFindingTool",
    "SubmitVerificationTool",
    "create_tool_registry",
    "parse_html",
    "validate_public_url",
]
