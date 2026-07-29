"""Product contract for reusable Runtime Map Prior Snapshot catalogs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object

RUNTIME_PRIOR_CATALOG_SCHEMA = "runtime_map_prior_catalog_v1"

COMPATIBLE = "compatible"
ADVISORY_REGRADE = "advisory_regrade"
STALE = "stale"
BLOCKING_STALE = "blocking_stale"
ACCEPTED_STALENESS = frozenset({COMPATIBLE, ADVISORY_REGRADE, STALE})


@dataclass(frozen=True)
class RuntimePriorCatalogKey:
    """Stable scene/map identity for reusable prior catalog entries."""

    world: str
    backend: str
    source_map_identity: str
    scene_identity: str

    @property
    def id(self) -> str:
        return "::".join((self.world, self.backend, self.source_map_identity, self.scene_identity))

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> RuntimePriorCatalogKey:
        forbidden_keys = {
            "scenario_setup",
            "relocation_seed",
            "generated_mess_set",
            "relocated_object_ids",
            "hidden_target_list",
            "acceptable_destinations",
        }
        present = sorted(key for key in forbidden_keys if key in payload)
        if present:
            raise ValueError(
                f"runtime prior catalog key contains private cleanup fields: {present}"
            )
        return cls(
            world=_required_string(payload, "world"),
            backend=_required_string(payload, "backend"),
            source_map_identity=_required_string(payload, "source_map_identity"),
            scene_identity=_required_string(payload, "scene_identity"),
        )

    def to_payload(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class RuntimeMapPriorCatalogEntry:
    """Normalized recommended prior for one world/backend pair."""

    world_id: str
    backend_id: str
    path: str
    status: str
    source: str
    staleness: str = COMPATIBLE
    selected_candidate_id: str = ""
    run_id: str = ""
    catalog_key: dict[str, Any] | None = None
    product_route: dict[str, Any] | None = None
    producer: dict[str, Any] | None = None
    evidence: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        return f"{self.world_id}::{self.backend_id}"

    @property
    def auto_enabled(self) -> bool:
        return catalog_entry_auto_enables(self.to_payload())

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "world_id": self.world_id,
            "backend_id": self.backend_id,
            "path": self.path,
            "status": self.status,
            "staleness": self.staleness,
            "source": self.source,
            "selected_candidate_id": self.selected_candidate_id,
            "run_id": self.run_id,
            "catalog_key": dict(self.catalog_key or {}),
            "product_route": dict(self.product_route or {}),
            "producer": dict(self.producer or {}),
            "evidence": list(self.evidence),
        }


def load_runtime_prior_catalog(path: Path) -> tuple[dict[str, Any], ...]:
    """Read and normalize a recommended-prior catalog file."""

    payload = read_json_object(path, label="runtime prior catalog")
    if payload.get("schema") != RUNTIME_PRIOR_CATALOG_SCHEMA:
        raise ValueError(f"expected schema {RUNTIME_PRIOR_CATALOG_SCHEMA}")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("runtime prior catalog entries must be a list")
    normalized = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"runtime prior catalog entry {index} must be an object")
        normalized.append(normalize_runtime_prior_catalog_entry(entry))
    return tuple(normalized)


def load_runtime_prior_catalog_entries(path: Path) -> tuple[RuntimeMapPriorCatalogEntry, ...]:
    """Read catalog entries and classify missing artifacts as blocking stale."""

    entries = []
    for payload in load_runtime_prior_catalog(path):
        item = dict(payload)
        if item["staleness"] != BLOCKING_STALE and not Path(item["path"]).is_file():
            item["staleness"] = BLOCKING_STALE
        entries.append(RuntimeMapPriorCatalogEntry(**_entry_constructor_values(item)))
    return tuple(entries)


def normalize_runtime_prior_catalog_entry(entry: dict[str, Any]) -> dict[str, Any]:
    catalog_key = (
        RuntimePriorCatalogKey.from_mapping(entry["catalog_key"]).to_payload()
        if isinstance(entry.get("catalog_key"), dict)
        else {}
    )
    return {
        "id": _required_string(entry, "id"),
        "world_id": _required_string(entry, "world_id"),
        "backend_id": _required_string(entry, "backend_id"),
        "path": _required_string(entry, "path"),
        "status": _required_string(entry, "status"),
        "staleness": _required_string(entry, "staleness"),
        "source": _required_string(entry, "source"),
        "catalog_key": catalog_key,
        "selected_candidate_id": str(entry.get("selected_candidate_id") or ""),
        "run_id": str(entry.get("run_id") or ""),
        "product_route": dict(entry.get("product_route") or {}),
        "producer": dict(entry.get("producer") or {}),
        "source_map_contract": dict(entry.get("source_map_contract") or {}),
        "current_contract": dict(entry.get("current_contract") or {}),
        "evidence": tuple(str(item) for item in entry.get("evidence") or ()),
        "canonical_digest": str(entry.get("canonical_digest") or ""),
        "artifact_sha256": str(entry.get("artifact_sha256") or ""),
        "canonical_provenance": str(entry.get("canonical_provenance") or ""),
    }


def classify_runtime_prior_compatibility(
    *,
    entry_contract: dict[str, Any],
    current_contract: dict[str, Any],
    prior_path: str = "",
) -> str:
    """Classify catalog prior staleness against current scene/map contracts."""

    if prior_path and not Path(prior_path).is_file():
        return BLOCKING_STALE
    for key in ("world", "backend", "source_map_identity"):
        old = str(entry_contract.get(key) or "")
        new = str(current_contract.get(key) or "")
        if old and new and old != new:
            return BLOCKING_STALE
    for key in ("runtime_map_prior_schema", "public_map_contract_version"):
        old = str(entry_contract.get(key) or "")
        new = str(current_contract.get(key) or "")
        if old and new and old != new:
            return STALE
    old_grader = str(entry_contract.get("grader_version") or "")
    new_grader = str(current_contract.get("grader_version") or "")
    if old_grader and new_grader and old_grader != new_grader:
        return ADVISORY_REGRADE
    return COMPATIBLE


def catalog_entry_auto_enables(entry: dict[str, Any]) -> bool:
    status = str(entry.get("status") or "")
    staleness = str(entry.get("staleness") or entry.get("compatibility") or "")
    path = str(entry.get("path") or "")
    return status == "accepted" and staleness in ACCEPTED_STALENESS and bool(path)


def _entry_constructor_values(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "world_id": payload["world_id"],
        "backend_id": payload["backend_id"],
        "path": payload["path"],
        "status": payload["status"],
        "source": payload["source"],
        "staleness": payload["staleness"],
        "selected_candidate_id": payload["selected_candidate_id"],
        "run_id": payload["run_id"],
        "catalog_key": payload["catalog_key"],
        "product_route": payload["product_route"],
        "producer": payload["producer"],
        "evidence": tuple(payload["evidence"]),
    }


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"runtime prior catalog {key} must be a non-empty string")
    return value.strip()
