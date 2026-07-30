from __future__ import annotations

import pytest

from roboclaws.core.raw_fpv_guidance import (
    RAW_FPV_PUBLIC_CLEANUP_PRIORITY_EXAMPLES,
    RAW_FPV_PUBLIC_SETTLED_EXAMPLES,
    raw_fpv_inline_candidate_instruction,
)
from roboclaws.household.semantic_acceptability import public_source_requires_cleanup


@pytest.mark.parametrize(
    ("object_category", "source_category"),
    RAW_FPV_PUBLIC_CLEANUP_PRIORITY_EXAMPLES,
)
def test_raw_fpv_priority_examples_require_public_cleanup(
    object_category: str,
    source_category: str,
) -> None:
    assert public_source_requires_cleanup(object_category, source_category) is True


@pytest.mark.parametrize(
    ("object_category", "source_category"),
    RAW_FPV_PUBLIC_SETTLED_EXAMPLES,
)
def test_raw_fpv_settled_examples_do_not_require_public_cleanup(
    object_category: str,
    source_category: str,
) -> None:
    assert public_source_requires_cleanup(object_category, source_category) is False


def test_raw_fpv_instruction_prioritizes_wrong_support_and_skips_settled_distractors() -> None:
    instruction = raw_fpv_inline_candidate_instruction("raw_fpv_001")

    assert "dish on bed" in instruction
    assert "electronics on dining table" in instruction
    assert "skip already settled distractors" in instruction
    assert "food on countertop" in instruction
