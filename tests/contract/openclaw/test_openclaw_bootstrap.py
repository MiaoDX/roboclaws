"""Static checks on ``scripts/openclaw/openclaw-bootstrap.sh`` — the contract this file
locks in is:

1. Each supported ``PROVIDER=…`` branch has a corresponding auth-profile
   entry with a non-empty ``EXTRA_MODELS_JSON`` array (except Kimi where
   the bootstrap either uses a custom provider override or the built-in
   plugin path) and a
   provider id that matches a Gateway plugin manifest at
   ``/app/dist/extensions/<id>/openclaw.plugin.json``.

The tests read the live ``scripts/openclaw/openclaw-bootstrap.sh`` plus the pinned
image contents; if Docker + the image aren't available the affected
tests ``skip`` (so CI's ``lint-and-mock`` job passes without pulling the
Gateway image).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BOOTSTRAP = ROOT / "scripts" / "openclaw" / "openclaw-bootstrap.sh"
DEFAULTS_ENV = ROOT / "scripts" / "openclaw" / "openclaw-defaults.env"


def _default_gateway_image() -> str:
    """Read OPENCLAW_IMAGE_DEFAULT from ``scripts/openclaw/openclaw-defaults.env``."""
    raw = DEFAULTS_ENV.read_text(encoding="utf-8")
    for line in raw.splitlines():
        if line.startswith("OPENCLAW_IMAGE_DEFAULT="):
            value = line.split("=", 1)[1].strip().strip('"')
            if value:
                return value
    raise AssertionError(f"OPENCLAW_IMAGE_DEFAULT missing in {DEFAULTS_ENV}")


IMAGE_DEFAULT = _default_gateway_image()


# ---------------------------------------------------------------------------
# Pre-seed heredoc runner
# ---------------------------------------------------------------------------
#
# ``scripts/openclaw/openclaw-bootstrap.sh`` materialises ``openclaw.json`` inside a
# short-lived throwaway container via a python3 pre-seed script.  The D-04 /
# spike F-3 contract (mcp.servers + tools.profile must be present BEFORE first
# container start) is encoded entirely in that pre-seed — so the regression
# tests have to execute the pre-seed against a tmp config root and inspect the
# resulting openclaw.json.  Spinning docker for every test would be slow and
# require the pinned image, which is not available in lint-and-mock CI.
# Instead: extract the heredoc body that bash writes to a host temp file via
# ``cat > "$preseed_py" <<'PY'``, patch the hard-coded ``/home/node/.openclaw``
# root to ``tmp_path``, and exec it with ``python3`` directly.  This is the
# same script the Gateway container runs, minus Docker's isolation.


def _extract_preseed_heredoc(script_src: str) -> str:
    """Return the body of the pre-seed python3 heredoc in ``openclaw-bootstrap.sh``.

    Structure on disk (post-refactor — apostrophes in Python comments would
    break the previous wrapped-heredoc-inside-sh-lc form, so the pre-seed is
    now written to a host temp file and bind-mounted into the container):

        preseed_py="$(mktemp -t openclaw-preseed.XXXXXX.py)"
        cat > "$preseed_py" <<'PY'
        <BODY>
        PY

    The opening fence is the ``cat > "$preseed_py" <<'PY'`` line.  The
    closing fence is a line whose stripped content is exactly ``PY``.
    Simple line-based scanning is more robust than a regex over bash quoting.
    """
    lines = script_src.splitlines()
    start: int | None = None
    for idx, line in enumerate(lines):
        if 'cat > "$preseed_py" <<' in line and "'PY'" in line:
            start = idx + 1
            break
    if start is None:
        raise AssertionError(
            "could not locate pre-seed python heredoc opener in openclaw-bootstrap.sh"
        )
    end: int | None = None
    for idx in range(start, len(lines)):
        if lines[idx].rstrip() == "PY":
            end = idx
            break
    if end is None:
        raise AssertionError(
            "could not locate pre-seed python heredoc closing PY fence in openclaw-bootstrap.sh"
        )
    return "\n".join(lines[start:end])


def _run_preseed(tmp_path: Path, env_overrides: dict[str, str]) -> Path:
    """Execute the pre-seed python heredoc against a tmp config root.

    Returns the path to the generated ``openclaw.json``.  The heredoc is
    unchanged code that normally runs inside the Gateway image's throwaway
    container; we redirect its ``/home/node/.openclaw`` paths to ``tmp_path``
    so the test can be executed on the host without Docker.
    """
    script_src = BOOTSTRAP.read_text(encoding="utf-8")
    heredoc_body = _extract_preseed_heredoc(script_src)

    # Redirect the one hard-coded config root to tmp_path.  The heredoc uses
    # ``base = "/home/node/.openclaw"`` exactly once and derives every other
    # path from it — so a single-point string replacement is sufficient.
    patched = heredoc_body.replace(
        'base = "/home/node/.openclaw"',
        f"base = {json.dumps(str(tmp_path))}",
    )

    script_file = tmp_path / "preseed.py"
    script_file.write_text(patched)

    # Minimum env the heredoc reads via os.environ (including the Phase 2.6
    # additions ROBOCLAWS_MCP_URL + ROBOCLAWS_TOOL_PROFILE).  Tests only
    # override what they care about; everything else gets a safe default.
    env = {
        "PROVIDER_API_KEY": "sk-fake",
        "PROVIDER_ID": "kimi",
        "PROVIDER_ID_OVERRIDE": "",
        "PROVIDER_ENTRY_JSON": "",
        "PROVIDER_BASE_URL": "",
        "MODEL": "kimi/k2p5",
        "IMAGE_MODEL": "kimi/k2p5",
        "TIMEOUT_SECONDS": "600",
        "AGENT_IDS_CSV": "agent-0",
        "EXTRA_MODELS_JSON": "[]",
        "AGENT_SOUL_CSV": "",
        "ROBOCLAWS_MCP_ENABLED": "1",
        "ROBOCLAWS_MCP_URL": "http://host.docker.internal:18788/mcp",
        "ROBOCLAWS_TOOL_PROFILE": "minimal",
        # In production the bash wrapper reads this from
        # scripts/openclaw/openclaw_plugin_allowlist.py; for the test we synthesize
        # the same JSON so the pre-seed exercises the plugins.allow code path.
        "PLUGIN_ALLOW_JSON": json.dumps(["acpx", "memory-core", "kimi"]),
    }
    env.update(env_overrides)
    for k in ("PATH", "HOME", "LANG", "LC_ALL"):
        if k in os.environ:
            env[k] = os.environ[k]

    subprocess.run(
        ["python3", str(script_file)],
        env=env,
        check=True,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    return Path(tmp_path) / "openclaw.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _gateway_image_available(image: str = IMAGE_DEFAULT) -> bool:
    if not _docker_available():
        return False
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return result.returncode == 0


def _read_bootstrap() -> str:
    return BOOTSTRAP.read_text(encoding="utf-8")


def _extract_extra_models_for(provider: str) -> list[dict]:
    """Return the parsed ``EXTRA_MODELS_JSON`` block for a given PROVIDER case.

    Parses the bash script's heredoc-quoted JSON literal. Kept deliberately
    strict: if the script's structure changes, the test fails loudly rather
    than silently returning ``[]``.
    """
    text = _read_bootstrap()
    # Match the case branch, then capture the EXTRA_MODELS_JSON='[...]' literal.
    # Limit "next branch" detection to the top-level PROVIDER case labels.
    # The Kimi branch contains a nested case (KIMI_PROVIDER_MODE), so a
    # generic `^\s*[a-z]+\)$` pattern would stop at `custom)` / `plugin)`.
    pattern = (
        rf"^    {re.escape(provider)}\)\s*$"  # top-level case label
        r"(?:(?!^    [a-z]+\)\s*$).)*?"  # up to next top-level case label
        r"EXTRA_MODELS_JSON='(\[.*?\])'"
    )
    m = re.search(pattern, text, flags=re.MULTILINE | re.DOTALL)
    if not m:
        # Kimi branch uses "[]" double-quoted instead of single.
        pattern_alt = (
            rf"^    {re.escape(provider)}\)\s*$"
            r"(?:(?!^    [a-z]+\)\s*$).)*?"
            r'EXTRA_MODELS_JSON="(\[.*?\])"'
        )
        m = re.search(pattern_alt, text, flags=re.MULTILINE | re.DOTALL)
        if not m:
            raise AssertionError(
                f"bootstrap.sh does not declare EXTRA_MODELS_JSON for PROVIDER={provider}"
            )
    return json.loads(m.group(1))


def _extract_provider_base_urls() -> dict[str, str]:
    """Return ``{ provider_id: base_url }`` for every explicit PROVIDER_BASE_URL
    declaration in the bootstrap. Kimi's empty string is included too (it
    means "use the built-in catalog's baseUrl").
    """
    text = _read_bootstrap()
    out: dict[str, str] = {}
    for provider_match in re.finditer(
        r"^    ([a-z][a-z0-9]*)\)\s*$"
        r"(?:(?!^    [a-z]+\)\s*$).)*?"
        r'PROVIDER_BASE_URL="([^"]*)"',
        text,
        flags=re.MULTILINE | re.DOTALL,
    ):
        out[provider_match.group(1)] = provider_match.group(2)
    return out


def _cat_path_in_image(path: str) -> str:
    """Return the contents of a single exact path inside the pinned Gateway
    image. Use this when the path is already resolved (e.g. from a prior
    ``find`` call); use :func:`_read_gateway_catalog` when the filename has
    a content-hashed suffix.
    """
    result = subprocess.run(
        ["docker", "run", "--rm", IMAGE_DEFAULT, "sh", "-lc", f"cat {path}"],
        capture_output=True,
        timeout=30,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"could not read {path} from {IMAGE_DEFAULT}: {result.stderr}")
    return result.stdout


def _read_gateway_catalog(path_glob: str, content_marker: str) -> str:
    """Return the body of the dist file matching ``path_glob`` whose content
    contains ``content_marker``.

    The Gateway bundles each provider catalog into its own JS chunk with a
    webpack/vite content-hashed filename (e.g.
    ``provider-catalog-C9xZ5Sl52.js``); the hash changes on every image
    rebuild, so pinning a specific filename forces a test edit on every
    image bump. ``content_marker`` is a fixed string we know lives only in
    the catalog we want — much more stable
    than the hash.
    """
    err_msg = f"no file in {path_glob} contains {content_marker}"
    script = (
        "set -e; "
        f"f=$(grep -lF {content_marker!r} {path_glob} 2>/dev/null | head -1); "
        f'if [ -z "$f" ]; then echo "{err_msg}" >&2; exit 1; fi; '
        'cat "$f"'
    )
    result = subprocess.run(
        ["docker", "run", "--rm", IMAGE_DEFAULT, "sh", "-lc", script],
        capture_output=True,
        timeout=30,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"could not read {path_glob} (marker={content_marker!r}) from "
            f"{IMAGE_DEFAULT}: {result.stderr}"
        )
    return result.stdout


# ---------------------------------------------------------------------------
# Free-tier claims
# ---------------------------------------------------------------------------


def test_kimi_branch_has_empty_extra_models() -> None:
    """Kimi's EXTRA_MODELS_JSON stays empty because the kimi branch now uses
    the PROVIDER_ENTRY_JSON / mode=replace path (custom ``anthropic_kimi``
    provider) rather than merging extra models into the built-in plugin's
    catalog.  See :func:`test_kimi_branch_registers_anthropic_kimi_provider`
    for the assertions on the custom entry itself.
    """
    models = _extract_extra_models_for("kimi")
    assert models == [], (
        "kimi branch should keep EXTRA_MODELS_JSON='[]' — its catalog entry "
        "now lives in PROVIDER_ENTRY_JSON with mode=replace."
    )


def _extract_provider_entry_for(provider: str) -> dict | None:
    """Parse the ``PROVIDER_ENTRY_JSON`` heredoc-quoted JSON literal for a
    given PROVIDER case.  Returns ``None`` when the branch is using the
    legacy EXTRA_MODELS_JSON / mode=merge path.
    """
    text = _read_bootstrap()
    pattern = (
        rf"^    {re.escape(provider)}\)\s*$"
        r"(?:(?!^    [a-z_]+\)\s*$).)*?"
        r"PROVIDER_ENTRY_JSON=\$\(cat <<JSON\n(.*?)\nJSON\n"
    )
    m = re.search(pattern, text, flags=re.MULTILINE | re.DOTALL)
    if not m:
        return None
    return json.loads(m.group(1))


def test_kimi_branch_registers_anthropic_kimi_provider() -> None:
    """Kimi's bootstrap branch must register a custom ``anthropic_kimi``
    provider (via PROVIDER_ENTRY_JSON / mode=replace) rather than relying
    on the built-in ``kimi-coding`` plugin, which drives
    ``api.kimi.com/coding/`` in a reasoning-heavy mode that serialises
    every multi-image turn at 60-120s and regularly trips the Gateway's
    idle watchdog (observed 2026-04-20).

    The custom entry pins the request shape we want — anthropic-messages
    at the same host, no forced reasoning, canonical
    ``User-Agent: Claude-Code/1.0``.  Kimi's direct-probe path in
    ``KimiCodingProvider`` uses the same host at a different surface for
    the same reason.
    """
    entry = _extract_provider_entry_for("kimi")
    assert entry is not None, (
        "kimi branch no longer declares PROVIDER_ENTRY_JSON. Revert to the "
        "anthropic_kimi custom registration or this path silently falls back "
        "to the slow built-in kimi-coding plugin."
    )
    assert entry["baseUrl"] == "https://api.kimi.com/coding/"
    assert entry["api"] == "anthropic-messages"
    assert entry["auth"] == "api-key"
    # apiKey is interpolated from $PROVIDER_API_KEY by the heredoc at bootstrap
    # time; the literal string before interpolation is the env var reference.
    assert "${PROVIDER_API_KEY}" in entry["apiKey"] or entry["apiKey"].startswith("sk-"), (
        "apiKey must be injected from KIMI_API_KEY (heredoc interpolation)."
    )
    headers = entry.get("headers", {})
    assert headers.get("User-Agent") == "Claude-Code/1.0", (
        "Kimi-For-Coding gate requires a recognised coding-agent User-Agent."
    )
    assert headers.get("anthropic-version"), (
        "anthropic-messages calls require an ``anthropic-version`` header."
    )
    models = entry.get("models", [])
    ids = {m["id"] for m in models}
    assert ids == {"k2p5", "k2.6"}, (
        "custom anthropic_kimi provider should advertise both k2p5 and k2.6 "
        "so local probes can compare model behavior without switching provider mode."
    )
    for model in models:
        assert "image" in model.get("input", []), "demo sends 2 images per turn"
        assert model.get("reasoning") is False, (
            "reasoning:true on api.kimi.com/coding/ is exactly what we're routing "
            "around — flipping this to true would re-introduce the slow path."
        )


def test_kimi_provider_mode_defaults_to_custom_and_supports_plugin() -> None:
    """Kimi bootstrap should default to the custom provider override while
    exposing an explicit stock-plugin escape hatch for local A/B probes.
    """
    text = _read_bootstrap()
    assert 'KIMI_PROVIDER_MODE="${KIMI_PROVIDER_MODE:-custom}"' in text, (
        "Kimi bootstrap must default to the custom provider override so "
        "existing local runs keep the faster path unless explicitly changed."
    )
    assert re.search(r"^\s{12}plugin\)\s*$", text, flags=re.MULTILINE), (
        "Kimi bootstrap should expose a plugin mode for stock OpenClaw provider comparisons."
    )
    assert 'MODEL="${MODEL:-kimi/k2p5}"' in text, (
        "plugin mode should route to the stock kimi/k2p5 Gateway alias."
    )


def test_bootstrap_uses_mode_replace_when_custom_entry_present() -> None:
    """When PROVIDER_ENTRY_JSON is supplied, the Python pre-seed block must
    register the custom provider with ``mode: replace`` — not merge.  The
    merge path would union our entry with the built-in plugin catalog and
    the Gateway could still route via the slow built-in kimi model id
    during request-shaping, defeating the fix.
    """
    text = _read_bootstrap()
    assert re.search(
        r'if provider_entry_json:.*?"mode":\s*"replace"',
        text,
        flags=re.DOTALL,
    ), "bootstrap pre-seed must write mode=replace when PROVIDER_ENTRY_JSON is set"


def test_bootstrap_pins_image_model_to_current_model_by_default() -> None:
    """The pre-seeded config should set ``agents.defaults.imageModel`` so the
    generic ``image`` tool does not auto-pair to some other image-capable
    catalog entry on the same provider.

    This matters for the custom Kimi path: without an explicit imageModel,
    Gateway's image-tool resolver picks the first image-capable entry from the
    provider catalog, which made image analysis silently route through
    ``anthropic_kimi/k2p5`` during local debugging even when the main model was
    pinned to ``anthropic_kimi/k2.6``.
    """
    text = _read_bootstrap()
    assert 'image_model = os.environ.get("IMAGE_MODEL") or model' in text
    assert '"imageModel": {"primary": image_model}' in text, (
        "bootstrap pre-seed must write agents.defaults.imageModel.primary."
    )
    assert '-e IMAGE_MODEL="${IMAGE_MODEL:-$MODEL}" \\' in text, (
        "docker pre-seed call must pass IMAGE_MODEL through to the config writer."
    )


def test_only_curated_providers_supported() -> None:
    """The bootstrap's ``case "$PROVIDER"`` statement should list exactly
    the curated provider set: Kimi. If this test fails
    because a new provider was added, make sure you've also:

      1. Added a catalog entry (EXTRA_MODELS_JSON or PROVIDER_ENTRY_JSON)
         with values verified live — every declared ``contextWindow``
         must clear the Gateway memory-flush headroom (see
         ``test_advertised_context_windows_clear_flush_headroom``).
      2. Added a PROVIDER_BASE_URL matching the Gateway plugin catalog
         (or an explicit PROVIDER_ENTRY_JSON.baseUrl for custom hosts).
      3. Added a parametrize row in test_provider_env_var_matches_plugin_manifest
         if the upstream uses an auth env recognised by a Gateway plugin.
      4. Updated docs/human/model-matrix.md and docs/human/openclaw/local.md.
    """
    text = _read_bootstrap()
    case_labels = re.findall(r"^    ([a-z][a-z0-9]*)\)\s*$", text, flags=re.MULTILINE)
    # Filter to labels inside the provider case block (between
    # `case "$PROVIDER" in` and the closing `esac`).
    m = re.search(r'case "\$PROVIDER" in(.*?)\nesac', text, flags=re.DOTALL)
    assert m, "could not find the PROVIDER case block"
    block = m.group(1)
    provider_labels = re.findall(r"^    ([a-z][a-z0-9]*)\)\s*$", block, flags=re.MULTILINE)
    assert set(provider_labels) == {"kimi"}, (
        f"bootstrap.sh PROVIDER case declares {sorted(set(provider_labels))!r}; "
        "expected exactly {'kimi'} per curated contract."
    )
    # Quieten the unused variable from earlier refactor.
    del case_labels


@pytest.mark.integration
def test_advertised_context_windows_clear_flush_headroom() -> None:
    """Every model the bootstrap advertises must declare enough context
    headroom for the Gateway's pre-compaction memory-flush gate.

    The Gateway's ``memory-core`` extension fires a flush turn once a
    session reaches ``contextWindow - reserveTokensFloor(20000) -
    softThresholdTokens(4000)`` tokens. With the defaults that's
    ``contextWindow - 24000``. A declared ``contextWindow`` below ~30k
    leaves almost no headroom and causes the flush to fire on the first
    observe turn (FPV + overhead + bootstrap context already consume
    7-10k tokens). Some models respond to the flush by calling
    ``roboclaws__done`` — collapsing the chat session. See the
    2026-04-23 retro and ``docs/human/model-matrix.md`` for the full
    incident.

    131 072 is the current floor; any
    new model entry must meet or exceed that.
    """
    text = _read_bootstrap()
    MIN_CTX = 131_072
    violations: list[str] = []
    # Pull every ``{"id":"…", …, "contextWindow":N, …}`` record the script
    # emits, regardless of whether it sits in EXTRA_MODELS_JSON or a
    # PROVIDER_ENTRY_JSON.models heredoc. A regex over raw text is
    # deliberate: new provider branches will show up here without needing
    # to teach ``_extract_provider_entry_for`` another shape.
    pattern = re.compile(
        r'"id"\s*:\s*"(?P<id>[^"]+)"'
        r'(?:(?!"id"\s*:\s*").)*?'
        r'"contextWindow"\s*:\s*(?P<ctx>\d+)',
        flags=re.DOTALL,
    )
    matches = list(pattern.finditer(text))
    assert matches, (
        "bootstrap has no contextWindow declarations — the regex needs "
        "updating or every provider entry lost its catalog shape."
    )
    for m in matches:
        model_id = m.group("id")
        ctx = int(m.group("ctx"))
        if ctx < MIN_CTX:
            violations.append(f"{model_id}: contextWindow={ctx}")
    assert not violations, (
        "bootstrap advertises models below the Gateway memory-flush "
        f"headroom ({MIN_CTX}); flush will trip on turn 1-2 and the "
        "chat session will tear down when the model picks "
        f"roboclaws__done: {violations}"
    )


# ---------------------------------------------------------------------------
# Plugin id ↔ auth env var sanity
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize(
    "provider_id, expected_auth_env",
    [
        ("kimi", "KIMI_API_KEY"),
    ],
)
def test_provider_env_var_matches_plugin_manifest(provider_id: str, expected_auth_env: str) -> None:
    """The ``PROVIDER_ENV_VAR`` the bootstrap passes into the container must
    match the Gateway plugin's declared ``providerAuthEnvVars[<id>]`` or
    the plugin won't pick up the api key and the probe fails with 401/503.
    """
    text = _read_bootstrap()
    pattern = (
        rf"^\s*{re.escape(provider_id)}\)\s*$"
        r"(?:(?!^\s*[a-z]+\)\s*$).)*?"
        r'PROVIDER_ENV_VAR="([^"]+)"'
    )
    m = re.search(pattern, text, flags=re.MULTILINE | re.DOTALL)
    assert m, f"bootstrap.sh missing PROVIDER_ENV_VAR for {provider_id}"
    assert m.group(1) == expected_auth_env, (
        f"{provider_id}: bootstrap sets PROVIDER_ENV_VAR={m.group(1)!r} but "
        f"the Gateway plugin expects {expected_auth_env!r}."
    )

    if not _gateway_image_available():
        pytest.skip(f"{IMAGE_DEFAULT} not pulled locally; skip plugin-manifest check")
    # A provider id may be served by a differently-named plugin directory
    # (e.g. the `kimi` provider is declared by the `kimi-coding` plugin).
    # Find every manifest under /app/dist/extensions and check which one
    # claims the provider id.
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            IMAGE_DEFAULT,
            "sh",
            "-lc",
            "find /app/dist/extensions -name openclaw.plugin.json -print",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    declared_env_vars: list[str] = []
    for path in result.stdout.strip().split("\n"):
        if not path.strip():
            continue
        manifest = json.loads(_cat_path_in_image(path.strip()))
        providers = manifest.get("providers") or []
        if provider_id not in providers:
            continue
        envs = (manifest.get("providerAuthEnvVars") or {}).get(provider_id, [])
        declared_env_vars.extend(envs)
    assert declared_env_vars, (
        f"no /app/dist/extensions/*/openclaw.plugin.json declares provider "
        f"{provider_id!r} in its `providers` list — bootstrap needs updating."
    )
    assert expected_auth_env in declared_env_vars, (
        f"{provider_id}: plugin manifests declare {declared_env_vars!r} for "
        f"this provider; bootstrap uses {expected_auth_env!r} which isn't "
        "in the accepted list."
    )


# ---------------------------------------------------------------------------
# SOUL injection: static contract checks (no Docker required)
# ---------------------------------------------------------------------------


def test_bootstrap_declares_agent_souls_env_var() -> None:
    """AGENT_SOULS env var is declared and consumed by the bootstrap."""
    text = _read_bootstrap()
    assert "AGENT_SOULS" in text, "bootstrap.sh does not reference AGENT_SOULS"


def test_bootstrap_passes_soul_csv_to_preseed() -> None:
    """AGENT_SOUL_CSV is exported so the pre-seed container can copy SOUL files."""
    text = _read_bootstrap()
    assert "AGENT_SOUL_CSV" in text, (
        "bootstrap.sh does not pass AGENT_SOUL_CSV to the pre-seed container; "
        "per-agent SOUL injection will silently do nothing"
    )


def test_bootstrap_binds_souls_dir_readonly() -> None:
    """SOULS_DIR is bind-mounted read-only into the pre-seed container."""
    text = _read_bootstrap()
    assert "/host-souls:ro" in text, (
        "bootstrap.sh does not bind-mount SOULS_DIR as /host-souls:ro in the "
        "pre-seed container; SOUL files cannot be copied into agent workspaces"
    )


def test_bootstrap_declares_exit_5_for_personality_collision() -> None:
    """Bootstrap exits with code 5 when the divergence probe detects identical responses.

    The bootstrap uses ``die "..." 5`` (die helper calls ``exit ${2:-1}``),
    not a bare ``exit 5``.
    """
    text = _read_bootstrap()
    assert "die(" in text or "die " in text, "bootstrap.sh missing 'die' helper"
    # die() is called with exit-code 5 for the personality-collision case.
    assert re.search(r"die\b.*\b5\b", text), (
        "bootstrap.sh does not call die with exit-code 5; personality collision in "
        "the divergence probe should fail with exit 5 so the caller detects SOUL load failures"
    )


def test_bootstrap_personality_probe_is_skippable() -> None:
    """PERSONALITY_PROBE=0 must be supported to skip the probe for identical-soul runs."""
    text = _read_bootstrap()
    assert "PERSONALITY_PROBE" in text, (
        "bootstrap.sh does not reference PERSONALITY_PROBE; there is no way to "
        "skip the probe for identical-soul runs (e.g. cooperative,cooperative)"
    )


# ---------------------------------------------------------------------------
# Phase 2.6: MCP + tools.profile seeding (D-03, D-04; spike F-1, F-3)
# ---------------------------------------------------------------------------


def test_bootstrap_ready_timeout_allows_current_gateway_cold_start() -> None:
    """Current gateway image builds can spend >60s on first run when caching/deps warm.

    A too-short ready timeout leaves the Gateway running after the host-side
    MCP server exits, which makes the agent see only ``session_status``.
    """
    text = _read_bootstrap()
    assert 'READY_TIMEOUT="${READY_TIMEOUT:-180}"' in text


def test_bootstrap_cleans_gateway_container_after_startup_failure() -> None:
    """If bootstrap fails after ``docker run``, it must not leave an orphan Gateway.

    An orphan Gateway keeps serving the Control UI after Roboclaws has closed
    its MCP server, so the nav tools disappear from the model's tool list.
    """
    text = _read_bootstrap()
    assert "gateway_started=0" in text
    # Trap was renamed to ``_cleanup_on_exit`` when temp-file cleanup was
    # folded into the same handler; guard the new name + behaviour.
    assert "trap _cleanup_on_exit EXIT" in text
    assert "gateway_started=1" in text
    assert "removing Gateway container after bootstrap failure" in text


def test_mcp_seeds_server_transport_and_url(tmp_path: Path) -> None:
    """The pre-seed must write ``mcp.servers.roboclaws`` with the
    ``transport`` key (not ``type``) set to ``streamable-http`` and the url
    taken from ROBOCLAWS_MCP_URL (default http://host.docker.internal:18788/mcp).

    Spike F-1: other combinations silently fail with a 400 on the SSE
    handshake and the agent reports "I don't have that tool". This test
    guards against anyone "fixing" the key to match other MCP client
    conventions (`type`) and accidentally dropping the tool surface.
    """
    cfg_path = _run_preseed(tmp_path, {})
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    server = cfg["mcp"]["servers"]["roboclaws"]
    assert server["transport"] == "streamable-http", (
        f"mcp.servers.roboclaws.transport={server.get('transport')!r}; "
        "Gateway MCP loader at /app/dist/pi-bundle-mcp-tools-*.js accepts "
        "only 'streamable-http' or 'sse' on this key."
    )
    assert server["url"] == "http://host.docker.internal:18788/mcp"
    # Spike F-1 regression guard: `type` is the key you reach for from MCP
    # client docs; the Gateway wants `transport`.
    assert "type" not in server, (
        "mcp.servers.roboclaws must use 'transport' key, not 'type' — "
        "see spike F-1 in 02.6-SPIKE-FINDINGS.md"
    )


def test_mcp_seeds_per_agent_tools_profile_minimal(tmp_path: Path) -> None:
    """Every agent in ``agents.list`` carries ``tools.profile = "minimal"``
    by default (D-03).  The Gateway's tool-policy loader reads this per-agent
    and applies the restriction before any tool dispatch; a missing entry
    falls back to the implicit "coding" profile and re-opens exec/curl.
    """
    cfg_path = _run_preseed(tmp_path, {"AGENT_IDS_CSV": "agent-0,agent-1"})
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert cfg["agents"]["defaults"]["compaction"]["memoryFlush"]["enabled"] is False, (
        "minimal tool profile must disable Gateway pre-compaction memory flush; "
        f"defaults={cfg['agents']['defaults']!r}"
    )
    agent_ids = {entry["id"] for entry in cfg["agents"]["list"]}
    assert agent_ids == {"agent-0", "agent-1"}, (
        f"agents.list does not match AGENT_IDS_CSV; got ids={agent_ids!r}"
    )
    for entry in cfg["agents"]["list"]:
        assert entry["tools"]["profile"] == "minimal", (
            f"agent {entry['id']!r} missing tools.profile=minimal; entry={entry!r}"
        )
        # Image 2026.4.25-beta.11 consolidated MCP-tool exposure under the
        # `bundle-mcp` policy ID, and `minimal` no longer includes it. The
        # bootstrap splices it back in via alsoAllow so roboclaws__* tools
        # remain reachable. See docs/ai/openclaw/tool-profiles.md.  Lock the
        # tools block to exactly these two keys so any drift (a stray deny,
        # a custom override) trips the test.
        assert set(entry["tools"].keys()) == {"profile", "alsoAllow"}, (
            f"agent {entry['id']!r} tools block does not match expected "
            f"shape; got keys={set(entry['tools'].keys())!r}"
        )
        assert entry["tools"]["alsoAllow"] == ["bundle-mcp"], (
            f"agent {entry['id']!r} alsoAllow must splice exactly bundle-mcp; "
            f"got {entry['tools']['alsoAllow']!r}"
        )


def test_mcp_can_be_disabled_for_provider_only_probes(tmp_path: Path) -> None:
    """Provider-only Gateway probes can disable the Roboclaws MCP surface."""
    cfg_path = _run_preseed(
        tmp_path,
        {
            "AGENT_IDS_CSV": "agent-0,agent-1",
            "ROBOCLAWS_MCP_ENABLED": "0",
        },
    )
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert "mcp" not in cfg
    for entry in cfg["agents"]["list"]:
        assert entry["tools"] == {"profile": "minimal"}, (
            f"direct chat-completions agents must not expose bundle-mcp; entry={entry!r}"
        )


def test_plugins_allow_seeded_from_canonical_allowlist(tmp_path: Path) -> None:
    """Seeded openclaw.json must carry ``plugins.allow`` from the canonical
    list in ``scripts/openclaw/openclaw_plugin_allowlist.py``.

    Strict allow-list flips the failure mode on a gateway image bump: any
    new auto-enabled plugin upstream is hard-rejected unless we explicitly
    add it here. Without this, the bonjour/browser/document-extract/microsoft
    family silently lazy-installs heavy npm tarballs (playwright, edge-tts,
    pdfjs) on first start. See scripts/openclaw/openclaw_plugin_allowlist.py for
    rationale + per-entry justification.
    """
    cfg_path = _run_preseed(tmp_path, {})
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    sys.path.insert(0, str(BOOTSTRAP.parent))
    from openclaw_plugin_allowlist import ALLOWED as expected_allow

    assert cfg["plugins"]["allow"] == list(expected_allow), (
        "plugins.allow drift detected — update scripts/openclaw/openclaw_plugin_allowlist.py "
        "or the bootstrap pre-seed in lockstep so both paths agree on the list"
    )
    # acpx probeAgent pins the embedded-ACP health probe to one of our agents
    # instead of the upstream default ``codex``.
    assert cfg["plugins"]["entries"]["acpx"]["enabled"] is True, (
        "plugins.entries.acpx must set enabled=true or the entries-system "
        "warns 'plugin disabled (bundled (disabled by default)) but config "
        "is present' and silently drops the config block"
    )
    assert cfg["plugins"]["entries"]["acpx"]["config"]["probeAgent"] == "agent-0", (
        "acpx probeAgent must point at our first agent so the embedded ACP "
        "backend doesn't stall on the missing default 'codex' probe"
    )


def test_bootstrap_reads_canonical_plugin_allowlist() -> None:
    """The bash wrapper must source ``plugins.allow`` from
    ``scripts/openclaw/openclaw_plugin_allowlist.py`` (single source of truth shared
    with the appliance seeder), not inline a copy of the list.
    """
    text = _read_bootstrap()
    assert "openclaw_plugin_allowlist" in text and "PLUGIN_ALLOW_JSON" in text, (
        "openclaw-bootstrap.sh must read the canonical allow-list module and "
        "forward it to the pre-seed as PLUGIN_ALLOW_JSON"
    )


def test_retired_railway_appliance_surface_stays_removed() -> None:
    retired_paths = (
        ROOT / "Dockerfile.railway",
        ROOT / "railway.toml",
        ROOT / "deploy" / "railway",
        ROOT / "scripts" / "appliance",
        ROOT / "scripts" / "appliance-run-interactive.sh",
        ROOT / "scripts" / "appliance_control_ui_smoke.py",
    )

    for path in retired_paths:
        assert not path.exists(), f"retired Railway/OpenClaw appliance surface returned: {path}"


def test_mcp_url_env_override_honored(tmp_path: Path) -> None:
    """ROBOCLAWS_MCP_URL env override flows through to the seeded
    openclaw.json — no hard-coded default shadows it.
    """
    cfg_path = _run_preseed(tmp_path, {"ROBOCLAWS_MCP_URL": "http://example.test:9999/mcp"})
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert cfg["mcp"]["servers"]["roboclaws"]["url"] == "http://example.test:9999/mcp"


def test_bootstrap_has_no_sim_server_url_compatibility_path() -> None:
    """OpenClaw bootstrap accepts the canonical MCP URL env var only.

    The old HTTP sim-server path is retired, so reintroducing a
    SIM_SERVER_URL translate-and-warn branch would preserve a stale owner
    instead of making callers use ROBOCLAWS_MCP_URL directly.
    """
    assert "SIM_SERVER_URL" not in _read_bootstrap()


def test_tool_profile_env_override_honored(tmp_path: Path) -> None:
    """ROBOCLAWS_TOOL_PROFILE=coding (used by the live-probe plan 02.6-06)
    rewrites every agent's tools.profile to "coding" — no minimal lock-in
    past the env var.
    """
    cfg_path = _run_preseed(
        tmp_path,
        {
            "AGENT_IDS_CSV": "agent-0,agent-1",
            "ROBOCLAWS_TOOL_PROFILE": "coding",
        },
    )
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert "compaction" not in cfg["agents"]["defaults"], (
        "coding profile should not inherit the minimal-profile memoryFlush disable; "
        f"defaults={cfg['agents']['defaults']!r}"
    )
    for entry in cfg["agents"]["list"]:
        assert entry["tools"]["profile"] == "coding", (
            f"agent {entry['id']!r} tools.profile did not honor "
            f"ROBOCLAWS_TOOL_PROFILE=coding override; entry={entry!r}"
        )


def test_mcp_seed_is_idempotent(tmp_path: Path) -> None:
    """Running the pre-seed twice against the same tmp config root produces
    identical openclaw.json — no duplicated mcp.servers entries, no growing
    agents.list.  Idempotency is required because operators re-run
    openclaw-bootstrap.sh to pick up model changes and expect the resulting
    config to converge rather than accumulate.
    """
    first = _run_preseed(tmp_path, {})
    first_contents = first.read_text(encoding="utf-8")
    # Run again against the same tmp_path; the heredoc's os.makedirs calls
    # are exist_ok=True and json.dump overwrites the file, so re-running
    # should be a no-op at the content level.
    second = _run_preseed(tmp_path, {})
    second_contents = second.read_text(encoding="utf-8")
    assert first_contents == second_contents, (
        "pre-seed is not idempotent — re-running produced a different "
        "openclaw.json. Diff the two contents to find the drift."
    )


def test_preseed_bakes_openclaw_token_when_set(tmp_path: Path) -> None:
    """OPENCLAW_TOKEN=<value> lands inside gateway.auth.token.

    This is how the `just chat::*` recipes pin a stable `demo` bearer so
    operators don't have to paste a fresh random token every `just chat`.
    """
    cfg_path = _run_preseed(tmp_path, {"OPENCLAW_TOKEN": "demo"})
    config = json.loads(cfg_path.read_text(encoding="utf-8"))
    auth = config["gateway"]["auth"]
    assert auth["mode"] == "token"
    assert auth["token"] == "demo", (
        "OPENCLAW_TOKEN=demo must be pre-seeded into openclaw.json; the "
        "Gateway will leave pre-seeded tokens alone and only generate a "
        "random one when the field is missing."
    )


def test_preseed_omits_token_field_when_env_unset(tmp_path: Path) -> None:
    """When OPENCLAW_TOKEN is unset, gateway.auth has no token field.

    The Gateway's first-boot logic generates and writes a random token into
    this slot; bootstrap's readyz loop reads whatever value ends up live.
    If we pre-seed an empty string the Gateway may treat that as "already
    set" and skip generation — so the field must be omitted, not empty.
    """
    cfg_path = _run_preseed(tmp_path, {"OPENCLAW_TOKEN": ""})
    config = json.loads(cfg_path.read_text(encoding="utf-8"))
    auth = config["gateway"]["auth"]
    assert auth == {"mode": "token"}, (
        f"expected auth to be exactly {{'mode': 'token'}} when no token is configured; got {auth!r}"
    )
