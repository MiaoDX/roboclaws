"""Strict contracts and trust-boundary validation for Eval Evolution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar

from roboclaws.core.json_sources import read_json_object

CAMPAIGN_SCHEMA = "eval_evolution_campaign_v1"
FEEDBACK_SCHEMA = "eval_evolution_feedback_v1"
CANDIDATE_SCHEMA = "eval_evolution_candidate_v1"
SELECTION_SCHEMA = "eval_evolution_selection_report_v1"
PROMOTION_SCHEMA = "eval_evolution_promotion_manifest_v1"

_FORBIDDEN_KEY_PARTS = frozenset(
    {
        "acceptable_destination",
        "api_key",
        "credential",
        "endpoint",
        "generated_mess",
        "grader_config",
        "grader_internal",
        "holdout",
        "private_goal",
        "private_truth",
        "provider_key",
        "raw_provider",
        "selection_threshold",
        "scenario_secret",
        "secret",
        "token_value",
    }
)
_HOST_PATH_RE = re.compile(r"(?:^|\s)/(?:home|root|Users|workspace|workspaces|mnt)/\S+")
_PROC_PATH_RE = re.compile(r"(?:^|\s)/proc(?:/|\s|$)")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_FORBIDDEN_MUTABLE_ROOTS = frozenset({"evals", "output", "roboclaws/evals"})
_CANDIDATE_STATUSES = frozenset(
    {"proposed", "gated", "evaluated", "accepted", "rejected", "blocked", "inconclusive"}
)


@dataclass(frozen=True)
class Campaign:
    campaign_id: str
    target: dict[str, Any]
    optimizer: dict[str, Any]
    robot: dict[str, Any]
    training: dict[str, Any]
    sealed_holdout_ref: str
    gates: dict[str, Any]
    selection: dict[str, Any]
    budgets: dict[str, Any]
    identity: dict[str, Any]
    feedback_schema: str
    candidate_limits: dict[str, Any]
    promotion_policy: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "campaign_id",
            "target",
            "optimizer",
            "robot",
            "training",
            "sealed_holdout_ref",
            "gates",
            "selection",
            "budgets",
            "identity",
            "feedback_schema",
            "candidate_limits",
            "promotion_policy",
        }
    )

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> Campaign:
        _require_exact_fields(payload, cls._FIELDS, "campaign")
        _require_schema(payload, CAMPAIGN_SCHEMA)
        target = _mapping(payload, "target")
        optimizer = _mapping(payload, "optimizer")
        robot = _mapping(payload, "robot")
        _require_exact_fields(
            target,
            frozenset({"kind", "id", "mutable_paths", "baseline_commit", "target_sha256"}),
            "campaign target",
        )
        _require_exact_fields(
            optimizer,
            frozenset({"agent_engine", "provider_profile", "model", "settings"}),
            "campaign optimizer",
        )
        _require_exact_fields(
            robot,
            frozenset({"agent_engine", "provider_profile", "model"}),
            "campaign robot",
        )
        _validate_agent_roles(optimizer, robot)
        _validate_target(target)
        _require_digest(target, "target_sha256")
        _require_commit(target, "baseline_commit")
        budgets = _mapping(payload, "budgets")
        _validate_budgets(budgets)
        if payload.get("feedback_schema") != FEEDBACK_SCHEMA:
            raise ValueError(f"feedback_schema must be {FEEDBACK_SCHEMA}")
        return cls(
            campaign_id=_string(payload, "campaign_id"),
            target=target,
            optimizer=optimizer,
            robot=robot,
            training=_mapping(payload, "training"),
            sealed_holdout_ref=_string(payload, "sealed_holdout_ref"),
            gates=_mapping(payload, "gates"),
            selection=_mapping(payload, "selection"),
            budgets=budgets,
            identity=_mapping(payload, "identity"),
            feedback_schema=str(payload["feedback_schema"]),
            candidate_limits=_mapping(payload, "candidate_limits"),
            promotion_policy=_string(payload, "promotion_policy"),
        )


@dataclass(frozen=True)
class Feedback:
    payload: dict[str, Any]

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> Feedback:
        required = frozenset(
            {
                "schema",
                "campaign_id",
                "target",
                "public_context",
                "failure",
                "quality",
                "work",
                "prior_candidate",
                "remaining_budget",
            }
        )
        _require_exact_fields(payload, required, "feedback")
        _require_schema(payload, FEEDBACK_SCHEMA)
        validate_optimizer_visible_payload(payload)
        return cls(dict(payload))

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)


@dataclass(frozen=True)
class Candidate:
    payload: dict[str, Any]

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> Candidate:
        required = frozenset(
            {
                "schema",
                "candidate_id",
                "campaign_id",
                "target_kind",
                "parent_commit",
                "parent_target_sha256",
                "hypothesis",
                "patch",
                "patch_sha256",
                "mutable_paths",
                "materialized_sha256",
                "optimizer_identity",
                "optimizer_usage",
                "gates",
                "eval_identities",
                "terminal_status",
            }
        )
        _require_exact_fields(payload, required, "candidate")
        _require_schema(payload, CANDIDATE_SCHEMA)
        for key in ("parent_target_sha256", "patch_sha256", "materialized_sha256"):
            _require_digest(payload, key)
        _require_commit(payload, "parent_commit")
        _string_list(payload, "mutable_paths")
        if _mapping(payload, "optimizer_identity").get("agent_engine") != "openai-agents-sdk":
            raise ValueError("candidate optimizer identity must use openai-agents-sdk")
        if payload.get("terminal_status") not in _CANDIDATE_STATUSES:
            raise ValueError("unsupported candidate terminal_status")
        return cls(dict(payload))

    def validate_for_campaign(self, campaign: Campaign) -> None:
        if self.payload["campaign_id"] != campaign.campaign_id:
            raise ValueError("candidate campaign identity mismatch")
        if self.payload["parent_commit"] != campaign.target["baseline_commit"]:
            raise ValueError("candidate has stale baseline commit")
        if self.payload["parent_target_sha256"] != campaign.target["target_sha256"]:
            raise ValueError("candidate has stale target identity")
        if self.payload["target_kind"] != campaign.target["kind"]:
            raise ValueError("candidate target kind mismatch")
        if tuple(self.payload["mutable_paths"]) != tuple(campaign.target["mutable_paths"]):
            raise ValueError("candidate mutable paths do not match campaign authority")
        _validate_candidate_patch(self.payload, campaign.candidate_limits)


def _validate_agent_roles(optimizer: dict[str, Any], robot: dict[str, Any]) -> None:
    if optimizer.get("agent_engine") != "openai-agents-sdk":
        raise ValueError("optimizer.agent_engine must be openai-agents-sdk")
    if robot.get("agent_engine") != "openai-agents-sdk":
        raise ValueError("robot.agent_engine must be openai-agents-sdk")
    if optimizer == robot:
        raise ValueError("optimizer and robot identities must be distinct")


def _validate_target(target: dict[str, Any]) -> None:
    if target.get("kind") not in {"skill", "mcp-description", "mcp-behavior"}:
        raise ValueError("target.kind must be skill, mcp-description, or mcp-behavior")
    mutable_paths = _string_list(target, "mutable_paths")
    if not mutable_paths:
        raise ValueError("target.mutable_paths must not be empty")
    for mutable_path in mutable_paths:
        _validate_relative_path(mutable_path)
        if any(
            mutable_path == root or mutable_path.startswith(f"{root}/")
            for root in _FORBIDDEN_MUTABLE_ROOTS
        ):
            raise ValueError(f"target.mutable_paths contains forbidden path: {mutable_path}")
    if target["kind"] == "skill" and (
        len(mutable_paths) != 1 or not re.fullmatch(r"skills/[^/]+/SKILL\.md", mutable_paths[0])
    ):
        raise ValueError("skill campaigns must target exactly one skills/<name>/SKILL.md")


def _validate_budgets(budgets: dict[str, Any]) -> None:
    for key in (
        "optimizer_turns",
        "candidates",
        "live_trials",
        "provider_concurrency",
        "tokens",
        "cost_usd",
        "wall_time_s",
        "timeout_s",
        "retries",
    ):
        value = budgets.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise ValueError(f"budgets.{key} must be a non-negative number")


def _validate_candidate_patch(candidate: dict[str, Any], candidate_limits: dict[str, Any]) -> None:
    patch = candidate["patch"]
    if not isinstance(patch, str):
        raise ValueError("candidate patch must be text")
    patch_bytes = patch.encode("utf-8")
    if b"\x00" in patch_bytes:
        raise ValueError("candidate patch must not contain binary data")
    max_patch_bytes = candidate_limits.get("max_patch_bytes")
    if not isinstance(max_patch_bytes, int) or max_patch_bytes < 1:
        raise ValueError("candidate_limits.max_patch_bytes must be a positive integer")
    if len(patch_bytes) > max_patch_bytes:
        raise ValueError("candidate patch exceeds max_patch_bytes")
    max_changed_paths = candidate_limits.get("max_changed_paths")
    if not isinstance(max_changed_paths, int) or max_changed_paths < 1:
        raise ValueError("candidate_limits.max_changed_paths must be a positive integer")
    if len(candidate["mutable_paths"]) > max_changed_paths:
        raise ValueError("candidate paths exceed max_changed_paths")
    if sha256(patch_bytes).hexdigest() != candidate["patch_sha256"]:
        raise ValueError("candidate patch digest mismatch")


@dataclass(frozen=True)
class SelectionReport:
    payload: dict[str, Any]

    @property
    def campaign_id(self) -> str:
        return str(self.payload["campaign_id"])

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> SelectionReport:
        required = frozenset(
            {
                "schema",
                "campaign_id",
                "baseline_identity",
                "candidate_id",
                "training",
                "holdout",
                "quality_gates",
                "minimum_improvement",
                "status",
                "digests",
            }
        )
        _require_exact_fields(payload, required, "selection report")
        _require_schema(payload, SELECTION_SCHEMA)
        if payload.get("status") not in {"accepted", "rejected", "blocked", "inconclusive"}:
            raise ValueError("unsupported selection report status")
        return cls(dict(payload))


@dataclass(frozen=True)
class PromotionManifest:
    payload: dict[str, Any]

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> PromotionManifest:
        required = frozenset(
            {
                "schema",
                "campaign_id",
                "candidate_id",
                "maintainer_approved",
                "bindings",
                "reviewer",
            }
        )
        _require_exact_fields(payload, required, "promotion manifest")
        _require_schema(payload, PROMOTION_SCHEMA)
        if not isinstance(payload.get("maintainer_approved"), bool):
            raise ValueError("maintainer_approved must be boolean")
        return cls(dict(payload))

    def validate_for_report(self, report: SelectionReport) -> None:
        if not self.payload["maintainer_approved"]:
            raise ValueError("promotion requires maintainer_approved=true")
        if report.payload["status"] != "accepted":
            raise ValueError("promotion requires an accepted selection report")
        if self.payload["campaign_id"] != report.campaign_id:
            raise ValueError("promotion campaign identity mismatch")
        if self.payload["candidate_id"] != report.payload["candidate_id"]:
            raise ValueError("promotion candidate identity mismatch")


def load_campaign(path: Path) -> Campaign:
    return Campaign.from_mapping(read_json_object(path, label="eval evolution campaign"))


def load_selection_report(path: Path) -> SelectionReport:
    return SelectionReport.from_mapping(read_json_object(path, label="eval evolution selection"))


def load_promotion_manifest(path: Path) -> PromotionManifest:
    return PromotionManifest.from_mapping(read_json_object(path, label="eval evolution promotion"))


def validate_optimizer_visible_payload(payload: Any, *, path: str = "$") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
            if any(part in normalized for part in _FORBIDDEN_KEY_PARTS):
                raise ValueError(
                    f"optimizer-visible payload contains forbidden key at {path}.{key}"
                )
            validate_optimizer_visible_payload(value, path=f"{path}.{key}")
        return
    if isinstance(payload, list):
        for index, value in enumerate(payload):
            validate_optimizer_visible_payload(value, path=f"{path}[{index}]")
        return
    if isinstance(payload, str):
        if _HOST_PATH_RE.search(payload):
            raise ValueError(f"optimizer-visible payload contains host path at {path}")
        if _PROC_PATH_RE.search(payload):
            raise ValueError(f"optimizer-visible payload contains proc path at {path}")


def validate_candidate_authority(
    workspace: Path, changed_paths: tuple[str, ...], allowed_paths: tuple[str, ...]
) -> None:
    allowed = set(allowed_paths)
    for raw_path in changed_paths:
        path = _validate_relative_path(raw_path)
        if raw_path not in allowed:
            raise ValueError(f"candidate path is not campaign-authorized: {raw_path}")
        current = workspace
        for part in path.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError(f"candidate path crosses symlink: {raw_path}")


def campaign_terminal_status(*, budget_exhausted: bool, quality_failed: bool) -> str:
    if budget_exhausted:
        return "inconclusive"
    return "failed" if quality_failed else "passed"


def _require_schema(payload: dict[str, Any], expected: str) -> None:
    if payload.get("schema") != expected:
        raise ValueError(f"schema must be {expected}")


def _require_exact_fields(payload: dict[str, Any], expected: frozenset[str], label: str) -> None:
    missing = expected - payload.keys()
    if missing:
        raise ValueError(f"missing {label} field(s): {', '.join(sorted(missing))}")
    extra = payload.keys() - expected
    if extra:
        raise ValueError(f"unsupported {label} field(s): {', '.join(sorted(extra))}")


def _string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return dict(value)


def _string_list(payload: dict[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{key} must be a list of non-empty strings")
    return tuple(value)


def _require_digest(payload: dict[str, Any], key: str) -> None:
    if not _SHA256_RE.fullmatch(str(payload.get(key, ""))):
        raise ValueError(f"{key} must be a lowercase SHA-256 digest")


def _require_commit(payload: dict[str, Any], key: str) -> None:
    if not _COMMIT_RE.fullmatch(str(payload.get(key, ""))):
        raise ValueError(f"{key} must be a 40-character lowercase commit id")


def _validate_relative_path(raw_path: str) -> PurePosixPath:
    path = PurePosixPath(raw_path)
    if path.is_absolute() or ".." in path.parts or str(path) != raw_path:
        raise ValueError(f"candidate path must be relative normalized path: {raw_path}")
    return path
