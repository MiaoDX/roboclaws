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
    assert policies["package-to-scripts"]["status"] == "ratcheted-known-red"
