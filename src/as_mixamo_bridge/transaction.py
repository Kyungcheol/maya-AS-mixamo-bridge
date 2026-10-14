from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from .models import BridgeError, CharacterContext, RestoreReport


class TransactionState(str, Enum):
    NEW = "new"
    ACTIVE = "active"
    COMMITTED = "committed"
    RESTORED = "restored"
    FAILED = "failed"


class TransactionScene(Protocol):
    def create_bridge_session(self, session_id: str, profile_id: str, state: str) -> str: ...
    def set_session_state(self, node: str, state: str) -> None: ...
    def set_session_manifest(self, node: str, manifest: str) -> None: ...
    def open_undo_chunk(self, name: str) -> None: ...
    def close_undo_chunk(self) -> None: ...
    def capture_scene_settings(self) -> dict[str, Any]: ...
    def restore_scene_settings(self, settings: dict[str, Any]) -> None: ...
    def delete_node(self, node: str) -> None: ...
    def set_attribute(self, plug: str, value: Any) -> None: ...
    def disconnect(self, destination: str) -> None: ...
    def connect(self, source: str, destination: str) -> None: ...
    def delete_layer(self, layer: str) -> None: ...


@dataclass(frozen=True, slots=True)
class _Record:
    kind: str
    data: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, **self.data}


