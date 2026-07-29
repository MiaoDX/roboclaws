"""Explicit promotion of immutable, content-addressed Runtime Map Priors."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from roboclaws.core.json_sources import read_json_object
from roboclaws.evals.runtime_prior_selection import RUNTIME_PRIOR_SELECTION_REPORT_SCHEMA
from roboclaws.maps.runtime_prior_catalog import RUNTIME_PRIOR_CATALOG_SCHEMA

CANONICAL_PRIOR_PROMOTION_MANIFEST_SCHEMA = "canonical_runtime_map_prior_promotion_v1"
CANONICAL_PRIOR_PROVENANCE_SCHEMA = "canonical_runtime_map_prior_provenance_v1"
IDENTITY_FIELDS = (
    "world",
    "scene_identity",
    "source_map_identity",
    "backend",
    "builder_provider",
    "builder_model",
    "prompt_or_skill_version",
    "evidence_lane",
    "camera_labeler",
    "seed",
    "map_schema_version",
)


def promote_canonical_runtime_prior(
    *,
    selection_report_path: Path,
    promotion_manifest_path: Path,
    output_root: Path,
) -> dict[str, str]:
    """Promote one approved selector result into an immutable catalog location."""

    report, identity_payload = _load_promotion_inputs(
        selection_report_path=selection_report_path,
        promotion_manifest_path=promotion_manifest_path,
    )
    entry = dict(report["catalog_entry"])
    source = Path(str(entry.get("path") or ""))
    if not source.is_file():
        raise ValueError(f"selected runtime map prior does not exist: {source}")
    artifact_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    canonical_digest = hashlib.sha256(
        json.dumps(
            {"artifact_sha256": artifact_sha256, "identity": identity_payload},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    canonical_dir = output_root / "by-sha256" / canonical_digest
    prior_path = canonical_dir / "runtime_map_prior_snapshot.json"
    provenance_path = canonical_dir / "provenance.json"
    _materialize_canonical_prior(
        source=source,
        prior_path=prior_path,
        provenance_path=provenance_path,
        canonical_digest=canonical_digest,
        artifact_sha256=artifact_sha256,
        identity=identity_payload,
        selection_report_path=selection_report_path,
        selected_candidate_id=str(report.get("selected_candidate_id") or ""),
    )
    entry.update(
        {
            "path": str(prior_path.resolve()),
            "canonical_digest": canonical_digest,
            "artifact_sha256": artifact_sha256,
            "canonical_provenance": str(provenance_path.resolve()),
        }
    )
    catalog = {"schema": RUNTIME_PRIOR_CATALOG_SCHEMA, "entries": [entry]}
    catalog_path = output_root / "runtime_map_prior_catalog.json"
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "prior": str(prior_path.resolve()),
        "provenance": str(provenance_path.resolve()),
        "catalog": str(catalog_path.resolve()),
        "canonical_digest": canonical_digest,
    }


def _load_promotion_inputs(
    *, selection_report_path: Path, promotion_manifest_path: Path
) -> tuple[dict[str, object], dict[str, object]]:
    report = read_json_object(selection_report_path, label="runtime prior selection report")
    if report.get("schema") != RUNTIME_PRIOR_SELECTION_REPORT_SCHEMA:
        raise ValueError("canonical promotion requires a runtime prior selection report")
    if report.get("status") != "accepted" or not isinstance(report.get("catalog_entry"), dict):
        raise ValueError("canonical promotion requires an accepted selector report")

    manifest = read_json_object(promotion_manifest_path, label="canonical prior promotion manifest")
    if manifest.get("schema") != CANONICAL_PRIOR_PROMOTION_MANIFEST_SCHEMA:
        raise ValueError("unsupported canonical prior promotion manifest schema")
    if manifest.get("maintainer_approved") is not True:
        raise ValueError("canonical prior promotion requires maintainer_approved=true")
    identity = manifest.get("identity")
    if not isinstance(identity, dict):
        raise ValueError("canonical prior promotion identity must be an object")
    missing = [field for field in IDENTITY_FIELDS if identity.get(field) in {None, ""}]
    if missing:
        raise ValueError(f"canonical prior promotion identity is missing fields: {missing}")

    identity_payload = {field: identity[field] for field in IDENTITY_FIELDS}
    return report, identity_payload


def _materialize_canonical_prior(
    *,
    source: Path,
    prior_path: Path,
    provenance_path: Path,
    canonical_digest: str,
    artifact_sha256: str,
    identity: dict[str, object],
    selection_report_path: Path,
    selected_candidate_id: str,
) -> None:
    if prior_path.parent.exists():
        existing = read_json_object(provenance_path, label="canonical prior provenance")
        if existing.get("canonical_digest") != canonical_digest:
            raise ValueError(f"canonical prior cache collision at {prior_path.parent}")
        if (
            not prior_path.is_file()
            or hashlib.sha256(prior_path.read_bytes()).hexdigest() != artifact_sha256
        ):
            raise ValueError(f"canonical prior cache artifact was mutated at {prior_path}")
    else:
        prior_path.parent.mkdir(parents=True)
        shutil.copyfile(source, prior_path)
        provenance = {
            "schema": CANONICAL_PRIOR_PROVENANCE_SCHEMA,
            "canonical_digest": canonical_digest,
            "artifact_sha256": artifact_sha256,
            "identity": identity,
            "selection_report": str(selection_report_path.resolve()),
            "selected_candidate_id": selected_candidate_id,
        }
        provenance_path.write_text(
            json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
