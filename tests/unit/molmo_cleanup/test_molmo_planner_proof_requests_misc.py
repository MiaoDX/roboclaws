from __future__ import annotations

from roboclaws.household.semantic_timeline import canonical_cleanup_tool_sequence


def test_canonical_cleanup_tool_sequence_uses_semantic_order() -> None:
    assert canonical_cleanup_tool_sequence(
        "navigate_to_object,navigate_to_receptacle,open_receptacle,pick,place_inside"
    ) == [
        "navigate_to_object",
        "pick",
        "navigate_to_receptacle",
        "open_receptacle",
        "place_inside",
    ]
