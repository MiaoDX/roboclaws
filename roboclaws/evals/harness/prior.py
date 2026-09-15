"""Baseline Runtime Map Prior resolution."""

from __future__ import annotations

from pathlib import Path

from roboclaws.maps.runtime_prior_catalog import load_runtime_prior_catalog

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PRIOR_CATALOG_PATH = REPO_ROOT / "assets" / "eval-priors" / "runtime_map_prior_catalog.json"
DEFAULT_WORLD = "molmospaces/procthor-10k-val/0"
DEFAULT_BACKEND = "mujoco"


def resolve_baseline_prior(
    explicit_path: str = "",
    *,
    catalog_path: Path | None = None,
    world_id: str = DEFAULT_WORLD,
    backend_id: str = DEFAULT_BACKEND,
) -> str:
    """Resolve an explicit or catalog-backed prior without silently falling back."""

    explicit = str(explicit_path or "").strip()
    if explicit:
        candidate = Path(explicit)
        if not candidate.is_absolute():
            candidate = REPO_ROOT / candidate
        return str(candidate)
    catalog_path = catalog_path or DEFAULT_PRIOR_CATALOG_PATH
    if not catalog_path.is_file():
        return ""
    for entry in load_runtime_prior_catalog(catalog_path):
        if entry.world_id == world_id and entry.backend_id == backend_id and entry.auto_enabled:
            return str(Path(entry.path).resolve())
    return ""
