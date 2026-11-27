# Roadmap

sw2sc reads SolidWorks files without SolidWorks and rebuilds their **editable feature structure**
in SolidCraft. The project's success measure is a feature-tree rebuild that matches the solid
SolidWorks saved. An imported STEP solid is only a diagnostic fallback and does **not** count as
project success. This is the execution order for the remaining work. Issue IDs and detailed
diagnoses are in `ISSUES.md`; attempted fixes and evidence are in `logs/working-log.md`.

Before starting, read `CONTRIBUTING.md`: the clean-room rule, privacy, and keeping the Python and
Rust implementations the same.

## Current measurements

Full 19-part NIST run on the current dev integration. **Only an exact feature-tree match is
project success; an imported-solid fallback does not count.**

| Measure | Before this batch | Current | Change |
|---|---:|---:|---:|
| **Exact feature-tree matches** | **0 / 19 (0%)** | **0 / 19 (0%)** | **No success yet** |
| Fully decoded and attempted a rebuild | 4 / 19 (21.1%) | 12 / 19 (63.2%) | **+8 parts** |
| Rebuilt, but did not match | 4 / 19 | 12 / 19 | +8 |
| Still blocked by unread features/sketches | 15 / 19 | 7 / 19 | **-8 blockers** |
| Public 35-part feature check (separate baseline) | 10 / 35 match | Not rerun | Must not regress |
| Rebuild regression set | 21 / 22 match | 20 / 22 on 0.50.0 at 300 seconds | One recovered; PartT8 remains 0.1265% off (B-023) |
| Python/Rust parity on public samples | 0 new differences | 0 differences on 54 files, 43 designs | No new difference; both pattern parts also match separately |
| Full 356-part GrabCAD structural batch | No baseline | 26 / 356 exact rebuilds (7.3%) | First full baseline; zero memory-limit terminations |

The current dev batch contains the SolidWorks 2012 parameter reader, missing standard sketch
planes, revolve rebuild ordering, body/face colours, and eight-job feature checks/triage. The full
NIST run took about eight minutes with eight jobs.

### NIST blocker movement

| Area | Before | Now |
|---|---|---|
| SolidWorks 2012 CTC 01/03/04/05 | Hole sizes, and some fillet/chamfer sizes, not read | All four reach a rebuild; none matches yet |
| SolidWorks 2012 CTC 02 | Hole sizes unread | Hole sizes and Fillet3 read; only a 3D sketch still blocks decoding |
| FTC 08, both saves | Sketch9 plane not found | Both reach a rebuild; neither matches yet |
| FTC 06, both saves | Fillet2 unread | Both reach a rebuild; neither matches yet |
| FTC 07 | Variable-radius fillets and sketch text | Unchanged |
| FTC 09 and FTC 11 | Sketch text | Unchanged known limitation |
| FTC 10 | One 3D sketch | Unchanged: still a reader blocker |

## Rules that decide the order

1. **Read the file before searching harder.** A missing feature, size, plane or axis is a reader
   problem. Search changes are for genuinely ambiguous construction choices.
2. **Fix shared blockers before one-off symptoms.** Use `tools/feature_blockers.py` over the
   sample sets after each batch to re-rank the queue.
3. **Keep imported geometry and feature rebuilds as separate benchmarks.** Improving one must not
   hide a regression in the other.
4. **Do not patch around a SolidCraft kernel rejection with invented geometry.** Make a small
   public STEP reproduction and address it upstream where the evidence points to the kernel.
5. **Small verified batches.** A few related fixes go to public `dev` after all gates pass. Do not
   push every worker commit, and never force-push or publish local branches containing private
   history.

## Current batch: finish and publish the baseline improvement

- [x] Recover the SolidWorks 2012 parameter layout (holes, fillets and chamfers).
- [x] Read standard planes when no plane object is numbered (NIST FTC 08).
- [x] Add eight-job `feature_check.py` and `rebuild_triage.py`, with ordered-report regression tests.
- [x] Finish verifying revolve/revolved-cut rebuild ordering (F-033).
- [x] Finish verifying Parasolid body/face colours (F-014).
- [x] Complete the wider-spaced NIST fillet/chamfer reference reading (F-032).
- [x] Read linear patterns with a consecutive `FIX_n` spacing/count pair (ten features, two parts).
- [x] Read mid-plane extrude end conditions (F-035); other end-condition layouts remain open.
- [x] Run the full NIST set and update `logs/feature-check-nist.md` and `docs/dev-build.md`.
- [x] Measure a rotating private external batch: 6 exact rebuilds, 8 built without a match,
  10 no-builds, 3 TBD, 11 without feature history, 1 unnumbered stream and 1 error out of 40.
- [ ] Pass the unattended queue, then apply only sanitized diffs to public `dev`.

Revolve, colour and the wider fillet groups pass their Python/Rust tests. Full parity after the
lazy-product and previous-feature fixes is zero feature/design differences on 54 public-sample
parts (43 designs). On SolidCraft 0.50.0 the 300-second regression is 20 of 22; PartT8 remains the
separate area-only B-023 failure and is not being reopened in this batch.

## Ordered work queue

### 1. Shared feature readers: unlock whole groups first

These tasks change `sw2sc/features.py`, the corresponding modules under
`plugin/sw2sc-core/src/features/`, and existing feature tests.

1. **Fillet and chamfer selections (F-032, F-044, F-045).** The wider-spaced groups are fixed:
   CTC 02 Fillet3 and FTC 06 Fillet2 now read in both saves. Continue with older files' selections,
   merged faces and full-round fillets. Do not confuse unread edge selections with a fillet surface
   the kernel cannot build.
