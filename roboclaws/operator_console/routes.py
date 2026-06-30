"""Launch-axis registry for the standalone agent operator console."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from roboclaws.agents.provider_registry import (
    provider_route_specs,
    route_payload,
)
from roboclaws.household.profiles import (
    CAMERA_GROUNDED_LABELS_LANE,
    cleanup_evidence_lane_names,
)
from roboclaws.launch.agent_engines import AGENT_ENGINE_SPECS
from roboclaws.launch.backends import BACKEND_SPECS, BackendSpec
from roboclaws.launch.catalog import LaunchError, resolve_surface_launch
from roboclaws.launch.environment_setup import (
    ENVIRONMENT_SETUP_BASELINE,
    ENVIRONMENT_SETUP_RELOCATE_CLEANUP_RELATED_OBJECTS,
)
from roboclaws.launch.intents import TASK_INTENT_SPECS
from roboclaws.launch.worlds import MOLMOSPACES_CONSOLE_WORLD_IDS, WORLD_SPECS

DEFAULT_PROMPTS = {
    "cleanup": "帮我收拾这个房间",
    "map-build": "帮我建立这个房间的 Runtime Metric Map",
    "open-ended": "在这个场景中完成开放性导航任务，并报告你看到的证据。",
}

AGIBOT_CAMERA_LABELER = "grounding-dino"
SIMULATION_CAMERA_LABELER = "grounding-dino"

REAL_EVIDENCE_LANES = cleanup_evidence_lane_names()
ISAAC_SUPPORTED_EVIDENCE_LANES = REAL_EVIDENCE_LANES
B1_ROBOT_PROOF_REQUIRED_OVERRIDES: tuple[str, ...] = ()


@dataclass(frozen=True)
class RouteGate:
    """A start gate surfaced to operators before a live robot run."""

    id: str
    label: str
    kind: str
    required: bool = True
    severity: str = "blocking"
    help_text: str = ""

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ConsoleLaunchSelection:
    """Canonical operator-console launch selection."""

    world_id: str
    backend_id: str
    intent_id: str
    agent_engine_id: str
    provider_profile: str | None
    evidence_lane: str
    scenario_setup: str
    preset_id: str = ""
    enabled: bool = True
    unsupported_reason: str = ""
    required_overrides: tuple[str, ...] = ()
    default_overrides: tuple[str, ...] = ()
    gates: tuple[RouteGate, ...] = ()
    supports_prompt: bool = True
    supports_operator_steer: bool = False
    supports_paused_handoff_resume: bool = False
    supports_relative_navigation_control: bool = False
    emergency_stop_required: bool = False

    @property
    def id(self) -> str:
        return "::".join(
            (
                self.world_id,
                self.backend_id,
                selection_task_selector(self.intent_id),
                self.agent_engine_id,
                self.evidence_lane,
            )
        )

    @property
    def surface(self) -> str:
        return WORLD_SPECS[self.world_id].surface_id

    @property
    def backend(self) -> BackendSpec:
        return BACKEND_SPECS[self.backend_id]

    @property
    def lock_name(self) -> str:
        return self.backend.lock_name

    @property
    def resource_kind(self) -> str:
        return self.backend.resource_kind

    @property
    def checker_id(self) -> str:
        return TASK_INTENT_SPECS[self.intent_id].checker_id

    @property
    def task_prompt_default(self) -> str:
        return DEFAULT_PROMPTS.get(self.intent_id, "")

    @property
    def launch_default_overrides(self) -> tuple[str, ...]:
        return (
            *WORLD_SPECS[self.world_id].default_overrides,
            *BACKEND_SPECS[self.backend_id].default_overrides,
            *self.default_overrides,
        )

    @property
    def label(self) -> str:
        world = WORLD_SPECS[self.world_id].label
        backend = self.backend.label
        intent = _intent_label(self.intent_id)
        engine = AGENT_ENGINE_SPECS[self.agent_engine_id].label
        return f"{world} / {backend} / {intent} / {engine}"

    @property
    def disabled_reason(self) -> str:
        return self.unsupported_reason

    def base_args(self) -> list[str]:
        args = [
            f"surface={self.surface}",
            f"world={self.world_id}",
            f"backend={self.backend_id}",
            f"agent_engine={self.agent_engine_id}",
            f"evidence_lane={self.evidence_lane}",
            f"scenario_setup={self.scenario_setup}",
            *self.launch_default_overrides,
        ]
        if self.preset_id:
            args.insert(3, f"preset={self.preset_id}")
        if self.provider_profile:
            args.append(f"provider_profile={self.provider_profile}")
        return args

    def to_payload(self) -> dict[str, Any]:
        world = WORLD_SPECS[self.world_id]
        backend = self.backend
        engine = AGENT_ENGINE_SPECS[self.agent_engine_id]
        payload = {
            "id": self.id,
            "label": self.label,
            "world_id": self.world_id,
            "world_label": world.label,
            "backend_id": self.backend_id,
            "backend_label": backend.label,
            "intent_id": self.intent_id,
            "intent": self.intent_id,
            "preset_id": self.preset_id,
            "preset": self.preset_id,
            "agent_engine_id": self.agent_engine_id,
            "agent_engine_label": engine.label,
            "agent_engine_availability": engine.availability,
            "provider_profile": self.provider_profile or "",
            "supported_provider_profiles": list(engine.supported_provider_profiles),
            "provider_routes": [
                route_payload(route, agent_engine=self.agent_engine_id)
                for route in provider_route_specs()
                if self.agent_engine_id in route.supported_engines
            ],
            "default_provider_profile": engine.default_provider_profile or "",
            "evidence_lane": self.evidence_lane,
            "scenario_setup": self.scenario_setup,
            "surface": self.surface,
            "enabled": self.enabled,
            "unsupported_reason": self.unsupported_reason,
            "checker_id": self.checker_id,
            "lock_name": backend.lock_name,
            "resource_kind": backend.resource_kind,
            "supports_prompt": self.supports_prompt,
            "supports_operator_steer": self.supports_operator_steer,
            "supports_paused_handoff_resume": self.supports_paused_handoff_resume,
            "supports_relative_navigation_control": self.supports_relative_navigation_control,
            "emergency_stop_required": self.emergency_stop_required,
            "required_overrides": list(self.required_overrides),
            "default_overrides": list(self.default_overrides),
            "launch_default_overrides": list(self.launch_default_overrides),
            "preview_assets": _preview_assets_payload(world.preview_assets),
            "gates": [gate.to_payload() for gate in self.gates],
            "required_gates": [gate.to_payload() for gate in self.gates if gate.required],
            "state": "enabled" if self.enabled else "disabled",
            "blocker": self.unsupported_reason,
            "default_prompt": self.task_prompt_default,
            "prompt_disabled_reason": (
                ""
                if self.supports_prompt
                else (
                    "This selection cannot accept a custom prompt safely. "
                    "Use the default task prompt."
                )
            ),
            "field_groups": list(backend.field_groups),
            "view_modes": list(backend.view_modes),
            "argv_preview": ["just", "run::surface", *self.base_args()],
            "command_preview": ["just", "run::surface", *self.base_args()],
            "intent_options": [_intent_option(self.intent_id)],
            "default_intent": self.intent_id,
            "supported_intents": [self.intent_id],
            "preset_options": [_preset_option(self.preset_id)] if self.preset_id else [],
            "default_preset": self.preset_id,
            "supported_presets": [self.preset_id] if self.preset_id else [],
        }
        return payload


PROVIDER_KEY_GATE = RouteGate(
    id="provider_key",
    label="Agent provider route present",
    kind="provider_key",
    help_text="Load a repo-local OpenAI Agents SDK provider route before launch.",
)
MCP_PORT_FREE_GATE = RouteGate(
    id="mcp_port_free",
    label="MCP port available",
    kind="mcp_port_free",
    help_text="The runner will start its MCP server on this host and port.",
)
AGIBOT_CONTEXT_GATE = RouteGate(
    id="context_json",
    label="Agibot map context JSON attached",
    kind="request_field",
    help_text="Attach a completed Agibot map context JSON.",
)
AGIBOT_LOCALIZATION_GATE = RouteGate(
    id="localization_ready",
    label="Localization available for real movement",
    kind="operator_gate",
    required=False,
    severity="capability",
    help_text="Required only when real movement is enabled.",
)
AGIBOT_ENABLEMENT_GATE = RouteGate(
    id="run_enabled",
    label="Run enablement available for real movement",
    kind="operator_gate",
    required=False,
    severity="capability",
    help_text="Required only when real movement is enabled.",
)
AGIBOT_ESTOP_GATE = RouteGate(
    id="estop_ready",
    label="E-stop/manual-stop visible for real movement",
    kind="operator_gate",
    required=False,
    severity="capability",
    help_text="Required only when real movement is enabled.",
)
B1_ALIGNMENT_ARTIFACT_GATE = RouteGate(
    id="b1_alignment_artifact",
    label="B1 verified alignment artifact available",
    kind="request_field",
    help_text=(
        "Optional: leave empty to generate a B1 / Map 12 alignment residual JSON at launch."
    ),
)
B1_NAVIGATION_ARTIFACT_GATE = RouteGate(
    id="b1_navigation_artifact",
    label="B1 verified navigation smoke artifact available",
    kind="request_field",
    help_text="Optional: leave empty to generate a B1 / Map 12 navigation smoke JSON at launch.",
)


def list_worlds(*, include_hidden: bool = False) -> tuple[dict[str, Any], ...]:
    """Return searchable world/scene metadata for the console rail."""

    rows = []
    for world in WORLD_SPECS.values():
        if world.availability == "hidden" and not include_hidden:
            continue
        rows.append(
            {
                "id": world.id,
                "label": world.label,
                "surface_id": world.surface_id,
                "available_backends": list(world.available_backends),
                "scene_source": world.scene_source,
                "tags": list(world.tags),
                "default_backend": world.default_backend,
                "resource_kind": world.resource_kind,
                "availability": world.availability,
                "preview_assets": _preview_assets_payload(world.preview_assets),
                "sampler_metadata": dict(world.sampler_metadata or {}),
            }
        )
    return tuple(rows)


def list_evidence_lanes() -> tuple[dict[str, str], ...]:
    """Return the full operator-visible household evidence-lane list."""

    return tuple(
        {
            "id": lane,
            "label": lane,
        }
        for lane in cleanup_evidence_lane_names()
    )


def selection_task_selector(intent_id: str) -> str:
    """Return the task segment used by canonical console selection ids."""

    return intent_id if intent_id in {"cleanup", "map-build"} else "open-task"


def _preview_assets_payload(items: tuple[tuple[str, str], ...]) -> dict[str, dict[str, str]]:
    return {name: {"path": path, "href": path} for name, path in items}


def list_console_combinations(
    *, include_disabled: bool = True
) -> tuple[ConsoleLaunchSelection, ...]:
    """Return the catalog-backed console support matrix."""

    rows = _enabled_combinations()
    disabled = _disabled_combinations()
    if include_disabled:
        return (*rows, *disabled)
    return rows


def get_selection(selection_id: str) -> ConsoleLaunchSelection:
    for selection in list_console_combinations(include_disabled=True):
        if selection.id == selection_id:
            return selection
    raise KeyError(selection_id)


def validate_supported_routes_against_catalog() -> None:
    """Fail if supported console combinations drift away from launch catalog."""

    for selection in list_console_combinations(include_disabled=False):
        try:
            resolve_surface_launch(selection.base_args())
        except LaunchError as exc:  # pragma: no cover - assertion context
            raise AssertionError(f"invalid console selection {selection.id}: {exc}") from exc


def _common_gates() -> tuple[RouteGate, ...]:
    return (PROVIDER_KEY_GATE, MCP_PORT_FREE_GATE)


def _enabled_combinations() -> tuple[ConsoleLaunchSelection, ...]:
    common_gates = _common_gates()
    return (
        *_molmospaces_enabled_combinations(),
        *_lane_selections(
            "agibot-g2/map-12",
            "agibot-gdk",
            "map-build",
            "openai-agents-sdk",
            "codex-router-responses",
            evidence_lanes=(CAMERA_GROUNDED_LABELS_LANE,),
            camera_labeler=AGIBOT_CAMERA_LABELER,
            scenario_setup=ENVIRONMENT_SETUP_BASELINE,
            gates=(
                *common_gates,
                AGIBOT_CONTEXT_GATE,
                AGIBOT_LOCALIZATION_GATE,
                AGIBOT_ENABLEMENT_GATE,
                AGIBOT_ESTOP_GATE,
            ),
            required_overrides=("context_json",),
            default_overrides=(
                "policy=openai_agents_agibot_map_build",
                "visual_grounding_timeout_s=20",
            ),
            emergency_stop_required=True,
        ),
        *_lane_selections(
            "b1-map12",
            "isaaclab",
            "open-ended",
            "openai-agents-sdk",
            "codex-router-responses",
            evidence_lanes=ISAAC_SUPPORTED_EVIDENCE_LANES,
            camera_labeler=SIMULATION_CAMERA_LABELER,
            scenario_setup=ENVIRONMENT_SETUP_BASELINE,
            gates=(
                *common_gates,
                B1_ALIGNMENT_ARTIFACT_GATE,
                B1_NAVIGATION_ARTIFACT_GATE,
            ),
            required_overrides=B1_ROBOT_PROOF_REQUIRED_OVERRIDES,
            default_overrides=("seed=7",),
            supports_operator_steer=True,
            supports_paused_handoff_resume=True,
            supports_relative_navigation_control=True,
        ),
    )


def _molmospaces_enabled_combinations() -> tuple[ConsoleLaunchSelection, ...]:
    rows: list[ConsoleLaunchSelection] = []
    common_gates = _common_gates()
    for world_id in MOLMOSPACES_CONSOLE_WORLD_IDS:
        rows.extend(
            _lane_selections(
                world_id,
                "mujoco",
                "cleanup",
                "openai-agents-sdk",
                "codex-router-responses",
                gates=common_gates,
                default_overrides=("seed=7",),
                supports_operator_steer=True,
                supports_paused_handoff_resume=True,
                supports_relative_navigation_control=True,
            )
        )
        rows.extend(
            _lane_selections(
                world_id,
                "mujoco",
                "map-build",
                "openai-agents-sdk",
                "codex-router-responses",
                scenario_setup=ENVIRONMENT_SETUP_BASELINE,
                gates=common_gates,
                default_overrides=("seed=7",),
            )
        )
        rows.extend(
            _lane_selections(
                world_id,
                "mujoco",
                "open-ended",
                "openai-agents-sdk",
                "codex-router-responses",
                scenario_setup=ENVIRONMENT_SETUP_BASELINE,
                gates=common_gates,
                default_overrides=("seed=7",),
                supports_operator_steer=True,
                supports_paused_handoff_resume=True,
                supports_relative_navigation_control=True,
            )
        )
        rows.extend(
            _lane_selections(
                world_id,
                "mujoco",
                "map-build",
                "direct-runner",
                None,
                scenario_setup=ENVIRONMENT_SETUP_BASELINE,
                gates=(MCP_PORT_FREE_GATE,),
                default_overrides=("seed=7",),
            )
        )
    return tuple(rows)


def _disabled_combinations() -> tuple[ConsoleLaunchSelection, ...]:
    return (
        _selection(
            "agibot-g2/map-12",
            "agibot-gdk",
            "cleanup",
            "openai-agents-sdk",
            "codex-router-responses",
            evidence_lane="camera-grounded-labels",
            enabled=False,
            unsupported_reason=(
                "Physical manipulation is not active. Use Agibot G2 Map Build for map evidence."
            ),
            supports_prompt=False,
            emergency_stop_required=True,
        ),
    )


def _selection(
    world_id: str,
    backend_id: str,
    intent_id: str,
    agent_engine_id: str,
    provider_profile: str | None,
    *,
    evidence_lane: str = "world-public-labels",
    scenario_setup: str | None = None,
    enabled: bool = True,
    unsupported_reason: str = "",
    required_overrides: tuple[str, ...] = (),
    default_overrides: tuple[str, ...] = (),
    gates: tuple[RouteGate, ...] = (),
    supports_prompt: bool = True,
    supports_operator_steer: bool = False,
    supports_paused_handoff_resume: bool = False,
    supports_relative_navigation_control: bool = False,
    emergency_stop_required: bool = False,
) -> ConsoleLaunchSelection:
    setup = scenario_setup or (
        ENVIRONMENT_SETUP_RELOCATE_CLEANUP_RELATED_OBJECTS
        if intent_id == "cleanup"
        else ENVIRONMENT_SETUP_BASELINE
    )
    preset_id = intent_id if intent_id in {"cleanup", "map-build"} else ""
    return ConsoleLaunchSelection(
        world_id=world_id,
        backend_id=backend_id,
        intent_id=intent_id,
        agent_engine_id=agent_engine_id,
        provider_profile=provider_profile,
        evidence_lane=evidence_lane,
        scenario_setup=setup,
        preset_id=preset_id,
        enabled=enabled,
        unsupported_reason=unsupported_reason,
        required_overrides=required_overrides,
        default_overrides=default_overrides,
        gates=gates,
        supports_prompt=supports_prompt,
        supports_operator_steer=supports_operator_steer,
        supports_paused_handoff_resume=supports_paused_handoff_resume,
        supports_relative_navigation_control=supports_relative_navigation_control,
        emergency_stop_required=emergency_stop_required,
    )


def _lane_selections(
    world_id: str,
    backend_id: str,
    intent_id: str,
    agent_engine_id: str,
    provider_profile: str | None,
    *,
    evidence_lanes: tuple[str, ...] = REAL_EVIDENCE_LANES,
    camera_labeler: str = SIMULATION_CAMERA_LABELER,
    scenario_setup: str | None = None,
    enabled: bool = True,
    unsupported_reason: str = "",
    required_overrides: tuple[str, ...] = (),
    default_overrides: tuple[str, ...] = (),
    gates: tuple[RouteGate, ...] = (),
    supports_prompt: bool = True,
    supports_operator_steer: bool = False,
    supports_paused_handoff_resume: bool = False,
    supports_relative_navigation_control: bool = False,
    emergency_stop_required: bool = False,
) -> tuple[ConsoleLaunchSelection, ...]:
    rows: list[ConsoleLaunchSelection] = []
    for evidence_lane in evidence_lanes:
        lane_default_overrides = default_overrides
        if evidence_lane == CAMERA_GROUNDED_LABELS_LANE:
            lane_default_overrides = (
                *lane_default_overrides,
                f"camera_labeler={camera_labeler}",
            )
        rows.append(
            _selection(
                world_id,
                backend_id,
                intent_id,
                agent_engine_id,
                provider_profile,
                evidence_lane=evidence_lane,
                scenario_setup=scenario_setup,
                enabled=enabled,
                unsupported_reason=unsupported_reason,
                required_overrides=required_overrides,
                default_overrides=lane_default_overrides,
                gates=gates,
                supports_prompt=supports_prompt,
                supports_operator_steer=supports_operator_steer,
                supports_paused_handoff_resume=supports_paused_handoff_resume,
                supports_relative_navigation_control=supports_relative_navigation_control,
                emergency_stop_required=emergency_stop_required,
            )
        )
    return tuple(rows)


def _intent_option(intent_id: str) -> dict[str, str]:
    spec = TASK_INTENT_SPECS.get(intent_id)
    if spec is None:
        return {
            "id": intent_id,
            "label": _intent_label(intent_id),
            "prompt_id": "",
            "checker_id": "",
            "goal_scope": "",
            "evaluation_policy": "",
            "done_readiness_policy": "",
            "checker_policy": "",
        }
    return {
        "id": intent_id,
        "label": _intent_label(intent_id),
        "prompt_id": spec.prompt_id,
        "checker_id": spec.checker_id,
        "goal_scope": spec.default_goal_scope,
        "evaluation_policy": spec.evaluation_policy,
        "done_readiness_policy": spec.done_readiness_policy,
        "checker_policy": spec.checker_policy,
    }


def _preset_option(preset_id: str) -> dict[str, str]:
    return {
        "id": preset_id,
        "label": _intent_label(preset_id),
        "intent_id": preset_id,
    }


def _intent_label(intent_id: str) -> str:
    return {
        "cleanup": "Cleanup",
        "open-ended": "Open-ended",
        "map-build": "Map build",
    }.get(intent_id, intent_id.replace("-", " ").title())
