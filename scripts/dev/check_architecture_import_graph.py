#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Iterable, NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "roboclaws"
SCHEMA = "roboclaws_architecture_import_graph_v1"
DEFAULT_BASELINE = REPO_ROOT / "scripts" / "dev" / "architecture_import_baseline.json"
SCRIPT_PATH_PATTERN = re.compile(r"(?<![\w.])scripts/[A-Za-z0-9_*./-]+\.py")


class ImportEdge(NamedTuple):
    source: str
    target: str
    line: int
    kind: str = "import"


PLANNED_POLICIES = (
    {
        "id": "package-to-scripts",
        "description": "roboclaws modules must not import or execute scripts",
        "owning_wave": "Wave 5",
    },
    {
        "id": "core-product-inversions",
        "description": "core product packages must not import eval, report, or operator-console UI",
        "owning_wave": "Waves 1-2",
    },
    {
        "id": "planned-reverse-package-edges",
        "description": (
            "remove household->agents/launch, agents->household/operator_console, "
            "and agents->launch"
        ),
        "owning_wave": "Waves 1-2",
    },
)


def module_name(path: Path) -> str:
    relative = path.relative_to(REPO_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def python_modules(root: Path = PACKAGE_ROOT) -> dict[str, Path]:
    return {module_name(path): path for path in sorted(root.rglob("*.py"))}


def resolve_from(source: str, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module
    package = source.split(".")[:-1]
    if (REPO_ROOT / Path(*source.split(".")) / "__init__.py").exists():
        package = source.split(".")
    keep = len(package) - node.level + 1
    if keep < 0:
        return None
    prefix = package[:keep]
    return ".".join([*prefix, *(node.module or "").split(".")]).rstrip(".")


def collect_import_edges(root: Path = PACKAGE_ROOT) -> list[ImportEdge]:
    modules = python_modules(root)
    edges: set[ImportEdge] = set()
    for source, path in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            for target in _import_targets(source, node):
                candidates = [target]
                while candidates[-1] and candidates[-1] not in modules and "." in candidates[-1]:
                    candidates.append(candidates[-1].rsplit(".", 1)[0])
                resolved = next((item for item in candidates if item in modules), None)
                if resolved and resolved != source:
                    edges.add(ImportEdge(source, resolved, int(node.lineno)))
    return sorted(edges)


def collect_script_references(root: Path = PACKAGE_ROOT) -> list[list[str]]:
    references: set[tuple[str, str]] = set()
    for source, path in python_modules(root).items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            references.update((source, target) for target in _script_targets(node))
    return [list(item) for item in sorted(references)]


def _import_targets(source: str, node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        base = resolve_from(source, node)
        if base:
            return [base, *(f"{base}.{alias.name}" for alias in node.names)]
        return []
    dynamic_target = _dynamic_import_target(node)
    return [dynamic_target] if dynamic_target else []


def _script_targets(node: ast.AST) -> set[str]:
    targets: set[str] = set()
    if isinstance(node, ast.Import):
        targets.update(
            alias.name
            for alias in node.names
            if alias.name == "scripts" or alias.name.startswith("scripts.")
        )
    elif isinstance(node, ast.ImportFrom):
        module = node.module or "scripts"
        if module == "scripts" or module.startswith("scripts."):
            targets.add(module)
    dynamic_target = _dynamic_import_target(node)
    if dynamic_target == "scripts" or (dynamic_target or "").startswith("scripts."):
        targets.add(dynamic_target or "scripts")
    static_text = _static_path_text(node)
    if static_text is not None:
        targets.update(SCRIPT_PATH_PATTERN.findall(static_text.replace("\\", "/")))
    return targets


def _static_path_text(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                parts.append("*")
            else:
                return None
        return "".join(parts)
    if isinstance(node, ast.Call) and node.args and _is_path_constructor(node.func):
        return _static_path_text(node.args[0])
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Div)):
        left = _static_path_text(node.left)
        right = _static_path_text(node.right)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Div):
            return f"{left.rstrip('/')}/{right.lstrip('/')}"
        return left + right
    return None


def _is_path_constructor(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "Path"
    return isinstance(node, ast.Attribute) and node.attr == "Path"


def _dynamic_import_target(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call) or not node.args:
        return None
    is_import = isinstance(node.func, ast.Name) and node.func.id == "__import__"
    is_import_module = isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"
    if not (is_import or is_import_module):
        return None
    target = _static_path_text(node.args[0])
    return target if target and "*" not in target else None


def strongly_connected_components(  # noqa: C901 - Tarjan traversal stays together.
    modules: Iterable[str], edges: Iterable[ImportEdge]
) -> list[list[str]]:
    graph = {module: set() for module in modules}
    for edge in edges:
        graph.setdefault(edge.source, set()).add(edge.target)
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    result: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in sorted(graph.get(node, ())):
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] == indices[node]:
            component: list[str] = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.append(member)
                if member == node:
                    break
            if len(component) > 1:
                result.append(sorted(component))

    for module in sorted(graph):
        if module not in indices:
            visit(module)
    return sorted(result)


def top_package(module: str) -> str:
    parts = module.split(".")
    return parts[1] if len(parts) > 1 else parts[0]


def package_edges(edges: Iterable[ImportEdge]) -> list[list[str]]:
    return sorted(
        {
            tuple((top_package(edge.source), top_package(edge.target)))
            for edge in edges
            if top_package(edge.source) != top_package(edge.target)
        }
    )


def bidirectional_package_edges(edges: Iterable[ImportEdge]) -> list[list[str]]:
    directed = {tuple(edge) for edge in package_edges(edges)}
    return [list(edge) for edge in sorted(directed) if edge[0] < edge[1] and edge[::-1] in directed]


def policy_violations(
    edges: Iterable[ImportEdge], root: Path = PACKAGE_ROOT
) -> dict[str, list[list[str]]]:
    pairs = {(edge.source, edge.target) for edge in edges}
    violations: dict[str, set[tuple[str, str]]] = {
        policy["id"]: set() for policy in PLANNED_POLICIES
    }
    core = {"agents", "backends", "household", "launch", "maps", "worlds"}
    forbidden_ui = {"evals", "reports", "operator_console"}
    reverse = {
        ("household", "agents"),
        ("household", "launch"),
        ("agents", "household"),
        ("agents", "launch"),
        ("agents", "operator_console"),
    }
    for source, target in pairs:
        source_package, target_package = top_package(source), top_package(target)
        if source_package in core and target_package in forbidden_ui:
            violations["core-product-inversions"].add((source, target))
        if (source_package, target_package) in reverse:
            violations["planned-reverse-package-edges"].add((source, target))
    result = {key: [list(pair) for pair in sorted(value)] for key, value in violations.items()}
    result["package-to-scripts"] = collect_script_references(root)
    return result


def build_graph_state(root: Path = PACKAGE_ROOT) -> dict:
    modules = python_modules(root)
    edges = collect_import_edges(root)
    violations = policy_violations(edges, root)
    packages = sorted({top_package(module) for module in modules})
    directed = {tuple(edge) for edge in package_edges(edges)}
    return {
        "schema": SCHEMA,
        "module_count": len(modules),
        "edge_count": len({(edge.source, edge.target) for edge in edges}),
        "module_sccs": strongly_connected_components(modules, edges),
        "package_bidirectional_edges": bidirectional_package_edges(edges),
        "allowed_package_edge_matrix": {
            package: sorted(target for target in packages if (package, target) in directed)
            for package in packages
        },
        "policies": [
            {
                **policy,
                "status": "green" if not violations[policy["id"]] else "ratcheted-known-red",
                "known_violations": violations[policy["id"]],
            }
            for policy in PLANNED_POLICIES
        ],
        "edges": [edge._asdict() for edge in edges],
    }


def compare_to_baseline(current: dict, baseline: dict) -> list[str]:
    failures: list[str] = []
    current_sccs = {tuple(item) for item in current["module_sccs"]}
    baseline_sccs = {tuple(item) for item in baseline["module_sccs"]}
    if new_sccs := sorted(current_sccs - baseline_sccs):
        failures.append(f"new architecture module SCCs: {new_sccs}")
    current_pairs = {tuple(item) for item in current["package_bidirectional_edges"]}
    baseline_pairs = {tuple(item) for item in baseline["package_bidirectional_edges"]}
    if new_pairs := sorted(current_pairs - baseline_pairs):
        failures.append(f"new bidirectional package edges: {new_pairs}")
    for source, targets in current["allowed_package_edge_matrix"].items():
        baseline_targets = baseline["allowed_package_edge_matrix"].get(source, ())
        new_targets = sorted(set(targets) - set(baseline_targets))
        if new_targets:
            failures.append(f"new package edges from {source}: {new_targets}")
    current_policies = {item["id"]: item for item in current["policies"]}
    for expected in baseline["policies"]:
        actual = current_policies[expected["id"]]
        if expected.get("status") == "green" and actual.get("status") != "green":
            failures.append(
                f"{expected['id']} status changed: green -> {actual.get('status', 'missing')}"
            )
        known = {tuple(edge) for edge in expected["known_violations"]}
        new = sorted({tuple(edge) for edge in actual["known_violations"]} - known)
        if new:
            failures.append(f"new {expected['id']} violations: {new}")
    return failures


def success_summary(state: dict) -> str:
    policy_violation_count = sum(len(policy["known_violations"]) for policy in state["policies"])
    return (
        "architecture import graph ok: "
        f"{state['module_count']} modules, {state['edge_count']} edges, "
        f"{len(state['module_sccs'])} SCCs, "
        f"{len(state['package_bidirectional_edges'])} bidirectional package pairs, "
        f"{policy_violation_count} policy violations"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record or check the roboclaws AST import graph.")
    parser.add_argument("--write", type=Path, help="Write the deterministic graph state as JSON.")
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    args = parser.parse_args(argv)
    state = build_graph_state()
    if args.write_baseline:
        args.baseline.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return 0
    if args.write:
        args.write.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.baseline.exists():
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        failures = compare_to_baseline(state, baseline)
        if failures:
            print("\n".join(failures))
            return 1
    elif not args.write:
        print(f"missing architecture baseline: {args.baseline}")
        return 1
    if not args.write:
        print(success_summary(state))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
