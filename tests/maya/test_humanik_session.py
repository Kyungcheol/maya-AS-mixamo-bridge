from __future__ import annotations

import pytest

pytest.importorskip("maya.cmds")

import maya.cmds as cmds
import maya.mel as mel

from as_mixamo_bridge.humanik import HumanIKSession, MayaHumanIKBackend
from as_mixamo_bridge.models import BridgeError, CharacterContext
from as_mixamo_bridge.profiles import load_profile
from as_mixamo_bridge.transaction import BridgeTransaction, MayaTransactionScene


def setup_module():
    import maya.standalone

    try:
        maya.standalone.initialize(name="python")
    except RuntimeError:
        pass


def teardown_function():
    cmds.file(new=True, force=True)


def _create_profile_skeleton(profile):
    positions = {
        "hips": (0, 100, 0), "spine": (0, 110, 0), "chest": (0, 125, 0),
        "neck": (0, 140, 0), "head": (0, 150, 0),
        "left_shoulder": (5, 135, 0), "left_upper_arm": (15, 135, 0),
        "left_lower_arm": (35, 135, 0), "left_hand": (55, 135, 0),
        "right_shoulder": (-5, 135, 0), "right_upper_arm": (-15, 135, 0),
        "right_lower_arm": (-35, 135, 0), "right_hand": (-55, 135, 0),
        "left_upper_leg": (8, 95, 0), "left_lower_leg": (8, 55, 1),
        "left_foot": (8, 10, 0), "left_toe": (8, 2, 12),
        "right_upper_leg": (-8, 95, 0), "right_lower_leg": (-8, 55, 1),
        "right_foot": (-8, 10, 0), "right_toe": (-8, 2, 12),
    }
    parents = {
        "spine": "hips", "chest": "spine", "neck": "chest", "head": "neck",
        "left_shoulder": "chest", "left_upper_arm": "left_shoulder",
        "left_lower_arm": "left_upper_arm", "left_hand": "left_lower_arm",
        "right_shoulder": "chest", "right_upper_arm": "right_shoulder",
        "right_lower_arm": "right_upper_arm", "right_hand": "right_lower_arm",
        "left_upper_leg": "hips", "left_lower_leg": "left_upper_leg",
        "left_foot": "left_lower_leg", "left_toe": "left_foot",
        "right_upper_leg": "hips", "right_lower_leg": "right_upper_leg",
        "right_foot": "right_lower_leg", "right_toe": "right_foot",
    }
    nodes = {}
    for semantic in profile.skeleton:
        cmds.select(clear=True)
        node = cmds.joint(name=f"Test_{profile.skeleton[semantic]}", position=positions[semantic])
        nodes[semantic] = node
        parent = parents.get(semantic)
        if parent:
            cmds.parent(node, nodes[parent])
    return nodes


def test_session_uses_unique_character_and_preserves_unrelated_hik():
    """Catches global Character1 reuse or cleanup that deletes another HIK definition."""
    backend = MayaHumanIKBackend()
    unrelated = backend.create_character("UnrelatedCharacter")
    profile = load_profile("as_belato01_v1")
    joints = _create_profile_skeleton(profile)
    context = CharacterContext(
        root=joints["hips"],
        profile_id=profile.profile_id,
        nodes={f"joint:{semantic}": node for semantic, node in joints.items()},
    )
    tx = BridgeTransaction.begin(
        MayaTransactionScene(), context, session_id="humanik_integration"
    )

    session = HumanIKSession.create(backend, context, profile, tx)
    assert session.character != unrelated
    assert unrelated in backend.scene_characters()
    assert session.character in backend.scene_characters()

    session.delete_owned_nodes()
    assert unrelated in backend.scene_characters()
    assert session.character not in backend.scene_characters()
    tx.restore()


def test_missing_joint_fails_before_hik_character_creation():
    """Catches partial characterization leaving new HumanIK nodes in the scene."""
    backend = MayaHumanIKBackend()
    profile = load_profile("as_belato01_v1")
    context = CharacterContext("|missing", profile.profile_id, nodes={})
    before = backend.scene_characters()

    with pytest.raises(BridgeError, match="missing mapped joint"):
        HumanIKSession.create(backend, context, profile, None)

    assert backend.scene_characters() == before
