# ruff: noqa: E402, F403, F405, F821
from tests.support.cleanup_checker_robot_views import *


def _write_isaac_scene_index(
    base: Path,
    scene_bindings: dict[str, object],
    *,
    artifact_scene_bindings: dict[str, object] | None = None,
    segmentation: dict[str, object] | None = None,
    object_prim_path: str = "/World/Objects/mug_01",
    extra_object_index: dict[str, object] | None = None,
) -> None:
    if artifact_scene_bindings is None:
        artifact_scene_bindings = scene_bindings
    if segmentation is None:
        segmentation = {
            "status": "blocked_capability",
            "agent_facing": False,
            "no_simulator_label_fallback": True,
        }
    object_index = {"mug_01": {"usd_prim_path": object_prim_path}}
    object_index.update(extra_object_index or {})
    payload = {
        "schema": "isaac_scene_index_artifact_v1",
        "backend": "isaaclab_subprocess",
        "agent_facing": False,
        "private_manifest_exposed_to_agent": False,
        "object_index": object_index,
        "object_index_count": len(object_index),
        "receptacle_index": {
            "sink_01": {"usd_prim_path": "/World/Receptacles/sink_01"},
        },
        "receptacle_index_count": 1,
        "scene_binding_diagnostics": artifact_scene_bindings,
        "segmentation": segmentation,
    }
    (base / "isaac_scene_index.json").write_text(json.dumps(payload), encoding="utf-8")


def _isaac_available_segmentation() -> dict[str, object]:
    bbox = _isaac_segmentation_bbox()
    return {
        "schema": "isaac_segmentation_diagnostics_v1",
        "status": "available",
        "available": True,
        "source": "isaac_lab_camera",
        "capture_method": "isaac_lab_camera_segmentation",
        "requested_data_types": [
            "semantic_segmentation",
            "instance_segmentation_fast",
            "instance_id_segmentation_fast",
        ],
        "output_data_types": ["instance_id_segmentation_fast"],
        "tensor_output_available": True,
        "candidate_overlay_status": "available",
        "candidate_bbox_count": 1,
        "selected_usd_prim_match_count": 1,
        "selected_usd_prim_paths": [
            "/World/Objects/mug_01",
            "/World/Receptacles/sink_01",
        ],
        "selected_candidate_bboxes": [bbox],
        "candidate_bboxes": [bbox],
        "agent_facing": False,
        "no_simulator_label_fallback": True,
    }


def _isaac_semantic_pose_state() -> dict[str, object]:
    event_base = {
        "schema": "isaac_semantic_pose_event_v1",
        "state_source": "backend_json_state",
        "primitive_provenance": "isaac_semantic_pose",
        "rendered_to_usd": False,
        "planner_backed": False,
        "physical_robot": False,
        "object_id": "mug_01",
        "object_usd_prim_path": "/World/Objects/mug_01",
        "receptacle_id": "sink_01",
        "receptacle_usd_prim_path": "/World/Receptacles/sink_01",
    }
    return {
        "schema": "isaac_semantic_pose_state_v1",
        "state_source": "backend_json_state",
        "primitive_provenance": "isaac_semantic_pose",
        "rendered_to_usd": False,
        "planner_backed": False,
        "physical_robot": False,
        "semantic_pose_only": True,
        "object_poses": {
            "mug_01": {
                "state_source": "backend_json_state",
                "rendered_to_usd": False,
                "usd_prim_path": "/World/Objects/mug_01",
                "support_receptacle_id": "sink_01",
                "support_usd_prim_path": "/World/Receptacles/sink_01",
            }
        },
        "articulations": {
            "sink_01": {
                "state_source": "backend_json_state",
                "rendered_to_usd": False,
                "usd_prim_path": "/World/Receptacles/sink_01",
            }
        },
        "transform_events": [
            {
                **event_base,
                "sequence": 1,
                "tool": "pick",
                "state_mutation": "isaac_prim_attach",
            },
            {
                **event_base,
                "sequence": 2,
                "tool": "place",
                "state_mutation": "isaac_prim_transform",
            },
        ],
    }


def _isaac_semantic_pose_state_with_refreshed_robot_views(
    *,
    canonical_camera_control: bool = False,
    mounted_head_camera: bool = False,
    head_camera_equivalent: bool = False,
) -> dict[str, object]:
    state = _isaac_semantic_pose_state()
    state["rendered_to_usd"] = True
    state["semantic_pose_view_capture"] = {
        "schema": "isaac_semantic_pose_robot_view_capture_v1",
        "capture_method": "isaac_lab_camera_rgb_semantic_pose_robot_views",
        "rendered_to_usd": True,
        "scene_usd": "loaded_scene.usda",
        "render_steps": 4,
        "canonical_camera_control": canonical_camera_control,
        "robot_mounted_head_camera": mounted_head_camera,
        "head_camera_prim_path": "/World/robot_0/head_camera" if mounted_head_camera else "",
        "head_camera_equivalent": head_camera_equivalent,
    }
    return state


