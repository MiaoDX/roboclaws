from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.regression

REPO_ROOT = Path(__file__).resolve().parents[3]

ACTIVE_SEARCH_ROOTS = (
    ".github",
    "README.md",
    "docs/ai/openclaw",
    "docs/human",
    "docs/troubleshooting",
    "examples",
    "just",
    "roboclaws",
    "scripts",
    "skills",
    "tests",
)
ALLOWED_HISTORICAL_PATHS = {
    "docs/human/model-matrix.md",
    "docs/human/molmospaces-visual-grounding-results.md",
}
FORBIDDEN_ACTIVE_PATTERNS = (
    "mimo-v2-" + "omni",
    "xiaomi/mimo-v2-" + "omni",
    "mimo-" + "omni",
    "MiMo v2 " + "Omni",
    "MiMo V2 " + "Omni",
    "claude-mimo-" + "omni",
    "mify-" + "omni",
    "probe_mify_" + "omni",
    "mimo_" + "omni",
    "mimo_v2_" + "omni",
)


def test_active_mimo_references_do_not_use_deprecated_omni_ids() -> None:
    offenders = _find_forbidden_active_references()
    assert offenders == []


# --- retired text-bridge removal guard (2026-06-04) -------------------------
#
# The repo removed the text-bridge foundation (roboclaws/mcp/text_bridge.py and
# its test). MiMo v2.5 Pro is now supported directly through the mify Responses
# route and does not require that bridge. This guard only prevents the retired
# bridge symbols from returning on executable surfaces.
#
# Docs and historical archives are out of scope because they record route
# history rather than executable compatibility behavior.
EXECUTABLE_SEARCH_ROOTS = (
    ".github",
    "examples",
    "just",
    "roboclaws",
    "scripts",
    "skills",
    "tests",
)
_GUARD_RELPATH = "tests/contract/regression/test_mimo_v25_migration_guard.py"
FORBIDDEN_PRO_TEXTBRIDGE_PATTERNS = (
    "text_" + "bridge",
    "Vision" + "Bridge",
    "resolve_observe_" + "delivery",
    "vision_" + "bridge",
)


def test_executable_surfaces_do_not_resurrect_text_bridge() -> None:
    offenders = _find_forbidden_pro_textbridge_references()
    assert offenders == []


def _find_forbidden_pro_textbridge_references() -> list[str]:
    offenders = []
    for root in EXECUTABLE_SEARCH_ROOTS:
        path = REPO_ROOT / root
        if not path.exists():
            continue
        paths = path.rglob("*") if path.is_dir() else (path,)
        for candidate in paths:
            if not candidate.is_file() or _is_excluded(candidate):
                continue
            relpath = candidate.relative_to(REPO_ROOT).as_posix()
            if relpath == _GUARD_RELPATH:
                continue
            try:
                lines = candidate.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for line_number, line in enumerate(lines, start=1):
                if any(pattern in line for pattern in FORBIDDEN_PRO_TEXTBRIDGE_PATTERNS):
                    offenders.append(f"{relpath}:{line_number}:{line}")
    return offenders


def _find_forbidden_active_references() -> list[str]:
    offenders = []
    for root in ACTIVE_SEARCH_ROOTS:
        path = REPO_ROOT / root
        if not path.exists():
            continue
        paths = path.rglob("*") if path.is_dir() else (path,)
        for candidate in paths:
            if not candidate.is_file() or _is_excluded(candidate):
                continue
            relpath = candidate.relative_to(REPO_ROOT).as_posix()
            if relpath in ALLOWED_HISTORICAL_PATHS:
                continue
            try:
                lines = candidate.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for line_number, line in enumerate(lines, start=1):
                if any(pattern in line for pattern in FORBIDDEN_ACTIVE_PATTERNS):
                    offenders.append(f"{relpath}:{line_number}:{line}")
    return offenders


def _is_excluded(path: Path) -> bool:
    relpath = path.relative_to(REPO_ROOT).as_posix()
    excluded_prefixes = (
        "docs/retrospectives/",
        "docs/plans/",
        "docs/status/",
        "output/",
        "vendors/",
    )
    return relpath.startswith(excluded_prefixes) or "__pycache__/" in relpath
