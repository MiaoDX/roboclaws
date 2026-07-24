from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_isaac_image_contract_is_digest_pinned_and_eula_is_durable() -> None:
    contract = json.loads(
        (REPO_ROOT / "skills/eval-harness/catalog/cloudml_isaac_proof.json").read_text()
    )
    dockerfile = (REPO_ROOT / "Dockerfile.eval.isaac").read_text()
    image = contract["image"]
    runtime = contract["runtime"]

    assert image["base_image"].startswith("nvcr.io/nvidia/isaac-sim@sha256:")
    assert image["base_image"] in dockerfile
    assert image["dino_runtime_image"].endswith(
        "@sha256:d1d4c398f0677beceb8ab646b11f0bfd9d4d00d9e67a087170de4e23478669a4"
    )
    assert image["dino_runtime_image"] in dockerfile
    assert image["isaac_lab_source_archive"].endswith(f"/{runtime['isaac_lab_revision']}.tar.gz")
    assert len(image["isaac_lab_source_archive_sha256"]) == 64
    assert image["eula_accepted"] is True
    assert image["eula_authorization"]
    assert runtime["isaac_lab_revision"] in dockerfile
    assert f"ARG ISAACLAB_VERSION={runtime['isaac_lab']}" in dockerfile
    assert f"ARG ISAACSIM_VERSION={runtime['isaac_sim_distribution']}" in dockerfile
    assert f"ARG ISAACSIM_RELEASE={runtime['isaac_sim']}" in dockerfile
    assert f"ARG ISAACSIM_BUILD={runtime['isaac_sim_build']}" in dockerfile
    assert f"ARG TORCH_VERSION={runtime['torch']}" in dockerfile
    assert "ENV OMNI_KIT_ACCEPT_EULA=YES" in dockerfile
    assert "ENV OMNI_KIT_ALLOW_ROOT=1" in dockerfile
    assert "ENV ROBOCLAWS_ISAACLAB_PYTHON=/isaac-sim/python.sh" in dockerfile
    assert 'Path("/isaac-sim/docs/py/VERSION")' in dockerfile
    assert 'Path("/isaac-sim/VERSION")' in dockerfile


def test_isaac_build_defaults_to_local_only_and_offline_gpu_proof() -> None:
    build = (REPO_ROOT / "scripts/dev/build_isaac_eval_image.sh").read_text()
    smoke = (REPO_ROOT / "scripts/dev/run_isaac_eval_image_offline_smoke.sh").read_text()

    assert "ROBOCLAWS_ISAAC_IMAGE_PUSH:-false" in build
    assert "ROBOCLAWS_ISAAC_IMAGE_PUBLICATION_APPROVED:-false" in build
    assert '--build-context "isaaclab-source=$isaaclab_source"' in build
    assert ".venv-isaaclab-src/IsaacLab-v3" in build
    assert "grounding-dino-cache" not in build
    assert "--gpus all --network none" in smoke
    assert "--entrypoint /bin/bash" in smoke
    assert "-e OMNI_KIT_ALLOW_ROOT=1" in smoke
    assert "-e ROBOCLAWS_ISAACLAB_PYTHON=/isaac-sim/python.sh" in smoke
    assert "just harness::isaac-runtime-smoke" in smoke
    assert "torch.cuda.is_available()" in smoke
    assert 'test -s "$output_dir/$stamp/state.json"' in smoke
    assert '"$output_dir/$stamp/state.json" >/dev/null' in smoke
    assert '"$output_dir/$stamp/init_result.json" >/dev/null' not in smoke


def test_isaac_camera_capture_uses_sim6_stage_api() -> None:
    capture_sources = [
        (REPO_ROOT / "scripts/isaac_lab_cleanup/isaac_camera_capture.py").read_text(),
        (REPO_ROOT / "scripts/isaac_lab_cleanup/isaac_scene_camera_capture.py").read_text(),
    ]

    for source in capture_sources:
        assert "import isaacsim.core.experimental.utils.stage as stage_utils" in source
        assert "import isaacsim.core.utils.stage as stage_utils" not in source
        assert "opened, _ = stage_utils.open_stage" in source
