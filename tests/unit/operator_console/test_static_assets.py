from __future__ import annotations

import json
import re
from pathlib import Path

from roboclaws.launch.worlds import (
    MOLMOSPACES_CONSOLE_WORLD_IDS,
    MOLMOSPACES_LAUNCH_ALIAS_SCENE_INDICES,
    WORLD_SPECS,
)

STATIC_ROOT = Path(__file__).resolve().parents[3] / "roboclaws" / "operator_console" / "static"
REPO_ROOT = Path(__file__).resolve().parents[3]


def test_static_app_references_existing_dom_ids() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    app = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    declared_ids = set(re.findall(r'id="([^"]+)"', html))
    referenced_ids = set(re.findall(r'getElementById\("([^"`$]+)"\)', app))

    assert referenced_ids - declared_ids == set()


def test_static_app_references_existing_els_keys() -> None:
    app = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    els_match = re.search(r"const els = \{(?P<body>.*?)\n\};", app, re.DOTALL)
    assert els_match is not None
    declared_keys = set(
        re.findall(r"^\s*([A-Za-z][A-Za-z0-9]*):", els_match.group("body"), re.MULTILINE)
    )
    referenced_keys = set(re.findall(r"\bels\.([A-Za-z][A-Za-z0-9]*)\b", app))

    assert referenced_keys - declared_keys == set()


def test_static_app_has_route_specific_field_groups() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    app = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    setup_html = html.split('<aside class="setup-panel">', 1)[1].split("</aside>", 1)[0]
    state_rail_html = html.split('<aside class="state-rail">', 1)[1].split("</aside>", 1)[0]

    for snippet in (
        'id="isaac-fields"',
        'id="provider-profile-input"',
        'id="agibot-gate-fields"',
        'id="real-movement-gate"',
        'id="prompt-preview-button"',
        'id="background-tasks-button"',
        'data-operator-mode="steer"',
        'data-operator-mode="resume"',
    ):
        assert snippet in html

    for snippet in (
        "renderRouteFields",
        "field_groups",
        "selectedProviderRoute",
        "renderScenarioSetup",
        "refreshPromptPreview",
        "/api/prompt-preview",
        "renderBackgroundTaskButton",
        "background_blockers",
        "TASK RUNNING",
        "/api/runtime/tasks",
    ):
        assert snippet in app

    assert "Operator Input" in setup_html
    assert "Operator Input" not in state_rail_html


def test_static_app_keeps_deleted_operator_console_widgets_deleted() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    app = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    css = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    for snippet in (
        'id="messup-button"',
        'id="messup-status"',
        'id="tasks-panel"',
        'id="background-task-list"',
        'data-view="tasks"',
        'data-panel="runtime_map"',
    ):
        assert snippet not in html

    for snippet in (
        "previewMessup",
        "/api/messup-preview",
        "schedulePromptPreviewRefresh",
        "promptPreviewTimer",
        "renderBackgroundTasks",
        "backgroundTaskViewAvailable",
        "taskActionsHtml",
        "runTaskAction",
        "copy_command",
        "api_post",
        'setImageSlot(\n    "runtime_map"',
        'runtime_map: "Metric Map"',
    ):
        assert snippet not in app

    for snippet in (
        ".tasks-panel",
        ".task-row",
        ".mode-tasks",
        '.mode-overview [data-panel="runtime_map"]',
        ".messup-actions",
    ):
        assert snippet not in css


def test_static_app_does_not_short_circuit_context_json_readiness() -> None:
    app = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'gate.id === "context_json" && Boolean(els.contextInput.value.trim())' not in app


def test_static_app_renders_scene_preview_assets() -> None:
    app = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    preview_dir = STATIC_ROOT / "previews"

    _assert_scene_preview_app_wiring(app)
    molmospaces_preview_files = _assert_molmospaces_preview_files(preview_dir)
    _assert_b1_world_spec_has_four_preview_assets()
    _assert_agibot_map12_world_spec_reuses_safe_b1_review_assets()
    _assert_molmospaces_preview_metadata(preview_dir)
    _assert_b1_preview_metadata(preview_dir)
    assert not any(name.startswith("molmospaces-val_6-") for name in molmospaces_preview_files)
    assert not any(name.startswith("molmospaces-val_8-") for name in molmospaces_preview_files)
    assert not (preview_dir / "ai2thor-floorplan201-topdown.png").exists()


