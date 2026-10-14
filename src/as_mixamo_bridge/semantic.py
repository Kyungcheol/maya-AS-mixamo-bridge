from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, Sequence

from .models import BridgeError, CharacterContext, FrameRange, RigProfile, SwitchEvent
from .pose_bake import PosePassResult
from .transaction import BridgeTransaction


Vector3 = tuple[float, float, float]


class EventScene(Protocol):
    def key_times(self, node: str, attributes: Sequence[str] | None = None) -> Sequence[float]: ...
    def value_at(self, plug: str, frame: float) -> float: ...


class SemanticScene(Protocol):
    def create_override_layer(self, name: str) -> str: ...
    def delete_layer(self, layer: str) -> None: ...
    def match_switch(
        self,
        target: CharacterContext,
        profile: RigProfile,
        channel: str,
        frames: tuple[float, ...],
        layer: str,
    ) -> None: ...
    def key_switch(self, plug: str, value: float, frame: float, layer: str) -> None: ...


@dataclass(frozen=True, slots=True)
class SemanticPassResult:
    layer: str
    events: tuple[SwitchEvent, ...]
    frames: tuple[float, ...]


def _normalized_switch(value: float, fk_value: float, ik_value: float) -> float:
    midpoint = (fk_value + ik_value) * 0.5
    if ik_value > fk_value:
        return 1.0 if value >= midpoint else 0.0
    return 1.0 if value <= midpoint else 0.0


def _space_name(value: float, values: dict[str, float] | object) -> str:
    mapping = dict(values)  # type: ignore[arg-type]
    if not mapping:
        raise BridgeError("space mapping contains no values")
    return min(mapping, key=lambda name: abs(float(mapping[name]) - value))


def extract_switch_events(
    scene: EventScene,
    source: CharacterContext,
    profile: RigProfile,
    frame_range: FrameRange,
) -> tuple[SwitchEvent, ...]:
    events: list[SwitchEvent] = []
    for name, definition in profile.switches.items():
        node = source.nodes.get(f"switch:{name}")
        if not node:
            continue
        plug = f"{node}.{definition.attribute}"
        keys = sorted(
            float(frame)
            for frame in scene.key_times(node, [definition.attribute])
            if frame_range.start <= float(frame) <= frame_range.end
        )
        if not keys:
            continue
        previous = _normalized_switch(
            float(scene.value_at(plug, keys[0])), definition.fk_value, definition.ik_value
        )
        for frame in keys[1:]:
            value = _normalized_switch(
                float(scene.value_at(plug, frame)), definition.fk_value, definition.ik_value
            )
            if value != previous:
                events.append(SwitchEvent(frame, f"switch:{name}", previous, value))
                previous = value

    for name, definition in profile.spaces.items():
        node = source.nodes.get(f"space:{name}")
        if not node:
            continue
        plug = f"{node}.{definition.attribute}"
        keys = sorted(
            float(frame)
            for frame in scene.key_times(node, [definition.attribute])
            if frame_range.start <= float(frame) <= frame_range.end
        )
        if not keys:
            continue
        previous = _space_name(float(scene.value_at(plug, keys[0])), definition.values)
        for frame in keys[1:]:
            value = _space_name(float(scene.value_at(plug, frame)), definition.values)
            if value != previous:
                events.append(SwitchEvent(frame, f"space:{name}", previous, value))
                previous = value
    return tuple(sorted(events, key=lambda event: (event.frame, event.channel)))


