"""所有工具共同遵守的最小协议。新增工具时只需继承 Tool。"""
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from _thread import LockType
from threading import Lock
import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..models import RunState
from ..persistence.reports import now


def canonical_url(url: str) -> str:
    """忽略 www、fragment、尾部斜线和跟踪参数，识别同一个网页。"""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    query = urlencode(sorted(
        (key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ))
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return urlunsplit((parts.scheme.lower(), host, parts.path.rstrip("/"), query, ""))


def urls_in_text(text: str) -> set[str]:
    """提取用户明确给出的 URL；它们是待核验材料，不是独立核验证据。"""
    matches = re.findall(r"https?://[^\s<>\"'\u3000\u4e00-\u9fff]+", text)
    return {canonical_url(url.rstrip(".,;:!?，。；：！？)]}）】")) for url in matches}


def _normalize_call_value(value: object, field: str = "") -> object:
    """规范化工具参数；只处理不改变参数语义的差异。"""
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_call_value(item, str(key))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_call_value(item) for item in value]
    if field == "url" and isinstance(value, str):
        return canonical_url(value)
    return value


def tool_call_key(
    tool_name: str,
    arguments: Mapping[str, object],
) -> tuple[str, str] | None:
    """返回稳定的 ``(工具名, 参数 JSON)``；无法序列化时不生成身份。"""
    try:
        canonical_arguments = json.dumps(
            _normalize_call_value(arguments),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return None
    return tool_name, canonical_arguments


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
        question = self.run.get("original_question", self.run.get("input", ""))
        return bool(url) and canonical_url(url) in urls_in_text(str(question))

    def is_excluded_source_url(self, url: str) -> bool:
        """判断 URL 是否属于前序 Agent 已经使用过的证据文章。"""
        excluded = {
            canonical_url(item)
            for item in self.run.get("excluded_source_urls", [])
            if isinstance(item, str) and item
        }
        return bool(url) and canonical_url(url) in excluded

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
    """工具基类：schema、执行方法以及上下文复用策略放在一起。"""

    name: str
    description: str
    parameters: Mapping[str, object]
    terminal: bool = False
    # 是否只读取外部世界；写操作成功后，未来的只读缓存应全部失效。
    is_readonly: bool = True
    # 是否允许模型在正常流程中用相同或不同参数再次调用。
    repeatable: bool = False
    # 相同参数是否始终产生同一个逻辑结果，可直接复用确定性缓存。
    deterministic: bool = False
    # 非确定性只读结果从消息中消失后，是否允许恢复本次 run 的旧结果。
    replay_after_compaction: bool = False

    def __init__(self, context: ToolContext):
        self.context = context

    def skip_reason(self, **kwargs: object) -> str | None:
        """执行前的确定性拦截；返回原因时不执行工具，也不消耗预算。"""
        return None

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
