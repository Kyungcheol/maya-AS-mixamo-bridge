from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from .models import (
    ProfileError,
    RigKind,
    RigProfile,
    SpaceDefinition,
    SwitchDefinition,
)


REQUIRED_BODY_JOINTS = (
    "hips",
    "spine",
    "chest",
    "neck",
    "head",
    "left_shoulder",
    "left_upper_arm",
    "left_lower_arm",
    "left_hand",
    "right_shoulder",
    "right_upper_arm",
    "right_lower_arm",
    "right_hand",
    "left_upper_leg",
    "left_lower_leg",
    "left_foot",
    "left_toe",
    "right_upper_leg",
    "right_lower_leg",
    "right_foot",
    "right_toe",
)

CONTROL_GROUPS = ("fk", "ik", "pole", "root", "finger")
TOLERANCE_KEYS = (
    "root_position_cm",
    "end_effector_position_cm",
    "root_orientation_deg",
    "end_effector_orientation_deg",
    "body_orientation_deg",
    "foot_drift_cm",
)
PROFILE_KEYS = {
    "profile_id",
    "version",
    "rig_kind",
    "signature_nodes",
    "skeleton",
    "controls",
    "switches",
    "spaces",
    "excluded_roots",
    "humanik_slots",
    "tolerances",
}


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProfileError(f"{label} must be an object")
    return value


def _require_string_map(value: Any, label: str) -> dict[str, str]:
    mapping = _require_mapping(value, label)
    result: dict[str, str] = {}
    for key, item in mapping.items():
        if not isinstance(key, str) or not key or not isinstance(item, str) or not item:
            raise ProfileError(f"{label} must contain non-empty string pairs")
        result[key] = item
    return result


def _reject_duplicate_values(mapping: Mapping[str, str], label: str) -> None:
    seen: dict[str, str] = {}
    for semantic, scene_node in mapping.items():
        previous = seen.get(scene_node)
        if previous is not None:
            raise ProfileError(
                f"{label} contains duplicate scene node {scene_node!r} for {previous!r} and {semantic!r}"
            )
        seen[scene_node] = semantic


def parse_profile(data: Mapping[str, Any]) -> RigProfile:
    raw = _require_mapping(data, "profile")
    missing_keys = PROFILE_KEYS.difference(raw)
    extra_keys = set(raw).difference(PROFILE_KEYS)
    if missing_keys or extra_keys:
        raise ProfileError(
            f"profile keys mismatch; missing={sorted(missing_keys)}, extra={sorted(extra_keys)}"
        )

    profile_id = raw["profile_id"]
    if not isinstance(profile_id, str) or not re.fullmatch(r"[a-z0-9_]+", profile_id):
        raise ProfileError("profile_id must contain only lowercase letters, digits, and underscores")
    version = raw["version"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ProfileError("version must be a positive integer")
    try:
        rig_kind = RigKind(raw["rig_kind"])
    except (TypeError, ValueError) as exc:
        raise ProfileError(f"unknown rig_kind: {raw['rig_kind']!r}") from exc

    signatures = raw["signature_nodes"]
    if not isinstance(signatures, list) or not signatures or not all(
        isinstance(item, str) and item for item in signatures
    ):
        raise ProfileError("signature_nodes must be a non-empty string list")

    skeleton = _require_string_map(raw["skeleton"], "skeleton")
    missing_joints = sorted(set(REQUIRED_BODY_JOINTS).difference(skeleton))
    if missing_joints:
        raise ProfileError(f"skeleton is missing required joints: {', '.join(missing_joints)}")
    _reject_duplicate_values(skeleton, "skeleton")

    raw_controls = _require_mapping(raw["controls"], "controls")
    if set(raw_controls) != set(CONTROL_GROUPS):
        raise ProfileError(f"controls must contain exactly: {', '.join(CONTROL_GROUPS)}")
    controls = {
        group: _require_string_map(raw_controls[group], f"controls.{group}")
        for group in CONTROL_GROUPS
    }

    switches = {}
    for name, item in _require_mapping(raw["switches"], "switches").items():
        values = _require_mapping(item, f"switches.{name}")
        if set(values) != {"node", "attribute", "fk_value", "ik_value"}:
            raise ProfileError(f"switches.{name} has invalid keys")
        if not isinstance(values["node"], str) or not isinstance(values["attribute"], str):
            raise ProfileError(f"switches.{name} node and attribute must be strings")
        if not all(isinstance(values[key], (int, float)) for key in ("fk_value", "ik_value")):
            raise ProfileError(f"switches.{name} values must be numeric")
        switches[name] = SwitchDefinition(
            node=values["node"],
            attribute=values["attribute"],
            fk_value=float(values["fk_value"]),
            ik_value=float(values["ik_value"]),
        )

    spaces = {}
    for name, item in _require_mapping(raw["spaces"], "spaces").items():
        values = _require_mapping(item, f"spaces.{name}")
        if set(values) != {"node", "attribute", "values"}:
            raise ProfileError(f"spaces.{name} has invalid keys")
        spaces[name] = SpaceDefinition(
            node=str(values["node"]),
            attribute=str(values["attribute"]),
            values={
                key: float(number)
                for key, number in _require_mapping(
                    values["values"], f"spaces.{name}.values"
                ).items()
            },
        )

    excluded = raw["excluded_roots"]
    if not isinstance(excluded, list) or not excluded or not all(
        isinstance(item, str) and item for item in excluded
    ):
        raise ProfileError("excluded_roots must be a non-empty string list")

    humanik_slots: dict[int, str] = {}
    for raw_slot, semantic in _require_mapping(raw["humanik_slots"], "humanik_slots").items():
        try:
            slot = int(raw_slot)
        except (TypeError, ValueError) as exc:
            raise ProfileError(f"invalid HumanIK slot: {raw_slot!r}") from exc
        if slot < 0 or not isinstance(semantic, str) or semantic not in skeleton:
            raise ProfileError(f"HumanIK slot {raw_slot!r} references unknown joint {semantic!r}")
        if slot in humanik_slots:
            raise ProfileError(f"duplicate HumanIK slot: {slot}")
        humanik_slots[slot] = semantic

    raw_tolerances = _require_mapping(raw["tolerances"], "tolerances")
    if set(raw_tolerances) != set(TOLERANCE_KEYS):
        raise ProfileError(f"tolerances must contain exactly: {', '.join(TOLERANCE_KEYS)}")
    tolerances = {}
    for name in TOLERANCE_KEYS:
        value = raw_tolerances[name]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            raise ProfileError(f"tolerance {name} must be positive")
        tolerances[name] = float(value)

    return RigProfile(
        profile_id=profile_id,
        version=version,
        rig_kind=rig_kind,
        signature_nodes=tuple(signatures),
        skeleton=skeleton,
        controls=controls,
        switches=switches,
        spaces=spaces,
        excluded_roots=tuple(excluded),
        humanik_slots=humanik_slots,
        tolerances=tolerances,
    )


def load_profile(profile_id: str) -> RigProfile:
    if not re.fullmatch(r"[a-z0-9_]+", profile_id):
        raise ProfileError(f"invalid profile id: {profile_id!r}")
    path = Path(__file__).with_name("profiles") / f"{profile_id}.json"
    if not path.is_file():
        raise ProfileError(f"unknown profile: {profile_id}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfileError(f"cannot read profile {profile_id}: {exc}") from exc
    profile = parse_profile(data)
    if profile.profile_id != profile_id:
        raise ProfileError(
            f"profile filename id {profile_id!r} does not match payload {profile.profile_id!r}"
        )
    return profile
