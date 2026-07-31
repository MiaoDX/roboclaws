from __future__ import annotations

from pathlib import Path

from roboclaws.backends.isaaclab import rby1m_robot_usd


def test_import_request_is_typed_and_writes_blocked_summary(tmp_path: Path) -> None:
    summary_path = tmp_path / "summary.json"
    request = rby1m_robot_usd.Rby1mRobotUsdRequest(
        urdf_path=tmp_path / "missing.urdf",
        output_usd_path=tmp_path / "robot.usda",
        summary_output=summary_path,
        robot_name="typed-rby1m",
        static_only=True,
    )

    summary = rby1m_robot_usd.import_rby1m_robot_usd(request)

    assert summary["status"] == "blocked"
    assert summary["robot_name"] == "typed-rby1m"
    assert summary["static_only"] is True
    assert summary_path.is_file()


def test_parse_urdf_tree_records_visuals_and_link_transforms(tmp_path: Path) -> None:
    mesh_path = tmp_path / "head.obj"
    mesh_path.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
    urdf_path = tmp_path / "robot.urdf"
    urdf_path.write_text(
        """<robot name="rby1m">
  <link name="base"/>
  <link name="head">
    <visual>
      <origin xyz="0.1 0.2 0.3" rpy="0 0 0"/>
      <geometry><mesh filename="head.obj"/></geometry>
    </visual>
  </link>
  <joint name="base_to_head" type="fixed">
    <parent link="base"/>
    <child link="head"/>
    <origin xyz="1 2 3" rpy="0 0 0"/>
  </joint>
</robot>
""",
        encoding="utf-8",
    )

    robot = rby1m_robot_usd._parse_urdf_tree(urdf_path)

    assert set(robot["link_transforms"]) == {"base", "head"}
    assert robot["link_transforms"]["base"] == rby1m_robot_usd._identity_matrix()
    assert robot["link_transforms"]["head"][0][3] == 1.0
    assert robot["link_transforms"]["head"][1][3] == 2.0
    assert robot["link_transforms"]["head"][2][3] == 3.0
    assert robot["visuals"]["head"][0]["mesh_path"] == mesh_path.resolve()
    assert robot["visuals"]["head"][0]["origin_matrix"][0][3] == 0.1
    assert robot["child_to_parent"]["head"][0] == "base"
