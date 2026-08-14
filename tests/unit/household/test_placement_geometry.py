from __future__ import annotations

from roboclaws.backends.isaaclab import isaac_placement_resolution
from roboclaws.backends.molmospaces import placement as molmospaces_placement
from roboclaws.household import placement_geometry


def test_backends_share_canonical_placement_geometry() -> None:
    for name in (
        "surface_candidate_positions",
        "candidate_has_direct_support",
        "aabb_xy_overlaps",
        "elevated_position_over_surface",
    ):
        canonical = getattr(placement_geometry, name)
        assert getattr(isaac_placement_resolution, name) is canonical
        assert getattr(molmospaces_placement, name) is canonical


def test_surface_candidate_geometry_preserves_rotation_and_support_bounds() -> None:
    surface = {
        "center": [1.0, 2.0],
        "top_z": 0.75,
        "half_extents": [0.5, 0.4],
    }

    candidates = placement_geometry.surface_candidate_positions(
        surface,
        footprint=(0.1, 0.05),
        bottom_offset=0.2,
        clearance=0.015,
        index=2,
    )

    assert candidates[0] == [1.198, 2.0, 0.965]
    assert len(candidates) == 9
    assert all(
        placement_geometry.candidate_has_direct_support(candidate, surface, (0.1, 0.05))
        for candidate in candidates
    )


def test_aabb_overlap_margin_and_elevated_fallback() -> None:
    other = {"min_x": 1.02, "max_x": 2.0, "min_y": -0.5, "max_y": 0.5}

    assert not placement_geometry.aabb_xy_overlaps((0.0, 1.0, -0.5, 0.5), other, margin=0.0)
    assert placement_geometry.aabb_xy_overlaps((0.0, 1.0, -0.5, 0.5), other, margin=0.02)
    assert placement_geometry.elevated_position_over_surface(
        {"center": [1.1234567, 2.7654321], "top_z": 0.75},
        bottom_offset=0.2,
    ) == [1.123457, 2.765432, 1.03]
