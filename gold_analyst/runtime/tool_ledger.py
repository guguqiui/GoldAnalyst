"""保存当前 Agent 运行内的成功工具结果，为后续上下文恢复提供依据。"""
from __future__ import annotations

import json
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field

from ..tools.base import tool_call_key


ToolCallKey = tuple[str, str]
FAILURE_BLOCK_THRESHOLD = 2
NO_PROGRESS_ROUND_LIMIT = 3


@dataclass
class ToolResultLedger:
    """只保存本次 ``investigate`` 的完整成功结果，不跨 Session。"""

    _results: dict[ToolCallKey, str] = field(default_factory=dict)
    _call_keys: dict[str, ToolCallKey] = field(default_factory=dict)
    _compacted: set[ToolCallKey] = field(default_factory=set)
    _failure_counts: dict[ToolCallKey, int] = field(default_factory=dict)
    _observations: set[tuple[str, str]] = field(default_factory=set)
    _round_has_new_observation: bool = False
    stalled_rounds: int = 0

    def has_succeeded(self, tool_name: str, arguments: Mapping[str, object]) -> bool:
        key = tool_call_key(tool_name, arguments)
        return key is not None and key in self._results

    def record_success(
        self,
        call_id: str,
        tool_name: str,
        arguments: Mapping[str, object],
        result: object,
    ) -> ToolCallKey | None:
        """保存未额外截断的 JSON 结果，并记录本次 call_id 的调用身份。"""
        key = tool_call_key(tool_name, arguments)
        if key is None:
            return None
        try:
            serialized = json.dumps(result, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            return None
        self._results[key] = serialized
        self._call_keys[call_id] = key
        self._compacted.discard(key)
        self._failure_counts.pop(key, None)
        observation = (tool_name, hashlib.sha256(serialized.encode("utf-8")).hexdigest())
        if observation not in self._observations:
            self._observations.add(observation)
            self._round_has_new_observation = True
        return key

    def record_failure(self, tool_name: str, arguments: Mapping[str, object]) -> int:
        """记录相同调用的失败次数；无法生成稳定身份时不累计。"""
        key = tool_call_key(tool_name, arguments)
        if key is None:
            return 0
        count = self._failure_counts.get(key, 0) + 1
        self._failure_counts[key] = count
        return count

    def failure_count(self, tool_name: str, arguments: Mapping[str, object]) -> int:
        key = tool_call_key(tool_name, arguments)
        return self._failure_counts.get(key, 0) if key is not None else 0

    def is_blocked(self, tool_name: str, arguments: Mapping[str, object]) -> bool:
        return self.failure_count(tool_name, arguments) >= FAILURE_BLOCK_THRESHOLD

    def key_for(self, tool_name: str, arguments: Mapping[str, object]) -> ToolCallKey | None:
        return tool_call_key(tool_name, arguments)

    def result_for_key(self, key: ToolCallKey) -> str | None:
        return self._results.get(key)

    def key_for_call(self, call_id: str) -> ToolCallKey | None:
        return self._call_keys.get(call_id)

    def mark_compacted(self, keys: set[ToolCallKey]) -> None:
        self._compacted.update(key for key in keys if key in self._results)

    def is_compacted(self, key: ToolCallKey) -> bool:
        return key in self._compacted

    def mark_restored(self, call_id: str, key: ToolCallKey) -> None:
        self._call_keys[call_id] = key
        self._compacted.discard(key)

    def finish_round(self) -> bool:
        """结束一轮并返回是否已连续多轮没有取得新工具观察。"""
        if self._round_has_new_observation:
            self.stalled_rounds = 0
        else:
            self.stalled_rounds += 1
        self._round_has_new_observation = False
        return self.stalled_rounds >= NO_PROGRESS_ROUND_LIMIT

    @property
    def result_count(self) -> int:
        return len(self._results)
