# Survey 0.18.0 (2026-11-27)

## Scope

This release improves editable SolidWorks feature-tree reading and rebuild stability in Python and
Rust. It includes wider sketch/plane/curve coverage, SolidWorks 2012 parameters, holes, fillets and
chamfers, revolves, ribs, draft/move-face operations, body moves, patterns, mid-plane extrudes,
body/face colours, and the supporting regression tools. `CHANGELOG.md` contains the complete list.

An imported STEP solid is a fallback, not a successful structural conversion. Success below means
an editable feature-tree rebuild matching the saved solid's volume, area and bounding box within 0.1%.

## Memory and crash corrections

- Rust's eager Cartesian-product allocation is replaced by lazy iteration. One public NIST part has
  293,932,800,000 sketch-plane combinations and previously drove a conversion to 43 GB.
- The working-set watchdog terminates a conversion and its process tree on excess memory, drains
  output without deadlocking, and passes a real allocation test.
- A through-all boss after an imported body no longer indexes a nonexistent previous feature. All
  12 public-batch crashes are cleared; three of those parts now rebuild exactly.
- Full 356-part public reruns have no memory-limit terminations. No previous exact match was lost.

## Measured checks

| Check | Result |
|---|---|
| Regression set | **21 / 22 rebuild, 0 gained, 0 lost** |
| Python tests | **120 passed, 5 skipped** |
| Rust tests | **19 passed** |
| Python/Rust public parity | **54 files, 43 designs, 0 differences** |
| Full public structural batch | **29 / 356 exact (8.1%)**, up from 26 / 356 (7.3%) |
| NIST structural benchmark | **0 / 19 exact**, 12 rebuild attempts, 7 reader-blocked |
| Private release sample | **6 / 40 exact (15%)**, no losses, crashes or memory-limit events |
| Kernel used for rebuild checks | SolidCraft CLI 0.50.0 |
| Privacy check | `nothing personal found` |

The final public batch also has 30 built mismatches, 113 no-builds, 58 TBD, 117 parts without feature
history, 8 unnumbered streams and 1 empty-body error. The two straight curve-pattern parts moved
from TBD to no-build without adding exact matches.

The private batch is represented only by aggregate counts. Its names, paths, geometry and per-file
results stay outside the repository. The remaining long private scan is diagnostic and is not a
release gate.

## Known limitations

NIST has no exact structural match yet. General 3D sketches, remaining extrude end conditions,
variable-radius fillets, sketch text, older record numbering and several surface/kernel cases remain
open. `ROADMAP.md` is the allocation queue for that work; `ISSUES.md` and `logs/working-log.md` hold
the evidence and unsuccessful experiments.
