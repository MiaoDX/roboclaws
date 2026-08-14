from __future__ import annotations

import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ACTIVE_STATUS_ROOT = REPO_ROOT / "docs" / "status" / "active"
CURRENT_DOCS = (
    REPO_ROOT / "README.md",
    REPO_ROOT / "ARCHITECTURE.md",
    REPO_ROOT / "docs" / "agents" / "operating-runbook.md",
    REPO_ROOT / "docs" / "human" / "contributing.md",
    REPO_ROOT / "just" / "README.md",
)
TERMINAL_STATUS = re.compile(r"(?im)^status:\s*(?:done|complete|completed)\s*$")


def test_active_markdown_capsules_are_not_terminal() -> None:
    terminal = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in ACTIVE_STATUS_ROOT.glob("*.md")
        if TERMINAL_STATUS.search(path.read_text(encoding="utf-8"))
    ]

    assert terminal == []


def test_current_sdk_command_lines_select_a_provider_profile() -> None:
    missing_profile: list[str] = []
    for path in CURRENT_DOCS:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "just run::surface" not in line or "agent_engine=openai-agents-sdk" not in line:
                continue
            if "provider_profile=" not in line:
                missing_profile.append(f"{path.relative_to(REPO_ROOT)}:{line_number}")

    assert missing_profile == []


def test_product_cli_rejects_repo_only_eval_aliases() -> None:
    for args in (("eval",), ("agent", "eval")):
        result = subprocess.run(
            [sys.executable, "-m", "roboclaws.cli.main", *args],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        assert "eval" not in result.stdout


def test_product_packages_do_not_import_repo_evals() -> None:
    product_sources = [
        path
        for path in (REPO_ROOT / "roboclaws").rglob("*.py")
        if "evals" not in path.relative_to(REPO_ROOT / "roboclaws").parts
    ]
    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in product_sources
        if "roboclaws.evals" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []


def test_built_distributions_exclude_repo_eval_surfaces(tmp_path: Path) -> None:
    subprocess.run(
        ["uv", "build", "--out-dir", str(tmp_path)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(tmp_path.glob("*.whl"))
    sdist = next(tmp_path.glob("*.tar.gz"))
    with zipfile.ZipFile(wheel) as archive:
        wheel_paths = archive.namelist()
    with tarfile.open(sdist) as archive:
        sdist_paths = archive.getnames()

    for paths in (wheel_paths, sdist_paths):
        assert not any("roboclaws/evals/" in path for path in paths)
        assert not any("evals/household_world/" in path for path in paths)
        assert not any("skills/eval-harness/" in path for path in paths)


def test_product_runtime_does_not_depend_on_script_modules() -> None:
    product_hits: list[str] = []
    for path in (REPO_ROOT / "roboclaws").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "from scripts." in text or "import scripts." in text:
            product_hits.append(path.relative_to(REPO_ROOT).as_posix())
    assert product_hits == []
