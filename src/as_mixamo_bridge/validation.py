from __future__ import annotations

import math
from typing import Protocol, Sequence

from .models import (
    BridgeError,
    CharacterContext,
    RigProfile,
    SwitchEvent,
    ValidationIssue,
    ValidationReport,
)
from .neutral import Matrix, NeutralMotion, multiply_matrices, validate_matrix


class ValidationScene(Protocol):
    def set_time(self, frame: float) -> None: ...
    def world_matrix(self, node: str) -> Sequence[float]: ...
    def is_keyable(self, node: str) -> bool: ...


_END_EFFECTORS = {"left_hand", "right_hand", "left_foot", "right_foot"}
_CONTACT_FEET = {"left_foot", "right_foot"}
_EPSILON = 1e-6


def _position(matrix: Sequence[float]) -> tuple[float, float, float]:
    return (float(matrix[12]), float(matrix[13]), float(matrix[14]))


def _distance(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(sum((float(left) - float(right)) ** 2 for left, right in zip(a, b)))


def _rotation_rows(matrix: Matrix) -> tuple[tuple[float, float, float], ...]:
    rows = []
    for row in range(3):
        values = tuple(matrix[row * 4 + column] for column in range(3))
        length = math.sqrt(sum(value * value for value in values))
        if length <= 1e-12:
            raise BridgeError("matrix contains a zero-scale rotation axis")
        rows.append(tuple(value / length for value in values))
    return tuple(rows)


def _orientation_error_degrees(expected: Matrix, actual: Matrix) -> float:
    expected_rows = _rotation_rows(expected)
    actual_rows = _rotation_rows(actual)
    trace = sum(
        expected_rows[row][column] * actual_rows[row][column]
        for row in range(3)
        for column in range(3)
    )
    cosine = max(-1.0, min(1.0, (trace - 1.0) * 0.5))
    return math.degrees(math.acos(cosine))


def _issue(
    category: str,
    body_part: str,
    frame: float,
    measured: float,
    tolerance: float,
) -> ValidationIssue:
    return ValidationIssue(
        category,
        body_part,
        frame,
        measured,
        tolerance,
        f"{body_part} {category} error {measured:.6f} exceeds {tolerance:.6f} at frame {frame:g}",
    )


def _switch_effector(channel: str) -> str | None:
    return {
        "switch:arm_l": "left_hand",
        "switch:arm_r": "right_hand",
        "switch:leg_l": "left_foot",
        "switch:leg_r": "right_foot",
    }.get(channel)


def validate_motion(
    scene: ValidationScene,
    neutral: NeutralMotion,
    target: CharacterContext,
    profile: RigProfile,
    events: Sequence[SwitchEvent] = (),
) -> ValidationReport:
    issues: list[ValidationIssue] = []
    metrics = {
        "max_position_cm": 0.0,
        "max_orientation_deg": 0.0,
        "max_foot_drift_cm": 0.0,
    }
    if target.profile_id != profile.profile_id:
        issues.append(_issue("profile_mismatch", "character", 0, 1, 0))
        return ValidationReport(tuple(issues), metrics)

    for key, node in target.nodes.items():
        if key.startswith("control:") or key.startswith("switch:") or key.startswith("space:"):
            if not scene.is_keyable(node):
                issues.append(_issue("unkeyable_control", key, neutral.frames[0], 1, 0))

    sampled: dict[tuple[float, str], tuple[Matrix, Matrix] | None] = {}
    for frame in neutral.frames:
        scene.set_time(frame)
        for semantic in profile.skeleton:
            node = target.nodes.get(f"joint:{semantic}")
            if not node:
                issues.append(_issue("missing_joint", semantic, frame, 1, 0))
                sampled[(frame, semantic)] = None
                continue
            expected = multiply_matrices(
                neutral.joint_relative[frame][semantic], neutral.root_world[frame]
            )
            try:
                expected = validate_matrix(expected, require_invertible=True)
                actual = validate_matrix(scene.world_matrix(node), require_invertible=True)
            except BridgeError:
                issues.append(_issue("invalid_matrix", semantic, frame, math.inf, 0))
                sampled[(frame, semantic)] = None
                continue
            sampled[(frame, semantic)] = (expected, actual)
            position_error = _distance(_position(expected), _position(actual))
            orientation_error = _orientation_error_degrees(expected, actual)
            metrics["max_position_cm"] = max(metrics["max_position_cm"], position_error)
            metrics["max_orientation_deg"] = max(
                metrics["max_orientation_deg"], orientation_error
            )

            if semantic == "hips":
                position_tolerance = profile.tolerances["root_position_cm"]
                orientation_tolerance = profile.tolerances["root_orientation_deg"]
            elif semantic in _END_EFFECTORS:
                position_tolerance = profile.tolerances["end_effector_position_cm"]
                orientation_tolerance = profile.tolerances["end_effector_orientation_deg"]
            else:
                position_tolerance = None
                orientation_tolerance = profile.tolerances["body_orientation_deg"]

            if position_tolerance is not None and position_error > position_tolerance + _EPSILON:
                issues.append(
                    _issue("position", semantic, frame, position_error, position_tolerance)
                )
            if orientation_error > orientation_tolerance + _EPSILON:
                issues.append(
                    _issue(
                        "orientation", semantic, frame, orientation_error, orientation_tolerance
                    )
                )

    foot_tolerance = profile.tolerances["foot_drift_cm"]
    for semantic in _CONTACT_FEET:
        for previous_frame, frame in zip(neutral.frames, neutral.frames[1:]):
            previous_sample = sampled.get((previous_frame, semantic))
            sample = sampled.get((frame, semantic))
            if previous_sample is None or sample is None:
                continue
            expected_drift = _distance(
                _position(previous_sample[0]), _position(sample[0])
            )
            if expected_drift > _EPSILON:
                continue
            actual_drift = _distance(_position(previous_sample[1]), _position(sample[1]))
            metrics["max_foot_drift_cm"] = max(
                metrics["max_foot_drift_cm"], actual_drift
            )
            if actual_drift > foot_tolerance + _EPSILON:
                issues.append(
                    _issue("contact_drift", semantic, frame, actual_drift, foot_tolerance)
                )

    end_tolerance = profile.tolerances["end_effector_position_cm"]
    for event in events:
        semantic = _switch_effector(event.channel)
        if semantic is None:
            continue
        sample = sampled.get((float(event.frame), semantic))
        if sample is None:
            continue
        error = _distance(_position(sample[0]), _position(sample[1]))
        if error > end_tolerance + _EPSILON:
            issues.append(
                _issue(
                    "switch_discontinuity", semantic, float(event.frame), error, end_tolerance
                )
            )

    return ValidationReport(tuple(issues), metrics)


class MayaValidationScene:
    def __init__(self) -> None:
        try:
            import maya.cmds as cmds
        except ImportError as exc:
            raise BridgeError("MayaValidationScene requires Autodesk Maya") from exc
        self.cmds = cmds

    def set_time(self, frame: float) -> None:
        self.cmds.currentTime(frame, edit=True)

    def world_matrix(self, node: str) -> Sequence[float]:
        return tuple(self.cmds.xform(node, query=True, worldSpace=True, matrix=True))

    def is_keyable(self, node: str) -> bool:
        if not self.cmds.objExists(node):
            return False
        return bool(self.cmds.listAttr(node, keyable=True, unlocked=True) or [])
