# HumanIK AS–Mixamo Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a one-click Maya bridge that transfers validated body animation between the supplied studio Mixamo control rig and AdvancedSkeleton while preserving recoverability, frame numbers, FK/IK transitions, and supported space switches.

**Architecture:** Maya HumanIK transfers evaluated body pose through a tagged neutral skeleton. The target is first densely baked to AS FK controls, validated, and then explicit source IK/FK and parent/follow intervals are reconstructed in a separate semantic pass. All scene mutations run inside a recoverable bridge transaction and final acceptance compares the AS deformation result with the neutral reference.

**Tech Stack:** Python 3 for Maya 2025, `maya.cmds`, `maya.api.OpenMaya`, MEL calls to Maya's built-in HumanIK procedures, PySide6, JSON rig profiles, pytest for pure-Python tests, and Maya `mayapy` integration tests.

**Spec:** `docs/superpowers/specs/2026-10-14-as-mixamo-bridge-design.md`

## Global Constraints

- Initial supported host is Autodesk Maya 2025; imports must remain compatible with Maya's Python 3 runtime.
- Maya HumanIK is required; AdvancedSkeleton is expected for AS-target operations, but no AS or third-party source is copied or redistributed.
- Detection is scoped from the selected node to one character hierarchy and must be namespace-safe.
- Default timing preserves exact source frame numbers and never changes scene FPS automatically.
- Facial nodes, keys, blendshapes, and deformation are excluded from transfer and preserved unchanged.
- Output goes to a new AS override animation layer; existing base keys and layers are not deleted or rewritten.
- Dense integer-frame bake is the correctness baseline; key reduction is not part of the initial implementation.
- Original `.ma`, `.mb`, and `.fbx` assets are never saved over, committed, or pushed.
- No conversion is reported successful until deformation validation passes.

## Review Focus

- Nested namespaces and two similar characters in one scene must resolve only the selected hierarchy; Task 2 pins this with an ambiguity test.
- Existing unrelated HumanIK characters must survive session creation and cleanup unchanged; Task 4 pins this with a coexistence integration test.
- A semantic IK pass that fails after a valid FK pass must retain the validated FK fallback; Task 6 pins this with a rollback test.
- Existing AS face and body animation must remain recoverable after success, cancellation, and exceptions; Task 3 pins this with manifest round-trip tests and Task 9 with Maya scene hashes.
- Singular matrices, NaN channels, locked controls, and missing mappings must stop before destructive work or fail validation explicitly; Tasks 2 and 7 pin these error cases.

---

## File Structure

- `src/as_mixamo_bridge/models.py`: immutable domain records, enums, errors, and report types.
- `src/as_mixamo_bridge/profiles.py`: JSON profile loading and validation.
- `src/as_mixamo_bridge/profiles/*.json`: versioned AS and studio Mixamo mappings.
- `src/as_mixamo_bridge/scene.py`: narrow Maya scene-query and mutation interface.
- `src/as_mixamo_bridge/detection.py`: selected-character and rig-profile resolution.
- `src/as_mixamo_bridge/timing.py`: key-range and FPS policy.
- `src/as_mixamo_bridge/transaction.py`: session tags, manifest, undo, and restore.
- `src/as_mixamo_bridge/humanik.py`: isolated HumanIK characterization and source assignment.
- `src/as_mixamo_bridge/neutral.py`: neutral skeleton, cache capture, and source bake.
- `src/as_mixamo_bridge/pose_bake.py`: dense AS FK pose pass and animation-layer output.
- `src/as_mixamo_bridge/semantic.py`: IK/FK and parent/follow event reconstruction.
- `src/as_mixamo_bridge/validation.py`: deformation and switch-boundary comparison.
- `src/as_mixamo_bridge/adapter.py`: lightweight Mixamo-style work controls.
- `src/as_mixamo_bridge/commands.py`: transactional public workflows.
- `src/as_mixamo_bridge/ui.py`: compact PySide6 panel and reports.
- `tests/unit/`: Maya-independent contract and algorithm tests.
- `tests/maya/`: `mayapy` scene integration and supplied-rig acceptance scripts.

