from __future__ import annotations

from scripts.molmo_cleanup.molmospaces_rendering import inflate_bbox


def test_inflate_bbox_keeps_top_edge_box_ordered_below_header() -> None:
    assert inflate_bbox(20, 0, 30, 4, (360, 540, 3)) == (9, 29, 41, 29)


def test_inflate_bbox_clips_bottom_right_box_without_reversing_edges() -> None:
    left, top, right, bottom = inflate_bbox(535, 355, 539, 359, (360, 540, 3))

    assert (left, top, right, bottom) == (521, 341, 539, 359)
