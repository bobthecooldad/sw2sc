# Changelog

Versions follow [semantic versioning](https://semver.org). The version is in `VERSION`.
Each release has a survey log in `logs/survey-<version>.md`.

## [Unreleased]

### Added
- `tools/publish.py`: `check` finds personal data (home and cloud-folder paths, e-mail addresses,
  and the private names and words kept in a private folder outside the repository); `export`
  writes the repository into a clone of the public one with private names replaced by fixed
  aliases, then checks it. Nothing is committed or pushed by it.
- `tools/checks.py`: a check queue that follows a branch and runs the whole suite on each new
  commit in a checkout of its own (build, parity, tests, regression set, and the long sample run
  while idle), with a report per commit; `tools/rebuild_set.py` and `tools/convert_sample.py`
  run the regression set and the sample.
- `ROADMAP.md` and `CONTRIBUTING.md`: where help is most useful, which recent fixes need checking
  on more files, and the rules for contributing.
- The public repository's CI build and release workflow, version stamping and LICENSE.
- **Scale** (`moScale_c`) comes across as SolidCraft's scale: its x, y and z factors from the
  record (KeyWords lists no dimension for it), the point it scales about (the origin, the solid's
  centre of mass or the middle of its box) chosen by the rebuild check. Before a scale, the
  search's volume bounds and box check are off: the solid is still to change size.

### Fixed
- Lengths from KeyWords (thin extrudes, shells, domes, pattern spacings, threads) are in the
  document's units and rounded for display: they are now taken exact from the feature's record,
  so inch parts no longer come out 25.4 times too small.
- An extrude whose depth is only in KeyWords is built to that depth, not tried as through all.
- A sketch whose plane reference is written after it is tried on that plane too.
- The rebuild search no longer retries every combination of later sketches' planes when an early
  sketch's plane is wrong: plane sets that repeat a prefix that already failed are skipped.
- An extrude whose sketch isn't found is TBD (the plugin stopped on it).
- A partial build smaller than the part, with nothing left that adds material, is dropped: a
  boss read as a cut no longer passes because it changed the solid.
- An extrude whose sketch plane reads through the origin is also tried starting at a face of the
  body so far (SolidCraft's `start_offset`): sketches on faces whose plane isn't stored, or on a
  pocket's floor.
- An arc whose centre was read at the wrong point is given the sketch point that makes the lines
  meeting it tangent.
- A thin cut kept under the plain cut class gets its wall from KeyWords' `D5`.
- An extrude or revolve whose sketch has no curves read is TBD instead of building nothing.
- A boss whose sketch has a loop reaching past the part (a stray circle read with the outline) is
  also tried without it.
- Hole Wizard holes: a tapped hole's `Thread Major Dia.` where it has no drill diameter, and the
  `Diameter`, `Depth`, `C-Bore Diameter`, `C-Bore Depth` names some files use.
- A Hole Wizard hole whose record names no size takes it from its default name (`M3 Clearance
  Hole1`, `M3 Tapped Hole1`, `Tap Drill for M2 Tap1`) with the ISO 273 and ISO 261 tables.
- A Hole Wizard hole placed by a 3D sketch: its points are read and drilled on the plane through them.
- Every part is rebuilt in sequence: plain extrude-and-cut parts now also get a boss read as a cut,
  starts from a face and stray loops left out.
- A circle whose radius matches none of its sketch's circle dimensions is centred on the point at
  a dimensioned radius from its through-point.

### Changed
- Features kept in the tree that make no solid (unused sketches, reference axes, cosmetic
  threads, combines) are `kept` in the tree summary, and the plugin's import report lists them
  as information instead of among the features not converted.
- Sketch text says why it isn't converted: SolidWorks keeps the words, their size and place, not
  the letters' outlines, so SolidCraft's own lettering can't be matched to the solid exactly.

## [0.17.3] - 2026-11-23

A sketch's chain record is read, and a rebuild that doesn't match now says what shape its cause
has.

### Added
- **A sketch's chain record is read and kept.** `moSketchChain_c` — 196 parts write one, at the end
  of the sketch — is a `u16` count and then that many `u32` point ids: the points a chain runs
  through, in order, in the sketch's own numbering (Bucket's 12 are its 12 lines' points,
  spring_holder_v1's 10, PartT_7's 18, 19, 20, 17). Kept on `Sketch.chain`. It is a different
  numbering from the region's curves, which is why the two records looked unrelated. It does not
  settle F-047, and the lead is now spent: the points Bucket's and PartT_7's chains name but the
  reader lacks (3, 18), and Rocker Arm's missing arc ends (9, 11), have no record of their own
  anywhere in the sketch, so the file stores no position for them to be read from.

- **A rebuild that doesn't match is signed by the shape of its cause.** `verify.mismatch_signature`
  reads the numbers a candidate came out with and names the first thing to look at: too much
  material points at a loop taken as an island or a cut that didn't take, too little at a missing
  feature or a wrong direction, the same volume with a different area at a missing or wrong fillet
  or chamfer, and a box that moved on its own at the placement. A design that doesn't build is
  signed by what stopped it. `feature_check` writes it in the report's notes (`too much material
  (+12.2%): a loop is an island, or a cut didn't take`), and the closest attempt is kept
  (`verify.LAST`) so the numbers signed are the best the search reached, not its last try.

### Fixed
- **Opening a large pre-2015 file could take minutes.** Finding where its numbering starts
  numbered the whole feature stream for each of up to 600 starts; only the stream up to where
  `moRefPlane_c` is brought in decides it, so only that is numbered now (the same start on all
  33 old samples, which now read in 3.3 s together).
- **The rebuild search spun on parts built in sequence.** It stepped through every set of extrude
  directions (3 ** extrudes, billions for 20 extrudes) only to skip each, until the 240 s budget
  ran out; one set is taken now, as the directions are chosen feature by feature anyway.
- **The tests took hours and four failed.** The vault tests imported whole trees with the rebuild
  search on every part; they now import without it (the rebuild has its own tests), so they are
  quick and the same every run. `test_archive` failed to load under `discover`. All 80 tests
  pass in 94 s.

### Added (plugin)
- **`plugin/`: a SolidCraft importer plugin** (Rust, WebAssembly) that opens `.sldprt` files with
  their feature tree, checked against the part's own solid through SolidCraft's `evaluate`
  interface. A port of this converter: the same reading on all 199 sample parts, the same
  designs, the same rebuilds on the 22 compared. `plugin/build.ps1` builds `plugin/sw2sc.zip`.

### Results
- **Full feature check over `samples/slippad-solidworks` (35 parts) on 0.47.0:
  10 rebuilt and matching, 19 rebuilt without a match, 4 not fully decoded, 2 pre-2015**
  (`logs/survey-0.17.3.md`, `logs/feature-check-0.17.3.md`). Every part has the same result as
  0.17.2, part for part — what this release should do, since the chain is kept as data and
  nothing in the rebuild path reads it.
- The signatures are what the report gains: 8 of the 19 mismatches name the shape of their cause,
  the other 11 `no build to compare` (the search spent its budget before evaluating a candidate).
- F-047 is no further forward: its chain lead is spent (see the issue).

## [0.17.2] - 2026-11-23

A rebuild check now says which SolidCraft checked it, and refuses to be believed otherwise.

### Added
- **The kernel a rebuild used is recorded, and checked.** SolidCraft is built most days, and a
  check tool silently took whichever `solidcraft-cli` it found first — the installed 0.44.1
  while the checkout stood at 0.47.0. `verify.kernel_status` compares the CLI with the checkout
  beside it (its version, and the binary's build time against the checkout's last commit) and
  gives the reason when it is behind. `feature_check` and `rebuild_triage` write that line into
  their reports and warn on stderr; a conversion records it in the design's metadata
  (`rebuild_check`) and warns (B-022).

- **Sketch regions are read and kept.** A sketch's `moSketchRegion_c` names the curves of the
  region SolidWorks made, each with its tag resolved through the file's own class table
  (`Sketch.region`). Kept as data: the tag is `sgArcHandle` for circles too, so it does not by
  itself tell an arc read from one point from a circle (F-047, still open).

- **A tie between two 0.47.0 CLIs is no longer the installed copy's.** The app updates itself,
  so `find_cli` could take `C:\Program Files\SolidCraft` while the report named the checkout
  build. A build from a checkout now outranks an installed copy at the same version, an
  installed copy is reported stale, and `feature_check` passes the CLI it reports into the
  rebuild. It also prints each part as it goes instead of only at the end.

### Results
- **Full feature check over `samples/slippad-solidworks` (35 parts) on 0.47.0:
  10 rebuilt and matching, 19 rebuilt without a match, 4 not fully decoded, 2 pre-2015**
  (`logs/survey-0.17.2.md`, `logs/feature-check-0.17.2.md`). Against the 0.17.0 report, 11 parts
  that stopped on an unread feature now decode, and 4 more rebuild and match; none regressed.
- Refreshed to today's `main` (0.47.0, commit 1f8df8628) and rebuilt `solidcraft-cli`. Boom still
  rebuilds from its tree and matches its solid exactly; PartT8, bearing_3x6x2 and
  Top_modular_aperture_v2 still match. The idler arms' R1 outline fillet is still refused, now
  with the wall measured at 0.906 mm: their arc is right, and what SolidWorks rounds over the
  hole's face the kernel will not yet do.

## [0.17.1] - 2026-11-23

A hole at a rounded end came across as a lump.

### Fixed
- A sketch's loops are nested by each arc's real curve, not by its chord. A hole inside an arc
  that bulges outward (Boom's fourth pin hole, in a 2.275 mm round end) fell outside its
  outline and was extruded as an island: a solid lump where SolidWorks has a hole (B-021).

### Results
- Boom (CAT wheel loader) now rebuilds from its feature tree and matches its solid exactly:
  sketch, an extrude, a 4-edge fillet, a through-all cut and a pin — 4413.955 mm3, 4491.51 mm2.

## [0.17.0] - 2026-11-19

Chamfers and Hole Wizard holes come across, and features the file's numbering hid are found.

### Added
- **Chamfers** become SolidCraft chamfers on the edges SolidWorks chamfered: distance (`D1`) and
  angle or second distance, tried on both sides where the two differ.
- **Hole Wizard holes** become SolidCraft holes (SolidCraft has the feature: simple, drilled,
  counterbore, countersink), drilled at the hole's placement-sketch points, with SolidWorks'
  sizes ("Hole Dia.", "C'Sink Dia.", "C'Sink Angle" …) as model parameters. Blind or through
  all, and the side, are settled by the rebuild check.
- **Features KeyWords lists as extrudes, holes and cuts** (`<Extrusion>`, `<HoleWizard>`,
  `<Cut>`) are recovered by name when the record numbering misses them; an extrude KeyWords
  types as a boss or a cut is read as that. `moCut_c` reads as a cut-extrude.
- Parts with fillets, chamfers or holes are rebuilt feature by feature: each extrude only the
  ways that change the solid and keep it inside the part's own box, so parts with many
  extrudes no longer run out of tries.

### Fixed
- Six files crashed the reader after 0.16.0's recovery (a recovered feature had no record).
- SolidCraft names an extrude's far face `bottom` too; edges on it weren't found.
- Circles whose handle class the numbering doesn't know (one point per curve) are read.
- A hole's sketch follows the feature-id remap when the rebuild joins the converted part.

### Results
- 16 parts rebuild from their feature tree and match their solid (14 in 0.16.0), among them
  Top_beltSupportRim (a 70-degree chamfer) and Top_modular_aperture (Hole Wizard countersinks).

## [0.16.0] - 2026-11-19

Fillets come across as SolidCraft fillets, on the edges SolidWorks rounded.

### Added
- **Fillets** are read from the file: the radius (a model parameter, `Fillet1_D1`) and the
  edges, which SolidWorks names by the faces meeting there (a face swept by a sketch curve of a
  feature, an end face, an earlier fillet's face). sw2sc rebuilds the part up to the fillet in
  SolidCraft, lists its edges by SolidCraft's own names (`F5:side:l3|F5:top`) and works out
  which edges are SolidWorks': which sketch curve each SolidWorks entity number is, which end
  face is the start, consistently across all the part's fillets. The fillet is written with
  those edges and names, and the part is kept only if it still matches its own solid.
- **Features the record numbering missed** (88 fillets in the samples, and chamfers and others)
  are now found by their name from KeyWords' feature list, so they keep their place in the tree
  instead of disappearing; a missed fillet is read as any other.
- Sketch text marks its sketch TBD (it isn't converted yet).
- A part whose own solid imports as open faces (no volume) is checked by its area and box.

### Results
- 14 distinct parts rebuild from their feature tree and match their solid (13 in 0.15.1, now PartT8 too); none lost.
- PartT8 (griper robot) is the first part with fillets rebuilt from its tree: sketch, extrude,
  a 60-edge and a 12-edge fillet, matching its solid.
- The idler arms' outline fillet (R1 all round) is refused by SolidCraft ("not supported yet:
  the fillet is larger than the faces beside its edges allow"), so they keep their solid.

## [0.15.1] - 2026-11-19

### Changed
- **Offsets are SolidCraft offsets.** A SolidWorks Offset Entities now becomes SolidCraft's own
  associative offset (Sketch > Offset), driven by one offset dimension with the SolidWorks
  parameter (`Sketch2_D4`), instead of a parallel and a distance per line. solidcraft-cli makes
  the offset from the loop it follows; it's kept when its curves are the ones SolidWorks drew
  and the part still matches its solid, else the 0.15.0 constraints stay. Extrudes that used the
  loop use the offset's curves.

### Results
- Part K: one offset dimension holds the outer loop; the sketch is at 0 degrees
  of freedom, and D4, D3 and D2 each rebuild the part as SolidWorks would.

## [0.15.0] - 2026-11-19

Sketches stay where SolidWorks put them: construction lines, the origin and offsets come across.

### Added
- **Construction lines** are read from the sketch's segment records (where their numbering
  checks out against the curves already read) and written as SolidCraft construction lines,
  kept out of profiles. A centre rectangle keeps its diagonals, so the relations putting the
  origin on them now hold the sketch on the origin.
- **Offsets** (Sketch > Offset Entities, the `D4` of Part K): SolidCraft has no
  offset constraint, so each offset line is written parallel to its partner at a distance
  driven by the offset's parameter (`Sketch2_D4`), and each offset arc concentric with its
  partner and tangent to the lines it meets. Changing `Sketch2_D4` moves the whole loop.
- Revolves try construction lines (centrelines) first as their axis.

### Results
- Part K's sketch is fully constrained (0 degrees of freedom), centred on the
  origin, with the outer loop 3 mm off the inner one all the way round.
- The 13 parts that rebuild still match their solid; 121 constraints in all (was 93).

## [0.14.0] - 2026-11-19

Sketch dimensions and relations come across with the feature tree.

### Added
- **Sketch dimensions** become SolidCraft driving dimensions, each with a model parameter named
  after the SolidWorks one (`D1@Sketch2` is `Sketch2_D1`): distances between points, radii and
  diameters. Only dimensions SolidWorks lists for the sketch are used, and only where the stored
  value matches what it measures.
- **Sketch relations** become SolidCraft constraints: horizontal, vertical, tangent, parallel,
  perpendicular, coincident, point on a curve, midpoint, the corner where two lines meet,
  equal, collinear, concentric, symmetric, points level or plumb. A relation is written only
  when everything it names was read and it holds in the sketch; relations to projected model
  geometry (the origin, an axis, a model edge) are left out for now.
- **Extrude depths** are model parameters too (`Boss_Extrude1_D1`), so changing one in
  SolidCraft rebuilds the part.
- If a sketch's constraints ever made the rebuild differ from the solid, the part keeps its
  features without them instead of falling back to the imported solid.
- Revolves are read and tried (they don't rebuild to a match yet, so those parts keep their
  solid). The rebuild check uses the newest `solidcraft-cli` it finds, by its `--version`.

### Results
- The 13 sample parts that rebuild from their feature tree still match their solid, now with
  93 constraints and their sketch dimensions. Part K: 27 constraints and the
  dimensions D1 = 50, D2 = 150, D3 = R3 plus the 20 mm depth.

## [0.13.0] - 2026-11-19

Parts come across with their own feature tree where it is decoded.

### Added
- **Feature trees (F-006, in progress).** sw2sc reads a part's features from its own feature
  stream: sketches (points, lines, arcs, circles and the plane or face they are on), extrudes
  and cut-extrudes (depth, direction), added planes, and imported bodies. When every feature of
  a part is decoded and SolidCraft's `solidcraft-cli` is on the PC, the part is rebuilt from
  those features and kept only if its volume, surface area and size match the solid SolidWorks
  saved; the part then opens in SolidCraft as editable sketches and extrudes. Otherwise it keeps
  its exact imported solid, as before.
- Every part's design records its feature tree in the sw2sc metadata: each feature's name,
  kind, and whether it converted or is **TBD** (with the SolidWorks class it would need), in its
  place in the tree.
- Files from before 2015 and from 2015 on, in any language (feature names are not used).
- Tools for the work: `tools/feature_check.py` (rebuild and compare every part in some
  folders), `feature_stats.py`, `feature_blockers.py`, `feature_debug.py`, `feature_survey.py`,
  `archive_check.py`. How the format was worked out, wrong turns included, is in
  `logs/working-log.md`.

### Results
- Over the three sample sets (199 parts): 13 parts rebuild from their feature tree and match
  their solid; 71 are imported bodies (no tree in SolidWorks either) and convert as imports; 2
  rebuild but don't match yet; the other 113 keep their imported solid with their tree recorded
  and the unconverted features marked TBD. Most common TBD: fillets, revolves, chamfers, Hole
  Wizard holes, mirrors.

## [0.12.0] - 2026-11-18

Folders in the vault, and imports that check the folder first.

### Added
- **Folders** in the vault window: a folder tree beside the designs, with New folder, Rename
  and Remove, and a Folder picker in each design's details (or drag a design onto a folder).
  Folders sort what the window shows; files stay where the import put them, so links,
  releases and the next import keep working. They are kept in `folders.json` and each
  change is a Git commit. A design starts in the folder its SolidWorks file came from.
- **Copy the folder's other files too**: untick it (or `--designs-only`) to import only the
  SolidWorks files.

### Fixed
- An import now checks the folder first and asks before going on (B-011) when it is a
  personal or whole-drive folder (Documents, Desktop, the user folder), holds few SolidWorks
  files among many others, is very large, or is a different project than the vault holds
  (whose designs the import would remove). The command line refuses unless given `--yes`.
- SolidCraft's own lock files (`.~name.lock`) are no longer imported.
- An import never overwrites the vault's own `folders.json`, `roles.json` or `workflow.json`.

### Results
- An import of a whole Documents folder (17.2 GB, 18 SolidWorks files among 19,238) was
  stopped and its copies removed; the vault's history was untouched. The check now refuses it.
- On a copy of a 40-design vault, folders were made, designs moved (picker and API) and each
  change committed. Dragging could not be checked with the test browser.

## [0.11.0] - 2026-11-18

Open in the SolidCraft window you already have.

### Added
- **Open** and **Open in SolidCraft** send the design to a SolidCraft window that is already
  open, through its local control channel (`doc.open`), instead of starting another window.
  SolidCraft puts it in a new tab and only ever replaces a blank design. A new window starts
  when none answers: none open, the channel turned off, an older app, or a stale token.
- `"reuse_window": false` in `~/.sw2sc-gui.json` always starts a new window.

### Results
- Tests use a stand-in control server: open sent with the token, fallback on no app and on a
  refused token. The SolidCraft window open on this PC answered a read-only request on port
  27878 with its token file.

## [0.10.0] - 2026-11-13

Open designs in SolidCraft.

### Added
- **Open in SolidCraft** on the selected design in the vault window.
- **Open** on each release: the release is pulled out of Git into a temporary folder first,
  so you see exactly what was released; changes there don't touch the vault.
- The window finds the SolidCraft app on the PATH, in its install folders and in a build in
  `C:\dev\solidcraft`, and uses the newest one. The `solidcraft` entry in
  `~/.sw2sc-gui.json` picks one yourself. Only designs the vault lists can be opened.

### Results
- The SolidCraft desktop app 0.40.1 was built from source on this PC (Rust 1.98.0, about 16
  minutes). It opened the vault's `Assem4` with all 23 links found.
- From the window, Open started SolidCraft 0.40.1 on the design, and Open on release A started
  it on the pulled-out copy. A path outside the vault was refused.

## [0.9.0] - 2026-11-12

Approver roles.

### Added
- `roles.json` in a vault names the **admins** (they change the roles) and the **approvers**
  (they release and reject). Anyone can still submit and start a new revision.
- **Four-eyes** rule (optional): an approver can't release something they submitted. A
  whole-assembly release then can't submit and release in one go; it lists what blocks it.
- Who is acting is the logged-in account (`DOMAIN\user` on Windows), never a typed name, in
  both the window and the command line. History records that account.
- A vault without roles stays open, as before. The first person to set roles up becomes the
  first admin. A vault always keeps at least one admin.
- Every change to the roles is a Git commit.
- Command line: `vault roles <vault>` shows them; `add-approver`, `remove-approver`,
  `add-admin`, `remove-admin` and `four-eyes on|off` change them.
- Window: "You are ..." with your roles; a Roles panel (admins can add and remove people and
  turn four-eyes on or off); Release and Reject show only for approvers, and everyone else
  sees who the approvers are.

### Changed
- `--by` is gone from the command line: the account is taken from the system.
- A damaged `roles.json` blocks releasing until it is fixed, rather than opening the vault.

### Limits
- This guards against mistakes, not against someone determined: anyone who can write the
  vault's files can change them. Git history shows any such change.

## [0.8.0] - 2026-11-12

Release a whole assembly.

### Added
- **Release with everything it contains**: releases an assembly and every part and
  subassembly in it that isn't Released yet. Parts go first, then the assemblies that use
  them. Items In Work are submitted and released in the same step, and their history says so.
  Items already Released are left at their revision.
- **Submit with everything it contains**: moves the assembly and everything in it that is In
  Work to In Review, for a team that reviews before releasing.
- Both show what they will do first and change nothing until confirmed. Both are all or
  nothing: one blocked item (Obsolete, or failed to convert) stops the whole step.
- One Git commit for the whole step, and a Git tag for each item released.
- Command line: `vault release-all` and `vault submit-all`, with `--dry-run` to preview.

### Changed
- The workflow checks a step, applies it in memory and records it once, so a single release
  and a whole-assembly release are recorded the same way.

### Results
- Slip-Pad `Assem4`: 40 items released in one step (one commit, 40 tags). After one part
  changed, the next release of `Assem4` released only the 4 items at rev B and left 36 alone,
  done from the window.

## [0.7.0] - 2026-11-12

Release states.

### Added
- Every part and assembly in a vault has a state and a revision: In Work, In Review,
  Released (and Obsolete when it leaves the source folder). `workflow.json` keeps them.
- Actions: submit (In Work to In Review), reject (back to In Work, with a reason), release
  (In Review to Released), and revise (Released to the next revision, In Work). Revisions
  count A, B ... Z, AA; a SolidWorks revision property is the first label when it has one.
- Rules: an assembly can't be released until everything it contains is Released.
- Import keeps the states. An item that changes, or that contains an item that changed, goes
  back to In Work; if it was Released, its next revision starts.
- Each change records who, when and a comment, and is a Git commit. Each release is also a
  Git tag, and `vault get` (or **Get this release** in the window) writes that release and
  everything it contained, exactly as released, to a folder.
- Command line: `vault status`, `vault submit`, `vault reject`, `vault release`,
  `vault revise`, `vault get`.
- Window: State and Rev columns; on the selected item, the action buttons with a comment and a
  name, what still blocks a release, each contained item's state, the state history and the
  releases.

### Fixed
- The window's server no longer shares its port with another server (B-017).

### Results
- Released the idler assembly and its four parts, then changed one part in the source. The
  re-import moved the part and the assembly to rev B In Work and left the other parts
  Released. Release A came back byte for byte, and SolidCraft found all its links unchanged.

## [0.6.0] - 2026-11-12

Vault window.

### Added
- `Vault.cmd` (double-click) or `python -m sw2sc gui` opens the vault window in the browser.
  It runs on this PC only: it listens on 127.0.0.1 and needs a token made for each run.
- Import a folder: Browse buttons open Windows' folder dialog, the options match the command
  line, and the import shows its progress. The last folders are remembered.
- Vault contents: search by name, part number or description, sort any column, and select an
  item to see its properties, everything it contains (with quantities through every level),
  where it is used, its conversion notes and the import history. Show in Explorer opens the
  vault or a design.
- `vault import --embed-subassemblies` keeps subassemblies inside each assembly, as before 0.5.0.

### Results
- Driven in a browser: imported the Slip-Pad tree into a new vault from the window, searched,
  and followed where-used and contains links. Requests without the token, with a wrong token
  or from another host name are refused (tested).

## [0.5.0] - 2026-11-12

Linked subassemblies.

### Added
- In a vault, a subassembly is linked to its own design instead of being repeated inside
  every assembly that uses it. It is one linked component, the form SolidCraft's Insert Design
  gives a linked assembly. Its geometry is a STEP assembly that places each of its parts with a
  mapped item (`stepasm.py`); a part placed many times is stored once in it.
- Assemblies import bottom-up, so each subassembly's design exists before its parent links to
  it. A loop between assemblies is reported and left embedded.
- Re-import follows the chain: a changed part reconverts its subassemblies and every assembly
  above them, and nothing else.

### Results
- Slip-Pad `Assem4`: 23 components instead of 39, 4 subassembly links. SolidCraft 0.40.1 opens
  it with no errors, finds all 23 links, and Update Links reads them all.
- `vault bom` multiplies through levels: 4 bobbin assemblies x 4 bearings = 16 bearings.
- GrabCAD tree: 167 designs, none failed. In the wheel loader, steam engine and office-suite
  assemblies SolidCraft finds every link (subassemblies included) and Update Links fails none.

### Limits
- SolidCraft shows a linked subassembly as one part today (F-022). Its parts stay listed in
  `vault.json`, `vault bom` and `vault where-used`.

## [0.4.0] - 2026-11-12

Vault import.

### Added
- `sw2sc vault import <source> <vault>`: converts a folder tree into a vault of SolidCraft
  designs. Folders are mirrored, each part and assembly becomes its own design, assemblies
  link to their part designs with SolidCraft's own link format, and other files are copied.
- `vault.json` and `VAULT.md`: the index of properties, revisions, uses and where-used.
- Git history: each import is one commit. Running it again converts only the changed files
  and the assemblies that link to them.
- `sw2sc vault where-used` and `sw2sc vault bom`, through all levels of nested assemblies.
- `docs/vault.md`.

### Changed
- STEP text no longer carries the time it was written, so the same part always gives the
  same design and an unchanged part shows no change in Git.
- A referenced part found in several folders resolves to the copy nearest the assembly.
- The validator checks design links.

### Results
- Slip-Pad tree: 40 designs in about 10 seconds. SolidCraft 0.40.1 finds every link, sees it
  as unchanged, and Update Links reads all of them.
- GrabCAD tree (7 projects): 167 designs and 100 other files, none failed. In the wheel-loader
  assembly SolidCraft finds all 15 links.

## [0.3.0] - 2026-11-12

Fillets.

### Changed
- Rolling-ball fillet surfaces are built from their definition instead of fitted through
  boundary points: the spine is solved to lie exactly at the blend offsets from both supporting
  surfaces, and each cross-section runs between the spine point's feet on those surfaces.
- Closest-point projection for every surface type, including fillets on fillets, cliff-edge
  fillets (a zero-radius blend stands for the cliff edge) and offsets.
- B-spline supports are continued along their border tangents, since a fillet can run past the
  patch its support is stored on.
- Intersection-curve edges are densified and each point is put exactly on both surfaces.
- Exact B-spline edge curves are trimmed to the piece the edge uses.

### Results
- In a 4-part check, fillet faces more than 0.1 mm from their edges went from 72 of 85 to 0.
- SolidCraft 0.40.1 reads 296 of 399 solids as closed (was 273); 142 of 185 part files come in
  fully closed (was 136). 42 of the remaining open solids are one part (Tyre, B-012).

## [0.2.0] - 2026-11-12

Geometry: parts now carry their solids.

### Added
- `parasolid.py`: reader for the Parasolid neutral-binary data inside SolidWorks parts, written
  from the published XT Format Reference, including the per-file schema edits newer versions use.
- `xtgeom.py`: Parasolid nodes to a neutral B-rep. Exact for planes, cylinders, cones, spheres,
  tori, B-spline surfaces and curves, lines, circles, ellipses, and offsets of those. Fitted
  B-splines for intersection curves, curves on surfaces, rolling-ball blends, swept and spun
  surfaces.
- `step.py`: STEP AP214 writer (millimetres). `nurbs.py`: evaluation, interpolation, trimming.
- `geometry.py`: finds bodies in `Config-N-Partition` and in `FeatureBodies/LocalBodies`
  (newer files keep one Parasolid part per body there).
- Each part component gets an Import feature holding its STEP text. `--no-geometry` skips it.
- `tools/check_steps.py` opens every STEP file in SolidCraft's CLI; `tools/selfcheck.py`
  measures edge-to-surface gaps without SolidCraft.

### Fixed
- ZLB streams over 1 MiB are split into chunks; all chunks are now read (B-006).

### Results
- All 186 sample part geometries parse to the last byte; 185/185 parts with geometry export to
  STEP and open in SolidCraft 0.40.1 without errors.
- SolidCraft reads 273 of 399 solids as closed bodies; 136 of 185 part files come in fully
  closed. The rest open as surfaces or with faces missing (see B-007 to B-010).
- 34,207 faces converted: 1,184 are fitted approximations, 28 left out.

## [0.1.0] - 2026-11-11

First version: structure migration.

### Added
- Clean-room readers for both SolidWorks containers: pre-2015 compound files (`cfb.py`) and the
  2015+ record format (`swfile.py`).
- Assembly tree from `COMPINSTANCETREE`: nested subassemblies, shared definitions, instance
  numbers, placements, hidden/suppressed/virtual/BOM flags.
- Feature tree, material and configurations from `KeyWords`.
- Custom properties from `docProps/custom.xml` (2015+) and OLE property sets (older).
- SolidCraft writer (format `solidcraft/28`): components, occurrences, hidden placements,
  component metadata and properties.
- Validator mirroring SolidCraft's open checks (`validate.py`).
- CLI: `convert`, `inspect`, `survey`. Unit tests.

### Results
- 207/207 sample files (40 Slip-Pad, 167 GrabCAD; 111 pre-2015, 96 2015+) convert and validate.
  See `logs/survey-0.1.0.md`.
