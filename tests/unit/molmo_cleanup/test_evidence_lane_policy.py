from __future__ import annotations

import pytest

from roboclaws.household.evidence_lane_policy import evidence_lane_compatibility


def test_raw_fpv_rejects_route_incompatible_model_override() -> None:
    with pytest.raises(
        ValueError,
        match=("model 'MiniMax-M3' is incompatible with provider_profile 'kimi-openai-chat'"),
    ):
        evidence_lane_compatibility(
            evidence_lane="camera-raw-fpv",
            agent_engine="openai-agents-sdk",
            provider_profile="kimi-openai-chat",
            model_id="MiniMax-M3",
        )


def test_raw_fpv_still_reports_image_transport_for_route_compatible_model() -> None:
    compatibility = evidence_lane_compatibility(
        evidence_lane="camera-raw-fpv",
        agent_engine="openai-agents-sdk",
        provider_profile="kimi-openai-chat",
        model_id="kimi-k2.7-code",
    )

    assert compatibility.allowed is False
    assert "image_transport=unsupported" in compatibility.reason
