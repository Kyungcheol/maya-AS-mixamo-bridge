from __future__ import annotations

import pytest

from as_mixamo_bridge.semantic import solve_pole_vector


def test_pole_vector_points_away_from_limb_plane():
    """Catches a pole solve placed on the bone line instead of the bend plane."""
    result = solve_pole_vector((0, 0, 0), (1, 1, 0), (2, 0, 0))
    assert result == pytest.approx((1, 3, 0))


def test_collinear_limb_uses_previous_side_stably():
    """Catches pole-vector flips when the limb becomes momentarily straight."""
    result = solve_pole_vector(
        (0, 0, 0), (1, 0, 0), (2, 0, 0), previous=(1, 0, 2)
    )
    assert result == pytest.approx((1, 0, 2))


def test_collinear_limb_without_history_uses_deterministic_perpendicular():
    """Catches NaN output on the first straight-limb frame."""
    result = solve_pole_vector((0, 0, 0), (1, 0, 0), (2, 0, 0))
    assert result == pytest.approx((1, 0, 2))
