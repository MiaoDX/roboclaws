"""Credential-scrubbed malicious probe for MCP behavior candidate placement."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROBE_SCHEMA = "candidate_isolation_probe_manifest_v1"
RESULT_SCHEMA = "candidate_isolation_probe_result_v1"
SUPERVISOR_RESULT_SCHEMA = "candidate_isolation_supervisor_result_v1"
ATTESTATION_SCHEMA = "candidate_isolation_attestation_v1"
_SENSITIVE_TOKENS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
_EXPECTED_PROVIDER_ENV = (
    "ANTHROPIC_API_KEY",
    "CODEX_RESPONSES_API_KEY",
    "KIMI_API_KEY",
    "MIMO_RESPONSES_API_KEY",
    "MM_API_KEY",
    "OPENAI_API_KEY",
)
_PLACEMENTS = frozenset({"local-docker", "cloudml-native-container"})
_RESULT_CHECKS = frozenset(
    {
        "approved_output_write",
        "expected_environment_absent",
        "forbidden_paths_unreadable",
        "forbidden_writes_denied",
        "network_denied",
        "path_traversal_denied",
        "sensitive_environment_absent",
        "subprocess_private_read_denied",
        "symlink_denied",
    }
)


@dataclass(frozen=True)
class ProbeManifest:
    approved_read_roots: tuple[Path, ...]
    output_root: Path
    forbidden_paths: tuple[Path, ...]
    network_targets: tuple[tuple[str, int], ...]
    expected_env_absent: tuple[str, ...]

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "ProbeManifest":
        if payload.get("schema") != PROBE_SCHEMA:
            raise ValueError(f"schema must be {PROBE_SCHEMA}")
        required = {
            "schema",
            "approved_read_roots",
            "output_root",
            "forbidden_paths",
            "network_targets",
            "expected_env_absent",
        }
        if set(payload) != required:
            raise ValueError("probe manifest fields must be exact")

        output_root = Path(payload["output_root"])
        if not output_root.is_absolute():
            raise ValueError("output_root must be absolute")
        approved = _absolute_paths(payload, "approved_read_roots")
        forbidden = _absolute_paths(payload, "forbidden_paths")
        if any(path == output_root or output_root in path.parents for path in forbidden):
            raise ValueError("output_root must not be a forbidden path")
        return cls(
            approved,
            output_root,
            forbidden,
            _network_targets(payload["network_targets"]),
            _string_list(payload, "expected_env_absent"),
        )


@dataclass(frozen=True)
class IsolationAttestation:
    payload: dict[str, Any]
    result: dict[str, Any]

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(self.payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def summary(self) -> dict[str, Any]:
        return {
            "schema": ATTESTATION_SCHEMA,
            "task_id": self.payload["task_id"],
            "image_digest": self.payload["image_digest"],
            "probe_source_sha256": self.payload["probe_source_sha256"],
            "placement": self.payload["placement"],
            "result_sha256": self.payload["result_sha256"],
            "verdict": self.payload["verdict"],
        }


def load_isolation_attestation(path: Path, *, expected_sha256: str) -> IsolationAttestation:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("candidate isolation attestation digest mismatch")
    payload = json.loads(raw)
    required = {
        "schema",
        "task_id",
        "image_digest",
        "probe_source_sha256",
        "code_commit",
        "placement",
        "result_path",
        "result_sha256",
        "collected_at",
        "verdict",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("candidate isolation attestation fields must be exact")
    if payload.get("schema") != ATTESTATION_SCHEMA:
        raise ValueError(f"candidate isolation attestation schema must be {ATTESTATION_SCHEMA}")
    for key in ("image_digest", "probe_source_sha256", "result_sha256"):
        _require_sha256(str(payload.get(key) or ""), key, allow_prefix=key == "image_digest")
    _require_sha256(str(payload.get("code_commit") or ""), "code_commit", length=40)
    if payload.get("placement") not in _PLACEMENTS:
        raise ValueError("candidate isolation attestation placement is unsupported")
    if payload.get("verdict") != "passed":
        raise ValueError("candidate isolation attestation verdict must be passed")
    result_ref = Path(str(payload.get("result_path") or ""))
    if result_ref.is_absolute() or ".." in result_ref.parts:
        raise ValueError("candidate isolation result path must be relative and traversal-free")
    result_path = path.parent / result_ref
    if result_path.is_symlink() or not result_path.is_file():
        raise ValueError("candidate isolation result must be a regular non-symlink file")
    result_raw = result_path.read_bytes()
    if hashlib.sha256(result_raw).hexdigest() != payload["result_sha256"]:
        raise ValueError("candidate isolation result digest mismatch")
    result = json.loads(result_raw)
    validate_supervisor_result(
        result,
        expected_placement=str(payload["placement"]),
        expected_source_sha256=str(payload["probe_source_sha256"]),
    )
    return IsolationAttestation(dict(payload), result)


def validate_supervisor_result(
    payload: Any,
    *,
    expected_placement: str,
    expected_source_sha256: str,
) -> None:
    if not isinstance(payload, dict) or payload.get("schema") != SUPERVISOR_RESULT_SCHEMA:
        raise ValueError("candidate isolation supervisor result schema mismatch")
    if payload.get("ok") is not True or payload.get("status") != "passed":
        raise ValueError("candidate isolation supervisor result did not pass")
    _validate_supervisor_identity(
        payload,
        expected_placement=expected_placement,
        expected_source_sha256=expected_source_sha256,
    )
    _validate_child_result(payload.get("child_result"))


def _validate_supervisor_identity(
    payload: dict[str, Any], *, expected_placement: str, expected_source_sha256: str
) -> None:
    if payload.get("placement") != expected_placement:
        raise ValueError("candidate isolation placement mismatch")
    if payload.get("candidate_script_sha256") != expected_source_sha256:
        raise ValueError("candidate isolation source digest mismatch")
    if payload.get("candidate_uid") != 65534 or payload.get("candidate_gid") != 65534:
        raise ValueError("candidate isolation UID/GID mismatch")
    if payload.get("candidate_environment_keys") != ["LANG", "LC_ALL", "PATH"]:
        raise ValueError("candidate isolation environment surface mismatch")
    if payload.get("candidate_bundle_entries") != [
        "candidate-isolation-probe.py",
        "probe-manifest.json",
    ]:
        raise ValueError("candidate isolation bundle surface mismatch")


def _validate_child_result(child: Any) -> None:
    if not isinstance(child, dict) or child.get("schema") != RESULT_SCHEMA:
        raise ValueError("candidate isolation child result schema mismatch")
    checks = child.get("checks")
    if not isinstance(checks, dict) or set(checks) != _RESULT_CHECKS:
        raise ValueError("candidate isolation check set mismatch")
    if not all(value is True for value in checks.values()):
        raise ValueError("candidate isolation denial check failed")
    if child.get("environment_keys") != ["LANG", "LC_ALL", "PATH"]:
        raise ValueError("candidate child environment surface mismatch")
    if child.get("sensitive_environment_keys") != []:
        raise ValueError("candidate child received sensitive environment")
    if child.get("forbidden_path_count") != 8:
        raise ValueError("candidate isolation forbidden target count mismatch")


def _require_sha256(value: str, name: str, *, allow_prefix: bool = False, length: int = 64) -> None:
    candidate = value.removeprefix("sha256:") if allow_prefix else value
    if len(candidate) != length or any(
        character not in "0123456789abcdef" for character in candidate
    ):
        raise ValueError(f"{name} must be a lowercase hexadecimal digest")


def _string_list(payload: dict[str, Any], name: str) -> tuple[str, ...]:
    values = payload[name]
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ValueError(f"{name} must be a string list")
    return tuple(values)


def _absolute_paths(payload: dict[str, Any], name: str) -> tuple[Path, ...]:
    paths = tuple(Path(value) for value in _string_list(payload, name))
    if any(not path.is_absolute() for path in paths):
        raise ValueError(f"{name} entries must be absolute")
    return paths


def _network_targets(values: Any) -> tuple[tuple[str, int], ...]:
    if not isinstance(values, list):
        raise ValueError("network_targets must be a list")
    targets: list[tuple[str, int]] = []
    for target in values:
        if not isinstance(target, dict) or set(target) != {"host", "port"}:
            raise ValueError("network target fields must be exact")
        host, port = target["host"], target["port"]
        if not isinstance(host, str) or not isinstance(port, int) or not 0 < port < 65536:
            raise ValueError("network target must contain a valid host and port")
        targets.append((host, port))
    return tuple(targets)


def _digest_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except (OSError, ValueError):
        return None


def _read_forbidden(path: Path) -> bool:
    try:
        if path.is_dir():
            next(path.iterdir())
        else:
            path.read_bytes()
        return True
    except (OSError, ValueError, StopIteration):
        return False


def _write_forbidden(path: Path) -> bool:
    try:
        path.write_text("candidate-isolation-probe", encoding="utf-8")
        return True
    except (OSError, ValueError):
        return False


def _subprocess_read(path: Path) -> bool:
    code = "from pathlib import Path; Path(__import__('sys').argv[1]).read_bytes()"
    try:
        completed = subprocess.run(
            [sys.executable, "-c", code, str(path)],
            capture_output=True,
            check=False,
            timeout=3,
        )
        return completed.returncode == 0
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def _path_attempt_id(index: int, path: Path) -> str:
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]
    return f"forbidden-{index:02d}-{digest}"


def run_probe(manifest: ProbeManifest) -> dict[str, Any]:
    """Run only deny-oriented checks and never include private values in output."""
    env_keys = sorted(os.environ)
    sensitive_env_keys = [
        key for key in env_keys if any(token in key.upper() for token in _SENSITIVE_TOKENS)
    ]
    expected_absent = [key for key in manifest.expected_env_absent if key in os.environ]

    forbidden = [
        (_path_attempt_id(index, path), path) for index, path in enumerate(manifest.forbidden_paths)
    ]
    forbidden_read = {attempt: _read_forbidden(path) for attempt, path in forbidden}
    traversal_read = {
        f"approved-{root_index:02d}:{attempt}": _read_forbidden(root / os.path.relpath(path, root))
        for root_index, root in enumerate(manifest.approved_read_roots)
        for attempt, path in forbidden
    }
    symlink_read: dict[str, bool] = {}
    symlink_root = manifest.output_root / ".candidate-isolation-probe-links"
    try:
        symlink_root.mkdir(parents=True, exist_ok=True)
        for index, (attempt, path) in enumerate(forbidden):
            link = symlink_root / str(index)
            link.symlink_to(path)
            symlink_read[attempt] = _read_forbidden(link)
            link.unlink(missing_ok=True)
    except (OSError, ValueError):
        symlink_read.setdefault("probe-error", False)
    finally:
        try:
            symlink_root.rmdir()
        except OSError:
            pass
    subprocess_read = {attempt: _subprocess_read(path) for attempt, path in forbidden}
    forbidden_write = {attempt: _write_forbidden(path) for attempt, path in forbidden}
    network = {}
    for host, port in manifest.network_targets:
        key = f"{host}:{port}"
        try:
            with socket.create_connection((host, port), timeout=2):
                network[key] = True
        except (OSError, ValueError):
            network[key] = False

    manifest.output_root.mkdir(parents=True, exist_ok=True)
    marker = manifest.output_root / ".candidate-isolation-probe-write"
    try:
        marker.write_text("ok\n", encoding="utf-8")
        output_write = marker.read_text(encoding="utf-8") == "ok\n"
        marker.unlink(missing_ok=True)
    except (OSError, ValueError):
        output_write = False

    checks = {
        "sensitive_environment_absent": not sensitive_env_keys,
        "expected_environment_absent": not expected_absent,
        "forbidden_paths_unreadable": not any(forbidden_read.values()),
        "path_traversal_denied": not any(traversal_read.values()),
        "symlink_denied": not any(symlink_read.values()),
        "subprocess_private_read_denied": not any(subprocess_read.values()),
        "forbidden_writes_denied": not any(forbidden_write.values()),
        "network_denied": not any(network.values()),
        "approved_output_write": output_write,
    }
    return {
        "schema": RESULT_SCHEMA,
        "probe_manifest_schema": PROBE_SCHEMA,
        "ok": all(checks.values()),
        "checks": checks,
        "environment_keys": env_keys,
        "sensitive_environment_keys": sensitive_env_keys,
        "forbidden_read_attempts": forbidden_read,
        "path_traversal_attempts": traversal_read,
        "symlink_attempts": symlink_read,
        "subprocess_read_attempts": subprocess_read,
        "forbidden_write_attempts": forbidden_write,
        "network_attempts": network,
        "approved_read_root_count": len(manifest.approved_read_roots),
        "output_root_sha256": hashlib.sha256(str(manifest.output_root).encode("utf-8")).hexdigest(),
        "forbidden_path_count": len(manifest.forbidden_paths),
    }


def _demote_candidate() -> None:
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)


def run_supervised_probe(*, work_root: Path, durable_output: Path) -> dict[str, Any]:
    """Run the malicious probe as an untrusted UID and persist only as supervisor."""
    if os.geteuid() != 0:
        return {
            "schema": SUPERVISOR_RESULT_SCHEMA,
            "ok": False,
            "status": "blocked",
            "reason": "supervisor_requires_root_for_uid_isolation",
        }
    placement = os.environ.get("ROBOCLAWS_ISOLATION_PLACEMENT", "local-docker")
    if placement not in _PLACEMENTS:
        raise ValueError(f"unsupported isolation placement: {placement}")
    work_root = work_root.resolve()
    durable_output = durable_output.resolve()
    approved_root = work_root / "candidate-public"
    scratch_root = work_root / "candidate-scratch"
    trusted_root = work_root / "trusted-private"
    manifest_path = approved_root / "probe-manifest.json"
    candidate_script = approved_root / "candidate-isolation-probe.py"
    candidate_result = scratch_root / "result.json"
    sentinel_paths = (
        trusted_root / "provider.env",
        trusted_root / "sealed-holdout.json",
        trusted_root / "private-evaluator.json",
        Path(f"/proc/{os.getpid()}/environ"),
        durable_output.parent / "candidate-write.json",
        Path("/workspace/private-truth.json"),
        Path("/output/eval-harness/private-truth.json"),
        Path("/mnt/cloudml/input/private-evaluator.json"),
    )

    approved_root.mkdir(parents=True, exist_ok=False)
    scratch_root.mkdir(parents=True, exist_ok=False)
    trusted_root.mkdir(parents=True, exist_ok=False)
    durable_output.parent.mkdir(parents=True, exist_ok=True)
    for path, content in (
        (sentinel_paths[0], "OPENAI_API_KEY=private-sentinel\n"),
        (sentinel_paths[1], '{"holdout":"private-sentinel"}\n'),
        (sentinel_paths[2], '{"grader":"private-sentinel"}\n'),
    ):
        path.write_text(content, encoding="utf-8")
        path.chmod(0o600)
    trusted_root.chmod(0o700)
    durable_output.parent.chmod(0o700)
    scratch_root.chmod(0o700)
    os.chown(scratch_root, 65534, 65534)
    shutil.copyfile(Path(__file__).resolve(), candidate_script)
    candidate_script.chmod(0o444)

    manifest_payload = {
        "schema": PROBE_SCHEMA,
        "approved_read_roots": [str(approved_root)],
        "output_root": str(scratch_root),
        "forbidden_paths": [str(path) for path in sentinel_paths],
        "network_targets": [
            {"host": "1.1.1.1", "port": 53},
            {"host": "169.254.169.254", "port": 80},
        ],
        "expected_env_absent": list(_EXPECTED_PROVIDER_ENV),
    }
    manifest_bytes = (json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n").encode()
    manifest_path.write_bytes(manifest_bytes)
    manifest_path.chmod(0o444)
    approved_root.chmod(0o555)
    candidate_env = {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
    }
    completed = subprocess.run(
        [
            sys.executable,
            str(candidate_script),
            "--manifest",
            str(manifest_path),
            "--output",
            str(candidate_result),
        ],
        cwd=approved_root,
        env=candidate_env,
        capture_output=True,
        check=False,
        timeout=30,
        preexec_fn=_demote_candidate,
    )
    try:
        child_result = json.loads(candidate_result.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        child_result = None
    child_ok = bool(
        completed.returncode == 0
        and isinstance(child_result, dict)
        and child_result.get("schema") == RESULT_SCHEMA
        and child_result.get("ok") is True
    )
    result = {
        "schema": SUPERVISOR_RESULT_SCHEMA,
        "ok": child_ok,
        "status": "passed" if child_ok else "failed",
        "placement": placement,
        "candidate_uid": 65534,
        "candidate_gid": 65534,
        "candidate_environment_keys": sorted(candidate_env),
        "candidate_bundle_entries": sorted(path.name for path in approved_root.iterdir()),
        "candidate_script_sha256": _digest_file(candidate_script),
        "probe_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "child_returncode": completed.returncode,
        "child_result": child_result,
    }
    durable_output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--supervised-work-root", type=Path)
    parser.add_argument("--supervised-output", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    supervised = args.supervised_work_root is not None or args.supervised_output is not None
    if supervised:
        if args.supervised_work_root is None or args.supervised_output is None:
            raise ValueError("supervised mode requires work root and output")
        if args.manifest is not None or args.output is not None:
            raise ValueError("supervised mode does not accept child manifest arguments")
        result = run_supervised_probe(
            work_root=args.supervised_work_root,
            durable_output=args.supervised_output,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["ok"] else 1
    if args.manifest is None or args.output is None:
        raise ValueError("child mode requires --manifest and --output")
    manifest = ProbeManifest.from_mapping(json.loads(args.manifest.read_text(encoding="utf-8")))
    result = run_probe(manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
