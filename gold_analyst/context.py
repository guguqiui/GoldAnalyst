"""为专业 Agent 构造本次运行内可追溯、受预算约束的上下文。"""
from __future__ import annotations

import copy
from dataclasses import dataclass

from .models import RunState
from .schemas import Finding, PlanTask


MAX_EVIDENCE_TEXT_CHARS = 6_000
MAX_TOTAL_EVIDENCE_TEXT_CHARS = 18_000
MAX_TABLE_ROWS = 12
MAX_CITATIONS = 10


@dataclass(frozen=True)
class SpecialistContext:
    """模型读取紧凑副本；工具和校验器继续持有完整证据。"""

    payload: dict[str, object]
    full_evidence: list[dict[str, object]]
    manifest: dict[str, object]


def _excerpt(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    if limit < 200:
        return text[:limit], True
    tail = min(1_000, limit // 4)
    head = limit - tail
    return (
        text[:head]
        + "\n…[上下文中间部分已省略，可调用 get_evidence 按证据编号读取完整正文]…\n"
        + text[-tail:]
    ), True


class ContextBuilder:
    """集中决定专业 Agent 看见哪些前序事实和证据。"""

    def dependency_context(
        self,
        task: PlanTask,
        completed: dict[str, RunState],
        evidence: list[dict[str, object]],
    ) -> tuple[list[Finding], list[dict[str, object]]]:
        findings = [
            copy.deepcopy(completed[task_id]["finding"])
            for task_id in task["depends_on"]
            if "finding" in completed[task_id]
        ]
        referenced_ids = {
            evidence_id
            for finding in findings
            for evidence_id in finding.get("evidence_ids", [])
        }
        selected = [
            copy.deepcopy(item) for item in evidence if item.get("id") in referenced_ids
        ]
        return findings, selected

    def build_specialist_context(
        self,
        parent: RunState,
        task: PlanTask,
        findings: list[Finding],
        evidence: list[dict[str, object]],
    ) -> SpecialistContext:
        by_id = {
            str(item.get("id")): copy.deepcopy(item)
            for item in evidence
            if isinstance(item, dict) and item.get("id")
        }
        referenced_ids = list(dict.fromkeys(
            str(evidence_id)
            for finding in findings
            for evidence_id in finding.get("evidence_ids", [])
        ))
        selected_ids = [evidence_id for evidence_id in referenced_ids if evidence_id in by_id]
        full_evidence = [by_id[evidence_id] for evidence_id in selected_ids]
        missing_ids = [evidence_id for evidence_id in referenced_ids if evidence_id not in by_id]

        compact_evidence: list[dict[str, object]] = []
        truncated_ids: list[str] = []
        remaining_text = MAX_TOTAL_EVIDENCE_TEXT_CHARS
        for original in full_evidence:
            compact = {
                key: copy.deepcopy(value)
                for key, value in original.items()
                if key not in {"text", "tables", "links", "citations"}
            }
            text = original.get("text")
            if isinstance(text, str):
                allowance = min(MAX_EVIDENCE_TEXT_CHARS, max(remaining_text, 0))
                excerpt, truncated = _excerpt(text, allowance)
                compact["text"] = excerpt
                remaining_text -= len(excerpt)
                if truncated:
                    truncated_ids.append(str(original["id"]))
            tables = original.get("tables")
            if isinstance(tables, list):
                compact["tables"] = copy.deepcopy(tables[:MAX_TABLE_ROWS])
            citations = original.get("citations")
            if isinstance(citations, list):
                compact["citations"] = copy.deepcopy(citations[:MAX_CITATIONS])
            compact_evidence.append(compact)

        plan = parent.get("plan", {}) if isinstance(parent.get("plan"), dict) else {}
        manifest: dict[str, object] = {
            "finding_count": len(findings),
            "fact_count": sum(len(finding.get("facts", [])) for finding in findings),
            "evidence_ids": selected_ids,
            "missing_evidence_ids": missing_ids,
            "truncated_evidence_ids": truncated_ids,
        }
        payload: dict[str, object] = {
            "question": parent["input"],
            "task": task,
            "market": plan.get("market", ""),
            "time_intent": plan.get("time_intent", {}),
            "time_range": plan.get("time_range", {}),
            "dependency_findings": copy.deepcopy(findings),
            "dependency_evidence": compact_evidence,
            "context_manifest": manifest,
        }
        return SpecialistContext(payload, full_evidence, manifest)
