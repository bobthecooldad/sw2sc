# Survey 0.17.2 (2026-11-23)

The full feature check over the sample parts on today's SolidCraft, so the numbers on record
belong to this kernel and not 0.17.0's.

Kernel: `solidcraft-cli 0.47.0 at C:\dev\solidcraft\target\release\solidcraft-cli.exe (checkout
C:\dev\solidcraft, commit 1f8df8628 of 2026-11-23 09:46)`. Every shard reported the same line.

Measured: `tools/feature_check.py` over `samples/slippad-solidworks`, 35 parts. The folder in one
process had not finished in 55 minutes (the slow path logged at 0.17.1), so it was run as eight
copies of the folder with one process each, which finished in about twenty minutes; the reports
are merged in `logs/feature-check-0.17.2.md`. Each part is rebuilt from its own feature tree and
compared with its imported solid: volume, surface area and bounding box within 0.1 %.

| Result | Parts |
|---|---|
| rebuilt, matches the solid | 10 |
| rebuilt, does not match | 19 |
| not fully decoded | 4 |
| feature stream not numbered (pre-2015) | 2 |

**Rebuilt and matching (10):** PCB_v1, Top_beltSupportRim_v1, Top_modular_aperture_v2,
arm_idler_v2, bearing_3x6x2, drive_belt_71mm_v1, idler_single_v2, loadcell_spacer_v1,
shaft_3x22mm, shaft_3x55mm.

**Rebuilt, does not match (19):** Base_loadCell_v1, FrameBracket_v2,
FrameBracket_v2_loadCell_v1, MicroGearMotor_v1, PET_tape_top_v1, PET_tape_v1, Top_mainplate_v1,
arm_idler_single_v4, finger_aperture_15mm_v4, idler_differential_arm_short_v1,
idler_differential_arm_v1, idler_differential_baseJoint_v1, idler_single_v1, loadCell_v1,
loadcell_centerPlatform_v1, motorClip_v1, spring_base_tab_v1, spring_base_v1, spring_holder_v1.
This is the queue: every one of them now decodes, and what stands between it and its solid is
geometry (the idler arms' R1 outline fillet, which the kernel will not round over the hole's
face, is one of them).

**Not fully decoded (4):** GT2_Bobbin_Idler_v2 and GT2_Spur_v2_18tooth (an imported body among
the features), GT2_Bobbin_v2 (`moEndSpec_c`), arm_idler_single_v3_mirrored (`moMirrorStock_c`).

**Pre-2015 (2):** Spring_0_5len_0_24dia_1986K630, setScrew_M2x2_5_92015A207 — the numbering
isn't read for these files yet.

**Since the 0.17.0 report** (per part, by name): 15 of the 35 differ, and none went backwards.
11 that stopped on a feature not read yet now decode and stop at a rebuild that doesn't match
(Base_loadCell_v1, FrameBracket_v2, FrameBracket_v2_loadCell_v1, MicroGearMotor_v1,
PET_tape_top_v1, PET_tape_v1, Top_mainplate_v1, arm_idler_single_v4, motorClip_v1,
spring_base_tab_v1, spring_holder_v1). 4 now rebuild and match where they didn't:
Top_modular_aperture_v2, arm_idler_v2, bearing_3x6x2, idler_single_v2.

**Unit tests:** 67 run, OK (25 skipped where the sample models aren't reachable from the
worktree).

Two things found while measuring, both fixed in this release:
- The installed SolidCraft app updated itself to 0.47.0, so `find_cli` hit a version tie and
  took the installed copy while the report's header named the checkout build. A build from a
  checkout now outranks an installed copy at the same version, an installed copy is reported as
  stale (it may be any build behind the checkout), and `feature_check` passes the CLI it reports
  into the rebuild instead of letting it choose again.
- `feature_check` printed nothing until it finished. It now prints each part as it goes, which
  is how the sharded run above could be followed.
