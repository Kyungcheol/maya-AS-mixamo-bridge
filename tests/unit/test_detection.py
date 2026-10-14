from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from as_mixamo_bridge.detection import canonical_leaf_name, detect_character
from as_mixamo_bridge.models import BridgeError
from as_mixamo_bridge.profiles import load_profile


@dataclass
class FakeScene:
    parents: dict[str, str | None]
    keyable: dict[str, bool] = field(default_factory=dict)
    keys: dict[str, tuple[float, ...]] = field(default_factory=dict)

    def exists(self, node):
        return node in self.parents

    def ancestors(self, node):
        result = []
        current = node
        while current is not None:
            result.append(current)
            current = self.parents[current]
        return tuple(result)

    def descendants(self, root):
        result = []
        for node in self.parents:
            current = node
            while current is not None:
                if current == root:
                    result.append(node)
                    break
                current = self.parents[current]
        return tuple(result)

    def is_keyable(self, node):
        return self.keyable.get(node, True)

    def key_times(self, node, attributes=None):
        return self.keys.get(node, ())


def _scene_for_profile(namespace="", root="|Character"):
    profile = load_profile("as_belato01_v1")
    prefix = f"{namespace}:" if namespace else ""
    parents = {root: None}
    for name in set(profile.signature_nodes) | set(profile.skeleton.values()):
        parents[f"{root}|{prefix}{name}"] = root
    for group in profile.controls.values():
        for name in group.values():
            parents.setdefault(f"{root}|{prefix}{name}", root)
    for switch in profile.switches.values():
        parents.setdefault(f"{root}|{prefix}{switch.node}", root)
    for space in profile.spaces.values():
        parents.setdefault(f"{root}|{prefix}{space.node}", root)
    parents[f"{root}|{prefix}Geometry|{prefix}BodyMesh"] = root
    return FakeScene(parents), f"{root}|{prefix}Geometry|{prefix}BodyMesh", profile


def test_canonical_leaf_removes_dag_and_nested_namespace():
    """Catches matching failures caused solely by nested namespace prefixes."""
    assert canonical_leaf_name("|world|shot:char:FKIKArm_L") == "FKIKArm_L"


@pytest.mark.parametrize("namespace", ["", "shot:Belato01_rig_v01_w01"])
def test_detection_is_namespace_agnostic_and_selection_scoped(namespace):
    """Catches global-name lookup and namespace-sensitive detection."""
    scene, selected, profile = _scene_for_profile(namespace)
    other, _, _ = _scene_for_profile("other", "|OtherCharacter")
    scene.parents.update(other.parents)

    context = detect_character(scene, selected, [profile])

    assert context.root == "|Character"
    assert context.profile_id == profile.profile_id
    assert context.nodes["joint:hips"].startswith("|Character|")
    assert not context.nodes["joint:hips"].startswith("|OtherCharacter|")


def test_detection_rejects_missing_required_node():
    """Catches a partial profile match that would produce a degraded bake."""
    scene, selected, profile = _scene_for_profile()
    missing = next(node for node in scene.parents if canonical_leaf_name(node) == "Ankle_L")
    del scene.parents[missing]

    with pytest.raises(BridgeError, match="missing"):
        detect_character(scene, selected, [profile])


def test_detection_rejects_unkeyable_mapped_control():
    """Catches a target rig whose required output control cannot receive keys."""
    scene, selected, profile = _scene_for_profile()
    locked = next(node for node in scene.parents if canonical_leaf_name(node) == "FKHead_M")
    scene.keyable[locked] = False

    with pytest.raises(BridgeError, match="not keyable"):
        detect_character(scene, selected, [profile])
