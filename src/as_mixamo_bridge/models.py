from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class BridgeError(RuntimeError):
    """Base error for an operation that must stop safely."""


class ProfileError(BridgeError):
    """A rig profile is malformed or incomplete."""


class RigKind(str, Enum):
    ADVANCED_SKELETON = "advanced_skeleton"
    STUDIO_MIXAMO = "studio_mixamo"
    RAW_MIXAMO = "raw_mixamo"


class TimingMode(str, Enum):
    PRESERVE_FRAME_NUMBERS = "preserve_frame_numbers"
    PRESERVE_PLAYBACK_DURATION = "preserve_playback_duration"


@dataclass(frozen=True, slots=True)
class FrameRange:
    start: float
    end: float

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("frame range end must not precede start")


@dataclass(frozen=True, slots=True)
class SwitchDefinition:
    node: str
    attribute: str
    fk_value: float
    ik_value: float

    def __post_init__(self) -> None:
        if self.fk_value == self.ik_value:
            raise ProfileError("FK and IK switch values must differ")


@dataclass(frozen=True, slots=True)
class SpaceDefinition:
    node: str
    attribute: str
    values: Mapping[str, float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


@dataclass(frozen=True, slots=True)
class RigProfile:
    profile_id: str
    version: int
    rig_kind: RigKind
    signature_nodes: tuple[str, ...]
    skeleton: Mapping[str, str]
    controls: Mapping[str, Mapping[str, str]]
    switches: Mapping[str, SwitchDefinition]
    spaces: Mapping[str, SpaceDefinition]
    excluded_roots: tuple[str, ...]
    humanik_slots: Mapping[int, str]
    tolerances: Mapping[str, float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "skeleton", MappingProxyType(dict(self.skeleton)))
        object.__setattr__(
            self,
            "controls",
            MappingProxyType(
                {name: MappingProxyType(dict(values)) for name, values in self.controls.items()}
            ),
        )
        object.__setattr__(self, "switches", MappingProxyType(dict(self.switches)))
        object.__setattr__(self, "spaces", MappingProxyType(dict(self.spaces)))
        object.__setattr__(self, "humanik_slots", MappingProxyType(dict(self.humanik_slots)))
        object.__setattr__(self, "tolerances", MappingProxyType(dict(self.tolerances)))


@dataclass(frozen=True, slots=True)
class CharacterContext:
    root: str
    profile_id: str
    namespace: str = ""
    nodes: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", MappingProxyType(dict(self.nodes)))


@dataclass(frozen=True, slots=True)
class SwitchEvent:
    frame: float
    channel: str
    previous_value: float
    value: float
    world_matrices: Mapping[str, tuple[float, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "world_matrices", MappingProxyType(dict(self.world_matrices)))


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    category: str
    body_part: str
    frame: float
    measured: float
    tolerance: float
    message: str


@dataclass(frozen=True, slots=True)
class ValidationReport:
    issues: tuple[ValidationIssue, ...] = ()
    metrics: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))

    @property
    def passed(self) -> bool:
        return not self.issues


@dataclass(frozen=True, slots=True)
class RestoreReport:
    restored: bool
    details: tuple[str, ...] = ()


JsonObject = Mapping[str, Any]
