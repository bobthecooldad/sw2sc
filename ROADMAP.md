# Roadmap

sw2sc reads SolidWorks files without SolidWorks and rebuilds their **editable feature structure**
in SolidCraft. Success is a feature-tree rebuild whose volume, surface area and bounding box match
the saved solid within 0.1%, followed by geometric evidence (two-way differences natively, or exact
face geometry in the read-only host). Expected sketch dimensions must also survive into the delivered
model. An imported STEP solid is only a fallback and does **not** count; a geometric match with missing
dimensions is not a complete conversion. Report geometry and dimension retention separately.

This file is for choosing and allocating work. `ISSUES.md` holds diagnoses, `docs/clean-room.md`
holds format evidence, and `logs/working-log.md` holds attempted fixes and measurements. Current
benchmark tables belong in `docs/dev-build.md`, not in this allocation queue.

Read `CONTRIBUTING.md` before starting: clean-room sources, privacy, Python/Rust parity, and the
required checks.

## Allocate work without duplicating it

Add a row here before starting a task. Keep the scope narrow enough for someone else to work on a
different row without editing the same feature region.

| Issues | Exact scope | Owner / branch | Status |
|---|---|---|---|
| B-028, F-038 | Resolve the shared `sgPntPntDist` loss first: 195 single-dimension-blocker and 1,434 any-part cases in the private census; verify values and references, then continue down the dimension classes | `kimi/public-dev` | In progress |

- **TBD** means available to claim. **In progress** requires an owner/branch and a current scope.
- Do not start work in another row's active scope. Split broad issues by record layout or operation.
- Move a row out of the active table when its work is integrated. Leave the remaining work as TBD.
- Record unsuccessful experiments in the working log so nobody repeats them. An interrupted or
  crashed worker is not an active claim unless someone resumes it.

## Priority 1: shared readers that unlock whole groups

These tasks normally change `sw2sc/features.py`, the corresponding modules under
`plugin/sw2sc-core/src/features/`, and existing tests. Read the records before adding search branches.

| Issues | Work still to do | Status |
|---|---|---|
| F-032, F-044, F-045 | Remaining fillet/chamfer selections, merged faces and full-round fillets. The wider-spaced groups are already fixed. Distinguish unread selections from kernel-rejected fillet surfaces. | TBD |
| F-006, F-036 | General 3D sketches (`mo3DProfileFeature_c`): read points, curves and references from records. This blocks NIST FTC 10 and part of CTC 02. A previous worker crashed without saving code or evidence. | TBD |
| F-035 | Remaining extrude end conditions: through-all, up-to-next/face and offset references by version. Mid-plane type 6 is done. | TBD |
| F-039, B-019, B-020 | Older record numbering for construction centrelines, arc centres and drifted class tags. Keep this separate from rebuild ordering. | TBD |
| F-036, F-047 | External/derived sketch planes, sketch blocks, missing arc endpoints and centre selection. Re-rank blockers after each reader improvement. | TBD |
| F-034 | Curve patterns with genuinely curved paths or no saved spacing. Straight, uniformly spaced one-line paths are done; do not map other cases to linear patterns by guessing. | TBD |
| F-034 | Split tools stored as face/surface references. The single checked `moCompProfile_c` layout is documented; most unread splits do not use it. | TBD |
| F-034 and related classes | Other mirrors/patterns, sweeps, helical threads, combine/cavity, surfaces and sheet metal, in blocker-count order. Sheet metal is a large separate effort, not a quick reader fix. | TBD |

Sketch text is a known limitation rather than a straightforward reader task: SolidWorks stores the
words, size and placement but not the letter outlines. Do not promise an exact geometric match until
that limitation is resolved or the benchmark explicitly excludes it.

## Priority 2: rebuild search and deterministic diagnosis

These tasks primarily involve `sw2sc/verify.py`, `plugin/sw2sc-core/src/search.rs`, fillet selection
code and `tools/rebuild_triage.py`. Preserve every previously matching regression part.

