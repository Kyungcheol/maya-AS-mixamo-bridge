from __future__ import annotations

import math

import pytest

from as_mixamo_bridge.models import CharacterContext, FrameRange, SwitchEvent
from as_mixamo_bridge.neutral import NeutralMotion
from as_mixamo_bridge.profiles import load_profile
from as_mixamo_bridge.validation import validate_motion


def translation(x=0.0, y=0.0, z=0.0):
    return (
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        x, y, z, 1.0,
    )


def rotation_z(degrees):
    radians = math.radians(degrees)
    c, s = math.cos(radians), math.sin(radians)
    return (
        c, s, 0.0, 0.0,
        -s, c, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    )


class ValidationScene:
    def __init__(self, samples, unkeyable=()):
        self.samples = samples
        self.frame = 1.0
        self.unkeyable = set(unkeyable)

    def set_time(self, frame):
        self.frame = frame

    def world_matrix(self, node):
        return self.samples[(self.frame, node)]

    def is_keyable(self, node):
        return node not in self.unkeyable


def fixture_motion(actual_overrides=None, controls=None):
    profile = load_profile("as_belato01_v1")
    frames = (1.0, 2.0)
    relative = {semantic: translation() for semantic in profile.skeleton}
    neutral = NeutralMotion(
        FrameRange(1, 2), frames,
        {1.0: translation(), 2.0: translation()},
        {1.0: relative, 2.0: relative}, {}, 30.0,
    )
    nodes = {f"joint:{semantic}": semantic for semantic in profile.skeleton}
    if controls:
        nodes.update(controls)
    samples = {(frame, semantic): translation() for frame in frames for semantic in profile.skeleton}
    samples.update(actual_overrides or {})
    return profile, neutral, CharacterContext("|Character", profile.profile_id, nodes=nodes), samples


@pytest.mark.parametrize(
    ("semantic", "matrix", "passes", "category"),
    [
        ("left_foot", translation(0.1, 0, 0), True, None),
        ("left_foot", translation(0.1001, 0, 0), False, "position"),
        ("left_hand", rotation_z(0.1), True, None),
        ("left_hand", rotation_z(0.1001), False, "orientation"),
        ("left_upper_arm", rotation_z(0.25), True, None),
        ("left_upper_arm", rotation_z(0.2501), False, "orientation"),
    ],
)
def test_validation_threshold_boundaries(semantic, matrix, passes, category):
    """Catches inclusive tolerances or wrong per-body-part limits."""
    profile, neutral, target, samples = fixture_motion({(2.0, semantic): matrix})
    report = validate_motion(ValidationScene(samples), neutral, target, profile)
    assert report.passed is passes
    if category:
        assert any(issue.category == category and issue.body_part == semantic for issue in report.issues)


def test_stationary_foot_drift_beyond_point_one_cm_fails():
    """Catches a planted neutral foot sliding in the final AS deformation."""
    profile, neutral, target, samples = fixture_motion({(2.0, "left_foot"): translation(0.1001, 0, 0)})
    report = validate_motion(ValidationScene(samples), neutral, target, profile)
    assert any(issue.category == "contact_drift" for issue in report.issues)


@pytest.mark.parametrize("bad", [(0.0,) * 16, translation()[:-1] + (math.nan,)])
def test_invalid_matrix_is_reported_not_accepted(bad):
    """Catches corrupt numeric data being treated as a small error."""
    profile, neutral, target, samples = fixture_motion({(1.0, "left_hand"): bad})
    report = validate_motion(ValidationScene(samples), neutral, target, profile)
    assert not report.passed
    assert any(issue.category == "invalid_matrix" for issue in report.issues)


def test_unkeyable_target_control_fails_preflight():
    """Catches a result that cannot be reproduced by its declared AS control."""
    controls = {"control:ik:left_hand": "IKArm_L"}
    profile, neutral, target, samples = fixture_motion(controls=controls)
    report = validate_motion(
        ValidationScene(samples, unkeyable={"IKArm_L"}), neutral, target, profile
    )
    assert any(issue.category == "unkeyable_control" for issue in report.issues)


def test_switch_frame_discontinuity_is_named():
    """Catches a visible hand pop hidden among ordinary per-frame errors."""
    profile, neutral, target, samples = fixture_motion({(2.0, "left_hand"): translation(0.2, 0, 0)})
    report = validate_motion(
        ValidationScene(samples), neutral, target, profile,
        events=(SwitchEvent(2, "switch:arm_l", 0.0, 1.0),),
    )
    assert any(issue.category == "switch_discontinuity" and issue.frame == 2 for issue in report.issues)
