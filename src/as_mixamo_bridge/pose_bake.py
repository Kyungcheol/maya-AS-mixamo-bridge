from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from .models import BridgeError, CharacterContext, RigProfile
from .neutral import Matrix, NeutralMotion, multiply_matrices
from .transaction import BridgeTransaction


@dataclass(frozen=True, slots=True)
class FKBakeTarget:
    role: str
    semantic: str
    control: str


@dataclass(frozen=True, slots=True)
class FKBakePlan:
    motion: NeutralMotion
    target: CharacterContext
    targets: tuple[FKBakeTarget, ...]
    frames: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class PosePassResult:
    layer: str
    keyed_controls: tuple[str, ...]
    frames: tuple[float, ...]
    validated: bool = False


class PoseBakeScene(Protocol):
    def is_keyable(self, node: str) -> bool: ...
    def create_override_layer(self, name: str, controls: Sequence[str]) -> str: ...
    def set_time(self, frame: float) -> None: ...
    def set_world_matrix(self, node: str, matrix: Matrix) -> None: ...
    def key_transform(self, node: str, frame: float, layer: str) -> None: ...


def build_fk_bake_plan(
    neutral: NeutralMotion,
    target: CharacterContext,
    profile: RigProfile,
) -> FKBakePlan:
    if target.profile_id != profile.profile_id:
        raise BridgeError(
            f"target profile {target.profile_id!r} does not match {profile.profile_id!r}"
        )
    if not neutral.frames:
        raise BridgeError("neutral motion contains no sampled frames")

    targets: list[FKBakeTarget] = []
    for semantic in profile.controls["fk"]:
        if semantic not in profile.skeleton:
            continue
        key = f"control:fk:{semantic}"
        control = target.nodes.get(key)
        if not control:
            raise BridgeError(f"missing target FK control for {semantic}")
        targets.append(FKBakeTarget("fk", semantic, control))

    root_control = target.nodes.get("control:root:root")
    if not root_control:
        raise BridgeError("missing target root control for hips")
    targets.insert(0, FKBakeTarget("root", "hips", root_control))

    if not targets:
        raise BridgeError("FK bake plan contains no targets")
    return FKBakePlan(neutral, target, tuple(targets), tuple(neutral.frames))


def _source_world(plan: FKBakePlan, target: FKBakeTarget, frame: float) -> Matrix:
    if target.role == "root":
        return plan.motion.root_world[frame]
    relative = plan.motion.joint_relative[frame][target.semantic]
    return multiply_matrices(relative, plan.motion.root_world[frame])


def bake_fk_pose_pass(
    scene: PoseBakeScene,
    plan: FKBakePlan,
    layer_name: str,
    transaction: BridgeTransaction,
) -> PosePassResult:
    unkeyable = [target.control for target in plan.targets if not scene.is_keyable(target.control)]
    if unkeyable:
        raise BridgeError(f"target controls are not keyable: {', '.join(unkeyable)}")

    controls = tuple(dict.fromkeys(target.control for target in plan.targets))
    layer = scene.create_override_layer(layer_name, controls)
    transaction.record_layer(layer)
    for frame in plan.frames:
        scene.set_time(frame)
        for target in plan.targets:
            scene.set_world_matrix(target.control, _source_world(plan, target, frame))
            scene.key_transform(target.control, frame, layer)
    return PosePassResult(layer=layer, keyed_controls=controls, frames=plan.frames)


class MayaPoseBakeScene:
    def __init__(self) -> None:
        try:
            import maya.cmds as cmds
        except ImportError as exc:
            raise BridgeError("MayaPoseBakeScene requires Autodesk Maya") from exc
        self.cmds = cmds

    def is_keyable(self, node: str) -> bool:
        if not self.cmds.objExists(node):
            return False
        attributes = self.cmds.listAttr(node, keyable=True, unlocked=True) or []
        return any(attribute in attributes for attribute in ("translateX", "rotateX"))

    def create_override_layer(self, name: str, controls: Sequence[str]) -> str:
        layer = self.cmds.animLayer(name, override=True)
        for control in controls:
            for channel in (
                "translateX", "translateY", "translateZ",
                "rotateX", "rotateY", "rotateZ",
            ):
                plug = f"{control}.{channel}"
                if self.cmds.objExists(plug) and self.cmds.getAttr(plug, settable=True):
                    self.cmds.animLayer(layer, edit=True, attribute=plug)
        self.cmds.animLayer(layer, edit=True, selected=True, preferred=True)
        return layer

    def set_time(self, frame: float) -> None:
        self.cmds.currentTime(frame, edit=True)

    def set_world_matrix(self, node: str, matrix: Matrix) -> None:
        self.cmds.xform(node, worldSpace=True, matrix=list(matrix))

    def key_transform(self, node: str, frame: float, layer: str) -> None:
        keyable = set(self.cmds.listAttr(node, keyable=True, unlocked=True) or [])
        for channel in (
            "translateX", "translateY", "translateZ",
            "rotateX", "rotateY", "rotateZ",
        ):
            if channel in keyable:
                self.cmds.setKeyframe(
                    node, attribute=channel, time=frame, animLayer=layer
                )