def _assert_scene_preview_app_wiring(app: str) -> None:
    assert "renderSelectedScenePreview" in app
    assert "renderSelectedScenePreview(route);" in app
    assert "route.preview_assets" in app
    assert 'setImageSlot("topdown", previews.topdown' in app
    assert 'data-view-role="${escapeHtml(visualRole)}"' in app
    assert 'data-artifact-source-family="${escapeHtml(sourceFamily)}"' in app
    assert "No Top2Down scene preview is available." in app
    assert "state.activeRunId" in app
    assert "Grounding will appear after a camera-grounded run starts." in app


def _assert_molmospaces_preview_files(preview_dir: Path) -> list[str]:
    expected_preview_files = sorted(
        {
            *(
                f"molmospaces-val_{scene_index}-{view_name}.png"
                for scene_index in MOLMOSPACES_LAUNCH_ALIAS_SCENE_INDICES
                for view_name in ("chase", "fpv", "map", "topdown")
            ),
            *(
                Path(path).name
                for world_id in MOLMOSPACES_CONSOLE_WORLD_IDS
                for _view_name, path in WORLD_SPECS[world_id].preview_assets
                if path.startswith("/previews/")
            ),
        }
    )
    molmospaces_preview_files = sorted(
        path.name
        for path in preview_dir.glob("molmospaces-*.png")
        if path.name in expected_preview_files
    )
    assert molmospaces_preview_files == expected_preview_files
    return molmospaces_preview_files


def _assert_molmospaces_preview_metadata(preview_dir: Path) -> None:
    expected_metadata_files = sorted(
        {
            *(
                f"molmospaces-val_{scene_index}-preview.json"
                for scene_index in MOLMOSPACES_LAUNCH_ALIAS_SCENE_INDICES
            ),
            *(
                f"{Path(WORLD_SPECS[world_id].preview_assets[0][1]).name.rsplit('-', 1)[0]}"
                "-preview.json"
                for world_id in MOLMOSPACES_CONSOLE_WORLD_IDS
            ),
        }
    )
    metadata_files = sorted(
        path.name
        for path in preview_dir.glob("molmospaces-*-preview.json")
        if path.name in expected_metadata_files
    )
    assert metadata_files == expected_metadata_files

    for world_id in MOLMOSPACES_CONSOLE_WORLD_IDS:
        preview_by_view = dict(WORLD_SPECS[world_id].preview_assets)
        assert set(preview_by_view) == {"fpv", "map", "chase", "topdown"}
        _assert_preview_png_files_exist(preview_dir, preview_by_view)
        scene_slug = Path(preview_by_view["fpv"]).name.rsplit("-", 1)[0]
        metadata_path = preview_dir / f"{scene_slug}-preview.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert metadata["world_id"] == world_id
        assert metadata["views"]["fpv"]["view"] == "raw_fpv"
        assert metadata["views"]["map"]["view"] == "base_metric_map_preview"
        assert metadata["views"]["map"]["visual_role"] == "base_metric_map_preview"
        assert metadata["views"]["map"]["artifact_source_family"] == "base_metric_map_bundle"
        assert metadata["views"]["map"]["provenance"] == "map_bundle_preview_png"
        assert metadata["views"]["chase"]["view"] == "chase_camera"
        assert metadata["views"]["chase"]["image_diagnostics"]["visual_status"] == "reviewable"
        assert metadata["views"]["topdown"]["view"] == "topdown_scene_render"
        assert metadata["views"]["topdown"]["visual_role"] == "topdown_scene_render"
        assert metadata["views"]["topdown"]["artifact_source_family"] == "scene_camera_render"
        assert "semantic_projection" not in metadata["views"]["map"]
        assert "scene_alignment" not in metadata["views"]["map"]
        assert metadata["views"]["fpv"]["path"] != metadata["views"]["topdown"]["path"]
        assert metadata["views"]["chase"]["path"] != metadata["views"]["fpv"]["path"]
        assert metadata["views"]["chase"]["path"] != metadata["views"]["topdown"]["path"]


