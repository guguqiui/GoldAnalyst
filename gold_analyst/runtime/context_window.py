"""不调用模型的第一层上下文压缩：清理较老的工具正文。"""
from __future__ import annotations

import json

from .tool_ledger import ToolCallKey, ToolResultLedger


COMPACTED_STATE = "tool_result_compacted"


def _is_tool_output(message: object) -> bool:
    return isinstance(message, dict) and message.get("type") == "function_call_output"


def _is_compacted(output: object) -> bool:
    if not isinstance(output, str):
        return False
    try:
        payload = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(payload, dict) and payload.get("_context_state") == COMPACTED_STATE


def estimate_message_chars(messages: list[object]) -> int:
    """粗略计算动态消息大小；这里只用于决定是否执行零成本压缩。"""
    total = 0
    for message in messages:
        if isinstance(message, dict):
            total += len(str(message.get("content", "")))
            total += len(str(message.get("output", "")))
        else:
            total += len(str(message))
    return total


def readable_success_keys(
    messages: list[object],
    ledger: ToolResultLedger,
) -> set[ToolCallKey]:
    """找出当前消息里仍保留完整正文的成功工具调用。"""
    readable: set[ToolCallKey] = set()
    for message in messages:
        if not _is_tool_output(message) or _is_compacted(message.get("output")):
            continue
        call_id = message.get("call_id")
        if not isinstance(call_id, str):
            continue
        key = ledger.key_for_call(call_id)
        if key is not None:
            readable.add(key)
    return readable


def microcompact(
    messages: list[object],
    ledger: ToolResultLedger,
    *,
    char_limit: int,
    keep_recent: int,
) -> set[ToolCallKey]:
    """超过限制时压缩旧结果，并返回本次刚从上下文消失的调用身份。"""
    if estimate_message_chars(messages) <= char_limit:
        return set()
    candidates = [
        message for message in messages
        if _is_tool_output(message)
        and not _is_compacted(message.get("output"))
        and isinstance(message.get("call_id"), str)
        and ledger.key_for_call(message["call_id"]) is not None
    ]
    if len(candidates) <= keep_recent:
        return set()

    readable_before = readable_success_keys(messages, ledger)
    for message in candidates[:-keep_recent]:
        output = str(message.get("output", ""))
        message["output"] = json.dumps({
            "_context_state": COMPACTED_STATE,
            "original_chars": len(output),
            "message": "完整工具结果已从模型上下文移除，但仍保存在本次运行账本中。",
        }, ensure_ascii=False)
    lost = readable_before - readable_success_keys(messages, ledger)
    ledger.mark_compacted(lost)
    return lost
