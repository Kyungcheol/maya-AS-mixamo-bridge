from __future__ import annotations

import pytest

from as_mixamo_bridge.models import BridgeError, CharacterContext, FrameRange, SwitchEvent
from as_mixamo_bridge.pose_bake import PosePassResult
from as_mixamo_bridge.profiles import load_profile
from as_mixamo_bridge.semantic import apply_semantic_pass, extract_switch_events


class EventScene:
    def __init__(self):
        self.keys = {"LeftHand_Options.FK_IK": (1001.0, 1010.0, 1020.0)}
        self.values = {
            ("LeftHand_Options.FK_IK", 1001.0): 0.0,
            ("LeftHand_Options.FK_IK", 1010.0): 1.0,
            ("LeftHand_Options.FK_IK", 1020.0): 0.0,
        }

    def key_times(self, node, attributes=None):
        attribute = attributes[0]
        return self.keys.get(f"{node}.{attribute}", ())

    def value_at(self, plug, frame):
        return self.values[(plug, frame)]


def test_extract_switch_events_normalizes_0_1_and_preserves_frames():
    """Catches copying studio switch numbers directly into AS's 0–10 channel."""
    profile = load_profile("studio_mixamo_teamextra01_v1")
    context = CharacterContext(
        "|Character",
        profile.profile_id,
        nodes={"switch:arm_l": "LeftHand_Options"},
    )

    events = extract_switch_events(EventScene(), context, profile, FrameRange(1001, 1020))

    assert events == (
        SwitchEvent(1010.0, "switch:arm_l", 0.0, 1.0),
        SwitchEvent(1020.0, "switch:arm_l", 1.0, 0.0),
    )


def test_every_studio_space_event_has_an_explicit_as_target_mapping():
    """Catches source parent/follow events becoming unsupported only after pose bake."""
    studio = load_profile("studio_mixamo_teamextra01_v1")
    advanced = load_profile("as_belato01_v1")
    assert set(studio.spaces).issubset(advanced.spaces)


class SemanticScene:
    def __init__(self, fail=False):
        self.layers = {"FKPose"}
        self.keys = []
        self.fail = fail

    def create_override_layer(self, name):
        self.layers.add(name)
        return name

    def delete_layer(self, layer):
        self.layers.discard(layer)

    def match_switch(self, target, profile, channel, frames, layer):
        if self.fail:
            raise RuntimeError("injected semantic failure")
        self.keys.append(("match", channel, frames, layer))

    def key_switch(self, plug, value, frame, layer):
        self.keys.append((plug, value, frame, layer))


class RecordingTransaction:
    def __init__(self):
        self.layers = []

    def record_layer(self, layer):
        self.layers.append(layer)


def _as_target():
    profile = load_profile("as_belato01_v1")
    return profile, CharacterContext(
        "|Character",
        profile.profile_id,
        nodes={
            "switch:arm_l": "FKIKArm_L",
            "space:arm_l_follow": "IKArm_L",
        },
    )


def test_semantic_pass_maps_normalized_ik_to_as_10_and_matches_boundaries():
    """Catches switch pops and the wrong target switch scale."""
    profile, target = _as_target()
    scene = SemanticScene()
    tx = RecordingTransaction()
    pose = PosePassResult("FKPose", (), tuple(float(frame) for frame in range(1001, 1021)))

    result = apply_semantic_pass(
        scene,
        pose,
        (SwitchEvent(1010, "switch:arm_l", 0.0, 1.0),),
        tx,
        target=target,
        profile=profile,
    )

    assert result.layer == "FKPose_Semantic"
    assert ("FKIKArm_L.FKIKBlend", 10.0, 1010, result.layer) in scene.keys
    assert ("match", "switch:arm_l", (1009.0, 1010.0, 1011.0), result.layer) in scene.keys
    assert tx.layers == [result.layer]


def test_unsupported_space_is_reported_and_semantic_layer_is_removed():
    """Catches silent substitution of a source space the AS profile cannot represent."""
    profile, target = _as_target()
    scene = SemanticScene()
    with pytest.raises(BridgeError, match="unsupported space"):
        apply_semantic_pass(
            scene,
            PosePassResult("FKPose", (), (1.0, 2.0, 3.0)),
            (SwitchEvent(2, "space:not_mapped", "world", "prop"),),
            RecordingTransaction(),
            target=target,
            profile=profile,
        )
    assert scene.layers == {"FKPose"}


def test_semantic_failure_rolls_back_but_keeps_fk_fallback():
    """Catches semantic errors destroying the already verified FK result."""
    profile, target = _as_target()
    scene = SemanticScene(fail=True)
    with pytest.raises(RuntimeError, match="injected"):
        apply_semantic_pass(
            scene,
            PosePassResult("FKPose", (), (1.0, 2.0, 3.0)),
            (SwitchEvent(2, "switch:arm_l", 0.0, 1.0),),
            RecordingTransaction(),
            target=target,
            profile=profile,
        )
    assert scene.layers == {"FKPose"}
