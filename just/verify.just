# Verification gate dispatcher.
#
# `verify::*` is the umbrella for confidence gates. It delegates scenario
# execution to `harness::*` where the gate drives a system under test.
#
# Preferred entrypoints:
# - just verify::static            lint/format/whitespace
# - just verify::mock              static + fast unit/mock tests
# - just verify::ci-required       required PR gate: mock + HTML report artifact
# - just verify::contract          focused fixture/schema/report contracts
# - just verify::household-world  public/private household-world cleanup proof
# - just verify::molmo-realworld-agent-mcp  ADR-0003 MCP smoke-agent proof
# - just verify::molmo-realworld-agent-dogfood-kit  ADR-0003 direct-agent kit proof
# - just verify::molmo-realworld-openclaw-dogfood-kit  ADR-0003 OpenClaw minimum-gate kit proof
# - just verify::molmo-realworld-openclaw-visual-dogfood-kit  ADR-0010 OpenClaw visual report proof
# - just verify::molmo-realworld-raw-fpv  ADR-0013 raw FPV-only observation proof
# - just verify::molmo-planner-proof-bundle-runner  proof-request dry-run handoff
# - just verify::molmo-planner-proof-bundle-execute-rerun  local GPU proof-bundle execution
# - just verify::molmo-planner-manipulation-probe  ADR-0014 planner manipulation proof gate
# - just verify::full-local        active deterministic local gates

set working-directory := '..'

standalone_pytest := "./scripts/dev/run_pytest_standalone.sh"

default:
    @just --list verify

# L0: static checks only.
static:
    #!/usr/bin/env bash
    set -euo pipefail
    ruff_bin="${ROBOCLAWS_RUFF:-}"
    if [[ -z "$ruff_bin" ]]; then
      if [[ -x ".venv/bin/ruff" ]]; then
        ruff_bin=".venv/bin/ruff"
      else
        ruff_bin="ruff"
      fi
    fi
    "$ruff_bin" check .
    "$ruff_bin" format --check .
    python scripts/dev/check_python_quality_ratchet.py
    git diff --check

# L1: static checks plus fast unit/mock tests.
mock:
    #!/usr/bin/env bash
    set -euo pipefail
    just verify::static
    just dev::test fast

# Required PR gate: deterministic checks plus active household report contracts.
ci-required output_dir="output/demo":
    #!/usr/bin/env bash
    set -euo pipefail
    output_dir="{{output_dir}}"
    output_dir="${output_dir#output_dir=}"
    python_bin="${ROBOCLAWS_PYTHON:-}"
    if [[ -z "$python_bin" ]]; then
      if [[ -x ".venv/bin/python" ]]; then
        python_bin=".venv/bin/python"
      else
        python_bin="python"
      fi
    fi
    just verify::mock
    ./scripts/dev/run_pytest_standalone.sh -q \
      tests/contract/reports/test_molmo_cleanup_report.py \
      tests/contract/reports/test_molmo_cleanup_artifact_report.py
    mkdir -p "$output_dir"

# L2: focused fixture/schema/report contracts.
contract:
    {{standalone_pytest}} -q \
      tests/contract/reports/test_molmo_cleanup_report.py \
      tests/contract/reports/test_molmo_cleanup_artifact_report.py \
      tests/contract/reports/test_molmo_report_visual_core.py

# ADR-0003 public/private cleanup gate. Requires the repo-local uv MolmoSpaces
# runtime for the harness; focused tests use the synthetic backend.
household-world generated_mess_count="10":
    #!/usr/bin/env bash
    set -euo pipefail
    {{standalone_pytest}} -q \
      tests/contract/molmo_cleanup/test_household_runtime_contract.py \
      tests/contract/molmo_cleanup/test_molmospaces_realworld_cleanup.py \
      tests/contract/checkers/test_check_molmo_realworld_cleanup_result.py \
      tests/contract/reports/test_molmo_cleanup_report.py \
      tests/contract/dev_tools/test_verify_just_recipes.py
    just harness::household-world "1 2 3" "output/household-world-harness" "帮我收拾这个房间" "{{generated_mess_count}}"

# ADR-0003 real-world MCP smoke-agent gate. Requires the repo-local uv
# MolmoSpaces runtime for the harness; focused tests use the synthetic backend.
molmo-realworld-agent-mcp generated_mess_count="10":
    #!/usr/bin/env bash
    set -euo pipefail
    {{standalone_pytest}} -q \
      tests/contract/molmo_cleanup/test_household_mcp_server.py \
      tests/contract/checkers/test_check_molmo_realworld_cleanup_result.py \
      tests/contract/molmo_cleanup/test_molmo_mcp_smoke_shared_semantic_loop.py \
      tests/contract/dev_tools/test_verify_just_recipes.py
    just harness::molmo-realworld-agent-mcp "1" "output/molmo-realworld-agent-mcp-harness" "帮我收拾这个房间" "{{generated_mess_count}}"

