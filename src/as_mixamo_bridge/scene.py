from __future__ import annotations

from typing import Protocol, Sequence


class SceneQuery(Protocol):
    """Small read-only scene boundary used by detection and timing."""

    def exists(self, node: str) -> bool: ...

    def ancestors(self, node: str) -> Sequence[str]: ...

    def descendants(self, root: str) -> Sequence[str]: ...

    def is_keyable(self, node: str) -> bool: ...

    def key_times(
        self, node: str, attributes: Sequence[str] | None = None
    ) -> Sequence[float]: ...


class MayaSceneQuery:
    def __init__(self) -> None:
        try:
            import maya.cmds as cmds
        except ImportError as exc:
            raise RuntimeError("MayaSceneQuery requires Autodesk Maya") from exc
        self.cmds = cmds

    def exists(self, node: str) -> bool:
        return bool(self.cmds.objExists(node))

    def ancestors(self, node: str) -> Sequence[str]:
        matches = self.cmds.ls(node, long=True) or []
        if not matches:
            return ()
        current = matches[0]
        result = [current]
        while True:
            parents = self.cmds.listRelatives(current, parent=True, fullPath=True) or []
            if not parents:
                break
            current = parents[0]
            result.append(current)
        return tuple(result)

    def descendants(self, root: str) -> Sequence[str]:
        return (root, *(self.cmds.listRelatives(root, allDescendents=True, fullPath=True) or []))

    def is_keyable(self, node: str) -> bool:
        return bool(self.cmds.listAttr(node, keyable=True, unlocked=True) or [])

    def key_times(
        self, node: str, attributes: Sequence[str] | None = None
    ) -> Sequence[float]:
        kwargs = {"query": True, "timeChange": True}
        if attributes:
            kwargs["attribute"] = list(attributes)
        return tuple(sorted(set(self.cmds.keyframe(node, **kwargs) or [])))
