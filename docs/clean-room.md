# Clean-room rules

This converter has to stay free of proprietary code and data, so anyone can use it without a SolidWorks licence.

## Allowed sources
- Public specifications: Microsoft MS-CFB (compound files), MS-OLEPS (property sets),
  ECMA-376 custom properties, and later the published Parasolid XT format reference.
- Our own study of sample files their authors published (GrabCAD downloads, CC BY-SA projects).
- SolidCraft's own source (Apache-2.0 / MIT) for the *target* format.

## Not allowed
- The SolidWorks API, SDK, Document Manager, eDrawings, headers or type libraries.
- Running SolidWorks (or any licensed CAD) to produce data or reference output.
- Code from other converters under GPL/LGPL/AGPL licences, or any leaked or proprietary code.
- Copying text or documentation from SolidWorks help.

## Other projects' code

Another converter's code, whatever its licence, is read only once its authors say how they learned the format and that fits the rules above (public specifications and study of sample files, no SolidWorks API, SDK or Document Manager). Until then only results are compared, on the same public parts. cadkit-kernel (github.com/civilkit/cadkit-kernel, MIT OR Apache-2.0, crates `ck-sldprt` and `ck-swedit`): its author says it was made clean-room (asked 2026-11-24). It may be read as a guide, and (the user's decision, 2026-11-26, the author having confirmed clean-room) its code may be ported where it solves a blocker: each ported function names its cadkit source path in a header comment ("ported from cadkit-kernel <path>, MIT OR Apache-2.0") and cadkit's MIT notice is kept in `THIRD_PARTY_NOTICES.md`. Every finding it leads to is credited here and in the working log ("with help from cadkit-kernel"). Ported so far: `ck-swedit/src/rib.rs` (a rib's wall from its own faces), `ck-swedit/src/hole.rs` (hole placement planes from the hole's own cylinders), `ck-sldprt/src/sketch.rs` (`entities` and the curve records of `build_sketch`).

### Findings from cadkit-kernel (credited)

- *With help from cadkit-kernel* (`ck-sldprt/src/ir.rs`): each face of the part's Parasolid body carries the attribute `FACE_ID_2001`, integers `[kind, feature id, stamp, 0, local index, ...]`. The feature id is the feature's id in `swXmlContents/KeyWords`; a face two features share carries one tag per feature. Their reading of `kind` from sample files: 40 an end cap, 74 a side, 72 a fillet face. The body's `LAST_BODY_MODIFYING_FEATURE_ID` names the last feature that changed it. Not yet used here; to be checked on our own samples before it is.

## How the formats were learned
Record each new finding here.

- **Pre-2015 files:** a standard compound file. Streams ending `__ZLB` hold a 16-byte GUID,
  u32 raw size, u32 packed size, then zlib data.
- **2015+ files:** a run of records. Each has a per-file 4-byte tag, `14 00 06 00 08 00`, u32 type,
  u32 checksum, u32 packed size, u32 raw size, u32 name length, the name with each byte's
  nibbles swapped, then raw DEFLATE data. Found by looking for the repeated marker in sample files.
- **`swXmlContents/COMPINSTANCETREE`:** the XML assembly tree. The transform layout was
  confirmed by matching 18 sample assemblies' stored bounding boxes exactly.
- **`swXmlContents/KeyWords`:** an XML list of features, sketches and dimensions.
- **`Contents/Config-N-Partition`:** length-prefixed ZLB blocks: a Parasolid partition (`PS`
  header, root WORLD) and a deltas file (ignored).
- **`Config-N-FeatureBodies/LocalBodies`:** newer files keep each body here as its own Parasolid
  part, each preceded by the body's name as a UTF-16 string.
- **ZLB chunks:** after the 16-byte GUID come repeated (u32 raw size, u32 packed size, zlib);
  data over 1 MiB spans several chunks.
- **Parasolid data:** read from the published "Parasolid XT Format Reference" (Siemens, 2006;
  kept in `samples/specs/`, not committed). Differences found in real files: base schema 13006
  has 9 LIST fields, not 12; node types 163/184 (helix forms) are the other way round; a cone's
  radius grows along +axis (checked on 98 cone faces). Fields added by newer versions come from
  the schema edits each file carries.
- **Parasolid colours:** an owner's `attributes_groups` chain can hold `SDL/TYSA_COLOUR` (faces)
  and `SDL/TYSA_COLOUR_2` (bodies). Its `REAL_VALUES` fields begin with three finite RGB doubles
  in the 0…1 range. Found by inspecting published sample parts; the values are carried to AP214
  `COLOUR_RGB` / `STYLED_ITEM` chains and checked by opening the resulting STEP in SolidCraft.
- **`Contents/Config-N-ResolvedFeatures` (feature tree, F-006):** a stream of serialized
  objects in the layout of the publicly documented MFC `CArchive` object format: a new class is
  `FF FF`, u16 schema, u16 name length, ASCII class name, then the object's fields; a later
  object of a class already seen is `0x8000 | class index`. Text is `FF FE FF` + u8 length (in
  UTF-16 characters) + UTF-16LE. Lengths are SI units (metres). Classes seen in a one-sketch,
  one-extrude part (`shaft_3x22mm`): `moProfileFeature_c` (a sketch, named `Sketch1`),
  `sgSketch`, `sgPointHandle`, `sgArcHandle` (the circle), `sgCircleDim`/`moLengthParameter_c`
  (its 3 mm diameter, stored 0.003), `moExtrusion_c` (`Boss-Extrude1`), `moEndSpec_c` and
  `moFromEndSpec_c` (end conditions), `ParallelPlaneDistanceDim_c` (its 22 mm depth, stored
  0.022). The same values also appear in `Contents/Config-0`. Found by searching the stream
  for the part's known dimensions as doubles.
- **Sketch entities (partly decoded, `PCB_v1`, a 100 mm square):** inside the sketch's
  `moProfileFeature_c`, each sketch point is a record with a u32 id, then `FF FF 1F 00 01`, a
  fixed run of fields, `00 00 F0 3F 1E 00` and the point's x and y as doubles in the sketch
  plane (metres). Here the points were (0.05, 0.05), (−0.05, −0.05), (−0.05, 0.05) and
  (0.05, −0.05). Point id 1 is the sketch's origin (0, 0). Newer files (SolidWorks version
  15000) put 8 more zero bytes between `F0 3F` and `1E 00`.
