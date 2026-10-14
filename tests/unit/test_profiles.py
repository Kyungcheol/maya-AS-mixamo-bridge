from __future__ import annotations

import importlib

import pytest

from as_mixamo_bridge.models import ProfileError, RigKind
from as_mixamo_bridge.profiles import (
    REQUIRED_BODY_JOINTS,
    load_profile,
    parse_profile,
)


@pytest.mark.parametrize(
    ("profile_id", "kind"),
    [
        ("as_belato01_v1", RigKind.ADVANCED_SKELETON),
        ("studio_mixamo_teamextra01_v1", RigKind.STUDIO_MIXAMO),
    ],
)
def test_bundled_profiles_cover_required_body_contract(profile_id, kind):
    """Catches a shipped profile that silently omits a required body joint."""
    profile = load_profile(profile_id)

    assert profile.rig_kind is kind
    assert set(REQUIRED_BODY_JOINTS).issubset(profile.skeleton)
    assert profile.signature_nodes
    assert profile.humanik_slots
    assert profile.excluded_roots
    assert all("face" in root.lower() for root in profile.excluded_roots)


def test_studio_and_as_switch_ranges_represent_the_real_rigs():
    """Catches reversed or normalized switch ranges that would select the wrong rig mode."""
    studio = load_profile("studio_mixamo_teamextra01_v1")
    advanced = load_profile("as_belato01_v1")

    assert studio.switches["arm_l"].fk_value == 0.0
    assert studio.switches["arm_l"].ik_value == 1.0
    assert advanced.switches["arm_l"].fk_value == 0.0
    assert advanced.switches["arm_l"].ik_value == 10.0


def test_studio_profile_uses_verified_teamextra_control_names():
    """Catches guessed controller names that do not exist in TeamExtra01."""
    studio = load_profile("studio_mixamo_teamextra01_v1")

    assert studio.controls["root"]["root"] == "global_CTRL"
    assert studio.controls["root"]["body"] == "Root_CTRL"
    assert studio.controls["fk"]["hips"] == "Pelvis_CTRL"
    assert studio.controls["fk"]["left_upper_arm"] == "LeftArm_FK_CTRL"
    assert studio.controls["ik"]["left_hand"] == "LeftHand_IK_CTRL"
    assert studio.controls["pole"]["left_elbow"] == "LeftForeArm_IK_CTRL"
    assert studio.spaces["arm_l_follow"].node == "LeftHand_IK_CTRL"
    assert studio.spaces["leg_l_foot"].node == "LeftLeg_IK_CTRL"


def test_profile_rejects_duplicate_scene_nodes(valid_profile_dict):
    """Catches two semantic joints accidentally targeting one scene node."""
    valid_profile_dict["skeleton"]["head"] = valid_profile_dict["skeleton"]["hips"]

    with pytest.raises(ProfileError, match="duplicate scene node"):
        parse_profile(valid_profile_dict)


def test_profile_rejects_missing_required_mapping(valid_profile_dict):
    """Catches incomplete profiles before any Maya scene mutation occurs."""
    del valid_profile_dict["skeleton"]["left_foot"]

    with pytest.raises(ProfileError, match="left_foot"):
        parse_profile(valid_profile_dict)


def test_profile_modules_do_not_import_maya():
    """Catches accidental Maya imports that would break pure-Python validation tooling."""
    importlib.import_module("as_mixamo_bridge.models")
    importlib.import_module("as_mixamo_bridge.profiles")

    assert "maya" not in importlib.import_module("as_mixamo_bridge.models").__dict__


@pytest.fixture
def valid_profile_dict():
    skeleton = {name: f"Joint_{index}" for index, name in enumerate(REQUIRED_BODY_JOINTS)}
    return {
        "profile_id": "test_profile_v1",
        "version": 1,
        "rig_kind": "advanced_skeleton",
        "signature_nodes": ["RootControl", "MotionSystem"],
        "skeleton": skeleton,
        "controls": {
            "fk": {"head": "FKHead"},
            "ik": {"left_hand": "IKArm_L"},
            "pole": {"left_elbow": "PoleArm_L"},
            "root": {"root": "RootX_M"},
            "finger": {},
        },
        "switches": {
            "arm_l": {
                "node": "FKIKArm_L",
                "attribute": "FKIKBlend",
                "fk_value": 0,
                "ik_value": 10,
            }
        },
        "spaces": {},
        "excluded_roots": ["FaceGroup"],
        "humanik_slots": {"1": "hips", "15": "head"},
        "tolerances": {
            "root_position_cm": 0.1,
            "end_effector_position_cm": 0.1,
            "root_orientation_deg": 0.1,
            "end_effector_orientation_deg": 0.1,
            "body_orientation_deg": 0.25,
            "foot_drift_cm": 0.1,
        },
    }
