from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .adapter import AdapterRig, MayaAdapterScene, create_adapter
from .detection import canonical_leaf_name, detect_character
from .models import (
    BridgeError,
    CharacterContext,
    RestoreReport,
    TimingMode,
    ValidationReport,
)
from .neutral import (
    NeutralMotion,
    calibration_matrix,
    multiply_matrices,
    root_relative_matrix,
    validate_matrix,
)
from .profiles import load_profile
from .scene import MayaSceneQuery
from .semantic import solve_pole_vector
from .timing import detect_key_range, sample_frames
from .transaction import BridgeTransaction, MayaTransactionScene
from .validation import MayaValidationScene, validate_motion


class UserCancelled(BridgeError):
    pass


@dataclass(frozen=True, slots=True)
class ControlPolicy:
    arms: str = "fk"
    legs: str = "ik"


@dataclass(slots=True)
class SessionResult:
    context: CharacterContext
    adapter: Any
    transaction: Any
    source_kind: str | None = None


@dataclass(frozen=True, slots=True)
class BakeResult:
    layer: str
    validation: ValidationReport


class BridgeServices(Protocol):
    def detect(self, selected: str) -> CharacterContext: ...
    def begin(self, context: CharacterContext) -> Any: ...
    def create_adapter(self, context: CharacterContext, transaction: Any) -> Any: ...
    def apply_animation(
        self, session: SessionResult, source_path: str | None, policy: ControlPolicy | None
    ) -> str: ...
    def bake(self, session: SessionResult) -> BakeResult: ...


class BridgeController:
    def __init__(self, services: BridgeServices) -> None:
        self.services = services
        self.sessions: dict[str, SessionResult] = {}

    def enter_work_mode(self, selected: str) -> SessionResult:
        context = self.services.detect(selected)
        existing = self.sessions.get(context.root)
        if existing is not None:
            return existing
        transaction = self.services.begin(context)
        try:
            adapter = self.services.create_adapter(context, transaction)
        except Exception:
            transaction.restore()
            raise
        result = SessionResult(context, adapter, transaction)
        self.sessions[context.root] = result
        return result

    def apply_mixamo_animation(
        self, source_path: str | None, selected: str
    ) -> SessionResult:
        session = self.enter_work_mode(selected)
        policy = ControlPolicy() if source_path else None
        try:
            session.source_kind = self.services.apply_animation(
                session, source_path, policy
            )
        except Exception:
            session.transaction.restore()
            self.sessions.pop(session.context.root, None)
            raise
        return session

    def bake_to_as(self, selected: str) -> BakeResult:
        session = self.enter_work_mode(selected)
        try:
            return self.services.bake(session)
        except Exception:
            session.transaction.restore()
            self.sessions.pop(session.context.root, None)
            raise

    def restore_pre_conversion(self, selected: str) -> RestoreReport:
        context = self.services.detect(selected)
        session = self.sessions.pop(context.root, None)
        if session is None:
            raise BridgeError("no active bridge session exists for the selected character")
        return session.transaction.restore()


