"""项目内的本地运行数据；整个 .local 目录不会提交到 Git。"""
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from .config import ROOT

LOCAL_ROOT = ROOT / ".local"


def _jsonable(value):
    """把 OpenAI Pydantic 对象和测试对象转换成可读 JSON。"""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if hasattr(value, "__dict__"):
        return {key: _jsonable(item) for key, item in vars(value).items() if not key.startswith("_")}
    return repr(value)


def _atomic_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def save_llm_turn(run_id: str, sequence: int, label: str, model: str, request, response) -> str:
    """将一轮发给模型的完整消息与原始返回成对保存。"""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
        raise ValueError("无效的 run id，不能创建本地轨迹目录")
    path = LOCAL_ROOT / "runs" / run_id / "messages" / f"{sequence:03d}.json"
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "sequence": sequence,
        "label": label,
        "model": model,
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "message": {
            "agent": _jsonable(request),
            # raw_response 是 SDK Response.model_dump() 的完整结果，没有先做语义裁剪。
            "llm_raw_response": _jsonable(response.raw_response),
            "llm_parsed": {
                "output": _jsonable(response.history_items),
                "tool_calls": _jsonable(response.tool_calls),
                "usage": {"input_tokens": response.input_tokens, "output_tokens": response.output_tokens},
            },
        },
    }
    _atomic_json(path, payload)
    return str(path.relative_to(ROOT))


def save_local_run(run, report_markdown: str) -> None:
    """把最终运行和报告镜像到同一个 UUID 目录，便于按一次调查回看。"""
    run_dir = LOCAL_ROOT / "runs" / run["id"]
    _atomic_json(run_dir / "run.json", _jsonable(run))
    if run.get("report"):
        _atomic_json(run_dir / "report.json", _jsonable(run["report"]))
        path = run_dir / "report.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".md.tmp")
        temporary.write_text(report_markdown, encoding="utf-8")
        temporary.replace(path)
