"""Deterministic first-pass scoring for structured GoldAnalyst run records."""

import json
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import CheckResult, EvaluationCase


def _text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).casefold()


def _canonical_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
        return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), parts.path.rstrip("/"), query, ""))
    except ValueError:
        return value.rstrip("/").casefold()


def _infrastructure_failures(run: dict[str, Any]) -> list[str]:
    known_failures = (
        "联网搜索需要配置 OpenAI API Key",
        "OpenAI Key 无效",
        "无法连接 OpenAI",
        "OpenAI 请求超时",
        "OpenAI 额度不足",
    )
    failures = []
    for event in run.get("events", []):
        if not isinstance(event, dict) or event.get("stage") not in {"工具受阻", "未完成"}:
            continue
        message = str(event.get("message", ""))
        if any(marker in message for marker in known_failures) and message not in failures:
            failures.append(message)
    return failures


def _find_claim(claims: list[dict[str, Any]], terms: list[str]) -> dict[str, Any] | None:
    ranked = sorted(
        ((sum(term.casefold() in _text(claim) for term in terms), claim) for claim in claims),
        key=lambda item: item[0],
        reverse=True,
    )
    return ranked[0][1] if ranked and ranked[0][0] > 0 else None


def _referenced_urls(run: dict[str, Any], claims: list[dict[str, Any]]) -> set[str]:
    referenced_ids = {
        evidence_id
        for claim in claims
        for evidence_id in claim.get("evidence_ids", [])
        if isinstance(evidence_id, str)
    }
    urls: set[str] = set()
    for evidence in run.get("evidence", []):
        if not isinstance(evidence, dict) or evidence.get("id") not in referenced_ids:
            continue
        if isinstance(evidence.get("url"), str):
            urls.add(_canonical_url(evidence["url"]))
        for citation in evidence.get("citations", []):
            if isinstance(citation, dict) and isinstance(citation.get("url"), str):
                urls.add(_canonical_url(citation["url"]))
    return urls


def _evaluate_check(
    check: dict[str, Any],
    case: EvaluationCase,
    run: dict[str, Any],
    report: dict[str, Any],
    claims: list[dict[str, Any]],
) -> tuple[bool, str]:
    check_type = check["type"]
    report_text = _text(report)
    if check_type == "verdict":
        claim = _find_claim(claims, check["match_terms"])
        actual = claim.get("verdict") if claim else None
        passed = actual == check["expected"]
        return passed, f"expected verdict {check['expected']}; actual {actual or 'missing'}"
    if check_type == "contains_all":
        missing = [value for value in check["values"] if value.casefold() not in report_text]
        return not missing, "all required values found" if not missing else "missing: " + ", ".join(missing)
    if check_type == "contains_any":
        found = [value for value in check["values"] if value.casefold() in report_text]
        return bool(found), "found: " + ", ".join(found) if found else "none of the alternatives were found"
    if check_type == "source_url":
        source_by_id = {source["id"]: source for source in case.sources}
        expected = {_canonical_url(source_by_id[source_id]["url"]) for source_id in check["source_ids"]}
        actual = _referenced_urls(run, claims)
        passed = bool(expected & actual)
        return passed, "referenced an accepted primary source" if passed else "no accepted primary source was cited"
    if check_type == "max_usage":
        usage = run.get("usage", {})
        exceeded = [
            f"{name}={usage.get(name, 'missing')} > {limit}"
            for name, limit in check["limits"].items()
            if not isinstance(usage.get(name), (int, float)) or usage[name] > limit
        ]
        return not exceeded, "within usage limits" if not exceeded else "; ".join(exceeded)
    raise ValueError(f"Unsupported check type: {check_type}")


def score_run(case: EvaluationCase, run: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(run, dict):
        raise ValueError("Run must be an object")
    report = run.get("report", run)
    if not isinstance(report, dict) or not isinstance(report.get("claims"), list):
        raise ValueError("Run must contain a report with claims")
    claims = [claim for claim in report["claims"] if isinstance(claim, dict)]
    results: list[CheckResult] = []
    caps: list[int] = []
    critical_errors: list[str] = []
    for check in case.checks:
        passed, detail = _evaluate_check(check, case, run, report, claims)
        failure_code = check.get("failure_code") if not passed else None
        score_cap = check.get("score_cap") if not passed else None
        if failure_code:
            critical_errors.append(failure_code)
        if score_cap is not None:
            caps.append(score_cap)
        results.append(CheckResult(
            id=check["id"],
            dimension=check["dimension"],
            passed=passed,
            earned=check["points"] if passed else 0,
            possible=check["points"],
            detail=detail,
            failure_code=failure_code,
            score_cap=score_cap,
        ))

    raw_score = sum(result.earned for result in results)
    calculated_score = min([raw_score, *caps]) if caps else raw_score
    invalid_reasons = _infrastructure_failures(run)
    final_score = None if invalid_reasons else calculated_score
    dimensions: dict[str, dict[str, int]] = {}
    for dimension in case.rubric["dimensions"]:
        dimension_results = [result for result in results if result.dimension == dimension["id"]]
        dimensions[dimension["id"]] = {
            "earned": sum(result.earned for result in dimension_results),
            "possible": dimension["points"],
        }
    return {
        "case_id": case.id,
        "valid": not invalid_reasons,
        "invalid_reasons": invalid_reasons,
        "score": final_score,
        "diagnostic_score": calculated_score,
        "raw_score": raw_score,
        "score_cap": min(caps) if caps else None,
        "dimensions": dimensions,
        "critical_errors": critical_errors,
        "checks": [result.as_dict() for result in results],
    }