### Task 1: Package Contracts and Versioned Profiles

**Files:**
- Create: `pyproject.toml`
- Create: `src/as_mixamo_bridge/__init__.py`
- Create: `src/as_mixamo_bridge/models.py`
- Create: `src/as_mixamo_bridge/profiles.py`
- Create: `src/as_mixamo_bridge/profiles/as_belato01_v1.json`
- Create: `src/as_mixamo_bridge/profiles/studio_mixamo_teamextra01_v1.json`
- Test: `tests/unit/test_profiles.py`

**Interfaces:**
- Produces: `RigKind`, `TimingMode`, `RigProfile`, `CharacterContext`, `FrameRange`, `SwitchEvent`, `ValidationReport`, `BridgeError`, and `load_profile(profile_id: str) -> RigProfile`.
- Produces: profile mappings for required skeleton joints, FK/IK/pole/root/finger controls, switch scaling, space attributes, excluded face roots, HumanIK slot IDs, and validation tolerances.

- [ ] **Step 1: Write failing profile contract tests** asserting both JSON profiles load, required mappings are complete, `0/1` studio switches and `0/10` AS switches are represented, face roots are excluded, and malformed or duplicate mappings raise `ProfileError`.
- [ ] **Step 2: Run `python -m pytest tests/unit/test_profiles.py -v`** and verify collection or import fails because the package is absent.
- [ ] **Step 3: Implement the domain records and `load_profile()`** with strict schema checks and no Maya import at module load.
- [ ] **Step 4: Run `python -m pytest tests/unit/test_profiles.py -v`** and verify all profile tests pass.
- [ ] **Step 5: Commit** with `git commit -m "feat: define bridge contracts and rig profiles"`.

### Task 2: Selection-Scoped Detection and Key-Derived Timing

**Files:**
- Create: `src/as_mixamo_bridge/scene.py`
- Create: `src/as_mixamo_bridge/detection.py`
- Create: `src/as_mixamo_bridge/timing.py`
- Test: `tests/unit/test_detection.py`
- Test: `tests/unit/test_timing.py`

**Interfaces:**
- Consumes: `RigProfile`, `CharacterContext`, `FrameRange`, and `TimingMode` from Task 1.
- Produces: `detect_character(scene: SceneQuery, selected: str, profiles: Sequence[RigProfile]) -> CharacterContext`.
- Produces: `detect_key_range(scene: SceneQuery, context: CharacterContext) -> FrameRange` and `sample_frames(frame_range: FrameRange, mode: TimingMode, source_fps: float, target_fps: float) -> tuple[float, ...]`.

- [ ] **Step 1: Write failing fake-scene tests** for no namespace, nested namespaces, duplicate leaf names outside the selected hierarchy, two characters, missing required nodes, locked/unkeyable mapped controls, face-only keys, switch-only keys, and exact `1001–1120` frame preservation across 24/30 fps.
- [ ] **Step 2: Run `python -m pytest tests/unit/test_detection.py tests/unit/test_timing.py -v`** and verify failures reference missing detection/timing functions.
- [ ] **Step 3: Implement the minimal `SceneQuery` protocol, canonical leaf-name logic, hierarchy scoring, ambiguity rejection, key filtering, and explicit duration-retime sampling.**
- [ ] **Step 4: Run the two unit-test files** and verify all tests pass.
- [ ] **Step 5: Commit** with `git commit -m "feat: detect scoped rigs and keyed timing"`.

### Task 3: Transaction Manifest, Undo, and Durable Restore

**Files:**
- Create: `src/as_mixamo_bridge/transaction.py`
- Test: `tests/unit/test_transaction.py`
- Test: `tests/maya/test_transaction_scene.py`

