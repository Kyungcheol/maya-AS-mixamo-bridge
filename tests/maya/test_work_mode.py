from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("maya.cmds")

import maya.cmds as cmds

from as_mixamo_bridge.adapter import MayaAdapterScene, create_adapter
from as_mixamo_bridge.commands import BridgeController, MayaBridgeServices
from as_mixamo_bridge.detection import detect_character
from as_mixamo_bridge.profiles import load_profile
from as_mixamo_bridge.scene import MayaSceneQuery
from as_mixamo_bridge.transaction import BridgeTransaction, MayaTransactionScene


def setup_module():
    import maya.standalone
    try:
        maya.standalone.initialize(name="python")
    except RuntimeError:
        pass


def teardown_function():
    cmds.file(new=True, force=True)


def _leaf(node):
    return node.rsplit("|", 1)[-1].rsplit(":", 1)[-1]


def test_work_mode_adapter_is_tagged_lightweight_and_excludes_face():
    source_path = os.environ.get("ASMB_AS_RIG")
    if not source_path or not Path(source_path).is_file():
        pytest.skip("ASMB_AS_RIG does not point to the supplied AS rig")
    cmds.file(source_path, open=True, force=True, prompt=False, ignoreVersion=True)
    profile = load_profile("as_belato01_v1")
    selected = next(node for node in cmds.ls(long=True) if _leaf(node) == "RootX_M")
    context = detect_character(MayaSceneQuery(), selected, [profile])
    before_skin = set(cmds.ls(type="skinCluster") or [])
    tx = BridgeTransaction.begin(MayaTransactionScene(), context, session_id="adapter_test")

    adapter = create_adapter(MayaAdapterScene(), context, profile, tx)

    assert set(cmds.ls(type="skinCluster") or []) == before_skin
    assert adapter.controls
    for node in adapter.owned_nodes:
        if cmds.objExists(node):
            assert cmds.objExists(f"{node}.asmbSessionId")
            assert cmds.getAttr(f"{node}.asmbSessionId") == "adapter_test"
    protected = set(cmds.editDisplayLayerMembers(adapter.protection_layer, query=True, fullNames=True) or [])
    assert any(_leaf(node) == "FKHead_M" for node in protected)
    assert all("FaceMotionSystem" not in node and "FaceGroup" not in node for node in protected)
    face_control = next((node for node in cmds.ls(long=True) if _leaf(node) == "ctrlBox"), None)
    if face_control:
        assert face_control not in protected

    tx.restore()
    assert not cmds.objExists(adapter.root)


def test_work_mode_bakes_exact_as_result_to_recoverable_layer():
    source_path = os.environ.get("ASMB_AS_RIG")
    if not source_path or not Path(source_path).is_file():
        pytest.skip("ASMB_AS_RIG does not point to the supplied AS rig")
    cmds.file(source_path, open=True, force=True, prompt=False, ignoreVersion=True)
    selected = next(node for node in cmds.ls(long=True) if _leaf(node) == "RootX_M")
    controller = BridgeController(MayaBridgeServices())
    session = controller.enter_work_mode(selected)
    adapter_root = session.adapter.controls["control:root:root"]
    initial = cmds.xform(adapter_root, query=True, worldSpace=True, translation=True)
    for frame, offset in ((1001, 0.0), (1002, 3.0)):
        cmds.currentTime(frame)
        cmds.xform(
            adapter_root,
            worldSpace=True,
            translation=(initial[0] + offset, initial[1], initial[2]),
        )
        cmds.setKeyframe(adapter_root, attribute=("translateX", "translateY", "translateZ"))

    result = controller.bake_to_as(selected)

    assert result.validation.passed, result.validation.issues[:3]
    assert cmds.objExists(result.layer)
    assert not cmds.objExists(session.adapter.root)
    report = controller.restore_pre_conversion(selected)
    assert report.restored
    assert not cmds.objExists(result.layer)


