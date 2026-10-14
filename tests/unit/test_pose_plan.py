from __future__ import annotations

import pytest

from as_mixamo_bridge.models import BridgeError, CharacterContext, FrameRange
from as_mixamo_bridge.neutral import NeutralMotion
from as_mixamo_bridge.pose_bake import build_fk_bake_plan
from as_mixamo_bridge.profiles import load_profile


IDENTITY = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)


def _motion(profile):
    joints = {semantic: IDENTITY for semantic in profile.skeleton}
    return NeutralMotion(
        FrameRange(1001, 1002),
        (1001.0, 1002.0),
        {1001.0: IDENTITY, 1002.0: IDENTITY},
        {1001.0: joints, 1002.0: joints},
        {semantic: f"neutral_{semantic}" for semantic in profile.skeleton},
        24.0,
    )


def _target(profile):
    nodes = {}
    for group, mapping in profile.controls.items():
        for semantic in mapping:
            nodes[f"control:{group}:{semantic}"] = f"target_{group}_{semantic}"
    return CharacterContext("|Character", profile.profile_id, nodes=nodes)


def test_fk_plan_has_exact_frames_and_only_body_controls():
    """Catches sparse/retimed plans or accidental face-control inclusion."""
    profile = load_profile("as_belato01_v1")
    plan = build_fk_bake_plan(_motion(profile), _target(profile), profile)

    assert plan.frames == (1001.0, 1002.0)
    assert {target.semantic for target in plan.targets}.issuperset(
        {"hips", "head", "left_hand", "right_foot"}
    )
    assert all("face" not in target.control.lower() for target in plan.targets)
    assert all(target.semantic in profile.skeleton for target in plan.targets)


def test_fk_plan_rejects_missing_control_before_layer_creation():
    """Catches a partial bake plan that would silently omit a body part."""
    profile = load_profile("as_belato01_v1")
    target = _target(profile)
    nodes = dict(target.nodes)
    del nodes["control:fk:head"]

    with pytest.raises(BridgeError, match="head"):
        build_fk_bake_plan(
            _motion(profile),
            CharacterContext(target.root, target.profile_id, nodes=nodes),
            profile,
        )


def test_fk_plan_rejects_profile_mismatch():
    """Catches applying an AS plan to the wrong detected character profile."""
    profile = load_profile("as_belato01_v1")
    target = _target(profile)
    wrong = CharacterContext(target.root, "other_profile", nodes=target.nodes)
    with pytest.raises(BridgeError, match="profile"):
        build_fk_bake_plan(_motion(profile), wrong, profile)
