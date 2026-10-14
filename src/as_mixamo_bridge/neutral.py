from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Protocol, Sequence

from .models import BridgeError, CharacterContext, FrameRange, RigProfile
from .transaction import BridgeTransaction


Matrix = tuple[float, ...]


def _coerce_matrix(matrix: Sequence[float]) -> Matrix:
    if len(matrix) != 16:
        raise BridgeError(f"matrix must have 16 values, got {len(matrix)}")
    result = tuple(float(value) for value in matrix)
    if not all(math.isfinite(value) for value in result):
        raise BridgeError("matrix contains NaN or infinite values")
    return result


def multiply_matrices(left: Sequence[float], right: Sequence[float]) -> Matrix:
    a = _coerce_matrix(left)
    b = _coerce_matrix(right)
    return tuple(
        sum(a[row * 4 + inner] * b[inner * 4 + column] for inner in range(4))
        for row in range(4)
        for column in range(4)
    )


def invert_matrix(matrix: Sequence[float]) -> Matrix:
    values = _coerce_matrix(matrix)
    rows = [
        [values[row * 4 + column] for column in range(4)]
        + [1.0 if row == column else 0.0 for column in range(4)]
        for row in range(4)
    ]
    for column in range(4):
        pivot = max(range(column, 4), key=lambda row: abs(rows[row][column]))
        if abs(rows[pivot][column]) <= 1e-12:
            raise BridgeError("matrix is non-invertible")
        rows[column], rows[pivot] = rows[pivot], rows[column]
        divisor = rows[column][column]
        rows[column] = [value / divisor for value in rows[column]]
        for row in range(4):
            if row == column:
                continue
            factor = rows[row][column]
            rows[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(rows[row], rows[column])
            ]
    return tuple(rows[row][column] for row in range(4) for column in range(4, 8))


def validate_matrix(
    matrix: Sequence[float], *, require_invertible: bool = False
) -> Matrix:
    result = _coerce_matrix(matrix)
    if require_invertible:
        invert_matrix(result)
    return result


def root_relative_matrix(joint_world: Sequence[float], root_world: Sequence[float]) -> Matrix:
    return multiply_matrices(joint_world, invert_matrix(root_world))


def calibration_matrix(source_rest: Sequence[float], target_rest: Sequence[float]) -> Matrix:
    return multiply_matrices(invert_matrix(source_rest), target_rest)


@dataclass(frozen=True, slots=True)
class NeutralMotion:
    frame_range: FrameRange
    frames: tuple[float, ...]
    root_world: Mapping[float, Matrix]
    joint_relative: Mapping[float, Mapping[str, Matrix]]
    neutral_nodes: Mapping[str, str]
    source_fps: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "root_world", MappingProxyType(dict(self.root_world)))
        object.__setattr__(
            self,
            "joint_relative",
            MappingProxyType(
                {frame: MappingProxyType(dict(values)) for frame, values in self.joint_relative.items()}
            ),
        )
        object.__setattr__(self, "neutral_nodes", MappingProxyType(dict(self.neutral_nodes)))


class NeutralScene(Protocol):
    def set_time(self, frame: float) -> None: ...
    def world_matrix(self, node: str) -> Sequence[float]: ...
    def create_neutral_skeleton(
        self, profile: RigProfile, session_id: str
    ) -> Mapping[str, str]: ...
    def apply_neutral_sample(
        self,
        nodes: Mapping[str, str],
        frame: float,
        root_world: Matrix,
        relative_matrices: Mapping[str, Matrix],
    ) -> None: ...
    def fps(self) -> float: ...


def capture_neutral_motion(
    scene: NeutralScene,
    source: CharacterContext,
    profile: RigProfile,
    frame_range: FrameRange,
    transaction: BridgeTransaction,
) -> NeutralMotion:
    neutral_nodes = dict(scene.create_neutral_skeleton(profile, transaction.session_id))
    for node in neutral_nodes.values():
        transaction.record_created_node(node)
    frames = tuple(float(frame) for frame in range(math.ceil(frame_range.start), math.floor(frame_range.end) + 1))
    root_world_by_frame: dict[float, Matrix] = {}
    relative_by_frame: dict[float, dict[str, Matrix]] = {}
    root_node = source.nodes.get("joint:hips")
    if not root_node:
        raise BridgeError("source context has no hips joint")
    for frame in frames:
        scene.set_time(frame)
        root_world = validate_matrix(scene.world_matrix(root_node), require_invertible=True)
        relative = {
            semantic: root_relative_matrix(
                scene.world_matrix(source.nodes[f"joint:{semantic}"]), root_world
            )
            for semantic in profile.skeleton
        }
        scene.apply_neutral_sample(neutral_nodes, frame, root_world, relative)
        root_world_by_frame[frame] = root_world
        relative_by_frame[frame] = relative
    return NeutralMotion(
        frame_range=frame_range,
        frames=frames,
        root_world=root_world_by_frame,
        joint_relative=relative_by_frame,
        neutral_nodes=neutral_nodes,
        source_fps=float(scene.fps()),
    )