class BridgeTransaction:
    def __init__(
        self,
        scene: TransactionScene,
        context: CharacterContext,
        session_id: str,
    ) -> None:
        self.scene = scene
        self.context = context
        self.session_id = session_id
        self.state = TransactionState.NEW
        self.records: list[_Record] = []
        self.settings: dict[str, Any] = {}
        self.session_node = ""
        self._undo_open = False

    @classmethod
    def begin(
        cls,
        scene: TransactionScene,
        context: CharacterContext,
        session_id: str | None = None,
    ) -> "BridgeTransaction":
        transaction = cls(scene, context, session_id or uuid.uuid4().hex)
        transaction.settings = scene.capture_scene_settings()
        scene.open_undo_chunk(f"AS Mixamo Bridge {transaction.session_id}")
        transaction._undo_open = True
        try:
            transaction.session_node = scene.create_bridge_session(
                transaction.session_id,
                context.profile_id,
                TransactionState.ACTIVE.value,
            )
            transaction.state = TransactionState.ACTIVE
            transaction.records.append(
                _Record("created_node", {"node": transaction.session_node})
            )
            transaction._persist()
        except Exception:
            transaction._close_undo()
            raise
        return transaction

    def __enter__(self) -> "BridgeTransaction":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc_type is None:
            self.commit()
        else:
            self.state = TransactionState.FAILED
            self.scene.set_session_state(self.session_node, self.state.value)
            self.restore()
        return False

    def _require_active(self) -> None:
        if self.state is not TransactionState.ACTIVE:
            raise BridgeError(f"transaction is not active: {self.state.value}")

    def _persist(self) -> None:
        if self.session_node:
            self.scene.set_session_manifest(self.session_node, self.manifest_json())

    def _append(self, record: _Record) -> None:
        self._require_active()
        self.records.append(record)
        self._persist()

    def record_created_node(self, node: str) -> None:
        self._append(_Record("created_node", {"node": node}))

    def record_attribute(self, plug: str, original_value: Any) -> None:
        self._append(
            _Record("attribute", {"plug": plug, "original_value": original_value})
        )

    def record_connection(self, destination: str, original_source: str | None) -> None:
        self._append(
            _Record(
                "connection",
                {"destination": destination, "original_source": original_source},
            )
        )

    def record_layer(self, layer: str) -> None:
        self._append(_Record("layer", {"layer": layer}))

    def manifest_json(self) -> str:
        return json.dumps(
            {
                "schema": 1,
                "session_id": self.session_id,
                "profile_id": self.context.profile_id,
                "character_root": self.context.root,
                "state": self.state.value,
                "settings": self.settings,
                "records": [record.as_dict() for record in self.records],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _close_undo(self) -> None:
        if self._undo_open:
            self.scene.close_undo_chunk()
            self._undo_open = False

    def commit(self) -> None:
        self._require_active()
        self.state = TransactionState.COMMITTED
        self.scene.set_session_state(self.session_node, self.state.value)
        self._persist()
        self._close_undo()

    def restore(self) -> RestoreReport:
        if self.state is TransactionState.RESTORED:
            return RestoreReport(True, ("already restored",))
        if self.state is TransactionState.NEW:
            raise BridgeError("cannot restore a transaction that never began")

        self._close_undo()
        details: list[str] = []
        try:
            if self.session_node:
                self.scene.set_session_state(
                    self.session_node, TransactionState.RESTORED.value
                )
            for record in reversed(self.records):
                data = record.data
                if record.kind == "layer":
                    self.scene.delete_layer(data["layer"])
                elif record.kind == "connection":
                    self.scene.disconnect(data["destination"])
                    if data["original_source"]:
                        self.scene.connect(data["original_source"], data["destination"])
                elif record.kind == "attribute":
                    self.scene.set_attribute(data["plug"], data["original_value"])
                elif record.kind == "created_node":
                    self.scene.delete_node(data["node"])
                else:
                    raise BridgeError(f"unknown transaction record: {record.kind}")
                details.append(record.kind)
            self.scene.restore_scene_settings(self.settings)
        except Exception as exc:
            self.state = TransactionState.FAILED
            raise BridgeError(f"transaction restore failed: {exc}") from exc

        self.state = TransactionState.RESTORED
        return RestoreReport(True, tuple(details))


class MayaTransactionScene:
    """Lazy Maya adapter so pure-Python modules remain importable outside Maya."""

    def __init__(self) -> None:
        try:
            import maya.cmds as cmds
        except ImportError as exc:
            raise BridgeError("MayaTransactionScene requires Autodesk Maya") from exc
        self.cmds = cmds

    def create_bridge_session(self, session_id: str, profile_id: str, state: str) -> str:
        node = self.cmds.createNode("network", name=f"asmbSession_{session_id[:12]}")
        for attribute in ("sessionId", "profileId", "state", "manifest"):
            self.cmds.addAttr(node, longName=attribute, dataType="string")
        self.cmds.setAttr(f"{node}.sessionId", session_id, type="string")
        self.cmds.setAttr(f"{node}.profileId", profile_id, type="string")
        self.cmds.setAttr(f"{node}.state", state, type="string")
        return node

    def set_session_state(self, node: str, state: str) -> None:
        if self.cmds.objExists(f"{node}.state"):
            self.cmds.setAttr(f"{node}.state", state, type="string")

    def set_session_manifest(self, node: str, manifest: str) -> None:
        if self.cmds.objExists(f"{node}.manifest"):
            self.cmds.setAttr(f"{node}.manifest", manifest, type="string")

    def open_undo_chunk(self, name: str) -> None:
        self.cmds.undoInfo(openChunk=True, chunkName=name)

    def close_undo_chunk(self) -> None:
        self.cmds.undoInfo(closeChunk=True)

    def capture_scene_settings(self) -> dict[str, Any]:
        evaluation = self.cmds.evaluationManager(query=True, mode=True) or ["parallel"]
        return {
            "time": float(self.cmds.currentTime(query=True)),
            "auto_key": bool(self.cmds.autoKeyframe(query=True, state=True)),
            "time_unit": self.cmds.currentUnit(query=True, time=True),
            "playback_min": float(self.cmds.playbackOptions(query=True, minTime=True)),
            "playback_max": float(self.cmds.playbackOptions(query=True, maxTime=True)),
            "evaluation_mode": evaluation[0],
        }

    def restore_scene_settings(self, settings: dict[str, Any]) -> None:
        self.cmds.currentUnit(time=settings["time_unit"], updateAnimation=False)
        self.cmds.playbackOptions(
            minTime=settings["playback_min"], maxTime=settings["playback_max"]
        )
        self.cmds.evaluationManager(mode=settings["evaluation_mode"])
        self.cmds.currentTime(settings["time"], edit=True)
        self.cmds.autoKeyframe(state=settings["auto_key"])

    def delete_node(self, node: str) -> None:
        if self.cmds.objExists(node):
            self.cmds.delete(node)

    def set_attribute(self, plug: str, value: Any) -> None:
        if isinstance(value, str):
            self.cmds.setAttr(plug, value, type="string")
        else:
            self.cmds.setAttr(plug, value)

    def disconnect(self, destination: str) -> None:
        sources = self.cmds.listConnections(
            destination, source=True, destination=False, plugs=True
        ) or []
        for source in sources:
            self.cmds.disconnectAttr(source, destination)

    def connect(self, source: str, destination: str) -> None:
        self.cmds.connectAttr(source, destination, force=True)

    def delete_layer(self, layer: str) -> None:
        if self.cmds.objExists(layer):
            self.cmds.delete(layer)
