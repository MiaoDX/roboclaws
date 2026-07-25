"""Canonical OpenClaw Gateway plugin allow-list for roboclaws.

The Gateway image (ghcr.io/openclaw/openclaw) ships ~100 extensions in
``/app/dist/extensions/`` and auto-loads every one whose manifest declares
``"enabledByDefault": true``. For our embedded use case we only need a
handful, and the upstream "enabled-by-default" set drifts on every release —
silently lazy-installing heavy npm tarballs (playwright, edge-tts,
pdfjs-dist, …) the first time the Control UI enumerates capabilities.

Switching to a strict allow-list (``cfg.plugins.allow``) flips the failure
mode: anything new the upstream enables-by-default in the next image bump
is hard-rejected unless we explicitly opt in. The breakage on upgrade is
loud and immediate rather than silent and gradual — desirable when the
gateway image is a third-party dependency we don't curate.

``scripts/openclaw/openclaw-bootstrap.sh`` reads this list as the single source
of truth. Regression tests in
``tests/contract/openclaw/test_openclaw_bootstrap.py`` pin the rendered
``openclaw.json`` against ``ALLOWED``.

Each entry below is paired with a one-line justification. Adding an entry
requires a real reason; removing one should be probed first.

For the rationale, the live-probed before/after, the gotchas (manifest id
vs directory name), and the image-bump checklist, see
``docs/ai/openclaw/plugin-allowlist.md``.
"""

from __future__ import annotations

ALLOWED: list[str] = [
    # Embedded ACP runtime backend — provides the agent loop / session /
    # transport plumbing that ``/v1/chat/completions`` is built on.
    # Without this the gateway boots but no agent run can start.
    "acpx",
    # Memory tool surface. The agent's ``memory.*`` contract resolves
    # through this plugin even when ``compaction.memoryFlush`` is disabled,
    # so dropping it leaves the agent without a memory tool path.
    "memory-core",
    # Kimi (Moonshot) provider plugin — the manifest at
    # ``/app/dist/extensions/kimi-coding/openclaw.plugin.json`` declares
    # ``"id": "kimi"`` (the directory name "kimi-coding" is NOT the plugin
    # id, despite appearances). Required for KIMI_PROVIDER_MODE=plugin;
    # harmless under the custom-mode path which uses ``mode=replace`` to
    # register ``anthropic_kimi`` independently. The 2026-04-28 first
    # probe used "kimi-coding" here and the gateway warned
    # ``plugin not found: kimi-coding (stale config entry ignored)`` —
    # don't regress to dir-name-based ids.
    "kimi",
]