def _isaac_semantic_pose_trace_events(
    state: dict[str, object],
    *,
    include_provenance: bool = True,
) -> list[dict[str, object]]:
    events = state.get("transform_events") or []
    trace_events: list[dict[str, object]] = []
    if not isinstance(events, list):
        return trace_events
    for event in events:
        if not isinstance(event, dict):
            continue
        response = {
            "ok": True,
            "status": "ok",
            "tool": str(event.get("tool") or ""),
            "object_id": str(event.get("object_id") or ""),
            "receptacle_id": str(event.get("receptacle_id") or ""),
            "state_mutation": str(event.get("state_mutation") or ""),
        }
        if include_provenance:
            response["primitive_provenance"] = "isaac_semantic_pose"
        trace_events.append(_trace_response(str(event.get("tool") or ""), response))
    return trace_events


def _isaac_segmentation_bbox() -> dict[str, object]:
    return {
        "view": "fpv",
        "data_type": "instance_id_segmentation_fast",
        "label_id": 3,
        "label": "/World/Objects/mug_01",
        "usd_prim_path": "/World/Objects/mug_01",
        "bbox_xyxy": [8, 8, 32, 36],
        "pixel_count": 144,
        "image_size": [64, 48],
    }


def _isaac_report_text(
    scene_bindings: dict[str, object],
    *,
    semantic_pose_state: dict[str, object] | None = None,
    include_semantic_pose_rows: bool = True,
) -> str:
    selected_objects = scene_bindings.get("selected_object_bindings") or {}
    selected_receptacles = scene_bindings.get("selected_target_receptacle_bindings") or {}
    rows = [*selected_objects.values(), *selected_receptacles.values()]
    row_text = " ".join(
        f"{row.get('usd_handle', '')} {row.get('usd_prim_path', '')}"
        for row in rows
        if isinstance(row, dict)
    )
    semantic_pose_text = ""
    if semantic_pose_state is not None and include_semantic_pose_rows:
        semantic_pose_text = _isaac_semantic_pose_report_text(semantic_pose_state)
    return (
        "Isaac Runtime Diagnostics Segmentation Scene Index Artifact Rows "
        "Selected USD Binding Rows Selected USD Index Rows "
        "isaac_semantic_pose Semantic Pose State Semantic Pose Events "
        "Rendered to USD Planner backed "
        f"{row_text} {semantic_pose_text}"
    )


def _isaac_semantic_pose_report_text(state: dict[str, object]) -> str:
    values: list[str] = [
        "Object USD",
        "Support USD",
        "USD prim",
        "Mutation",
        "Receptacle USD",
    ]
    object_poses = state.get("object_poses") or {}
    if isinstance(object_poses, dict):
        for object_id, pose in object_poses.items():
            if not isinstance(pose, dict):
                continue
            values.extend(
                [
                    str(object_id),
                    str(pose.get("support_receptacle_id") or ""),
                    str(pose.get("usd_prim_path") or ""),
                    str(pose.get("support_usd_prim_path") or ""),
                ]
            )
    articulations = state.get("articulations") or {}
    if isinstance(articulations, dict):
        for receptacle_id, articulation in articulations.items():
            if not isinstance(articulation, dict):
                continue
            values.extend(
                [
                    str(receptacle_id),
                    str(articulation.get("usd_prim_path") or ""),
                ]
            )
    events = state.get("transform_events") or []
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict):
                continue
            values.extend(
                [
                    str(event.get("tool") or ""),
                    str(event.get("state_mutation") or ""),
                    str(event.get("object_id") or ""),
                    str(event.get("receptacle_id") or ""),
                    str(event.get("object_usd_prim_path") or ""),
                    str(event.get("receptacle_usd_prim_path") or ""),
                ]
            )
    return " ".join(value for value in values if value)


