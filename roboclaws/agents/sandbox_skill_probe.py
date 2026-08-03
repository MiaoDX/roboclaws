"""Deterministic isolation probe for the eval-only Sandbox Skills delivery cell."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from roboclaws.agents.drivers.openai_agents_sandbox_skills import (
    run_sandbox_isolation_probe,
    write_probe_payload,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skill",
        type=Path,
        default=Path("skills/household-world/SKILL.md"),
        help="Selected SKILL.md to materialize; no other repository path is exposed.",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


async def _run(skill_path: Path, output_path: Path) -> int:
    content = skill_path.read_text(encoding="utf-8")
    probe = await run_sandbox_isolation_probe(
        skill_name=skill_path.parent.name,
        content=content,
    )
    write_probe_payload(output_path, probe)
    print(json.dumps(probe.payload, indent=2, sort_keys=True))
    return 0 if probe.ok else 1


def main() -> int:
    args = _parser().parse_args()
    return asyncio.run(_run(args.skill, args.output))


if __name__ == "__main__":
    raise SystemExit(main())