# ADR-0003 direct-agent dogfood kit gate. Real Codex/Claude/OpenClaw dogfood is
# local evidence; this focused gate proves the stricter skill, server setup,
# checker, and synthetic artifact shape stay wired.
molmo-realworld-agent-dogfood-kit:
    #!/usr/bin/env bash
    set -euo pipefail
    {{standalone_pytest}} -q \
      tests/contract/molmo_cleanup/test_household_agent_server.py \
      tests/contract/molmo_cleanup/test_household_mcp_server.py \
      tests/contract/checkers/test_check_molmo_realworld_cleanup_result.py \
      tests/contract/dev_tools/test_verify_just_recipes.py
    just harness::molmo-realworld-agent-dogfood-kit

# ADR-0003 OpenClaw dogfood kit gate. Real Gateway dogfood is local evidence;
# this focused gate proves the OpenClaw minimum checker and artifact shape.
molmo-realworld-openclaw-dogfood-kit:
    #!/usr/bin/env bash
    set -euo pipefail
    {{standalone_pytest}} -q \
      tests/contract/molmo_cleanup/test_household_mcp_server.py \
      tests/contract/checkers/test_check_molmo_realworld_cleanup_result.py \
      tests/contract/dev_tools/test_verify_just_recipes.py
    just harness::molmo-realworld-openclaw-dogfood-kit

# ADR-0010 OpenClaw visual dogfood kit gate. Real Gateway dogfood is local
# evidence; this focused gate proves the OpenClaw-labeled visual report shape.
molmo-realworld-openclaw-visual-dogfood-kit generated_mess_count="10":
    #!/usr/bin/env bash
    set -euo pipefail
    {{standalone_pytest}} -q \
      tests/contract/molmo_cleanup/test_household_mcp_server.py \
      tests/contract/checkers/test_check_molmo_realworld_cleanup_result.py \
      tests/contract/reports/test_molmo_cleanup_report.py \
      tests/contract/dev_tools/test_verify_just_recipes.py
    just harness::molmo-realworld-openclaw-visual-dogfood-kit "7" "output/molmo-realworld-openclaw-visual-dogfood-kit" "帮我收拾这个房间" "{{generated_mess_count}}"

# ADR-0013 raw FPV-only observation gate. Requires the repo-local uv
# MolmoSpaces runtime and local robot assets for the harness evidence.
molmo-realworld-raw-fpv generated_mess_count="10":
    #!/usr/bin/env bash
    set -euo pipefail
    {{standalone_pytest}} -q \
      tests/contract/molmo_cleanup/test_household_runtime_contract.py \
      tests/contract/molmo_cleanup/test_household_mcp_server.py \
      tests/contract/reports/test_molmo_cleanup_report.py \
      tests/contract/checkers/test_check_molmo_realworld_cleanup_result.py \
      tests/contract/dev_tools/test_verify_just_recipes.py
    just harness::molmo-realworld-raw-fpv "7" "output/molmo-realworld-raw-fpv-harness" "帮我收拾这个房间" "{{generated_mess_count}}"

# ADR-0042 proof-bundle runner dry-run handoff. Real planner execution remains
# an explicit local-dev follow-up outside this default verify gate.
molmo-planner-proof-bundle-runner:
    #!/usr/bin/env bash
    set -euo pipefail
    {{standalone_pytest}} -q \
      tests/contract/dev_tools/test_verify_just_recipes.py \
      tests/unit/scripts/test_run_molmo_planner_proof_bundle_from_requests.py \
      tests/contract/checkers/test_check_molmo_planner_proof_bundle_runner_result.py
    just harness::molmo-planner-proof-bundle-runner

# ADR-0044 local-dev proof-bundle execution gate. Requires local CUDA and
# MolmoSpaces/RBY1M/CuRobo runtime; not part of default CI.
molmo-planner-proof-bundle-execute-rerun:
    #!/usr/bin/env bash
    set -euo pipefail
    {{standalone_pytest}} -q \
      tests/contract/dev_tools/test_verify_just_recipes.py \
      tests/unit/scripts/test_run_molmo_planner_proof_bundle_from_requests.py \
      tests/contract/checkers/test_check_molmo_planner_proof_bundle_runner_result.py \
      tests/contract/checkers/test_check_molmo_realworld_cleanup_result.py
    just harness::molmo-planner-proof-bundle-execute-rerun

# ADR-0014 planner-backed manipulation proof gate. Default verification accepts
# explicit blocked-capability evidence; strict planner-backed proof uses the
# checker --require-planner-backed flag outside this default gate.
molmo-planner-manipulation-probe:
    #!/usr/bin/env bash
    set -euo pipefail
    {{standalone_pytest}} -q \
      tests/contract/reports/test_molmo_cleanup_report.py \
      tests/unit/molmo_cleanup/test_molmo_manipulation_provenance.py \
      tests/contract/checkers/test_check_molmo_planner_manipulation_probe.py \
      tests/contract/dev_tools/test_verify_just_recipes.py
    just harness::molmo-planner-manipulation-probe

# Full local confidence ladder for active deterministic gates.
full-local:
    #!/usr/bin/env bash
    set -euo pipefail
    just verify::mock
    just verify::contract
