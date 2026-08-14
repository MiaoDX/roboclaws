from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "dev" / "check_architecture_import_graph.py"


def load_module():
    spec = importlib.util.spec_from_file_location("check_architecture_import_graph", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_tarjan_reports_only_nontrivial_components() -> None:
    module = load_module()
    edges = [
        module.ImportEdge("roboclaws.a", "roboclaws.b", 1),
        module.ImportEdge("roboclaws.b", "roboclaws.a", 1),
        module.ImportEdge("roboclaws.b", "roboclaws.c", 2),
    ]

    assert module.strongly_connected_components(
        ["roboclaws.a", "roboclaws.b", "roboclaws.c"], edges
    ) == [["roboclaws.a", "roboclaws.b"]]


def test_comparison_allows_removals_but_rejects_new_edges() -> None:
    module = load_module()
    baseline = {
        "module_sccs": [["roboclaws.a", "roboclaws.b"]],
        "package_bidirectional_edges": [["a", "b"]],
        "allowed_package_edge_matrix": {"a": ["b"], "b": ["a"]},
        "policies": [
            {"id": "package-to-scripts", "known_violations": [["roboclaws.a", "scripts/a.py"]]}
        ],
    }
    current = {
        "module_sccs": [],
        "package_bidirectional_edges": [],
        "allowed_package_edge_matrix": {"a": ["b"], "b": []},
        "policies": [{"id": "package-to-scripts", "known_violations": []}],
    }

    assert module.compare_to_baseline(current, baseline) == []

    current["allowed_package_edge_matrix"]["a"].append("c")
    assert module.compare_to_baseline(current, baseline) == ["new package edges from a: ['c']"]


def test_script_references_detect_embedded_commands_and_argv_paths(
    tmp_path: Path, monkeypatch
) -> None:
    module = load_module()
    package_root = tmp_path / "roboclaws"
    package_root.mkdir()
    (package_root / "sample.py").write_text(
        "\n".join(
            (
                'COMMAND = ".venv/bin/python scripts/operator_console/export.py --dry-run"',
                'ARGV = [".venv/bin/python", "scripts/operator_console/runner.py"]',
                'JOINED = "scripts/maps/" + "joined.py"',
                'PATHED = Path("scripts") / "maps" / "path_runner.py"',
                'FORMATTED = f"scripts/tools/{command}.py"',
                'DYNAMIC = importlib.import_module("scripts.dynamic_runner")',
                'OTHER_DYNAMIC = __import__("scripts.other_runner")',
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    assert module.collect_script_references(package_root) == [
        ["roboclaws.sample", "scripts.dynamic_runner"],
        ["roboclaws.sample", "scripts.other_runner"],
        ["roboclaws.sample", "scripts/maps/joined.py"],
        ["roboclaws.sample", "scripts/maps/path_runner.py"],
        ["roboclaws.sample", "scripts/operator_console/export.py"],
        ["roboclaws.sample", "scripts/operator_console/runner.py"],
        ["roboclaws.sample", "scripts/tools/*.py"],
    ]


def test_dynamic_package_imports_participate_in_graph_edges(tmp_path: Path, monkeypatch) -> None:
    module = load_module()
    package_root = tmp_path / "roboclaws"
    package_root.mkdir()
    (package_root / "source.py").write_text(
        'TARGET = importlib.import_module("roboclaws.target")\n',
        encoding="utf-8",
    )
    (package_root / "target.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    assert module.collect_import_edges(package_root) == [
        module.ImportEdge("roboclaws.source", "roboclaws.target", 1)
    ]


def test_type_checking_imports_do_not_participate_in_runtime_graph(
    tmp_path: Path, monkeypatch
) -> None:
    module = load_module()
    package_root = tmp_path / "roboclaws"
    package_root.mkdir()
    (package_root / "source.py").write_text(
        "\n".join(
            (
                "from typing import TYPE_CHECKING",
                "if TYPE_CHECKING:",
                "    from roboclaws.type_target import TypeTarget",
                "else:",
                "    from roboclaws.runtime_target import RuntimeTarget",
            )
        ),
        encoding="utf-8",
    )
    (package_root / "type_target.py").write_text("class TypeTarget: ...\n", encoding="utf-8")
    (package_root / "runtime_target.py").write_text("class RuntimeTarget: ...\n", encoding="utf-8")
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    assert module.collect_import_edges(package_root) == [
        module.ImportEdge("roboclaws.source", "roboclaws.runtime_target", 5)
    ]


def test_current_graph_freezes_authoritative_cycles_and_package_pairs() -> None:
    module = load_module()

    state = module.build_graph_state()
    baseline = json.loads(module.DEFAULT_BASELINE.read_text(encoding="utf-8"))

    assert state["module_sccs"] == baseline["module_sccs"]
    assert state["package_bidirectional_edges"] == baseline["package_bidirectional_edges"]
    assert state["module_sccs"] == []
    assert state["package_bidirectional_edges"] == []
    policies = {item["id"]: item for item in state["policies"]}
    assert policies["package-to-scripts"]["owning_wave"] == "Wave 5"
    assert policies["core-product-inversions"]["owning_wave"] == "Waves 1-2"
    assert policies["core-product-inversions"]["status"] == "green"
    assert policies["core-product-inversions"]["known_violations"] == []
    assert policies["planned-reverse-package-edges"]["status"] == "green"
    assert policies["planned-reverse-package-edges"]["known_violations"] == []
    assert policies["package-to-scripts"]["status"] == "green"
    assert policies["package-to-scripts"]["known_violations"] == []


def test_default_success_output_is_concise(tmp_path: Path, monkeypatch, capsys) -> None:
    module = load_module()
    state = {
        "module_count": 12,
        "edge_count": 34,
        "module_sccs": [],
        "package_bidirectional_edges": [],
        "allowed_package_edge_matrix": {},
        "policies": [
            {"id": "package-to-scripts", "known_violations": []},
            {"id": "core-product-inversions", "known_violations": []},
        ],
    }
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(module, "build_graph_state", lambda: state)

    assert module.main(["--baseline", str(baseline)]) == 0
    assert capsys.readouterr().out == (
        "architecture import graph ok: 12 modules, 34 edges, 0 SCCs, "
        "0 bidirectional package pairs, 0 policy violations\n"
    )


def test_write_keeps_full_json_output_and_stdout_silent(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    module = load_module()
    state = {
        "module_count": 1,
        "edge_count": 0,
        "module_sccs": [],
        "package_bidirectional_edges": [],
        "allowed_package_edge_matrix": {},
        "policies": [],
    }
    output = tmp_path / "graph.json"
    missing_baseline = tmp_path / "missing-baseline.json"
    monkeypatch.setattr(module, "build_graph_state", lambda: state)

    assert module.main(["--baseline", str(missing_baseline), "--write", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8")) == state
    assert capsys.readouterr().out == ""


def test_failure_output_keeps_detailed_regressions(tmp_path: Path, monkeypatch, capsys) -> None:
    module = load_module()
    baseline = {
        "module_sccs": [],
        "package_bidirectional_edges": [],
        "allowed_package_edge_matrix": {"a": []},
        "policies": [{"id": "package-to-scripts", "known_violations": []}],
    }
    current = {
        "module_count": 2,
        "edge_count": 1,
        "module_sccs": [],
        "package_bidirectional_edges": [],
        "allowed_package_edge_matrix": {"a": ["b"]},
        "policies": [{"id": "package-to-scripts", "known_violations": []}],
    }
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    monkeypatch.setattr(module, "build_graph_state", lambda: current)

    assert module.main(["--baseline", str(baseline_path)]) == 1
    assert capsys.readouterr().out == "new package edges from a: ['b']\n"