- **Lines come from the points:** after its x and y, each point lists the lines it lies on,
  as `<class tag> <u16 line id> FF FF FF FF 00 00 00 00` per line. The first point's first line
  sits right after the `sgLineHandle` class header (its `03 00` is line 3). Two points that list
  the same line are that line's ends. Checked on two rectangles (`PCB_v1`, 100 × 100, and a
  120 × 40 mould part): every edge comes out right.
- **Sketch plane: in the sketch chain.** Each sketch's `moSketchChain_c` holds a plane record:
  class tag, `02 00`, 41 zero bytes, u32 **plane feature id** (−1 when the sketch isn't on a
  plane, e.g. on a face), u32 save stamp, then within about 120 bytes the sketch's **rotation**
  as 9 doubles (rows: the sketch's x and y axes and its normal in model space), then 3 doubles
  (offset, zero so far). A Front Plane sketch stores no rotation (the identity). Checked on all
  three sample sets: plane name and rotation agree every time (Top: x→(1,0,0), y→(0,0,1),
  n→(0,−1,0); Right: (0,0,1), (0,1,0), (−1,0,0)). Feature ids come from each named record: the
  `FF FE FF` name, 7 zero bytes, a flag byte (0x40 or 0xC0), u16 id. The first plane record,
  before `moProfileFeature_c`, always says id 2 and is not the sketch's plane.
- **The 2 bytes after `moCompRefPlane_c`** (`2E 80 02 00` and so on) are the class tag of a
  common sub-record (the same one starts every folder and feature), not a plane reference.
- **Dimension records** (`moSkDimHandleValG2_c`, `moSkDimHandleRadial_c`) start with the sketch
  plane's normal as 3 doubles, then the dimension's anchor points in sketch coordinates.
- **`moTransRefPlaneData_c` (in `Contents/Config-0`):** the plane's display size (half-extents
  of the model, e.g. 11 mm and 1.5 mm for the 22 × 3 mm shaft), not its orientation.