| Issues | Work still to do | Status |
|---|---|---|
| F-006, B-021 | NIST CTC 01 (2018): the latest closest result has 0.6% extra material. Identify the island or cut that does not take using loop and feature-by-feature evidence. | TBD |
| F-006 | NIST FTC 08: fully decoded but times out. Profile the search and prune impossible prefixes; do not call a larger timeout a fix. | TBD |
| F-006, F-035 | NIST CTC 04: all 105 evaluated builds miss. Recheck after end-condition work, then compare holes and cuts against the saved solid. | TBD |
| F-006 | General no-build cases: use `FACE_ID_2001`, mismatch signatures and prefix pruning for reproducible diagnoses instead of longer blind searches. Three newly decoded private fillet cases time out before a complete candidate and need prefix profiling, not a larger timeout. | TBD |
| B-030 | Native-matching revolved geometry rejected by the read-only host's face comparison. Obtain exact non-analytic surface evidence or host support; do not relax the threshold. | TBD |

## Priority 3: operations and kernel-bound geometry

| Issues | Work still to do | Status |
|---|---|---|
| F-046 | Draft and Move Face selections: NIST CTC 03 stops at `offset_face`; CTC 05 stops at Draft2. Determine whether the input or the SolidCraft operation is wrong. | TBD |
| F-032 | Variable-radius fillets and remaining fillet surfaces, including NIST FTC 07. Do not substitute another radius guess for the required surface/trimming work. | TBD |
| F-034 | Independent Body Move/Copy copies and curved-face draft. Rigid translations/rotations are already written. | TBD |
| B-007, B-009, B-010, B-012, B-013 | Thread-like windings, self-intersecting tori, trimmed cones and unsupported blends: make small public reproductions and establish upstream evidence. | TBD |

Do not patch around a SolidCraft kernel rejection with invented geometry. Use the open-source target
as the checker and prepare an upstream reproduction where the evidence points to its kernel.

## Later: assemblies, configurations and product completion

Core part conversion comes first.

| Issues | Work still to do | Status |
|---|---|---|
| F-005 | Assemblies in the Rust plugin, then mates as joints. The current part-only runner does not cover `.sldasm`. | TBD |
| F-007, F-013 | Configurations and geometry beyond the first configuration. | TBD |
| F-012 | Consistent SolidWorks Y-up to SolidCraft Z-up conversion across geometry and placements. | TBD |
| F-010, F-022, B-016 | Virtual components, linked-subassembly visibility and component visibility. | TBD |
| F-009 | Component appearances, distinct from Parasolid body/face colours (F-014). | TBD |
| F-017, F-018, F-024 and related issues | Upstream contributions, vault/release workflow and Windows packaging. Follow upstream PDM decisions rather than creating a competing server model. | TBD |

## Choosing between tasks

**B-028 / F-038 dimension retention is the current priority over new TBD feature classes.** Use the
full dimension census to choose shared record/reference fixes; do not substitute geometry-only success.

1. Prefer shared, evidence-backed reader fixes over rare one-off geometry cases.
2. Use `tools/feature_blockers.py` after a batch to re-rank the queue; counts change as readers improve.
3. Keep imported-geometry and feature-tree benchmarks separate.
4. Work in small verified batches. Python and Rust change together.
5. A local model may summarize sanitized reports or review a bounded diff, but it is not format
   evidence and never decides parity or acceptance.

## Gate for every task

1. Add a failing regression test first and watch it fail for the intended reason.
2. Implement the change in both Python and Rust.
3. Pass `python -m unittest discover -s tests` and `cargo test --release -p sw2sc-core`.
4. Build release examples and run `compare_features.py` and `compare_designs.py`: zero new differences.
5. Run the rebuild regression with a before baseline: zero previously matching parts lost.
6. Run affected NIST parts, then all 19 before a dev push. Publish exact measured counts, never
   estimates from partial runs. Private checks publish only aggregate outcomes.
7. Update `logs/working-log.md`, `CHANGELOG.md`, `ISSUES.md` and `docs/dev-build.md` as applicable.
   Update this file only when work becomes available, active, blocked or integrated.
8. Run `python tools/publish.py check`. Private names, paths and geometry stay out of every commit.

## Dev release gate

Push only when a useful batch is complete and the regression gates pass with no new losses. The
release report leads with exact feature-tree matches, then decoded/rebuild counts and remaining
blockers. Imported-solid figures are diagnostics only. Use sanitized diffs and never force-push or
publish branches containing private history.
