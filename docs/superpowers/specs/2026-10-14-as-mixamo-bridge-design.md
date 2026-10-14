# AS–Mixamo Bridge: Maya One-Click Retargeting Design

Date: 2026-10-14

Primary host: Autodesk Maya 2025

Initial rig profiles: studio Mixamo control rig (`TeamExtra01_rig_v01.mb`) and AdvancedSkeleton (`Belato01_rig_v01_w01.mb`)

## 1. Goal

Build a Maya Python tool that lets an animator work in a Mixamo-style hybrid control rig and return the finished body animation to an AdvancedSkeleton (AS) rig without handling namespaces, world origin, scale, rest-pose offsets, frame ranges, or controller mappings manually.

The tool must prioritize animation fidelity and recoverability over bake speed or implementation simplicity. It must never silently accept a degraded conversion.

## 2. User Workflow

The normal workflow has four primary actions:

1. Select any node belonging to an AS character and click **Mixamo Work Mode**.
2. Animate with the generated Mixamo-style adapter controls, or click **Apply Mixamo Animation** to load animation from a Mixamo FBX or the studio Mixamo control rig.
3. Click **Bake to AS**. The tool writes the result to a new AS animation layer and validates it.
4. If the result is accepted, the animator uses Maya **Save As**. If it is not accepted, the animator clicks **Restore Pre-Conversion State**.

The current Maya scene remains the working scene. The tool does not require the animator to export a work scene or switch documents.

## 3. Supported Scope

### Included

- Root motion, pelvis, spine, neck, head, clavicles, arms, legs, feet, toes, hands, and fingers.
- FK, IK, and keyed FK/IK transitions for arms and legs.
- IK end-effectors and pole vectors.
- Supported parent/follow/space transitions with world-pose preservation.
- Existing studio Mixamo control rigs that follow the `TeamExtra01` structure.
- Raw Mixamo FBX skeleton animation.
- AS rigs that follow the naming and graph conventions found in `Belato01`.
- Namespaced, referenced, translated, rotated, or scaled character roots.
- Multiple characters in one scene when the user selects the intended character.

### Excluded

- Facial controls, facial deformation joints, facial blendshapes, and facial animation transfer.
- Automatic transfer of arbitrary custom props or character-specific secondary controls that have no declared profile mapping.
- Guessing IK/FK or space-switch intent from raw joint-only FBX data. Raw FBX contains pose motion, not animator control-state semantics.

Excluded facial systems are preserved, not deleted or reset. Head and neck body motion remains included.

## 4. Rig Detection and Profiles

Detection starts from the user's selected node and walks to the character root. It does not search globally and choose the first matching name.

Node matching uses a canonical leaf name with DAG paths and namespaces removed. For example, `Belato01_rig_v01_w01:FKIKArm_L` resolves to `FKIKArm_L`, but only inside the selected character hierarchy.

Each supported rig type has a versioned profile containing:

- Structural signature nodes.
- Deformation or animation skeleton mappings.
- FK, IK, pole-vector, root, and finger control mappings.
- IK/FK switch ranges and direction.
- Parent/follow/space mappings.
- Rest-pose markers and scale references.
- Nodes and subtrees that must be excluded.

Initial verified profile facts:

- Studio Mixamo control rig: `FK_IK` uses `0 = FK`, `1 = IK`.
- AS rig: `FKIKBlend` uses `0 = FK`, `10 = IK`.
- Studio Mixamo parent controls include `FollowBody`, `ParentToGlobal`, `FollowHand`, and `FollowFoot`.
- AS parent behavior is expressed through `follow` attributes and matching controls.

If a profile signature is incomplete or ambiguous, the tool stops and reports the missing nodes. It does not fall back to a similarly named node outside the selected hierarchy.

## 5. Architecture

### 5.1 Prior Art and Dependency Boundary

The bridge does not implement a complete character-retargeting solver from
scratch. Maya HumanIK is the pose-retargeting backbone because it already
handles characterized skeletons, rest-pose differences, scale compensation,
and non-destructive source-to-target evaluation.

AdvancedSkeleton's documented Create HumanIK, Bake HumanIK, and Motion Capture
workflows establish the production pattern of driving the deformation system,
baking through a temporary neutral skeleton, and finally keying AS controls.
The installed AdvancedSkeleton source and third-party open-source tools are
research references only. Their code is not copied or redistributed.

The bridge owns the behavior missing from those workflows:

