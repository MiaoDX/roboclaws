from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKER = REPO_ROOT / "scripts" / "dev" / "check_public_surface.py"


def _run_checker(tmp_path: Path, content: str) -> subprocess.CompletedProcess[str]:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "sample.txt").write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "sample.txt"], cwd=tmp_path, check=True)
    return subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_rejects_generic_private_surface_values(tmp_path: Path) -> None:
    private_ip = "10" + ".42.1.9"
    home_path = "/home/" + "private-owner/work"
    git_url = "git" + "@private.example:team/repo.git"
    credential = "SERVICE_API_KEY=" + "real-looking-value"

    result = _run_checker(tmp_path, "\n".join((private_ip, home_path, git_url, credential)))

    assert result.returncode == 1
    assert "private-ip" in result.stdout
    assert "absolute-home" in result.stdout
    assert "private-git-protocol" in result.stdout
    assert "credential-assignment" in result.stdout
    assert private_ip not in result.stdout
    assert "private-owner" not in result.stdout
    assert "private.example" not in result.stdout
    assert "real-looking-value" not in result.stdout


def test_allows_public_urls_placeholders_and_test_credentials(tmp_path: Path) -> None:
    content = "\n".join(
        (
            "https://github.com/example/project.git",
            "/home/user/project",
            "127.0.0.1",
            "SERVICE_API_KEY=",
            "OTHER_TOKEN=fake-test-token",
            'PASSWORD="${PASSWORD:-}"',
        )
    )

    result = _run_checker(tmp_path, content)

    assert result.returncode == 0
    assert result.stdout.strip() == "public-surface check passed"


def test_rejects_a_root_that_is_not_a_git_worktree(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stdout.strip() == "public-surface check failed: root is not a Git worktree"


def test_rejects_an_empty_git_worktree(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    result = subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stdout.strip() == (
        "public-surface check failed: Git worktree has no tracked files"
    )
