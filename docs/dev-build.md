## What's new on dev since 0.17.3

- **More of the feature tree converts:** Draft, Move Face, Rib, Revolve, Body Move/Copy (translation) and Split (as Split Body).
- **SolidWorks 2012 files:** their feature trees now read (all five NIST CTC 2012 saves), including the 2012 parameter layout for Hole Wizard holes, fillets and chamfers.
- **Parallel checks:** `feature_check.py` and `rebuild_triage.py` now use `--jobs` (default 20), with regression tests for ordered, process-safe reports. Triage's default per-part budget is 300 seconds.
- **Kernel check:** the full NIST set was rerun on SolidCraft CLI 0.50.0. The wider fillet/chamfer reader subsequently moved two more parts from reader-blocked to rebuild attempts: 12 mismatches and 7 reader blockers, still 0 exact matches.
- **Sketches:** more sketch planes found (in our 4,000-part test set, 55 of 93 parts that had a sketch with no plane now have every plane, up from 8); curves and arc centres read from the sketch's curve records; sketches in pre-2010 files read.
- **Holes and chamfers:** Hole Wizard placement sketches recovered; hole placement planes taken from the hole itself; chamfers on hole rims.
- **Patterns:** linear patterns with a consecutive `FIX_n` spacing/count pair now read in Python and Rust, fully decoding two more public parts.
- **Mid-plane extrudes:** `moEndSpec_c` type 6 now becomes a symmetric total-distance extrude directly from the file, rather than a three-way direction search.
- **Straight curve patterns:** uniformly spaced patterns with a unique referenced one-line path now convert as linear patterns in Python and Rust. Two more parts are fully decoded, but both currently time out without a build, so they add no exact matches.
- **Fillet reliability:** only the file-selected edges are blended, without implicit tangent propagation. PartT8 matches again in Python and Rust, restoring the regression baseline to 21 of 22 with zero losses.
- **Large imported parts (issue #1):** STEP output about 14% smaller.
- **Credit:** parts of the rib, hole and sketch readers are ported from [cadkit-kernel](https://github.com/civilkit/cadkit-kernel) (MIT OR Apache-2.0, clean-room); see `THIRD_PARTY_NOTICES.md`.

Full detail: `CHANGELOG.md` **0.18.0** and `logs/working-log.md` on the dev branch.

## NIST test set: where each part is up to

A part counts as **converted** only when its editable feature tree rebuilds in SolidCraft and
matches the part's own solid (volume, area and bounding box within 0.1%). An imported-solid
fallback is not counted as conversion success.

Latest full eight-job run: **0 of 19 converted; 12 of 19 fully decoded and attempted a rebuild;
7 of 19 still blocked by unread features or sketches.** Before this batch those figures were 0,
4 and 15 respectively.

| Part | Saved in | Tree | Current blocker |
|---|---|---|---|
| CTC 01 | SW 2012 | rebuilds, no match | no build to compare |
| CTC 02 | SW 2012 | partly read | a 3D sketch |
| CTC 03 | SW 2012 | rebuilds, no match | no build to compare |
| CTC 04 | SW 2012 | rebuilds, no match | no build to compare |
| CTC 05 | SW 2012 | rebuilds, no match | no build to compare |
| CTC 01 | SW 2018 | rebuilds, no match | 0.6% too much material in the latest run (a loop is an island, or a cut did not take) |
| CTC 02 | SW 2018 | partly read | a 3D sketch |
| CTC 03 | SW 2018 | rebuilds, no match | no build to compare |
| CTC 04 | SW 2018 | rebuilds, no match | no build to compare |
| CTC 05 | SW 2018 | rebuilds, no match | no build to compare |
| FTC 06 | SW 2015 | rebuilds, no match | no build to compare |
| FTC 06 | SW 2018 | rebuilds, no match | no build to compare |
| FTC 07 | SW 2018 | partly read | variable-radius fillets; sketch text |
| FTC 08 | SW 2015 | rebuilds, no match | no build to compare |
| FTC 08 | SW 2018 | rebuilds, no match | no build to compare |
| FTC 09 | SW 2015 | partly read | sketch text only |
| FTC 09 | SW 2018 | partly read | sketch text only |
| FTC 10 | SW 2018 | partly read | a 3D sketch only |
| FTC 11 | SW 2018 | partly read | sketch text only |

Sketch text can't match exactly, because SolidWorks keeps the words but not the letter shapes.

## Full GrabCAD structural batch

All 356 parts in the example folder were checked with 12 workers and a 2 GiB per-process watchdog.
**29 exact feature-tree rebuilds (8.1%)**, 30 built without a match, 113 no-builds, 58 TBD,
117 without feature history, 8 unnumbered streams, no crashes and 1 error (a saved partition with no
`BODY` node). No process hit the memory limit. This is up from 26 exact matches (7.3%): three former
crash cases now rebuild exactly, no previous match was lost, and all 12 crashes are cleared.

The first combined pass used an outer 300-second process timeout, equal to the internal search budget,
so 98 parts could not return a final report. Retrying only those with a 600-second outer limit produced
82 no-builds and 16 built mismatches; the merged 356-part counts above are complete. The completed
JSONL is the next regression baseline.

## Additional private structural sample

A separate rotating 40-part batch from a private model folder was run locally on SolidCraft 0.50.0.
Only aggregate results are published: **6 exact feature-tree rebuilds (15%)**, 5 built without a
match, 10 no-builds, 6 TBD, 12 without feature history and 1 missing-geometry error. No match was
lost; there were no crashes or memory-limit events. The per-part report, filenames, paths and
geometry remain private. The remaining private models continue scanning locally without blocking
this measured release sample.
