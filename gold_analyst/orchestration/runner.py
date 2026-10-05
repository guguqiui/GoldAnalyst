"""按 TaskPlan 的依赖关系调度专业 Agent。"""
from __future__ import annotations

import copy
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..agent_specs import get_agent_spec
from ..models import RunState
from ..schemas import Finding, PlanTask, TaskPlan
from ..specialist import run_specialist
from ..context import ContextBuilder
from .validation import validate_task_plan


SpecialistRunner = Callable[..., RunState]
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "msclkid"}


def _evidence_key(item: dict[str, object]) -> str:
    """同一网页的跟踪参数不应产生新证据；无 URL 证据不在这里合并。"""
    url = item.get("url")
    if not isinstance(url, str) or not url.strip():
        return ""
    parts = urlsplit(url.strip())
    query = sorted(
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_") and key.casefold() not in TRACKING_QUERY_KEYS
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), path, urlencode(query), ""))


def _enrich_existing_evidence(target: dict[str, object], incoming: dict[str, object]) -> None:
    """去重时保留更完整的正文和更高的来源等级。"""
    target_text = target.get("text")
    incoming_text = incoming.get("text")
    if isinstance(incoming_text, str) and (
        not isinstance(target_text, str) or len(incoming_text) > len(target_text)
    ):
        target["text"] = incoming_text

    target_tier = target.get("source_tier")
    incoming_tier = incoming.get("source_tier")
    if isinstance(incoming_tier, int) and (
        not isinstance(target_tier, int) or incoming_tier < target_tier
    ):
        target["source_tier"] = incoming_tier

    for field in ("title", "kind", "retrieved_at"):
        if not target.get(field) and incoming.get(field):
            target[field] = incoming[field]


def _dependency_context(
    task: PlanTask,
    completed: dict[str, RunState],
    evidence: list[dict[str, object]],
) -> tuple[list[Finding], list[dict[str, object]]]:
    return ContextBuilder().dependency_context(task, completed, evidence)


def _merge_child(run: RunState, child: RunState) -> None:
    """将子 Agent 的新证据改成父运行内唯一的 E 编号。"""
    parent_evidence = run.setdefault("evidence", [])
    existing_by_id = {str(item.get("id")): item for item in parent_evidence}
    existing_by_key = {_evidence_key(item): item for item in parent_evidence if _evidence_key(item)}
    id_map: dict[str, str] = {}

    for original in child.get("evidence", []):
        old_id = str(original.get("id", ""))
        key = _evidence_key(original)
        duplicate = existing_by_key.get(key) if key else None
        if duplicate is not None:
            _enrich_existing_evidence(duplicate, original)
            if old_id:
                id_map[old_id] = str(duplicate["id"])
            continue
        if old_id in existing_by_id and existing_by_id[old_id] == original:
            id_map[old_id] = old_id
            continue
        item = copy.deepcopy(original)
        new_id = f"E{len(parent_evidence) + 1}"
        item["id"] = new_id
        parent_evidence.append(item)
        existing_by_id[new_id] = item
        if key:
            existing_by_key[key] = item
        if old_id:
            id_map[old_id] = new_id

    if "finding" in child:
        finding = copy.deepcopy(child["finding"])
        finding["evidence_ids"] = [id_map.get(item, item) for item in finding.get("evidence_ids", [])]
        child["finding"] = finding
        run.setdefault("findings", []).append(finding)
    if "verification_result" in child:
        verification = copy.deepcopy(child["verification_result"])
        for fact_result in verification.get("fact_results", []):
            for field in ("supporting_evidence_ids", "contradicting_evidence_ids"):
                fact_result[field] = [
                    id_map.get(item, item) for item in fact_result.get(field, [])
                ]
        run["verification_result"] = verification

    for key in run["usage"]:
        run["usage"][key] += child["usage"][key]
    run.setdefault("message_files", []).extend(child.get("message_files", []))


def run_task_plan(
    run: RunState,
    plan: TaskPlan,
    emit: Callable[..., None],
    client: object | None = None,
    specialist_runner: SpecialistRunner = run_specialist,
) -> RunState:
    """并行执行已就绪任务，再将结构化结果交给依赖它的任务。"""
    validate_task_plan(plan)
    run["plan"] = copy.deepcopy(plan)
    run["findings"] = []
    pending = {task["id"]: task for task in plan["tasks"]}
    completed: dict[str, RunState] = {}
    order = {task["id"]: index for index, task in enumerate(plan["tasks"])}

    while pending:
        ready = [task for task in pending.values() if set(task["depends_on"]) <= completed.keys()]
        ready.sort(key=lambda task: order[task["id"]])
        emit("编排器", "启动已就绪任务：" + "、".join(task["id"] for task in ready))

        def execute(task: PlanTask) -> tuple[str, RunState]:
            findings, evidence = _dependency_context(task, completed, run["evidence"])
            child = specialist_runner(
                run,
                task,
                get_agent_spec(task["agent"]),
                emit,
                client,
                findings,
                evidence,
            )
            return task["id"], child

        with ThreadPoolExecutor(max_workers=len(ready)) as pool:
            results = dict(pool.map(execute, ready))

        # 并行完成顺序不稳定；按 TaskPlan 顺序合并，保证记录可重现。
        for task in ready:
            task_id = task["id"]
            child = results[task_id]
            _merge_child(run, child)
            completed[task_id] = child
            del pending[task_id]

    run["review_status"] = "专业 Agent 与独立核验已完成，待生成最终报告"
    return run
