from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from .models import BridgeError, CharacterContext, RigProfile
from .scene import SceneQuery


def canonical_leaf_name(node: str) -> str:
    leaf = node.rsplit("|", 1)[-1]
    return leaf.rsplit(":", 1)[-1]


def _namespace(node: str) -> str:
    leaf = node.rsplit("|", 1)[-1]
    return leaf.rsplit(":", 1)[0] if ":" in leaf else ""


def _contains_excluded_segment(node: str, excluded: set[str]) -> bool:
    return any(canonical_leaf_name(segment) in excluded for segment in node.split("|") if segment)


def _unique(index: dict[str, list[str]], leaf: str, label: str) -> str:
    matches = index.get(leaf, [])
    if not matches:
        raise BridgeError(f"missing {label}: {leaf}")
    if len(matches) > 1:
        raise BridgeError(f"ambiguous {label}: {leaf} matched {len(matches)} nodes")
    return matches[0]


def _match_profile(
    scene: SceneQuery, root: str, profile: RigProfile
) -> CharacterContext:
    excluded = set(profile.excluded_roots)
    index: dict[str, list[str]] = defaultdict(list)
    for node in scene.descendants(root):
        if not _contains_excluded_segment(node, excluded):
            index[canonical_leaf_name(node)].append(node)

    for signature in profile.signature_nodes:
        _unique(index, signature, "signature node")

    nodes: dict[str, str] = {}
    for semantic, leaf in profile.skeleton.items():
        nodes[f"joint:{semantic}"] = _unique(index, leaf, f"joint {semantic}")

    for group, mappings in profile.controls.items():
        for semantic, leaf in mappings.items():
            path = _unique(index, leaf, f"{group} control {semantic}")
            if not scene.is_keyable(path):
                raise BridgeError(f"mapped control is not keyable: {path}")
            nodes[f"control:{group}:{semantic}"] = path

    for name, switch in profile.switches.items():
        path = _unique(index, switch.node, f"switch {name}")
        if not scene.is_keyable(path):
            raise BridgeError(f"mapped switch is not keyable: {path}")
        nodes[f"switch:{name}"] = path

    for name, space in profile.spaces.items():
        path = _unique(index, space.node, f"space {name}")
        if not scene.is_keyable(path):
            raise BridgeError(f"mapped space control is not keyable: {path}")
        nodes[f"space:{name}"] = path

    namespace_source = nodes.get("joint:hips", root)
    return CharacterContext(
        root=root,
        profile_id=profile.profile_id,
        namespace=_namespace(namespace_source),
        nodes=nodes,
    )


def detect_character(
    scene: SceneQuery,
    selected: str,
    profiles: Sequence[RigProfile],
) -> CharacterContext:
    if not selected or not scene.exists(selected):
        raise BridgeError(f"selected node does not exist: {selected!r}")
    if not profiles:
        raise BridgeError("no rig profiles were supplied")

    failures: list[str] = []
    for root in scene.ancestors(selected):
        matches: list[CharacterContext] = []
        for profile in profiles:
            try:
                matches.append(_match_profile(scene, root, profile))
            except BridgeError as exc:
                failures.append(f"{root} / {profile.profile_id}: {exc}")
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            ids = ", ".join(match.profile_id for match in matches)
            raise BridgeError(f"ambiguous rig profiles at {root}: {ids}")

    details = failures[-1] if failures else "no candidate hierarchy"
    raise BridgeError(f"character detection failed; missing or invalid mapping ({details})")
