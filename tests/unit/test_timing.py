from __future__ import annotations

import pytest

from as_mixamo_bridge.models import BridgeError, CharacterContext, FrameRange, TimingMode
from as_mixamo_bridge.timing import detect_key_range, sample_frames


class KeyScene:
    def __init__(self, keys):
        self.keys = keys

    def key_times(self, node, attributes=None):
        return self.keys.get(node, ())


def test_key_range_ignores_unmapped_face_animation_and_uses_switch_keys():
    """Catches timeline expansion from face keys and omission of switch-only endpoints."""
    scene = KeyScene({"body": (1010, 1050), "switch": (1001, 1120), "face": (1, 5000)})
    context = CharacterContext(
        root="|Character",
        profile_id="as_belato01_v1",
        nodes={"joint:hips": "body", "switch:arm_l": "switch"},
    )

    assert detect_key_range(scene, context) == FrameRange(1001, 1120)


def test_key_range_requires_at_least_one_supported_key():
    """Catches silently baking an arbitrary playback range when no body keys exist."""
    context = CharacterContext("|Character", "as_belato01_v1", nodes={"joint:hips": "body"})
    with pytest.raises(BridgeError, match="No supported body keys"):
        detect_key_range(KeyScene({}), context)


def test_preserve_frame_numbers_is_default_even_when_fps_differs():
    """Catches an accidental duration retime of the user's exact key frame numbers."""
    frames = sample_frames(
        FrameRange(1001, 1120), TimingMode.PRESERVE_FRAME_NUMBERS, 24.0, 30.0
    )
    assert frames[0] == 1001
    assert frames[-1] == 1120
    assert len(frames) == 120


def test_duration_mode_is_explicit_and_rejects_invalid_fps():
    """Catches zero-FPS division and verifies retiming only in the advanced mode."""
    frames = sample_frames(
        FrameRange(1001, 1120), TimingMode.PRESERVE_PLAYBACK_DURATION, 24.0, 30.0
    )
    assert frames == tuple(float(frame) for frame in range(1001, 1151))
    with pytest.raises(ValueError, match="positive"):
        sample_frames(FrameRange(1, 2), TimingMode.PRESERVE_PLAYBACK_DURATION, 0, 30)
