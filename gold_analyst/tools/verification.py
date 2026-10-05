"""核验 Agent 用来提交逐事实结果的终止型工具。"""
from typing import cast
from urllib.parse import urlsplit

from ..schemas import VerificationResult
from .base import Tool


STRING = {"type": "string"}
VERDICTS = ["supported", "partial", "contradicted", "insufficient"]


def _source_identity(evidence: dict[str, object]) -> str:
    """用来源域名识别独立来源；无域名的计算和搜索摘要不算来源。"""
    domain = evidence.get("source_domain")
    if isinstance(domain, str) and domain.strip():
        return domain.lower().removeprefix("www.")
    url = evidence.get("url")
    if isinstance(url, str) and url:
        return (urlsplit(url).hostname or "").lower().removeprefix("www.")
    return ""


def _is_read_source(evidence: dict[str, object]) -> bool:
    return (
        evidence.get("kind") not in {"search", "calculation"}
        and evidence.get("evidence_usage") not in {"clue_only", "target_material"}
        and bool(_source_identity(evidence))
    )


class SubmitVerificationTool(Tool):
    name = "submit_verification"
    description = "逐条提交前序 Fact 的核验结果、支持证据、反驳证据和未解决问题。"
    terminal = True
    parameters = {
        "fact_results": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "fact_id": STRING,
                    "verdict": {"type": "string", "enum": VERDICTS},
                    "reason": STRING,
                    "supporting_evidence_ids": {"type": "array", "items": STRING},
                    "contradicting_evidence_ids": {"type": "array", "items": STRING},
                    "unresolved": {"type": "array", "items": STRING},
                },
                "required": [
                    "fact_id", "verdict", "reason", "supporting_evidence_ids",
                    "contradicting_evidence_ids", "unresolved",
                ],
            },
        },
        "conflicts": {"type": "array", "items": STRING},
        "unresolved": {"type": "array", "items": STRING},
    }

    def execute(self, **result: object) -> VerificationResult:
        for field in ("conflicts", "unresolved"):
            value = result.get(field)
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f"{field} 必须是字符串数组")

        fact_results = result.get("fact_results")
        if not isinstance(fact_results, list):
            raise ValueError("fact_results 必须是数组")
        fact_roles = {
            str(fact.get("fact_id")): str(finding.get("agent", ""))
            for finding in self.context.run.get("findings", [])
            if isinstance(finding, dict)
            for fact in finding.get("facts", [])
            if isinstance(fact, dict) and fact.get("fact_id")
        }
        known_fact_ids = set(fact_roles)
        evidence_by_id = {
            str(item.get("id")): item
            for item in self.context.run.get("evidence", [])
            if isinstance(item, dict) and item.get("id")
        }
        known_evidence_ids = set(evidence_by_id)
        original_evidence_by_fact = {
            str(fact.get("fact_id")): {
                str(evidence_id) for evidence_id in finding.get("evidence_ids", [])
            }
            for finding in self.context.run.get("findings", [])
            if isinstance(finding, dict)
            for fact in finding.get("facts", [])
            if isinstance(fact, dict) and fact.get("fact_id")
        }
        seen: set[str] = set()
        normalized: list[dict[str, object]] = []

        for item in fact_results:
            if not isinstance(item, dict):
                raise ValueError("fact_results 中的每一项都必须是对象")
            fact_id = item.get("fact_id")
            verdict = item.get("verdict")
            reason = item.get("reason")
            if not isinstance(fact_id, str) or not fact_id:
                raise ValueError("fact_id 不能为空")
            if fact_id in seen:
                raise ValueError("同一 Fact 不能重复核验：" + fact_id)
            if verdict not in VERDICTS:
                raise ValueError("未知的 Fact 核验结果")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError(f"Fact {fact_id} 的 reason 不能为空")
            for field in ("supporting_evidence_ids", "contradicting_evidence_ids", "unresolved"):
                value = item.get(field)
                if not isinstance(value, list) or not all(isinstance(entry, str) for entry in value):
                    raise ValueError(f"Fact {fact_id} 的 {field} 必须是字符串数组")

            supporting = cast(list[str], item["supporting_evidence_ids"])
            contradicting = cast(list[str], item["contradicting_evidence_ids"])
            overlap = set(supporting) & set(contradicting)
            if overlap:
                raise ValueError(f"Fact {fact_id} 的同一证据不能同时支持和反驳")
            unknown_evidence = (set(supporting) | set(contradicting)) - known_evidence_ids
            if unknown_evidence:
                raise ValueError("核验结果引用了不存在的证据：" + "、".join(sorted(unknown_evidence)))
            if verdict == "supported" and not supporting:
                raise ValueError(f"Fact {fact_id} 判为 supported 时必须有支持证据")
            if verdict == "contradicted" and not contradicting:
                raise ValueError(f"Fact {fact_id} 判为 contradicted 时必须有反驳证据")
            if verdict == "partial" and not supporting and not contradicting:
                raise ValueError(f"Fact {fact_id} 判为 partial 时必须有证据")
            if verdict == "supported":
                originals = original_evidence_by_fact.get(fact_id, set())
                original_support = set(supporting) & originals
                role = fact_roles.get(fact_id)
                if not original_support:
                    raise ValueError(f"Fact {fact_id} 必须保留前序 Agent 的原始证据")
                if role == "market" and not any(
                    evidence_by_id[evidence_id].get("source_tier") == 1
                    for evidence_id in original_support
                ):
                    raise ValueError(f"行情 Fact {fact_id} 判为 supported 时必须引用一级官方证据")
                if role == "cause":
                    original_sources = {
                        _source_identity(evidence_by_id[evidence_id])
                        for evidence_id in original_support
                        if _is_read_source(evidence_by_id[evidence_id])
                    }
                    corroborating_sources = {
                        _source_identity(evidence_by_id[evidence_id])
                        for evidence_id in set(supporting) - originals
                        if _is_read_source(evidence_by_id[evidence_id])
                    }
                    if not original_sources:
                        raise ValueError(f"原因 Fact {fact_id} 的原始支持证据必须是已阅读网页")
                    if not (corroborating_sources - original_sources):
                        raise ValueError(
                            f"原因 Fact {fact_id} 判为 supported 时必须新增不同域名的已阅读来源"
                        )
            seen.add(fact_id)
            normalized.append(dict(item))

        unknown = seen - known_fact_ids
        if unknown:
            raise ValueError("核验结果引用了不存在的 Fact：" + "、".join(sorted(unknown)))
        missing = known_fact_ids - seen
        if missing:
            raise ValueError("核验结果遗漏了 Fact：" + "、".join(sorted(missing)))

        verdicts = [str(item["verdict"]) for item in normalized]
        if verdicts and all(verdict == "supported" for verdict in verdicts):
            status = "passed"
        elif verdicts and all(verdict == "contradicted" for verdict in verdicts):
            status = "failed"
        elif not verdicts or all(verdict == "insufficient" for verdict in verdicts):
            status = "insufficient"
        else:
            status = "partial"
        return cast(VerificationResult, {
            "status": status,
            "fact_results": normalized,
            "conflicts": result["conflicts"],
            "unresolved": result["unresolved"],
        })
