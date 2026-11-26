## What's new on dev since 0.17.3

- **More of the feature tree converts:** Draft, Move Face, Rib, Revolve, Body Move/Copy (translation) and Split (as Split Body).
- **SolidWorks 2012 files:** their feature trees now read (all five NIST CTC 2012 saves), including the 2012 parameter layout for Hole Wizard holes, fillets and chamfers.
- **Parallel checks:** `feature_check.py` and `rebuild_triage.py` now use `--jobs` (default 8), with regression tests for ordered, process-safe reports.
- **Sketches:** more sketch planes found (in our 4,000-part test set, 55 of 93 parts that had a sketch with no plane now have every plane, up from 8); curves and arc centres read from the sketch's curve records; sketches in pre-2010 files read.
- **Holes and chamfers:** Hole Wizard placement sketches recovered; hole placement planes taken from the hole itself; chamfers on hole rims.
- **Large imported parts (issue #1):** STEP output about 14% smaller.
- **Credit:** parts of the rib, hole and sketch readers are ported from [cadkit-kernel](https://github.com/civilkit/cadkit-kernel) (MIT OR Apache-2.0, clean-room); see `THIRD_PARTY_NOTICES.md`.

Full detail: `CHANGELOG.md` [Unreleased] and `logs/working-log.md` on the dev branch.

## NIST test set: where each part is up to

A part counts as **converted** when its feature tree rebuilds in SolidCraft and matches the part's own solid (volume, area and bounding box within 0.1%). Every part already opens as an imported solid.

| Part | Saved in | Tree | What still stops it |
|---|---|---|---|
| CTC 01 | SW 2012 | partly read | Hole Wizard hole sizes (2012 layout); Fillet1 |
| CTC 02 | SW 2012 | partly read | Hole Wizard hole sizes (2012 layout) |
| CTC 03 | SW 2012 | partly read | Hole Wizard hole sizes (2012 layout) |
| CTC 04 | SW 2012 | partly read | Hole Wizard hole sizes (2012 layout) |
| CTC 05 | SW 2012 | partly read | Hole Wizard hole sizes (2012 layout); Chamfer1 |
| CTC 01 | SW 2018 | **rebuilds** | 1.8% too much material (a cut that doesn't take) |
| CTC 02 | SW 2018 | partly read | Fillet3; a 3D sketch |
| CTC 03 | SW 2018 | fully read | SolidCraft doesn't build it (Offset Face; "flip side to cut") |
| CTC 04 | SW 2018 | fully read | SolidCraft doesn't build it |
| CTC 05 | SW 2018 | fully read | SolidCraft doesn't build it |
| FTC 06 | SW 2015 | partly read | Fillet2 only |
| FTC 06 | SW 2018 | partly read | Fillet2 only |
| FTC 07 | SW 2018 | partly read | variable-radius fillets; sketch text |
| FTC 08 | SW 2015 | partly read | one sketch with no plane found |
| FTC 08 | SW 2018 | partly read | one sketch with no plane found |
| FTC 09 | SW 2015 | partly read | sketch text only |
| FTC 09 | SW 2018 | partly read | sketch text only |
| FTC 10 | SW 2018 | partly read | a 3D sketch only |
| FTC 11 | SW 2018 | partly read | sketch text only |

Converted: 0 of 19. Sketch text can't match exactly, because SolidWorks keeps the words but not the letter shapes.
