"""Launch backend metadata."""

from __future__ import annotations

import argparse
from dataclasses import dataclass


@dataclass(frozen=True)
class BackendSpec:
    """Runtime/backend metadata for one launch world."""

    id: str
    label: str
    implementation_backend: str
    lock_name: str
    resource_kind: str
    field_groups: tuple[str, ...]
    view_modes: tuple[str, ...]
    gates: tuple[str, ...] = ()
    default_overrides: tuple[str, ...] = ()
    availability: str = "enabled"


BACKEND_SPECS: dict[str, BackendSpec] = {
    "mujoco": BackendSpec(
        id="mujoco",
        label="MuJoCo",
        implementation_backend="molmospaces_subprocess",
        lock_name="molmospaces_mujoco",
        resource_kind="simulator",
        field_groups=("common",),
        view_modes=("overview", "fpv", "map", "chase", "outputs"),
    ),
    "isaaclab": BackendSpec(
        id="isaaclab",
        label="Isaac Lab",
        implementation_backend="isaaclab_subprocess",
        lock_name="isaac_gpu",
        resource_kind="gpu",
        field_groups=("common",),
        view_modes=("overview", "fpv", "map", "grounding", "chase", "outputs"),
        gates=("isaac_preflight",),
    ),
    "agibot-gdk": BackendSpec(
        id="agibot-gdk",
        label="Agibot GDK",
        implementation_backend="agibot_gdk",
        lock_name="agibot_g2",
        resource_kind="physical_robot",
        field_groups=("common", "agibot", "agibot_gates"),
        view_modes=("overview", "fpv", "map", "grounding", "outputs"),
        gates=("context_json", "localization_ready", "run_enabled", "estop_ready"),
    ),
}

SYNTHETIC_CLEANUP_IMPLEMENTATION_BACKEND = "api_semantic_synthetic"


def backend_spec(backend_id: str) -> BackendSpec:
    """Return a backend spec by public id."""

    return BACKEND_SPECS[backend_id]


def implementation_backend_ids(
    *,
    include_synthetic: bool = False,
    include_agibot: bool = True,
    include_auto: bool = False,
) -> tuple[str, ...]:
    """Return implementation backend ids known to the launch catalog."""

    ids: list[str] = []
    if include_auto:
        ids.append("auto")
    if include_synthetic:
        ids.append(SYNTHETIC_CLEANUP_IMPLEMENTATION_BACKEND)
    for spec in BACKEND_SPECS.values():
        if spec.implementation_backend == "agibot_gdk" and not include_agibot:
            continue
        ids.append(spec.implementation_backend)
    return tuple(dict.fromkeys(ids))


def cleanup_implementation_backend_ids() -> tuple[str, ...]:
    """Return private cleanup backends accepted by the Molmo cleanup runner."""

    return implementation_backend_ids(include_synthetic=True, include_agibot=False)


def normalize_cleanup_implementation_backend(value: str) -> str | None:
    """Normalize a private cleanup backend override from the command layer."""

    backend = str(value or "").strip()
    if backend in {"", "auto"}:
        return None
    return _require_backend(
        backend,
        choices=cleanup_implementation_backend_ids(),
    )


def _require_backend(
    backend: str,
    *,
    choices: tuple[str, ...],
) -> str:
    if backend in choices:
        return backend
    expected = "|".join(choices)
    raise ValueError(f"unsupported backend '{backend}' (expected {expected})")


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect Roboclaws launch backend metadata.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    command_parser = subparsers.add_parser("cleanup-implementation-backend")
    command_parser.add_argument("backend")

    args = parser.parse_args(argv)
    try:
        backend = normalize_cleanup_implementation_backend(args.backend)
        if backend is not None:
            print(backend)
        return 0
    except ValueError as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(_main())