def test_raw_mixamo_fbx_import_keys_adapter_and_removes_temporary_source(tmp_path):
    source_path = os.environ.get("ASMB_AS_RIG")
    if not source_path or not Path(source_path).is_file():
        pytest.skip("ASMB_AS_RIG does not point to the supplied AS rig")
    cmds.file(new=True, force=True)
    cmds.namespace(add="mixamorig")
    joints = {}
    mapping = {
        "Hips": None,
        "Spine": "Hips", "Spine2": "Spine", "Neck": "Spine2", "Head": "Neck",
        "LeftShoulder": "Spine2", "LeftArm": "LeftShoulder",
        "LeftForeArm": "LeftArm", "LeftHand": "LeftForeArm",
        "RightShoulder": "Spine2", "RightArm": "RightShoulder",
        "RightForeArm": "RightArm", "RightHand": "RightForeArm",
        "LeftUpLeg": "Hips", "LeftLeg": "LeftUpLeg", "LeftFoot": "LeftLeg",
        "LeftToeBase": "LeftFoot", "RightUpLeg": "Hips", "RightLeg": "RightUpLeg",
        "RightFoot": "RightLeg", "RightToeBase": "RightFoot",
    }
    positions = {
        "Hips": (0, 100, 0), "Spine": (0, 110, 0), "Spine2": (0, 125, 0),
        "Neck": (0, 140, 0), "Head": (0, 150, 0),
        "LeftShoulder": (5, 135, 0), "LeftArm": (15, 135, 0),
        "LeftForeArm": (35, 133, 2), "LeftHand": (55, 133, 2),
        "RightShoulder": (-5, 135, 0), "RightArm": (-15, 135, 0),
        "RightForeArm": (-35, 133, 2), "RightHand": (-55, 133, 2),
        "LeftUpLeg": (8, 95, 0), "LeftLeg": (8, 55, 2),
        "LeftFoot": (8, 10, 0), "LeftToeBase": (8, 2, 12),
        "RightUpLeg": (-8, 95, 0), "RightLeg": (-8, 55, 2),
        "RightFoot": (-8, 10, 0), "RightToeBase": (-8, 2, 12),
    }
    for leaf, parent in mapping.items():
        cmds.select(clear=True)
        joint = cmds.joint(name=f"mixamorig:{leaf}", position=positions[leaf])
        joints[leaf] = joint
        if parent:
            cmds.parent(joint, joints[parent])
    for frame, value in ((1001, 0.0), (1002, 4.0)):
        cmds.setKeyframe(joints["Hips"], attribute="translateX", time=frame, value=value)
    cmds.playbackOptions(
        minTime=1001, maxTime=1002, animationStartTime=1001, animationEndTime=1002
    )
    cmds.loadPlugin("fbxmaya", quiet=True)
    cmds.select(joints["Hips"], hierarchy=True)
    fbx_path = tmp_path / "raw_walk.fbx"
    import maya.mel as mel
    mel.eval("FBXExportBakeComplexAnimation -v true")
    mel.eval("FBXExportBakeComplexStart -v 1001")
    mel.eval("FBXExportBakeComplexEnd -v 1002")
    mel.eval("FBXExportBakeComplexStep -v 1")
    mel.eval(f'FBXExport -f "{str(fbx_path).replace(chr(92), "/")}" -s')

    cmds.file(source_path, open=True, force=True, prompt=False, ignoreVersion=True)
    selected = next(node for node in cmds.ls(long=True) if _leaf(node) == "RootX_M")
    controller = BridgeController(MayaBridgeServices())
    session = controller.apply_mixamo_animation(str(fbx_path), selected)

    assert session.source_kind == "raw_fbx"
    assert sorted(set(cmds.keyframe(
        session.adapter.controls["control:root:root"], query=True, timeChange=True
    ) or [])) == [1001.0, 1002.0]
    leg_option = session.adapter.controls["switch:leg_l"]
    arm_option = session.adapter.controls["switch:arm_l"]
    assert cmds.getAttr(f"{leg_option}.FKIKBlend", time=1001) == 10.0
    assert cmds.getAttr(f"{arm_option}.FKIKBlend", time=1001) == 0.0
    assert not any("ASMB_SRC_" in node for node in (cmds.ls() or []))
    controller.restore_pre_conversion(selected)
