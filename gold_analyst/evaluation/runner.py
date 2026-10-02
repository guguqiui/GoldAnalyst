"""Sequential batch runner for reviewed evaluation cases."""

from datetime import datetime
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..config import ROOT, settings
from .loader import load_cases, match_case_for_run
from .models import EvaluationCase
from .storage import default_evaluation_path


STRATEGY_NAMES = ("source_first", "scope_first", "counter_first")


def completed_jobs(reports_dir: Path, cases: list[EvaluationCase]) -> set[tuple[str, str]]:
    completed: set[tuple[str, str]] = set()
    for path in reports_dir.glob("*.json"):
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        case = match_case_for_run(cases, run)
        strategy = run.get("strategy")
        if case and run.get("status") == "completed" and strategy in STRATEGY_NAMES:
            score_path = default_evaluation_path(path, case.id)
            try:
                score_record = json.loads(score_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if score_record.get("valid", True):
                completed.add((case.id, strategy))
    return completed


def plan_jobs(
    cases: list[EvaluationCase],
    strategies: list[str],
    completed: set[tuple[str, str]],
    rerun: bool = False,
) -> list[tuple[EvaluationCase, str]]:
    return [
        (case, strategy)
        for strategy in strategies
        for case in cases
        if rerun or (case.id, strategy) not in completed
    ]


def run_seed(strategy: str = "source_first", rerun: bool = False) -> dict[str, Any]:
    cfg = settings()
    if not cfg["api_key"]:
        raise ValueError("请先在本地 .env 配置 OPENAI_API_KEY，再运行批量评测。")
    cases = load_cases()
    strategies = list(STRATEGY_NAMES) if strategy == "all" else [strategy]
    reports_dir = ROOT / "reports" / "seed"
    reports_dir.mkdir(parents=True, exist_ok=True)
    existing = completed_jobs(reports_dir, cases)
    jobs = plan_jobs(cases, strategies, existing, rerun)
    batch_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:6]
    summary: dict[str, Any] = {
        "schema_version": "1.0",
        "batch_id": batch_id,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "requested_strategy": strategy,
        "rerun": rerun,
        "case_count": len(cases),
        "planned_runs": len(jobs),
        "previously_completed": len(cases) * len(strategies) - len(jobs),
        "runs": [],
    }
    if not jobs:
        summary["status"] = "nothing_to_run"
    else:
        from ..server import execute, new_run

        for index, (case, strategy_name) in enumerate(jobs, start=1):
            print(f"[{index}/{len(jobs)}] {strategy_name} · {case.id}", flush=True)
            run = new_run("live", case.task["input"], strategy_name)
            run["case_id"] = case.id
            run["artifact_group"] = "seed"
            run = execute(run)
            item = {
                "case_id": case.id,
                "strategy": strategy_name,
                "run_id": run["id"],
                "status": run["status"],
                "report_path": f"reports/seed/{run['id']}.json",
                "valid": run.get("evaluation", {}).get("valid"),
                "score": run.get("evaluation", {}).get("score"),
                "score_path": run.get("evaluation", {}).get("result_path"),
                "error": run.get("error") or run.get("evaluation_error"),
            }
            summary["runs"].append(item)
            if item["status"] != "completed":
                outcome = f"failed: {item['error'] or '调查未完成'}"
            elif item["valid"] is False:
                outcome = f"invalid: {item['error'] or '本次运行不具备可评分条件'}"
            elif item["valid"] is True:
                outcome = f"score={item['score']}"
            else:
                outcome = f"unscored: {item['error'] or '未生成评分结果'}"
            print(f"    {outcome}", flush=True)
        summary["status"] = "completed_with_errors" if any(
            item["status"] != "completed" or not item["valid"] for item in summary["runs"]
        ) else "completed"

    batch_path = ROOT / "evals" / "results" / "seed" / "batches" / f"{batch_id}.json"
    batch_path.parent.mkdir(parents=True, exist_ok=True)
    batch_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary["batch_result_path"] = str(batch_path.relative_to(ROOT))
    return summary
