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