2. **3D sketches (`mo3DProfileFeature_c`, F-006/F-036).** Six parts in the scan; also the sole
   feature blocker on NIST FTC 10 and part of CTC 02. Read points, curves and references from the
   records before adding them to rebuilds.
3. **Remaining extrude end conditions (F-035).** Type 6 (mid-plane) now reads as a symmetric
   total-distance extrude. Continue with through all, up to next/face and offset references by
   version. This removes search branches and addresses no-build cuts such as the NIST CTC 04
   suspects. Hard, high value.
4. **Older record numbering (F-039, B-019, B-020).** Needed for older construction centrelines,
   arc centres and drifted class tags. Keep this separate from the revolve rebuild-order fix.
5. **Remaining sketch planes and curves (F-036, F-047).** External/derived references, sketch
   blocks, missing arc endpoints and centre selection. Re-run the blocker scan after each fix;
   the counts change as earlier readers improve.

Sketch text is a separate known limitation: SolidWorks stores words, size and placement but not
the letter outlines. Do not count an exact geometric match as achievable until that limitation is
resolved or explicitly excluded from the benchmark.

### 2. Rebuild search and deterministic diagnosis

These tasks primarily involve `sw2sc/verify.py`, `plugin/sw2sc-core/src/search.rs`, fillet
selection code and `tools/rebuild_triage.py`.

1. **NIST CTC 01 (2018): 1.8% extra material.** Use loop nesting and cut evaluation to identify
   the island or cut that does not take. This is the closest current feature-tree mismatch.
2. **NIST FTC 08: fully decoded but times out.** Profile the search, prune impossible prefixes and
   give plane choices bounded time slices. Do not increase the global timeout and call it a fix.
3. **NIST CTC 04: all 105 builds evaluate but none matches.** Recheck after end-condition reading;
   then compare holes and cuts feature by feature against the saved solid.
4. **General no-build cases.** Improve face-by-face checks using `FACE_ID_2001`, mismatch
   signatures and pruning. Preserve the 21-of-22 regression baseline throughout.

Run independent reader and search tasks in parallel only when they touch different feature
regions. Both implementations change together in every task.

### 3. Feature operations and kernel-bound cases

1. **Draft (F-046) and Move Face.** NIST CTC 03 stops at `offset_face`; CTC 05 stops at Draft2.
   Determine whether the input selection is wrong or SolidCraft rejects a valid operation.
   Body Move/Copy rotations now convert as rigid matrices; independent copies and curved-face draft
   remain open.
2. **Variable-radius fillets and remaining fillet surfaces.** NIST FTC 07 is the feature-tree
   case. The equal-pipe mitre fillets in CTC 02/FTC 07 are also imported-geometry kernel cases:
   the exact surface folds near the ellipse end and needs a bounded-surface or trimming solution,
   not another radius guess.
3. **Other unsupported features.** Complete mirrors/patterns, sweeps and helical threads,
   combine/cavity, surfaces, and sheet metal in blocker-count order. Keep unsupported features as
   named TBD nodes until read correctly.
4. **STEP/kernel failures (B-007, B-009, B-010, B-012, B-013).** Thread-like windings,
   self-intersecting tori, trimmed cones and unsupported blends need small public reproductions
   and upstream evidence. Maintain the 14-of-19 NIST imported-volume result while working on them.

### 4. Assemblies, configurations and product completion

Core part conversion comes first; then:

1. Assemblies in the Rust plugin, then mates as joints (F-005).
2. Configurations and geometry beyond the first configuration (F-007, F-013).
3. Consistent SolidWorks Y-up to SolidCraft Z-up conversion (F-012).
4. Virtual components and linked-subassembly component visibility (F-010, F-022, B-016).
5. Component appearances (F-009), distinct from Parasolid body/face colours (F-014).
6. Vault/release workflow improvements, Windows packaging and upstream SolidCraft contributions
   (F-017, F-018, F-024 and related issues). Follow upstream PDM decisions rather than building a
   competing server model.

## Parallel work lanes

- **Lane A — readers:** one worker per feature class or record layout.
- **Lane B — rebuild/search:** loop nesting, end-condition use, pruning and timeout diagnosis.
- **Lane C — STEP/kernel:** geometry failures and minimal upstream reproductions.
- **Lane D — automation:** regression tooling, NIST reports, blocker counts, memory-capped
  full-folder conversion batches and rotating private external samples. Only aggregate outcomes
  from private batches may enter public logs.

A local model may summarize sanitized reports or review a bounded diff. It is not file-format
evidence and never decides parity or acceptance. Deterministic tools and the main reviewer make
those decisions.

## Gate for every task

1. Add a failing regression test first; watch it fail for the intended reason.
2. Implement the reading/design/rebuild change in both Python and Rust.
3. Pass `python -m unittest discover -s tests` and `cargo test --release -p sw2sc-core`.
4. Build release examples and run `compare_features.py` and `compare_designs.py`: zero new
   differences beyond the documented pre-existing STEP baseline.
5. Run `tools/rebuild_set.py` with a before baseline: zero previously matching parts lost.
6. Run the affected NIST parts, then all 19 before a dev push; report exact counts and rates.
   Also run the rotating private external batch when available, but publish only aggregate counts.
7. Update `logs/working-log.md`, `CHANGELOG.md`, `ISSUES.md`, this roadmap and
   `docs/dev-build.md` as applicable, including failed attempts.
8. Run `python tools/publish.py check`. Private filenames, paths and geometry stay out of every
   committed file. Apply only sanitized change diffs to the public branch.

## Dev release gate

Push only when several related fixes are complete, the unattended queue passes with no new
regressions, and the NIST/dev-build tables describe the measured result. Lead with the exact
feature-tree success rate; also report fully decoded parts and remaining reader blockers.
Imported-solid figures are diagnostics only, never the project's success rate. No percentage may
be estimated from a partial run.
