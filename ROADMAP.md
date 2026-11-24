# Roadmap

sw2sc reads SolidWorks files without SolidWorks and brings them into SolidCraft: first the
part's solid, then its **feature tree**, rebuilt in SolidCraft and kept only where the rebuild
matches the solid SolidWorks saved. This page says where that stands and where help is most
useful. The detail behind each item is in `ISSUES.md` (IDs such as F-035) and `logs/working-log.md`.

Before starting, read [CONTRIBUTING.md](CONTRIBUTING.md): the clean-room rule, keeping your own
files private, and keeping the Python and Rust readers the same.

## Where it stands (November 2026)

Measured on a private set of 200 parts from years of real work (not in this repository), with the
SolidCraft plugin's converter:

| Outcome | Parts |
|---|---|
| Rebuilt from the feature tree, matching the saved solid | 20 |
| Tree read, but the rebuild finds no build within its 4 minutes | 41 → fewer (see below) |
| Tree read and built, but not matching the solid | 35 |
| Some features not converted yet (TBD) | 31 |
| No feature history (imported or derived bodies): solid only | 63 |
| Feature stream not readable yet (older files): solid only | 5 |
| Not a SolidWorks part, or no geometry | 5 |

Every part opens with at least its solid. The fixes since that run (a build that can no longer
reach the part's size is dropped; extrudes are tried from a face of the body so far) rebuilt four
more parts of that set that had found no build.

## Where help is most useful

Ordered by how many parts each item would bring across. "Good first" items need no knowledge of
the file format beyond what the code already shows.

### 1. The rebuild search: finding the right build in time

Most parts that find no build get far into their tree and then run out of time at a cut (often
"through all") or a fillet. The search tries every way each feature could have been built and
checks each partial build against the saved solid's volume and box (`sw2sc/verify.py`,
`plugin/sw2sc-core/src/search.rs`).

- **Read extrude end conditions** (F-035): through all, up to next, up to a face, mid plane, and
  the offsets. They are in `moEndSpec_c` records whose layout varies by version. Reading them
  would remove most of the branching. *Hard, high value.*
- **Better pruning**: every rule that drops an impossible partial build early saves whole subtrees.
  Recent ones: the volume bounds, the part's box, "nothing left can add material". Ideas: faces
  the part has that no later feature can make; a cut must remove something inside the part's box.
- **Time slicing**: give each plane choice a share of the budget instead of letting the first
  one use it all.
- **Good first:** a part that times out, traced with the debug tools in `tools/` (`rebuild_triage.py`,
  `feature_debug.py`): which feature it stops at and why, written up as an issue.

### 2. Sketches read wrong or not at all

- **Extrudes of a sketch with no curves of its own**: SolidWorks lets an extrude use edges of the model the sketch selects (converted entities), so its sketch record holds none. SolidCraft can extrude a body's face directly (`face: [x,y,z]`): the search should try each flat face of the body so far. Likely most of the next item. *Medium, high value.*
- **Sketches whose curves aren't read at all**: the commonest blocker in a census of about 4,000 real parts (170). Their sketch records are tiny (under 1 KB, no points), Russian-language files among them: the geometry must be stored somewhere else. *Hard, high value.*
- Sketches whose plane isn't found (93 parts in that census), lines with one end, arcs with no centre (38: each a different point missing) (F-036, F-047, B-020).
- Circles whose centre reads at a stray point (a circle through the origin instead of on it): the
  relations say where the centre is (`_centres_from_relations` in `sw2sc/features.py`); extending
  that to a centre that was read but disagrees with a coincident relation.
- Older files (before 2015) number their records differently (F-039, B-019).
- Sketch text: SolidWorks keeps the words, not the letters' outlines, so it can't match exactly.

### 3. Features not converted yet

| Feature | Notes |
|---|---|
| Helical sweep (a thread cut along a helix) | SolidCraft's `solid.coil` takes a profile sketch, axis, pitch and turns; the helix record (`moHelix_c`) is still to be read |
| Draft (F-046) | SolidCraft has `solid.draft`; the faces and neutral plane are still to be read |
| Full round fillet (F-045) | No full round in SolidCraft; two half-width rounds where the kernel allows |
| Hole sizes | Holes with no named sizes (`M2 Clearance Hole1`): the sizes aren't in KeyWords either, so they must be in the hole record's layout |
| Fillet and chamfer edges (F-032) | Older files' edge selections aren't found yet; in some parts a fillet's edges name curves of a cut's sketch that the sketch as read doesn't number (a 12-line cut numbered 1-4 and 8-15, the edges naming 5 and 6): which numbering is off is open |
| Split, sheet metal, surfaces, cavity | Listed as TBD in the tree |

### 4. Assemblies in the plugin

The command-line converter reads assemblies (components, placements, properties); the plugin
opens parts only. Next: assemblies in the plugin, then mates as joints (F-005), configurations
(F-007), and standing models up (SolidWorks is Y-up, SolidCraft Z-up: F-012).

### 5. Geometry SolidCraft can't read yet

Some solids come in as surfaces because SolidCraft's STEP reader refuses a face: thread-like faces
winding many turns round a cylinder (B-007), self-intersecting tori (B-010), some trimmed cones
(B-012). These are SolidCraft's to fix; a small STEP file that shows each one helps there.

## Fixes that need checking on more files

These were made against a limited set of parts. If you have SolidWorks files of your own, running
the converter on them and reporting what happens (without sharing the files; see CONTRIBUTING.md)
is the most useful check there is.

| Fix | What to look for |
|---|---|
| Lengths from KeyWords taken exact from the feature's record (inch parts were read as mm) | Inch parts with thin extrudes, shells, domes, patterns, threads: right size? |
| An extrude with no depth in its records built to its KeyWords depth | Blind extrudes no longer tried as through all |
| A sketch's plane reference written after the sketch tried as its plane | Sketches on the wrong plane in parts from other SolidWorks versions |
| Plane choices that already failed are skipped | Rebuilds that used to time out on parts with many sketches |
| A build smaller than the part, with nothing left that adds material, is dropped | A boss read as a cut; parts that stopped finding a build they found before |
| Extrudes tried starting from a face of the body so far | Sketches on faces whose plane isn't stored |
| Scale, imports with features after them, shared sketches | Parts using these |
| Feature names in Portuguese, Spanish, German and Italian | Parts saved by a localized SolidWorks |

## How results are measured

- `python -m unittest discover -s tests` (tests needing sample files skip without them).
- `plugin/tools/compare_features.py` and `compare_designs.py`: the Rust port reads and writes
  exactly as the Python does, on every part you point them at.
- A regression set of parts that rebuild: every change keeps them rebuilding.
- `tools/feature_check.py`: the full feature check over a folder, written to `logs/`.