def _seed7_cleanup_bindings(anchor_probe: dict[str, object]) -> list[dict[str, object]]:
    bindings = []
    anchor_by_id = _runtime_anchor_by_id(anchor_probe)
    for row in anchor_probe.get("semantic_substeps", []):
        if not isinstance(row, dict):
            continue
        object_id = str(row.get("object_id") or "")
        source_fixture_id = str(row.get("source_receptacle_id") or "")
        candidate_fixture_id = str(row.get("target_receptacle_id") or "")
        if not object_id or not candidate_fixture_id:
            continue
        tools = _planner_tools_for_target_anchor(anchor_by_id.get(candidate_fixture_id, {}))
        bindings.append(
            _cleanup_binding(
                object_id,
                source_fixture_id,
                candidate_fixture_id,
                tools,
            )
        )
    if len(bindings) < 5:
        raise AssertionError(f"expected at least five seed=7 cleanup bindings, got {bindings}")
    return bindings[:5]


def _runtime_anchor_by_id(result: dict[str, object]) -> dict[str, dict[str, object]]:
    agent_view = result.get("agent_view")
    agent_view = agent_view if isinstance(agent_view, dict) else {}
    runtime_map = agent_view_module.runtime_metric_map(agent_view) if agent_view else {}
    runtime_map = runtime_map if isinstance(runtime_map, dict) else {}
    return {
        str(item.get("anchor_id") or ""): item
        for item in runtime_map.get("public_semantic_anchors", [])
        if isinstance(item, dict) and item.get("anchor_id")
    }


def _planner_tools_for_target_anchor(anchor: dict[str, object]) -> list[str]:
    affordances = {str(item) for item in anchor.get("affordances", [])}
    if "open" in affordances:
        return ["open_receptacle", "place_inside", "close_receptacle"]
    if "place_inside" in affordances:
        return ["place_inside"]
    return ["place"]


def _first_seed7_binding_requiring_tool(
    anchor_probe: dict[str, object],
    required_tool: str,
) -> dict[str, object]:
    for binding in _seed7_cleanup_bindings(anchor_probe):
        if required_tool in binding["tools"]:
            return binding
    raise AssertionError(f"expected seed=7 binding requiring {required_tool}")


def _candidate_fixture_id_for_object(result: dict[str, object], object_id: str) -> str:
    for candidate_fixture_id in (
        _semantic_substep_target_fixture_id(result, object_id),
        _primitive_evidence_target_fixture_id(result, object_id),
        _agent_view_worklist_candidate_fixture_id(result, object_id),
    ):
        if candidate_fixture_id:
            return candidate_fixture_id
    raise AssertionError(f"expected candidate fixture for {object_id}")


def _semantic_substep_target_fixture_id(result: dict[str, object], object_id: str) -> str:
    return _target_fixture_id_from_rows(
        result.get("semantic_substeps", []),
        object_id=object_id,
        field="target_receptacle_id",
    )


def _primitive_evidence_target_fixture_id(result: dict[str, object], object_id: str) -> str:
    primitive_evidence = result.get("cleanup_primitive_evidence")
    primitive_evidence = primitive_evidence if isinstance(primitive_evidence, dict) else {}
    return _target_fixture_id_from_rows(
        primitive_evidence.get("objects", []),
        object_id=object_id,
        field="target_receptacle_id",
    )


def _agent_view_worklist_candidate_fixture_id(result: dict[str, object], object_id: str) -> str:
    agent_view = result.get("agent_view") if isinstance(result.get("agent_view"), dict) else {}
    worklist = agent_view_module.cleanup_worklist(agent_view) if agent_view else {}
    rows = worklist.get("objects", []) if isinstance(worklist, dict) else []
    for item in rows:
        if not isinstance(item, dict) or str(item.get("object_id") or "") != object_id:
            continue
        candidate_fixture_id = str(item.get("candidate_fixture_id") or "")
        if candidate_fixture_id:
            return candidate_fixture_id
        return _first_destination_option_fixture_id(item.get("destination_options") or [])
    return ""


def _target_fixture_id_from_rows(rows: object, *, object_id: str, field: str) -> str:
    for item in rows if isinstance(rows, list) else []:
        if not isinstance(item, dict) or str(item.get("object_id") or "") != object_id:
            continue
        candidate_fixture_id = str(item.get(field) or "")
        if candidate_fixture_id:
            return candidate_fixture_id
    return ""


def _first_destination_option_fixture_id(destination_options: object) -> str:
    for option in destination_options if isinstance(destination_options, list) else []:
        if not isinstance(option, dict):
            continue
        candidate_fixture_id = str(option.get("candidate_fixture_id") or "")
        if candidate_fixture_id:
            return candidate_fixture_id
    return ""


def _cleanup_binding(
    object_id: str,
    source_receptacle_id: str,
    target_receptacle_id: str,
    target_tools: list[str],
) -> dict[str, object]:
    return {
        "schema": "planner_probe_cleanup_primitive_binding_v1",
        "object_id": object_id,
        "target_receptacle_id": target_receptacle_id,
        "source_receptacle_id": source_receptacle_id,
        "planner_object_id": f"{object_id}/body",
        "planner_target_receptacle_id": f"{target_receptacle_id}/body",
        "tools": [
            "navigate_to_object",
            "pick",
            "navigate_to_receptacle",
            *target_tools,
        ],
    }


