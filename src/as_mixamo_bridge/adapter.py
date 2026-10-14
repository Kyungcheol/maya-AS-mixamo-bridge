from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Protocol, Sequence

from .models import BridgeError, CharacterContext, RigProfile
from .transaction import BridgeTransaction


@dataclass(frozen=True, slots=True)
class AdapterRig:
    root: str
    context: CharacterContext
    controls: Mapping[str, str]
    protection_layer: str
    owned_nodes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "controls", MappingProxyType(dict(self.controls)))


class AdapterScene(Protocol):
    def create_adapter(
        self,
        context: CharacterContext,
        profile: RigProfile,
        transaction: BridgeTransaction,
    ) -> AdapterRig: ...


def create_adapter(
    scene: AdapterScene,
    context: CharacterContext,
    profile: RigProfile,
    transaction: BridgeTransaction,
) -> AdapterRig:
    if context.profile_id != profile.profile_id:
        raise BridgeError("adapter target profile does not match detected character")
    return scene.create_adapter(context, profile, transaction)


class MayaAdapterScene:
    _CHANNELS = ("translateX", "translateY", "translateZ", "rotateX", "rotateY", "rotateZ")

    def __init__(self) -> None:
        try:
            import maya.cmds as cmds
        except ImportError as exc:
            raise BridgeError("MayaAdapterScene requires Autodesk Maya") from exc
        self.cmds = cmds

    @staticmethod
    def _safe(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_]", "_", value)

    def _tag(self, node: str, session_id: str) -> None:
        plug = f"{node}.asmbSessionId"
        if not self.cmds.objExists(plug):
            self.cmds.addAttr(node, longName="asmbSessionId", dataType="string")
        self.cmds.setAttr(plug, session_id, type="string")

    def _record_new_nodes(
        self, before: set[str], transaction: BridgeTransaction, owned: list[str]
    ) -> None:
        for node in sorted(set(self.cmds.ls() or []).difference(before)):
            try:
                self._tag(node, transaction.session_id)
            except RuntimeError:
                pass
            transaction.record_created_node(node)
            owned.append(node)

    def _original_source(self, plug: str) -> str | None:
        sources = self.cmds.listConnections(
            plug, source=True, destination=False, plugs=True
        ) or []
        return sources[0] if sources else None

    def _create_control(self, name: str, parent: str, matrix: Sequence[float]) -> str:
        control = self.cmds.circle(
            name=name, normal=(0, 1, 0), radius=3.0, constructionHistory=False
        )[0]
        self.cmds.parent(control, parent)
        self.cmds.xform(control, worldSpace=True, matrix=list(matrix))
        return control

    def _unlocked_axes(self, node: str, prefix: str) -> tuple[str, ...]:
        axes: list[str] = []
        for axis in "XYZ":
            plug = f"{node}.{prefix}{axis}"
            if self.cmds.objExists(plug) and not self.cmds.getAttr(plug, lock=True):
                axes.append(axis.lower())
        return tuple(axes)

    def _constrain_available_channels(self, driver: str, target: str) -> None:
        translate_axes = self._unlocked_axes(target, "translate")
        rotate_axes = self._unlocked_axes(target, "rotate")
        if translate_axes:
            self.cmds.pointConstraint(
                driver,
                target,
                maintainOffset=False,
                skip=tuple(axis for axis in "xyz" if axis not in translate_axes),
            )
        if rotate_axes:
            self.cmds.orientConstraint(
                driver,
                target,
                maintainOffset=False,
                skip=tuple(axis for axis in "xyz" if axis not in rotate_axes),
            )

    def create_adapter(
        self,
        context: CharacterContext,
        profile: RigProfile,
        transaction: BridgeTransaction,
    ) -> AdapterRig:
        owned: list[str] = []
        controls: dict[str, str] = {}
        before = set(self.cmds.ls() or [])
        root = self.cmds.createNode(
            "transform", name=f"ASMB_{transaction.session_id[:8]}_Adapter"
        )
        self._record_new_nodes(before, transaction, owned)

        for key, target in context.nodes.items():
            if not key.startswith("control:"):
                continue
            before = set(self.cmds.ls() or [])
            control = self._create_control(
                f"ASMB_{transaction.session_id[:8]}_{self._safe(key)}",
                root,
                self.cmds.xform(target, query=True, worldSpace=True, matrix=True),
            )
            self._record_new_nodes(before, transaction, owned)
            controls[key] = control
            for channel in self._CHANNELS:
                target_plug = f"{target}.{channel}"
                if self.cmds.objExists(target_plug):
                    transaction.record_connection(
                        target_plug, self._original_source(target_plug)
                    )
            before = set(self.cmds.ls() or [])
            self._constrain_available_channels(control, target)
            self._record_new_nodes(before, transaction, owned)

        option_nodes: dict[str, str] = {}
        for name, definition in profile.switches.items():
            before = set(self.cmds.ls() or [])
            option = self.cmds.createNode(
                "transform",
                name=f"ASMB_{transaction.session_id[:8]}_Options_{name}",
                parent=root,
            )
            self.cmds.addAttr(
                option,
                longName=definition.attribute,
                attributeType="double",
                minValue=min(definition.fk_value, definition.ik_value),
                maxValue=max(definition.fk_value, definition.ik_value),
                defaultValue=definition.fk_value,
                keyable=True,
            )
            self._record_new_nodes(before, transaction, owned)
            option_nodes[name] = option
            controls[f"switch:{name}"] = option
            target_node = context.nodes[f"switch:{name}"]
            destination = f"{target_node}.{definition.attribute}"
            transaction.record_connection(destination, self._original_source(destination))
            self.cmds.connectAttr(f"{option}.{definition.attribute}", destination, force=True)

        for name, definition in profile.spaces.items():
            before = set(self.cmds.ls() or [])
            option = self.cmds.createNode(
                "transform",
                name=f"ASMB_{transaction.session_id[:8]}_Space_{name}",
                parent=root,
            )
            attribute = self._safe(name)
            values = tuple(float(value) for value in definition.values.values())
            self.cmds.addAttr(
                option,
                longName=attribute,
                attributeType="double",
                minValue=min(values),
                maxValue=max(values),
                defaultValue=values[0],
                keyable=True,
            )
            self._record_new_nodes(before, transaction, owned)
            controls[f"space:{name}"] = option
            destination_node = context.nodes[f"space:{name}"]
            destination = f"{destination_node}.{definition.attribute}"
            transaction.record_connection(destination, self._original_source(destination))
            self.cmds.connectAttr(f"{option}.{attribute}", destination, force=True)

        before = set(self.cmds.ls() or [])
        protection_layer = self.cmds.createDisplayLayer(
            name=f"ASMB_{transaction.session_id[:8]}_ProtectedAS", empty=True
        )
        body_nodes = tuple(dict.fromkeys(context.nodes.values()))
        if body_nodes:
            self.cmds.editDisplayLayerMembers(
                protection_layer, *body_nodes, noRecurse=True
            )
        self.cmds.setAttr(f"{protection_layer}.displayType", 2)
        self._record_new_nodes(before, transaction, owned)

        adapter_context_nodes = dict(controls)
        return AdapterRig(
            root=root,
            context=CharacterContext(
                root=root,
                profile_id=profile.profile_id,
                namespace="",
                nodes=adapter_context_nodes,
            ),
            controls=controls,
            protection_layer=protection_layer,
            owned_nodes=tuple(dict.fromkeys(owned)),
        )
