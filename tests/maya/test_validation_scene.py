from __future__ import annotations

import pytest

pytest.importorskip("maya.cmds")

import maya.cmds as cmds

from as_mixamo_bridge.models import CharacterContext, FrameRange
from as_mixamo_bridge.neutral import NeutralMotion
from as_mixamo_bridge.profiles import load_profile
from as_mixamo_bridge.validation import MayaValidationScene, validate_motion


IDENTITY = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)


def setup_module():
    import maya.standalone
    try:
        maya.standalone.initialize(name="python")
    except RuntimeError:
        pass


def teardown_function():
    cmds.file(new=True, force=True)


def test_maya_report_names_single_frame_foot_offset():
    profile = load_profile("as_belato01_v1")
    nodes = {}
    for semantic in profile.skeleton:
        node = cmds.createNode("transform", name=f"Joint_{semantic}")
        nodes[f"joint:{semantic}"] = node
        cmds.setKeyframe(node, attribute="translateX", time=1, value=0)
        cmds.setKeyframe(node, attribute="translateX", time=2, value=0.2 if semantic == "left_foot" else 0)
    relative = {semantic: IDENTITY for semantic in profile.skeleton}
    neutral = NeutralMotion(
        FrameRange(1, 2), (1.0, 2.0), {1.0: IDENTITY, 2.0: IDENTITY},
        {1.0: relative, 2.0: relative}, {}, 30.0,
    )
    target = CharacterContext("|Character", profile.profile_id, nodes=nodes)

    report = validate_motion(MayaValidationScene(), neutral, target, profile)

    issue = next(issue for issue in report.issues if issue.body_part == "left_foot" and issue.frame == 2)
    assert issue.measured == pytest.approx(0.2)
    assert issue.tolerance == 0.1