- **`swXmlContents/Features`:** XML naming the files a part refers to and its external
  features, e.g. a Cavity's tool body (`swExtFeature`, type `XformStock`, its name and the
  assembly's path).
- **SolidCraft as a checker:** built from its open source to open our output. It is never used
  to read SolidWorks data.
- **Segment records (2015+):** the sketch's records with the point header but no coordinates.
  u32 curve id, `FF FF 1F 00 03`, …, `F0 3F`, 8 zero bytes, u16 start and u16 end point (point id
  − 1), u16 flag (0 = construction). Holds in some sketches only; used where at least half of a
  sketch's records give the ends of curves already read. Gives the construction lines a centre
  rectangle's relations name (Part K: the origin on both diagonals).
- **Offset dimension (`sgSkOffsetDim`):** a value and no handles; the offset loop is the one its
  curves' relations don't hold. Written as parallel + distance and concentric + tangent.

- **Point record marker, older files:** files saved before about 2010 write `FF FF 07 00` where
  later ones write `FF FF 1F 00`; the rest of the record (`F0 3F 1E 00`, x, y, handle list) is the
  same (tutor1, Arduino 2560, tutorial 3). Found from the files.
- **Arc tag that is the line class:** where a sketch brings `sgLineHandle` in inline (curve id 1)
  and the next points name that edge under the tag the numbering gives `sgArcHandle` (also id 1),
  every "arc" under that tag has two points and no centre: the tag is the line class (A2773 bolt,
  its segment records give the same point pairs). Found from the files.
- **Centre point with an inline class:** a point record can carry an inline `moTempAxisRef_w`
  class after its `80 BF`, pushing its coordinates ~370 bytes on (figure 1); not used yet.
- **Curve records index points by position** (with help from cadkit-kernel
  `crates/ck-sldprt/src/sketch.rs`, MIT): a curve record's two ends, and an arc's or circle's
  centre (first of six u16 at +20, the second being `FFFE`), are positions in the sketch's list of
  point records, not point ids. Checked on the A2773 bolt (hexagon + circle), connecting rod, figure 1.
  A point id can be written twice; the first record is the sketch's point.
- **Fillet/chamfer edge groups with non-sequential own-face numbers:** each edge also has a group
  headed `04 00 00 00 00 02 00 00`, followed by four face references. The first is within 40 bytes
  after the 8-byte header; later references do not have fixed 20/24-byte spacing. Direct evidence:
  a CTC 02 Fillet3 group has references at +30, +74, +118 and +162 bytes from the header, and an
  FTC 06 Fillet2 group at +30, +74, +126 and +178 (the same in its 2015 and 2018 saves). The old
  4 × 24-byte collection window missed the fourth. A header-shaped run inside a reference is not a
  group: its supposed first reference begins inside the 8-byte header itself. Reading four sequential
  references with gaps of at most 72 bytes yields 46 distinct edges for CTC 02 Fillet3 and 18 for
  FTC 06 Fillet2. Found from the public sample files; no external implementation was used.
- **Extrude end type, mid-plane only (F-035):** `moEndSpec_c` stores its type as a u32 sixteen bytes
  into the object (after the class declaration for its first object, or after its class token later).
  The record starts `00 00 01 00` in the checked mid-plane cases, followed by 12 zero bytes and
  `06 00 00 00`. Type 6 is mid-plane: the listed depth is the total distance about the sketch plane,
  so it becomes SolidCraft's `direction: symmetric`, `convention: total_distance`. Checked directly
  against the raw records of NIST FTC 10 (75 mm) and public sample extrudes of 55, 20, 6, 4 and 3 mm;
  their type-0 blind counterparts store zero at the same offset. Other end types are not decoded by
  this reading. Layout identified with help from cadkit-kernel `crates/ck-sldprt/src/sketch.rs`
  (`object_word`, MIT OR Apache-2.0), then checked against these public files.
