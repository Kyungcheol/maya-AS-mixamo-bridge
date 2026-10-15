# Isolated TeamExtra–AdvancedSkeleton Bridge Redesign

Date: 2026-10-15

Host: Autodesk Maya 2025, Python 3, AdvancedSkeleton 6

Initial production profiles: `TeamExtra01_rig_v01.mb` and `Belato01_rig_v01_w01.mb`

Status: approved conversational design, pending written-spec review

## 1. Purpose

Build a Maya tool that lets an animator select an AdvancedSkeleton (AS) character, create a real hybrid FK/IK work rig with the studio TeamExtra control conventions, animate or apply Mixamo/ActorCore motion, and bake the result back to the original AS rig.

The normal workflow must require three obvious actions:

1. **Create TeamExtra Work Rig**
2. **Bake Back to AS**
3. **Return to Original AS**

The animator stays in the same Maya scene and uses **Save As** after visually accepting the result. Exporting an intermediate FBX or opening another Maya scene is not part of the normal workflow.

Animation fidelity and recoverability take priority over speed. The tool must stop with a precise diagnostic instead of silently producing a degraded result.

## 2. Design Correction

The previous implementation is not a foundation for this redesign. It created flat proxy controls and constrained them directly to AS controls. That does not create a TeamExtra rig and cannot reproduce its hierarchy, IK handles, pole vectors, offset groups, switches, or parent spaces.

This redesign uses:

- A genuine, separately evaluated hybrid work rig.
- A canonical result skeleton as the pose boundary between rigs.
- AS's dedicated motion-capture input concepts and namespace-aware FK/IK alignment functions where they are safe to call.
- Dense, validated baking instead of persistent constraints on animator controls.

The old HumanIK/proxy-adapter branch remains only as a failure record. No product code is carried forward automatically.

## 3. Evidence From Supplied References

### 3.1 Studio Xsens-to-TeamExtra Tool

The supplied `XsensToMixamo` package confirms the production TeamExtra transfer sequence:

1. Set arm and leg `FK_IK` attributes to FK (`0`).
2. Orient-constrain body and limb FK controls from the source joints.
3. Derive root translation from the source `Reference` node relative to its initial position.
4. Bake root, torso, and FK limb controls.
5. Set arm and leg `FK_IK` attributes to IK (`1`).
6. Enable `FollowHand` and `FollowFoot` on pole controls.
7. Orient- and point-constrain hand and foot IK controls from source end-point helpers.
8. Bake IK controls, delete temporary constraints, and transfer toe rotation into `ToeTap`.

The original tool does not explicitly bake elbow or knee pole-vector translation. It relies on TeamExtra's follow system and established pole placement. The bridge must preserve that behavior as one supported policy, while also providing a geometric pole solve for motion that requires independent pole animation.

### 3.2 AdvancedSkeleton 6

The supplied AS package confirms these supported mechanisms:

- Mixamo, CharacterCreator, MotionBuilder, and other mocap name profiles.
- Independent AS and source namespaces in the MoCap Matcher.
- Motion capture connections to `FKExtra*` and `RootExtraX_M`, instead of destructive connections to the primary animator controls.
- Optional IK feet and geometric knee pole placement.
- `asAlignFKIK` and `asAnimBakeFKIK`, which accept an AS namespace and perform per-frame FK/IK matching.
- HumanIK baking that first duplicates a neutral joint hierarchy, then drives and bakes both AS FK and IK controls.

The bridge may call documented or version-detected AS procedures through a narrow adapter. It must not copy or redistribute AdvancedSkeleton source code. Procedures that write base animation destructively are not called directly; their behavior is used only as a reference for an independently controlled bake.

## 4. Supported Scope

### Included

