from __future__ import annotations

import pytest

pytest.importorskip("maya.cmds")

import maya.cmds as cmds

from as_mixamo_bridge.models import CharacterContext
from as_mixamo_bridge.transaction import BridgeTransaction, MayaTransactionScene


def setup_module():
    import maya.standalone

    try:
        maya.standalone.initialize(name="python")
    except RuntimeError:
        pass


def teardown_function():
    cmds.file(new=True, force=True)


def test_maya_transaction_restores_scene_without_touching_unrelated_data():
    source = cmds.createNode("transform", name="source")
    target = cmds.createNode("transform", name="target")
    unrelated = cmds.createNode("transform", name="unrelated")
    cmds.setAttr(f"{target}.tx", 2.0)
    cmds.connectAttr(f"{source}.tx", f"{target}.ty", force=True)
    cmds.setKeyframe(unrelated, attribute="tx", time=1001, value=7)
    existing_layer = cmds.animLayer("ExistingLayer")
    cmds.currentTime(1001)
    cmds.autoKeyframe(state=True)
    before_unrelated = cmds.keyframe(unrelated, query=True, timeChange=True)

    scene = MayaTransactionScene()
    context = CharacterContext("|target", "as_belato01_v1")
    tx = BridgeTransaction.begin(scene, context, session_id="integration")
    temporary = cmds.createNode("transform", name="temporary")
    tx.record_created_node(temporary)
    tx.record_attribute(f"{target}.tx", 2.0)
    cmds.setAttr(f"{target}.tx", 9.0)
    tx.record_connection(f"{target}.ty", f"{source}.tx")
    replacement = cmds.createNode("transform", name="replacement")
    tx.record_created_node(replacement)
    cmds.connectAttr(f"{replacement}.tx", f"{target}.ty", force=True)
    bridge_layer = cmds.animLayer("BridgeLayer")
    tx.record_layer(bridge_layer)
    cmds.currentTime(20)
    cmds.autoKeyframe(state=False)

    report = tx.restore()

    assert report.restored
    assert not cmds.objExists(temporary)
    assert not cmds.objExists(replacement)
    assert not cmds.objExists(bridge_layer)
    assert cmds.objExists(existing_layer)
    assert cmds.getAttr(f"{target}.tx") == 2.0
    assert cmds.isConnected(f"{source}.tx", f"{target}.ty")
    assert cmds.keyframe(unrelated, query=True, timeChange=True) == before_unrelated
    assert cmds.currentTime(query=True) == 1001
    assert cmds.autoKeyframe(query=True, state=True)