- Selection-scoped, namespace-safe character detection.
- Versioned mappings for the two supplied production rigs.
- Key-derived frame ranges and explicit FPS policy.
- Transactional output layers and durable recovery.
- Preservation of authored FK/IK and parent/follow events.
- Face-system exclusion and preservation.
- Per-frame deformation validation before cleanup.

Maya HumanIK is a required built-in dependency. AdvancedSkeleton is expected
for AS-target operations, but the bridge does not vendor or modify it.

### 5.2 Lightweight Adapter Controls

The tool adds a tagged, temporary Mixamo-style adapter control set over the selected AS rig. It does not add a second skinned character or a permanently active duplicate deformation skeleton.

The adapter contains only the controls needed for body animation:

- Root and pelvis.
- Spine, neck, head, and clavicles.
- Arm and leg FK controls.
- Hand and foot IK controls.
- Arm and leg pole-vector controls.
- Toe and finger controls.
- FK/IK and supported parent/follow attributes.

AS body control shapes are placed in a temporary display layer so animators cannot accidentally key both interfaces. This is a selection/display safeguard, not deletion or permanent attribute locking. Face controls remain available.

Adapter-to-AS driving uses the smallest reliable connection graph. FK controls drive AS FK controls; IK effectors and pole vectors drive their AS counterparts; switch attributes are converted through explicit profile rules. Connections exist only during Mixamo Work Mode and are removed after a successful AS bake or restore.

### 5.3 Neutral Retarget Skeleton and Canonical Motion Cache

All transfers first bake evaluated body motion to a tagged neutral skeleton
characterized for HumanIK. The neutral skeleton is temporary scene data and
contains no render geometry. It breaks live dependencies on the source rig and
provides a stable result that can be compared after the target controls are
baked.

Alongside it, a rig-independent canonical motion cache stores, for every
sampled frame:

- Character-root-relative world matrices for mapped body joints.
- Root translation, rotation, and scale context.
- Source and target rest-pose calibration matrices.
- Explicit source FK/IK states when available.
- Explicit parent/follow/space states when available.
- Source frame range, frame numbers, and FPS metadata.
- Contact observations for hands and feet used by validation.

The neutral skeleton and cache together are the ground truth for solving and
validation. Local Euler channel values are never copied directly between
unrelated rigs.

### 5.4 HumanIK Characterization

Every HumanIK character definition receives a bridge-session-specific name.
Character slots are populated from a verified profile and hierarchy-scoped DAG
paths, never from global leaf-name searches. Existing HumanIK characters in the
scene are not renamed, reused, or deleted.

Characterization is validated before animation is applied. Missing required
slots, duplicate joints, invalid stance, or a failed HumanIK definition stops
the transaction before target keys are changed.

### 5.5 Two-Pass Target Bake

The final AS conversion is deliberately split into two passes:

1. **Pose pass:** HumanIK drives the target deformation system and the bridge
   densely bakes the evaluated result to AS FK body controls over the detected
   keyed range. This produces the safest complete body-motion result.
2. **Semantic pass:** intervals that explicitly used IK or a supported
   parent/follow space in the studio control rig are converted from the verified
   FK result to the corresponding AS IK controls, pole vectors, and switch
   attributes. Boundary controls are matched in world space before each switch.

Raw joint-only Mixamo FBX has no authored control-state semantics, so it keeps
the declared default policy: leg IK and arm FK. A user may choose a different
policy before the semantic pass.

If the semantic pass fails validation, the verified FK pose-pass layer remains
available as a safe fallback. The tool never substitutes a failed IK result
without reporting it.

### 5.6 Transfer Directions

#### AS to Mixamo Work Mode

1. Detect and validate the selected AS rig.
2. Create a recovery checkpoint and transaction manifest.
3. Detect the first and last keyed body frames.
4. Bake evaluated AS deformation poses to the neutral HumanIK skeleton and
   canonical cache.
5. Create and align adapter controls.
6. Retarget the neutral HumanIK character to the adapter and bake its controls.
7. Activate the temporary adapter-to-AS drive graph.
8. Protect AS body controls through the display layer.

#### Raw Mixamo FBX to Work Mode

1. Import the FBX into a unique temporary namespace.
2. Detect `Hips` and the Mixamo skeleton by hierarchy, not namespace.
3. Characterize it as a session-specific HumanIK source and bake its evaluated
   animation to the neutral skeleton and canonical cache.
