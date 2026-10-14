from __future__ import annotations

import math

from .models import BridgeError, CharacterContext, FrameRange, TimingMode
from .scene import SceneQuery


def detect_key_range(scene: SceneQuery, context: CharacterContext) -> FrameRange:
    times: list[float] = []
    for node in dict.fromkeys(context.nodes.values()):
        times.extend(float(frame) for frame in scene.key_times(node))
    finite = [frame for frame in times if math.isfinite(frame)]
    if not finite:
        raise BridgeError("No supported body keys were found on the selected character")
    return FrameRange(min(finite), max(finite))


def _dense_frames(frame_range: FrameRange) -> tuple[float, ...]:
    start = frame_range.start
    end = frame_range.end
    frames: list[float] = []
    if not float(start).is_integer():
        frames.append(start)
    frames.extend(float(frame) for frame in range(math.ceil(start), math.floor(end) + 1))
    if not float(end).is_integer() and (not frames or frames[-1] != end):
        frames.append(end)
    return tuple(dict.fromkeys(frames))


def sample_frames(
    frame_range: FrameRange,
    mode: TimingMode,
    source_fps: float,
    target_fps: float,
) -> tuple[float, ...]:
    if source_fps <= 0 or target_fps <= 0:
        raise ValueError("source and target FPS must be positive")
    if mode is TimingMode.PRESERVE_FRAME_NUMBERS:
        return _dense_frames(frame_range)
    if mode is TimingMode.PRESERVE_PLAYBACK_DURATION:
        interval_count = round((frame_range.end - frame_range.start) * target_fps / source_fps)
        return tuple(frame_range.start + float(index) for index in range(interval_count + 1))
    raise ValueError(f"unsupported timing mode: {mode!r}")