- Root, pelvis, spine, chest, neck, head, clavicles, arms, legs, feet, toes, hands, and mapped fingers.
- TeamExtra-style arm and leg FK/IK controls, pole vectors, and FK/IK switches.
- `FollowBody`, `ParentToGlobal`, `FollowHand`, `FollowFoot`, and profile-declared equivalent spaces.
- Existing AS animation transferred into the work rig.
- Raw Mixamo FBX and ActorCore/CharacterCreator skeleton animation applied to the work rig.
- Studio TeamExtra result-skeleton animation applied to AS.
- Namespaced and nested-namespaced characters.
- Characters translated, rotated, or uniformly scaled away from world origin.
- Multiple characters in one scene when the user selects a node belonging to the intended character.
- Keyed FK-to-IK and IK-to-FK transitions.
- Exact source frame numbers by default.

### Excluded

- Facial control, facial joint, facial blendshape, or facial key transfer.
- Automatic transfer of arbitrary props and character-specific secondary controls without an explicit profile.
- Non-uniformly scaled character roots unless a profile-specific validation proves them safe.
- Recovering original animator intent from raw joint-only animation. Joint animation contains evaluated poses, not authored FK/IK or space-switch choices.
- Claiming lossless conversion of unmapped twist, bend, muscle, cloth, hair, or custom systems.

Facial systems are excluded from transfer but must remain unchanged. Body-driven head motion remains included.

## 5. Safety Boundary

### Work Mode

Entering Work Mode must not delete keys, unlock protected channels, disconnect unknown incoming connections, or constrain primary AS animator controls.

The work rig and its result skeleton live under a unique namespace and are tagged with a bridge session ID. Viewport preview uses one of two profile-declared paths:

1. **Preferred AS mocap input:** temporary, recorded connections drive only AS's dedicated `FKExtra*` and `RootExtraX_M` motion-capture inputs. This preserves the original geometry, facial system, primary controls, and existing animation.
2. **Isolated preview fallback:** when the dedicated AS inputs are missing or already have unsupported connections, create a session-owned preview duplicate rather than replacing existing AS graph connections.

There is no fallback that attaches the work rig directly to primary AS controls. If neither safe preview path is available, Work Mode creation stops before mutation.

### Final Bake

The first write to primary AS animation occurs only when the user clicks **Bake Back to AS**. Before that write, the bridge creates:

- A scene-persistent session manifest.
- A durable recovery snapshot path.
- A new AS override animation layer.
- A single Maya undo chunk for immediate recovery when Maya retains undo history.

Existing base keys and existing animation layers are not deleted. A failed bake remains isolated on the bridge-owned layer or is rolled back.

## 6. Architecture

### 6.1 Selection-Scoped Rig Detection

Detection begins from the selected node and walks its DAG and connected rig sets. It never performs a global wildcard search and chooses the first result.

Each versioned rig profile declares:

- Structural signature nodes and sets.
- Deformation and result skeleton mappings.
- Root, FK, IK, pole, toe, and finger control mappings.
- Switch ranges and directions.
- Supported parent/follow spaces.
- Safe mocap input nodes.
- Face roots and other excluded subtrees.
- Required keyable channels and expected connections.
- Validation tolerances.

Ambiguous matches, incomplete signatures, unsupported existing connections, or duplicate nodes inside the selected character stop the operation with a report.

### 6.2 Canonical Motion Skeleton

A session-owned canonical skeleton separates evaluated pose from rig controls. It is fitted from the selected character's body-joint world matrices and stores:

- Joint world matrices for each sampled frame.
- Character-root transform and scale context.
- Rest-pose calibration matrices.
- Source frame numbers and FPS metadata.
- Explicit FK/IK and space-switch events when the source is a control rig.

Transfers compare and solve world matrices; they never copy unrelated local Euler values directly between rigs.

### 6.3 Real TeamExtra-Compatible Work Rig

The work interface is a real hybrid control rig, not a collection of control shapes. It contains:

- A fitted animation/result skeleton.
- Hierarchical zero and offset groups.
- FK chains for arms, legs, spine, neck, head, clavicles, toes, and supported fingers.
- IK handles for arms, legs, feet, and toes where the profile requires them.
- Stable elbow and knee pole-vector controls.
- `0 = FK`, `1 = IK` limb switches.
- TeamExtra-compatible follow and parent-space attributes.
- Match functions that preserve world pose when switching.

The rig is generated independently from profile data. The supplied proprietary `.mb` rig is a structural reference and test fixture, not a redistributable runtime dependency.