**Interfaces:**
- Consumes: `CharacterContext` and `SceneQuery` from Tasks 1–2.
- Produces: `BridgeTransaction.begin(scene, context) -> BridgeTransaction`, `record_created_node()`, `record_attribute()`, `record_connection()`, `record_layer()`, `commit()`, and `restore() -> RestoreReport`.
- Produces: bridge session network node attributes `sessionId`, `profileId`, `state`, and serialized manifest path.

- [ ] **Step 1: Write failing unit tests** for manifest serialization, LIFO restoration, idempotent restore, created-node scoping, and restoration after an injected exception.
- [ ] **Step 2: Run `python -m pytest tests/unit/test_transaction.py -v`** and verify the tests fail for the missing transaction.
- [ ] **Step 3: Implement the transaction state machine** (`NEW`, `ACTIVE`, `COMMITTED`, `RESTORED`, `FAILED`) and adapter-backed recording without Maya-global side effects.
- [ ] **Step 4: Write and run a `mayapy` integration test** that creates unrelated keys, layers, connections, and display state; mutates them inside one undo chunk; restores; and compares pre/post snapshots exactly.
- [ ] **Step 5: Run unit and Maya transaction tests** and verify success, cancellation, and exception paths all restore scene settings.
- [ ] **Step 6: Commit** with `git commit -m "feat: add recoverable bridge transactions"`.

### Task 4: Isolated HumanIK and Neutral Motion Capture

**Files:**
- Create: `src/as_mixamo_bridge/humanik.py`
- Create: `src/as_mixamo_bridge/neutral.py`
- Test: `tests/unit/test_neutral_math.py`
- Test: `tests/maya/test_humanik_session.py`

**Interfaces:**
- Consumes: profile HumanIK slot mappings, `CharacterContext`, `FrameRange`, and `BridgeTransaction`.
- Produces: `HumanIKSession.create(scene, context, profile, transaction) -> HumanIKSession`, `set_source(source_character: str)`, and `delete_owned_nodes()`.
- Produces: `capture_neutral_motion(scene, source, profile, frame_range, transaction) -> NeutralMotion`, where `NeutralMotion` contains tagged skeleton paths, root-context matrices, sampled joint matrices, and timing metadata.

- [ ] **Step 1: Write failing pure-math tests** for root-relative matrix capture, rest-pose offsets, scale context, non-invertible matrices, and NaN rejection.
- [ ] **Step 2: Run `python -m pytest tests/unit/test_neutral_math.py -v`** and verify failures for missing neutral APIs.
- [ ] **Step 3: Implement neutral-motion math and the Maya HumanIK wrapper** using unique session-prefixed character names and profile slot IDs; keep MEL calls inside this module.
- [ ] **Step 4: Write a Maya integration test** that creates an unrelated HumanIK character, creates and removes a bridge session, and asserts the unrelated definition and nodes are byte-for-byte unchanged by the recorded snapshot.
- [ ] **Step 5: Run the unit and Maya HumanIK tests** and verify characterization fails before target mutation when slots or stance validation fail.
- [ ] **Step 6: Commit** with `git commit -m "feat: capture motion through isolated HumanIK"`.

### Task 5: Dense AS FK Pose Pass

**Files:**
- Create: `src/as_mixamo_bridge/pose_bake.py`
- Test: `tests/unit/test_pose_plan.py`
- Test: `tests/maya/test_as_fk_bake.py`

**Interfaces:**
- Consumes: `NeutralMotion`, AS `RigProfile`, `CharacterContext`, and `BridgeTransaction`.
- Produces: `build_fk_bake_plan(neutral: NeutralMotion, target: CharacterContext, profile: RigProfile) -> FKBakePlan`.
- Produces: `bake_fk_pose_pass(scene, plan: FKBakePlan, layer_name: str, transaction: BridgeTransaction) -> PosePassResult`.

