"""Persistence for evaluation results, kept separate from raw investigation runs."""

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from .loader import PROJECT_ROOT
from .models import EvaluationCase


EVALUATOR_VERSION = "deterministic-1.0"


def default_evaluation_path(run_path: Path, case_id: str) -> Path:
    results_dir = PROJECT_ROOT / "evals" / "results"
    try:
        relative_run = run_path.resolve().relative_to((PROJECT_ROOT / "reports").resolve())
    except ValueError:
        relative_run = Path(run_path.name)
    if len(relative_run.parts) > 1:
        results_dir /= Path(*relative_run.parts[:-1])
    return results_dir / f"{run_path.stem}.{case_id}.score.json"


def build_evaluation_record(
    case: EvaluationCase,
    run: dict[str, Any],
    result: dict[str, Any],
    run_path: Path,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "evaluator_version": EVALUATOR_VERSION,
        "evaluated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "case_id": case.id,
        "case_title": case.data["title"],
        "run": {
            "id": run.get("id", run_path.stem),
            "strategy": run.get("strategy"),
            "strategy_version": run.get("strategy_version"),
            "report_path": str(run_path),
        },
        **result,
    }


def save_evaluation(
    case: EvaluationCase,
    run: dict[str, Any],
    result: dict[str, Any],
    run_path: Path,
    output_path: Path | None = None,
) -> Path:
    target = output_path
    if target is None:
        target = default_evaluation_path(run_path, case.id)
    elif not target.is_absolute():
        target = PROJECT_ROOT / target
    target.parent.mkdir(parents=True, exist_ok=True)
    record = build_evaluation_record(case, run, result, run_path)
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target
