from __future__ import annotations

import json
import re
from pathlib import Path

from roboclaws.launch.worlds import MOLMOSPACES_CONSOLE_WORLD_IDS, WORLD_SPECS
from roboclaws.operator_console.server import ConsoleRequestHandler
from roboclaws.worlds.molmospaces.catalog import CURRENT_CURATED_INDICES

STATIC_ROOT = Path(__file__).resolve().parents[3] / "roboclaws" / "operator_console" / "static"
REPO_ROOT = Path(__file__).resolve().parents[3]
BEHAVIOR_MODULES = (
    "app.js",
    "background-tasks.js",
    "http-dom.js",
    "launch.js",
    "manual-control.js",
    "run-session.js",
    "state.js",
    "visual-workspace.js",
    "workflow-model.js",
    "workflow-view.js",
)


def _static_javascript() -> str:
    return "\n".join(
        (STATIC_ROOT / module_name).read_text(encoding="utf-8") for module_name in BEHAVIOR_MODULES
    )


def test_static_app_is_native_module_composition_entrypoint() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    app = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert '<script type="module" src="/app.js?v=modules-20260731"></script>' in html
    assert 180 <= len(app.splitlines()) <= 250
    assert set(path.name for path in STATIC_ROOT.glob("*.js")) == set(BEHAVIOR_MODULES)
    assert _static_javascript().count("export const state = {") == 1
    assert "const state = {" not in app

    for module_name in BEHAVIOR_MODULES[1:]:
        assert f'from "./{module_name}"' in _static_javascript()

    for module_name in BEHAVIOR_MODULES:
        source = (STATIC_ROOT / module_name).read_text(encoding="utf-8")
        for imported_name in re.findall(r'from "\./([^"?]+\.js)"', source):
            assert (STATIC_ROOT / imported_name).is_file()


def test_static_asset_allowlist_includes_native_modules() -> None:
    handler = ConsoleRequestHandler.__new__(ConsoleRequestHandler)
    handler.static_root = STATIC_ROOT

    assert handler._is_static_asset("/app.js")
    assert handler._is_static_asset("/state.js")
    assert handler._is_static_asset("/workflow-view.js")
    assert not handler._is_static_asset("/.split-app.mjs")
    assert not handler._is_static_asset("/nested/state.js")
    assert not handler._is_static_asset("/missing.js")


def test_static_app_references_existing_dom_ids() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    app = _static_javascript()

    declared_ids = set(re.findall(r'id="([^"]+)"', html))
    referenced_ids = set(re.findall(r'getElementById\("([^"`$]+)"\)', app))

    assert referenced_ids - declared_ids == set()


def test_static_app_references_existing_els_keys() -> None:
    app = _static_javascript()

    els_match = re.search(r"const els = \{(?P<body>.*?)\n\};", app, re.DOTALL)
    assert els_match is not None
    declared_keys = set(
        re.findall(r"^\s*([A-Za-z][A-Za-z0-9]*):", els_match.group("body"), re.MULTILINE)
    )
    referenced_keys = set(re.findall(r"\bels\.([A-Za-z][A-Za-z0-9]*)\b", app))

    assert referenced_keys - declared_keys == set()


def test_static_app_keeps_deleted_operator_console_widgets_deleted() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    app = _static_javascript()
    css = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    for snippet in (
        'id="messup-button"',
        'id="messup-status"',
        'id="tasks-panel"',
        'data-view="tasks"',
        'data-panel="runtime_map"',
    ):
        assert snippet not in html

    for snippet in (
        "previewMessup",
        "/api/messup-preview",
        "schedulePromptPreviewRefresh",
        "promptPreviewTimer",
        "backgroundTaskViewAvailable",
        "taskActionsHtml",
        "copy_command",
        'setImageSlot(\n    "runtime_map"',
        'runtime_map: "Map"',
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
    app = _static_javascript()

    assert 'gate.id === "context_json" && Boolean(els.contextInput.value.trim())' not in app


def test_static_app_renders_scene_preview_assets() -> None:
    app = _static_javascript()
    preview_dir = STATIC_ROOT / "previews"

    _assert_scene_preview_app_wiring(app)
    molmospaces_preview_files = _assert_molmospaces_preview_files(preview_dir)
    _assert_optional_world_specs_do_not_publish_private_previews()
    _assert_molmospaces_preview_metadata(preview_dir)
    _assert_b1_preview_metadata(preview_dir)
    assert not any(name.startswith("molmospaces-val_6-") for name in molmospaces_preview_files)
    assert not any(name.startswith("molmospaces-val_8-") for name in molmospaces_preview_files)
    assert not (preview_dir / "ai2thor-floorplan201-topdown.png").exists()


def _assert_scene_preview_app_wiring(app: str) -> None:
    assert "renderSelectedScenePreview" in app
    assert "renderSelectedScenePreview(route);" in app
    assert "route.preview_assets" in app
    assert 'setImageSlot(\n    "topdown",\n    previews.topdown' in app
    assert 'data-view-role="${escapeHtml(visualRole)}"' in app
    assert 'data-artifact-source-family="${escapeHtml(sourceFamily)}"' in app
    assert "No top-down scene preview is available." in app
    assert "state.activeRunId" in app
    assert "Perception output will appear after a camera-grounded run starts." in app


def _assert_molmospaces_preview_files(preview_dir: Path) -> list[str]:
    expected_preview_files = sorted(
        {
            *(
                f"molmospaces-val_{scene_index}-{view_name}.png"
                for scene_index in CURRENT_CURATED_INDICES
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
                for scene_index in CURRENT_CURATED_INDICES
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


def _assert_optional_world_specs_do_not_publish_private_previews() -> None:
    assert WORLD_SPECS["b1-map12"].preview_assets == ()
    assert WORLD_SPECS["agibot-g2/map-12"].preview_assets == ()


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


def test_static_app_announces_run_state_via_live_region() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")

    # The event strip is the live region operators monitor peripherally; it
    # must announce terminal state and safety blockers without focus.
    assert 'id="event-log"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
