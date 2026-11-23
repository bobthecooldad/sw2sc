# Survey 0.17.1 (2026-11-23)

A fix release: a sketch's loops are nested by each arc's real curve, not its chord (B-021),
so a hole inside an outward-bulging arc is a hole again.

Measured:
- **Boom** (CAT Part R loader): rebuilds from its feature tree and matches its solid exactly,
  4413.955 mm3 / 4491.51 mm2 (sketch, extrude, 4-edge fillet, through-all cut, pin).
- **Parts that matched in 0.17.0**, rechecked: shaft_3x22mm, Top_beltSupportRim_v1 and PartT8
  all still match (rebuild_triage, "matches", 0.0 %).
- **Unit tests:** 59 run, OK (25 skipped where the sample models aren't reachable from the
  worktree).

Not finished: the full feature check (`tools/feature_check.py`) over Documents, the samples and
the GrabCAD examples was started after dark on this release and had not finished 20 minutes
later; 0.17.0's counts stand until it is run to the end: 24 rebuilt (16 distinct parts), 25
rebuilt without a match, 154 not fully decoded, 142 imported bodies, 4 streams not numbered
(`logs/survey-0.17.0.md`).

Left open on the same gap as before (see `logs/working-log.md` 113): Rocker Arm, PartT_7 and
Bucket all stop on sketches whose curves don't have all their points in the stream (arcs read
as circles, F-047).
