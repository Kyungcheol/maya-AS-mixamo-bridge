from __future__ import annotations

import math

import pytest

from as_mixamo_bridge.models import BridgeError
from as_mixamo_bridge.neutral import (
    calibration_matrix,
    invert_matrix,
    multiply_matrices,
    root_relative_matrix,
    validate_matrix,
)


IDENTITY = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)


def translation(x, y, z, scale=1.0):
    return (
        scale, 0.0, 0.0, 0.0,
        0.0, scale, 0.0, 0.0,
        0.0, 0.0, scale, 0.0,
        float(x), float(y), float(z), 1.0,
    )


def test_root_relative_matrix_removes_world_translation_and_scale():
    """Catches origin- or character-scale-dependent motion capture."""
    root = translation(100, 0, -20, scale=2)
    joint = multiply_matrices(translation(1, 3, 4), root)

    relative = root_relative_matrix(joint, root)

    assert relative == pytest.approx(translation(1, 3, 4))


def test_calibration_maps_source_rest_to_target_rest():
    """Catches rest-pose offsets being applied in the wrong matrix order."""
    source = translation(2, 0, 0)
    target = translation(5, 1, 0)
    offset = calibration_matrix(source, target)

    assert multiply_matrices(source, offset) == pytest.approx(target)


def test_inverse_round_trip_preserves_affine_matrix():
    """Catches an inverse implementation that loses scale or translation."""
    matrix = translation(4, -2, 8, scale=1.5)
    assert multiply_matrices(matrix, invert_matrix(matrix)) == pytest.approx(IDENTITY)


@pytest.mark.parametrize(
    "matrix",
    [
        (0.0,) * 16,
        IDENTITY[:-1] + (math.nan,),
        IDENTITY[:-1] + (math.inf,),
    ],
)
def test_invalid_matrices_stop_before_scene_mutation(matrix):
    """Catches singular or non-finite input propagating corrupt animation."""
    with pytest.raises(BridgeError):
        validate_matrix(matrix, require_invertible=True)
