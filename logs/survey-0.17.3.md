# Survey 0.17.3 (2026-11-23)

The full feature check again, on the same kernel, to see that reading a sketch's chain record
changed none of it — and to put this release's numbers on record with the mismatch signatures
the report now carries.

Kernel: `solidcraft-cli 0.47.0 at C:\dev\solidcraft\target\release\solidcraft-cli.exe (checkout
C:\dev\solidcraft, commit 1f8df8628 of 2026-11-23 09:46)`. Every shard reported the same line.

Measured: `tools/feature_check.py` over `samples/slippad-solidworks`, 35 parts, as eight copies
of the folder with one process each (the arrangement 0.17.2 settled on), about fifteen minutes.
The reports are merged in `logs/feature-check-0.17.3.md`. Each part is rebuilt from its own
feature tree and compared with its imported solid: volume, surface area and bounding box within
0.1 %.

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

**Not fully decoded (4):** GT2_Bobbin_Idler_v2 and GT2_Spur_v2_18tooth (an imported body among
the features), GT2_Bobbin_v2 (`moEndSpec_c`), arm_idler_single_v3_mirrored (`moMirrorStock_c`).

**Pre-2015 (2):** Spring_0_5len_0_24dia_1986K630, setScrew_M2x2_5_92015A207.

**Since the 0.17.2 report:** every part has the same result, part for part. That is what this
release should do — the chain record is kept as data and nothing in the rebuild path reads it —
so the 35 rows matching the 0.17.2 report is the check, not a coincidence.

**The signatures are the new part of the report.** Eight of the nineteen mismatches now say what
shape their cause has:

| Part | Signature |
|---|---|
| PET_tape_top_v1 | too much material (+22955.7 %): a loop is an island, or a cut didn't take |
| PET_tape_v1 | too much material (+31748.8 %): a loop is an island, or a cut didn't take |
| idler_single_v1 | too much material (+12.2 %): a loop is an island, or a cut didn't take |
| idler_differential_baseJoint_v1 | too little material (-59.3 %): a feature is missing, or its direction is wrong |
| spring_base_tab_v1 | too little material (-7.1 %): a feature is missing, or its direction is wrong |
| finger_aperture_15mm_v4 | too little material (-0.7 %): a feature is missing, or its direction is wrong |

The other eleven say `no build to compare`: `rebuild` spent its budget, or stopped before a
candidate was evaluated, so there are no numbers to sign. That is the next thing to fix in the
report rather than in the reading.

**Unit tests:** 67 run, OK — no skips this time, because the sample folders are reachable from
the worktree (they are junctions to the project's own `samples/` and `Solidworks Example
Grabcad/`).

**F-047 is no further forward, and its lead is spent.** A sketch's chain record names points, not
curves, and the points Bucket's and PartT_7's chains name but the reader lacks (3 and 18) have no
record of their own anywhere in the sketch — searched for `<id> <id> FF FF 1F 00`, and for the
coordinates' `F0 3F 1E 00`, and found neither. Rocker Arm's missing arc ends 9 and 11 are absent
in every shape too. A one-point curve's other end is not in the file to be read; the solid, or
the neighbouring curves' tangency, has to say which way the arc sweeps.
