# Test Organization

The suite is organized by confidence layer first and by domain second. The
top-level folder controls the default pytest marker, while domain folders keep
related tests close enough to scan.

```text
tests/
  unit/
  contract/
  integration/
  fixtures/
  support/
```

## Layers

- `unit`: fast, isolated behavior through public module APIs.
- `contract`: public schemas, CLI/recipe shapes, MCP tools, reports, replay
  artifacts, and compatibility promises.
- `integration`: process, Docker, external CLI, provider, simulator, or other
  environment-bound tests.
- `local`: requires local GPU, paid API key, real simulator, or backend service.
- `slow`: CI-safe but expensive enough to keep out of tight loops.

## Common Commands

```bash
./scripts/dev/run_pytest_standalone.sh -m unit -q
./scripts/dev/run_pytest_standalone.sh -m contract -q
./scripts/dev/run_pytest_standalone.sh -m "not integration and not local and not slow" -q
```

`tests/conftest.py` auto-marks tests from the top-level folder. It still has a
filename fallback for any short-lived legacy flat files, but new tests should go
directly into the right layer and domain folder.

Slow tight-loop exclusions are maintained in `tests/conftest.py`.

## Keep Or Delete

Keep tests that protect parser fallback behavior, safety defaults, public tool
contracts, trace/replay/report schemas, CLI output, or a known regression.

Merge or delete tests that only assert dataclass mechanics, copied constants,
private helper calls, or file existence without a runtime/package contract.
