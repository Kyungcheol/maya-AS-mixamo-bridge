from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import BridgeError, CharacterContext, RigProfile
from .transaction import BridgeTransaction


class HumanIKBackend(Protocol):
    def scene_characters(self) -> tuple[str, ...]: ...
    def scene_nodes(self) -> set[str]: ...
    def node_exists(self, node: str) -> bool: ...
    def create_character(self, name_hint: str) -> str: ...
    def assign_joint(self, character: str, joint: str, slot: int) -> None: ...
    def lock_character(self, character: str) -> bool: ...
    def delete_character(self, character: str) -> None: ...
    def delete_node(self, node: str) -> None: ...
    def set_character_input(self, target: str, source: str) -> None: ...


def _safe_name(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value)


@dataclass(slots=True)
class HumanIKSession:
    backend: HumanIKBackend
    character: str
    owned_nodes: tuple[str, ...]
    transaction: BridgeTransaction | None

    @classmethod
    def create(
        cls,
        backend: HumanIKBackend,
        context: CharacterContext,
        profile: RigProfile,
        transaction: BridgeTransaction | None,
    ) -> "HumanIKSession":
        resolved: dict[int, str] = {}
        for slot, semantic in profile.humanik_slots.items():
            key = f"joint:{semantic}"
            node = context.nodes.get(key)
            if not node or not backend.node_exists(node):
                raise BridgeError(f"missing mapped joint for HumanIK slot {slot}: {semantic}")
            resolved[slot] = node

        before = backend.scene_nodes()
        session_token = transaction.session_id[:8] if transaction else "validate"
        hint = _safe_name(f"ASMB_{session_token}_{profile.profile_id}")
        character = ""
        try:
            character = backend.create_character(hint)
            for slot, node in sorted(resolved.items()):
                backend.assign_joint(character, node, slot)
            if not backend.lock_character(character):
                raise BridgeError(f"HumanIK characterization failed for {character}")
        except Exception:
            if character:
                backend.delete_character(character)
            raise

        owned = tuple(sorted(backend.scene_nodes().difference(before)))
        if transaction:
            for node in owned:
                transaction.record_created_node(node)
        return cls(backend, character, owned, transaction)

    def set_source(self, source_character: str) -> None:
        if source_character not in self.backend.scene_characters():
            raise BridgeError(f"HumanIK source does not exist: {source_character}")
        self.backend.set_character_input(self.character, source_character)

    def delete_owned_nodes(self) -> None:
        if self.character in self.backend.scene_characters():
            self.backend.delete_character(self.character)
        for node in reversed(self.owned_nodes):
            if self.backend.node_exists(node):
                self.backend.delete_node(node)


class MayaHumanIKBackend:
    _SOURCES = (
        "hikSkeletonOperations.mel",
        "hikGlobalUtils.mel",
        "hikDefinitionUtils.mel",
        "hikInputSourceUtils.mel",
        "hikDefinitionOperations.mel",
        "hikCharacterControlsUtils.mel",
    )

    def __init__(self) -> None:
        try:
            import maya.cmds as cmds
            import maya.mel as mel
        except ImportError as exc:
            raise BridgeError("MayaHumanIKBackend requires Autodesk Maya") from exc
        self.cmds = cmds
        self.mel = mel
        for plugin in ("mayaHIK", "mayaCharacterization"):
            if not self.cmds.pluginInfo(plugin, query=True, loaded=True):
                self.cmds.loadPlugin(plugin, quiet=True)
        for source in self._SOURCES:
            self.mel.eval(f'source "{source}";')

    @staticmethod
    def _mel_string(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def scene_characters(self) -> tuple[str, ...]:
        return tuple(sorted(self.cmds.ls(type="HIKCharacterNode") or []))

    def scene_nodes(self) -> set[str]:
        return set(self.cmds.ls() or [])

    def node_exists(self, node: str) -> bool:
        return bool(self.cmds.objExists(node))

    def create_character(self, name_hint: str) -> str:
        name = self._mel_string(name_hint)
        character = self.mel.eval(f'hikCreateCharacter("{name}")')
        if not character or not self.cmds.objExists(character):
            raise BridgeError(f"Maya failed to create HumanIK character {name_hint}")
        return str(character)

    def assign_joint(self, character: str, joint: str, slot: int) -> None:
        character_value = self._mel_string(character)
        joint_value = self._mel_string(joint)
        self.mel.eval(
            f'setCharacterObject("{joint_value}","{character_value}",{int(slot)},0)'
        )

    def lock_character(self, character: str) -> bool:
        value = self._mel_string(character)
        self.mel.eval(f'hikCharacterLock("{value}",1,1)')
        return bool(self.cmds.getAttr(f"{character}.InputCharacterizationLock"))

    def delete_character(self, character: str) -> None:
        if self.cmds.objExists(character):
            value = self._mel_string(character)
            self.mel.eval(f'hikDeleteCharacter("{value}")')

    def delete_node(self, node: str) -> None:
        if self.cmds.objExists(node):
            self.cmds.delete(node)

    def set_character_input(self, target: str, source: str) -> None:
        target_value = self._mel_string(target)
        source_value = self._mel_string(source)
        self.mel.eval(f'hikSetCharacterInput("{target_value}","{source_value}")')
