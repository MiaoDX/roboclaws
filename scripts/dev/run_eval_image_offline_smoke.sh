#!/usr/bin/env bash
set -Eeuo pipefail

default_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
repo_root="${ROBOCLAWS_EVAL_REPO_DIR:-$default_repo_root}"
image="${ROBOCLAWS_EVAL_IMAGE:-roboclaws-eval:local}"
suite="${ROBOCLAWS_EVAL_SUITE:-smoke_regression}"
budget="${ROBOCLAWS_EVAL_BUDGET:-smoke}"
stamp="${ROBOCLAWS_EVAL_STAMP:-offline-smoke}"
host_output_dir="${ROBOCLAWS_EVAL_OUTPUT_DIR:-/tmp/roboclaws-eval-output}"
container_output_dir="/workspace/output"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'USAGE'
Usage:
  ROBOCLAWS_EVAL_IMAGE=roboclaws-eval:local scripts/dev/run_eval_image_offline_smoke.sh

Environment overrides:
  ROBOCLAWS_EVAL_IMAGE       Docker image to run. Default: roboclaws-eval:local
  ROBOCLAWS_EVAL_SUITE       Eval suite. Default: smoke_regression
  ROBOCLAWS_EVAL_BUDGET      Eval budget. Default: smoke
  ROBOCLAWS_EVAL_STAMP       Eval stamp. Default: offline-smoke
  ROBOCLAWS_EVAL_OUTPUT_DIR  Host output dir. Default: /tmp/roboclaws-eval-output
  ROBOCLAWS_EVAL_REPO_DIR    Checkout to mount read-only. Default: current repo
USAGE
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "error: docker is required for the offline eval image proof" >&2
  exit 1
fi

if [[ ! -d "$repo_root/roboclaws" || ! -f "$repo_root/pyproject.toml" ]]; then
  echo "error: ROBOCLAWS_EVAL_REPO_DIR must point at a Roboclaws checkout: $repo_root" >&2
  exit 1
fi

mkdir -p "$host_output_dir"

docker run --rm --network none \
  -v "${repo_root}:/workspace/roboclaws:ro" \
  -v "${host_output_dir}:${container_output_dir}" \
  -e ROBOCLAWS_EVAL_SUITE="$suite" \
  -e ROBOCLAWS_EVAL_BUDGET="$budget" \
  -e ROBOCLAWS_EVAL_STAMP="$stamp" \
  "$image" \
  bash -lc '
    set -Eeuo pipefail
    repo_dir=/workspace/roboclaws
    output_root=/workspace/output
    cd "$repo_dir"
    test -x "$ROBOCLAWS_DEVTOOLS_PYTHON"
    uv pip install \
      --python "$ROBOCLAWS_DEVTOOLS_PYTHON" \
      --no-build-isolation \
      --no-deps \
      --editable "$repo_dir"
    "$ROBOCLAWS_DEVTOOLS_PYTHON" - <<PY
import pathlib
import roboclaws
import numpy
import PIL

repo = pathlib.Path("/workspace/roboclaws").resolve()
module = pathlib.Path(roboclaws.__file__).resolve()
if repo not in module.parents:
    raise SystemExit(f"roboclaws imported from {module}, expected under {repo}")
print(f"roboclaws import: {module}")
PY
    just agent::eval \
      "suite=${ROBOCLAWS_EVAL_SUITE}" \
      "budget=${ROBOCLAWS_EVAL_BUDGET}" \
      "output_dir=${output_root}" \
      "stamp=${ROBOCLAWS_EVAL_STAMP}"
    "$ROBOCLAWS_DEVTOOLS_PYTHON" - <<PY
import os
from pathlib import Path

root = Path("/workspace/output")
stamp = os.environ["ROBOCLAWS_EVAL_STAMP"]
matches = [path.parent for path in root.glob(f"*/{stamp}/eval_results.json")]
if len(matches) != 1:
    raise SystemExit(f"expected one eval_results.json under {root}/*/{stamp}, found {matches}")
run_dir = matches[0]
report = run_dir / "eval_report.html"
if not report.is_file():
    raise SystemExit(f"missing eval report: {report}")
print(f"offline eval artifacts: {run_dir}")
PY
  '
