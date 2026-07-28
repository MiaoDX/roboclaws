from __future__ import annotations

from types import SimpleNamespace

import pytest

from roboclaws.household.task_intent import (
    household_intent_from_args,
    normalize_household_intent,
)


def test_current_household_intents_normalize_from_public_tokens() -> None:
    assert normalize_household_intent("cleanup") == "cleanup"
    assert normalize_household_intent("map-build") == "map-build"
    assert normalize_household_intent("open-ended") == "open-ended"


@pytest.mark.parametrize(
    "value",
    ("semantic-map-build", "household-world.cleanup", "household-world.map-build"),
)
def test_removed_task_named_tokens_are_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="unsupported household intent"):
        normalize_household_intent(value)


def test_household_intent_from_args_ignores_removed_task_name_field() -> None:
    args = SimpleNamespace(task_name="semantic-map-build", intent="")

    assert household_intent_from_args(args, env={}, fallback="cleanup") == "cleanup"
