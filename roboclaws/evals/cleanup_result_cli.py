from __future__ import annotations

from roboclaws.evals.cleanup_result_args import parse_args
from roboclaws.evals.cleanup_result_grader import assert_advisory_scoring
from roboclaws.household.cleanup_validation_cli import validate_path
from roboclaws.household.cleanup_validation_support import resolve_path


def main() -> None:
    args = parse_args()
    run_results = validate_path(args)
    if args.require_advisory_scoring:
        for data, path in run_results:
            report_path = resolve_path(
                path.parent, str((data.get("artifacts") or {}).get("report", ""))
            )
            assert_advisory_scoring(data, path.parent, report_path.read_text(encoding="utf-8"))
    print(f"household-world ok: {args.path} ({len(run_results)} run(s))")


if __name__ == "__main__":
    main()