- [ ] **Step 1: Write failing plan tests** asserting every mapped body part has a solver target, frame numbers remain exact, face nodes are absent, and missing/unkeyable FK controls abort before layer creation.
- [ ] **Step 2: Run `python -m pytest tests/unit/test_pose_plan.py -v`** and verify the missing planner failure.
- [ ] **Step 3: Implement dense root/body/finger FK planning and override-layer bake** from evaluated HumanIK/deformation pose without copying unrelated local Euler values.
- [ ] **Step 4: Run a Maya test on a copy of `Belato01_rig_v01_w01.mb`** at translated/rotated/scaled roots and verify a separate override layer receives only mapped body keys over the detected range.
- [ ] **Step 5: Run unit and Maya FK tests** and verify the saved test output, never the input rig, reopens without a live HumanIK dependency.
- [ ] **Step 6: Commit** with `git commit -m "feat: bake validated AS FK pose pass"`.

### Task 6: FK/IK and Space-Switch Semantic Pass

**Files:**
- Create: `src/as_mixamo_bridge/semantic.py`
- Test: `tests/unit/test_switch_events.py`
- Test: `tests/unit/test_pole_vector.py`
- Test: `tests/maya/test_semantic_bake.py`

**Interfaces:**
- Consumes: verified `PosePassResult`, canonical `SwitchEvent` values, AS profile switch/space mappings, and `BridgeTransaction`.
- Produces: `extract_switch_events(scene, source: CharacterContext, profile: RigProfile, frame_range: FrameRange) -> tuple[SwitchEvent, ...]`.
- Produces: `solve_pole_vector(start, mid, end, previous=None) -> Vector3` and `apply_semantic_pass(scene, pose_pass, events, transaction) -> SemanticPassResult`.

- [ ] **Step 1: Write failing unit tests** for studio `0/1` to AS `0/10`, stepped switch keys, boundary match frames, collinear limbs, stable pole-vector side selection, supported follow spaces, and unsupported-space rejection.
- [ ] **Step 2: Run the semantic unit tests** and verify failures reference the missing event and pole solvers.
- [ ] **Step 3: Implement event extraction and world-space matching** so source pose remains continuous immediately before, on, and after each transition.
- [ ] **Step 4: Write a Maya integration test** with FK→IK→FK arm/leg intervals and parent/follow changes, asserting switch values, end-effector continuity, and no keys outside the output layer.
- [ ] **Step 5: Inject an IK solve failure after a valid FK pass** and verify the semantic changes roll back while the validated FK fallback layer remains inspectable.
- [ ] **Step 6: Run all semantic tests** and verify they pass.
- [ ] **Step 7: Commit** with `git commit -m "feat: restore IK FK and space semantics"`.

### Task 7: Deformation Validation and Acceptance Gate

**Files:**
- Create: `src/as_mixamo_bridge/validation.py`
- Test: `tests/unit/test_validation.py`
- Test: `tests/maya/test_validation_scene.py`

**Interfaces:**
- Consumes: neutral sampled matrices, target deformation joints, profile tolerances, and switch events.
- Produces: `validate_motion(scene, neutral: NeutralMotion, target: CharacterContext, profile: RigProfile, events=()) -> ValidationReport`.
- Produces: per-frame/root/body/end-effector/pole/contact issues with maximum error and a strict `passed` gate.

- [ ] **Step 1: Write failing tests** at and just beyond `0.1 cm`, `0.1°`, `0.25°`, and `0.1 cm` contact-drift limits, plus NaN, singular matrix, locked target, and switch-pop cases.
- [ ] **Step 2: Run `python -m pytest tests/unit/test_validation.py -v`** and verify failures for missing validators.
- [ ] **Step 3: Implement matrix, end-effector, pole-plane, contact, and switch-boundary metrics** with documented profile overrides included in reports.
- [ ] **Step 4: Write a Maya test** that intentionally offsets one foot on one frame and verify the report names the foot, frame, measured error, and failed tolerance.
- [ ] **Step 5: Run validation tests** and verify cleanup is authorized only when `ValidationReport.passed` is true.
- [ ] **Step 6: Commit** with `git commit -m "feat: gate cleanup on deformation validation"`.

### Task 8: Work-Mode Adapter, FBX Input, and Public Commands

