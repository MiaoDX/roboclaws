#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from html import escape
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from roboclaws.backends.isaaclab.b1_readiness import (
    NAVIGATION_SMOKE_SCHEMA,
    READINESS_SCHEMA,
    WAYPOINT_POSE_REQUESTS_SCHEMA,
    validate_navigation_smoke_artifact,
    validate_readiness_artifact,
    validate_waypoint_pose_requests_artifact,
)
from roboclaws.core.json_sources import read_json_object


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a B1 / robot_map_12 navigation-smoke HTML report."
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--navigation-artifact", type=Path)
    parser.add_argument("--readiness-artifact", type=Path)
    parser.add_argument("--waypoint-pose-requests", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_dir = Path(args.run_dir)
    navigation_path = Path(args.navigation_artifact or run_dir / "navigation_smoke.json")
    readiness_path = Path(args.readiness_artifact or run_dir / "readiness_with_navigation.json")
    pose_requests_path = Path(
        args.waypoint_pose_requests or run_dir / "waypoint_pose_requests.json"
    )
    output_path = Path(args.output or run_dir / "report.html")

    navigation = read_json_object(navigation_path, label="navigation artifact")
    _require_schema(
        navigation,
        path=navigation_path,
        label="navigation artifact",
        expected=NAVIGATION_SMOKE_SCHEMA,
    )
    readiness = _read_optional_json_object(
        readiness_path,
        label="readiness artifact",
        explicit=args.readiness_artifact is not None,
    )
    if readiness is not None:
        _require_schema(
            readiness,
            path=readiness_path,
            label="readiness artifact",
            expected=READINESS_SCHEMA,
        )
    pose_requests = _read_optional_json_object(
        pose_requests_path,
        label="waypoint pose request artifact",
        explicit=args.waypoint_pose_requests is not None,
    )
    if pose_requests is not None:
        _require_schema(
            pose_requests,
            path=pose_requests_path,
            label="waypoint pose request artifact",
            expected=WAYPOINT_POSE_REQUESTS_SCHEMA,
        )
    html = render_report(
        run_dir=run_dir,
        navigation=navigation,
        readiness=readiness or {},
        pose_requests=pose_requests or {},
        navigation_path=navigation_path,
        readiness_path=readiness_path if readiness is not None else None,
        pose_requests_path=pose_requests_path if pose_requests is not None else None,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(
        json.dumps(
            {
                "schema": "b1_map12_navigation_report_v1",
                "status": navigation.get("status"),
                "output": str(output_path),
            },
            sort_keys=True,
        )
    )
    return 0


def render_report(
    *,
    run_dir: Path,
    navigation: dict[str, Any],
    readiness: dict[str, Any],
    pose_requests: dict[str, Any],
    navigation_path: Path,
    readiness_path: Path | None,
    pose_requests_path: Path | None,
) -> str:
    if navigation.get("schema") != NAVIGATION_SMOKE_SCHEMA:
        raise ValueError(f"unexpected navigation schema: {navigation.get('schema')!r}")
    if readiness and readiness.get("schema") != READINESS_SCHEMA:
        raise ValueError(f"unexpected readiness schema: {readiness.get('schema')!r}")
    if pose_requests and pose_requests.get("schema") != WAYPOINT_POSE_REQUESTS_SCHEMA:
        raise ValueError(
            f"unexpected waypoint pose request schema: {pose_requests.get('schema')!r}"
        )
    navigation_errors = validate_navigation_smoke_artifact(navigation, require_files=False)
    readiness_errors = (
        validate_readiness_artifact(
            readiness,
            require_navigation_success=bool(readiness.get("robot_navigation_supported")),
        )
        if readiness
        else []
    )
    pose_request_errors = (
        validate_waypoint_pose_requests_artifact(pose_requests) if pose_requests else []
    )
    rows = [
        ("Navigation smoke", str(navigation.get("status") or "")),
        ("Readiness", str(readiness.get("readiness_status") or "not provided")),
        ("Waypoint pose requests", str(pose_requests.get("status") or "not provided")),
        ("Robot navigation", _yes_no(navigation.get("robot_navigation_supported"))),
        ("Navigation provenance", str(navigation.get("navigation_provenance") or "")),
        ("Robot provenance", str(navigation.get("robot_navigation_provenance") or "")),
        ("Planner backed", _yes_no(navigation.get("planner_backed"))),
        ("Physical robot", _yes_no(navigation.get("physical_robot"))),
        ("Semantic source", str(navigation.get("semantic_source") or "")),
        ("Semantic USD binding", str(navigation.get("semantic_usd_binding_status") or "")),
        ("USD object index", _yes_no(navigation.get("usd_object_index_ready"))),
        ("USD receptacle index", _yes_no(navigation.get("usd_receptacle_index_ready"))),
        ("Manipulation", _yes_no(navigation.get("manipulation_supported"))),
        ("Waypoint evidence", str(navigation.get("navigation_waypoint_count") or 0)),
        ("Ready pose requests", str(pose_requests.get("waypoint_count") or 0)),
        ("Blocked pose requests", str(pose_requests.get("blocked_request_count") or 0)),
        ("Robot views", str(navigation.get("robot_view_evidence_status") or "")),
        ("Map-scene alignment", str(readiness.get("readiness_alignment_status") or "")),
        ("Map-scene transform", str(readiness.get("map12_to_b1_usd_transform_status") or "")),
        ("Residual evidence", _residual_summary(readiness)),
    ]
    validation_rows = [
        ("navigation contract", navigation_errors),
        ("readiness contract", readiness_errors),
        ("waypoint pose request contract", pose_request_errors),
        ("navigation artifact validation", _validation_errors(navigation)),
        ("readiness artifact validation", _validation_errors(readiness)),
        ("waypoint pose request validation", _validation_errors(pose_requests)),
    ]
    request_cards = _pose_request_section(pose_requests)
    waypoint_cards = [
        _waypoint_card(run_dir, waypoint, index)
        for index, waypoint in enumerate(_waypoints(navigation), start=1)
    ]
    artifact_links = [
        ("navigation_smoke.json", _relative_href(run_dir, navigation_path)),
    ]
    if readiness_path is not None:
        artifact_links.append(
            ("readiness_with_navigation.json", _relative_href(run_dir, readiness_path))
        )
    if pose_requests_path is not None:
        artifact_links.append(
            ("waypoint_pose_requests.json", _relative_href(run_dir, pose_requests_path))
        )
    manipulation_badge = _badge(
        "manipulation",
        "unsupported" if not navigation.get("manipulation_supported") else "supported",
    )
    artifact_link_html = "".join(
        f'<div><a href="{escape(href)}">{escape(label)}</a></div>' for label, href in artifact_links
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>B1 / Map 12 Navigation Smoke</title>
  <style>
    :root {{
      color-scheme: light;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
      --ink: #17202a;
      --muted: #5d6b7a;
      --line: #d8dee6;
      --panel: #f7f8fa;
      --ok: #0f7b45;
      --warn: #8a5a00;
      --bad: #a32626;
    }}
    body {{
      margin: 0;
      background: #ffffff;
      color: var(--ink);
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 28px 24px 48px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 30px;
      line-height: 1.15;
      letter-spacing: 0;
    }}
    h2 {{
      margin: 28px 0 12px;
      font-size: 18px;
      letter-spacing: 0;
    }}
    p {{
      color: var(--muted);
      line-height: 1.5;
      margin: 0 0 16px;
    }}
    .badges {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 16px 0 24px;
    }}
    .badge {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 5px 10px;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .badge.ok {{ color: var(--ok); border-color: #98d4b7; background: #eefaf4; }}
    .badge.warn {{ color: var(--warn); border-color: #e3c075; background: #fff8e8; }}
    .badge.bad {{ color: var(--bad); border-color: #efaaa8; background: #fff0f0; }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    .summary div {{
      padding: 12px 14px;
      border-right: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
      min-width: 0;
    }}
    .summary dt {{
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 4px;
    }}
    .summary dd {{
      margin: 0;
      font-weight: 650;
      overflow-wrap: anywhere;
    }}
    .notice {{
      border: 1px solid #e3c075;
      background: #fff8e8;
      border-radius: 8px;
      padding: 12px 14px;
      color: #5b3e00;
      margin: 18px 0;
    }}
    .waypoint {{
      border: 1px solid var(--line);
      border-radius: 8px;
      margin: 16px 0;
      overflow: hidden;
    }}
    .request-table {{
      width: 100%;
      border-collapse: collapse;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      display: block;
      overflow-x: auto;
      white-space: nowrap;
    }}
    .request-table th, .request-table td {{
      border-bottom: 1px solid var(--line);
      padding: 8px 10px;
      text-align: left;
      font-size: 13px;
    }}
    .request-table th {{
      color: var(--muted);
      background: var(--panel);
      font-size: 12px;
    }}
    .waypoint-head {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) repeat(4, auto);
      gap: 12px;
      align-items: center;
      background: var(--panel);
      border-bottom: 1px solid var(--line);
      padding: 12px 14px;
    }}
    .waypoint-head strong {{
      overflow-wrap: anywhere;
    }}
    .metric {{
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }}
    .images {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
      padding: 14px;
    }}
    figure {{
      margin: 0;
      border: 1px solid var(--line);
      border-radius: 6px;
      overflow: hidden;
      background: #fff;
    }}
    img {{
      width: 100%;
      display: block;
      aspect-ratio: 3 / 2;
      object-fit: contain;
      background: #101820;
    }}
    figcaption {{
      padding: 8px 10px;
      color: var(--muted);
      font-size: 12px;
    }}
    .checks, .artifacts {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px 14px;
    }}
    .checks div, .artifacts div {{
      padding: 6px 0;
      border-bottom: 1px solid var(--line);
    }}
    .checks div:last-child, .artifacts div:last-child {{
      border-bottom: 0;
    }}
    code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
    }}
    a {{ color: #174ea6; }}
    @media (max-width: 720px) {{
      main {{ padding: 22px 16px 36px; }}
      .waypoint-head {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
<main>
  <h1>B1 / Map 12 Navigation Smoke</h1>
  <p>Pose-driven Isaac evidence for B1 floor 2 against robot_map_12 semantic anchors.</p>
  <div class="badges">
    {_badge("navigation", str(navigation.get("status") or ""))}
    {_badge("readiness", str(readiness.get("readiness_status") or "not provided"))}
    {_badge("planner", "planner-backed" if navigation.get("planner_backed") else "kinematic")}
    {manipulation_badge}
  </div>
  <section class="summary">
    {_summary_rows(rows)}
  </section>
  <div class="notice">
    This report proves local pose-driven robot-view navigation evidence only. It does not
    prove Nav2 planner parity, physical robot execution, semantic USD object binding, or
    pick/place manipulation readiness. Map-scene alignment is verified only when reviewed
    correspondence residual evidence is attached; the bbox overlay is a known-poor search seed.
  </div>
  <h2>Waypoint Evidence</h2>
  {"".join(waypoint_cards) if waypoint_cards else "<p>No waypoint evidence was recorded.</p>"}
  <h2>Waypoint Pose Requests</h2>
  {request_cards}
  <h2>Contract Checks</h2>
  <section class="checks">
    {_validation_rows(validation_rows)}
  </section>
  <h2>Artifacts</h2>
  <section class="artifacts">
    {artifact_link_html}
  </section>
</main>
</body>
</html>
"""


def _read_optional_json_object(
    path: Path,
    *,
    label: str,
    explicit: bool,
) -> dict[str, Any] | None:
    if explicit or path.is_file():
        return read_json_object(path, label=label)
    return None


def _require_schema(
    payload: dict[str, Any],
    *,
    path: Path,
    label: str,
    expected: str,
) -> None:
    if payload.get("schema") != expected:
        raise ValueError(f"unexpected {label} schema in {path}: {payload.get('schema')!r}")


def _waypoints(navigation: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in navigation.get("waypoint_evidence") or [] if isinstance(item, dict)]


def _pose_request_section(pose_requests: dict[str, Any]) -> str:
    if not pose_requests:
        return "<p>No waypoint pose request artifact was provided.</p>"
    ready_rows = [
        _pose_request_row(item, "ready") for item in _pose_request_waypoints(pose_requests)
    ]
    blocked_rows = [
        _pose_request_row(item, "blocked") for item in _pose_request_blocked(pose_requests)
    ]
    rows = "".join([*ready_rows, *blocked_rows])
    if not rows:
        rows = (
            '<tr><td colspan="6">No ready or blocked waypoint pose request rows were recorded.'
            "</td></tr>"
        )
    return f"""
  <table class="request-table">
    <thead>
      <tr>
        <th>Status</th>
        <th>Waypoint</th>
        <th>Coverage</th>
        <th>Map12</th>
        <th>B1 pose</th>
        <th>Reason</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
"""


def _pose_request_waypoints(pose_requests: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in pose_requests.get("waypoints") or [] if isinstance(item, dict)]


def _pose_request_blocked(pose_requests: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in pose_requests.get("blocked_requests") or [] if isinstance(item, dict)]


def _pose_request_row(item: dict[str, Any], status: str) -> str:
    coverage = (
        item.get("coverage_decision") if isinstance(item.get("coverage_decision"), dict) else {}
    )
    nav_goal = item.get("map12_nav_goal") if isinstance(item.get("map12_nav_goal"), dict) else {}
    pose = item.get("b1_pose") if isinstance(item.get("b1_pose"), dict) else {}
    return (
        "<tr>"
        f"<td>{escape(status)}</td>"
        f"<td>{escape(str(item.get('waypoint_id') or ''))}</td>"
        f"<td>{escape(_coverage_label(coverage))}</td>"
        f"<td>{_goal_label(nav_goal)}</td>"
        f"<td>{_pose_label(pose) if pose else ''}</td>"
        f"<td>{escape(str(item.get('reason') or ''))}</td>"
        "</tr>"
    )


def _waypoint_card(run_dir: Path, waypoint: dict[str, Any], index: int) -> str:
    pose = waypoint.get("robot_pose") if isinstance(waypoint.get("robot_pose"), dict) else {}
    nav_goal = (
        waypoint.get("map12_nav_goal") if isinstance(waypoint.get("map12_nav_goal"), dict) else {}
    )
    views = waypoint.get("views") if isinstance(waypoint.get("views"), dict) else {}
    view_order = ("fpv", "chase", "topdown", "verify")
    figures = []
    for view_name in view_order:
        raw = views.get(view_name)
        if not raw:
            continue
        path = Path(str(raw))
        href = _relative_href(run_dir, path)
        shape = _shape_label(waypoint, view_name)
        figures.append(
            f'<figure><img src="{escape(href)}" alt="{escape(view_name)} view" />'
            f"<figcaption>{escape(view_name.upper())}{escape(shape)}</figcaption></figure>"
        )
    return f"""
  <article class="waypoint">
    <div class="waypoint-head">
      <strong>{index}. {escape(str(waypoint.get("waypoint_id") or "waypoint"))}</strong>
      <span class="metric">anchor: {escape(str(waypoint.get("source_anchor_id") or ""))}</span>
      <span class="metric">pose: {_pose_label(pose)}</span>
      <span class="metric">map12: {_goal_label(nav_goal)}</span>
      <span class="metric">applied: {_yes_no(waypoint.get("robot_pose_applied"))}</span>
    </div>
    <div class="images">
      {"".join(figures) if figures else "<p>No view images recorded for this waypoint.</p>"}
    </div>
  </article>
"""


def _summary_rows(rows: list[tuple[str, str]]) -> str:
    return "".join(
        f"<div><dt>{escape(label)}</dt><dd>{escape(value)}</dd></div>" for label, value in rows
    )


def _validation_rows(rows: list[tuple[str, list[str]]]) -> str:
    rendered = []
    for label, errors in rows:
        status = "passed" if not errors else "; ".join(errors)
        rendered.append(f"<div><strong>{escape(label)}</strong>: {escape(status)}</div>")
    return "".join(rendered)


def _validation_errors(payload: dict[str, Any]) -> list[str]:
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    errors = validation.get("errors") if isinstance(validation.get("errors"), list) else []
    return [str(item) for item in errors]


def _residual_summary(readiness: dict[str, Any]) -> str:
    residual = readiness.get("residual_evidence")
    if not isinstance(residual, dict):
        return ""
    status = str(residual.get("status") or "not_available")
    count = int(residual.get("matched_anchor_count") or 0)
    mean = residual.get("mean_residual_m")
    max_value = residual.get("max_residual_m")
    if status != "available":
        return f"{status}, anchors={count}"
    return f"{status}, anchors={count}, mean={mean} m, max={max_value} m"


def _badge(label: str, value: str) -> str:
    text = f"{label}: {value or 'unknown'}"
    lowered = text.lower()
    class_name = "ok"
    if "blocked" in lowered or "failed" in lowered or "unsupported" in lowered:
        class_name = "bad" if "failed" in lowered else "warn"
    if "not provided" in lowered:
        class_name = "warn"
    return f'<span class="badge {class_name}">{escape(text)}</span>'


def _yes_no(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value or "")


def _pose_label(pose: dict[str, Any]) -> str:
    return escape(
        "x={x:.2f}, y={y:.2f}, yaw={yaw:.1f}".format(
            x=float(pose.get("x") or 0.0),
            y=float(pose.get("y") or 0.0),
            yaw=float(pose.get("yaw_deg") or 0.0),
        )
    )


def _goal_label(goal: dict[str, Any]) -> str:
    if not goal:
        return ""
    return escape(
        "x={x:.2f}, y={y:.2f}, yaw={yaw:.2f}".format(
            x=float(goal.get("x") or 0.0),
            y=float(goal.get("y") or 0.0),
            yaw=float(goal.get("yaw") or 0.0),
        )
    )


def _coverage_label(coverage: dict[str, Any]) -> str:
    if not coverage:
        return ""
    parts = [
        str(coverage.get("status") or ""),
        str(coverage.get("fit_scope") or ""),
        str(coverage.get("navigation_area_id") or ""),
    ]
    return " / ".join(part for part in parts if part)


def _shape_label(waypoint: dict[str, Any], view_name: str) -> str:
    shapes = waypoint.get("shapes") if isinstance(waypoint.get("shapes"), dict) else {}
    shape = shapes.get(view_name)
    if isinstance(shape, list) and len(shape) >= 2:
        return f" {shape[1]}x{shape[0]}"
    return ""


def _relative_href(run_dir: Path, path: Path) -> str:
    target = Path(path)
    if not target.is_absolute():
        target = target.resolve()
    base = Path(run_dir).resolve()
    try:
        return target.relative_to(base).as_posix()
    except ValueError:
        return target.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
