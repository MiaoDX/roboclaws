"""Live eval launch helpers for long-horizon household tasks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.evals import long_horizon as lh
from roboclaws.evals.long_horizon_manifest import write_generated_mess_manifest
from roboclaws.evals.models import EvalSample


def attach_generated_mess_manifest(
    kwargs: dict[str, Any],
    *,
    sample: EvalSample,
    run_dir: Path,
) -> None:
    spec = lh.long_horizon_spec(sample)
    if spec is None:
        return
    path = write_generated_mess_manifest(
        sample,
        spec,
        run_dir / "generated_mess_manifest.private.json",
    )
    kwargs["generated_mess_manifest_path"] = str(path)


def relocation_args(kwargs: dict[str, Any], *, relocation_count: int) -> list[str]:
    if not relocation_count:
        return []
    args = [
        "scenario_setup=relocate-cleanup-related-objects",
        f"relocation_count={relocation_count}",
    ]
    if generated_object_ids := kwargs.get("generated_mess_object_ids"):
        args.append(f"generated_mess_object_ids={','.join(generated_object_ids)}")
    generated_manifest_path = str(kwargs.get("generated_mess_manifest_path") or "")
    if generated_manifest_path:
        args.append(f"generated_mess_manifest_path={generated_manifest_path}")
    return args