### 6.4 AS-to-Work Transfer

1. Detect and validate the selected AS character.
2. Determine the body key range.
3. Capture evaluated AS deformation motion into the canonical skeleton.
4. Generate and fit the work rig.
5. Apply the proven two-pass TeamExtra bake: FK/body first, then hand/foot IK.
6. Bake and remove all temporary source-to-work constraints.
7. Activate the safe viewport preview path.
8. Hide or selection-protect AS body controls while leaving face controls available.

The work rig must reproduce the captured canonical pose before Work Mode is considered active.

### 6.5 Mixamo, ActorCore, and Studio Sources

Raw skeleton sources are imported into a unique temporary namespace and resolved by hierarchy plus a versioned profile:

- `mixamo_standard`
- `actorcore_cc_base`
- `studio_teamextra`

Their evaluated motion is captured into the same canonical skeleton before the work rig is driven. Temporary imported source nodes are deleted only after a verified work-rig bake.

Raw skeleton sources use the declared default semantic policy of arm FK and leg IK. The user may change this in advanced settings. Studio control-rig sources preserve explicit switch and parent/follow events.

### 6.6 Work-to-AS Dense Dual-System Bake

The final transfer evaluates the work result skeleton and produces matching keys for both AS FK and AS IK systems at every integer frame in the range.

The order is:

1. Capture work result motion and control-state events.
2. Apply parent/follow states before solving target control matrices.
3. Bake AS root, torso, FK limbs, toes, and fingers.
4. Solve and bake AS hand/foot IK controls and elbow/knee poles.
5. Use version-detected AS alignment functions at switch boundaries when available.
6. Map TeamExtra `0/1` switch values to AS `0/10` values.
7. Key both systems at transition boundaries before changing the switch.
8. Remove temporary constraints and evaluate AS from its own controls only.
9. Validate AS deformation against the canonical motion.

Dense keys are the correctness baseline. Sparse-key reduction is not part of the first production release.

Because both target systems are matched, the animator can alter an AS FK/IK switch after conversion without an immediate pose jump at sampled frames. This does not promise identical curve tangents or identical motion between deliberately deleted dense keys.

## 7. Pole-Vector Policy

The bridge supports two explicit policies per limb interval:

- **Follow policy:** reproduce the established TeamExtra tool by enabling `FollowHand` or `FollowFoot` and preserving the rig's matched pole offset.
- **Independent policy:** calculate a stable pole from the start-mid-end limb plane, retain the previous valid plane through near-collinear frames, and bake pole translation.

The solver must detect straight-limb singularities. It may reuse the last valid pole plane or the rest-pose plane, but it must not choose an arbitrary opposite side that causes a flip.

## 8. Timing and FPS

The default range is the earliest to latest key on mapped body controls, result joints, switch attributes, and supported parent/follow attributes. Face-only keys, setup-driven keys, and unrelated scene animation are excluded.

If the selected character has no body keys, the range is the current frame only and the UI states that this is a static-pose conversion.

Default policy: **Preserve Frame Numbers**.

- Source `1001–1120` remains target `1001–1120`.
- Scene FPS is not changed automatically.
- Switch and space events remain on the same numbered frames.

Advanced timing exposes:

- The detected range.
- Source and scene FPS.
- An explicit range override.
- **Preserve Playback Duration**, which retimes and resamples only after confirmation.
- A separately confirmed scene-FPS change.

## 9. Session State and Restore

A Maya network node stores the session ID, AS character identity, work namespace, profile versions, state, original display settings, altered attributes, created nodes, created layers, temporary connections, time settings, and recovery snapshot path.

The state must survive closing and reopening the UI and saving/reopening the Maya file.

### Return to Original AS before final bake

- Remove only session-tagged work nodes and preview connections.
- Restore AS visibility, selection state, time, auto-key, refresh, and evaluation settings.
- Verify that primary AS keys and incoming connections match the pre-session manifest.

### Return after final bake

- Remove or mute only the bridge-owned output layer.
- Restore recorded switch and display states.
- Preserve unrelated animation created after the session began.
- If exact manifest restoration cannot be verified, direct the user to the durable snapshot instead of reporting success.