class MayaBridgeServices:
    _RAW_SKELETON = {
        "hips": "Hips", "spine": "Spine", "chest": "Spine2",
        "neck": "Neck", "head": "Head",
        "left_shoulder": "LeftShoulder", "left_upper_arm": "LeftArm",
        "left_lower_arm": "LeftForeArm", "left_hand": "LeftHand",
        "right_shoulder": "RightShoulder", "right_upper_arm": "RightArm",
        "right_lower_arm": "RightForeArm", "right_hand": "RightHand",
        "left_upper_leg": "LeftUpLeg", "left_lower_leg": "LeftLeg",
        "left_foot": "LeftFoot", "left_toe": "LeftToeBase",
        "right_upper_leg": "RightUpLeg", "right_lower_leg": "RightLeg",
        "right_foot": "RightFoot", "right_toe": "RightToeBase",
    }

    def __init__(self) -> None:
        self.profile = load_profile("as_belato01_v1")
        self.studio_profile = load_profile("studio_mixamo_teamextra01_v1")
        self.timing_mode = TimingMode.PRESERVE_FRAME_NUMBERS
        self.change_scene_fps_to_source = False
        self.last_source_fps: float | None = None
        self.last_source_time_unit: str | None = None

    def detect(self, selected: str) -> CharacterContext:
        if not selected:
            selection = MayaSceneQuery().cmds.ls(selection=True, long=True) or []
            if not selection:
                raise BridgeError("select a node on the AdvancedSkeleton character")
            selected = selection[0]
        return detect_character(MayaSceneQuery(), selected, [self.profile])

    def begin(self, context: CharacterContext) -> BridgeTransaction:
        return BridgeTransaction.begin(MayaTransactionScene(), context)

    def create_adapter(
        self, context: CharacterContext, transaction: BridgeTransaction
    ) -> AdapterRig:
        return create_adapter(MayaAdapterScene(), context, self.profile, transaction)

    def apply_animation(
        self,
        session: SessionResult,
        source_path: str | None,
        policy: ControlPolicy | None,
    ) -> str:
        cmds = MayaSceneQuery().cmds
        imported: list[str] = []
        namespace = ""
        source_profile = None
        if source_path:
            path = Path(source_path)
            if not path.is_file():
                raise BridgeError(f"Mixamo source file does not exist: {path}")
            namespace = f"ASMB_SRC_{uuid.uuid4().hex[:8]}"
            old_time_unit = cmds.currentUnit(query=True, time=True)
            if path.suffix.lower() == ".fbx":
                import maya.mel as mel

                if not cmds.pluginInfo("fbxmaya", query=True, loaded=True):
                    cmds.loadPlugin("fbxmaya", quiet=True)
                escaped = str(path).replace("\\", "/").replace('"', '\\"')
                before = set(cmds.ls(long=True) or [])
                old_namespace = cmds.namespaceInfo(currentNamespace=True)
                cmds.namespace(add=namespace)
                cmds.namespace(set=namespace)
                mel.eval("FBXPushSettings")
                try:
                    mel.eval("FBXImportSetMayaFrameRate -v true")
                    mel.eval(f'FBXImport -f "{escaped}"')
                    imported = sorted(set(cmds.ls(long=True) or []).difference(before))
                    self.last_source_time_unit = cmds.currentUnit(query=True, time=True)
                    self.last_source_fps = self._scene_fps(self.last_source_time_unit)
                finally:
                    mel.eval("FBXPopSettings")
                    cmds.namespace(set=old_namespace)
                    cmds.currentUnit(time=old_time_unit, updateAnimation=False)
            else:
                imported = list(
                    cmds.file(
                        str(path),
                        i=True,
                        namespace=namespace,
                        returnNewNodes=True,
                        ignoreVersion=True,
                        mergeNamespacesOnClash=False,
                        options="v=0;",
                    )
                    or []
                )
                self.last_source_time_unit = old_time_unit
                self.last_source_fps = self._scene_fps(old_time_unit)
            for node in imported:
                if cmds.objExists(node):
                    try:
                        if not cmds.objExists(f"{node}.asmbSessionId"):
                            cmds.addAttr(node, longName="asmbSessionId", dataType="string")
                        cmds.setAttr(
                            f"{node}.asmbSessionId",
                            session.transaction.session_id,
                            type="string",
                        )
                    except RuntimeError:
                        pass
                    session.transaction.record_created_node(node)
            if path.suffix.lower() in {".ma", ".mb"}:
                source_profile = self.studio_profile
                source = self._find_studio_context(imported)
                source_kind = "studio"
            else:
                source = self._raw_context(imported, namespace)
                source_kind = "raw_fbx"
        else:
            source_profile = self.studio_profile
            source = self._find_studio_context(cmds.ls(long=True) or [])
            source_kind = "studio"
            self.last_source_time_unit = cmds.currentUnit(query=True, time=True)
            self.last_source_fps = self._scene_fps(self.last_source_time_unit)

        try:
            if self.change_scene_fps_to_source and self.last_source_time_unit:
                cmds.currentUnit(
                    time=self.last_source_time_unit, updateAnimation=False
                )
            self._key_adapter_from_source(
                session, source, source_profile, policy,
                self.last_source_fps or self._scene_fps(cmds.currentUnit(query=True, time=True)),
            )
        finally:
            if imported:
                existing = [node for node in imported if cmds.objExists(node)]
                if existing:
                    cmds.delete(existing)
                if namespace and cmds.namespace(exists=namespace):
                    cmds.namespace(removeNamespace=namespace, mergeNamespaceWithRoot=True)
        return source_kind

    def _raw_context(self, nodes: list[str], namespace: str) -> CharacterContext:
        joints = [node for node in nodes if MayaSceneQuery().cmds.nodeType(node) == "joint"]
        by_leaf: dict[str, list[str]] = {}
        for node in joints:
            by_leaf.setdefault(canonical_leaf_name(node), []).append(node)
        resolved: dict[str, str] = {}
        for semantic, leaf in self._RAW_SKELETON.items():
            matches = by_leaf.get(leaf, [])
            if len(matches) != 1:
                raise BridgeError(
                    f"raw Mixamo joint {leaf} matched {len(matches)} imported nodes"
                )
            resolved[f"joint:{semantic}"] = matches[0]
        return CharacterContext(
            resolved["joint:hips"], "raw_mixamo_v1", namespace, resolved
        )

    def _find_studio_context(self, nodes: list[str]) -> CharacterContext:
        candidates = [
            node for node in nodes
            if canonical_leaf_name(node) == self.studio_profile.skeleton["hips"]
        ]
        matches: list[CharacterContext] = []
        for candidate in candidates:
            try:
                matches.append(
                    detect_character(MayaSceneQuery(), candidate, [self.studio_profile])
                )
            except BridgeError:
                continue
        unique = {match.root: match for match in matches}
        if len(unique) != 1:
            raise BridgeError(
                f"expected one studio Mixamo source, found {len(unique)}; import or select only one"
            )
        return next(iter(unique.values()))

    def _key_adapter_from_source(
        self,
        session: SessionResult,
        source: CharacterContext,
        source_profile: Any,
        policy: ControlPolicy | None,
        source_fps: float,
    ) -> None:
        cmds = MayaSceneQuery().cmds
        frame_range = detect_key_range(MayaSceneQuery(), source)
        target_fps = self._scene_fps(cmds.currentUnit(query=True, time=True))
        frames = sample_frames(
            frame_range, self.timing_mode, source_fps, target_fps
        )
        if not frames:
            raise BridgeError("source animation has no integer frames")
        cmds.playbackOptions(minTime=frames[0], maxTime=frames[-1])
        cmds.currentTime(frame_range.start, edit=True)

        keyed: dict[str, tuple[str, tuple[float, ...]]] = {}
        for group in ("fk", "ik"):
            for semantic in self.profile.controls[group]:
                source_joint = source.nodes.get(f"joint:{semantic}")
                adapter = session.adapter.controls.get(f"control:{group}:{semantic}")
                if source_joint and adapter:
                    source_rest = cmds.xform(
                        source_joint, query=True, worldSpace=True, matrix=True
                    )
                    adapter_rest = cmds.xform(
                        adapter, query=True, worldSpace=True, matrix=True
                    )
                    keyed[f"control:{group}:{semantic}"] = (
                        source_joint,
                        calibration_matrix(source_rest, adapter_rest),
                    )
        root_adapter = session.adapter.controls["control:root:root"]
        source_hips = source.nodes["joint:hips"]
        keyed["control:root:root"] = (
            source_hips,
            calibration_matrix(
                cmds.xform(source_hips, query=True, worldSpace=True, matrix=True),
                cmds.xform(root_adapter, query=True, worldSpace=True, matrix=True),
            ),
        )

        target_joint_offsets = {
            semantic: calibration_matrix(
                cmds.xform(
                    source.nodes[f"joint:{semantic}"],
                    query=True, worldSpace=True, matrix=True,
                ),
                cmds.xform(
                    session.context.nodes[f"joint:{semantic}"],
                    query=True, worldSpace=True, matrix=True,
                ),
            )
            for semantic in self.profile.skeleton
        }
        pole_specs = {
            "control:pole:left_elbow": (
                "left_upper_arm", "left_lower_arm", "left_hand"
            ),
            "control:pole:right_elbow": (
                "right_upper_arm", "right_lower_arm", "right_hand"
            ),
            "control:pole:left_knee": (
                "left_upper_leg", "left_lower_leg", "left_foot"
            ),
            "control:pole:right_knee": (
                "right_upper_leg", "right_lower_leg", "right_foot"
            ),
        }
        pole_rest = {
            key: tuple(cmds.xform(node, query=True, worldSpace=True, matrix=True))
            for key, node in session.adapter.controls.items()
            if key in pole_specs
        }
        for frame in frames:
            if self.timing_mode is TimingMode.PRESERVE_PLAYBACK_DURATION:
                source_frame = frame_range.start + (
                    (frame - frame_range.start) * source_fps / target_fps
                )
            else:
                source_frame = frame
            cmds.currentTime(source_frame, edit=True)
            for key, (source_joint, offset) in keyed.items():
                adapter = session.adapter.controls[key]
                matrix = multiply_matrices(
                    cmds.xform(source_joint, query=True, worldSpace=True, matrix=True),
                    offset,
                )
                self._key_world_matrix(cmds, adapter, matrix, frame)
            for key, semantics in pole_specs.items():
                if key not in session.adapter.controls:
                    continue
                points = []
                for semantic in semantics:
                    matrix = multiply_matrices(
                        cmds.xform(
                            source.nodes[f"joint:{semantic}"],
                            query=True, worldSpace=True, matrix=True,
                        ),
                        target_joint_offsets[semantic],
                    )
                    points.append((matrix[12], matrix[13], matrix[14]))
                position = solve_pole_vector(points[0], points[1], points[2])
                matrix = list(pole_rest[key])
                matrix[12:15] = position
                self._key_world_matrix(
                    cmds, session.adapter.controls[key], tuple(matrix), frame
                )
            self._key_adapter_semantics(
                cmds, session, source, source_profile, policy, source_frame, frame
            )

    @staticmethod
    def _key_world_matrix(cmds: Any, node: str, matrix: tuple[float, ...], frame: float) -> None:
        cmds.xform(node, worldSpace=True, matrix=list(matrix))
        for attribute in (
            "translateX", "translateY", "translateZ",
            "rotateX", "rotateY", "rotateZ",
        ):
            plug = f"{node}.{attribute}"
            if cmds.objExists(plug) and not cmds.getAttr(plug, lock=True):
                cmds.setKeyframe(node, attribute=attribute, time=frame)

    def _key_adapter_semantics(
        self,
        cmds: Any,
        session: SessionResult,
        source: CharacterContext,
        source_profile: Any,
        policy: ControlPolicy | None,
        source_frame: float,
        target_frame: float,
    ) -> None:
        for name, target_definition in self.profile.switches.items():
            option = session.adapter.controls[f"switch:{name}"]
            plug = f"{option}.{target_definition.attribute}"
            if source_profile is None:
                limb = "arms" if name.startswith("arm") else "legs"
                mode = getattr(policy or ControlPolicy(), limb)
                value = (
                    target_definition.ik_value
                    if mode == "ik" else target_definition.fk_value
                )
            else:
                source_definition = source_profile.switches[name]
                source_node = source.nodes[f"switch:{name}"]
                source_value = float(
                    cmds.getAttr(
                        f"{source_node}.{source_definition.attribute}",
                        time=source_frame,
                    )
                )
                midpoint = (source_definition.fk_value + source_definition.ik_value) * 0.5
                is_ik = (
                    source_value >= midpoint
                    if source_definition.ik_value > source_definition.fk_value
                    else source_value <= midpoint
                )
                value = target_definition.ik_value if is_ik else target_definition.fk_value
            cmds.setKeyframe(
                plug, time=target_frame, value=value,
                inTangentType="stepnext", outTangentType="step",
            )

        if source_profile is None:
            return
        for name, target_definition in self.profile.spaces.items():
            source_definition = source_profile.spaces.get(name)
            if source_definition is None:
                continue
            source_node = source.nodes[f"space:{name}"]
            source_value = float(
                cmds.getAttr(
                    f"{source_node}.{source_definition.attribute}", time=source_frame
                )
            )
            label = min(
                source_definition.values,
                key=lambda item: abs(source_definition.values[item] - source_value),
            )
            if label not in target_definition.values:
                raise BridgeError(f"unsupported target space {name}: {label}")
            option = session.adapter.controls[f"space:{name}"]
            attribute = name.replace(":", "_")
            cmds.setKeyframe(
                f"{option}.{attribute}",
                time=target_frame,
                value=target_definition.values[label],
                inTangentType="stepnext", outTangentType="step",
            )

    def bake(self, session: SessionResult) -> BakeResult:
        cmds = MayaSceneQuery().cmds
        frame_range = detect_key_range(MayaSceneQuery(), session.adapter.context)
        frames = tuple(
            float(frame)
            for frame in range(int(frame_range.start), int(frame_range.end) + 1)
        )
        if not frames:
            raise BridgeError("the adapter has no integer frames to bake")

        root_world: dict[float, tuple[float, ...]] = {}
        joint_relative: dict[float, dict[str, tuple[float, ...]]] = {}
        hips = session.context.nodes["joint:hips"]
        for frame in frames:
            cmds.currentTime(frame, edit=True)
            hips_world = validate_matrix(
                cmds.xform(hips, query=True, worldSpace=True, matrix=True),
                require_invertible=True,
            )
            root_world[frame] = hips_world
            joint_relative[frame] = {
                semantic: root_relative_matrix(
                    cmds.xform(
                        session.context.nodes[f"joint:{semantic}"],
                        query=True,
                        worldSpace=True,
                        matrix=True,
                    ),
                    hips_world,
                )
                for semantic in self.profile.skeleton
            }

        expected = NeutralMotion(
            frame_range,
            frames,
            root_world,
            joint_relative,
            {},
            self._scene_fps(cmds.currentUnit(query=True, time=True)),
        )
        controls = tuple(
            dict.fromkeys(
                node
                for key, node in session.context.nodes.items()
                if key.startswith("control:")
            )
        )
        layer = cmds.animLayer(
            f"ASMB_{session.transaction.session_id[:8]}_Output", override=True
        )
        try:
            attributes = (
                "translateX", "translateY", "translateZ",
                "rotateX", "rotateY", "rotateZ",
            )
            for control in controls:
                for attribute in attributes:
                    plug = f"{control}.{attribute}"
                    if cmds.objExists(plug) and not cmds.getAttr(plug, lock=True):
                        cmds.animLayer(layer, edit=True, attribute=plug)
            semantic_plugs = self._semantic_plugs(session.context)
            for plug in semantic_plugs:
                cmds.animLayer(layer, edit=True, attribute=plug)
            cmds.animLayer(layer, edit=True, selected=True, preferred=True)
            cmds.bakeResults(
                controls,
                time=(frame_range.start, frame_range.end),
                simulation=True,
                sampleBy=1,
                destinationLayer=layer,
                preserveOutsideKeys=True,
                sparseAnimCurveBake=False,
                minimizeRotation=True,
                attribute=attributes,
            )
            if semantic_plugs:
                cmds.bakeResults(
                    semantic_plugs,
                    time=(frame_range.start, frame_range.end),
                    simulation=True,
                    sampleBy=1,
                    destinationLayer=layer,
                    preserveOutsideKeys=True,
                    sparseAnimCurveBake=False,
                )
            session.transaction.restore()
            output = BridgeTransaction.begin(MayaTransactionScene(), session.context)
            session.transaction = output
            output.record_layer(layer)
            report = validate_motion(
                MayaValidationScene(), expected, session.context, self.profile
            )
            output.commit()
        except Exception:
            if cmds.objExists(layer):
                cmds.delete(layer)
            raise
        return BakeResult(layer, report)

    @staticmethod
    def _scene_fps(unit: str) -> float:
        values = {
            "game": 15.0,
            "film": 24.0,
            "pal": 25.0,
            "ntsc": 30.0,
            "show": 48.0,
            "palf": 50.0,
            "ntscf": 60.0,
        }
        if unit in values:
            return values[unit]
        if unit.endswith("fps"):
            return float(unit[:-3])
        raise BridgeError(f"unsupported Maya time unit: {unit}")

    def _semantic_plugs(self, context: CharacterContext) -> tuple[str, ...]:
        plugs: list[str] = []
        for name, definition in self.profile.switches.items():
            plugs.append(
                f"{context.nodes[f'switch:{name}']}.{definition.attribute}"
            )
        for name, definition in self.profile.spaces.items():
            plugs.append(
                f"{context.nodes[f'space:{name}']}.{definition.attribute}"
            )
        return tuple(plugs)


_controller: BridgeController | None = None


def _default_controller() -> BridgeController:
    global _controller
    if _controller is None:
        _controller = BridgeController(MayaBridgeServices())
    return _controller


def enter_work_mode(selected: str = "") -> SessionResult:
    return _default_controller().enter_work_mode(selected)


def apply_mixamo_animation(
    source_path: str | None = None, selected: str = ""
) -> SessionResult:
    return _default_controller().apply_mixamo_animation(source_path, selected)


def bake_to_as(selected: str = "") -> BakeResult:
    return _default_controller().bake_to_as(selected)


def restore_pre_conversion(selected: str = "") -> RestoreReport:
    return _default_controller().restore_pre_conversion(selected)
