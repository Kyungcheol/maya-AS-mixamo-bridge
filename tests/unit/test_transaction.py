from __future__ import annotations

import json

from as_mixamo_bridge.models import CharacterContext
from as_mixamo_bridge.transaction import BridgeTransaction, TransactionState


class MemoryScene:
    def __init__(self):
        self.nodes = {"existing", "source", "replacement"}
        self.attributes = {"existing.tx": 2.0}
        self.connections = {"existing.ty": "source.tx"}
        self.layers = {"ExistingLayer"}
        self.settings = {"time": 1001, "auto_key": True}
        self.events = []
        self.sessions = {}
        self.undo_open = False

    def create_bridge_session(self, session_id, profile_id, state):
        node = f"session_{session_id}"
        self.nodes.add(node)
        self.sessions[node] = {"profile": profile_id, "state": state, "manifest": ""}
        return node

    def set_session_state(self, node, state):
        if node in self.sessions:
            self.sessions[node]["state"] = state

    def set_session_manifest(self, node, manifest):
        if node in self.sessions:
            self.sessions[node]["manifest"] = manifest

    def open_undo_chunk(self, name):
        self.undo_open = True

    def close_undo_chunk(self):
        self.undo_open = False

    def capture_scene_settings(self):
        return dict(self.settings)

    def restore_scene_settings(self, settings):
        self.settings = dict(settings)
        self.events.append("settings")

    def delete_node(self, node):
        self.nodes.discard(node)
        self.sessions.pop(node, None)
        self.events.append(f"delete:{node}")

    def set_attribute(self, plug, value):
        self.attributes[plug] = value
        self.events.append(f"attr:{plug}")

    def disconnect(self, destination):
        self.connections.pop(destination, None)
        self.events.append(f"disconnect:{destination}")

    def connect(self, source, destination):
        self.connections[destination] = source
        self.events.append(f"connect:{source}->{destination}")

    def delete_layer(self, layer):
        self.layers.discard(layer)
        self.events.append(f"layer:{layer}")


def _context():
    return CharacterContext("|Character", "as_belato01_v1")


def test_manifest_serializes_recovery_inputs():
    """Catches a session checkpoint that cannot survive beyond Maya undo history."""
    scene = MemoryScene()
    tx = BridgeTransaction.begin(scene, _context(), session_id="abc")
    tx.record_attribute("existing.tx", 2.0)
    tx.record_connection("existing.ty", "source.tx")

    payload = json.loads(tx.manifest_json())

    assert payload["session_id"] == "abc"
    assert payload["profile_id"] == "as_belato01_v1"
    assert [record["kind"] for record in payload["records"]] == [
        "created_node",
        "attribute",
        "connection",
    ]


def test_restore_is_lifo_scoped_and_idempotent():
    """Catches deleting unrelated data or restoring dependent changes in forward order."""
    scene = MemoryScene()
    tx = BridgeTransaction.begin(scene, _context(), session_id="abc")
    scene.nodes.add("temporary")
    tx.record_created_node("temporary")
    tx.record_attribute("existing.tx", 2.0)
    scene.attributes["existing.tx"] = 9.0
    tx.record_connection("existing.ty", "source.tx")
    scene.connections["existing.ty"] = "replacement.tx"
    scene.layers.add("BridgeLayer")
    tx.record_layer("BridgeLayer")
    scene.settings = {"time": 20, "auto_key": False}

    first = tx.restore()
    events_after_first = tuple(scene.events)
    second = tx.restore()

    assert first.restored and second.restored
    assert "temporary" not in scene.nodes
    assert "existing" in scene.nodes
    assert scene.attributes["existing.tx"] == 2.0
    assert scene.connections["existing.ty"] == "source.tx"
    assert scene.layers == {"ExistingLayer"}
    assert scene.settings == {"time": 1001, "auto_key": True}
    assert scene.events[:4] == [
        "layer:BridgeLayer",
        "disconnect:existing.ty",
        "connect:source.tx->existing.ty",
        "attr:existing.tx",
    ]
    assert tuple(scene.events) == events_after_first


def test_exception_restores_and_closes_undo_chunk():
    """Catches a failed operation leaving scene mutations or an open undo chunk behind."""
    scene = MemoryScene()

    try:
        with BridgeTransaction.begin(scene, _context(), session_id="abc") as tx:
            scene.nodes.add("temporary")
            tx.record_created_node("temporary")
            raise RuntimeError("injected")
    except RuntimeError:
        pass

    assert "temporary" not in scene.nodes
    assert not scene.undo_open
    assert tx.state is TransactionState.RESTORED


def test_commit_closes_undo_and_persists_manifest():
    """Catches a successful transaction that cannot later be explicitly restored."""
    scene = MemoryScene()
    tx = BridgeTransaction.begin(scene, _context(), session_id="abc")
    tx.record_attribute("existing.tx", 2.0)

    tx.commit()

    assert tx.state is TransactionState.COMMITTED
    assert not scene.undo_open
    assert json.loads(scene.sessions[tx.session_node]["manifest"])["records"]
