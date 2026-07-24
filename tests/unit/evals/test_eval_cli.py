from __future__ import annotations

import subprocess
import sys


def test_eval_cli_import_does_not_require_session_live_dependencies() -> None:
    script = """
import builtins

original_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name == "mcp" or name.startswith("mcp."):
        raise ModuleNotFoundError("mcp is intentionally unavailable")
    return original_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
import roboclaws.evals.cli
"""

    subprocess.run([sys.executable, "-c", script], check=True)
