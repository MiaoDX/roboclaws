# Phase 2 Validation Contract

## Requirement Matrix

| Requirement | Focused proof | Planned owner |
|---|---|---|
| Reconstruct before hard failure | Soft-watermark synthetic input invokes assembler before legacy guard | `02-01`, `02-02` |
| Reserve output and safety capacity | Admission arithmetic rejects input when expected output plus safety reserve exceed hard limit | `02-01` |
| Ordered eviction | Optional retrieval is removed before oldest raw overlap; snapshot critical fields remain | `02-01` |
| Bounded growth and residual overflow | Synthetic growth stays under hard limit after eviction; irreducible overflow checkpoints once, emits evidence, and sends no duplicate payload | `02-02` |

## Commands

```bash
./scripts/dev/run_pytest_standalone.sh -q tests/unit/agents/test_openai_agents_context_assembler.py tests/unit/agents/test_openai_agents_budget_sources.py
./scripts/dev/run_pytest_standalone.sh -q tests/unit/agents/test_live_runtime_budget.py tests/unit/agents/test_openai_agents_input_window.py
ruff check roboclaws/agents/drivers/openai_agents_context_assembler.py roboclaws/agents/drivers/openai_agents_budget.py roboclaws/agents/drivers/openai_agents_compaction.py roboclaws/agents/drivers/openai_agents_run_config.py
ruff format --check roboclaws/agents/drivers/openai_agents_context_assembler.py roboclaws/agents/drivers/openai_agents_budget.py roboclaws/agents/drivers/openai_agents_compaction.py roboclaws/agents/drivers/openai_agents_run_config.py
```

Execution remains responsible for running these gates; this planning phase
does not implement product code or claim runtime proof.
