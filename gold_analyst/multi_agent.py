"""V2.1：三个隔离研究员并行调查，再由独立裁判合并证据与结论。"""
from __future__ import annotations

import copy
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .agent import investigate, safe_error
from .config import settings
from .llm import create_llm
from .models import DEFAULT_RESEARCH_BUDGET, ResearchBudget, RunState
from .prompts import JUDGE, STRATEGIES
from .server_state import blank_run
from .tools import create_tool_registry


def _source_key(item: dict[str, object]) -> str:
    """去掉 fragment 和常见跟踪参数；无 URL 的计算证据保持独立。"""
    url = item.get("url")
    if not isinstance(url, str) or not url:
        return ""
    parts = urlsplit(url)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_")])
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, ""))


def merge_candidates(candidates: list[RunState]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """合并同 URL 证据并同步重写每份候选报告的引用。"""
    merged: list[dict[str, object]] = []
    by_source: dict[str, str] = {}
    summaries: list[dict[str, object]] = []
    for candidate in candidates:
        id_map: dict[str, str] = {}
        for original in candidate.get("evidence", []):
            item = copy.deepcopy(original)
            key = _source_key(item)
            new_id = by_source.get(key) if key else None
            if new_id is None:
                new_id = f"E{len(merged) + 1}"
                item["id"] = new_id
                item["researchers"] = [candidate["strategy"]]
                merged.append(item)
                if key:
                    by_source[key] = new_id
            else:
                target = next(x for x in merged if x["id"] == new_id)
                researchers = target.setdefault("researchers", [])
                if candidate["strategy"] not in researchers:
                    researchers.append(candidate["strategy"])
            id_map[str(original["id"])] = new_id

        report = copy.deepcopy(candidate.get("report", {}))
        for claim in report.get("claims", []):
            claim["evidence_ids"] = list(dict.fromkeys(id_map[x] for x in claim.get("evidence_ids", []) if x in id_map))
        summaries.append({
            "strategy": candidate["strategy"],
            "strategy_name": STRATEGIES[candidate["strategy"]]["name"],
            "status": candidate.get("status", "completed"),
            "report": report,
            "usage": copy.deepcopy(candidate["usage"]),
            "evidence_count": len(candidate.get("evidence", [])),
            "error": candidate.get("error", ""),
        })
    return merged, summaries


def investigate_multi(
    run: RunState,
    emit: Callable[..., None],
    client: object | None = None,
    budget: ResearchBudget = DEFAULT_RESEARCH_BUDGET,
) -> RunState:
    cfg = settings()
    if client is None and not cfg["api_key"]:
        raise ValueError("请先在本地 .env 填写 OPENAI_API_KEY，或选择免 Key 教学演示。")

    strategies = tuple(STRATEGIES)
    emit("编排器", "并行启动来源、口径与反证三个独立研究员")

    def work(strategy: str) -> RunState:
        child = blank_run("live", run["input"], strategy, run_id=f"{run['id']}-{strategy}")
        child_emit = lambda stage, message, details=None: emit(f"{STRATEGIES[strategy]['name']}研究员", message, details)
        try:
            investigate(child, child_emit, client, budget, review=False)
            child["status"] = "completed"
        except Exception as exc:
            child["status"] = "failed"
            child["error"] = safe_error(exc)
            child_emit("受阻", child["error"])
        return child

    candidates: list[RunState] = []
    with ThreadPoolExecutor(max_workers=len(strategies)) as pool:
        futures = {pool.submit(work, strategy): strategy for strategy in strategies}
        for future in as_completed(futures):
            candidates.append(future.result())
    candidates.sort(key=lambda item: strategies.index(item["strategy"]))
    successful = [item for item in candidates if item.get("report")]
    if not successful:
        raise ValueError("三个研究员均未生成候选报告，请检查模型连接或缩小问题。")

    evidence, summaries = merge_candidates(candidates)
    run["evidence"] = evidence
    run["candidates"] = summaries
    for item in candidates:
        for key in run["usage"]:
            run["usage"][key] += item["usage"][key]

    emit("裁判 Agent", f"合并 {len(successful)} 份候选报告，并对 {len(evidence)} 条去重证据进行裁决")
    tools = create_tool_registry(run, emit, client, cfg["model"])
    report_tool = tools.get("submit_report")
    judge_input = json.dumps({"task": run["input"], "candidates": summaries, "evidence": evidence}, ensure_ascii=False)
    response = create_llm(cfg, client).respond(
        JUDGE,
        [{"role": "user", "content": judge_input}],
        [report_tool.schema()],
        {"type": "function", "name": "submit_report"},
    )
    run["usage"]["input_tokens"] += response.input_tokens
    run["usage"]["output_tokens"] += response.output_tokens
    calls = [call for call in response.tool_calls if call.name == "submit_report"]
    if not calls:
        raise ValueError("裁判 Agent 没有提交有效报告")
    final = report_tool.execute(**calls[0].arguments)
    if not isinstance(final, dict):
        raise ValueError("裁判报告必须为对象")
    run["report"] = final
    run["model"] = cfg["model"]
    run["strategy"] = "multi_agent"
    run["strategy_version"] = "2.1"
    run["review_status"] = f"Multi-Agent 裁判完成（{len(successful)}/{len(candidates)} 个研究员成功）"
    run["notice"] = "三名独立研究员并行调查并由裁判合并；模型裁决仍需人工复核。"
    return run
