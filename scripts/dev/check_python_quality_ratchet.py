#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = REPO_ROOT / "scripts" / "dev" / "python_quality_baseline.json"
RUFF_COMPLEXITY_RULES = ("C901", "PLR0912", "PLR0915")
MAX_MODULE_LINES = 800
SOURCE_ROOTS = ("roboclaws", "scripts")
TEST_ROOT = "tests"
SIZE_THRESHOLDS = (500, 800, 1000)
SCHEMA = "roboclaws_python_quality_ratchet_v2"
_MEASURE_RE = re.compile(r"\((?P<value>\d+)\s*>\s*(?P<limit>\d+)\)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Ratchet Ruff complexity and Pylint-compatible too-many-lines debt "
            "against an explicit baseline."
        )
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE,
        help="Quality baseline JSON path.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--write-baseline",
        action="store_true",
        help="Replace the baseline with the current quality debt.",
    )
    mode.add_argument(
        "--summary",
        action="store_true",
        help="Print a read-only ranked quality-debt summary and exit.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Number of rows per section for --summary.",
    )
    args = parser.parse_args(argv)

    baseline_path = args.baseline if args.baseline.is_absolute() else REPO_ROOT / args.baseline
    try:
        current = collect_quality_state()
    except ValueError as exc:
        print(f"python-quality-ratchet: {exc}", file=sys.stderr)
        return 1

    if args.summary:
        print(format_quality_debt_summary(quality_debt_summary(current, top_n=args.top)))
        return 0

    if args.write_baseline:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
        try:
            display_path = baseline_path.relative_to(REPO_ROOT)
        except ValueError:
            display_path = baseline_path
        print(
            "python-quality-ratchet: wrote baseline "
            f"{display_path} "
            f"({len(current['ruff_complexity']['violations'])} Ruff violations, "
            f"{len(current['pylint_too_many_lines']['files'])} oversized modules)"
        )
        return 0

    if not baseline_path.exists():
        print(
            "python-quality-ratchet: missing baseline; run "
            f"{Path(__file__).relative_to(REPO_ROOT)} --write-baseline",
            file=sys.stderr,
        )
        return 1

    try:
        baseline = read_quality_baseline(baseline_path)
    except ValueError as exc:
        print(f"python-quality-ratchet: {exc}", file=sys.stderr)
        return 1
    failures = compare_to_baseline(current, baseline)
    if failures:
        print("python-quality-ratchet: failed", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        print(
            "Refactor the new debt, or deliberately refresh the baseline after review.",
            file=sys.stderr,
        )
        return 1

    print(
        "python-quality-ratchet: ok "
        f"({len(current['ruff_complexity']['violations'])} Ruff violations at/below baseline, "
        f"{len(current['pylint_too_many_lines']['files'])} oversized modules at/below baseline)"
    )
    return 0


def collect_quality_state() -> dict[str, Any]:
    files = tracked_python_files()
    return {
        "schema": SCHEMA,
        "generated_by": "scripts/dev/check_python_quality_ratchet.py",
        "ruff_complexity": {
            "rules": list(RUFF_COMPLEXITY_RULES),
            "violations": collect_ruff_complexity(files),
        },
        "pylint_too_many_lines": {
            "max_module_lines": MAX_MODULE_LINES,
            "files": collect_oversized_modules(files),
            "note": (
                "Pylint-compatible too-many-lines ratchet. Existing files over "
                "800 lines are baselined; new oversize files or line-count growth fail."
            ),
        },
        "repository_size": collect_repository_size(collect_scoped_file_sizes()),
    }


def read_quality_baseline(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"python quality baseline source cannot be read: {path}: {exc}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("python quality baseline source must contain valid JSON object") from exc
    if not isinstance(payload, dict):
        raise ValueError("python quality baseline source must contain a JSON object")
    return payload


def tracked_python_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--", "*.py"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    paths = []
    for line in result.stdout.splitlines():
        path = Path(line)
        if path.parts and path.parts[0] == "vendors":
            continue
        absolute_path = REPO_ROOT / path
        if not absolute_path.exists():
            continue
        paths.append(absolute_path)
    return sorted(paths)


def collect_ruff_complexity(files: list[Path]) -> list[dict[str, Any]]:
    ruff = ruff_command()
    command = [
        ruff,
        "check",
        "--select",
        ",".join(RUFF_COMPLEXITY_RULES),
        "--output-format",
        "json",
        *[str(path.relative_to(REPO_ROOT)) for path in files],
    ]
    result = subprocess.run(command, cwd=REPO_ROOT, check=False, capture_output=True, text=True)
    if result.returncode not in (0, 1):
        print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)

    diagnostics = _parse_ruff_diagnostics(result.stdout or "[]")
    symbols = SymbolIndex()
    rows: dict[str, dict[str, Any]] = {}
    for diagnostic in diagnostics:
        code = str(diagnostic.get("code") or "")
        if code not in RUFF_COMPLEXITY_RULES:
            continue
        path = Path(diagnostic["filename"]).resolve().relative_to(REPO_ROOT)
        message = str(diagnostic.get("message") or "")
        location = diagnostic.get("location") or {}
        row = int(location.get("row") or 0)
        value, limit = _measure_from_message(message)
        symbol = symbols.symbol_for(path, row)
        key = _ruff_key(path.as_posix(), code, symbol)
        current = rows.get(key)
        item = {
            "key": key,
            "path": path.as_posix(),
            "code": code,
            "symbol": symbol,
            "value": value,
            "limit": limit,
            "row": row,
            "message": message,
        }
        if current is None or int(item["value"]) > int(current["value"]):
            rows[key] = item
    return [rows[key] for key in sorted(rows)]


def _parse_ruff_diagnostics(text: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Ruff complexity diagnostics source must contain valid JSON array"
        ) from exc
    if not isinstance(payload, list):
        raise ValueError("Ruff complexity diagnostics source must contain a JSON array")
    diagnostics: list[dict[str, Any]] = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValueError(
                f"Ruff complexity diagnostics source row must contain a JSON object: row {index}"
            )
        diagnostics.append(item)
    return diagnostics


def collect_oversized_modules(files: list[Path]) -> list[dict[str, Any]]:
    file_sizes = collect_file_sizes(files)
    oversized = []
    for path, lines in file_sizes.items():
        if lines > MAX_MODULE_LINES:
            disposition = provisional_disposition(path)
            oversized.append(
                {
                    "path": path.relative_to(REPO_ROOT).as_posix(),
                    "lines": lines,
                    "max_module_lines": MAX_MODULE_LINES,
                    **disposition,
                }
            )
    return sorted(oversized, key=lambda item: item["path"])


def collect_file_sizes(files: list[Path]) -> dict[Path, int]:
    sizes: dict[Path, int] = {}
    for path in files:
        text = path.read_text(encoding="utf-8")
        sizes[path] = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
    return sizes


def collect_scoped_file_sizes() -> dict[Path, int]:
    files = [
        path
        for root in (*SOURCE_ROOTS, TEST_ROOT)
        for path in (REPO_ROOT / root).rglob("*.py")
        if path.is_file()
    ]
    return collect_file_sizes(sorted(files))


def collect_repository_size(file_sizes: dict[Path, int]) -> dict[str, Any]:
    def summarize(root_names: tuple[str, ...]) -> dict[str, Any]:
        selected = {
            path.relative_to(REPO_ROOT).as_posix(): lines
            for path, lines in file_sizes.items()
            if path.relative_to(REPO_ROOT).parts[0] in root_names
        }
        return {
            "roots": list(root_names),
            "python_files": len(selected),
            "loc": sum(selected.values()),
            "files_at_least": {
                str(threshold): sum(lines >= threshold for lines in selected.values())
                for threshold in SIZE_THRESHOLDS
            },
        }

    return {
        "line_count": "physical UTF-8 lines in Python files under the named roots",
        "source": summarize(SOURCE_ROOTS),
        "tests": summarize((TEST_ROOT,)),
    }


def provisional_disposition(path: Path) -> dict[str, str]:
    relative = path.relative_to(REPO_ROOT).as_posix()
    if relative.startswith("tests/"):
        return {
            "disposition": "SPLIT",
            "owner": "Wave 6 test topology",
            "trigger": "split with the retained behavior owner; preserve contract/privacy guards",
        }
    deletion_prefixes = ("scripts/molmo_cleanup/run_agent_sdk_perf_matrix.py",)
    if relative in deletion_prefixes:
        return {
            "disposition": "DELETE",
            "owner": "Wave 3 unconditional deletion",
            "trigger": (
                "delete after the Wave 0 caller ledger and neighboring preservation proofs pass"
            ),
        }
    if relative.startswith("scripts/maps/"):
        return {
            "disposition": "PARK",
            "owner": "Wave 5 B1 package CLI migration",
            "trigger": (
                "revisit after package-owned rebuild, digest, provenance, "
                "readiness, and product parity"
            ),
        }
    if relative.startswith("scripts/") or relative.startswith("skills/"):
        return {
            "disposition": "SPLIT",
            "owner": "Wave 5 package ownership migration",
            "trigger": (
                "move retained product behavior to its package owner and reduce the CLI adapter"
            ),
        }
    if relative in {
        "roboclaws/household/report.py",
        "roboclaws/reports/live_performance.py",
    }:
        return {
            "disposition": "MERGE",
            "owner": "Wave 6 report ownership",
            "trigger": (
                "merge duplicate projections before splitting retained renderers by behavior"
            ),
        }
    return {
        "disposition": "SPLIT",
        "owner": "Wave 6 retained owner split",
        "trigger": "split along the behavior owner named by the Wave 6 migration slice",
    }


def compare_to_baseline(current: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if baseline.get("schema") != SCHEMA:
        failures.append(f"baseline schema is {baseline.get('schema')!r}, expected {SCHEMA!r}")
        return failures

    base_ruff = {item["key"]: item for item in baseline["ruff_complexity"]["violations"]}
    for item in current["ruff_complexity"]["violations"]:
        base = base_ruff.get(item["key"])
        if base is None:
            failures.append(
                "new Ruff complexity violation "
                f"{item['path']}:{item['symbol']} {item['code']} {item['message']}"
            )
            continue
        if int(item["value"]) > int(base["value"]):
            failures.append(
                "Ruff complexity grew "
                f"{item['path']}:{item['symbol']} {item['code']} "
                f"{base['value']} -> {item['value']}"
            )

    base_modules = {
        item["path"]: int(item["lines"]) for item in baseline["pylint_too_many_lines"]["files"]
    }
    for item in current["pylint_too_many_lines"]["files"]:
        path = item["path"]
        lines = int(item["lines"])
        base_lines = base_modules.get(path)
        if base_lines is None:
            failures.append(f"new oversized module {path} has {lines} lines")
            continue
        if lines > base_lines:
            failures.append(f"oversized module grew {path} {base_lines} -> {lines} lines")

    return failures


def quality_debt_summary(state: dict[str, Any], *, top_n: int = 10) -> dict[str, Any]:
    top_limit = max(0, top_n)
    ruff_items = list(state.get("ruff_complexity", {}).get("violations") or [])
    oversized_items = list(state.get("pylint_too_many_lines", {}).get("files") or [])
    top_oversized = sorted(
        oversized_items,
        key=lambda item: (-_int_value(item.get("lines")), str(item.get("path") or "")),
    )[:top_limit]
    top_complexity = sorted(
        ruff_items,
        key=lambda item: (
            -_int_value(item.get("value")),
            str(item.get("path") or ""),
            str(item.get("symbol") or ""),
            str(item.get("code") or ""),
        ),
    )[:top_limit]

    by_file: dict[str, dict[str, Any]] = {}
    for item in ruff_items:
        path = str(item.get("path") or "<unknown>")
        value = _int_value(item.get("value"))
        limit = _int_value(item.get("limit"))
        code = str(item.get("code") or "unknown")
        bucket = by_file.setdefault(
            path,
            {
                "path": path,
                "violations": 0,
                "max_value": 0,
                "max_limit": 0,
                "codes": {},
            },
        )
        bucket["violations"] += 1
        if value > int(bucket["max_value"]):
            bucket["max_value"] = value
            bucket["max_limit"] = limit
        bucket["codes"][code] = int(bucket["codes"].get(code, 0)) + 1

    complexity_by_file = [
        {
            "path": str(bucket["path"]),
            "violations": int(bucket["violations"]),
            "max_value": int(bucket["max_value"]),
            "max_limit": int(bucket["max_limit"]),
            "codes": [
                {"code": code, "count": count} for code, count in sorted(bucket["codes"].items())
            ],
        }
        for bucket in by_file.values()
    ]
    complexity_by_file.sort(
        key=lambda item: (
            -int(item["violations"]),
            -int(item["max_value"]),
            str(item["path"]),
        )
    )

    return {
        "ruff_total": len(ruff_items),
        "oversized_total": len(oversized_items),
        "top_oversized_modules": top_oversized,
        "top_complexity_entries": top_complexity,
        "complexity_by_file": complexity_by_file[:top_limit],
    }


def format_quality_debt_summary(summary: dict[str, Any]) -> str:
    lines = [
        "python-quality-ratchet: summary",
        f"- Ruff complexity violations: {summary['ruff_total']}",
        f"- oversized modules: {summary['oversized_total']}",
        "",
        "Top oversized modules:",
    ]
    top_oversized = list(summary.get("top_oversized_modules") or [])
    if top_oversized:
        for item in top_oversized:
            lines.append(f"- {_int_value(item.get('lines'))} lines {item.get('path')}")
    else:
        lines.append("- none")

    lines.extend(["", "Highest complexity entries:"])
    top_complexity = list(summary.get("top_complexity_entries") or [])
    if top_complexity:
        for item in top_complexity:
            lines.append(
                "- "
                f"{_measure_text(item)} "
                f"{item.get('code')} {item.get('path')}::{item.get('symbol')}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "Complexity by file:"])
    complexity_by_file = list(summary.get("complexity_by_file") or [])
    if complexity_by_file:
        for item in complexity_by_file:
            codes = ", ".join(f"{code['code']}:{code['count']}" for code in item.get("codes") or [])
            suffix = f"; {codes}" if codes else ""
            lines.append(
                "- "
                f"{item['violations']} violations {item['path']} "
                f"(max {_measure_text(item)}{suffix})"
            )
    else:
        lines.append("- none")
    return "\n".join(lines)


def ruff_command() -> str:
    override = os.environ.get("ROBOCLAWS_RUFF")
    if override:
        return override
    local = REPO_ROOT / ".venv" / "bin" / "ruff"
    if local.exists():
        return str(local)
    return "ruff"


def _measure_from_message(message: str) -> tuple[int, int]:
    match = _MEASURE_RE.search(message)
    if not match:
        return 1, 0
    return int(match.group("value")), int(match.group("limit"))


def _ruff_key(path: str, code: str, symbol: str) -> str:
    return f"{path}|{code}|{symbol}"


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _measure_text(item: dict[str, Any]) -> str:
    value = _int_value(item.get("value", item.get("max_value")))
    limit = _int_value(item.get("limit", item.get("max_limit")))
    if limit:
        return f"{value}>{limit}"
    return str(value)


class SymbolIndex:
    def __init__(self) -> None:
        self._cache: dict[Path, list[tuple[int, int, str]]] = {}

    def symbol_for(self, path: Path, row: int) -> str:
        spans = self._cache.setdefault(path, self._load(path))
        matches = [span for span in spans if span[0] <= row <= span[1]]
        if not matches:
            return f"line:{row}"
        return max(matches, key=lambda span: span[0])[2]

    def _load(self, path: Path) -> list[tuple[int, int, str]]:
        source_path = REPO_ROOT / path
        try:
            tree = ast.parse(source_path.read_text(encoding="utf-8"))
        except SyntaxError:
            return []
        spans: list[tuple[int, int, str]] = []

        def visit(node: ast.AST, parents: list[str]) -> None:
            name = getattr(node, "name", None)
            is_named_scope = isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            next_parents = parents
            if is_named_scope and isinstance(name, str):
                next_parents = [*parents, name]
                spans.append(
                    (
                        int(getattr(node, "lineno", 0)),
                        int(getattr(node, "end_lineno", getattr(node, "lineno", 0))),
                        ".".join(next_parents),
                    )
                )
            for child in ast.iter_child_nodes(node):
                visit(child, next_parents)

        visit(tree, [])
        return spans


if __name__ == "__main__":
    raise SystemExit(main())
