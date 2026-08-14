"""Eval suite discovery and sample loading."""

from __future__ import annotations

from pathlib import Path

from roboclaws.evals.models import EvalSample, EvalSuite, load_eval_sample, load_eval_suite

REPO_ROOT = Path(__file__).resolve().parents[2]


def resolve_suite_path(suite_ref: str) -> Path:
    """Resolve a suite id, short name, or JSON path to a suite file."""

    raw = str(suite_ref or "").strip()
    if not raw:
        raw = "smoke_regression"
    candidate = Path(raw)
    if candidate.suffix == ".json":
        path = candidate if candidate.is_absolute() else REPO_ROOT / candidate
        if path.exists():
            return path
    short = raw.removeprefix("household_world.")
    path = REPO_ROOT / "evals" / "household_world" / "suites" / f"{short}.json"
    if path.exists():
        return path
    raise ValueError(f"unknown eval suite {suite_ref!r}")


def resolved_regrade_source(regrade_source: Path | None, *, suite: EvalSuite) -> Path | None:
    if regrade_source is None:
        return None
    source = Path(regrade_source)
    if not source.is_absolute():
        source = REPO_ROOT / source
    source = source.resolve()
    if not source.is_dir():
        raise ValueError(f"regrade_source does not exist or is not a directory: {source}")
    if source.name == path_token(suite.suite_id) and (source / "eval_results.json").is_file():
        return source
    suite_dir = source / path_token(suite.suite_id)
    if suite_dir.is_dir():
        return suite_dir.resolve()
    if (source / "eval_results.json").is_file():
        return source
    raise ValueError(
        "regrade_source must point to an existing eval run directory for "
        f"{suite.suite_id} or an output root containing it"
    )


def load_suite_samples(suite: EvalSuite) -> list[EvalSample]:
    if not suite.sample_refs:
        raise ValueError(f"eval suite {suite.suite_id!r} has no sample_refs")
    samples = [load_eval_sample(REPO_ROOT / ref) for ref in suite.sample_refs]
    loaded_ids = tuple(sample.sample_id for sample in samples)
    if loaded_ids != suite.sample_ids:
        raise ValueError(
            f"eval suite {suite.suite_id!r} sample_refs resolve to {loaded_ids}, "
            f"expected {suite.sample_ids}"
        )
    return samples


def validate_suite_runtime_map_prior(suite: EvalSuite, runtime_map_prior: Path | None) -> None:
    mode = str((suite.metadata or {}).get("execution_mode") or "")
    if mode == "task_matrix_on_fixed_map" and runtime_map_prior is None:
        raise ValueError(f"eval suite {suite.suite_id!r} requires runtime_map_prior=<path>")
    if mode != "task_matrix_on_fixed_map" and runtime_map_prior is not None:
        raise ValueError(
            "runtime_map_prior suite override is only valid for task_matrix_on_fixed_map suites"
        )


def load_suite(suite_ref: str) -> tuple[EvalSuite, list[EvalSample]]:
    suite = load_eval_suite(resolve_suite_path(suite_ref))
    return suite, load_suite_samples(suite)


def path_token(value: str) -> str:
    return str(value).replace("/", "_").replace(".", "_")
