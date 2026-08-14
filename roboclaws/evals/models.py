"""Schema models for repo-native eval suites."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object

EVAL_SUITE_SCHEMA = "roboclaws_eval_suite_v1"
EVAL_SAMPLE_SCHEMA = "roboclaws_eval_sample_v1"
EVAL_TRIAL_SCHEMA = "roboclaws_eval_trial_v1"
EVAL_RESULT_SCHEMA = "roboclaws_eval_result_v1"

MISSING_UNAVAILABLE = "unavailable"
MISSING_NOT_APPLICABLE = "not_applicable"
MISSING_SENTINELS = frozenset({MISSING_UNAVAILABLE, MISSING_NOT_APPLICABLE})

FAILURE_CLASSES = frozenset(
    {
        "artifact_missing",
        "environment_blocked",
        "agent_no_completion_claim",
        "private_goal_not_satisfied",
        "partial_progress_only",
        "trajectory_policy_violation",
        "private_truth_leak",
        "tool_argument_invalid",
        "tool_noop_or_repeated_failure",
        "perception_miss",
        "manipulation_failure",
        "map_actionability_failure",
        "planner_proof_missing_or_failed",
        "model_or_provider_unavailable",
        "budget_exhausted",
        "grader_inconclusive",
        "checker_validation_failed",
        "harness_bug_unclassified",
    }
)

RESULT_STATUSES = frozenset({"passed", "failed", "blocked", "inconclusive"})


@dataclass(frozen=True)
class EvalSuite:
    schema: str
    suite_id: str
    version: str
    capability: str
    sample_ids: tuple[str, ...]
    required_graders: tuple[str, ...]
    thresholds: dict[str, Any]
    sample_refs: tuple[str, ...] = ()
    metadata: dict[str, Any] | None = None

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "EvalSuite":
        _require_schema(payload, EVAL_SUITE_SCHEMA)
        sample_ids = _tuple_of_strings(payload, "sample_ids")
        sample_refs = _optional_tuple_of_strings(payload, "sample_refs", default=())
        if sample_refs and len(sample_refs) != len(sample_ids):
            raise ValueError("sample_refs must match sample_ids length")
        return cls(
            schema=str(payload["schema"]),
            suite_id=_required_string(payload, "suite_id"),
            version=_required_string(payload, "version"),
            capability=_required_string(payload, "capability"),
            sample_ids=sample_ids,
            required_graders=_tuple_of_strings(payload, "required_graders"),
            thresholds=_required_mapping(payload, "thresholds"),
            sample_refs=sample_refs,
            metadata=_optional_mapping(payload, "metadata"),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": self.schema,
            "suite_id": self.suite_id,
            "version": self.version,
            "capability": self.capability,
            "sample_ids": list(self.sample_ids),
            "required_graders": list(self.required_graders),
            "thresholds": dict(self.thresholds),
        }
        if self.sample_refs:
            payload["sample_refs"] = list(self.sample_refs)
        if self.metadata is not None:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True)
class EvalSample:
    schema: str
    sample_id: str
    version: str
    surface: str
    intent: str
    preset: str
    world: str
    backend: str
    evidence_lane: str
    camera_labeler: str
    scenario_setup: str
    seed: int
    prompt: str
    goal_contract_hash: str
    allowed_agent_engines: tuple[str, ...]
    trial_count: int
    required_graders: tuple[str, ...]
    private_goal_reference: dict[str, Any]
    provider_profiles: tuple[str, ...] = (MISSING_NOT_APPLICABLE,)
    grader_config: dict[str, Any] | None = None
    artifact_dependencies: dict[str, Any] | None = None
    launch_overrides: dict[str, Any] | None = None

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "EvalSample":
        _require_schema(payload, EVAL_SAMPLE_SCHEMA)
        _require_explicit_identity(payload, "camera_labeler")
        _require_explicit_identity(payload, "prompt")
        _require_explicit_identity(payload, "goal_contract_hash")
        trial_count = _required_int(payload, "trial_count")
        if trial_count < 1:
            raise ValueError("trial_count must be >= 1")
        return cls(
            schema=str(payload["schema"]),
            sample_id=_required_string(payload, "sample_id"),
            version=_required_string(payload, "version"),
            surface=_required_string(payload, "surface"),
            intent=_required_string(payload, "intent"),
            preset=_required_string(payload, "preset"),
            world=_required_string(payload, "world"),
            backend=_required_string(payload, "backend"),
            evidence_lane=_required_string(payload, "evidence_lane"),
            camera_labeler=_required_string(payload, "camera_labeler"),
            scenario_setup=_required_string(payload, "scenario_setup"),
            seed=_required_int(payload, "seed"),
            prompt=_required_string(payload, "prompt"),
            goal_contract_hash=_required_string(payload, "goal_contract_hash"),
            allowed_agent_engines=_tuple_of_strings(payload, "allowed_agent_engines"),
            trial_count=trial_count,
            required_graders=_tuple_of_strings(payload, "required_graders"),
            private_goal_reference=_required_mapping(payload, "private_goal_reference"),
            provider_profiles=_optional_tuple_of_strings(
                payload,
                "provider_profiles",
                default=(MISSING_NOT_APPLICABLE,),
            ),
            grader_config=_optional_mapping(payload, "grader_config"),
            artifact_dependencies=_optional_mapping(payload, "artifact_dependencies"),
            launch_overrides=_optional_mapping(payload, "launch_overrides"),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": self.schema,
            "sample_id": self.sample_id,
            "version": self.version,
            "surface": self.surface,
            "intent": self.intent,
            "preset": self.preset,
            "world": self.world,
            "backend": self.backend,
            "evidence_lane": self.evidence_lane,
            "camera_labeler": self.camera_labeler,
            "scenario_setup": self.scenario_setup,
            "seed": self.seed,
            "prompt": self.prompt,
            "goal_contract_hash": self.goal_contract_hash,
            "allowed_agent_engines": list(self.allowed_agent_engines),
            "provider_profiles": list(self.provider_profiles),
            "trial_count": self.trial_count,
            "required_graders": list(self.required_graders),
            "private_goal_reference": dict(self.private_goal_reference),
        }
        if self.grader_config is not None:
            payload["grader_config"] = dict(self.grader_config)
        if self.artifact_dependencies is not None:
            payload["artifact_dependencies"] = dict(self.artifact_dependencies)
        if self.launch_overrides is not None:
            payload["launch_overrides"] = dict(self.launch_overrides)
        return payload


@dataclass(frozen=True)
class EvalTrial:
    schema: str
    suite_id: str
    suite_version: str
    sample_id: str
    sample_version: str
    trial_id: str
    repetition_index: int
    surface: str
    intent: str
    preset: str
    world: str
    backend: str
    evidence_lane: str
    camera_labeler: str
    scenario_setup: str
    seed: int
    prompt: str
    goal_contract_hash: str
    agent_engine: str
    runner_class: str
    provider_profile: str
    model: str
    skill_name: str
    prompt_source: str
    mcp_profile: str
    tool_surface: tuple[str, ...]
    budgets: dict[str, Any]
    runtime: dict[str, Any]
    limitations: tuple[str, ...]

    @classmethod
    def from_sample(
        cls,
        sample: EvalSample,
        *,
        suite: EvalSuite,
        trial_id: str,
        repetition_index: int,
        agent_engine: str,
        runner_class: str,
        provider_profile: str = MISSING_UNAVAILABLE,
        model: str = MISSING_UNAVAILABLE,
        skill_name: str = MISSING_UNAVAILABLE,
        prompt_source: str = MISSING_UNAVAILABLE,
        mcp_profile: str = MISSING_UNAVAILABLE,
        tool_surface: tuple[str, ...] | list[str] = (MISSING_UNAVAILABLE,),
        budgets: dict[str, Any] | None = None,
        runtime: dict[str, Any] | None = None,
        limitations: tuple[str, ...] | list[str] = (),
    ) -> "EvalTrial":
        if repetition_index < 0:
            raise ValueError("repetition_index must be >= 0")
        if sample.sample_id not in suite.sample_ids:
            raise ValueError(
                f"sample {sample.sample_id!r} is not listed in suite {suite.suite_id!r}"
            )
        if agent_engine not in sample.allowed_agent_engines:
            raise ValueError(
                f"agent_engine {agent_engine!r} is not allowed for sample {sample.sample_id!r}"
            )
        return cls(
            schema=EVAL_TRIAL_SCHEMA,
            suite_id=suite.suite_id,
            suite_version=suite.version,
            sample_id=sample.sample_id,
            sample_version=sample.version,
            trial_id=trial_id,
            repetition_index=repetition_index,
            surface=sample.surface,
            intent=sample.intent,
            preset=sample.preset,
            world=sample.world,
            backend=sample.backend,
            evidence_lane=sample.evidence_lane,
            camera_labeler=sample.camera_labeler,
            scenario_setup=sample.scenario_setup,
            seed=sample.seed,
            prompt=sample.prompt,
            goal_contract_hash=sample.goal_contract_hash,
            agent_engine=agent_engine,
            runner_class=runner_class,
            provider_profile=provider_profile,
            model=model,
            skill_name=skill_name,
            prompt_source=prompt_source,
            mcp_profile=mcp_profile,
            tool_surface=_normalize_tool_surface(tool_surface),
            budgets=_normalized_budgets(budgets, repetition_index=repetition_index),
            runtime=_normalized_runtime(runtime),
            limitations=tuple(str(item) for item in limitations),
        )

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "EvalTrial":
        _require_schema(payload, EVAL_TRIAL_SCHEMA)
        for key in _TRIAL_IDENTITY_FIELDS:
            _require_explicit_identity(payload, key)
        repetition_index = _required_int(payload, "repetition_index")
        if repetition_index < 0:
            raise ValueError("repetition_index must be >= 0")
        return cls(
            schema=str(payload["schema"]),
            suite_id=_required_string(payload, "suite_id"),
            suite_version=_required_string(payload, "suite_version"),
            sample_id=_required_string(payload, "sample_id"),
            sample_version=_required_string(payload, "sample_version"),
            trial_id=_required_string(payload, "trial_id"),
            repetition_index=repetition_index,
            surface=_required_string(payload, "surface"),
            intent=_required_string(payload, "intent"),
            preset=_required_string(payload, "preset"),
            world=_required_string(payload, "world"),
            backend=_required_string(payload, "backend"),
            evidence_lane=_required_string(payload, "evidence_lane"),
            camera_labeler=_required_string(payload, "camera_labeler"),
            scenario_setup=_required_string(payload, "scenario_setup"),
            seed=_required_int(payload, "seed"),
            prompt=_required_string(payload, "prompt"),
            goal_contract_hash=_required_string(payload, "goal_contract_hash"),
            agent_engine=_required_string(payload, "agent_engine"),
            runner_class=_required_string(payload, "runner_class"),
            provider_profile=_required_string(payload, "provider_profile"),
            model=_required_string(payload, "model"),
            skill_name=_required_string(payload, "skill_name"),
            prompt_source=_required_string(payload, "prompt_source"),
            mcp_profile=_required_string(payload, "mcp_profile"),
            tool_surface=_tuple_of_strings(payload, "tool_surface"),
            budgets=_normalized_budgets(
                _required_mapping(payload, "budgets"),
                repetition_index=repetition_index,
            ),
            runtime=_normalized_runtime(_required_mapping(payload, "runtime")),
            limitations=_tuple_of_strings(payload, "limitations", allow_empty=True),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "suite_id": self.suite_id,
            "suite_version": self.suite_version,
            "sample_id": self.sample_id,
            "sample_version": self.sample_version,
            "trial_id": self.trial_id,
            "repetition_index": self.repetition_index,
            "surface": self.surface,
            "intent": self.intent,
            "preset": self.preset,
            "world": self.world,
            "backend": self.backend,
            "evidence_lane": self.evidence_lane,
            "camera_labeler": self.camera_labeler,
            "scenario_setup": self.scenario_setup,
            "seed": self.seed,
            "prompt": self.prompt,
            "goal_contract_hash": self.goal_contract_hash,
            "agent_engine": self.agent_engine,
            "runner_class": self.runner_class,
            "provider_profile": self.provider_profile,
            "model": self.model,
            "skill_name": self.skill_name,
            "prompt_source": self.prompt_source,
            "mcp_profile": self.mcp_profile,
            "tool_surface": list(self.tool_surface),
            "budgets": dict(self.budgets),
            "runtime": dict(self.runtime),
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class EvalResult:
    schema: str
    identity: dict[str, Any]
    status: str
    failure_class: str
    grader_outputs: dict[str, Any]
    artifacts: dict[str, Any]
    artifact_schema_versions: dict[str, Any]
    metrics: dict[str, Any]
    limitations: tuple[str, ...]

    @classmethod
    def from_trial(
        cls,
        trial: EvalTrial,
        *,
        status: str,
        failure_class: str = MISSING_NOT_APPLICABLE,
        grader_outputs: dict[str, Any],
        artifacts: dict[str, Any] | None = None,
        artifact_schema_versions: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        limitations: tuple[str, ...] | list[str] = (),
    ) -> "EvalResult":
        _validate_result_status(status)
        _validate_failure_class(status=status, failure_class=failure_class)
        return cls(
            schema=EVAL_RESULT_SCHEMA,
            identity=trial.to_dict() | {"schema": "roboclaws_eval_identity_v1"},
            status=status,
            failure_class=failure_class,
            grader_outputs=dict(grader_outputs),
            artifacts=dict(artifacts or {}),
            artifact_schema_versions=_normalized_artifact_schema_versions(
                artifacts=artifacts,
                artifact_schema_versions=artifact_schema_versions,
            ),
            metrics=dict(metrics or {}),
            limitations=tuple(str(item) for item in limitations or trial.limitations),
        )

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "EvalResult":
        _require_schema(payload, EVAL_RESULT_SCHEMA)
        status = _required_string(payload, "status")
        failure_class = _required_string(payload, "failure_class")
        _validate_result_status(status)
        _validate_failure_class(status=status, failure_class=failure_class)
        identity = _required_mapping(payload, "identity")
        for key in _RESULT_IDENTITY_FIELDS:
            _require_explicit_identity(identity, key)
        artifacts = _optional_mapping(payload, "artifacts") or {}
        return cls(
            schema=str(payload["schema"]),
            identity=identity,
            status=status,
            failure_class=failure_class,
            grader_outputs=_required_mapping(payload, "grader_outputs"),
            artifacts=artifacts,
            artifact_schema_versions=_normalized_artifact_schema_versions(
                artifacts=artifacts,
                artifact_schema_versions=_optional_mapping(payload, "artifact_schema_versions"),
            ),
            metrics=_optional_mapping(payload, "metrics") or {},
            limitations=tuple(str(item) for item in payload.get("limitations") or ()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "identity": dict(self.identity),
            "status": self.status,
            "failure_class": self.failure_class,
            "grader_outputs": dict(self.grader_outputs),
            "artifacts": dict(self.artifacts),
            "artifact_schema_versions": dict(self.artifact_schema_versions),
            "metrics": dict(self.metrics),
            "limitations": list(self.limitations),
        }


def load_eval_suite(path: Path) -> EvalSuite:
    return EvalSuite.from_mapping(_load_json(path))


def load_eval_sample(path: Path) -> EvalSample:
    return EvalSample.from_mapping(_load_json(path))


_TRIAL_IDENTITY_FIELDS = (
    "camera_labeler",
    "preset",
    "prompt",
    "goal_contract_hash",
    "provider_profile",
    "model",
    "skill_name",
    "prompt_source",
    "mcp_profile",
)

_RESULT_IDENTITY_FIELDS = (
    "suite_id",
    "suite_version",
    "sample_id",
    "sample_version",
    "trial_id",
    "repetition_index",
    "surface",
    "intent",
    "preset",
    "world",
    "backend",
    "evidence_lane",
    "camera_labeler",
    "scenario_setup",
    "seed",
    "prompt",
    "goal_contract_hash",
    "agent_engine",
    "runner_class",
    "provider_profile",
    "model",
    "skill_name",
    "prompt_source",
    "mcp_profile",
    "tool_surface",
    "budgets",
    "runtime",
)


def _load_json(path: Path) -> dict[str, Any]:
    return read_json_object(Path(path), label="eval JSON")


def _validate_result_status(status: str) -> None:
    if status not in RESULT_STATUSES:
        raise ValueError(f"unknown eval_result status {status!r}")


def _validate_failure_class(*, status: str, failure_class: str) -> None:
    if status == "failed" and failure_class in MISSING_SENTINELS:
        raise ValueError("failed eval_result requires failure_class")
    if failure_class not in FAILURE_CLASSES and failure_class not in MISSING_SENTINELS:
        raise ValueError(f"unknown failure_class {failure_class!r}")


def _normalized_budgets(
    budgets: dict[str, Any] | None,
    *,
    repetition_index: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "steps": MISSING_UNAVAILABLE,
        "time_s": MISSING_UNAVAILABLE,
        "token": MISSING_UNAVAILABLE,
        "cost": MISSING_UNAVAILABLE,
        "retry": MISSING_UNAVAILABLE,
        "repetition": repetition_index,
    }
    payload.update(dict(budgets or {}))
    return payload


def _normalized_runtime(runtime: dict[str, Any] | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "host": MISSING_UNAVAILABLE,
        "hardware": MISSING_UNAVAILABLE,
        "network": MISSING_UNAVAILABLE,
        "local_live_limitations": [],
    }
    payload.update(dict(runtime or {}))
    return payload


def _normalize_tool_surface(tool_surface: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    items = tuple(str(item) for item in tool_surface)
    return items or (MISSING_UNAVAILABLE,)


def _normalized_artifact_schema_versions(
    *,
    artifacts: dict[str, Any] | None,
    artifact_schema_versions: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(artifact_schema_versions or {})
    for key in artifacts or {}:
        payload.setdefault(str(key), MISSING_UNAVAILABLE)
    return payload


def _require_schema(payload: dict[str, Any], expected: str) -> None:
    actual = payload.get("schema")
    if actual != expected:
        raise ValueError(f"schema must be {expected!r}, got {actual!r}")


def _require_explicit_identity(payload: dict[str, Any], key: str) -> None:
    if key not in payload:
        raise ValueError(f"missing explicit identity field {key}")
    if payload[key] is None:
        raise ValueError(f"identity field {key} must use an explicit missing sentinel")


def _required_string(payload: dict[str, Any], key: str) -> str:
    if key not in payload:
        raise ValueError(f"missing required field {key}")
    value = payload[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _required_int(payload: dict[str, Any], key: str) -> int:
    if key not in payload:
        raise ValueError(f"missing required field {key}")
    value = payload[key]
    if not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _required_mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    if key not in payload:
        raise ValueError(f"missing required field {key}")
    value = payload[key]
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return dict(value)


def _optional_mapping(payload: dict[str, Any], key: str) -> dict[str, Any] | None:
    if key not in payload:
        return None
    value = payload[key]
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return dict(value)


def _tuple_of_strings(
    payload: dict[str, Any],
    key: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if key not in payload:
        raise ValueError(f"missing required field {key}")
    value = payload[key]
    if not isinstance(value, list | tuple):
        raise ValueError(f"{key} must be a list")
    if any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{key} must be a list of non-empty strings")
    items = tuple(value)
    if not allow_empty and not items:
        raise ValueError(f"{key} must not be empty")
    return items


def _optional_tuple_of_strings(
    payload: dict[str, Any],
    key: str,
    *,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    if key not in payload:
        return default
    return _tuple_of_strings(payload, key)
