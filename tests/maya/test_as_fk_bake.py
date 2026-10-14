from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("maya.cmds")

import maya.cmds as cmds

from as_mixamo_bridge.models import CharacterContext, FrameRange
from as_mixamo_bridge.neutral import NeutralMotion, root_relative_matrix
from as_mixamo_bridge.pose_bake import MayaPoseBakeScene, bake_fk_pose_pass, build_fk_bake_plan
from as_mixamo_bridge.profiles import load_profile
from as_mixamo_bridge.transaction import BridgeTransaction, MayaTransactionScene


pytestmark = [
    pytest.mark.filterwarnings("ignore::DeprecationWarning:mtoa.*"),
    pytest.mark.filterwarnings("ignore:.*find_module.*:DeprecationWarning"),
    pytest.mark.filterwarnings("ignore:.*find_loader.*:DeprecationWarning"),
    pytest.mark.filterwarnings("ignore:.*load_module.*:DeprecationWarning"),
]


def setup_module():
    import maya.standalone

    try:
        maya.standalone.initialize(name="python")
    except RuntimeError:
        pass


def _unique_leaf(leaf):
    matches = [node for node in cmds.ls(long=True) or [] if node.rsplit("|", 1)[-1].rsplit(":", 1)[-1] == leaf]
    assert len(matches) == 1, f"expected one {leaf}, got {matches}"
    return matches[0]


def test_fk_pose_pass_keys_only_new_override_layer_and_reopens_without_hik(tmp_path):
    source_path = os.environ.get("ASMB_AS_RIG")
    if not source_path or not Path(source_path).is_file():
        pytest.skip("ASMB_AS_RIG does not point to the supplied AS rig")
    cmds.file(source_path, open=True, force=True, prompt=False, ignoreVersion=True)
    profile = load_profile("as_belato01_v1")
    nodes = {}
    for group in ("fk", "root"):
        for semantic, leaf in profile.controls[group].items():
            nodes[f"control:{group}:{semantic}"] = _unique_leaf(leaf)
    context = CharacterContext(_unique_leaf("Group"), profile.profile_id, nodes=nodes)

    root = _unique_leaf(profile.skeleton["hips"])
    root_matrix = tuple(cmds.xform(root, query=True, worldSpace=True, matrix=True))
    relative = {}
    for semantic, leaf in profile.skeleton.items():
        joint_matrix = tuple(cmds.xform(_unique_leaf(leaf), query=True, worldSpace=True, matrix=True))
        relative[semantic] = root_relative_matrix(joint_matrix, root_matrix)
    moved_root = list(root_matrix)
    moved_root[12] += 3.0
    motion = NeutralMotion(
        FrameRange(1001, 1002),
        (1001.0, 1002.0),
        {1001.0: root_matrix, 1002.0: tuple(moved_root)},
        {1001.0: relative, 1002.0: relative},
        {},
        30.0,
    )
    transaction = BridgeTransaction.begin(
        MayaTransactionScene(), context, session_id="fk_pose_integration"
    )
    plan = build_fk_bake_plan(motion, context, profile)

    result = bake_fk_pose_pass(
        MayaPoseBakeScene(), plan, "ASMB_FK_Pose", transaction
    )
    transaction.commit()

    assert cmds.objExists(result.layer)
    assert cmds.getAttr(f"{result.layer}.override")
    assert result.frames == (1001.0, 1002.0)
    attributes = cmds.animLayer(result.layer, query=True, attribute=True) or []
    assert attributes
    assert all("face" not in attribute.lower() for attribute in attributes)

    output = tmp_path / "as_fk_pose_test.mb"
    cmds.file(rename=str(output))
    cmds.file(save=True, type="mayaBinary", force=True)
    cmds.file(new=True, force=True)
    cmds.file(str(output), open=True, force=True, prompt=False, ignoreVersion=True)
    assert not (cmds.ls(type="HIKCharacterNode") or [])
    assert cmds.objExists("ASMB_FK_Pose")
