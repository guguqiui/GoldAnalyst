"""所有工具共同遵守的最小协议。新增工具时只需继承 Tool。"""
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from _thread import LockType
from threading import Lock
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..models import RunState
from ..storage import now


def canonical_url(url: str) -> str:
    """忽略 fragment、尾部斜线和跟踪参数，识别同一个网页。"""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    query = urlencode(sorted(
        (key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ))
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, ""))


def urls_in_text(text: str) -> set[str]:
    """提取用户明确给出的 URL；它们是待核验材料，不是独立核验证据。"""
    matches = re.findall(r"https?://[^\s<>\"'\u3000\u4e00-\u9fff]+", text)
    return {canonical_url(url.rstrip(".,;:!?，。；：！？)]}）】")) for url in matches}


@dataclass
class ToolContext:
    """一次调查共享的状态和外部依赖，避免每个工具重复传参数。"""

    run: RunState
    emit: Callable[..., None]
    client: object | None = None
    model: str | None = None
    cache: dict[str, object] = field(default_factory=dict)
    lock: LockType = field(default_factory=Lock, repr=False)

    def is_target_url(self, url: str) -> bool:
        return bool(url) and canonical_url(url) in urls_in_text(self.run.get("input", ""))

    def add_evidence(
        self,
        title: str,
        text: str,
        url: str = "",
        kind: str = "source",
        **extra: object,
    ) -> dict[str, object]:
        with self.lock:
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

    def get_cached(self, key: str) -> object | None:
        with self.lock:
            return self.cache.get(key)

    def set_cached(self, key: str, value: object) -> None:
        with self.lock:
            self.cache[key] = value

    def add_search_usage(self, input_tokens: int, output_tokens: int) -> None:
        with self.lock:
            self.run["usage"]["input_tokens"] += input_tokens
            self.run["usage"]["output_tokens"] += output_tokens
            self.run["usage"]["search_requests"] += 1


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