def _assert_preview_png_files_exist(preview_dir: Path, preview_by_view: dict[str, str]) -> None:
    for view_name, asset_path in preview_by_view.items():
        if asset_path.startswith("/previews/"):
            path = preview_dir / Path(asset_path).name
        elif asset_path.startswith("/asset-previews/maps/"):
            path = REPO_ROOT / "assets" / "maps" / asset_path.removeprefix("/asset-previews/maps/")
        else:
            raise AssertionError(f"unsupported preview asset path: {asset_path}")
        assert path.is_file(), view_name
        assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def _assert_b1_world_spec_has_four_preview_assets() -> None:
    b1_preview_assets = dict(WORLD_SPECS["b1-map12"].preview_assets)
    assert set(b1_preview_assets) == {"fpv", "map", "chase", "topdown"}


def _assert_agibot_map12_world_spec_reuses_safe_b1_review_assets() -> None:
    agibot_preview_assets = dict(WORLD_SPECS["agibot-g2/map-12"].preview_assets)
    assert agibot_preview_assets == {
        "map": "/previews/b1-map12-map.png",
        "topdown": "/previews/b1-map12-topdown.png",
    }


def _assert_b1_preview_metadata(preview_dir: Path) -> None:
    for view_name in ("fpv", "map", "chase", "topdown"):
        path = preview_dir / f"b1-map12-{view_name}.png"
        assert path.is_file()
        assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    b1_metadata = json.loads((preview_dir / "b1-map12-preview.json").read_text(encoding="utf-8"))
    assert b1_metadata["world_id"] == "b1-map12"
    assert b1_metadata["backend"] == "isaaclab"
    assert b1_metadata["renderer"] == ("b1_map12_static_gaussian_topdown_with_isaac_runtime_camera")
    assert b1_metadata["scene_usd_path"] == (
        "data/robot-data-lab/scene-engine/data/2rd_floor_seperated/storey_1/scene_gs.usda"
    )
    assert b1_metadata["views"]["fpv"]["view"] == "raw_fpv"
    assert b1_metadata["views"]["chase"]["view"] == "chase_camera"
    assert b1_metadata["views"]["fpv"]["waypoint_id"] == "b1_aligned_plastic_bottle_table_1"
    assert b1_metadata["views"]["chase"]["waypoint_id"] == "b1_aligned_plastic_bottle_table_1"
    assert "source_artifact_sha256" in b1_metadata["camera_preview_artifact"]
    assert "path" not in b1_metadata["camera_preview_artifact"]
    assert b1_metadata["views"]["map"]["view"] == "base_metric_map_preview"
    assert b1_metadata["views"]["map"]["artifact_source_family"] == "base_metric_map_bundle"
    assert b1_metadata["views"]["topdown"]["view"] == "topdown_scene_render"
    assert b1_metadata["views"]["topdown"]["artifact_source_family"] == "scene_camera_render"
    assert b1_metadata["views"]["topdown"]["provenance"] == (
        "b1_scene_gaussian_topdown_crop_z1p8_png"
    )
    assert b1_metadata["views"]["topdown"]["alignment_status"] == (
        "height_cropped_gaussian_scene_topdown"
    )
    assert "diagnostic_views" not in b1_metadata


def test_static_app_exposes_explicit_intent_selector_and_interpretation() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    app = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    css = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert 'id="intent-input"' in html
    assert 'id="intent-preview"' in html
    assert "selectedIntent" in app
    assert "selectedIntentForRoute" in app
    assert 'const DEFAULT_UI_INTENT = "open-ended";' in app
    assert "preferredDefaultCombination" in app
    assert "item.enabled && item.intent_id === DEFAULT_UI_INTENT" in app
    assert "state.selectedIntent = els.intentInput.value;" in app
    assert "state.selectedIntent = selectedIntent();" not in app
    assert "syncAxesFromRoute" in app
    assert "currentSelectValue" in app
    assert "currentSelectValue(\n          els.intentInput" in app
    assert "const scopedCombos = axisMatches.length ? axisMatches : combos;" in app
    assert "launchInterpretation" in app
    assert "route.intent_options" in app
    assert "intent_id: selectedIntent()" in app
    assert "world_id: route.world_id" in app
    assert "backend_id: route.backend_id" in app
    assert "agent_engine_id: route.agent_engine_id" in app
    assert "scenario_setup: selectedScenarioSetup()" in app
    assert "intent=${selected}" in app
    assert '"open-ended": "Open-ended"' in app
    assert "Goal scope" in app
    assert "Checker" in app
    assert "Evaluation" in app
    assert "prompt-scoped" in app
    assert "checker_id" in app
    assert ".intent-preview" in css