- **Linear-pattern `FIX_n` dimensions:** some patterns have no `D1` count or `D3` spacing in
  `swXmlContents/KeyWords`; they have exactly two dimensions named `FIX_n` instead. In ten linear
  patterns across two public saves of the same design family, the lower consecutive number is the
  spacing and the next number is the instance count: 20 mm and 2 throughout. The reader accepts only
  one consecutive numeric pair with a positive spacing and a positive integer count, so unrelated or
  ambiguous `FIX_n` records stay unread. Found from the public sample files; no external code used.
- **Split-tool profile references:** a split can contain a `moCompProfile_c` whose feature reference
  names its sketch (at +106 bytes from the object record in the checked public sample). This confirms
  the sketch association directly rather than inferring it from proximity. Only one of the 15 unread
  split features in the full public batch has this layout, so it is recorded as evidence but not yet
  made a production shortcut. The others need their face/surface tool references decoded instead.
- **Straight, uniformly spaced curve patterns:** `moCurvePattern_c` uses KeyWords' `D1` instance
  count and `D3` spacing in the two checked public cases. Each pattern record directly references
  the feature id of an earlier, otherwise-unused sketch containing exactly one nonzero line and no
  arcs or circles. Accept only a unique referenced candidate. The line and its selected sketch plane
  give the model-space direction; forward and reverse are both candidates. These straight paths are
  equivalent to a linear rectangular pattern, not a general curve-driven pattern. Two other public
  cases have a count but no spacing and remain TBD. Found from the public records; no external code.
- **Saved arc sense and repeated-sketch contours (B-026):** cadkit-kernel's
  `crates/ck-sldprt/src/sketch.rs` explicitly says arc direction is not stored in the checked raw
  records; its `sense` field is not that direction. I resolve direction only from the part's own
  Parasolid circular edges: `same_sense` and the circle normal against the sketch normal determine
  counter-clockwise storage. Saved endpoints must resolve to existing sketch points; no point is
  invented. A full saved circle can similarly select an existing sketch point as a misread circle's
  centre when another existing point lies at its saved radius. `FACE_ID_2001` side faces identify
  which raw sketch loops belong to each repeated boss/cut. The shared-sketch clone is copied only
  after these corrections and each use filters its own curves and related constraints. Confirmed on
  a private sample; no private name, path, dimensions or geometry are recorded.


- **Repeated sketch dimension parameters (B-028):** a dimension's first parameter can be stale;
  the later parameter of the same name within that dimension carries the current value. Handles
  belong only to the interval before the next D… parameter or the relation list. Repeated handles
  are duplicates. R/Ø and MOD-DIAM metadata are usable only when the shown value, one raw parameter
  and an existing circle/arc all agree. A zero point handle may name the sketch origin directly;
  other direct/offset point IDs are accepted only when exactly one geometric reading agrees with
  the stored value. The approved cadkit-kernel `ck-sldprt/src/sketch.rs` describes relation point
  handles as record positions; sparse handles that fit neither the ID nor position reading remain
  unresolved. Evidence came from raw records of a private part, with no private identifiers or
  measurements published. Contour filtering must renumber curve references, retain required
  reference lines as construction geometry and remove unused points.


- **`edgeRadiusObject_c` named fillets (B-029):** three independent private models contain named
  records of this class whose feature IDs and KeyWords type identify them as Fillet features. Their
  radius parameter and face-reference layout agree with the working `Fillet_c` records in the same
  files. The reader maps this class to fillet only when the named feature's saved type confirms it;
  unnamed records and other feature types are not reclassified. No radius is inferred from nearby
  geometry. No private names, values or geometry are published.