def _insert_robot_timeline_before_score(report: Path) -> None:
    report_text = report.read_text(encoding="utf-8")
    robot_timeline = (
        '\n<section class="panel robot-timeline"><h2>Robot View Timeline</h2></section>'
    )
    score_marker = '<section class="panel">\n      <h2>Score</h2>'
    if score_marker in report_text:
        report_text = report_text.replace(score_marker, robot_timeline + "\n" + score_marker)
    else:
        report_text += robot_timeline
    report.write_text(report_text, encoding="utf-8")


def _b1_robot_consumption_run_result(tmp_path: Path, *, verified: bool) -> dict[str, object]:
    source_bundle = _compile_b1_runtime_bundle_for_checker(tmp_path, verified=verified)
    run_result: dict[str, object] = {
        "contract": "realworld_cleanup_contract_v1",
        "artifacts": {},
    }
    attach_nav2_map_bundle_snapshot(
        run_result=run_result,
        run_dir=tmp_path,
        source_bundle_dir=source_bundle,
    )
    manifest_path = source_bundle / "b1_robot_consumption_manifest.json"
    if manifest_path.is_file():
        shutil.copy2(manifest_path, tmp_path / "b1_robot_consumption_manifest.json")
    return run_result


def _compile_b1_runtime_bundle_for_checker(tmp_path: Path, *, verified: bool) -> Path:
    if not B1_BASE_LABELS.is_file():
        pytest.skip("B1 map source bundle is unavailable in this checkout")
    kwargs: dict[str, Path] = {}
    if verified:
        alignment_path = tmp_path / "b1_alignment_residuals.json"
        navigation_path = tmp_path / "b1_navigation_smoke.json"
        alignment_path.write_text(
            json.dumps(_b1_verified_alignment_artifact()),
            encoding="utf-8",
        )
        navigation_path.write_text(
            json.dumps(_b1_navigation_artifact(tmp_path, alignment_path=alignment_path)),
            encoding="utf-8",
        )
        kwargs = {
            "alignment_artifact_path": alignment_path,
            "navigation_artifact_path": navigation_path,
        }
    base_result = build_base_metric_map_bundle(
        map_bundle=B1_MAP12_BUNDLE,
        labels_path=B1_BASE_LABELS,
        room_semantics_path=B1_ROOM_SEMANTICS,
        output_dir=tmp_path / ("b1-base-verified" if verified else "b1-base-blocked"),
    )
    result = augment_base_metric_map_bundle(
        base_map_bundle=Path(base_result["output_dir"]),
        output_dir=tmp_path / ("b1-runtime-verified" if verified else "b1-runtime-blocked"),
        allow_blocked_proof=not verified,
        **kwargs,
    )
    return Path(result["output_dir"])


def _b1_verified_alignment_artifact() -> dict[str, object]:
    return {
        "schema": "b1_map12_scene_alignment_residuals_v1",
        "bbox_seed_policy": "known_poor_seed_only",
        "manipulation_supported": False,
        "object_receptacle_usd_binding_status": "blocked_out_of_scope",
        "global_alignment_status": "verified",
        "selected_transform_type": "rigid_2d",
        "selected_transform": {
            "source": "reviewed_correspondence_fit",
            "type": "rigid_2d",
        },
        "residual_evidence": {
            "status": "available",
            "matched_anchor_count": 6,
            "transform_source": "reviewed_correspondence_fit",
            "mean_residual_m": 0.1,
            "median_residual_m": 0.1,
            "p90_residual_m": 0.2,
            "max_residual_m": 0.3,
        },
        "area_alignment": [],
    }