## 10. UI

The main window has one detected-character status block and three primary buttons:

1. **TeamExtra 작업 리그 만들기**
2. **AS로 최종 베이크**
3. **원본 AS로 돌아가기**

Only actions valid for the current scene-persistent session state are enabled. For example, Restore is disabled when no active session exists.

The collapsed advanced section contains frame range, FPS policy, raw-skeleton semantic defaults, pole policy, output-layer name, and diagnostics. Mapping tables and developer details do not occupy the normal animator workflow.

All user-facing labels and errors are Korean-first, with exact Maya node names included in expandable diagnostics.

## 11. Failure Handling

Every public operation is transactional. On error or cancellation:

- Stop playback and close progress UI safely.
- Restore current time, auto-key, cycle check, refresh, evaluation mode, and selection.
- Delete only nodes created by the active transaction.
- Restore recorded temporary connections and display states.
- Keep the durable recovery snapshot.
- Show a concise user message and write a detailed traceback to the Script Editor.

The bridge never unlocks a channel or disconnects an incoming connection merely to force a bake. An unkeyable required target is reported before destructive work begins.

Missing renderer, hair, or unrelated plug-ins do not authorize saving the original scene from a reduced Maya environment.

## 12. Validation and Acceptance

Validation compares final evaluated deformation matrices, not control channel numbers.

It checks:

- Root position and orientation.
- Body-joint orientation.
- Hand and foot position and orientation.
- Elbow and knee bend-plane direction.
- Stationary-foot drift.
- Discontinuities at FK/IK and space-switch frames.
- Missing keys, NaN values, singular matrices, and live bridge dependencies.

Initial acceptance limits are:

- Root, hand, and foot position: `0.1 cm` maximum error.
- Root, hand, and foot orientation: `0.1 degrees` maximum error.
- Other mapped body-joint orientation: `0.25 degrees` maximum error.
- Stationary-foot drift: `0.1 cm` across the contact interval.

Any profile-specific relaxation must have a written reason in the validation report. It may not be silent.

A conversion is not called successful until:

- The supplied AS and TeamExtra scene copies pass automated matrix validation.
- Root offsets, nested namespaces, FK motion, IK motion, and multiple switches pass.
- Face nodes and keys are unchanged.
- Restoring removes all session-owned dependencies.
- The user manually opens the Maya result, scrubs it, tests FK/IK switching, and approves the visible behavior.

## 13. Delivery Phases and Gates

This architecture is implemented as three independently reviewable milestones.

### Milestone 1: Technical Proof

- Profile-scoped detection for the two supplied rigs.
- Canonical skeleton capture.
- Actual hybrid work rig with correct hierarchy, IK handles, poles, and switches.
- AS-to-work transfer for a static pose and short animation.
- Safe preview connection and complete restore.

Gate: the user visually confirms that controls do not separate, root motion is correct, feet remain stable, and Restore returns the original AS scene.

### Milestone 2: Final AS Bake

- Dense FK and IK bake.
- Switch and space-event mapping.
- Animation-layer output, durable snapshot, and matrix validation.
- Face-preservation and reopen tests.

Gate: automated tolerances pass and the user approves a baked AS test scene.

### Milestone 3: Production UX and Packaging

- Korean state-driven UI.
- Mixamo/ActorCore import profiles.
- Installer, diagnostics, documentation, and full acceptance matrix.

Gate: a clean Maya 2025 installation can install, run, restore, save, and reopen the accepted result using documented steps.

No milestone is described as finished merely because unit tests pass. Actual Maya scene approval is mandatory.

## 14. Repository and Licensing

- Implementation starts from `main` on the redesign branch, not from `feat/humanik-as-mixamo-bridge`.
- `reference/` assets, supplied `.mb` files, and proprietary rig packages are test inputs and remain untracked.
- AdvancedSkeleton and the supplied Xsens/TeamExtra code are research references. Their source is not copied into the repository.
- The generated work rig is independently implemented from documented behavior and measured scene structure.
- Any future third-party source inclusion requires explicit license review and attribution before commit.
