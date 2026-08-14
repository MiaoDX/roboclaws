from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from tests.contract.dev_tools.task_agent_just_recipes_support import (
    REPO_ROOT,
    just_bin,
)


def test_agent_eval_recommend_writes_eval_harness_manifest(tmp_path: Path) -> None:
    binary = just_bin()
    env = os.environ.copy()
    env["PATH"] = f"{Path(binary).parent}{os.pathsep}{env.get('PATH', '')}"
    output_dir = tmp_path / "eval-harness"
    result = subprocess.run(
        [
            binary,
            "agent::eval",
            "recommend",
            f"output_dir={output_dir}",
            "changed_file=roboclaws/agents/drivers/openai_agents_live.py",
            "budget=focused",
        ],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert f"eval harness manifest: {output_dir / 'eval_harness.json'}" in result.stdout
    manifest = json.loads((output_dir / "eval_harness.json").read_text(encoding="utf-8"))
    selected_row_ids = {row["row_id"] for row in manifest["rows"] if row["selected"]}
    assert manifest["schema"] == "roboclaws_eval_harness_manifest_v1"
    assert "openai-agents-sdk-open-task-live-eval" in selected_row_ids
