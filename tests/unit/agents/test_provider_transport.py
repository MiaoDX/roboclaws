from __future__ import annotations

import uuid
from pathlib import Path

from roboclaws.agents.provider_transport import (
    CODEX_WINDOW_ID_HEADER,
    provider_default_headers,
)


def test_codex_router_window_id_is_stable_per_run_dir(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"

    first = provider_default_headers("codex-router-responses", session_seed=run_dir)
    resumed = provider_default_headers("codex-router-responses", session_seed=run_dir)
    other = provider_default_headers(
        "codex-router-responses",
        session_seed=tmp_path / "other-run",
    )

    assert first == resumed
    assert first != other
    thread_id, generation = first[CODEX_WINDOW_ID_HEADER].rsplit(":", 1)
    assert uuid.UUID(thread_id)
    assert generation == "0"


def test_non_codex_routes_do_not_receive_codex_headers(tmp_path: Path) -> None:
    assert provider_default_headers("minimax-responses", session_seed=tmp_path) == {}
    assert provider_default_headers("mimo-mify-responses", session_seed=tmp_path) == {}
