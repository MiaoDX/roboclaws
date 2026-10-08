import pytest

from roboclaws.evals import runner
from roboclaws.evals.live_runtime import live_surface_env


def test_cli_forwards_explicit_total_budget(monkeypatch):
    captured = {}
    monkeypatch.setattr(runner, "run_eval_suite", lambda *args, **kw: captured.update(kw))
    runner.run_eval_from_overrides({"live_total_token_budget": "4000000"})
    assert captured["live_total_token_budget"] == 4_000_000


def test_eval_does_not_inherit_unrecorded_total_budget():
    env = live_surface_env({}, base_env={"ROBOCLAWS_EVAL_TOTAL_TOKEN_BUDGET": "4000000"})
    assert "ROBOCLAWS_EVAL_TOTAL_TOKEN_BUDGET" not in env


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_eval_rejects_invalid_total_budget_before_launch(value):
    with pytest.raises(ValueError, match="total_token_budget"):
        live_surface_env({"live_total_token_budget": value}, base_env={})