def _subtract(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(value: Vector3, factor: float) -> Vector3:
    return (value[0] * factor, value[1] * factor, value[2] * factor)


def _dot(a: Vector3, b: Vector3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _length(value: Vector3) -> float:
    return math.sqrt(_dot(value, value))


def _normalized(value: Vector3) -> Vector3:
    length = _length(value)
    if length <= 1e-10:
        raise BridgeError("cannot normalize a zero-length vector")
    return _scale(value, 1.0 / length)


def solve_pole_vector(
    start: Vector3,
    mid: Vector3,
    end: Vector3,
    previous: Vector3 | None = None,
) -> Vector3:
    axis = _subtract(end, start)
    axis_length = _length(axis)
    if axis_length <= 1e-10:
        raise BridgeError("limb start and end occupy the same point")
    axis_normal = _scale(axis, 1.0 / axis_length)
    start_to_mid = _subtract(mid, start)
    projection = _add(start, _scale(axis_normal, _dot(start_to_mid, axis_normal)))
    bend = _subtract(mid, projection)
    if _length(bend) <= 1e-8:
        if previous is not None:
            bend = _subtract(previous, mid)
            bend = _subtract(bend, _scale(axis_normal, _dot(bend, axis_normal)))
        if _length(bend) <= 1e-8:
            preferred = (0.0, 0.0, 1.0)
            if abs(_dot(axis_normal, preferred)) > 0.9:
                preferred = (0.0, 1.0, 0.0)
            bend = _subtract(preferred, _scale(axis_normal, _dot(preferred, axis_normal)))
    direction = _normalized(bend)
    candidate = _add(mid, _scale(direction, axis_length))
    if previous is not None and _dot(_subtract(candidate, mid), _subtract(previous, mid)) < 0:
        candidate = _add(mid, _scale(direction, -axis_length))
    return candidate


def _boundary_frames(frame: float, pose_frames: tuple[float, ...]) -> tuple[float, ...]:
    available = set(pose_frames)
    candidates = (frame - 1.0, frame, frame + 1.0)
    return tuple(value for value in candidates if value in available)


def apply_semantic_pass(
    scene: SemanticScene,
    pose_pass: PosePassResult,
    events: Sequence[SwitchEvent],
    transaction: BridgeTransaction,
    *,
    target: CharacterContext | None = None,
    profile: RigProfile | None = None,
) -> SemanticPassResult:
    if target is None or profile is None:
        raise BridgeError("semantic pass requires target context and profile")
    layer = scene.create_override_layer(f"{pose_pass.layer}_Semantic")
    used_frames: set[float] = set()
    try:
        for event in events:
            frames = _boundary_frames(float(event.frame), pose_pass.frames)
            if not frames:
                raise BridgeError(f"switch frame {event.frame} is outside the pose pass")
            scene.match_switch(target, profile, event.channel, frames, layer)
            used_frames.update(frames)
            kind, name = event.channel.split(":", 1)
            if kind == "switch":
                definition = profile.switches.get(name)
                node = target.nodes.get(event.channel)
                if definition is None or node is None:
                    raise BridgeError(f"unsupported switch: {name}")
                value = definition.ik_value if float(event.value) >= 0.5 else definition.fk_value
                scene.key_switch(
                    f"{node}.{definition.attribute}", value, float(event.frame), layer
                )
            elif kind == "space":
                definition = profile.spaces.get(name)
                node = target.nodes.get(event.channel)
                if definition is None or node is None or str(event.value) not in definition.values:
                    raise BridgeError(f"unsupported space: {name}={event.value}")
                scene.key_switch(
                    f"{node}.{definition.attribute}",
                    definition.values[str(event.value)],
                    float(event.frame),
                    layer,
                )
            else:
                raise BridgeError(f"unsupported semantic channel: {event.channel}")
    except Exception:
        scene.delete_layer(layer)
        raise
    transaction.record_layer(layer)
    return SemanticPassResult(layer, tuple(events), tuple(sorted(used_frames)))


class MayaSemanticScene:
    def __init__(self) -> None:
        try:
            import maya.cmds as cmds
        except ImportError as exc:
            raise BridgeError("MayaSemanticScene requires Autodesk Maya") from exc
        self.cmds = cmds

    def create_override_layer(self, name: str) -> str:
        return self.cmds.animLayer(name, override=True)

    def delete_layer(self, layer: str) -> None:
        if self.cmds.objExists(layer):
            self.cmds.delete(layer)

    def _add_keyable_to_layer(self, node: str, layer: str) -> None:
        for channel in self.cmds.listAttr(node, keyable=True, unlocked=True) or []:
            plug = f"{node}.{channel}"
            if self.cmds.getAttr(plug, settable=True):
                self.cmds.animLayer(layer, edit=True, attribute=plug)

    def match_switch(
        self,
        target: CharacterContext,
        profile: RigProfile,
        channel: str,
        frames: tuple[float, ...],
        layer: str,
    ) -> None:
        controls: list[str] = []
        if channel.startswith("switch:arm_l"):
            keys = (
                "control:fk:left_upper_arm", "control:fk:left_lower_arm",
                "control:fk:left_hand", "control:ik:left_hand", "control:pole:left_elbow",
            )
            controls = [target.nodes[key] for key in keys if key in target.nodes]
        elif channel.startswith("switch:arm_r"):
            keys = (
                "control:fk:right_upper_arm", "control:fk:right_lower_arm",
                "control:fk:right_hand", "control:ik:right_hand", "control:pole:right_elbow",
            )
            controls = [target.nodes[key] for key in keys if key in target.nodes]
        elif channel.startswith("switch:leg_l"):
            keys = (
                "control:fk:left_upper_leg", "control:fk:left_lower_leg",
                "control:fk:left_foot", "control:ik:left_foot", "control:pole:left_knee",
            )
            controls = [target.nodes[key] for key in keys if key in target.nodes]
        elif channel.startswith("switch:leg_r"):
            keys = (
                "control:fk:right_upper_leg", "control:fk:right_lower_leg",
                "control:fk:right_foot", "control:ik:right_foot", "control:pole:right_knee",
            )
            controls = [target.nodes[key] for key in keys if key in target.nodes]
        elif channel.startswith("space:"):
            node = target.nodes.get(channel)
            if node:
                controls = [node]
        if not controls:
            raise BridgeError(f"no controls resolved for semantic channel {channel}")
        for control in controls:
            self._add_keyable_to_layer(control, layer)
        self.cmds.animLayer(layer, edit=True, selected=True, preferred=True)
        for frame in frames:
            self.cmds.currentTime(frame, edit=True)
            for control in controls:
                for channel_name in (
                    "translateX", "translateY", "translateZ",
                    "rotateX", "rotateY", "rotateZ",
                ):
                    if self.cmds.objExists(f"{control}.{channel_name}"):
                        self.cmds.setKeyframe(
                            control, attribute=channel_name, time=frame, animLayer=layer
                        )

    def key_switch(self, plug: str, value: float, frame: float, layer: str) -> None:
        self.cmds.animLayer(layer, edit=True, attribute=plug)
        self.cmds.setAttr(plug, value)
        self.cmds.setKeyframe(plug, time=frame, value=value, animLayer=layer)
        self.cmds.keyTangent(plug, time=(frame, frame), inTangentType="step", outTangentType="step")
