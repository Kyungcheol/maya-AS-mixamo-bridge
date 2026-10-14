# Maya AS–Mixamo Bridge

A Maya tool for transferring body animation between a studio Mixamo-style
hybrid control rig and AdvancedSkeleton while preserving IK/FK transitions,
space switches, frame numbers, existing animation, and recovery data.

The project is currently in the design and implementation-planning stage. Its
retargeting backbone uses Maya HumanIK, followed by a dense AS FK pose pass and
an explicit IK/FK and space-switch semantic pass. The implementation prioritizes
validated animation fidelity and recoverability over bake speed.

See the [design specification](docs/superpowers/specs/2026-10-14-as-mixamo-bridge-design.md).
See the [implementation plan](docs/superpowers/plans/2026-10-14-humanik-as-mixamo-bridge.md).

## Safety

Production Maya, FBX, Alembic, analysis, and recovery files are intentionally
excluded from Git. Supplied character rigs are used only as local test inputs.
