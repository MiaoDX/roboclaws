from __future__ import annotations

from types import SimpleNamespace

import pytest

from roboclaws.backends.molmospaces import rendering
from roboclaws.backends.molmospaces.rendering import inflate_bbox


def test_inflate_bbox_keeps_top_edge_box_ordered_below_header() -> None:
    assert inflate_bbox(20, 0, 30, 4, (360, 540, 3)) == (9, 29, 41, 29)


def test_inflate_bbox_clips_bottom_right_box_without_reversing_edges() -> None:
    left, top, right, bottom = inflate_bbox(535, 355, 539, 359, (360, 540, 3))

    assert (left, top, right, bottom) == (521, 341, 539, 359)


def test_render_segmentation_disables_msaa_and_restores_model_quality(monkeypatch) -> None:
    render_offsamples = []
    closed = []
    model = SimpleNamespace(vis=SimpleNamespace(quality=SimpleNamespace(offsamples=4)))

    class FakeRenderer:
        def __init__(self, _model, **_kwargs) -> None:
            render_offsamples.append(model.vis.quality.offsamples)

        def update_scene(self, _data, *, camera) -> None:
            assert camera == "robot_0/head_camera"

        def render(self):
            render_offsamples.append(model.vis.quality.offsamples)
            return "segmentation"

        def enable_segmentation_rendering(self) -> None:
            return None

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(rendering.mujoco, "Renderer", FakeRenderer)

    result = rendering.render_segmentation(
        model,
        object(),
        "robot_0/head_camera",
        width=640,
        height=480,
        render_dimensions=lambda width, height: (width, height),
        ensure_offscreen_framebuffer=lambda *_args, **_kwargs: None,
    )

    assert result == "segmentation"
    assert render_offsamples == [0, 0, 0]
    assert model.vis.quality.offsamples == 4
    assert closed == [True]


def test_render_segmentation_restores_msaa_when_renderer_close_fails(monkeypatch) -> None:
    model = SimpleNamespace(vis=SimpleNamespace(quality=SimpleNamespace(offsamples=8)))

    class FakeRenderer:
        def __init__(self, _model, **_kwargs) -> None:
            assert model.vis.quality.offsamples == 0

        def update_scene(self, _data, *, camera) -> None:
            return None

        def render(self):
            return "segmentation"

        def enable_segmentation_rendering(self) -> None:
            return None

        def close(self) -> None:
            raise RuntimeError("close failed")

    monkeypatch.setattr(rendering.mujoco, "Renderer", FakeRenderer)

    with pytest.raises(RuntimeError, match="close failed"):
        rendering.render_segmentation(
            model,
            object(),
            "robot_0/head_camera",
            width=640,
            height=480,
            render_dimensions=lambda width, height: (width, height),
            ensure_offscreen_framebuffer=lambda *_args, **_kwargs: None,
        )

    assert model.vis.quality.offsamples == 8