4. Retarget the neutral motion onto adapter controls.
5. Remove the imported temporary skeleton after a verified adapter bake.

Raw FBX receives a declared default control policy because it has no IK/FK semantics. The initial default is leg IK and arm FK. The animator may change or match modes before the final AS bake.

#### Studio Mixamo Control Rig to AS

The tool reads body motion from the `AnimData_*` result skeleton and reads FK/IK and parent/follow intent from the visible control attributes. Pose is baked to the neutral HumanIK skeleton; control-state metadata is stored separately in the canonical cache before solving AS controls.

#### Work Mode to AS

1. Capture the currently evaluated work-mode motion and switch metadata.
2. Bake the evaluated work-mode result to the neutral HumanIK skeleton.
3. Create a new AS override animation layer.
4. Perform the dense FK pose pass for root, body, and fingers.
5. Validate the FK result against the neutral target.
6. Convert explicitly IK-authored and supported space-switched intervals in the
   semantic pass, inserting world-space match keys at boundaries.
7. Remove all temporary driving connections.
8. Evaluate the AS rig using only its own controls.
9. Validate the resulting deformation pose against the neutral target.
10. Mark the bake successful only if validation passes.

## 6. Frame and FPS Policy

The default range is the earliest through latest key found on supported body controls, result joints, and switch attributes. Facial keys, SDK curves, rig setup nodes, and unrelated scene animation are excluded.

The default timing mode is **Preserve Frame Numbers**:

- Source `1001–1120` becomes target `1001–1120`.
- The tool does not change the Maya scene FPS automatically.
- All FK/IK and parent/follow transitions remain on the same numbered frames.

An advanced FPS section provides:

- Detected source FPS.
- Current target-scene FPS.
- **Preserve Frame Numbers** (default).
- **Preserve Playback Duration** (explicit retime and resample).
- An optional, separately confirmed scene-FPS change.

Within the selected range, validation samples every integer frame. Sparse editable keys may be reduced only as an explicit post-process after a dense bake has passed validation.

## 7. IK/FK and Space Switching

Explicit source control-rig switch keys are preserved as semantic events, not inferred from the final joint rotations.

For each switch event:

1. Evaluate the source world pose immediately before the switch.
2. Match the incoming target control system to the outgoing pose.
3. Key both control systems and the switch at the required boundary frames.
4. Re-evaluate after the switch and compare end-effector and joint results.

Parent/follow/space changes follow the same world-pose-preserving process. Unsupported source spaces cause a reported validation failure instead of a silent substitution.

## 8. Data Safety and Recovery

Before the first mutation, the tool creates:

- A tagged bridge session node with a unique ID.
- A transaction manifest containing all created nodes, altered attributes, original incoming connections, display states, animation layers, and time settings.
- A recovery snapshot sufficient to restore the pre-conversion state.
- A single Maya undo chunk for immediate one-step Undo when Maya can safely retain it.

The tool never deletes or overwrites existing AS body or facial animation as part of the normal workflow. Output is written to a new **override** animation layer so existing lower layers and base keys remain intact while the transferred result reproduces the canonical target. Muting or deleting the new layer reveals the pre-conversion body animation.

**Restore Pre-Conversion State** removes only nodes and layers tagged with the active bridge session, restores recorded attributes and connections, and verifies the selected AS rig against the checkpoint. If manifest-based restoration cannot be verified, the tool offers the durable recovery snapshot instead of claiming success.

Temporary source FBX nodes are deleted only after their motion has been baked to adapter controls and that bake has passed validation.

## 9. Validation

Validation compares the final AS deformation result with the target-space canonical motion, not with raw source local channels.

Checks include:

- Root translation and orientation.
- Body-joint angular error.
- Hand and foot end-effector position and orientation.
- Pole-plane consistency for elbows and knees.
- Foot-contact drift during detected stationary intervals.
- Discontinuities at FK/IK and parent/follow switch frames.
- Missing or unkeyable target controls.
- NaN, infinite, or non-invertible matrices.

The report contains maximum error, affected body part, and frame number. A conversion that exceeds its profile's tolerance is marked failed and remains isolated on the output layer for inspection or rollback. The UI must not display a generic success message for a failed validation.

Initial validation limits are 0.1 cm for root/hand/foot position, 0.1 degrees for root/hand/foot orientation, 0.25 degrees for other mapped body-joint orientation, and 0.1 cm of foot drift across a detected stationary interval. Tolerance values are stored in the versioned rig profile so they can be calibrated against the two supplied production rigs without changing solver code. A profile may loosen a tolerance only with a documented reason that is shown in the validation report; it cannot do so silently.