**Files:**
- Create: `src/as_mixamo_bridge/adapter.py`
- Create: `src/as_mixamo_bridge/commands.py`
- Test: `tests/unit/test_command_flow.py`
- Test: `tests/maya/test_work_mode.py`

**Interfaces:**
- Consumes: detection, transaction, HumanIK, neutral capture, pose bake, semantic pass, and validation services.
- Produces: `enter_work_mode(selected: str) -> SessionResult`, `apply_mixamo_animation(source_path: str | None, selected: str) -> SessionResult`, `bake_to_as(selected: str) -> BakeResult`, and `restore_pre_conversion(selected: str) -> RestoreReport`.
- Produces: tagged adapter controls for root/pelvis/spine/head/limbs/fingers, FK/IK, poles, and supported follow spaces.

- [ ] **Step 1: Write failing command-flow tests** with fake services for success, user cancellation, raw FBX defaults, studio control semantics, validation failure, and retry after restore.
- [ ] **Step 2: Run `python -m pytest tests/unit/test_command_flow.py -v`** and verify failures for missing orchestration.
- [ ] **Step 3: Implement the smallest tagged adapter and transactional commands**; import FBX into a unique namespace and delete it only after verified adapter capture.
- [ ] **Step 4: Run Maya work-mode tests** asserting AS body controls are selection-protected, face controls stay available, adapter overhead has no duplicate skinned geometry, and all temporary nodes are session-tagged.
- [ ] **Step 5: Run command and work-mode tests** and verify restore returns the scene snapshot exactly.
- [ ] **Step 6: Commit** with `git commit -m "feat: add one-click bridge workflows"`.

### Task 9: Maya UI and Production Acceptance Matrix

**Files:**
- Create: `src/as_mixamo_bridge/ui.py`
- Create: `install.py`
- Create: `tests/maya/run_acceptance.py`
- Create: `docs/testing.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: four public commands and report types from earlier tasks.
- Produces: `show() -> BridgeWindow`, shelf/install instructions, machine-readable acceptance JSON, and human-readable validation summaries.

- [ ] **Step 1: Write a failing UI smoke test** asserting the five primary controls, collapsed Advanced timing/FPS controls, disabled destructive actions without a valid selection, and detailed failed-validation navigation.
- [ ] **Step 2: Run the smoke test under `mayapy`** and verify failure for the missing window.
- [ ] **Step 3: Implement the PySide6 window and installer** without placing transfer logic in UI callbacks.
- [ ] **Step 4: Implement `run_acceptance.py`** to copy each supplied rig into `outputs/acceptance`, exercise namespaces, transformed roots, FK, IK, switches, multiple characters, 24/30 fps, cancellation, restore, and unrelated HumanIK coexistence, then emit JSON.
- [ ] **Step 5: Record pre/post hashes and scene snapshots** proving the source rigs and face subsystem are unchanged and no bridge dependency remains after accepted bake.
- [ ] **Step 6: Run `python -m pytest tests/unit -v` and the full Maya acceptance command documented in `docs/testing.md`**; retain the report in ignored `outputs/` and fix every failure before release.
- [ ] **Step 7: Update README installation, workflow, limitations, and recovery instructions** using only verified behavior.
- [ ] **Step 8: Commit** with `git commit -m "feat: ship Maya bridge UI and acceptance suite"`.

## Self-Review Record

- Spec coverage: detection, timing, HumanIK isolation, neutral capture, two-pass bake, semantics, face exclusion, transaction safety, validation, adapter, raw FBX, UI, and acceptance each map to a task.
- Step scan: each implementation step names one component and each verification step names the proving command or assertion set.
- Type consistency: `CharacterContext`, `FrameRange`, `NeutralMotion`, `PosePassResult`, `SwitchEvent`, `ValidationReport`, and `BridgeTransaction` are introduced before their consumers.
- Review focus: all five high-risk conditions are assigned explicit unit or Maya integration tests.
- Proportion: the plan fixes interfaces and acceptance behavior without transcribing implementation bodies.
