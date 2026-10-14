from __future__ import annotations

import pytest

pytest.importorskip("maya.cmds")

import maya.cmds as cmds

from as_mixamo_bridge.models import CharacterContext, SwitchEvent
from as_mixamo_bridge.pose_bake import PosePassResult
from as_mixamo_bridge.profiles import load_profile
from as_mixamo_bridge.semantic import MayaSemanticScene, apply_semantic_pass
from as_mixamo_bridge.transaction import BridgeTransaction, MayaTransactionScene


def setup_module():
    import maya.standalone
    try:
        maya.standalone.initialize(name="python")
    except RuntimeError:
        pass


def teardown_function():
    cmds.file(new=True, force=True)


def test_maya_semantic_layer_keys_switch_and_follow_with_boundary_matches():
    profile = load_profile("as_belato01_v1")
    controls = {}
    for key in (
        "FKShoulder_L", "FKElbow_L", "FKWrist_L", "IKArm_L", "PoleArm_L"
    ):
        controls[key] = cmds.createNode("transform", name=key)
    switch = cmds.createNode("transform", name="FKIKArm_L")
    cmds.addAttr(switch, longName="FKIKBlend", attributeType="double", keyable=True)
    cmds.addAttr(controls["IKArm_L"], longName="follow", attributeType="double", keyable=True)
    context = CharacterContext(
        "|Character",
        profile.profile_id,
        nodes={
            "control:fk:left_upper_arm": controls["FKShoulder_L"],
            "control:fk:left_lower_arm": controls["FKElbow_L"],
            "control:fk:left_hand": controls["FKWrist_L"],
            "control:ik:left_hand": controls["IKArm_L"],
            "control:pole:left_elbow": controls["PoleArm_L"],
            "switch:arm_l": switch,
            "space:arm_l_follow": controls["IKArm_L"],
        },
    )
    fk_layer = cmds.animLayer("FKPose", override=True)
    tx = BridgeTransaction.begin(MayaTransactionScene(), context, session_id="semantic")
    result = apply_semantic_pass(
        MayaSemanticScene(),
        PosePassResult(fk_layer, tuple(controls.values()), tuple(float(x) for x in range(1, 21))),
        (
            SwitchEvent(10, "switch:arm_l", 0.0, 1.0),
            SwitchEvent(15, "space:arm_l_follow", "world", "body"),
        ),
        tx,
        target=context,
        profile=profile,
    )

    assert cmds.objExists(result.layer)
    assert cmds.keyframe(f"{switch}.FKIKBlend", query=True, timeChange=True) == [10.0]
    assert cmds.keyframe(f"{controls['IKArm_L']}.follow", query=True, timeChange=True) == [15.0]
    hand_keys = cmds.keyframe(controls["IKArm_L"], query=True, timeChange=True) or []
    assert set(hand_keys).issubset({9.0, 10.0, 11.0, 14.0, 15.0, 16.0})