## 10. Performance Policy

Correctness is not traded for speed. Performance is improved only through changes that produce identical validated results.

The initial implementation avoids:

- Duplicate skinned render geometry.
- A permanently active duplicate full control rig.
- Long-lived imported FBX skeletons.
- Unnecessary facial, hair, renderer, or clothing-rig traversal.

If the lightweight path cannot meet validation for a limb or switch interval, that region falls back to a denser frame-by-frame solve. Bake duration may increase; output accuracy may not decrease.

Playback performance will be measured on the supplied rigs before and during Work Mode. The report will identify adapter overhead separately from the existing AS rig cost.

## 11. Error Handling

All public operations are transactional. On an exception or user cancellation:

- Progress UI closes.
- Maya time, auto-key, refresh, and evaluation settings are restored.
- Newly created uncommitted nodes are removed.
- Original AS connections and display states are restored.
- The recovery checkpoint remains available.
- The Script Editor receives a detailed traceback and the user receives a concise actionable message.

Missing Ornatrix, V-Ray, or unrelated render nodes do not block body-rig conversion. The tool never saves over the supplied source file while those plugins are unavailable.

## 12. UI

The default panel remains deliberately small:

- Character status and detected rig profile.
- **Mixamo Work Mode**.
- **Apply Mixamo Animation**.
- **Bake to AS**.
- **Restore Pre-Conversion State**.
- Validation status.

An expandable Advanced section contains frame-range override, FPS policy, layer naming, source-control policy, mapping diagnostics, and validation details.

## 13. Implementation Boundaries

The implementation will be a small Maya Python package rather than a single monolithic script. Planned modules separate:

- UI and command orchestration.
- Rig detection and versioned profiles.
- HumanIK characterization and session isolation.
- Neutral-skeleton construction and dense pose baking.
- Canonical motion capture.
- Adapter construction and connection management.
- FK/IK and space solvers.
- Bake and animation-layer management.
- Validation and reporting.
- Transaction, undo, and recovery.

The existing `asMixamoBridge.py` prototype may be used only as reference. Its destructive whole-timeline key deletion and FK-only assumptions are not carried into the new implementation.

## 14. Test Strategy and Acceptance

Automated tests cover namespace normalization, hierarchy-scoped detection, mapping completeness, matrix conversion, frame-range detection, FPS policies, transaction cleanup, and profile serialization.

Maya integration tests use copies of both supplied `.mb` rigs and never save over the originals. Required scenarios include:

- No namespace and nested namespace.
- Character away from world origin with rotated/scaled root.
- FK-only motion.
- IK-only motion.
- Multiple FK/IK switches.
- Parent/follow switches.
- Raw Mixamo FBX import.
- Existing AS face keys and existing body keys.
- Cancel, exception, one-step Undo, and explicit restore.
- Multiple characters in one scene.
- 24fps and 30fps scenes using Preserve Frame Numbers.
- Existing unrelated HumanIK characters in the scene.
- A successful FK pose pass followed by a deliberately failed IK semantic pass.

Acceptance requires:

- The original source files remain unchanged.
- Facial animation and facial rig state remain unchanged.
- Existing AS animation remains recoverable and unmodified outside the new layer.
- Every temporary connection is removed after bake or restore.
- Final AS playback no longer depends on bridge nodes.
- Validation passes calibrated profile tolerances for root, body rotations, hands, and feet.
- Unsupported mappings are reported before destructive work begins.

## 15. Research References and Licensing

Primary references used to choose the architecture:

- Autodesk Maya HumanIK overview and retargeting workflow.
- AdvancedSkeleton documentation for Create HumanIK, Bake HumanIK, Motion
  Capture Create/Connect, and FK motion-capture setup.
- `iceanimations/mocapToRig` (EPL-2.0) as evidence that namespace-aware
  Mixamo and AdvancedSkeleton HumanIK profiles are practical.
- `Arcomade/BlendCap` documentation for the FK-first, optional-IK-conversion
  workflow.
- Other open-source retargeting tools for tagged temporary-node, visual-bake,
  state-restore, and cleanup patterns.

No third-party implementation is copied into this repository. If a future
change incorporates third-party source instead of an independently written
implementation, its license and attribution must be reviewed and recorded
before merge.
