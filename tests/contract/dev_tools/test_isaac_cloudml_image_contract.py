from __future__ import annotations

import json
import os
import subprocess
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
    assert image["nvidia_vulkan_overlay_image"].endswith(
        "@sha256:2d90ff0525fda7b3980ef8094f3eb432bcb2b1efed8c9bf4b531c0608561bdcb"
    )
    assert image["nvidia_vulkan_overlay_image"] in dockerfile
    assert (
        "COPY --from=nvidia-vulkan-overlay /opt/nvidia-driver-580.105.08"
        " /opt/nvidia-driver-580.105.08" in dockerfile
    )
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


def _run_vulkan_selector(
    tmp_path: Path,
    *,
    driver_output: str,
    ld_library_path: str,
    create_overlay: bool = True,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    overlay = tmp_path / "overlay"
    bin_dir.mkdir(parents=True)
    overlay.mkdir()
    nvidia_smi = bin_dir / "nvidia-smi"
    nvidia_smi.write_text(
        "#!/usr/bin/env bash\nprintf '%b' \"$ROBOCLAWS_TEST_DRIVER_OUTPUT\"\n",
        encoding="utf-8",
    )
    nvidia_smi.chmod(0o755)
    if create_overlay:
        for name in (
            "libGLX_nvidia.so.0",
            "libnvidia-glvkspirv.so.580.105.08",
            "libnvidia-gpucomp.so.580.105.08",
        ):
            (overlay / name).touch()
    selector = REPO_ROOT / "scripts/dev/configure_nvidia_vulkan_runtime.sh"
    command = (
        f'source "{selector}" && '
        "printf 'driver=%s\\nmode=%s\\nld=%s\\nvk=%s\\nicd=%s\\n' "
        '"$ROBOCLAWS_NVIDIA_DRIVER_VERSION" '
        '"$ROBOCLAWS_NVIDIA_VULKAN_RUNTIME_MODE" '
        '"$LD_LIBRARY_PATH" "$VK_DRIVER_FILES" "$VK_ICD_FILENAMES"'
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "LD_LIBRARY_PATH": ld_library_path,
        "ROBOCLAWS_NVIDIA_OVERLAY_ROOT": str(overlay),
        "ROBOCLAWS_TEST_DRIVER_OUTPUT": driver_output,
    }
    return subprocess.run(
        ["bash", "-c", command],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_vulkan_selector_uses_native_libraries_for_driver_570(tmp_path: Path) -> None:
    overlay = tmp_path / "overlay"
    result = _run_vulkan_selector(
        tmp_path,
        driver_output="570.124.06\\n",
        ld_library_path=f"{overlay}:/isaac/lib",
    )

    assert result.returncode == 0, result.stderr
    assert "driver=570.124.06" in result.stdout
    assert "mode=native" in result.stdout
    assert "ld=/isaac/lib" in result.stdout


def test_vulkan_selector_uses_overlay_for_driver_580(tmp_path: Path) -> None:
    result = _run_vulkan_selector(
        tmp_path,
        driver_output="580.105.08\\n",
        ld_library_path="/isaac/lib",
    )

    assert result.returncode == 0, result.stderr
    assert "driver=580.105.08" in result.stdout
    assert "mode=overlay" in result.stdout
    assert f"ld={tmp_path / 'overlay'}:/isaac/lib" in result.stdout
    assert "vk=/etc/vulkan/icd.d/nvidia_icd.json" in result.stdout
    assert "icd=/etc/vulkan/icd.d/nvidia_icd.json" in result.stdout


def test_vulkan_selector_rejects_unknown_or_mixed_drivers(tmp_path: Path) -> None:
    unknown = _run_vulkan_selector(
        tmp_path / "unknown",
        driver_output="575.1.2\\n",
        ld_library_path="/isaac/lib",
    )
    mixed = _run_vulkan_selector(
        tmp_path / "mixed",
        driver_output="570.124.06\\n580.105.08\\n",
        ld_library_path="/isaac/lib",
    )

    assert unknown.returncode == 78
    assert "unsupported_driver=575.1.2" in unknown.stderr
    assert mixed.returncode == 78
    assert "unsupported_driver_set=570.124.06 580.105.08" in mixed.stderr


def test_cloudml_worker_activates_driver_matched_vulkan_runtime() -> None:
    worker = (REPO_ROOT / "scripts/dev/run_cloudml_eval_worker.sh").read_text()
    selector = (REPO_ROOT / "scripts/dev/configure_nvidia_vulkan_runtime.sh").read_text()

    assert "nvidia-smi --query-gpu=driver_version" in selector
    assert 'source "$repo_dir/scripts/dev/configure_nvidia_vulkan_runtime.sh"' in worker
    assert "ROBOCLAWS_NVIDIA_VULKAN_RUNTIME_MODE" in worker


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
