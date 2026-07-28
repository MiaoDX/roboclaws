#!/usr/bin/env python3
"""Reject generic private-environment data from tracked public text files."""

from __future__ import annotations

import argparse
import ipaddress
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    rule: str
    value: str


IPV4_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
HOME_RE = re.compile(r"(?<![\w.-])(?:/home/([A-Za-z0-9._-]+)|/Users/([A-Za-z0-9._-]+))")
WINDOWS_HOME_RE = re.compile(r"(?i)(?<![\w.-])[A-Z]:\\Users\\([A-Za-z0-9._-]+)")
PRIVATE_GIT_RE = re.compile(r"(?:ssh|git)://[^\s'\"<>]+|\bgit@[^\s:'\"<>]+:[^\s'\"<>]+")
CREDENTIAL_RE = re.compile(
    r"(?m)^[ \t]*(?:export[ \t]+)?([A-Z][A-Z0-9_]*)[ \t]*[:=][ \t]*([^\s#]*)"
)
PLACEHOLDER_USERS = {"example", "node", "runner", "user", "username"}
PLACEHOLDER_PREFIXES = (
    "$",
    "<",
    "fake",
    "test",
    "demo",
    "example",
    "placeholder",
    "changeme",
    "redacted",
    "from-file",
    "xxx",
)


def _tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [root / Path(raw.decode()) for raw in result.stdout.split(b"\0") if raw]


def _text(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except (FileNotFoundError, IsADirectoryError):
        return None
    if b"\0" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _is_private_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    private_networks = (
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
    )
    return address.version == 4 and any(address in network for network in private_networks)


def _is_credential_name(value: str) -> bool:
    return value.endswith("_API_KEY") or any(
        component in {"PASSWORD", "SECRET", "TOKEN"} for component in value.split("_")
    )


def _credential_is_placeholder(value: str) -> bool:
    normalized = value.strip("'\"").lower()
    return not normalized or normalized.startswith(PLACEHOLDER_PREFIXES)


def _private_ip_findings(path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for match in IPV4_RE.finditer(text):
        value = match.group(0)
        if _is_private_ip(value):
            findings.append(Finding(path, _line_number(text, match.start()), "private-ip", value))
    return findings


def _home_path_findings(path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for match in HOME_RE.finditer(text):
        user = match.group(1) or match.group(2) or ""
        if user.lower() not in PLACEHOLDER_USERS:
            findings.append(
                Finding(path, _line_number(text, match.start()), "absolute-home", match.group(0))
            )
    for match in WINDOWS_HOME_RE.finditer(text):
        if match.group(1).lower() not in PLACEHOLDER_USERS:
            findings.append(
                Finding(path, _line_number(text, match.start()), "absolute-home", match.group(0))
            )
    return findings


def _private_git_findings(path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for match in PRIVATE_GIT_RE.finditer(text):
        findings.append(
            Finding(path, _line_number(text, match.start()), "private-git-protocol", match.group(0))
        )
    return findings


def _credential_findings(path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for match in CREDENTIAL_RE.finditer(text):
        if _is_credential_name(match.group(1)) and not _credential_is_placeholder(match.group(2)):
            findings.append(
                Finding(
                    path,
                    _line_number(text, match.start()),
                    "credential-assignment",
                    f"{match.group(1)}=<redacted>",
                )
            )
    return findings


def scan_file(root: Path, path: Path) -> list[Finding]:
    text = _text(path)
    if text is None:
        return []
    relative = path.relative_to(root)
    return [
        *_private_ip_findings(relative, text),
        *_home_path_findings(relative, text),
        *_private_git_findings(relative, text),
        *_credential_findings(relative, text),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()

    findings = [finding for path in _tracked_files(root) for finding in scan_file(root, path)]
    for finding in findings:
        print(f"{finding.path}:{finding.line}: {finding.rule}: <redacted>")
    if findings:
        print(f"public-surface check failed: {len(findings)} finding(s)")
        return 1
    print("public-surface check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