def test_static_app_uses_overview_workspace_and_outputs_copy() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    app = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    css = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    _assert_overview_outputs_html(html)
    _assert_overview_outputs_app(app)
    _assert_overview_outputs_css(css)


def _assert_overview_outputs_html(html: str) -> None:
    assert 'data-view="overview"' in html
    assert 'data-view="outputs"' in html
    assert 'data-view="artifacts"' not in html
    assert 'id="outputs-panel"' in html
    assert 'data-panel="blank-chase"' not in html
    assert ">Outputs<" in html
    assert "Artifacts" not in html
    assert ">Metric Map<" in html
    assert ">Base Map<" not in html
    assert ">Runtime Map<" not in html
    assert ">Semantic Map<" not in html
    assert ">Top2Down<" in html
    assert ">Top-down<" not in html
    assert 'data-panel-title="fpv"' in html
    assert 'data-panel-title="chase"' in html
    assert 'data-panel="grounding"' in html
    assert 'data-panel="grounding"' not in html.split('class="view-grid mode-overview"', 1)[0]
    assert "topdown-frame" in html
    assert "prompt-preview-20260616" in html


def _assert_overview_outputs_app(app: str) -> None:
    assert "Top-down Scene View" not in app
    assert "FPV(+Grounding)" in app
    assert 'display_source === "visual_grounding_overlay"' in app
    assert 'activeView: "overview"' in app
    assert "visiblePanelsForView" in app
    assert "routeViewModes" in app
    assert "routeHasOverviewChase" not in app
    assert 'resource_kind !== "physical_robot"' not in app
    overview_body = app.split('if (view === "overview") {', 1)[1].split("\n  }", 1)[0]
    assert 'new Set(["fpv", "map", "chase", "topdown"])' in overview_body
    assert '"outputs"' not in overview_body
    assert '"tasks"' not in overview_body
    assert '"grounding"' not in overview_body
    assert '"runtime_map"' not in overview_body
    assert "Missing run chase artifact" in app
    assert "Missing Metric Map artifact" in app
    assert "sourceAssets.runtime_map || sourceAssets.map" in app
    assert 'routeHasView(route, "chase") ? previews.chase : null' in app


def _assert_overview_outputs_css(css: str) -> None:
    assert ".mode-overview" in css
    assert '"fpv map"' in css
    assert '"chase topdown"' in css
    assert "object-position: center center" in css
    assert ".image-panel > .image-frame" in css
    assert "aspect-ratio: auto" in css
    assert '.mode-overview [data-panel="runtime_map"]' not in css
    assert '.mode-overview [data-panel="chase"]' in css
    assert '.mode-overview [data-panel="blank-chase"]' not in css
    assert ".blank-panel" not in css
    assert "[hidden]" in css
    assert "display: none !important" in css
    assert ".top-run-bar.run-active #run-title" in css
    assert "font-size: 14px" in css
    assert "text-overflow: ellipsis" in css


def test_static_app_announces_run_state_via_live_region() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")

    # The event strip is the live region operators monitor peripherally; it
    # must announce terminal state and safety blockers without focus.
    assert 'id="event-log"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html


def test_static_app_renders_stop_result_before_detaching_run() -> None:
    app = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    detach_body = app.split("function detachRunAfterStop(result) {", 1)[1].split(
        "\n}\n\nasync function toggleRawEvidence",
        1,
    )[0]

    assert "state.activeState = result;" in detach_body
    assert "renderRunState(result);" in detach_body
    assert detach_body.index("renderRunState(result);") < detach_body.index(
        "state.activeRunId = null;"
    )
    assert app.count("const checkerStatus = payload.checker_status || {};") >= 2