def _b1_navigation_artifact(tmp_path: Path, *, alignment_path: Path) -> dict[str, object]:
    first = tmp_path / "b1-waypoint-1.fpv.png"
    second = tmp_path / "b1-waypoint-2.fpv.png"
    _write_checker_reviewable_png(first, color=(32, 64, 96))
    _write_checker_reviewable_png(second, color=(96, 64, 32))
    return {
        "schema": "b1_map12_navigation_smoke_v1",
        "status": "passed",
        "b1_scene_usd": str(DEFAULT_B1_VISUAL_ROUTE_SCENE_USD),
        "visual_route": {
            "scene_id": "B1_floor2_slow",
            "scene_usd": str(DEFAULT_B1_VISUAL_ROUTE_SCENE_USD),
            "selected": True,
            "status": "same_pose_render_verified",
        },
        "robot_navigation_supported": True,
        "robot_navigation_provenance": NAVIGATION_PROVENANCE,
        "navigation_provenance": "kinematic_pose_driven",
        "alignment_artifact": str(alignment_path),
        "alignment_transform_source": "reviewed_correspondence_fit",
        "planner_backed": False,
        "physical_robot": False,
        "semantic_source": "robot_map_12_navigation_memory_overlay",
        "semantic_usd_binding_status": "blocked_until_segmentation_or_manifest",
        "semantic_anchors_are_usd_truth": False,
        "usd_object_index_ready": False,
        "usd_receptacle_index_ready": False,
        "manipulation_supported": False,
        "navigation_waypoint_count": 2,
        "robot_view_evidence_status": "available",
        "waypoint_evidence": [
            _b1_waypoint_evidence(
                "wp_1",
                x=-4.0,
                y=-8.0,
                alignment_path=alignment_path,
                fpv=first,
            ),
            _b1_waypoint_evidence(
                "wp_2",
                x=-2.0,
                y=-7.0,
                alignment_path=alignment_path,
                fpv=second,
            ),
        ],
    }


def _b1_waypoint_evidence(
    waypoint_id: str,
    *,
    x: float,
    y: float,
    alignment_path: Path,
    fpv: Path,
) -> dict[str, object]:
    return {
        "waypoint_id": waypoint_id,
        "scene_usd": str(DEFAULT_B1_VISUAL_ROUTE_SCENE_USD),
        "robot_pose": {
            "frame": "b1_rebuilt_scene_usd_world_candidate",
            "x": x,
            "y": y,
            "z": 0.0,
            "yaw_deg": 0.0,
        },
        "robot_pose_applied": True,
        "alignment_artifact": str(alignment_path),
        "alignment_transform_source": "reviewed_correspondence_fit",
        "views": {"fpv": str(fpv)},
    }


def _write_checker_reviewable_png(path: Path, *, color: tuple[int, int, int]) -> None:
    image = Image.new("RGB", (32, 24))
    pixels = image.load()
    red, green, blue = color
    for y in range(image.height):
        for x in range(image.width):
            pixels[x, y] = (
                (red + x * 7) % 256,
                (green + y * 11) % 256,
                (blue + (x + y) * 5) % 256,
            )
    image.save(path)


def _write_strict_planner_proof(
    base: Path,
    *,
    embodiment: str = "franka",
    upstream_policy_class: str = "PickAndPlacePlannerPolicy",
    curobo_available: bool = False,
    cleanup_binding: dict[str, object] | None = None,
    steps_executed: int = 2,
    max_abs_qpos_delta: float = 0.01,
) -> Path:
    base.mkdir(parents=True)
    views = base / "planner_views"
    views.mkdir()
    (views / "initial_wrist_camera.png").write_bytes(b"initial")
    (views / "final_wrist_camera.png").write_bytes(b"final")
    evidence = planner_backed_probe_evidence(
        backend="molmospaces_subprocess",
        embodiment=embodiment,
        task="pick_and_place",
        probe_mode="execute",
        upstream_policy_class=upstream_policy_class,
        steps_requested=2,
        steps_executed=steps_executed,
        max_abs_qpos_delta=max_abs_qpos_delta,
        image_artifacts={
            "initial": "planner_views/initial_wrist_camera.png",
            "final": "planner_views/final_wrist_camera.png",
        },
    )
    evidence["runtime_diagnostics"] = {
        "renderer_adapter_enabled": True,
        "modules": {"curobo": {"available": curobo_available}},
    }
    if cleanup_binding is not None:
        evidence["cleanup_primitive_binding"] = cleanup_binding
    path = base / "run_result.json"
    path.write_text(
        json.dumps(
            {
                "contract": MANIPULATION_PROBE_CONTRACT,
                "status": PLANNER_BACKED_PROVENANCE,
                "primitive_provenance": PLANNER_BACKED_PROVENANCE,
                "manipulation_evidence": evidence,
            }
        ),
        encoding="utf-8",
    )
    return path


__all__ = [name for name in globals() if not name.startswith("__")]

# The split fixture modules preserve the original shared helper namespace.
from tests.support import cleanup_checker_base as _base_module
from tests.support import cleanup_checker_isaac as _isaac_module
from tests.support import cleanup_checker_robot_views as _robot_views_module

for _module in (_base_module, _isaac_module, _robot_views_module):
    _module.__dict__.update(
        {name: value for name, value in globals().items() if not name.startswith("__")}
    )
