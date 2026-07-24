#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from roboclaws.evals.cloudml_isaac_assets import prepare_stage


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stage one frozen CloudML Isaac proof asset group."
    )
    parser.add_argument("--stage", choices=("A", "B", "C"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--code-archive", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("skills/eval-harness/catalog/cloudml_isaac_proof.json"),
    )
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    manifest = prepare_stage(
        repo_root=repo_root,
        contract_path=args.contract,
        stage_id=args.stage,
        output_dir=args.output_dir,
        code_archive=args.code_archive,
        code_commit=args.code_commit,
    )
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
