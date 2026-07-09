"""Work-network provider guard helpers for dev probes and benchmarks."""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import Path


def assert_no_work_network_codex_gpt55(
    entries: Iterable[tuple[str, str, str]],
    *,
    item_label: str,
    recommendation: str,
    is_work_network: bool | None = None,
) -> None:
    blocked = tuple(
        entry_id
        for provider_id, model, entry_id in entries
        if provider_id == "codex-router-responses" and model == "gpt-5.5"
    )
    if not blocked:
        return
    if is_work_network is None:
        is_work_network = current_network_is_work()
    if not is_work_network:
        return
    raise SystemExit(
        _blocked_message(blocked, item_label=item_label, recommendation=recommendation)
    )


def current_network_is_work() -> bool:
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["bash", "scripts/dev/network_status.sh", "--is-work-network"],
        cwd=repo_root,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise SystemExit("error: cannot determine network status; curl is required.")


def _blocked_message(
    blocked_ids: tuple[str, ...],
    *,
    item_label: str,
    recommendation: str,
) -> str:
    return (
        "error: work network detected; codex-router-responses/gpt-5.5 "
        f"{item_label} are blocked because that route currently returns HTTP 403 here: "
        f"{', '.join(blocked_ids)}. {recommendation}"
    )
