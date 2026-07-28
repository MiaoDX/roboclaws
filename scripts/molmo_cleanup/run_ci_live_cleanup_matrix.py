#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from roboclaws.core.rerun import shell_join  # noqa: E402
from roboclaws.household.ci_live_reports import (  # noqa: E402
    MODEL_ENTRIES,
    MolmoLiveModelEntry,
    base_status,
    diagnostic_path_for_entry,
    entry_by_name,
    entry_names,
    latest_seed_artifact_dir,
    latest_seed_run_dir,
    publish_diagnostic_seed_run,
    publish_seed_run,
    report_path_for_entry,
    status_path_for_entry,
    utc_timestamp,
    write_manifest,
    write_status,
)
from roboclaws.household.realworld_contract import DEFAULT_REALWORLD_TASK  # noqa: E402

PROVIDER_TIMING_PROXY_ENV = "ROBOCLAWS_PROVIDER_TIMING_PROXY"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run or rehearse the opt-in Molmo live CI cleanup matrix."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--entry", choices=entry_names())
    group.add_argument("--all", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("output/molmo/ci-live"))
    parser.add_argument("--published-dir", type=Path)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--generated-mess-count",
        type=int,
        default=None,
        help="Generated mess count override. Defaults to 5 for world-public-labels entries.",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="Override the cleanup profile declared by the selected live entry.",
    )
    parser.add_argument("--task", default=DEFAULT_REALWORLD_TASK)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18788)
    parser.add_argument("--uv-bin", default="uv")
    parser.add_argument("--just-bin", default="just")
    parser.add_argument("--python-bin", default=".venv/bin/python")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-uv-sync", action="store_true")
    parser.add_argument("--skip-prewarm", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    entries = _selected_entries(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    publish_root = args.published_dir or args.output_dir / "published"
    publish_root.mkdir(parents=True, exist_ok=True)

    preflight_statuses = _run_preflight_or_statuses(entries, args, publish_root)
    if preflight_statuses is not None:
        write_manifest(publish_root, preflight_statuses)
        return 1

    statuses, failure_count = _run_entries(entries, args, publish_root)
    write_manifest(publish_root, statuses)
    if failure_count:
        return 1
    return 0


def _selected_entries(args: argparse.Namespace) -> tuple[MolmoLiveModelEntry, ...]:
    return MODEL_ENTRIES if args.all else (entry_by_name(args.entry),)


def _run_preflight_or_statuses(
    entries: tuple[MolmoLiveModelEntry, ...],
    args: argparse.Namespace,
    publish_root: Path,
) -> list[dict[str, Any]] | None:
    if args.dry_run or not _any_entry_has_secret(entries):
        return None
    try:
        if not args.skip_uv_sync:
            _run_checked([args.uv_bin, "sync", "--extra", "dev", "--extra", "molmospaces"])
        if not args.skip_prewarm:
            _prewarm(args, generated_mess_count=_prewarm_generated_mess_count(entries, args))
    except Exception as exc:
        return [
            _preflight_failed_status(entry, args, publish_root, reason=str(exc))
            for entry in entries
        ]
    return None


def _preflight_failed_status(
    entry: MolmoLiveModelEntry,
    args: argparse.Namespace,
    publish_root: Path,
    *,
    reason: str,
) -> dict[str, Any]:
    status = base_status(
        entry,
        seed=args.seed,
        generated_mess_count=_entry_generated_mess_count(entry, args),
        profile=_entry_profile(entry, args),
        task=args.task,
    )
    status["status"] = "failed"
    status["reason"] = f"preflight failed: {reason}"
    return _finalize_status(status, publish_root)


def _run_entries(
    entries: tuple[MolmoLiveModelEntry, ...],
    args: argparse.Namespace,
    publish_root: Path,
) -> tuple[list[dict[str, Any]], int]:
    statuses: list[dict[str, Any]] = []
    failure_count = 0
    for entry in entries:
        status = _run_entry(entry, args, publish_root=publish_root)
        statuses.append(status)
        if status["status"] == "failed":
            failure_count += 1
            if not args.continue_on_error and not args.all:
                break
    return statuses, failure_count


def _run_entry(
    entry: MolmoLiveModelEntry,
    args: argparse.Namespace,
    *,
    publish_root: Path,
) -> dict[str, Any]:
    profile = _entry_profile(entry, args)
    generated_mess_count = _entry_generated_mess_count(entry, args)
    status = base_status(
        entry,
        seed=args.seed,
        generated_mess_count=generated_mess_count,
        profile=profile,
        task=args.task,
    )
    entry_output_dir = args.output_dir / entry.name
    command = _live_command(entry, entry_output_dir, args)
    rerun_command = _live_report_rerun_command(entry, args)
    status.update(
        {
            "command": command,
            "rerun_command": rerun_command,
            "env": {
                "ROBOCLAWS_PROVIDER_PROFILE": entry.provider_profile,
                _model_env_key(entry): entry.model,
                PROVIDER_TIMING_PROXY_ENV: _default_provider_timing_proxy_value(),
            },
            "cache_roots": [
                "~/.cache/uv",
                "~/.cache/molmospaces",
                "~/.cache/molmo-spaces-resources",
            ],
            "updated_at": utc_timestamp(),
        }
    )

    if args.dry_run:
        status["status"] = "dry_run"
        status["reason"] = "dry run requested; no live provider call made"
        return _finalize_status(status, publish_root)

    if not os.environ.get(entry.secret_env):
        status["status"] = "skipped"
        status["reason"] = f"missing required secret/env {entry.secret_env}"
        return _finalize_status(status, publish_root)

    env = os.environ.copy()
    env["ROBOCLAWS_PROVIDER_PROFILE"] = entry.provider_profile
    env[_model_env_key(entry)] = entry.model
    env.setdefault(PROVIDER_TIMING_PROXY_ENV, "1")
    env["ROBOCLAWS_REPORT_RERUN_COMMAND"] = rerun_command
    try:
        _run_checked(command, env=env)
        seed_dir = latest_seed_run_dir(entry_output_dir, seed=args.seed)
        if seed_dir is None:
            raise RuntimeError(
                f"no seed-{args.seed} run_result.json found under {entry_output_dir}"
            )
        published_seed_dir = publish_seed_run(
            source_seed_dir=seed_dir,
            publish_root=publish_root,
            entry_name=entry.name,
            seed=args.seed,
        )
        status["status"] = "success"
        status["run_dir"] = str(seed_dir)
        status["published_dir"] = str(published_seed_dir)
        status["report_path"] = report_path_for_entry(entry.name, seed=args.seed)
    except Exception as exc:
        status["status"] = "failed"
        status["reason"] = str(exc)
        seed_dir = latest_seed_artifact_dir(entry_output_dir, seed=args.seed)
        if seed_dir is not None:
            diagnostic_dir = publish_diagnostic_seed_run(
                source_seed_dir=seed_dir,
                publish_root=publish_root,
                entry_name=entry.name,
                seed=args.seed,
            )
            status["run_dir"] = str(seed_dir)
            status["diagnostic_dir"] = str(diagnostic_dir)
            status["diagnostic_path"] = diagnostic_path_for_entry(entry.name, seed=args.seed)
    return _finalize_status(status, publish_root)


def _finalize_status(status: dict[str, Any], publish_root: Path) -> dict[str, Any]:
    status["updated_at"] = utc_timestamp()
    write_status(status_path_for_entry(publish_root, str(status["entry"])), status)
    print(f"molmo-live-ci {status['entry']}: {status['status']}")
    if status.get("reason"):
        print(f"  reason: {status['reason']}")
    return status


def _entry_profile(entry: MolmoLiveModelEntry, args: argparse.Namespace) -> str:
    return args.profile or entry.profile


def _entry_generated_mess_count(entry: MolmoLiveModelEntry, args: argparse.Namespace) -> int:
    if args.generated_mess_count is not None:
        return int(args.generated_mess_count)
    return 5


def _prewarm_generated_mess_count(
    entries: tuple[MolmoLiveModelEntry, ...],
    args: argparse.Namespace,
) -> int:
    return max(_entry_generated_mess_count(entry, args) for entry in entries)


def _live_command(
    entry: MolmoLiveModelEntry,
    entry_output_dir: Path,
    args: argparse.Namespace,
) -> list[str]:
    profile = _entry_profile(entry, args)
    generated_mess_count = _entry_generated_mess_count(entry, args)
    return [
        args.just_bin,
        "run::surface",
        "surface=household-world",
        "world=molmospaces/val_0",
        "backend=mujoco",
        "intent=cleanup",
        f"agent_engine={entry.agent_engine}",
        f"provider_profile={entry.provider_profile}",
        f"evidence_lane={profile}",
        f"seed={args.seed}",
        "scenario_setup=relocate-cleanup-related-objects",
        f"relocation_count={generated_mess_count}",
        f"output_dir={entry_output_dir}",
        f"task={args.task}",
        f"host={args.host}",
        f"port={args.port}",
    ]


def _live_report_rerun_command(entry: MolmoLiveModelEntry, args: argparse.Namespace) -> str:
    profile = _entry_profile(entry, args)
    generated_mess_count = _entry_generated_mess_count(entry, args)
    command = [
        "just",
        "run::surface",
        "surface=household-world",
        "world=molmospaces/val_0",
        "backend=mujoco",
        "intent=cleanup",
        f"agent_engine={entry.agent_engine}",
        f"provider_profile={entry.provider_profile}",
        f"evidence_lane={profile}",
        f"seed={args.seed}",
        "scenario_setup=relocate-cleanup-related-objects",
        f"relocation_count={generated_mess_count}",
        f"task={args.task}",
    ]
    return (
        f"ROBOCLAWS_PROVIDER_PROFILE={entry.provider_profile} "
        f"{_model_env_key(entry)}={entry.model} "
        f"{PROVIDER_TIMING_PROXY_ENV}={_default_provider_timing_proxy_value()} "
        f"{shell_join(command)}"
    )


def _model_env_key(entry: MolmoLiveModelEntry) -> str:
    if entry.agent_engine == "openai-agents-sdk":
        return "ROBOCLAWS_OPENAI_AGENTS_MODEL"
    raise ValueError(f"unsupported Molmo live agent engine: {entry.agent_engine}")


def _default_provider_timing_proxy_value() -> str:
    return os.environ.get(PROVIDER_TIMING_PROXY_ENV, "1")


def _prewarm(args: argparse.Namespace, *, generated_mess_count: int) -> None:
    _run_checked(
        [
            args.python_bin,
            "scripts/molmo_cleanup/prewarm_molmospaces_ci_assets.py",
            "--output-dir",
            str(args.output_dir / "_prewarm"),
            "--seed",
            str(args.seed),
            "--generated-mess-count",
            str(generated_mess_count),
            "--robot-name",
            "rby1m",
        ]
    )


def _any_entry_has_secret(entries: tuple[MolmoLiveModelEntry, ...]) -> bool:
    return any(os.environ.get(entry.secret_env) for entry in entries)


def _run_checked(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(_shell_quote(item) for item in command))
    subprocess.run(command, check=True, env=env)


def _shell_quote(value: str | Path) -> str:
    text = str(value)
    if not text:
        return "''"
    safe = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_@%+=:,./-"
    if all(char in safe for char in text):
        return text
    return "'" + text.replace("'", "'\"'\"'") + "'"


if __name__ == "__main__":
    raise SystemExit(main())
