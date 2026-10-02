"""Strict loading and structural validation for human-reviewed eval cases."""

import json
from pathlib import Path
from typing import Any

from ..verification import VERDICTS
from .models import EvaluationCase


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASE_STATUSES = {"draft", "reviewed", "retired"}
CHECK_TYPES = {"verdict", "contains_all", "contains_any", "source_url", "max_usage"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) and item for item in value)


def _validate_case(data: Any, path: Path) -> None:
    label = path.name
    _require(isinstance(data, dict), f"{label}: case must be a JSON object")
    for field in ("schema_version", "id", "title", "status", "task", "sources", "oracle", "rubric", "checks"):
        _require(field in data, f"{label}: missing field {field}")
    _require(data["schema_version"] == "1.0", f"{label}: unsupported schema_version")
    _require(isinstance(data["id"], str) and data["id"], f"{label}: invalid id")
    _require(data["status"] in CASE_STATUSES, f"{label}: invalid status")
    _require(isinstance(data["task"], dict) and isinstance(data["task"].get("input"), str),
             f"{label}: task.input must be text")

    sources = data["sources"]
    _require(isinstance(sources, list) and sources, f"{label}: sources must not be empty")
    source_ids: set[str] = set()
    for source in sources:
        _require(isinstance(source, dict), f"{label}: source must be an object")
        for field in ("id", "role", "publisher", "title", "url", "fixture"):
            _require(isinstance(source.get(field), str) and source[field], f"{label}: source missing {field}")
        _require(source["id"] not in source_ids, f"{label}: duplicate source id {source['id']}")
        source_ids.add(source["id"])
        fixture = PROJECT_ROOT / source["fixture"]
        _require(fixture.is_file(), f"{label}: fixture not found: {source['fixture']}")

    oracle = data["oracle"]
    _require(isinstance(oracle, dict) and isinstance(oracle.get("claims"), list) and oracle["claims"],
             f"{label}: oracle.claims must not be empty")
    for claim in oracle["claims"]:
        _require(isinstance(claim, dict), f"{label}: oracle claim must be an object")
        _require(claim.get("expected_verdict") in VERDICTS, f"{label}: invalid expected verdict")
        accepted = claim.get("accepted_sources")
        _require(_string_list(accepted), f"{label}: accepted_sources must not be empty")
        _require(set(accepted) <= source_ids, f"{label}: oracle references an unknown source")

    rubric = data["rubric"]
    dimensions = rubric.get("dimensions") if isinstance(rubric, dict) else None
    _require(isinstance(dimensions, list) and dimensions, f"{label}: rubric dimensions must not be empty")
    dimension_points: dict[str, int] = {}
    for dimension in dimensions:
        dimension_id = dimension.get("id") if isinstance(dimension, dict) else None
        points = dimension.get("points") if isinstance(dimension, dict) else None
        _require(isinstance(dimension_id, str) and dimension_id, f"{label}: invalid rubric dimension")
        _require(dimension_id not in dimension_points, f"{label}: duplicate dimension {dimension_id}")
        _require(isinstance(points, int) and points > 0, f"{label}: invalid points for {dimension_id}")
        dimension_points[dimension_id] = points
    _require(sum(dimension_points.values()) == rubric.get("total_points") == 100,
             f"{label}: rubric must total 100 points")

    checks = data["checks"]
    _require(isinstance(checks, list) and checks, f"{label}: checks must not be empty")
    check_ids: set[str] = set()
    allocated = {dimension: 0 for dimension in dimension_points}
    for check in checks:
        _require(isinstance(check, dict), f"{label}: check must be an object")
        check_id, check_type = check.get("id"), check.get("type")
        dimension, points = check.get("dimension"), check.get("points")
        _require(isinstance(check_id, str) and check_id, f"{label}: invalid check id")
        _require(check_id not in check_ids, f"{label}: duplicate check id {check_id}")
        check_ids.add(check_id)
        _require(check_type in CHECK_TYPES, f"{label}: unsupported check type {check_type}")
        _require(dimension in dimension_points, f"{label}: unknown check dimension {dimension}")
        _require(isinstance(points, int) and points > 0, f"{label}: invalid check points")
        allocated[dimension] += points
        if check_type == "verdict":
            _require(check.get("expected") in VERDICTS, f"{label}: verdict check has invalid expected value")
            _require(_string_list(check.get("match_terms")), f"{label}: verdict check needs match_terms")
        elif check_type in {"contains_all", "contains_any"}:
            _require(_string_list(check.get("values")), f"{label}: {check_type} needs values")
        elif check_type == "source_url":
            _require(_string_list(check.get("source_ids")), f"{label}: source_url needs source_ids")
            _require(set(check["source_ids"]) <= source_ids, f"{label}: source_url references an unknown source")
        elif check_type == "max_usage":
            limits = check.get("limits")
            _require(isinstance(limits, dict) and limits, f"{label}: max_usage needs limits")
            _require(all(isinstance(k, str) and isinstance(v, (int, float)) and v >= 0
                         for k, v in limits.items()), f"{label}: invalid usage limits")
        if "score_cap" in check:
            _require(isinstance(check["score_cap"], int) and 0 <= check["score_cap"] <= 100,
                     f"{label}: invalid score_cap")
    _require(allocated == dimension_points,
             f"{label}: check points {allocated} do not match rubric {dimension_points}")


def load_case(path: str | Path) -> EvaluationCase:
    case_path = Path(path)
    try:
        data = json.loads(case_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot load evaluation case {case_path}: {exc}") from exc
    _validate_case(data, case_path)
    return EvaluationCase(case_path, data)


def load_cases(directory: str | Path | None = None, include_drafts: bool = False) -> list[EvaluationCase]:
    root = Path(directory) if directory else PROJECT_ROOT / "evals" / "cases" / "seed"
    cases = [load_case(path) for path in sorted(root.glob("*.json"))]
    selected = [case for case in cases if include_drafts or case.data["status"] == "reviewed"]
    ids = [case.id for case in selected]
    _require(len(ids) == len(set(ids)), f"{root}: duplicate case ids")
    return selected


def match_case_for_run(cases: list[EvaluationCase], run: dict[str, Any]) -> EvaluationCase | None:
    case_id = run.get("case_id")
    if isinstance(case_id, str):
        return next((case for case in cases if case.id == case_id), None)
    task = run.get("input")
    if not isinstance(task, str):
        return None
    normalized = "".join(task.split()).casefold()
    matches = [case for case in cases if "".join(case.task["input"].split()).casefold() == normalized]
    return matches[0] if len(matches) == 1 else None
