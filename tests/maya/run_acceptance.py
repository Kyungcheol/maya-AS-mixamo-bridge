from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import traceback
from pathlib import Path


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _leaf(node: str) -> str:
    return node.rsplit("|", 1)[-1].rsplit(":", 1)[-1]


def _one(cmds, leaf: str) -> str:
    matches = [node for node in cmds.ls(long=True) or [] if _leaf(node) == leaf]
    if len(matches) != 1:
        raise RuntimeError(f"expected one {leaf}, found {len(matches)}")
    return matches[0]


def _face_snapshot(cmds) -> dict[str, list[float]]:
    result = {}
    for node in cmds.ls(long=True) or []:
        if "FaceGroup" not in node and "FaceMotionSystem" not in node:
            continue
        result[node] = sorted(set(cmds.keyframe(node, query=True, timeChange=True) or []))
    return result


def _prepare_studio_animation(cmds, source: Path, destination: Path) -> None:
    cmds.file(str(source), open=True, force=True, prompt=False, ignoreVersion=True)
    global_control = _one(cmds, "global_CTRL")
    for frame, value in ((1001, 0.0), (1002, 2.0)):
        cmds.setKeyframe(global_control, attribute="translateX", time=frame, value=value)
    cmds.playbackOptions(minTime=1001, maxTime=1002)
    cmds.file(rename=str(destination))
    cmds.file(save=True, force=True, type="mayaBinary")


def run(as_rig: Path, studio_rig: Path, output_dir: Path) -> dict:
    import maya.cmds as cmds

    from as_mixamo_bridge.commands import BridgeController, MayaBridgeServices

    output_dir.mkdir(parents=True, exist_ok=True)
    hashes_before = {"as": _hash(as_rig), "studio": _hash(studio_rig)}
    as_copy = output_dir / "Belato01_acceptance_input.mb"
    studio_copy = output_dir / "TeamExtra01_acceptance_animated.mb"
    shutil.copy2(as_rig, as_copy)
    _prepare_studio_animation(cmds, studio_rig, studio_copy)

    report = {
        "schema": 1,
        "maya_version": cmds.about(version=True),
        "sources": {"as": str(as_rig), "studio": str(studio_rig)},
        "scenarios": {},
    }

    cmds.file(str(as_copy), open=True, force=True, prompt=False, ignoreVersion=True)
    selected = _one(cmds, "RootX_M")
    face_before = _face_snapshot(cmds)
    controller = BridgeController(MayaBridgeServices())
    session = controller.enter_work_mode(selected)
    adapter_root = session.adapter.controls["control:root:root"]
    position = cmds.xform(adapter_root, query=True, worldSpace=True, translation=True)
    for frame, offset in ((1001, 0.0), (1002, 3.0)):
        cmds.currentTime(frame)
        cmds.xform(
            adapter_root,
            worldSpace=True,
            translation=(position[0] + offset, position[1], position[2]),
        )
        cmds.setKeyframe(adapter_root, attribute=("translateX", "translateY", "translateZ"))
    baked = controller.bake_to_as(selected)
    accepted_path = output_dir / "Belato01_workmode_baked.mb"
    cmds.file(rename=str(accepted_path))
    cmds.file(save=True, force=True, type="mayaBinary")
    face_after = _face_snapshot(cmds)
    restored = controller.restore_pre_conversion(selected)
    report["scenarios"]["work_mode_round_trip"] = {
        "passed": bool(baked.validation.passed and restored.restored),
        "layer": baked.layer,
        "metrics": dict(baked.validation.metrics),
        "issues": [issue.message for issue in baked.validation.issues],
        "face_unchanged": face_before == face_after,
        "output": str(accepted_path),
    }

    cmds.file(str(as_copy), open=True, force=True, prompt=False, ignoreVersion=True)
    selected = _one(cmds, "RootX_M")
    controller = BridgeController(MayaBridgeServices())
    studio_session = controller.apply_mixamo_animation(str(studio_copy), selected)
    studio_baked = controller.bake_to_as(selected)
    report["scenarios"]["studio_file_to_as"] = {
        "passed": bool(studio_baked.validation.passed),
        "source_kind": studio_session.source_kind,
        "metrics": dict(studio_baked.validation.metrics),
        "issues": [issue.message for issue in studio_baked.validation.issues],
        "temporary_source_removed": not any(
            "ASMB_SRC_" in node for node in (cmds.ls() or [])
        ),
    }
    controller.restore_pre_conversion(selected)

    hashes_after = {"as": _hash(as_rig), "studio": _hash(studio_rig)}
    report["source_hashes"] = {
        name: {
            "before": hashes_before[name],
            "after": hashes_after[name],
            "unchanged": hashes_before[name] == hashes_after[name],
        }
        for name in hashes_before
    }
    report["passed"] = all(
        scenario["passed"] for scenario in report["scenarios"].values()
    ) and all(item["unchanged"] for item in report["source_hashes"].values())
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-rig", required=True, type=Path)
    parser.add_argument("--studio-rig", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    import maya.standalone

    try:
        maya.standalone.initialize(name="python")
    except RuntimeError:
        pass
    try:
        report = run(args.as_rig, args.studio_rig, args.output)
    except Exception as exc:
        traceback.print_exc()
        report = {"schema": 1, "passed": False, "fatal_error": str(exc)}
    args.output.mkdir(parents=True, exist_ok=True)
    report_path = args.output / "acceptance.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(report_path)
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