def test_static_app_uses_fixed_run_evidence_panel() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    app = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    css = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert 'href="/styles.css?v=' in html
    assert 'src="/app.js?v=' in html
    assert "refreshRawEvidence()" in app
    assert "forceStickToBottom: true" in app
    assert "shouldStickToBottom" in app
    assert "raw-evidence-open" in app
    assert 'id="state-rail-resizer"' not in html
    assert 'id="evidence-strip-resizer"' not in html
    assert "STATE_RAIL_WIDTH_KEY" not in app
    assert "EVIDENCE_STRIP_HEIGHT_KEY" not in app
    assert "setPointerCapture" not in app
    assert "--state-rail-width" not in css
    assert "--evidence-strip-height" not in css
    assert ".state-rail-splitter" not in css
    assert ".event-strip-splitter" not in css
    assert ".raw-evidence" in css
    assert "overflow: auto" in css
    assert "white-space: pre" in css


def test_static_app_routes_destructive_actions_through_styled_dialog() -> None:
    app = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    css = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    # Stop and Emergency Stop must use the themed <dialog>, not native
    # window.confirm, and carry the contract CTA labels.
    assert "window.confirm" not in app
    assert "confirmAction(" in app
    assert "Trigger Emergency Stop" in app
    assert "Stop Run" in app

    # Run title reaches the 28px display role only once a run is active.
    assert ".top-run-bar.run-active #run-title" in css
    assert "font-variant-numeric: tabular-nums" in css


def test_static_app_keeps_long_run_header_within_fixed_top_bar() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    app = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    css = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")
    desktop_controls = css.split(".global-controls {", 1)[1].split("\n}", 1)[0]
    responsive_controls = (
        css.split("@media (max-width: 1360px)", 1)[1]
        .split(
            ".global-controls {",
            1,
        )[1]
        .split("\n  }", 1)[0]
    )

    assert 'href="/styles.css?v=prompt-preview-20260616"' in html
    assert 'src="/app.js?v=prompt-preview-20260616"' in html
    assert ".run-meta {\n  display: flex;" in css
    assert "flex-wrap: nowrap;" in css
    assert ".run-meta > *" in css
    assert "#run-title {\n  flex: 1 1 auto;" in css
    assert "overflow: hidden" in css
    assert ".global-controls {\n  display: flex;" in css
    assert "flex: 0 0 auto;" in desktop_controls
    assert "flex-wrap: nowrap;" in desktop_controls
    assert "min-width: max-content;" in desktop_controls
    assert ".global-controls button" in css
    assert "white-space: nowrap;" in css
    assert "@media (max-width: 1360px)" in css
    assert "justify-content: flex-start;" in responsive_controls
    assert "flex-wrap: wrap;" in responsive_controls
    assert "#run-title {\n    flex-basis: 100%;" in css
    assert "function compactRunPart(part)" in app
    assert (
        "return `${fullTimestamp[2]}${fullTimestamp[3]}-${fullTimestamp[4]}${fullTimestamp[5]}`"
    ) in app
    assert (
        "return `${shortTimestamp[1]}${shortTimestamp[2]}_${shortTimestamp[3]}${shortTimestamp[4]}`"
    ) in app
    assert '"$2$3-$4$5$7"' not in app


def test_static_app_wires_manual_relative_navigation_controls() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    app = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    css = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert 'id="manual-control-panel"' in html
    assert 'id="manual-control-status"' in html
    for action in ("forward", "back", "left", "right", "turn-left", "turn-right", "observe"):
        assert f'data-control-action="{action}"' in html
    assert "MANUAL_CONTROL_STEP_M = 0.25" in app
    assert "MANUAL_CONTROL_TURN_DEG = 15" in app
    assert 'action: "navigate_to_relative_pose"' in app
    assert 'return { action: "observe" }' in app
    assert "/control" in app
    assert "supports_relative_navigation_control" in app
    assert "relative_navigation_control_available" in app
    assert "operator_handoff_paused" in app
    assert "supports_paused_handoff_resume" in app
    assert "operator moves are recorded as assisted interventions".lower() in app.lower()
    assert ".manual-control-panel" in css
    assert ".manual-control-grid" in css
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in css


def test_static_app_opens_images_in_large_dialog() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    app = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    css = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert 'id="image-dialog"' in html
    assert 'id="image-dialog-img"' in html
    assert "image-preview-button" in app
    assert "openImageDialog" in app
    assert "showModal()" in app
    assert "data-image-src" in app
    assert ".image-dialog" in css
    assert ".image-dialog-frame img" in css
    assert "max-height: calc(100vh - 168px)" in css
    assert "transform: scale(1.02)" in css
