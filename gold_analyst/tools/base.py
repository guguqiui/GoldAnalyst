"""所有工具共同遵守的最小协议。新增工具时只需继承 Tool。"""
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from ..models import RunState
from ..storage import now


@dataclass
class ToolContext:
    """一次调查共享的状态和外部依赖，避免每个工具重复传参数。"""

    run: RunState
    emit: Callable[..., None]
    client: object | None = None
    model: str | None = None
    cache: dict[str, object] = field(default_factory=dict)

    def add_evidence(
        self,
        title: str,
        text: str,
        url: str = "",
        kind: str = "source",
        **extra: object,
    ) -> dict[str, object]:
        item = {
            "id": f"E{len(self.run['evidence']) + 1}",
            "title": title,
            "text": text,
            "url": url,
            "kind": kind,
            "retrieved_at": now(),
            **extra,
        }
        self.run["evidence"].append(item)
        return item


class Tool(ABC):
    """工具基类：给模型看的 schema 与真正执行的 Python 方法放在一起。"""

    name: str
    description: str
    parameters: Mapping[str, object]
    terminal: bool = False

    def __init__(self, context: ToolContext):
        self.context = context

    def schema(self) -> dict[str, object]:
        """生成 OpenAI Responses API 所需的 function tool schema。"""
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": self.parameters,
                "required": list(self.parameters),
                "additionalProperties": False,
            },
        }

    @abstractmethod
    def execute(self, **kwargs: object) -> object:
        """执行工具并返回可被 JSON 序列化的结果。"""


class ToolRegistry:
    """集中注册、查找和调用工具；Agent 只依赖这个注册表。"""

    def __init__(self, tools: Iterable[Tool]):
        tool_list = list(tools)
        self._tools: dict[str, Tool] = {tool.name: tool for tool in tool_list}
        if len(self._tools) != len(tool_list):
            raise ValueError("工具名称不能重复")

    @property
    def names(self) -> set[str]:
        return set(self._tools)

    def schemas(self, include_terminal: bool = True) -> list[dict[str, object]]:
        return [tool.schema() for tool in self._tools.values() if include_terminal or not tool.terminal]

    def get(self, name: str) -> Tool:
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f"未知工具：{name}")
        return tool

    def execute(self, name: str, arguments: dict[str, object]) -> object:
        return self.get(name).execute(**arguments)
