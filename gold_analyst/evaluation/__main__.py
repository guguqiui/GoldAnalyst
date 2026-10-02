"""CLI for validating cases and scoring saved GoldAnalyst runs."""

import argparse
import json
from pathlib import Path

from .loader import PROJECT_ROOT, load_cases, match_case_for_run
from .scorer import score_run
from .storage import save_evaluation


def main() -> None:
    parser = argparse.ArgumentParser(description="GoldAnalyst deterministic evaluation tools")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate", help="validate all reviewed seed cases")
    score_parser = subparsers.add_parser("score", help="score a saved run JSON")
    score_parser.add_argument("case_id")
    score_parser.add_argument("run_json", type=Path)
    score_parser.add_argument("--output", type=Path, help="custom score JSON path")
    backfill_parser = subparsers.add_parser("backfill", help="score existing reports that match known cases")
    backfill_parser.add_argument("--reports", type=Path, default=PROJECT_ROOT / "reports")
    run_parser = subparsers.add_parser("run-seed", help="run and score all reviewed seed cases")
    run_parser.add_argument(
        "--strategy",
        choices=["source_first", "scope_first", "counter_first", "all"],
        default="source_first",
    )
    run_parser.add_argument("--rerun", action="store_true", help="rerun completed case and strategy pairs")
    args = parser.parse_args()

    cases = load_cases()
    if args.command == "validate":
        print(json.dumps({"valid": True, "case_count": len(cases), "case_ids": [case.id for case in cases]},
                         ensure_ascii=False, indent=2))
        return

    if args.command == "backfill":
        reports_dir = args.reports if args.reports.is_absolute() else PROJECT_ROOT / args.reports
        saved, skipped, errors = [], [], []
        for run_path in sorted(reports_dir.glob("*.json")):
            try:
                run = json.loads(run_path.read_text(encoding="utf-8"))
                case = match_case_for_run(cases, run)
                if case is None or not isinstance(run.get("report"), dict):
                    skipped.append(run_path.name)
                    continue
                result = score_run(case, run)
                saved_path = save_evaluation(case, run, result, run_path)
                saved.append({"report": run_path.name, "case_id": case.id, "valid": result["valid"],
                              "score": result["score"],
                              "result": str(saved_path.relative_to(PROJECT_ROOT))})
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                errors.append({"report": run_path.name, "error": str(exc)})
        print(json.dumps({"saved": saved, "skipped": skipped, "errors": errors}, ensure_ascii=False, indent=2))
        return

    if args.command == "run-seed":
        from .runner import run_seed

        try:
            summary = run_seed(args.strategy, args.rerun)
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    case_by_id = {case.id: case for case in cases}
    if args.case_id not in case_by_id:
        parser.error(f"unknown case id: {args.case_id}")
    run_path = args.run_json if args.run_json.is_absolute() else PROJECT_ROOT / args.run_json
    try:
        run = json.loads(run_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        parser.error(f"cannot read run JSON: {exc}")
    case = case_by_id[args.case_id]
    result = score_run(case, run)
    saved_path = save_evaluation(case, run, result, run_path, args.output)
    try:
        display_path = saved_path.relative_to(PROJECT_ROOT)
    except ValueError:
        display_path = saved_path
    print(json.dumps({**result, "saved_to": str(display_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
