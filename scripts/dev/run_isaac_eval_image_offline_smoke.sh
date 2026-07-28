#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
image="${ROBOCLAWS_ISAAC_IMAGE:-roboclaws-eval:isaac-local}"
output_dir="${ROBOCLAWS_ISAAC_OUTPUT_DIR:-/tmp/roboclaws-isaac-image-smoke}"
stamp="${ROBOCLAWS_ISAAC_SMOKE_STAMP:-offline-image-smoke}"

if ! command -v docker >/dev/null 2>&1; then
  echo "error: docker is required for the Isaac image smoke" >&2
  exit 1
fi
if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "error: an NVIDIA GPU runtime is required for the Isaac image smoke" >&2
  exit 1
fi
mkdir -p "$output_dir"

docker run --rm --gpus all --network none --entrypoint /bin/bash \
  -v "${output_dir}:/workspace/output" \
  -e OMNI_KIT_ACCEPT_EULA=YES \
  -e OMNI_KIT_ALLOW_ROOT=1 \
  -e ACCEPT_EULA=Y \
  -e ROBOCLAWS_ISAACLAB_PYTHON=/isaac-sim/python.sh \
  "$image" \
  -lc '
    set -Eeuo pipefail
    cd /opt/roboclaws/src
    nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
    "$ROBOCLAWS_ISAACLAB_PYTHON" - <<PY
import importlib.metadata
import json
import os
from pathlib import Path

import torch

versions = {
    "isaac_sim": Path("/isaac-sim/docs/py/VERSION").read_text().strip(),
    "isaac_sim_build": Path("/isaac-sim/VERSION").read_text().strip(),
    "isaac_lab": importlib.metadata.version("isaaclab"),
    "torch": torch.__version__,
    "cuda": torch.version.cuda,
}
assert versions == {
    "isaac_sim": "6.0.0",
    "isaac_sim_build": "6.0.0-rc.59+release.41464.5f2772bc.gl",
    "isaac_lab": "6.1.14",
    "torch": "2.10.0+cu128",
    "cuda": "12.8",
}
assert torch.cuda.is_available()
assert os.environ.get("OMNI_KIT_ACCEPT_EULA") == "YES"
assert os.environ.get("OMNI_KIT_ALLOW_ROOT") == "1"
assert os.environ.get("ROBOCLAWS_ISAACLAB_PYTHON") == "/isaac-sim/python.sh"
assert Path("/opt/roboclaws/.venv-isaaclab/.isaaclab-revision").read_text().strip() == (
    "ffff603eafc6b74264a5261cc0183d6a65390d78"
)
print(json.dumps(versions, sort_keys=True))
PY
    /opt/roboclaws/.venv-visual-grounding/bin/python - <<PY
import os
from pathlib import Path

import torch

assert torch.cuda.is_available()
model = Path(os.environ["VISUAL_GROUNDING_DINO_MODEL_ID"])
assert (model / "config.json").is_file()
assert (model / "model.safetensors").is_file()
assert (model / ".revision").read_text().strip() == os.environ[
    "VISUAL_GROUNDING_DINO_MODEL_REVISION"
]
print(torch.cuda.get_device_name(0), torch.version.cuda)
PY
    just harness::isaac-runtime-smoke \
      runtime_python="$ROBOCLAWS_ISAACLAB_PYTHON" \
      output_dir=/workspace/output \
      stamp="'"$stamp"'" \
      accept_nvidia_eula=true
  '

test -s "$output_dir/$stamp/state.json"
test -s "$output_dir/$stamp/init_result.json"
test -s "$output_dir/$stamp/robot_views_result.json"
jq -e '
  .runtime.isaac_sim_version == "6.0.0"
  and .runtime.isaac_sim_build == "6.0.0-rc.59+release.41464.5f2772bc.gl"
' "$output_dir/$stamp/state.json" >/dev/null
echo "isaac_image_smoke_output=$output_dir/$stamp"
