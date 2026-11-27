# Working log

What was tried, what worked and what didn't, newest last. Format findings that hold up go
into `docs/clean-room.md`; this log also keeps the dead ends, so they aren't tried twice.

Sample sets every finding is checked against:
- **A** `samples/slippad-solidworks` — 33 parts, SolidWorks version 7000 (2007-era).
- **B** `<parts folder>` — 14 parts, 4 assemblies, version 15000 (2015+). Read in
  place, never copied. Includes Cavity, Mirror, Fillet, Scale, Sheet-Metal.
- **C** `Solidworks Example Grabcad` — 150 parts from many versions.

## 2026-11-18

**Goal (from the user):** open any SolidWorks file in SolidCraft and carry on as in
SolidWorks: every file, with its sketches, features and history editable. Read the real tree
from the file; no rebuilding by guessing from the geometry. A feature SolidCraft lacks becomes
a TBD placeholder in its place. The converter must be generic, for all SolidWorks files.

1. **Where the tree is.** `Contents/Config-N-ResolvedFeatures` in 66 of the sample parts
   (A, C). Found by searching for the shaft's known dimensions as doubles: 0.003 (Ø3) and 0.022
   (22 mm) sit in `ParallelPlaneDistanceDim_c` and the sketch's `sgCircleDim`. Lengths are in
   metres. **Worked.**
2. **Object layout.** The MFC `CArchive` format: `FF FF` + schema u16 + name length u16 + class
   name for a new class; text as `FF FE FF` + length + UTF-16. **Worked.** Class names found:
   `moProfileFeature_c` (sketch), `sgPointHandle`, `sgLineHandle`, `sgArcHandle`, `sgSlot_c`,
   dimensions, `moExtrusion_c`, `moCut_c`, `moRevolution_c`, `moICE_c`, `moHoleWzd_c`,
   `moMirrorPattern_c`, fillets, `moCavity_c`.
3. **Sketch points.** Record: u32 id, `FF FF 1F 00`, type byte, fixed fields, `F0 3F`, (version
   15000: 8 more zero bytes), `1E 00`, x, y as doubles. Point 1 is the sketch origin. **Worked**
   on PCB_v1 (A, 100 × 100 square) and the mould part (B, 120 × 40).
4. **Sketch lines.** First guess: lines list their two points. **Wrong.** The points list the
   lines they're on; two points naming the same line are its ends. **Worked** on both
   rectangles: every edge right.
5. **Sketch plane, first guess:** the 2 bytes after `moCompRefPlane_c` (`2E 80 …`) as a plane
   reference. Matched the mould (Front) by chance. **Wrong**: PCB_v1 (Top) and the shaft (Right)
   read the same value.
6. **Sketch plane, second guess:** that value as an MFC object number. Counted objects:
   within 1 on the mould part, 80 off in set A. Across A the value ran 0x6A–0x14C and one
   value meant different planes. **Wrong.** In set B the value is the same at the start of
   every folder and feature record of a file: it is the class tag of a common sub-record.
7. **Sketch plane, other places tried, nothing found:** unit vectors near the sketch (only the
   standard planes' own); `moTransRefPlaneData_c` in `Contents/Config-0` (the plane's display
   size); the 4-byte value in the plane-reference record (found nowhere else; Front in one
   part and Right in another share it); the sketch header (Top and Right identical, the flag
   word splits differently in other parts).
8. **`Contents/Config-0` around Sketch1:** a feature history: each feature name followed by
   "Created" and "Modified" entries with 4-byte times. Useful for the history the user wants
   kept; not the plane.
9. **`swXmlContents/Features`:** XML naming the files a part refers to and its external
   features, e.g. the mould's Cavity tool body `Part L<1>` in
   `Part D.SLDASM`. **Worked.**

**Lesson:** spot-checking bytes on two or three files keeps producing readings that fit by
chance. Next is a real reader for the object stream, checked on all of A, B and C at once,
before any more field guesses.
10. **Survey of all three sets** (`tools/feature_survey.py`, result in `logs/feature-survey.md`):
    199 parts, 196 with a feature stream, saved by versions 7000 to 18000 (71 don't say).
    339 object classes. Sketch classes are in nearly every part; then extrude, fillet,
    revolve, cut, chamfer, mirror, linear and circular patterns, threads, sweep, sheet metal,
    weldments, imported bodies.
11. **Feature type names are localised.** KeyWords gives `Бобышка-Вытянуть` (Russian) and
    `Boss.-Extru.` (French) for Boss-Extrude, and the standard planes are named in the user's
    language too. So the converter must go by the object class (`moExtrusion_c` …), never by
    these names, and must not find the standard planes by their English names.
12. **Object numbering, newer files: solved.** A 2015+ feature stream starts with a u32,
    the number it carries on from, then a u16. The first new class takes that number itself
    (not the next one), its object the next; each `0x8000 | class number` tag takes one more.
    Classes numbered below the start were written in other sections (e.g. `moNodeName_c`).
    Calibrated on the plane objects, whose tag must equal `moRefPlane_c`'s number: exact on
    the mould part (0xA5), Part N (0xBF) and Part L. Mistakes on the way:
    numbering from start+1 (one too high, so every later tag of the stream's own classes was
    missed); reading the plane's second word (`05 80`, a field) as its tag.
    Now `sw2sc/archive.py`, tested in `tests/test_archive.py`.
13. **Checked on all sets** (`tools/archive_check.py`): in files with the header, 133 of 163
    parts have every named object's tag pointing at a known class; 66 tags off in all, likely
    data that looks like a tag. In 2007-era files (no header), 11 of 33.
14. **Old files share the numbering with `Contents/Config-0`:** the field after each folder's
    tag is exactly Config-0's number for `moNodeName_c` (68 in PCB_v1, 70 in PET_tape_v1). So
    the feature stream carries on from Config-0, but where it starts isn't Config-0's last
    number as counted (PCB_v1 needs 184; Config-0 counts to 161). Picking the start that lines
    up the most tags gave 172: **wrong**. False tags inside unknown data throw counts off, so
    the old start needs the same exact understanding as the new one.
15. **The sketch plane is not referred to by the plane object's number:** with exact numbers
    (mould part: Front 0xA6, Top 0xAA, Right 0xAD) none of them appears anywhere in the stream
    as a plain reference. A sketch must name its plane another way (feature id, or data kept
    in another section). Next to look at.
16. **The save stamp.** The 4-byte value in the first plane record is also in the file header
    and the version history: a save time, not a plane.
17. **Found by searching world coordinates.** PCB_v1's corner (±0.05, 0, ±0.05) turned up in
    the sketch's dimension record, which starts with the plane normal ((0,1,0) for Top, (0,0,−1)
    for Front). Then a search of every section for a 3 × 3 rotation of 0/±1 found one just
    before each extrude, inside `moSketchChain_c`.
18. **Sketch plane: solved.** The sketch chain's plane record has the plane's feature id (3 for
    Top in PCB_v1, 4 for Right in the shaft) and the sketch's rotation. Over all three sets:
    Front Plane ×26 (no rotation: identity), Top Plane ×13, `Top` ×1 (Valve Lid), Right Plane ×5,
    each with the matching rotation; 46 sketches with id −1 still have a rotation (face or added
    planes). Plane ids aren't always 2/3/4 (Bearing, Valve Lid differ), so they're resolved
    through each plane's own id record, never assumed.
    **Not yet covered:** sketches whose chain my pattern didn't match (fewer sketches matched
    than there are sketches), and the offset of sketches on offset planes (zero so far).
19. **Covering every sketch (2015+ files).** My first pattern only looked within 600 bytes of
    the text `moSketchChain_c`, which appears once per file (later chains are numbered tags), so
    most sketches were missed. With the reader's numbering, the plane record turns out to be a
    `moCompRefPlane_c` object (the `XX 80 02 00` I keyed on is its class tag). The newer
    layout has 16 × FF and 20 zero bytes between the 41 zeros and the plane id. Mistake on the
    way: reading the id 3 bytes early (ids like 0x04000000); it starts where the zero run ends.
    Result over 163 files with the header: Front Plane ×34 (no rotation), Top Plane ×8 and
    Right Plane ×5 (rotations right), Plane1–Plane4 ×12 (added planes, with rotations), id −1
    ×99 (a plane object follows the id: `BF 80` = `moRefPlane_c` in Part N).
    **Open:** 645 sketches with no `moCompRefPlane_c` found between them and the next feature;
    2 Right Plane sketches without a rotation; id 18000 in 57 sketches (Push Button parts).
20. **The 645 was mostly noise.** Counting only `moProfileFeature_c` records followed by their
    name (a real sketch; the rest are tag-like bytes inside compressed data, e.g. 21 "sketches"
    in the one-sketch mould part): 308 sketches in the 2015+ files, plane record found for 232,
    **76 without**. Of the 232: 95 have id −1 with the plane as a following object (added plane
    or face, still to read), 57 have id 18000 (Push Button parts, unexplained), and the rest
    name Front/Top/Right/Plane1–4 with matching rotations.
21. **Sketches on faces and added planes (id −1).** The −1 is followed by a plane object of
    its own (`moRefPlane_c`, often unnamed) and then its definition: `moFaceRefPlnData_c` (on
    a face: origin, face normal, a flag byte, then the sketch's x, y and z axes, then the plane
    offset and the face's extents; e.g. Part N, origin (0.103, 0, 0)),
    `moFixedRefPlnData_c`, `moAbsoluteRefPlnData_c`, `moFacePtRefPlnData_c`,
    `moDefaultRefPlnData_c` (the standard planes). Mistake on the way: finding these by class
    name, which is written once per file; they're found through the numbering.
22. **Every plane object stores its frame**, the 3 axes as 9 doubles, about 320–400 bytes after
    its name (the gap varies). Checked: Top Plane ×64 and Right Plane ×64 give exactly the
    Top/Right rotations. A plane square to the model (Front Plane ×72, 99 named and 53 unnamed
    planes) stores no frame: its axes are the model's. **Open:** where a plane stores its
    position (an offset plane parallel to Front still has to say how far out it is); 40 plane
    objects with no name nearby; the 76 sketches without a plane record; id 18000; the
    2007-era numbering.
23. **Plane position.** Each plane object's frame is a full transform: the 3 axes (9 doubles),
    then a translation (3 doubles), then a scale (1.0). Top and Right planes: translation 0.
    Part L: Plane1 (0, 0, −0.0467), Plane2 (0, 0, 0.0512). KeyWords lists these
    planes without dimensions (they're defined by references), so there's no stated distance to
    compare with. KeyWords does give each feature's id (Plane1 = 39), another way to resolve
    plane ids that doesn't depend on language.
24. **Checking placements against the solid: inconclusive.** Mapping each sketch's points to
    3D and counting how many land on a vertex of the part: most sketches land on none, even plain
    Front Plane ones where the placement can't be wrong. Sketch points often aren't vertices
    (circles, fillets, construction points). A better check is whether the points lie on the
    solid's faces or edges, not on its corners.
25. **A placement check that discriminates.** Place each sketch's points in 3D by the plane
    read from the file and count those lying on a plane face of the finished solid; control:
    the same points under the Front/Top/Right placements. Read placements fit (≥ 90 %) for
    ~80 sketches in 2015+ files. Weaknesses found: turned parts can't tell Front from Right
    (surfaces of revolution), so only plane faces are scored; faces through the origin make a
    standard placement "fit" by chance; later features change the solid.
26. **Id 18000 is a version stamp.** 2018 files (version 18000) write 0x4650 in many records
    (version-15000 files write 15000, `98 3A`); in plane records it comes just before the id.
    Skipping it gives real ids (2, 3, 26 …). Those files are also Russian (Спереди, Сверху,
    Справа for Front, Top, Right): plane names can never be used.
27. **When a sketch's plane record has no rotation, the plane's own frame applies** (looked up by
    id, or the plane object right after a −1). Assuming Front there was wrong in 19 sketches.
28. **Which plane record belongs to which sketch: not settled.** The sketch doesn't refer to it
    by number. Scored against each sketch's dimension record (which starts with the plane
    normal): "nearest plane record before the sketch" agrees 88, disagrees 25; "first after"
    79/69; "last after" 71/77. My earlier claim "the record before the sketch is always id 2
    and isn't its plane" was wrong: in 2015+ files it is the sketch's plane (it was 2 in
    PCB_v1 by chance; old files still need checking). Of the 25 disagreements, some are my
    check picking a wrong vector (tilted "normals"), about 15 read Top/Right where the
    dimension says Front, cause unknown. A rule picked by order isn't understanding: the
    record layout around a sketch needs reading properly.
29. **Plane record layout around a sketch (2015+).** In dyn_d52h27mm, Sketch1's records end
    with its region; then a plane-reference object (plane id 3, stamp, the Top rotation, scale
    1.0); then, with nothing between, the Sketch2 object. A plane reference whose record runs
    straight into a sketch agrees with the dimension normal **68 of 73** times. But 109 sketches
    have none there: what precedes them is the end of the previous feature (`moFromEndSpec_c`,
    dimension handles …). Tried for those, all **wrong or a coin toss**: a 2-byte
    back-reference right before the sketch (not object numbers); the plane reference's or
    plane object's number inside the sketch record (absent); "the plane reference before the
    sketch's feature" (24 agree / 21 disagree); "first plane reference after" (44 / 50).
30. **Dimension records hold world coordinates too.** In PCB_v1 the sketch's corners appear in
    `moSkDimHandleValG2_c` both in sketch coordinates and in world coordinates
    ((−0.05, 0, 0.05) …). Pairs of sketch point ↔ world point fix a sketch's placement exactly
    (rotation and offset) from the file's own data. Covers sketches with dimensions (188 of 308
    in the 2015+ set); next to build and check. (For Front Plane sketches the two coincide, so
    the mould part can't show it.)
31. **Placement from dimension records: partial.** Matching triangles of dimension world points
    to sketch points places only 9 sketches (most dimensions store just 2 anchor points). With 2
    points plus the plane normal at the start of the dimension record: 78 placements (2015+
    files). Where a plane record also exists, they agree 35 times and differ twice. For sketches
    with no plane record it adds 41, of which only 16 sit on the solid (≥ 90 % of points on its
    plane faces). A cross-check, not the answer: the 2-point match is ambiguous (several pairs
    share a length) and some "normals" read are other vectors.
    **State of sketch planes (2015+):** plane record right before the sketch: 68/73 right.
    The other ~109 sketches: not found yet. 2007-era files: numbering start still open.
32. **The converter path exists** (`sw2sc/features.py`, `tools/feature_check.py`): read the tree,
    write SolidCraft sketch + extrude features, rebuild with `solidcraft-cli eval` and compare
    volume, area and bounding box with the part converted as an imported solid (0.1 %). What
    the file leaves open (extrude direction, which of two plane references) is settled by
    trying the candidates the file gives and keeping the one that matches.
33. **Sketch curves.** Each point's handle list says which curves it is on; the class tag says
    line or arc. Arc centres: SolidWorks numbers an arc's points start, end, centre, so the
    centre is the next point id on no curve (equal distance to both ends); a circle is one point
    then its centre. Taking "the first equidistant point" was **wrong** (picked the wrong corner
    in Part K). Profiles: closed loops, nested ones are holes; arcs drawn the
    short way round (the file's end order isn't decoded yet). Points come in two layouts
    (`F0 3F 1E 00`, and 2015+ with 8 zero bytes before `1E 00`).
34. **Planes.** Every feature is preceded by the plane reference of the sketch it uses. In 2015+
    files the reference right before a sketch is its plane; in older files that one says Front
    regardless and the real one is the feature's. Faces: `moFaceRefPlnData_c` (origin, face
    normal, axes); the sketch faces out of the face (y = normal × x); taking the stored y was
    **wrong** (mirrored). Plane candidates are kept in order and the rebuild picks.
35. **Depth.** A dimension's value follows its name, 8 flag bytes, `FF FF FF FF` + 4 zeros,
    (2015+) an empty text field and 2 zero bytes. From the length parameter, else the distance
    dimension. Fixed offsets (+32, +38) were right only in one version.
36. **Imported bodies** (`moBaseBody_c`, `moRefSurface_c`): 72 parts have no feature tree in
    SolidWorks either; they convert as an import of the body, which is what sw2sc already did.
37. **Pre-2015 numbering: solved.** Anchor: the Top and Right planes are tagged with
    `moRefPlane_c`'s number. Two fixes needed: the old header is 2 bytes, not 6 (the first class
    was being skipped); and only classes of `Contents/Config-0` count as objects from outside the
    stream. Stray tag-like bytes still make the count drift, so it re-synchronises at anchors
    (named objects, curve handles, component references), matching only a class of the right
    kind; "nearest class" alone picked wrong classes.
38. **Status:** 84 of 199 parts convert faithfully: 12 rebuilt from their feature tree and
    matching the solid, 72 imported bodies. 8 rebuild but don't match; 104 have features or
    cases not decoded yet; 3 can't be numbered.
39. **0.13.0** puts the tree into the converter: a part is written as its sketches and extrudes
    when every feature is decoded and the rebuild matches its solid; otherwise it keeps the
    imported solid and the metadata lists the tree with TBD features. Every named record that
    isn't a folder, parameter, dimension, handle or helper is a feature, so fillets, chamfers,
    mirrors and moves now show as TBD instead of being skipped (they were silently missing
    before, which made some rebuilds "fail" for no visible reason).
40. **Extrudes with no distance** are tried as through all (SolidCraft `through_all`); the
    rebuild check rejects it when the end condition was something else.
41. **Plane references and face planes by their shape**, for files where the numbering drifts:
    a plane reference is tag, sub-tag, `02 00`, 40+ zero bytes; a face plane is origin, unit
    normal, a flag byte, three perpendicular unit axes.
42. **Fillet edges are named, not positioned.** A fillet's `moEdgeRef_c` is followed by face
    names, `moFromSktEntSurfIdRep_c` = (class tag, …, u32 feature id, u32 stamp, u32 sketch
    entity number): "the face made from entity N of feature F"; `moEndFaceSurfIdRep_c` an
    extrude's end face; an edge is two such faces. SolidCraft picks fillet edges by a point on
    each edge, so converting a fillet means computing those faces from the decoded sketch and
    extrude and the point where they meet. Radius: the fillet's length parameter. Not done yet.
43. **Sketch dimensions (started).** A dimension record (`sgPntPntDist`, `sgCircleDim`,
    `sgSkOffsetDim` …) embeds its parameter (name `D1`…, value in metres, read as other
    parameters) and is followed by handles naming what it measures (`<class tag> <u16 id>
    FF FF FF FF 00 00 00 00`, point or curve). Each dimension can be written twice, an earlier
    state then the current one; the last record per name matches KeyWords. Written as SolidCraft
    driving dimensions with a model parameter `Sketch2_D1`; a dimension is left out when its value
    doesn't match a reading of what it names. Part K: the R3 corner radius comes
    through; D1 (50) joins the rectangle's virtual sharp corners, points on no curve, which only
    mean something once relations tie them to the lines; D2's point pair doesn't measure 150
    (its reference isn't understood); D4 is an offset (no SolidCraft equivalent).
44. **Sketch relations (not decoded yet).** Records with the point header but no coordinates:
    after `80 BF` a type byte (1, 4, 5, 6 seen) and pairs of u16 references, e.g. type 6
    (13, 10), (12, 15), (16, 7), (9, 6). The references are not point ids (type 6 would pair
    points level and not level, and names a point the sketch hasn't got): they use their own
    numbering of sketch entities. Needs sketches with known relations to pin down.
45. **Segment records.** The sketch's records without coordinates (same header as points) are
    its segments: id = curve id + 1, then after `F0 3F` the start and end point (point id − 1)
    and a flag (1 normal, 0 construction). PCB_v1's two extra lines are a centre rectangle's
    construction diagonals. (Not used yet for arc direction.)
46. **Handles name points by id − 1.** In dimensions and relations a point handle's id is the
    point's id − 1 (segments too). That made Plate Sand's D2 readable: points 4 and 2, 150 apart.
47. **Relations: decoded.** After the dimensions, a list of records: u32 type, u32 2, 2 or 4 zero
    bytes (newer files: 2), `FE FF 00 00`, then handles in groups ending with `FFFF FFFF`. Types,
    from how often each property holds over all sample sketches (noise is from imperfect reads):
    4 horizontal (96 %), 5 vertical (95 %), 6 tangent, 7 parallel, 8 perpendicular, 9 coincident /
    point on curve, 11 symmetric, 12 midpoint / point on curve, 13 point at two lines'
    intersection (virtual sharp), 14 and 57 equal, 27 collinear (89 %), 28 concentric, 25 / 26
    points level or plumb. A relation is written only if all it names resolves and it holds in
    the decoded sketch. Unresolved points are mostly projected model geometry (`sgExtEnt_c`,
    `moTempAxisRef_w`, `moCompVertex_c`): no coordinates of their own.
    Mistakes on the way: "the relation records are the coordinate-less records" (those are the
    segments); point handle = point id (it's id − 1); reading a dimension's handles up to the
    next dimension (it swallowed the relation list).
48. **Stale dimensions.** A dimension can be stored as an earlier and a current record; some
    sketches keep a stray one (2MM Pin: 6.76 mm, while KeyWords lists no sketch dimension). Only
    dimensions KeyWords lists for the sketch are used.
49. **User check of Plate Sand (0.14): the sketch floated and the offset was lost.** Opened in
    SolidCraft, the rectangle could be dragged off the origin, and the outer loop, a 3 mm Offset
    Entities of the inner one in SolidWorks, was held only at the corners (the R3) and not all
    the way round. Two causes:
    - The rectangle is a centre rectangle: two construction diagonals with the origin on both
      (relations type 9, handles `line 5`, `line 6`). Construction lines weren't read, so those
      relations were dropped. Their ends are virtual sharps with no handles, so the points never
      name them.
    - The offset is the dimension `sgSkOffsetDim` D4 and holds the outer loop on its own: no
      relation names any outer curve except an equal length. SolidCraft has no offset
      constraint.
50. **Segment records, 2015+ layout.** `u32 curve id`, `FF FF 1F 00 03`, …, `F0 3F`, 8 zero bytes,
    u16 start, u16 end (point id − 1), u16 flag (1 normal, 0 construction). Plate Sand: lines
    first (inner 1–4 match their handle ids, 5 and 6 are the diagonals, flag 0), then the arcs
    (start, end). The offset loop's records carry curve ids that don't match the handles
    (record 7 holds line handle 0's ends).
    **Dead end:** taking this as the layout of every file. Over the samples (2,256 records naming
    a line already read) "point id − 1" holds for 469 and "position in the point list" for 513;
    older files (idler_single, spring_holder) fit neither, and reading them that way marked
    every line of spring_holder as construction and gave idler_single a made-up revolve axis.
    Now a sketch's records are used only when at least half of its normal records (and at
    least two) give the ends of a line or arc already read; otherwise the sketch keeps what its
    points say. Older files' numbering still to find.
51. **Offset written out as constraints.** The offset loop is the loop holding a curve no
    relation or dimension names; each of its lines gets `parallel` to the line D4 away plus
    `point_line_distance` driven by the parameter `Sketch2_D4`; each arc `concentric` with the
    arc D4 larger or smaller, and `tangent` to the offset lines it meets smoothly. Plate Sand's
    sketch now solves with 0 degrees of freedom (`sketch.inspect` headless), and D4 = 5 grows
    the part to ±80 × ±30 about the origin, as SolidWorks would.
    Mistake on the way: taking only the unnamed curves as the offset (the outer top line has an
    equal relation, so it was left loose); the whole loop is.
52. **Careful with the SolidCraft tools:** with the app running they drive the user's open window,
    not a headless session. Checks of converted designs go through `solidcraft-cli run` with a
    `sketch.inspect` script instead.
53. **Offsets as SolidCraft's own offset (user request).** "Instead of doing 4 dims it would be an
    offset." SolidCraft has an associative offset (`sketch.offset`): an offset chain stored with
    the sketch (sources, outputs, signed distance, a topology of line and arc roles) and one
    `offset_distance` dimension. Its stored form is SolidCraft's own, so sw2sc doesn't write it:
    the design is built with the 0.15.0 constraints, then solidcraft-cli deletes the offset loop
    and offsets its partner loop with the SolidWorks parameter. The outputs are matched to the
    SolidWorks curves by shape (ends, centre, radius), the extrude's profile is renamed to them,
    and the result must still match the solid.
    Trap: which sign is outward depends on the loop's direction, and the `side` point didn't pick
    it as expected (with `side` the offset went inward: R3 corners shrink to nothing, marked
    "retired"). Now the offset is made without `side`, then with `flip`, and kept only when its
    curves are SolidWorks'.
54. **Fillets: what the file says.** A fillet (`Fillet_c`) holds its radius (first
    `moLengthParameter_c`) and its selected edges, each as four face references: the two faces
    meeting at the edge, then the two at its ends (`S S E E` for an edge between two sides,
    `E S S S` / `S E S S` for an edge along a side). A face reference: class tag, 2 zero bytes,
    a feature reference (tag, 2 bytes, u32 feature id, u32 save stamp), then the sketch
    entity's number for a swept face, or 0 / 1 for an end face. Feature ids: the u16 8 bytes
    after a feature's name (Boss-Extrude4 = 0x6a). A fillet's own faces are named by its id and
    a running number (`moFilletSurfIdRep_c`: PartT8's Fillet1 made 60 faces, one per edge).
    The selection ends at the first record after it that isn't a face reference; the result
    (`moCompEdge_c` …) follows, and its records can be numbered elsewhere in the file (idler arm:
    stopping at `moCompEdge_c` by name read 85 "edges", 30 are real).
    End faces vs swept faces: by class name where the stream defines it
    (`moEndFaceSurfIdRep_c`), else the tag whose references are all 0 or 1. **Dead end:** "an
    end face is followed by a small u32" (PartT8's end faces are followed by 100000).
55. **SolidCraft names edges the same way.** `model.edges` gives every edge a persistent name:
    `F5:side:l3|F5:top`, `F5:side:l1|F5:start`, a split face `F2:side:l8#[F2:side:l25,F2:side:l7]`,
    a fillet's face `F3:blend(F2:side:l1|F2:side:l4)`. A fillet feature stores its edges as
    points plus these names. So a SolidWorks fillet becomes a SolidCraft one by matching names,
    once two things are known: which of our curves a SolidWorks entity number is (the sketch's
    own numbering, decoded only in some files) and which end face is start or top.
56. **Solving the matching (sw2sc/fillets.py).** A constraint search over SolidWorks faces ->
    SolidCraft faces: every selected edge must be an edge of the body as rebuilt up to the
    fillet; the faces at an edge's ends must touch its faces in SolidCraft too; smooth edges (an
    arc running on from a line) are never candidates; an entity means the same curve in every
    fillet, so later fillets prune earlier choices. Mistakes on the way:
    - one assignment per edge set (entities 16/15 swapped reach the same corner edges; which
      one survived depended on Python's hash order, and the next fillet needed the other);
    - one entity per curve (SolidWorks drew PartT8's long sides as separate collinear lines
      where the sketch as read has one: a curve in n pieces can be up to n entities);
    - exhaustive search: from scratch it ran out of any budget; restarting from each placement
      of the most constrained edge, each on its own budget, finds PartT8's 60 edges in 4 s.
    The reference solid of some parts imports as open faces (volume 0); the rebuild check then
    compares area and box only, the rebuild itself must be a solid.
57. **Where fillets stand.** 28 of the 59 fillets in the samples are read (the rest: older
    files whose selections aren't found this way). Four parts become fully decoded; none
    matches yet:
    - idler_differential_arm (both): Fillet2's three corners resolve; Fillet1 (R1 round the
      whole outline) is refused by SolidCraft: "not supported yet: the fillet is larger than the
      faces beside its edges allow … the largest radius that fits is 0.052 mm", at a small arc
      near the origin. A SolidCraft limit, not the file.
    - PartT8: all 60 edges placed; the rebuild is 0.45 % off in area. It matches (0.015 %) only
      if the inner cut-out's 12 edges are rounded too, but Fillet1 made 60 faces, so they
      aren't in its selection. Not explained yet.
    - AMAZIN USB: its "Text" sketch rebuilds a different cut (area 7311 vs 8202 before the
      fillet). Real sketch text (`sgTextHandle`) now marks a sketch TBD.
58. **88 fillets were never seen: KeyWords recovery.** Comparing KeyWords' feature list with the
    features read: 88 fillets (and chamfers, splits, moves …) are missing in the samples, e.g.
    PartT8's Fillet2 and the USB part's Fillet2. Their records carry a class tag the record
    numbering doesn't know (PartT8: Fillet2 tagged 0x85a8, while the count makes Fillet_c class
    717, 0x82cc; objects the count doesn't see). A feature KeyWords lists and the records miss
    is now found by its name (`<class tag> <node tag> FF FE FF` length, UTF-16), its class from
    its KeyWords type (as found features of the same file have it, else a table with the
    localized names seen). For such a feature nothing nearby can be found by class: its radius
    is its parameter D1, found by name, and its edge count comes from its own face list.
59. **A fillet's edge count is its own face count.** It lists its faces first, numbered 1…N, one
    per edge (PartT8 Fillet1 60, Fillet2 12, idler Fillet2 3, USB 1): the selection is the first
    4N references to other features. Traps: those references have two non-zero bytes where a
    selected face's have `00 00`; the list's header overlaps its first entry (matched whole, the
    first face went missing). Read at every occurrence of the feature's id instead.
    Base_loadCell's Fillet2: 4 edges (was 8 by the record rule).
60. **First part with fillets rebuilt from its tree: PartT8** (griper robot). Sketch, extrude,
    Fillet1 (60 edges, R0.15, all round the outline), Fillet2 (12 edges: the cut-out's and both
    holes' top and bottom edges); matches the solid, 14 s. Earlier its 0.45 % area gap was
    Fillet2 missing, not a wrong edge.
61. **Chamfers.** `Chamfer_c` is stored like a fillet: its own face list, then the selected edges
    as four face references each. D1 is the distance, D2 the angle (an angle parameter, radians:
    45 or 70 degrees in the samples) or a second distance. SolidCraft's chamfer takes the same:
    `distance`, `angle` or `distance2`, and `flip` for which face the distance runs along
    (tried both ways when the two sides differ). The angle reads 45.0000000000001: rounded to a
    millionth of a degree, else every 45-degree chamfer was tried both ways.
62. **SolidCraft's end faces are start, top or bottom.** A boss extruded the other way ends in
    `F2:bottom`; a pocket's floor is `F6:bottom`. The name parser knew only start and top, so the
    belt support rim's chamfer (on the pockets' floor edges) found no edges.
63. **Building in order beats every combination.** With 5 extrudes the direction search has 243
    combinations, over the 120-try cap, more with chamfers in between. Parts with fillets or
    chamfers are now built feature by feature: an extrude keeps only the directions that change
    the solid so far (a way that does nothing isn't how SolidWorks built it; two ways giving the
    same solid count once), a fillet or chamfer each edge set that fits.
64. **Drifted handle tags.** In the rim's Sketch6 the circles' handle class is brought in inline
    (`FF FF … sgArcHandle`) by the first circle point, and the other three points use tag 0x846f,
    which the record numbering gives no class. A tag a sketch uses right after a handle class is
    brought in inline is that class (learned per sketch, used for its dimensions and relations
    too). Then the circles' centres: they're the centre rectangle's corners, numbered before the
    circles' points, so "the next point on no curve" found none; now the nearest point on no
    curve when there's none after. Top_beltSupportRim: 11 features with its 70-degree chamfer,
    rebuilt and matching.
65. **Hole Wizard (`moHoleWzd_c`).** SolidCraft already has the feature (`solid.hole`: simple,
    drilled with a tip angle, counterbore, countersink, cosmetic thread, drilled at a sketch's
    points), so no SolidCraft change is needed. The SolidWorks record is tiny; its placement
    sketch (the points) and profile sketch follow it, then the hole's data: named parameters in
    the D1 layout, "Hole Dia." / "Thru Hole Dia.", "Hole Depth", "C'Sink Dia.", "C'Sink Angle",
    "C'Bore Dia.", "Drill Angle", "Head Clearance", the standard ("ANSI Metric") and a size table.
    Trap: an apostrophe in "C'Sink" (a name filter without it found no countersink). Written as
    a SolidCraft hole at the placement sketch's points, which move before it; the profile sketch
    is absorbed. Blind or through all, and the drilling side, are tried in the in-order build.
    French holes ("Fraisage pour vis à tête fraisée M8") use localized parameter names: not yet.
66. **A placement sketch's plane comes after its points**: `moCompRefPlane_c`, then the plane
    object (`moRefPlane_c`, its frame) or the face (`moFaceRefPlnData_c`). Read when no plane
    reference precedes the sketch.
67. **KeyWords lists extrudes and holes under their own elements** (`<Extrusion>`, `<HoleWizard>`,
    `<Cut>`), not `<Feature>`: recovery looked at `<Feature>` only. spring_base_v1 was missing 6
    of its 10 features. Extrusion types (Boss-Extrude, Cut-Extrude and localized) say boss or
    cut; 399 of 559 have no type: then the class of a found feature with the same class tag,
    then the name. A feature read as a cut that KeyWords types Boss-Extrude is a boss (the
    drift gave spring_base's Boss-Extrude2 the cut's class). Recovered features other than
    fillets used the record index (None) and crashed the reader on six files: they now take
    the nearest record before them.
68. **Pruning by the part's box.** The in-order build of spring_base (7 extrudes, 2 holes, a
    fillet) ran past 10 minutes. A partial build outside the part's own box can't become the
    part (later cuts, holes, fillets don't grow it; later bosses only add), so it is dropped.
69. **Open: faces SolidWorks merged.** spring_base's Fillet1 names 24 vertical edges as
    Boss-Extrude1's side faces, eight running up to Boss-Extrude3's top: SolidWorks merges a
    later boss's coplanar side face into the earlier one and keeps its name. SolidCraft names
    faces by the feature that made them, so those edges don't match. Needs a rule for merged
    faces.
70. **Boss or cut, when the class tag drifts.** finger_aperture's Boss-Extrude2 reads as a cut,
    KeyWords gives no type, and the solid says it adds material. Names can be changed, so a
    default name that says the other kind (Boss…, Cut…) doesn't decide: the in-order build tries
    both, and the solid does.
71. **`moCut_c` is a cut-extrude** (KeyWords lists it as `<Cut>`): read like `moICE_c`.
72. **Circles under a tag of no known class.** Top_modular_aperture's Sketch6 (four circles on a
    centre rectangle's corners) uses handle tag 0x8281, brought in inline in another sketch. A
    handle tag of no known class whose every curve names one point only is a circle's (a line or
    an arc has two ends).
73. **A hole's sketch id must follow the remap** when the rebuilt features join the converted
    part (`points.sketch`), as an extrude's `sketch` does: otherwise the final design drilled at
    the wrong sketch and the part fell back to its solid after its rebuild had matched.
74. **First Hole Wizard part: Top_modular_aperture_v2** (boss, R10 corner fillet, cut, four M3
    countersinks, a moCut_c through cut): 9 features, matching its solid.
75. **The "SolidCraft fillet limit" was mine.** Before writing a SolidCraft fix for the idler
    arms' refused R1 fillet, a check of the failure point (0.115, 1.156): it sits where the
    decoded outline arc dips to y = 1.154, 0.1 mm from the hole's edge (r 1.05). Rays fired down
    at x = 0 through SolidWorks' own solid find material from y 1.1 up to between 2.5 and 3.5;
    through the decoded one, only to 1.15. The arc (+-2.236, 2) bulges the other way: its centre
    is (0, -0.534), the mirror across the chord of the point taken, (0, 4.534); no point record
    sits at the true centre. SolidCraft was right to refuse the fillet: no PR. Lesson: check a
    "kernel limit" against the reference geometry before blaming the kernel.
76. **The arc, fixed as a choice.** An arc no line meets tangentially gets its centre's mirror
    across the chord as an alternative; the rebuild search tries it (the turned sketch is a copy,
    so its dimension parameters must be copied back, else `Sketch1_D1` went missing). With it the
    idler arm's outline matches SolidWorks' solid where the rays looked.
77. **Collinear SolidWorks faces, one SolidCraft face.** Fillet1 names 12 outline faces; the sketch
    as read has 11 curves: SolidWorks drew one side as two collinear lines (entities 22 and 23).
    An entity may share its curve with a neighbour SolidWorks says it borders, and its edges are
    then the same SolidCraft edges (written once). The mirror case of PartT8's split faces.
78. **Now a real SolidCraft limit, checked.** With those, the idler arm's Fillet1 (R1 round the
    outline) is refused along the V's lower edge: "the largest radius that fits is 0.851 mm". The
    wall between that edge and the hole is 0.85 mm (hole's edge confirmed by rays through
    SolidWorks' solid); SolidWorks lets the round run over onto the hole's face. Upstream SolidCraft
    has fillet overflow fixes not in the installed 0.44.1 (#18468 "a large round that runs off the
    flat face beside its edge builds again", #19262, #18659 in 0.45.0-rc.2, #16654 in rc.4).
    To be retried against the newest SolidCraft before any PR is considered.
79. **Localized hole parameters.** French Hole Wizard names ("Diamètre du perçage", "Profondeur
    du perçage", "… jusqu'au prochain", "Diamètre/Angle du fraisage entrant", "Angle de pointe")
    and English "Near C'Sink Dia./Angle" (arm_idler_v2, read as a plain hole before). Names run
    past 32 characters. Desk-29_104 (French): 12 features with two M8 countersinks, rebuilt and
    matching.
80. **Sketches from KeyWords too** (`<Sketch … Dissectable="true">`, not the origin):
    FrameBracket_v2 read 18 features and no sketch at all.
81. **Plane references in files with many classes.** `_plane_record` wanted its sub-record's tag
    to end in 0x80: true only while class numbers stay under 256. Any tag with the high bit set
    is one. FrameBracket: 20 of 26 sketch planes read (0 before).
82. **Unused sketches don't block a part.** A sketch no feature uses whose plane isn't read stays
    in the tree as TBD and isn't written. Extrudes don't name their sketch in their record (no
    feature reference to it), so "the sketch before it" stays the rule.
83. **A time budget per part** (4 minutes) for the rebuild search: past it the part keeps its
    solid. The collinear-face rule had sent one idler conversion past 9 minutes.
84. **Volume bounds in the in-order build.** From a partial build, the bosses still to come add at
    most their profile's area times their depth (arcs counted as full half-discs, circles whole,
    5 % over); cuts, holes, chamfers and fillets only take material away. A partial build that
    can't reach the part's volume either way is dropped. Top_mainplate's search finished in 74 s
    (it ran past 8 minutes); still no match, so something in it is misread, not missed.
85. **Upstream SolidCraft built** (C:\dev\solidcraft-upstream, a worktree of the user's checkout
    at origin/main 906b5e864, 0.45.0; 18 minutes). The idler arm's Fillet1 is refused there too,
    the same way. But a synthetic copy of the situation (a V edge 0.85 mm from a hole, R1 round
    the whole outline top and bottom, my own polygon) builds on 0.44.1 and 0.45 alike. So no
    clean SolidCraft failure to report: the refusal mentions tangent propagation pulling in a
    chain of edges, which points at the edges sw2sc picked. No PR.
    Upstream changes read for the converter: sketch offset now goes to the side point given
    (#18611, the 0.15.1 workaround tries both sides anyway); design format v63 (sw2sc writes
    v55, which SolidCraft upgrades); extrude profiles with hundreds of curves (#16673, script
    lettering); no change to edge or face names.
86. **Shared centres.** Concentric arcs (PET_tape: two arcs about point 10) and rings (two circles
    about one point, the Push Buttons, GT2 sketches) share their centre point; the reader let a
    point be one curve's centre only. Arcs without a centre: 39 -> 7.
87. **Drifted handle tags, by order.** A class's tag is the object count when it was brought in,
    so the classes a sketch brings in inline take its unknown tags in order (smallest tag the
    earliest class); a point's handle list names curves, never points, so a tag the numbering
    reads as `sgPointHandle` there is unknown too (Boom Cylinder). Dead end on the way: "the
    class brought in most recently" misassigned where a sketch brings in a line and an arc
    (lines with 3 or 4 ends appeared).
88. **A line with one end** (its other end a point not read: projected geometry, mostly
    centrelines) is left out and noted instead of blocking the sketch; an outline that needed
    it doesn't close and the rebuild check rejects the part.
89. **Faces whose axes aren't stored.** Some versions' face record holds the face's origin and
    normal, then a box, not the sketch's axes; and where the numbering drifts, the record isn't
    named (found by shape: the first unit vector after the plane reference). The sketch's x axis
    along each world axis projected onto the face, both ways, are offered as candidate planes
    for the rebuild check. Parts with nothing blocking: 113 -> 141.
90. **Mirrors.** SolidCraft has `solid.mirror` (features replayed on the other side, or bodies;
    plane as origin and axes). A SolidWorks mirror (`moMirrorPattern_c`, `moMirrorSolid_c`) names
    its face like a fillet's edges (`moFaceRef_c`: e.g. Bearing's side face 4 of Boss-Extrude1)
    and sometimes a plane reference. The list of features it mirrors isn't read yet. The in-order
    build tries: planes the record names, then the body's flat faces whose SolidCraft name fits
    the face SolidWorks names, then the other flat faces, then the planes through the origin;
    and what it mirrors: the cuts since the last boss, every feature after the first, the
    feature before it, or the body (joined). Trap: mirroring the body about a middle plane fills
    the cuts back in (Bearing came out as the plain block): a mirror of features is not a mirror
    of the body. Bearing still differs, by its cuts (5400 mm3 removed in SolidWorks, about 2000
    here): a cut's depth or end condition is misread, not the mirror.
91. **Up to a face.** An extrude with no depth in the file was tried as through all only; a boss
    "up to next" ran past the part (Push Button's Boss-Extrude4 to y 17.3 where the part ends at
    11). SolidCraft's extrude takes `to` (a point on a face): the in-order build now also tries
    up to each flat face of the body so far.
92. **Threads.** SolidCraft's `solid.thread` (face, designation, from, length, modeled). A
    SolidWorks Thread (`moSweepThread_c`) record holds only its name; its sizes are KeyWords'
    dimensions for it (`<MOD-DIAM>4` the diameter, then pitch and length; one value only: the
    pitch, the thread running the face's length). Written as a modelled thread "M4x0.7" on a
    cylinder of the body so far whose radius fits (the major diameter outside, about the drill
    inside), from either end. Base.SLDPRT (44 features, six threads) is now fully decoded; its
    search ran out of time.
93. **A crash from the drifted-tag work:** a handle class brought in inline has no tag (Karman_101a,
    FUEL TANK unreadable).
94. **tools/rebuild_triage.py**: for each part fully decoded but not matching, how far the in-order
    build gets, what stops it, and how close the closest complete design comes.
95. **Patterns.** SolidCraft's pattern (`features` replayed; rectangular dir1/count1/spacing1,
    optional second direction; circular origin/axis/count/total angle). A SolidWorks pattern's
    counts and spacings are KeyWords' dimensions (D1 count, D3 spacing or angle, D2/D4 the second
    direction). Directions tried along the world axes; circular axes those of the body's
    cylinders and the world axes; the angle as the total or the step between instances; what it
    repeats as for mirrors. Karman_202a reads fully; no match yet.
96. **Revolve axes.** A revolve was skipped when no free line (centreline) was read. SolidCraft's
    revolve also turns about the sketch's own x or y axis (`sketch_axis`) or a profile line; those
    are tried next. bearing_3x6x2: the first revolve rebuilt from its tree and matching (about the
    sketch's axis, no centreline in the file as read).
97. **Thin extrudes** (`moBossThin_c`, `moCutThin_c`): SolidCraft's extrude has `thin` (curves,
    thickness, side). KeyWords' D1 the depth, D5 the wall; the wall's side is tried.
98. **Transposed plane frames.** spring_base_tab's Right-plane sketch came out mirrored: the frame
    read as a rotation from a plane reference maps the sketch's x onto +z where SolidWorks has
    -z; its transpose is SolidWorks' Right plane exactly (and the Top plane likewise). Matching
    parts so far were symmetric enough not to show it. The transpose is now a later candidate
    after every rotation-read frame (existing matches keep theirs).
99. **Holes drill at the placement sketch's own points**, not at the ends of curves in it; and
    the point records carry a byte after `80 BF` (0 for points SolidWorks adds, 1 or 2 for the
    user's, so far): point sets by that byte are tried. spring_base_tab still takes too much
    per hole (open).
100. **Domes without a SolidCraft change.** SolidCraft has no dome feature, so this looked like the
    SolidCraft PR the user asked for. But SolidCraft makes domes itself as a revolve of an arc (its
    button-head screws, `revolve_domed`), so the converter does the same: on a flat face that is a
    whole disc (radius from its area), a quarter profile (rim, arc of radius (r^2+h^2)/2h to the
    apex, the axis) on a plane through the face's axis, revolved and joined. Checked: a 2 mm dome
    on an r 5 cylinder gives the spherical cap's volume exactly. A native Dome feature (any face
    outline) would set a new file-format shape, which SolidCraft's CONTRIBUTING asks to go to a
    design review first; not opened.

101. Shells (moShell_c): thickness from KeyWords D1, the opened face tried among the body's flat faces (the one fitting SolidWorks' face reference first). Committed untested on a real part; Bucket is the only sample with a shell and also needs mirror-body, combine and linear pattern of bodies. Full check fc-018b still running at stop.

102. Combines of bodies absorbed (the converter joins bodies as it goes; KeyWords' Combine entry carries no operation, so the rebuild's comparison is what catches a subtracting one). Bucket: its record numbering drifts so far that Sketches 2-9 and 11 read only their points (line/arc records come out as unnamed "preN" classes). Those sketches were passing as profiles with nothing in them; a profile (not a hole's placement sketch) with points but no curves is now TBD "sketch curves not read". Front Body: next blocker is Draft1 (3°, faces and neutral plane to be picked in the rebuild; SolidCraft has solid.draft {faces, angle, neutral, pull}).

103. Handle tags learned in one sketch now carry to the sketches after it. Where the numbering drifts, a handle class is brought in inline in the first sketch using it (Bucket: sgLineHandle in Sketch1, used under tag 0x92B7, which the numbering gives sgPointHandle), and later sketches only use the tag. The per-sketch rule learned it in Sketch1 and dropped it; later sketches read points only. Learned tags now also override a wrong class from the numbering. Parts with an unread profile: 32 -> 10 (Bucket all 11 sketches read).
    Dead end: widening archive.records' resync so a shift that lands on another class shifts that class too. It gave Bucket's Sketch9 its planes but pushed sgPointHandle further off (4805 against the true 4791); reverted.

104. A sketch's plane written inside it: shaped references are tried after the named moCompRefPlane_c ones (Bucket's Sketch9 had a named one that doesn't read and a good one by shape, never tried).
105. tools/feature_check.py counted an absorbed feature's reason as a blocker (verify.fully_decoded doesn't), so parts whose only extra features are reference axes, cosmetic threads or combines were reported "not fully decoded" and never rebuilt. Fixed. tools/rebuild_triage.py's step list now has the newer kinds.
106. Fillets and chamfers dragged up the tree: records are in the order features were made, so a fillet moved up keeps its early place but names faces of later features (Bucket's Fillet1 names Shell1 and Boss-Extrude4, Fillet2 Boss-Extrude5 and 6). Such a feature now goes right after the latest feature its edges name. Bucket's rebuild now gets to Boss-Extrude4 (was stopping at Fillet1).
    Dead end: making faces of later features wildcards in the fillet solver (31 candidate edge sets for Fillet1, none rebuilding past the next fillet). Reverted for the reorder.

107. Arc centres on a curve: when no point on no curve fits, a point a line is drawn from (a radius line, a slot's axis) is taken (PartT_7, Rocker Arm). The problem now names the arc's ends. Both decode now; neither matches yet: PartT_7's Sketch1 reads two big "circles" (r 33.4 and 39) that are arcs with one handle point each (the extrude is 32952 mm3 against 6574); Rocker Arm stops at its first cut.

108. Handle classes a sketch brings in inline also take tags the numbering gives a curve class, where that class is one the sketch brings in (the numbering can be off by a class: Boom's line and arc handles came under the point's and the line's numbers, so its 7 "lines" were arcs). Guarded as before: as many tags as classes, a line has two ends. Boom's sketches now read (Sketch1 14 lines, 7 arcs); parts with an unread profile 10 -> 8. The 20 parts that matched in fc-018b all still match.
    Open (F-047): in drifted sketches an arc listing one end point is read as a circle, its centre the next point on no curve, which is wrong there (Boom: r 39.9 against a 0.95 neighbour; PartT_7). No second point lies at those radii, so it isn't a missing end.

109. Circle centres by number: a circle's point and its centre are numbered one after the other, so where the next number is a point on no arc, it is that circle's centre and no other circle's. A circle whose next number is another circle's point takes the nearest point not on an arc. Boom's four pin holes now read r 0.95 (one was r 39.9 and pushed the rest onto wrong centres). The 20 matched parts still match; Boom and PartT_7 still don't.

110. A boss through all (no depth in the file) now also tries a blind extent as far as the body reaches: from its sketch plane to the body's box along the normal, one way, the other or both. SolidCraft's through all, made for cuts, runs past the body when joining (Boom's pin stuck out 1.4 mm each side). Boom with Sketch1's third plane and the transposed frames for Sketches 2 and 3 now rebuilds to 4425.3 mm3 / 4479.0 mm2 against 4414.0 / 4491.5; the full search doesn't yet find a match (the remaining 11 mm3 is earlier than the pin; Fillet1 changes the volume by only 0.6 mm3 along four edges, to be checked).

111. **A hole at a round end (Boom), found by subtracting.** Boom's rebuild was 11.4 mm3 over: a `solid.combine` of the rebuild and the part's own solid, both ways, showed ten small bodies in the two 2 mm end strips, the largest a 1.9 x 1.9 x 1.57 block at the fourth pin hole. The hole sits inside a 2.275 mm round end, and `_loops` measured nests with each arc's **chord**, so the hole fell outside its outline and was extruded as an island (a lump) instead of a hole. Arcs are now sampled every 22.5 degrees along their true sweep (anticlockwise from the end the design writes first, `_arc_ends`). Boom matches: sketch, boss, a 4-edge fillet, a through-all cut both ways, a pin — 4413.955 mm3 / 4491.51 mm2, exactly.
112. **Through-all cuts are one-sided in SolidCraft** (checked on a 20 x 20 x 10 block cut on a plane at z = 5: `positive` leaves z 0..5, `negative` z 5..10, `symmetric` cuts both ways). A SolidWorks cut whose sketch plane lies inside the body therefore needs `symmetric`; a boss too, or its far side sticks out of the part's box. Boom only builds right with boss, cut and pin all `symmetric` (and the pin's span 36 mm, entry 110).
113. **The three parts left open (triage, 150 s each).** *Rocker Arm* stops at its first cut: its Sketch1 reads two big "circles", R16.208 through p8 and R18.434 through p10 — the arm's two end arcs. Their other end has no point record at all (ids 9 and 11 are missing from the sketch), so `centre_for` takes the nearest point on no curve (p19, p20) as the centre and the profile grows two discs; the cut then takes nothing off them. *PartT_7* stops at Fillet1 (its sketch still reads a 33.95 mm disc, F-047). *Bucket* stops at Boss-Extrude4. All three are the same class of gap: a sketch curve whose points aren't all in the stream. The sketch's own region records (which curves make which loop) are the way past it; not decoded yet.
114. **0.17.1** fixes the chord nesting (B-021); README and ISSUES brought up to date (the README had still said 0.10). Boom joins the parts that rebuild from their tree.
115. **The full check after 0.17.1 was too slow to finish.** `tools/feature_check.py` over three folders (61 parts) ran 20 minutes without writing its log; it was stopped. Instead the three parts that matched in 0.17.0 and sit in reachable folders were rechecked (shaft_3x22mm, Top_beltSupportRim_v1, PartT8): all still match; unit tests OK (59 run, 25 skipped). The whole set still needs a full run; `logs/survey-0.17.1.md` says so.
116. **Rocker Arm and PartT_7 are misread deeper than the missing arc ends.** A one-point arc
    whose centre had to be guessed is now marked doubtful and the rebuild may leave it out of
    the profile. Tried, no help: Rocker Arm's boss is 1075.8 mm3 with both big circles left out
    and 14.9 mm3 with one kept, against about 520 mm3 (the bar's own outline is 205 mm2 x 5.25);
    PartT_7's is 387-768 mm3 against 6574. The arcs are only part of it: with the chord fix a
    big one-point circle now often lands *inside* the outline and becomes a hole. Reverted the
    candidate (it multiplies the search and settles nothing) until the sketch's region records,
    which name the curves of each loop, are decoded.
117. **SolidCraft moved on.** The checkout at C:\dev\solidcraft was 2382 commits behind
    origin/main (0.40.1 built); pulled to 9c75b75f0 (the 0.47.0 line, 2026-11-23) and its
    solidcraft-cli built in release. `verify.cli_version` now reads the leading numbers of each
    dotted part, so a nightly `0.47.0-nightly.20261123.157.1` still ranks above 0.44.1 instead
    of failing to parse and being ignored.
118. **Retested on 0.47.0** (C:\dev\solidcraft, built today). Boom still rebuilds and matches
    exactly (4413.954574702776 against 4413.954574702785; the count it needs is still boss, cut
    and pin symmetric with the pin's 36 mm span). PartT8, bearing_3x6x2 and
    Top_modular_aperture_v2 still match. The idler arms are still refused at their R1 outline
    fillet, now "the largest radius that fits is 0.095 mm" (0.851 on 0.45) at (0.115, 1.156):
    upstream's overflow fix (#20757, "a round whose contact crosses a tangent edge partway rolls
    onto the next face") doesn't help because our outline there is what is wrong — the V edge
    runs 0.095 mm from the hole where SolidWorks keeps 0.85 mm (entry 78). Their reference solid
    imports with no volume (open faces), so the rebuild check compares area and box only, and
    the 8:1 search takes over 200 s for this one-sketch part; triage with a 100 s budget reports
    "stops", which is the budget, not the build.
119. **Refreshing SolidCraft** (do this before any result is trusted; it changes daily):
    `cd C:\dev\solidcraft && git fetch origin && git pull --ff-only origin main &&
    cargo build --release -p solidcraft-cli` (17m31s today, on the 0.47.0 line, commit
    9c75b75f0). The converter picks it up by itself: `verify.find_cli()` takes the newest
    version, and `verify.cli_version` now reads a nightly suffix ("0.47.0-nightly.…") instead of
    failing on it and falling back to the installed 0.44.1.
120. **The idler arms: the arc is settled, the fillet is the kernel's.** Built both ways through
    both fillets. With the V arc's centre as stored (0, 4.534, dipping to y 1.1545) Fillet1 is
    refused at (0.144, 1.158): "the largest radius that fits is 0.095 mm" — the arc hugs the
    hole, so that reading is wrong. With the mirrored centre (0, -0.534, the top edge at
    y 2.845) the refusal moves to (-8.281, -0.318, z 2.850) and says "the largest radius that
    fits is 0.906 mm": the right outline, with the wall entry 78 measured (0.85 mm). So the
    converter picks the right arc; SolidWorks' R1 round runs over onto the hole's face and
    0.47.0's overflow fix (#20757) does not roll it over. The kernel's message now names the
    propagation that does it ("tangent propagation blended the picked edges' tangent chain with
    them; with it off, tangent_chain: false, only the picked edges are blended") — worth putting
    in the upstream report for F-017, with this part. The rebuilt bodies are 339.6 mm3 / 510.2
    mm2 (stored centre) and 354.5 / 520.6 (mirrored); the reference imports open (no volume,
    468.1 mm2), so the check there is area and box only and can't confirm either way.
121. **Refreshed again, to 1f8df8628.** Two more commits on main (`1f8df8628`, 0.47.0, edge check
    reads tangent faces' order past their tolerance band). `cargo build --release -p
    solidcraft-cli` took 16m13s; the binary is 10:42, after the commit, so the check below calls
    it current.
122. **A stale kernel can no longer pass as the checkout (B-022).** The check tools took
    whichever CLI they found: `feature_check` had a hardcoded path with an env override, and the
    installed 0.44.1 was read the same way as the 0.47.0 build. `verify.kernel_status` finds the
    checkout (`SOLIDCRAFT_SRC`, the CLI's own `target/release`, or `C:\dev\solidcraft`), reads its
    Cargo.toml version and its HEAD (sha and committer time), and calls the CLI stale when its
    version is older **or** its build time is before that commit — the same version with new
    commits is exactly the case a version alone would miss. `kernel_line` puts it in one line for
    a report. `feature_check` and `rebuild_triage` print it, write it at the top of their report
    and warn on stderr; a conversion records it in the design's metadata (`rebuild_check`) and
    warns. The installed copy demonstrates it: "solidcraft-cli 0.44.1 … STALE: the CLI is 0.44.1,
    the checkout 0.47.0". Version parsing now stops at a suffix, so a nightly compares equal to
    its release and the commit time decides (unit tests in tests/test_kernel.py).
123. **Sketch region records: the files to read them from are gone.** F-047 names PartT_7,
    Rocker Arm and Bucket, all from `Documents\Solidworks Example Grabcad`; that folder is no
    longer on this machine (searched Documents, Downloads, Desktop and OneDrive to depth 7 for
    the three file names). The 55 parts in `samples/slippad-solidworks` carry no record whose
    class name contains "Region" at all — checked in every part's `Config-0-ResolvedFeatures`
    stream — so the record's layout can't be read from what is here. Sketches now keep their
    record range (`Sketch.end`), so the hunt can start at the right bytes the moment the files
    are back. Probes: `out/region_probe.py` (runs of curve ids in a sketch), `out/region_probe2.py`
    (the records inside a sketch, by class).
124. **The full feature check, on 0.47.0 (survey 0.17.2).** 35 parts in samples/slippad-solidworks:
    10 rebuilt and matching, 19 rebuilt without a match, 4 not fully decoded, 2 pre-2015; merged
    report in `logs/feature-check-0.17.2.md`. Against the 0.17.0 report 15 of the 35 differ and
    none went backwards: 11 that stopped on an unread feature now decode and stop at a rebuild
    that doesn't match, 4 now rebuild and match (Top_modular_aperture_v2, arm_idler_v2,
    bearing_3x6x2, idler_single_v2).
125. **A version tie hid which CLI was doing the work.** One process, 55 minutes, and the child
    was `C:\Program Files\SolidCraft\solidcraft-cli.exe`: the app had updated itself to 0.47.0,
    `max(found, key=cli_version)` returned the first of two equal keys, and the installed copy
    came first. `find_cli` now ranks by (version, is a checkout's own build, build time), so the
    checkout build wins a tie; `kernel_status` calls any installed copy stale (it can be any
    build behind the checkout); `feature_check` passes the CLI it reports into `rebuild` instead
    of letting it resolve again, and prints a line per part (it printed nothing until the end,
    which is why the 0.17.1 run was stopped blind). The survey was run as eight copies of the
    folder, one process each: 35 parts in about twenty minutes instead of over an hour.
126. **The Grabcad samples are in the project.** The user gave
    `C:\Solidworks to Solidcraft\Solidworks Example Grabcad` — Rocker Arm and Bucket in
    `cat-wheel-loader-1.snapshot.2`, PartT_7 in `griper-robot-2.snapshot.11` (the Documents copy
    is gone). 42 of the folder's parts carry `moSketchRegion_c`; the 35 slippad parts carry none,
    which is why nothing could be read from them.
127. **`moSketchRegion_c` decoded.** Record, then per curve `<tag> <id> FF FF FF FF 00 00`, the tag
    being the file's own number for `sgLineHandle`/`sgArcHandle` (PartT_7: 32960/32962; Rocker
    Arm: 33376/33388 — it differs per file, so it must be resolved through the class table, not
    hard-coded). PartT_7's region names 22 curves: arcs 0-8 and 13 lines, which is our reading
    plus arc 5 (never read) and minus line 6 (also unread). Kept on `Sketch.region`.
128. **It does not settle F-047, and dropping "arcs" was wrong.** `sgArcHandle` names circles too,
    so a curve with one point and an arc tag is exactly the ambiguous case. I tried treating them
    as arcs and skipping them: 11R22.5's two genuine circles vanished and the part went from a
    rebuild to "not decoded", so that is reverted — the region is recorded, not acted on. Rocker
    Arm and Bucket have **no** region record, but both carry `moSketchChain_c` (Rocker's at 32655):
    a list of ids (~33622, then counts and ids 3,7,4,8,9,10,11,12) in a numbering that doesn't
    match the sketch's curve ids — the next thing to decode. All three parts still rebuild and
    don't match, and the 9-part region check (8 Grabcad parts + PCB_v1) is unchanged by the
    change: PCB_v1 rebuilt, Bearing and Base mismatch, the rest not decoded for their own reasons.
129. **The chain record names points, not curves.** `moSketchChain_c` (196 parts, at the end of
    the sketch) is a `u16` count and then that many `u32` point ids: the points a chain runs
    through, in order, in the sketch's own numbering. Bucket's 12 are its 12 lines' points (8, 7,
    6, 4, 5, 11, 3, 10, 9, 1, 2, 12), spring_holder_v1's 10, PartT_7's 18, 19, 20, 17, Rocker
    Arm's one (5). Kept on `Sketch.chain`. It looked unrelated to the region because the two are
    different lists: the region names curves (0-14 on PartT_7), the chain names points (up to 35).
    **It does not settle F-047.** The ids it names that the reader has no position for — Bucket's 3,
    PartT_7's 18 — have no record of their own in the sketch (`<id> <id> FF FF 1F 00` finds none,
    and no `F0 3F 1E 00` pair), so SolidWorks stores no position for them; Rocker Arm's missing arc
    ends 9 and 11 are absent in every shape. The next lead is not in this record: a one-point
    curve's other end is not in the file to be read, so either the solid or the neighbouring
    curves' tangency has to say which way the arc sweeps.
130. **Survey 0.17.3: reading the chain changes nothing, which is the point.** 35 parts,
    10 rebuilt and matching, 19 without a match, 4 not fully decoded, 2 pre-2015 — the same as
    0.17.2 part for part, so the record is kept at no cost to the rebuild. The signatures are the
    new part of the report: 8 of the 19 name a cause (PET_tape_v1 +31748.8 % and PET_tape_top_v1
    +22955.7 %, idler_single_v1 +12.2 %, idler_differential_baseJoint_v1 -59.3 %,
    spring_base_tab_v1 -7.1 %, finger_aperture_15mm_v4 -0.7 %), the other 11 `no build to
    compare` — `rebuild` spent its budget before a candidate was evaluated, which is where the
    report needs work next, not the reading. Unit tests: 67 run, OK, and no skips for the first
    time — the sample folders are junctions to the project's own, so the worktree sees them.
    `logs/survey-0.17.3.md`, `logs/feature-check-0.17.3.md`.
131. **Why the tests took hours.** Three causes, found with per-test timings and a stack dump
    every 2 minutes: `archive.old_start_number` numbered the whole stream for each of up to 600
    starts (only the stream up to moRefPlane_c's introduction decides the class number: same
    start on all 33 old samples, 3.3 s for all); `verify._search` iterated 3 ** extrudes direction
    sets for sequentially built parts and skipped each (now one set); and the vault tests imported
    whole trees (Slip-Pad's 35 parts, a TreeReleaseTests setup per test: 38 min each) with the
    rebuild search on. They now import with `find_cli` patched to None, which also fixed four
    failures (a time-limited search gave reimports different results, so parts looked changed).
    `test_archive` lacked the sys.path line the other tests have. 80 tests, 94 s, OK.
    Dead end on the way: a first try at the vault-test change ran in the same background command
    as the tests, failed its own assert, and the tests ran on without it.
132. **The importer plugin.** `plugin/` ports the converter to Rust for SolidCraft's importer
    world (wasm32-unknown-unknown, no WASI): containers, records, feature reader, design writer,
    fillet solver, rebuild search (Python generators as a recursive step with a sink), the
    Parasolid body and STEP writer. Checked against the Python at each layer: streams on 225
    files, features on 199 (every field), default designs on 87, rebuilds on 22 (same result and
    design), STEP on 199 (110 identical, 89 differing only in last-digit rounding from the maths
    libraries). SolidCraft's `plugin test` opens 2MM Pin, Axle Rod, shaft_3x22mm and Boom as
    feature trees; Boom's 7 features at 4413.955 mm3.
133. **A user part opened through the plugin came in as its solid; three items listed.** One was an
    unused sketch (absorbed, not a blocker: now `kept` and reported as information). One was a
    scale: its factors are three doubles near the end of its record (1.06 each, a casting
    shrinkage), with no KeyWords dimension; converted, with the origin / centre of mass / box
    middle tried (synthetic L-plate test in Python and Rust: the search finds the centre of mass).
    The third is sketch text: each line is a `moDimText_c` (the words, with `<b>` markup), a
    position and a `utCharFormat_c` (6.5 mm high), no font name (the document's default). The
    letters' outlines aren't stored and SolidCraft would lay out its own, so the rebuild can't be
    matched exactly: kept TBD with that reason. Parity: features 199/0, designs 87/0.
134. **Dev branch work (no version bumps until a release).** A census of the TBDs across the samples
    (35 parts blocked, 89 decoded) and fixes, Python and Rust alike:
    - Imports with features after them: `FeatureBodies/LocalBodies` keeps the body as imported,
      under its feature's name; it is written as SolidCraft's import feature with the tree after
      it. Where the partition holds the part's solid, those local bodies are left out of the
      reference (they were in it). A mirror of another part file (`moMirrorStock_c`) has no tree
      here: it comes in as its solid, reported as such.
    - `…Spec_c` records (an extrude's end conditions) are never features (one read as `D2`).
    - A one-point circle with no centre: a missing point numbered next to it that a coincident
      relation puts on a point read is its centre (a circle centred on the origin).
    - An empty sketch `Sketch3<3>` is SolidWorks' copy for a second feature using Sketch3: the
      feature uses Sketch3.
    - A face record whose z points into the part has its y the other way from the y computed from
      the face normal; some files' sketches use the record's own axes (a user's bracket: its side
      sketches came out mirrored, y -80..0 against 0..80). Both are candidates now, and each
      sketch's planes are ordered by how many of its points fall inside the part's box.
    - The box check excused nothing: an imported blank wider than its part failed every step. It
      is strict on a first pass and, only where that pass found nothing and the box stopped a build
      a later cut could trim, relaxed on a second.
    - **The time budget leaked**: it was checked on entering a step only, so once it ran out every
      loop in progress still evaluated all its remaining options (a user's bracket "loaded" for
      ever in the plugin). Evaluations now return nothing past it (`verify.past_deadline`, Rust
      `Timed`). The plugin also counts evaluations as a second each where its clock reads 0 (no
      clock permission), and shows progress ("Rebuilding the feature tree: N designs tried").
    Results: regression on the 22 earlier matches: 21 match (Boom back; Desk-29_103 matches for the
    first time), PartT_7 still not. Parity: features 199/0; designs 94 with 2 one-line STEP
    differences (a point the two roundings dedupe differently). The bracket still finds no design
    in 240 s: through-all extrudes branch over 16 faces each; reading the end conditions
    (`moEndSpec_c`, drift-tagged after the first) is the next lever.
135. **Parts whose rebuild found no design.** A sample of a user's own models (kept locally, not
    named here): 46 of 200 ended with no design built. Small parts traced one by one:
    - **KeyWords lengths are in the document's units, rounded as it shows them.** The thin
      extrude's depth and wall, a shell's thickness, a dome's height, a pattern's spacings and a
      thread's sizes were taken as mm: an inch part's 5.63 (inches) became 5.63 mm. Each is now
      found in the feature's own record, which keeps it exact in metres: the record's doubles
      that round to the shown value, the commonest kept (5.625 in, not 5.63). The unit is learned
      from the first sketch whose KeyWords dimensions match its own, else from the first value
      found (mm and inch only until then: a wider unit's window took an unrelated double).
    - An extrude with no distance in its records but a KeyWords `D1` is blind to that depth (it
      was tried as through all only; through all lists no dimension).
    - Some files write a sketch's plane reference after it, among its own records; the one before
      it is then another's (the origin's). That plane is a candidate too.
    - **The plane search was a product over all sketches**, the last sketch's plane varying
      fastest: a wrong plane for the first sketch was only changed after every combination of the
      others had been built. A sequence that stops at a feature now marks the planes of the
      sketches before it, and later sets with those same planes are skipped (what is built up to
      there depends on nothing else).
    - KeyWords `<Sketch … />` and `<Extrusion … />` written closed on themselves are not read on
      into the next element's dimensions.
    Results: two of the traced parts match now (an inch tube, a bearing). Regression 21/22 as
    before; parity features 199/0 on the samples and 485/0 on a set of the user's folders. The
    same 200-part sample through the plugin's converter: rebuilt 17 -> 20, no build 46 -> 41,
    built but not matching 32 -> 35, TBD 32 -> 31; no crash of the converter (3 files that aren't
    SolidWorks parts stop the test driver `convert_one` only).
136. **Where the 41 parts with no build get stuck.** The real search, instrumented (the furthest
    feature any plane set reached), on each: 35 run out of time, almost all deep in their tree
    (a cut, often through all, then fillets, patterns, scales); only one stops at its first
    feature. Traced a family of four copies of one small part (boss, boss, hole, through-all cut):
    - **A boss read as a cut passed because it changed the solid.** Its name says boss (so the
      boss is an alternative), but built as a cut it removed material and the search went on,
      then spent the whole budget on the last cut. The part is 24.9 mm tall; after that cut
      nothing could reach past 3 mm. New rule: where nothing still to come adds material (only
      cuts, holes, fillets, chamfers, shells; not bosses, revolves, sweeps, mirrors, patterns,
      threads, domes, scales, imports), a partial build smaller than the part's box in any
      direction can't become the part and is dropped.
    - **The boss's sketch is on the first boss's top face, but its plane reads through the
      origin**: a plane object stored without a frame defaults to the origin. An extrude whose
      sketch plane passes through the origin (and isn't the first) is now also tried starting at
      either side of the body's box along the sketch normal: SolidCraft's extent `start_offset`
      (picked as `start:<feature>`, written in both design writers).
    Results: the four copies rebuild (9 s each, from a time-out). Of the 41, several others now
    end in seconds instead of timing out, still without a match (their next cause is further on).
    Parity: features 199/0; designs 95 with the 2 one-line STEP rounding differences accepted
    before; Python tests 82 OK; Rust tests pass. Regression 21/22 as before (PartT_7 still not).
137. **Publishing safely, and a roadmap for contributors.** The repository is public
    (`github.com/bobthecooldad/sw2sc`, a separate clean export with its own short history), and
    has been shared so others can help.
    - Checked the public history (all four commits) for anything identifying: authors use the
      GitHub no-reply address; no home or cloud-folder paths, e-mail addresses or private part
      names. The first export had replaced the owner's own part names with aliases (`Part A`..),
      with two flaws: the aliases came from an unordered set (a second export could renumber
      them), and generic words that were also file names (`Wheel`, `Adapter`) were replaced
      inside other words ("Flywheel" became "FlyPart R", in logs only; no code was touched).
    - The public repository had three commits of its own (CI build and release workflow, version
      stamping, README download link, LICENSE): brought into this branch so the next export
      doesn't undo them.
    - `tools/publish.py`: `check` scans files for paths into home and cloud-synced folders, e-mail
      addresses (other than no-reply), and, from a private folder outside the repository
      (`~/.sw2sc-private`: aliases, terms, folders of one's own files, public sample folders,
      allowed names), private words and private file names written with their extension. `export
      DEST` writes a commit into a clone of the public repository with every private name replaced
      by its fixed alias (new names get the next free one, kept in the private folder), whole
      names only, longest first, then runs the check; it never commits or pushes. The aliases the
      first export used were recovered by matching its files line by line against the commit it
      came from, so they stay the same. The current public repository passes the check.
    - `ROADMAP.md` (where things stand, where help is most useful, which fixes need checking on
      more files) and `CONTRIBUTING.md` (clean room, keeping one's own files private, Python and
      Rust parity, checking before claiming, keeping these logs).
138. **Three reading faults found on two more stuck parts.**
    - A sketch with no curves read at all (an older tutorial part: every sketch empty) left its
      extrudes "decoded", and the search spent its budget building nothing. An extrude or revolve
      whose sketch has no curves read is now TBD: "its sketch's curves weren't read".
    - A thin cut kept under the plain cut class (an older file's `moICE_c`) was built as an
      ordinary cut of an open outline: its wall was never read. Where KeyWords gives the extrude a
      `D5` and its name or type says thin, that is its wall (snapped to the record like other
      KeyWords lengths: 0.22 in shown, 7/32 in kept).
    - An arc whose centre was read at the wrong point: a hub's outline took the top of a lobe as
      its big arc's centre. Both that point and the true one (the origin) are as far from the
      arc's two ends, but only the origin makes the lines meeting the arc tangent. Where the
      centre as read leaves every line meeting the arc at a corner, another sketch point as far
      from both ends that makes all of them tangent is taken as the centre (`_tangent_centres`,
      before the mirror-image alternatives).
    - Extrudes whose sketch plane reads through the origin are now also tried from every flat face
      of the body so far parallel to the sketch (a pocket's floor), not only the two sides of its
      box: at most 8 starts.
    Results: the hub's first extrude is now its true outline and it builds well into its tree, but
    still doesn't match (its back-face cuts; next to look at). Checked by the new check queue (139).
139. **A check queue that works while no one is at the keyboard** (`tools/checks.py`). `watch`
    follows a branch: each new commit gets the whole suite, one job at a time, in a checkout of
    its own (a git worktree under `~/.sw2sc-checks`, never the one being edited): build, Rust and
    Python feature and design parity, Python and Rust tests, the regression set (parts that
    rebuild must still rebuild, against the last commit that passed), and, while the queue is
    idle, the long sample run through the plugin's converter (no part that rebuilt may stop, no
    new crash). A newer commit replaces an older one still waiting. Reports name parts, so they
    stay under `~/.sw2sc-checks`; which parts are checked is in the private folder's
    `checks.json`. The regression and sample runners moved from scratch scripts into
    `tools/rebuild_set.py` and `tools/convert_sample.py`. A commit goes to the public `dev`
    branch once its suite passes, and to `main` once a few have, with the long run passing.
140. **A stray loop read with a boss's outline.** Two parts that built but didn't match had one
    extra circle each, reaching well past the part: a plate's offset circle (336.55 mm round a
    304.8 mm disc), and a circle of 18.3 mm round a corner of a 20 x 10 mm block (centred on one
    point, through an unrelated one). Nested with the real loops, it turned the plate's ring into
    the wrong rings and the block's hole into an island. A boss can't put material past the part's
    box, so where loops of its sketch (on the plane being tried) do, the search also tries the
    boss with all of them left out (`drop:<feature>`, before the nesting is worked out). Parts
    with such a boss now go through the sequential search (the plain one has no per-feature
    choices). The plate rebuilds (both converters); the block's boss is now right and its fillet
    is what's left (finding its edges, F-032).
141. **Hole Wizard holes whose size wasn't read.** 69 parts of the user's folders stopped at
    "hole's size not read". Their holes' named parameters, listed: tapped holes with no drill
    diameter of their own carry `Thread Major Dia.` (2.5 for an M3x0.5: the hole as drilled, the
    thread cosmetic); other files name them `Diameter`, `Depth`, `C-Bore Diameter`, `C-Bore Depth`.
    Both are read now (the thread's diameter only where no drill diameter is). 26 of the 69 now
    read fully (0 before); Rust and Python read all of them the same. Left: 41 parts whose holes
    have no named sizes at all (`M2 Clearance Hole1`, `Tap Drill for M2 Tap1`), not in KeyWords
    either: their sizes must be in the hole record's own layout, still to be found (ROADMAP).
    - Many of those keep the Hole Wizard's own names, which say the size: `M2 Clearance Hole1`,
      `M3 Tapped Hole1`, `Tap Drill for M2 Tap1`. Where the record names no diameter, it comes
      from the name with public ISO tables: clearance holes ISO 273's medium series (the Hole
      Wizard's "normal" fit: M2 2.4, M3 3.4), tapped holes and tap drills the major diameter less
      the coarse pitch (ISO 261: M2 1.6, M3 2.5) or the pitch the name gives. With no depth they go
      through all; the rebuild check says whether either is right. 30 of the 69 now read fully;
      28 still have no size (holes renamed from the defaults). Parity 68/0.
142. **3D sketches that place Hole Wizard holes** (`mo3DProfileFeature_c`, written right after the
    hole; about 70 parts of the user's folders, 30 of the hole-blocked ones). Their records write
    each point twice as three doubles (metres); stray triples don't repeat, except unit vectors (a
    direction kept twice), which are skipped. The points become a sketch of points on a plane
    through them, so the hole, the search and the writer work as for any placement sketch: their
    own plane where they span one, the planes holding the line square to each world axis where
    they are in a line, the three world planes for one point; all with the first point as origin,
    so the points sit at the same place on every candidate. Points not on one plane stay TBD,
    as do 3D sketches anywhere else. 35 of the 69 hole-blocked parts now read fully (30 before);
    parity 68/0. The first part traced decodes but its rebuild doesn't finish in the budget.
143. **Plain extrude-and-cut parts never reached the search's alternatives.** A steam-engine part
    (a boss, a boss read as a cut, a cut) built too little material, though the sequential
    search, run by hand, found it at once: the search only built parts in sequence when they had
    fillets, holes, patterns, thin or through-all extrudes and the like; the others tried sets of
    directions only, so a boss read as a cut, a start from a face of the body so far and a stray
    loop left out were never tried. Every part is now built in sequence (it tries every direction
    the plain search did, and the rest). The part rebuilds in both converters; the plate (140)
    and the four copies of 136 still do. A change for every part, so the check queue's
    regression set and the long sample run decide whether it stays.
144. **A hole whose only placement point is the sketch's origin** (a tapped hole on a pin's axis)
    was written with no points ("a hole needs 1...10000 points"): the writer leaves point 1 at the
    origin out, as the sketch's own origin. Where it is the only point, the hole now drills at
    SolidCraft's fixed origin point of the sketch. The pin's hole builds; its fillet is what's left
    (F-032).
145. **A circle centred at the wrong point, shown by its dimension.** The block of 140 has two
    5 mm holes, not one hole and a stray circle: the second hole was read centred on the sketch
    origin (its true centre lies on a centreline, so it was no "point on no curve", and the
    nearest such point is the origin), with the radius to its through-point, 18.3 mm. Where a
    circle's radius is none of the sketch's circle dimensions while it has some, the one point at
    a dimensioned radius from its through-point (not another circle's centre) is now its centre
    (`_dimensioned_circles`, after the dimensions are read). The block rebuilds in both
    converters with its fillet. Parity 481/0 (samples, the hole parts, a large folder of the
    user's parts).
146. **The check queue's long run caught a regression** (its first): a pin that rebuilt stopped
    finding a build after 140 sent it to the sequential search. Its second extrude, from the same
    sketch, lies inside the first and adds nothing; the sequential search drops every way of a
    feature that doesn't change the solid ("a way that does nothing is no way SolidWorks built
    it"), so it had nowhere to go. Where no way of an extrude changes the solid but one builds,
    the search now goes on from the solid as it was. The pin rebuilds again (both converters).
147. **A fillet edge given as one face twice** (F-032). A pin's 1 mm fillet names its edge as
    between "end face 1 of the first boss" and the same face again: the rim of a cylinder, between
    its end and its side (the side of a one-circle extrude isn't named apart here). The edge
    matcher skipped such pairs, so the fillet had no candidates. An edge given as one face twice is
    now any edge of that face, the other face left open (the search tries each where the face has
    several, a rim and a hole's rim). The pin rebuilds in both converters, all 7 features.
148. **Fillet edges naming curves the sketch doesn't number** (open). A stand's fillet rounds 8
    edges between a boss's sides and a cut's: the edges name the cut's curves 1, 2, 5, 6, 13 and
    14, but its sketch as read numbers its 12 lines 1-4 and 8-15 (no 5, 6 or 7), so those edges
    can't be matched and the fillet has no candidates. Either the sketch's handle numbering or the
    face references count differently here; not settled (ROADMAP, F-032).
149. **Empty sketches stay in the tree.** SolidWorks keeps empty sketches; they are part of the
    tree's names and order. A sketch with no curves read is no longer itself made TBD: it comes
    across as read under its own name, and only the extrude, revolve or sweep using it is TBD. An
    unused empty sketch whose plane isn't read is written empty on the Front plane (with nothing in
    it, its plane changes nothing) instead of being left out. The user's point on why such an
    extrude exists at all: SolidWorks can extrude edges of the model a sketch selects (converted
    entities), so the sketch holds no curves of its own; the TBD reason says so, and extruding the
    body's face (SolidCraft's `face:`) is the next thing for the search to try (ROADMAP). Parity 413/0.
150. **Extrudes of model edges, and the NIST test set.**
    - (The user's point.) SolidWorks can extrude edges of the model a sketch selects, so the
      sketch holds no curves of its own. Such an extrude (not the part's first solid feature: then
      there's no model to select from, and its curves weren't read) is now `from_face`: the search
      tries each flat face of the body so far, both ways, and the design writes its sketch on that
      face with SolidCraft's projected-face link (`links: [{kind: project, source: {type: face,
      body, at}}]`; SolidCraft finds the outline again on every rebuild: checked by evaluating a
      sketch holding only the link). Of the 22 census parts blocked by an empty sketch alone, all
      had it on their first extrude, so none of them is helped; the rule is for the later ones.
    - Datum targets (`moDatumTarget_c`) and coordinate systems (`moCoordSys_c`) are annotations
      and reference geometry: kept in the tree, no solid (they blocked 5 NIST parts).
    - **NIST CTC/FTC set** (19 SolidWorks parts, saved by SolidWorks 2012, 2015 and 2018; the
      user's download, third-party and git-ignored). Every part opens with its solid. Its volume
      against NIST's own STEP of the same test case: 14 of 19 within 0.1%. The other 5: CTC 02
      (both saves) and FTC 07 come in as surfaces (SolidCraft refuses 6 of 488 faces on a B-spline
      knot multiplicity; 62 edges lie up to 0.1 mm off their faces); CTC 03 (both) is 0.16% under.
      Feature trees: none rebuilds yet: the 5 SolidWorks 2012 saves aren't numbered, and every
      other has two or more of draft, hole placement, sketch planes, fillet and chamfer edges, rib,
      move face, move/copy body. (cadkit-kernel reports 39 of 41 imported and 32 of 37 volumes
      matching on the NIST set; its author says it is clean-room, and it may now guide us,
      credited as a helper.)
151. **The local model's notes on cadkit-kernel, and per-face feature tags.** The 8B model's notes
    on cadkit-kernel's SolidWorks crates (`~/.sw2sc-checks/qwen/cadkit`) are thin and partly
    invented (offset tables that aren't in the code), so none of them is used as a fact. Two things
    hold: their crate is built around working back from the finished solid (modules `unblend`,
    `unmirror`, `hoist`, `reorder`, `prefix`, `fastverify`), and, read in their code itself, the
    face tags behind it: each face of the part's Parasolid body carries `FACE_ID_2001`, integers
    `[kind, feature id, stamp, 0, local index, ...]`, the feature id the one in KeyWords (40 an end
    cap, 74 a side, 72 a fillet face, as they read it). Recorded with credit in docs/clean-room.md;
    not used yet: it is the way to match fillet edges and check each rebuild step face by face.
152. **Fillet edges from the face tags (in progress: Python done, Rust port not written).** Read
    on our own samples, `FACE_ID_2001` (151) holds: a boss's faces are kind 40 (ends, local 0/1)
    and 74 (sides, local = the sketch curve id), a cut's sides kind 83, a fillet's own faces kind
    72 (local 1..n), each with the feature id of KeyWords. A fillet record's face references
    ("end", fid, 0|1) and ("side", fid, curve) are those same numbers, so the tags settle the
    stand of 148: the file's curve numbers are right, our sketch reading misnumbers that cut.
    - `features._tagged_faces(sw)`: every face of the part's Parasolid body by its tag.
    - `features._edge_lines`: for each fillet/chamfer edge between two flat tagged faces, the
      line the planes meet on (`edge_lines`); and for a fillet whose own faces (kind 72) are all
      cylinders, each face's axis and radius (`round_axes`).
    - `fillets.candidates`: the nearest edge of the build so far to each axis (1 to 3 radii away,
      the sharp edge a round replaced) is tried first; else, where every edge has a line, the
      edges lying on those lines; then the face matcher as before.
    Results (Python): the training block and the solenoid pin rebuild with their fillets found
    this way; the stand still doesn't (its last cuts, next to look at); a sensor housing times
    out. NOT YET IN RUST: `edge_lines`/`round_axes` aren't read by the Rust port, nor used by its
    `fillets::candidates`, and not in the parity dumps; the plugin doesn't get this until they are
    (same code shape: `parasolid.rs` has the ATTRIBUTE/ATTRIB_DEF/INT_VALUES nodes and `Node::p`,
    `F::List`). Then add both fields to `compare_features.py` and `dump_features.rs`.
    - Note on the check queue: Desk-29_103 rebuilds in 70-90 s alone but times out (240 s) when
      other rebuilds run at the same time; three "regression" failures today were that. Don't run
      heavy rebuilds while the queue's regression step runs, or give that part more time.
153. **Face-tag fillet edges ported to Rust** (finishing 152). `features/read.rs`: `tagged_faces`,
    `plane_line`, `edge_lines` (fields `edge_lines`, `round_axes` on `Feature`); `fillets.rs`:
    the same head of `candidates` (nearest edge to each fillet face's axis, else the edges on the
    face-pair lines, then the matcher). Both fields are in the parity dumps
    (`compare_features.py`, `dump_features.rs`); the empty face assignments are a list on both
    sides. Parity 504/0 (samples, the user's Documents, a large Dropbox folder, the hole parts, the
    fillet parts, the NIST set).
154. **NIST parts that came in as surfaces** (CTC 02 both saves, FTC 07). Compared with
    cadkit-kernel's rolling-ball construction (credited; it builds cross-sections from the blend's
    own `range`, support sides and spine limits, and it collapses the same two cases below too).
    - FTC 07's four fillets fell back to a fitted surface ("degenerate cross-section"): each joins
      two cylinders of the blend's own radius (a pipe bent round a corner), so the ball fills both
      and its feet are one point. The blend is then the tube of that radius round the spine: each
      cross-section a whole circle square to the spine, started from the spine plane's normal on
      every row (`_blend_surface_exact`, both converters). Likewise feet exactly opposite (a full
      round between parallel faces, F-045) give a half circle, on the side the face's own boundary
      is. No fillet of FTC 07 falls back now.
    - STEP knots a rounding error apart (1e-12 of the knot range) are merged (`nurbs.knot_eps`,
      both writers): written separately they don't increase.
    - What still stops both parts: B-spline surfaces in the file itself (rational, degrees 2x3)
      whose interior knots have multiplicity 3, the degree (a C0 crease Parasolid allows);
      SolidCraft's pcurve step refuses them ("portable B-rep: knot multiplicity"). Next: knot
      removal where the surface is in fact smooth there, else split the face at the crease.
155. **Why CTC 02 and FTC 07 still come in as surfaces: one cause, a self-folding fillet.** Their
    refused faces (6 in CTC 02, 4 in FTC 07) are all the same kind: a fillet where two cylinders of
    equal radius meet at a mitre, bounded by two circles of the pipe radius and two ellipses (the
    mitre). The fillet's radius is just above the ellipse's smallest radius of curvature (b^2/a):
    CTC 02 25 mm against 24.93, FTC 07 3.048 against 2.89. The exact rolling-ball surface folds
    over itself near the ends of the ellipse's long axis, and SolidCraft's pcurve step refuses it
    ("portable B-rep: knot multiplicity", though the surfaces' own knots are plain: single interior
    knots, clamped ends; the face's edges are exact circles and ellipses). The B-surface C0-knot
    idea of 154 was a misreading (the scan took weight lists for knots). Tried and undone: building
    only the arc of the tube the face covers (each FTC 07 face covers 19.4 degrees), which didn't
    change it. Next: build the face only over its own spine range without the padding (the fold may
    lie outside it), or leave out the folded strip and close the face to it; check what SolidWorks'
    own body does there (its Parasolid face may stop short of the fold). cadkit-kernel's
    `blend_row` collapses the same case (feet coincident) and doesn't import these either as far as
    its code shows.


156. **Large imported parts (public issue #1).** A 112 MB imported-body part ran the plugin out of
    memory and fuel, then its design was over SolidCraft's 256 MiB hand-over cap (the reporter's
    Python run: 363 MB of STEP, 89% edge B-spline curves and their points). Points, knots and
    weights are now written to 12 significant digits (knots in full where rounding would make two
    equal); the largest GrabCAD sample shrinks 14%. The issue's part needs about 30%, so this is a
    first step: next, look at what else dominates (entity refs, duplicate curves) and peak memory.
    Limits left as they are (the user: fix the cause, not the cap). Python/Rust parity was reviewed by local
    qwen2.5-coder:14b (no mismatches) and checked with `plugin/tools/compare_step.py`.

157. **Sketch curve tags calibrated file-wide** (NIST FTC 06 and others). FTC 06's sketches read points
    but no curves: every point's handle list tags its lines 0x8426 and arcs 0x8491, where the stream's
    numbering gives sgLineHandle 0x8196 and sgArcHandle 0x81E9 (objects before the first sketch the
    numbering doesn't count), and both classes come in before any sketch, so the per-sketch learning
    has nothing to learn from. `_handle_tags_file` / `handle_tags_file`: where no handle tag in any
    point's list is one the numbering gives a curve class, the distinct tags (sorted) take the curve
    classes in the order the stream brings them in, if the counts agree. Over the GrabCAD set it seeds
    14 parts; 10 read exactly as before, FTC 06 (both saves), FTC 08 and FTC 09 (2015) gain their
    curves (FTC 08 2015: 1 -> 126, FTC 09: 1 -> 70). FTC 06's Boss-Extrude1 and Revolve1 now convert.
    Not rebuild-checked yet: the parts still have other features left (holes, fillets, Rib1).
    Parity 19/0 on the NIST set.

158. **NIST CTC SolidWorks 2012 saves read** (all five). Their feature stream has no `moRefPlane_c` (the
    standard planes are in `Contents/Config-0`), so the plane anchor of `old_start_number` had nothing to
    go on. `_start_by_fit` / `start_by_fit`: of the starts from Config-0's highest class number up 500,
    the one that lets the most records be told apart in the first 30 kB (a wrong start soon names a tag
    no class has and the records stop): CTC 01 442 against 332, CTC 02 526/430, CTC 03 352/304, CTC 05
    445/352; CTC 04 is close on 30 kB (245/217), so the best 8 are scored again on 100 kB (1294/1086).
    Taken only 15% clear of the next best. Second cause, broader: `_name` wanted the node tag's high
    byte to be 0x80, and in streams whose class numbers run past 255 it is 0x81.. (CTC 01's Sketch1:
    `D0 81 FF FE FF`), so those features were found by number but dropped. Over the 169 GrabCAD parts
    only NIST files change, all gains: CTC 2012 None -> 22/106/37/59/44 features; FTC 06 2015 gains
    revolves and patterns, FTC 09 2015 patterns, FTC 08 2015 has no tbd left. Parity 19/0 on NIST.
    No cadkit-kernel code was used for this (found from the files).

159. **Ribs, ported from cadkit-kernel** (`ck-swedit/src/rib.rs`, MIT OR Apache-2.0; the user allowed
    porting 2026-11-26). The rib's faces in the part's solid (by FACE_ID_2001 feature id; on FTC 06 kind
    77 the two sides, 74 the free edge) are all planes: the parallel pair reaching farthest are the
    sides (FTC 06 Rib1: x = +-12.7 mm, so 25.4 mm, KeyWords' D1 = 1 in), the sketch plane midway; each
    other face's trace in that plane runs between its vertices' extremes, and the traces chained end to
    end are the open profile ((y, z) 97.79,-31.75 -> 46.99,-133.35 -> 34.93,-133.35). Written as a sketch
    on the mid plane and SolidCraft's `rib` (thickness; `flip` and `extend` tried in the rebuild,
    `extend` first). `_tagged_faces` now also gives each face's vertex points (Rust: `tagged_faces` keeps
    the face, `face_points`). Checked: on FTC 06's Sketch1 + Boss-Extrude1 the rib builds without error
    in every option, adding 19 067 mm3 at x +-12.7; the whole part can't be rebuild-checked while its
    holes and fillets are tbd. Parity 19/0 (the rib's plane and chain are in the dumps).
    Body-Move/Copy1 (FTC 10): cadkit-kernel has no SolidWorks handling of it (only Fusion and its own
    model), so nothing to port; not done.

160. **Body-Move/Copy (FTC 10), found from the file** (cadkit-kernel has nothing for it). KeyWords lists no
    dimension; its records keep a rotation (9 doubles, rows), 8 bytes (an integer 1), then the
    translation in metres: identity, then (0.0625, 0, 0). Checked against the saved solid: FTC 10's
    Boss-Extrude1 built in place spans x -132.5..7.5 mm, its tagged faces in the saved solid -70.9..70.9
    (later bosses widen it); moved 62.5 mm it spans -70..70. Written as SolidCraft's `move` of the
    part's body; a move with a turn is left tbd until a sample shows one (the doubles after the
    translation, 1, 0, -0.0625, 0.0155, aren't understood yet). Parity 19/0.
161. **Draft and Move Face read and written (NIST CTC 02, 03, 05, FTC 07).** `moDraft_c`: KeyWords'
    D1 is the angle (refined to the record's exact radians); `moMoveFace_c` with one dimension is an
    offset, D1 its distance. Neither record's face references are decoded; instead the faces come
    from where they end up. The drafted face keeps the tag of the feature that made it (no face is
    tagged with the draft's id), so the search (`verify.face_moves`, Rust `search::face_moves`) takes
    each flat face of the body so far, tilts its normal by the angle toward each axis direction, and
    looks for that plane among the part's own flat faces; where the two planes meet gives the
    neutral plane's level, and the faces sharing a level and pull are one draft. A move face's faces
    are those whose plane moved by ±D1 is one of the part's (preferring faces whose old plane is gone).
    Written as SolidCraft `draft` (custom neutral plane, pull; angle parameter `D1@Draft…` in deg)
    and `offset_face`. SolidCraft's sign checked on a box: positive angle, pull +z tilts a side's
    normal toward +z. All 11 features (9 in CTC 02) now read in both ports (parity checked); none
    is tbd. Rebuilds: CTC 05 still stops at Sketch1's plane (another session's area); CTC 03 gets
    to Move Face2, but our build up to Cut-Extrude1 already differs from the part (its Cut-Extrude1
    faces are at 45°, ours at 22.5°/25°), so no face matches; that cut comes first. CTC 02 and FTC 07
    have other tbd features (fillets, holes, 3D sketch, move/copy body). Not yet done: drafts of
    curved faces (cylinder → cone), and translate/rotate move faces. Reading cadkit-kernel's
    `draft.rs`/`moveface.rs` was blocked in this session, so this is our own method; its author has
    since confirmed it clean-room (credit "with help from cadkit-kernel" where it guides later work).

162. **CTC 03 Sketch3: a third face-plane candidate; cadkit's Move Face read.** Sketch3 sits on a
    side face whose record's own z points into the part. Both candidates put its profile at
    negative z, outside the part (z 0 to 162). The first candidate turned half round in its plane
    (x and y both reversed, the face's normal kept) puts its 45° line exactly through one of the
    part's own faces. It's now a third candidate (Python `_face_frame_at`, Rust `face_frame_at`).
    Move Face2 still matches nothing: in our build that face's normal is (0, 0.71, 0.71), in the
    part (0, -0.71, -0.71), so the material is on the other side. The open question is which of
    Sketch3's two loops Cut-Extrude1 cuts (or whether the search's prefix is wrong there), not the
    move itself. cadkit-kernel's `moveface.rs` (read, with help from cadkit-kernel) works the other
    way round from us: it reads the preceding cut back from the final body, finds the moved faces as
    that cut's flat faces whose edge with an earlier feature's face lies inside the body before the
    cut, and shifts them back by D1. Nothing in it carries over directly to our sketch-driven build,
    so nothing was ported and THIRD_PARTY_NOTICES.md isn't needed yet.

163. **Flip side to cut, emulated; CTC 03's Move Face2 now finds its faces, but SolidCraft refuses
    to move them.** CTC 03's Cut-Extrude1 keeps its profile and takes the rest (SolidWorks' "flip
    side to cut"): only that reading makes both of its 45° faces face the way the part's do.
    SolidCraft has no such option (none on main or any branch of `C:\dev\solidcraft`; request
    drafted in `docs/solidcraft-requests/flip-side-cut.md`). It's emulated as a cut of a 20 m
    square whose holes are the sketch's loops (`FLIP_SQUARE`, Python and Rust), tried for each cut
    after every ordinary way (search pick `flipside:<cut>`). Checked on a box with a flipped circle
    cut: 103141.59 mm³. With it, Move Face2's matching (log 157) finds one or two of the cut's faces
    moved 5.08 in, but SolidCraft's `offset_face` refuses each set ("the wall is too thick: it
    leaves no room inside the body", or "no face at" a point `model.faces` gave). So the search
    gets no further than Move Face2, and CTC 03 still doesn't rebuild. Next: try the faces by their
    `model.faces` names instead of points; ask SolidCraft about the "too thick" refusal (in the
    request file too).

164. **CTC 03 Move Face2 by face names: no help.** Giving `offset_face` the faces' `model.faces`
    names as well (`face_names` beside the points, as SolidCraft saves it) changes nothing:
    SolidCraft resolves the points, and the same two refusals come back. More telling: every
    face the matching finds lies on a strip about 1.9 mm wide (x 6.35 to 8.26, at z = 111.125),
    so the "too thick" refusal is real for our body there, and the flipped Cut-Extrude1 of log 159
    is likely not the part's either. Change undone. Next: compare our body after Cut-Extrude1 with
    the part face by face (which faces Cut-Extrude1 made in the part, tags 83/135), before Move Face.

165. **CTC 03 Cut-Extrude1 against the part, face by face.** The part's Cut-Extrude1 faces (tags
    83/135, local 10 to 17) are Sketch3's lines with the material inside the loops (for example
    -z faces at z = 100.965, and +y at y = 181.127), which confirms the flip side of log 159. The
    two -z faces at z = 116.205 are the u = 111.13 lines moved 5.08 mm: Move Face2. In the search,
    the flipped cut toward -x (SolidCraft's "positive" for the turned Sketch3 frame) leaves about
    80,000 mm³ against the part's 331,392 (and only cuts follow), so it's out. Toward +x
    ("negative", through the 1.9 mm wall from x = 6.35 to 8.26 and the boss beyond) leaves
    367,000 to 386,000 mm³, which is plausible, and Move Face2 finds the right faces there (z = 111.125,
    moved -5.08). SolidCraft's `offset_face` refuses that move ("the wall is too thick"), and with
    both faces says "no face at" the second. So CTC 03 now stops on SolidCraft's Offset Face, not
    on reading: in `docs/solidcraft-requests/flip-side-cut.md`. A repro to send them: the design
    up to Cut-Extrude1 (choices negative, Sketch3 plane 2, flipside) plus that offset.

166. **A first sketch with no plane reference: the standard planes tried.** CTC 05's Sketch1 has
    no plane reference anywhere (before it, inside it, or with the feature that uses it). A part's
    first sketch is nearly always on Front, Top or Right, so when it has curves and no plane, all
    three are offered and the rebuild check chooses (Python `STANDARD_PLANES`, Rust the same).
    Only the first sketch, so other parts' searches don't grow. CTC 05 now builds through
    Boss-Extrude1 to Cut-Extrude1 and stops at its first hole (3/8-16 Tapped Hole1, the holes
    session's area), before Draft2.
167. **NIST Hole Wizard holes and dropped features** (branch nist-holes-chamfers).
    - Holes "placement sketch not found" (FTC 06, 07, 09 2015, 10): three causes. (a) KeyWords lists
      a hole's placement sketch as `<Sketch Name="Sketch8" Type="Sketch"/>`, without `Dissectable`,
      so `_recover` skipped it where the numbering had drifted; now taken. (b) A recovered 3D
      placement sketch (`3DSketch2`) was read as a 2D sketch; found by name it now takes the 3D
      route when it follows a hole (only then: 3D sweep paths stay as they were). (c) A 3D sketch's
      points: each point has its own record, the double 1.0 (2018 saves: then 8 zero bytes), a
      2-byte tag, x y z, then the entity kind (01 first point, 08 further points; 02/0D are a
      line's ends). Read those first, the "written twice" guess as fallback: FTC 06's 3DSketch3
      had 2 of its 3 points, 3DSketch4 none. The hole's sizes are also read past a 3D sketch.
    - `_recover` required the class tag's high bit (`b[i-3] & 0x80`); in FTC 09 and FTC 08's 2015
      saves and FrameBracket_v2 that byte is plain (tag `5f 63`), and their first extrude, first
      sketch, fillets and patterns were silently missing (the tree looked "fully decoded" without
      its base). Now only the node tag's bit is required; a plane found that way is a standard
      plane and skipped. Census of 599 parts: only additions (no feature lost or changed kind).
    - Now: every hole in the four parts converts. FTC 08 2015 is fully decoded (Cut-Extrude1,
      Fillet7/8 were tbd only for the missing base) but stops at "Sketch1: no plane reference
      found" (the sketch-planes work). Still tbd here: chamfers of FTC 09, fillets of FTC 08 2018,
      and the recovered Boss-Extrude1/Fillet1 of FTC 06 2015 (sketch curves, fillet edges).
    - Both converters; parity 204/0 on samples and GrabCAD (NIST included).
168. **Fillet and chamfer edges written as groups** (finishing 157). FTC 09's chamfers list their own
    faces 4, 3, 2, 1 (2015 save) or interleaved with other references (2018), so the "own faces
    1…N, then 4N references" rule fails, and the record-run fallback finds nothing. Each edge is
    also written as a group: `04 00 00 00 00 02 00 00` (four references), a u32, 16 bytes, then
    side, side, end, end (side references packed 20 bytes apart in 2018 saves, 24 in 2015). Used
    only where both other rules give nothing; a group repeated later in the record is the same
    edge. Census diff against HEAD: 29 tbd fillets/chamfers convert (NIST CTC 02, FTC 06-10;
    GrabCAD Rear Body, Desk-29_101, Karman_101a, Sitrak C7, NARVA, Battery box); no converted
    feature's edges changed. Both converters, parity 204/0.
    - Rebuild check of the target parts (none rebuilds yet, for reasons outside these features):
      FTC 08 both saves "Sketch1 (and Sketch9): no plane reference found"; FTC 09 2018 its
      engraved text (Sketch30); FTC 09 2015 decodes fully but stops at its first hole: the
      placement sketch Sketch4 has only the candidate plane z=0 while the plate lies in XZ (y 0 to
      3.04 mm): a hole placed on a model face needs that face's plane as a candidate (the
      sketch-planes work). Its placement sketch also has 4 points at +-1.671 mm besides the
      hole's centre; the hole search's point sets should settle that once the plane is right.
      FTC 06 2015 still has Boss-Extrude1 (sketch curves) and Fillet1/2 tbd; FTC 07 draft,
      VarFillet, move/copy body; FTC 10 move/copy body, Fillet2, a 3D sketch.
169. **Hole placement planes from the hole itself (ported from cadkit-kernel's hole.rs).** The user
    now allows cadkit-kernel's code to be used (MIT OR Apache-2.0, credited in
    THIRD_PARTY_NOTICES.md and at each ported function). Its `hole_with` places the sketch square to
    the hole's axis at its entry. Ours: the cylinders tagged with the hole's feature id give the
    axis and a point (Parasolid's pvec, at the entry face here); each frame square to that
    standard axis, set so a sketch point lies on a hole axis, is scored by how many of the
    sketch's points do; the best (ties: origin at the world origin moved along the axis) go first,
    at most four. FTC 09's Sketch4 now gets the Top frame at y = 3.038 mm.
    - Two more blockers on the way: a Hole Wizard parameter name starting with a digit
      (`15_64__0_23438__Diameter_Hole1_diameter`) is read by SolidCraft as 15 then an unknown name,
      so the hole never built: names now start with `_` there. And KeyWords' `LPattern` /
      `CirPattern` types weren't in the recovery table: 11 patterns of FTC 09 2015 (and those of FTC 06
      and 08 2015) were missing.
    - FTC 09 2015 now builds through every hole, its patterns and Cut-Extrude1, and stops at
      Chamfer1: chamfers of the holes' rims (edges between a hole face and the boss's top face,
      including pattern instances). Next: fillet/chamfer candidates on a hole's circular rim edges.
    - Parity 204/0; census: only additions (patterns), FTC 09 Chamfer1's edges now name the patterns.
170. **Chamfer1 of FTC 09: chamfers on hole rims.** Four things stood between the search and it.
    (1) The rim edges weren't offered at all: `fillets.body_edges` keeps only edges whose two faces
    it can name, and a hole's bore (`F4:bore:side:2@F6.1`) isn't one; the edges are now also kept
    as (mid, name) for the geometric match. (2) The chamfer's own faces in the solid are cones
    (kind 72), each on a hole's axis with the hole's radius, so they now fill `round_axes` like a
    fillet's cylinders; for a chamfer the edge is the one at the cone's radius (within 0.01 mm), not
    the nearest (the drill point's edge was 0.002 mm nearer), ties going to the one nearest the
    cone's point along the axis, and seams (one face) left out. (3) LPattern1 (2 x 2) was built with
    its second direction off the part (2 of its 4 holes), explored first, and the time ran out
    before backtracking: a pattern's ways are now all tried first, then followed most-change first.
    (4) Off-axis distances are compared to 1e-3 mm (edge mids carry a few 1e-6 of noise).
    Chamfer1 now builds on the four top rims. Both converters; parity 204/0.

## Sketch curves not read / arc centres (sketch-curves branch, 2026-11-26)
Set: the 149 census parts blocked on "its sketch's curves weren't read" or "arc N: no centre
found", copied to `~/.sw2sc-checks/work/sketchcurves`.
- Point records `FF FF 07 00` (pre-2010 files) now read as `1F`. Parts with an unread sketch: 71 → 56.
  Two-point "no centre" parts 26 → 27 (newly read sketches show their own arcs), one-point 23 → 23.
  No part got a new problem.
- Arc tag retried as the line class when all its two-point curves find no centre (A2773 bolt
  Sketch2: 12 failures → 24 lines).
- Rebuild check (12 changed parts): 2 match (tutor1, ISO20 plywood floor), 4 mismatch, 6 now stop
  on other blockers (fillet/chamfer edges, moBlend_c, moMoveCopyBody_c, design table).
- Parity on the set: 3 diffs; `bottom` ×2 predate this change; 57mm Altimeter's newly read
  Sketch49 (unused, not built) picks a wrong circle centre by a different tie-break in each reader.
- Not done: sketch blocks (`moSketchBlockDef_c`, 19 parts), points with no curve handles (newer
  files), `moTempAxisRef_w` centre points. cadkit-kernel was not consulted: reading it was refused
  by this session's permission check.
- Curve records read by point position (with help from cadkit-kernel sketch.rs `entities` /
  `build_sketch`), used where the handle reading leaves curves unread. Unread-sketch parts 56 → 47;
  "no centre" parts (two-end 27 → 11, one-end 23 → 11); none worse. Parity: the same 3 diffs.
  Rebuild of 23 changed parts: A2773 bolt matches; 16 build but don't match (most "no build to
  compare" — fillets, planes, etc. downstream); 6 stop on other blockers.

171. **Split features (`moSplit_c`, 36 split-only parts in the census).** Read as SolidCraft's
    Split Body: the plane its record names (a plane reference, read like a mirror's), else a
    straight line of the sketch before it; the rebuild search tries keeping both pieces, the
    first (the second removed with a Remove feature) or the second. Builds before a split may
    reach past the part's box, so the box check is skipped for them. Python and Rust port.
    First 6-part check: 1 rebuilds and matches (a private turned part, "Circle"); the other 5
    find no build to compare, the trees before their splits not yet matching (sketch planes,
    through-all cuts, revolve profiles). Which piece SolidWorks keeps (`moPerBodyChooserData_c`)
    is not decoded. No cadkit-kernel code: it has no split module.

172. **Sketches with no plane found (census blocker, 93 parts).** Parts with every sketch plane
    read: 8 before, 55 after (49, 54, 91 and 93, which have hundreds of sketches, were left out).
    (a) A face plane reference can have a `01` flag in its zero run followed by a bare
    `FF FF FF FF` (id -1) with no 16-byte FF block; it was rejected. Read now, the face plane follows
    (8 → 44 parts). (b) The origin+normal plane object (4fb19d3) gave up to 6 candidates: the
    same doubles read at shifted offsets; only the first is kept now. (c) A sketch used by a second
    feature is written again as `SketchN<k>` with no points and no plane, only
    `moContourChooser_c` records; it now copies SketchN's geometry and planes (44 → 55). Which
    contours it takes is not read yet. Rebuild check (`tools/feature_check.py`): origin+normal parts
    1 of 8 match (the other 7 run out the 240 s search budget); face-flag parts 2 of 36; shared-sketch
    parts 0 of 10 (one more blocked by fillets). Most mismatches say "no build to compare" though
    their evaluations do run (one part: 261 builds, none at the reference volume; the cut and the
    circular pattern remove too much), so the planes aren't what's left. The other 38 parts: sketches
    on external or derived references (`moSketchExtRef_w`, `moCompEdge_c`) with no stored frame;
    the dimension records give only the normal. cadkit-kernel's `plane_refs` / `resolve_plane`
    read the 12-double frame after a reference, which `_triads` already finds: nothing to port for
    these. Python and Rust both; parity 0 differences on 50 parts.
173. **NIST set after merging the six parallel branches (5459af2).** `logs/feature-check-nist.md`,
    SolidCraft CLI 0.47.0. No NIST part rebuilds to a match yet; what stops each:
    - SW2012 CTC 01-05 (trees now read): every Hole Wizard hole "hole's size not read" (2012
      layout); CTC 01 Fillet1, CTC 05 Chamfer1.
    - CTC 01 (2018): rebuilds, +1.8% material (a loop taken as an island, or a cut that didn't take).
    - CTC 03, 04, 05 (2018): fully decoded, SolidCraft makes no build (CTC 03: Offset Face, 163-165).
    - CTC 02 (2018): Fillet3, 3DSketch1 (`mo3DProfileFeature_c`).
    - FTC 06 (2015 and 2018): Fillet2 only.
    - FTC 07: VarFillet1/3 (`VarFillet_c`), sketch text.
    - FTC 08 (2015 and 2018): Sketch9 "no plane reference found" only.
    - FTC 09 (2015 and 2018), FTC 11: only sketch text (SolidWorks keeps no letter shapes, so the
      check can't match exactly; to decide how these count).
    - FTC 10: 3DSketch1 only.
    Next (two workers): SW2012 hole sizes, fillets, CTC 01's extra material; FTC 08 Sketch9, the
    no-build parts, 3D sketches.

174. **SolidWorks 2012 parameter values (the five NIST CTC 2012 saves).** Every Hole Wizard hole of
    those saves said "hole's size not read", and most fillets and chamfers "size or edges not
    read": the parameter record's value sits elsewhere in 2012. Later saves: name, 8 flag bytes,
    `FF FF FF FF`, 4 zero bytes, an empty text field, 2 zero bytes, the double. 2012: `FF FF FF
    FF`, 2 zero bytes, the double (e.g. `Hole Dia.` 0.02 in CTC 01). `_param_value` /
    `param_value` read the 2012 place only where the later reading fails. In the five parts, 25
    holes, 14 fillets and 6 chamfers now convert; nothing else in the census changes. Left: CTC 02
    Fillet3 (also tbd in its 2018 save) and a 3D sketch (sketch-planes work). Parity 204/0.

175. **NIST FTC 08 Sketch9; what CTC 03/04/05 (2018) stop on.** FTC 08 numbers no plane object
    at all (no `moRefPlane_c` in either save), so the reference before Cut-Extrude1, which names
    plane feature 2, found nothing. The standard planes are still in the stream as named records
    (`FF FE FF` name, 7 zero bytes, flag 0x40/0xC0, u16 id: Front 2, Top 3, Right 4); where no plane
    object is numbered, the lowest three in a row with consecutive ids are taken as Front, Top and
    Right (Python and Rust, parity 44 files). Sketch9 reads on Front in both saves; FTC 08 now
    decodes fully but doesn't rebuild to a match (the search runs out of time). CTC 2018 saves,
    traced eval by eval: 03 stops on SolidCraft's offset_face for Move Face2 ("the wall is too
    thick", logs 163-165); 04 evaluates all 105 builds without an error and none matches (the
    holes and the cuts with no depth read are the suspects); 05 stops on Draft2: SMLib refuses the
    offset ("the new faces beside edge 55/58 that was tangent no longer meet") or moves no face.


178. **Parallel feature checks and triage.** `feature_check.py` still walked parts one at a time;
    recent surveys needed eight manually sharded folder copies. Both it and `rebuild_triage.py`
    now take `--jobs` (default 8), using process pools with the resolved SolidCraft CLI passed
    explicitly. Reports keep input order, per-part errors and the existing limit/keep/name filters.
    Two local qwen2.5-coder drafts for each tool were rejected: they changed unrelated behaviour,
    put the runner inside `main`, omitted required results, or reused the last part's name. New
    regression tests were written first and failed four times on the missing options/runners; the
    replacement implementations pass all three tests and the full Python suite (91 run, 5 skipped).
    A real two-part NIST check with one and two jobs produced identical reports (two mismatches,
    one not fully decoded). Two simultaneous triage jobs returned correctly named separate rows.


179. **The design-parity baseline was stale.** The first public-branch queue reported three
    one-line STEP differences against an allowance of two. The unmodified public base, built and
    checked separately on the affected folders, reports exactly the same three (24 files, 9 designs,
    3 differences). The NIST reader changes touch no STEP geometry code and introduce no new design
    difference. The private check baseline is therefore three known differences; any additional
    difference still fails the queue. Feature parity remained zero and the rebuild regression lost
    no parts.


180. **Full NIST check after the 2012 parameter and standard-plane fixes.** Eight jobs, about
    eight minutes, SolidCraft CLI 0.47.0. Exact feature-tree matches remain **0 of 19**: the
    imported-solid fallback is not project success. Fully decoded parts that attempt a rebuild
    rose from 4 to **10 of 19**; reader-blocked parts fell from 15 to **9**. Four of the five 2012
    CTC parts moved from unread hole/fillet/chamfer sizes to rebuild mismatches; CTC 02 still has
    Fillet3 and its 3D sketch. Both FTC 08 saves moved from a missing Sketch9 plane to rebuild
    mismatches. The other reader blockers are FTC 06's Fillet2 (both saves), FTC 07's variable
    fillets and text, FTC 09's text (both saves), FTC 10's 3D sketch and FTC 11's text. All ten
    rebuild attempts currently report no build to compare. Report: `logs/feature-check-nist.md`.


181. **NIST on SolidCraft 0.50.0.** The checkout was 64 commits behind; it was fast-forwarded and
    `solidcraft-cli` rebuilt. The same full 19-part, eight-job check still gives **0 exact matches,
    10 rebuild mismatches and 9 reader-blocked parts**, so the newer kernel does not change the
    project's success rate or decoder queue. One mismatch signature is more informative again:
    CTC 01 (2018) has 1.8% too much material, consistent with a loop island or a cut that did not
    take. The other nine rebuild attempts report no build to compare. Kernel 0.47.0's report is
    superseded by `logs/feature-check-nist.md` on 0.50.0.

182. **Private external structural samples and a five-minute triage budget.** A private folder
    contributes 3,998 additional parts; its paths and filenames stay out of the repository. The
    check queue's optional external batch uses a commit-derived seed, 40 parts, eight jobs and a
    separate baseline, so each long run can cover a different deterministic group without changing
    the existing sample baseline. Its first completed run took about nine minutes on SolidCraft
    0.50.0: **6 exact feature-tree rebuilds (15%)**, 8 built without a match, 10 no-builds, 3 TBD,
    11 without feature history, 1 unnumbered feature stream and 1 error. Only these aggregate
    outcomes are public; the per-part JSONL stays in the private check directory. The first manual
    smoke invocation missed the tools import path and was corrected before the successful run.
    The new automation tests failed three times before implementation; the full suite is 95 tests
    OK (5 skipped). Triage's default budget changed from 90 to **300 seconds**, with a CLI test
    that first observed 90 != 300 before the change.

183. **Fillet/chamfer edge groups whose references have wider spacing (F-032).** The post-merge NIST
    check had 10 mismatches and 9 not fully decoded, no matches. The sample blocker census had 10
    parts with a Fillet_c blocker, 4 blocked by fillets alone. CTC 02 Fillet3 (2012 and 2018) and
    FTC 06 Fillet2 (2015 and 2018) all had their radius but no edges. Their group reader assumed
    four references lay in a 4 x 24-byte window: a CTC 02 group's fourth is at +162 and an FTC 06
    group's at +178, so the whole selection was discarded. Another apparent group header is the two
    bytes before a reference, not a group. Read the first reference in the old range (within 40
    bytes after the 8-byte header), then four sequential references, gaps at most 72 bytes; skip a
    header whose first reference starts inside the header. Found from the sample bytes, no cadkit
    code. CTC 02 Fillet3 reads 46 edges, FTC 06 Fillet2 18. Across 201 sample parts, 6 fillets newly
    convert (the four NIST targets and two on other public parts), no existing fillet/chamfer
    selection changes. Blockers: 10 -> 5 with Fillet_c, 4 -> 2 fillet-only; fully decoded 173 -> 175.
    Priority rebuilds stay 0 of 3 (0 gained, 0 lost). Four previously matching public fillet/chamfer
    parts rebuild 4 of 4 before and after: one first timed out at 243 seconds with other checks
    running, then matched on its single-part retry (223 seconds), so no match was lost. Triage:
    FTC 06 2018 reaches Boss-Extrude1 and
    stops before Boss-Extrude2, before either fillet; its 2015 reference doesn't evaluate. CTC 02
    still has its 3D sketch. Gaps beyond 72 bytes, or other group headers, remain unproven and are
    left unread. Parity: 204/0 features, 101 designs with 2 imported-STEP text diffs, reproduced
    identically by the archived pre-change Python and Rust readers (so pre-existing, not from this
    change). Python: 90 tests pass; Rust: 5 tests pass. The census report itself initially
    stopped on a console Unicode encode error while printing a part name; its saved JSON was
    complete, and comparing that JSON (rather than Python tuples against JSON lists) gave the result
    above.

184. **NIST after the wider fillet/chamfer edge groups.** Full 19-part check on SolidCraft 0.50.0:
    exact structural matches remain **0 of 19**. Fully decoded parts attempting a rebuild rose from
    10 to **12**, and reader blockers fell from 9 to **7**. Both FTC 06 saves now reach a rebuild
    instead of stopping on unread Fillet2. CTC 02's Fillet3 is read in both saves; CTC 02 now stops
    only on its 3D sketch. FTC 06 2018 reports no build to compare and its 2015 reference still
    does not evaluate, so reading the fillets is progress, not a success claim. Parity on public
    samples: 54 files / 43 designs, zero differences. Python: 90 tests OK; Rust: 5 tests OK.

185. **Revolves were written but not rebuilt (F-033).** The feature reader and design writer had
    revolve/revolved-cut support, but `_sequential` / `sequential` omitted both kinds from the
    feature order, so a rebuild skipped their material while still trying later features. They are
    now built at their own tree position in Python and Rust, and later revolves/revolved cuts are
    included in the remaining-material bounds. The sketch record supplies the profile and candidate
    axes; the affected public samples checked use full turns. The interrupted worker also left a
    duplicated test class, removed before the runs. Python: 89 tests OK; Rust revolve test OK.
    Older files whose construction centrelines are not numbered remain limited by F-039.

186. **Body and face colours (F-014).** The generic Parasolid attribute reader kept the nodes but
    did not put their values on the neutral bodies/faces or into STEP. Published samples show a
    face's `SDL/TYSA_COLOUR` and a body's `SDL/TYSA_COLOUR_2`, each with three real RGB fractions
    in 0…1. Both converters now read those values, preferring the body form where both occur, and
    write AP214 `COLOUR_RGB` / `STYLED_ITEM` chains for the owning body or face. Identical RGB
    values share one presentation style. SolidCraft opens the styled STEP without errors. Python:
    90 tests OK; Rust: 4 tests OK, including body and face styles and unchanged no-colour output.


187. **The two rebuild losses also occur on the unmodified base (B-023).** On SolidCraft 0.50.0,
    the base and each feature branch report the same two misses at the 240-second budget, so the
    revolve and colour changes did not cause them. A base-only retry at 300 seconds recovered one
    part in 306 seconds including conversion/evaluation overhead. The other, PartT8, completed its
    whole three-feature tree in 399 seconds but its closest result was 0.1265% away from the saved
    solid, just beyond the 0.1% match threshold. Triage reached Fillet2, the final feature, with no
    kernel error. This is recorded as a separate base/kernel investigation; the threshold was not
    relaxed and the old baseline was not edited to hide it.


188. **PartT8's mismatch is area-only (B-023).** Detailed base-only measurement on SolidCraft
    0.50.0: reference volume 3016.2494 mm³ / area 2334.0546 mm²; closest rebuild 3016.4740 /
    2337.0065. Volume differs by 0.2246 mm³ (0.0075%), but area is 2.9519 mm² higher (0.1265%),
    so the mismatch signature is a missing or wrong fillet/chamfer, not a general size error or a
    reason to relax the 0.1% threshold. Bounding boxes agree within the check tolerance and the
    timeline has no error. Combined public integration: 100 Python tests OK, all Rust tests OK,
    feature parity 54/0 and design parity 43/0. The combined regression has no losses beyond the
    two already reproduced on the unmodified base.


189. **PartT8 tangent-option experiment reverted.** `tangent_chain: false` produced an exact
    match when forced for every fillet, proving the saved solid and selected edges can agree on
    SolidCraft 0.50.0. Adding it as a searched per-fillet option did not match within the production
    budget: propagation-first and picked-first both exhausted it, and grouping all picked-only
    candidates first also failed. The extra candidates increased search cost and provided no accepted
    improvement. All writer, search and test changes from that experiment are removed; B-023 stays
    open with the area-only mismatch documented. No more work on PartT8 in this batch.


190. **A five-minute main rebuild budget.** Python and Rust used 240 seconds while triage used
    90; the user asked for 300. New constant tests first failed on 240, then passed on 300 in both
    implementations. The full regression on SolidCraft 0.50.0 improved from 19 to **20 of 22**:
    the base part that had matched with a manually raised budget now matches with the default.
    PartT8 remains the separate B-023 area-only mismatch. Full suite: 101 Python tests OK, all
    Rust tests OK.


191. **Body Move/Copy rotations convert as rigid matrices.** The reader already returned nine
    rotation doubles and a translation, but rejected every non-identity rotation. Both Feature
    types now retain the rotation and `solid.move` receives its row-major 4 x 4 matrix (metres
    converted to mm); identity rotations keep the previous translation-only output. Four public
    parts / five affected features now read as `move` instead of TBD. One affected part is fully
    decoded; the others have unrelated mirror, sheet-metal, loft or sketch blockers. None has an
    exact rebuild yet. New Python and Rust tests cover a 90-degree matrix and identity output;
    full suite: 103 Python tests OK, all Rust tests OK. The full-convert test also now excludes
    `~$` lock files, matching the other discovery tools rather than treating them as CAD files.


192. **Full-folder conversion batches with long timeouts.** `convert_sample.py` now accepts a
    directory as well as a list file, uses the existing lock-file exclusion, and takes `--timeout`
    (default unchanged at 900 seconds). Results flush after every part and aggregate progress prints
    every ten. New tests prove directory filtering and a requested 3600-second subprocess timeout.
    A background batch of **356 GrabCAD parts** is running with eight jobs and 3600 seconds per part;
    its JSONL stays in the private check directory. `feature_blockers.py` separately ranks missing
    feature classes. Results are not claimed until the batch completes.


193. **Full-batch memory limits after a system crash.** The first 356-part batch used eight
    workers and was lost with its feature-blocker process. No converter processes remained on
    inspection. `convert_sample.py` now partitions files by size: those over 250 MB run through
    `run_batch(..., jobs=1)` before ordinary files use the selected worker count. The regression
    test observes one worker for a 2 MiB test file and two for a small file. The restarted batch
    uses two ordinary workers and one for large files, with no competing heavy jobs. Assemblies
    are not included in this Rust-plugin part runner; they need a separate conservative checker.


194. **Rust Cartesian-product allocation caused the conversion memory spike (B-024).** One small
    NIST part has sketch plane counts whose product is **293,932,800,000**. Rust's `product`
    allocated every combination before trying the first; the same file now uses a lazy `Product`
    iterator with ordering and empty-input tests. A 43 GB process was killed before another BSOD.
    `tools/process_limit.py` adds a psapi working-set watchdog and process-tree kill. An attempted
    Windows Job Object implementation failed with error 24 and was replaced by the watchdog, which
    passes a real 512 MiB allocation test and drains stdout/stderr without deadlocking large reports.
    The full 356-part GrabCAD batch is running with two ordinary workers, large files serial, and a
    2048 MiB cap. It has not completed, so no final success rate is claimed yet.


195. **Through-all bosses indexed a previous feature that did not exist (B-025).** Twelve of the
    356 full-batch parts panicked with index `18446744073709551615` in `search.rs`. An imported
    body before the first through-all boss made `first` false even though `sh.order` had no earlier
    feature, so `sh.order[i - 1]` underflowed. Both previous-feature paths now require `i > 0`.
    A regression test reproduces the exact panic and passes. The first affected file now returns a
    normal timeout instead of a crash.


196. **Full 356-part GrabCAD baseline.** The 12-worker batch completed with a 2 GiB per-process
    watchdog and no memory-limit terminations. Exact feature-tree rebuilds: **26 (7.3%)**. Other
    outcomes: 30 built without a match, 100 no-builds, 62 TBD, 117 without feature history, 8
    unnumbered streams, 12 crashes and 1 error. The crashes were the previous-feature underflow,
    fixed as B-025. The completed JSONL is now the regression baseline. Success is counted only
    from exact structural rebuilds, not from files that opened as imported solids.


197. **Triage before choosing the next small fixes.** The first whole-folder blocker census timed out
    at 15 minutes with its output still buffered, producing an empty report; it was rerun unbuffered
    with a longer budget. The completed 356-part JSONL already ranks the feature-class blockers without
    repeating conversions: 11 parts with general 3D sketches, 7 with unread fillet selections, and 4
    with unread split tools. CTC 01 (2018) completes all ten solid features in triage but still does
    not match, so no single missing feature was patched. Four public parts' 15 unread splits were
    inspected in the raw records. One has a `moCompProfile_c` feature reference to its preceding
    sketch; the other 14 do not, so that one-record layout was documented but not promoted into a
    one-part production shortcut. The batch's single `no bodies converted` error is also not a reader
    crash: its 976-byte Parasolid partition contains 21 metadata/schema nodes and no `BODY` node.
    No geometry was invented for it. Full parity after the lazy-product and previous-feature fixes:
    54 files / 43 designs, zero differences.

198. **Linear patterns with `FIX_n` spacing/count dimensions.** Ten unread linear patterns in two
    public parts had no `D1`/`D3`; each had exactly two `FIX_n` dimensions. Across all ten, the
    lower consecutive suffix holds 20 mm spacing and the next holds 2 instances. New helper tests
    failed before implementation and now guard the consecutive-pair, extra-dimension and fractional-
    count cases. Python and Rust accept only that narrow layout and preserve ordinary dimensions.
    Both parts become fully decoded, with all five patterns reading count 2 / spacing 20 mm. Their
    updated release-binary rebuilds finish in about 96 seconds each: both now attempt a rebuild but
    report no build to compare, so exact structural success has **not** improved. This moves those
    two parts from TBD to the ordinary no-build queue rather than claiming a match. Python: 110
    tests OK (5 skipped). Rust: all tests OK. The first quick rebuild invocation used the old example
    binary while it was still compiling, reproduced the old TBD result, and was discarded before the
    verified rerun above. Targeted Python/Rust parity on both parts: 2 / 2 feature trees and
    2 / 2 default designs identical. The 22-part regression is 20 / 22 with zero new losses: only
    the already documented B-023 PartT8 area-only mismatch differs from its older baseline.

199. **Mid-plane extrude end type (F-035), with help from cadkit-kernel.** Its
    `crates/ck-sldprt/src/sketch.rs` identified the end type as the u32 sixteen bytes into
    `moEndSpec_c`. Direct public-file checks confirmed type 6 on NIST FTC 10 and seven other
    mid-plane extrudes across six public sample files; type-0 blind extrudes store zero there.
    Python and Rust now read only this supported case, write a symmetric total-distance extrude
    even if handed a one-sided choice, and offer only the symmetric direction to the rebuild search.
    Focused regressions failed before the change (three Python directions instead of one; no Rust
    reader or field) and pass after it. Worker-isolated verification: 110 Python tests (30 skips),
    14 Rust tests, and 42 files / 36 designs with zero Python/Rust differences. The 55 mm mid-plane
    shaft rebuild matches in 2 seconds; another affected sample keeps its previously reported -7.1%
    mismatch. Other end conditions remain undecoded. Combined integration: **112 Python tests OK
    (5 skipped), all 16 Rust tests OK**, and full public parity of 54 files / 43 designs with zero
    differences. The combined 22-part regression is 20 / 22 with zero new losses; only B-023 PartT8
    differs from its older baseline. The 3D-sketch worker crashed twice without saving code or new
    record evidence, so that bounded lane was stopped and F-006/F-036 remains open.


200. **Full NIST check on the combined pattern and mid-plane readers.** All 19 parts were rerun on
    SolidCraft 0.50.0. The result is unchanged: **0 / 19 exact feature-tree matches**, 12 / 19 fully
    decoded and attempting a rebuild, and 7 / 19 reader-blocked. CTC 01 (2018) reports +1.8% material
    as its closest mismatch this run, versus +2.3% in the previous report; both are failed matches,
    so this is not counted as success or a completed fix. FTC 10's mid-plane extrude now reads
    directly as symmetric, but its general 3D sketch still blocks a rebuild. A new full 356-part
    GrabCAD run has started with 12 workers, a 300-second per-part budget and a 2 GiB watchdog;
    no updated full-batch percentage is claimed until it completes.

201. **Parallel whole-folder blocker census.** The original serial `feature_blockers.py` timed out
    at both 15 minutes and 60 minutes before printing its final aggregate. It now has the same
    process-pool pattern as the other readers, with `--jobs` defaulting to 8 and no script execution
    on import. A new aggregation test separates single blockers, shared blockers, fully decoded parts
    and unread files. Serial and eight-job NIST reports are byte-identical: 12 fully decoded, 3 parts
    blocked only by general 3D sketches, 4 with sketch text and 1 with variable-radius fillets.
    Full Python suite: **113 tests OK (5 skipped)**. The whole-folder parallel census will run after
    the conversion batch, so its CPU use cannot distort that benchmark's per-part timeouts.

202. **Complete combined 356-part benchmark: 29 exact rebuilds (8.1%).** The first pass used an
    outer 300-second timeout, equal to the internal search budget: 98 parts were killed before they
    could emit their normal result. Those 98 were rerun with a 600-second outer limit, producing 82
    no-builds and 16 built mismatches. Merged final outcomes: **29 exact (8.1%, was 26 / 7.3%)**, 30
    built mismatches, 111 no-builds, 60 TBD, 117 without feature history, 8 unnumbered streams, no
    crashes and 1 empty-body error. All three new exact matches were formerly crash cases fixed by
    B-025. Zero previous matches were lost, zero new crashes appeared, and no process hit the 2 GiB
    memory cap. The two `FIX_n` parts account for the TBD reduction; they are no-builds, not matches.
    The merged private JSONL is the next regression baseline.

203. **Bounded, incremental blocker subprocesses.** The eight-job in-process census also hit its
    overall timeout without a final aggregate, so worker count alone did not isolate a slow file.
    Each part now has its own subprocess, a 300-second timeout and a 2 GiB memory cap; `--out` writes
    one JSONL record per completed part. Timeouts and memory limits become explicit blocker categories
    instead of suppressing the other results. New mocked tests verify the limits and timeout handling.
    The first NIST comparison found identical counts but unstable tie ordering from completion-order
    aggregation; tied report rows are now alphabetical. The rerun is byte-identical to the prior NIST
    report. Full Python suite: **115 tests OK (5 skipped)**. The bounded full-folder census is running.

204. **The bounded full blocker census completes.** All 356 parts returned records in 348 seconds
    with eight workers; none was unread or hit the memory cap, and one hit its per-part timeout.
    **289 parts are fully decoded at the reader level** (not exact rebuild matches). Single-blocker
    leaders: 8 pre-2015 numbering, 5 sketch-text-only, 4 general-3D-sketch-only, 4 curve-pattern-only,
    3 fillet-only, 3 InkMarkup-only and 2 split-only. Across all blockers: 13 sketch text, 11 general
    3D sketches, 8 sheet-metal class groups, 7 fillets and 7 sketch planes. The two straight spaced
    curve patterns are the small next increment; genuinely curved or unspaced paths are not guessed.

205. **Straight, uniformly spaced curve patterns.** The four curve-pattern-only parts split into two
    narrow readable cases and two that must stay TBD. In the readable records, KeyWords supplies D1
    count / D3 spacing and the pattern directly references the feature id of an otherwise-unused,
    one-line, nonzero path sketch. The reader requires a unique referenced candidate and no arcs or
    circles; it converts the straight path to a linear pattern, using the selected sketch plane to
    derive exact forward/reverse model directions. The two usable parts are fully decoded with counts
    5 / 16 and spacings 0.8 / 0.25 mm. Two other parts have count 2 but no spacing and remain unread.
    Tests failed before the helpers existed and now cover unique path selection and direction. Full
    suite: **117 Python tests OK (5 skipped), all 18 Rust tests OK**. Four feature trees and two
    default designs have zero Python/Rust differences. Real rebuilds of both newly decoded parts end
    at the 300-second search budget with no build to compare, so exact full-batch success remains
    **29 / 356 (8.1%)** pending any later full rerun; no new match is claimed. Earlier-feature search
    work on these two is left bounded, not allowed to consume the next batch. Full public parity:
    54 files / 43 designs, zero differences. The 22-part regression remains 20 / 22 with zero new
    losses; only the known B-023 PartT8 mismatch differs from its older baseline.

206. **B-023 fixed by respecting the selected fillet edges.** The earlier per-fillet tangent search
    multiplied candidates and missed within 300 seconds, but forcing picked edges only had matched.
    The production writers now set `tangent_chain: false` on fillets directly: the file already
    supplies the selected edge set, so SolidCraft must not add implicit tangent-propagated edges.
    There are no new search branches, no timeout increase and no threshold relaxation. Python and
    Rust writer tests failed before the field was added and pass after it. PartT8 matches through
    Python in 269 seconds and through the Rust release converter in 267 seconds (11 candidates, no
    timeout). The complete regression is **21 of 22, with 0 gained and 0 lost**; the baseline is
    restored. PartT8 was already one of the 29 exact matches in the full public batch, so this fix
    changes its reliability, not that batch's count. Full tests and parity: **118 Python tests OK
    (5 skipped), all 19 Rust tests OK**, and 54 files / 43 designs with zero Python/Rust differences.
    NIST after the fix: **0 / 19 exact**, 12 rebuild attempts and 7 reader-blocked, unchanged in
    outcome. CTC 01's closest extra-material mismatch is +0.6% this run (was +1.8%), still a mismatch
    rather than a success. A fresh full-model regression is being checked before any dev push.

207. **Twenty-worker checks and the full private model tree.** The user asked for more parallelism
    without stopping the active full public batch. Its live 12-worker pool cannot be resized in place,
    so it is left intact. Future feature checks, triage, blocker scans and external batches now default
    to 20 workers; `convert_sample.py` and `rebuild_set.py` already defaulted to 20. The private folder
    is accessible and **3,998 private parts** are indexed for a local full scan. Ordinary private
    conversions will use 20 workers with 2 GiB caps (40 GiB total ceiling) and large files will run
    singly. Only aggregate outcomes may enter public reports. New default tests failed at 8 and pass
    at 20, including an explicit override test; the focused parallel/check suites are 9 tests OK.

208. **Roadmap changed into a work-allocation queue.** It now lists open scopes with issue IDs and
    TBD status, plus an active owner/branch table to prevent duplicate work. Interrupted workers do
    not leave a claim. Detailed measurements, completed batches and local runner quantities move out
    of the roadmap: current results belong in `docs/dev-build.md`, and experiments in this working log.
    The clean-room, parity, privacy and release gates remain, with no private identifiers published.

209. **Full public regression after the selected-edge fillet fix.** All 356 parts completed with
    12 workers and a 600-second outer timeout: **29 exact matches (8.1%)**, 30 built mismatches, 113
    no-builds, 58 TBD, 117 without feature history, 8 unnumbered streams and 1 empty-body error.
    Against the previous final baseline: zero matches lost, zero new crashes and zero memory-limit
    events. The two straight curve-pattern parts moved from TBD to no-build; exact count is unchanged.
    The private tree is split deterministically into 40 release models and 3,958 remaining models so
    the full scan does no duplicate conversion. The release sample is running with 20 workers, 600-
    second outer timeouts and 2 GiB caps. Only aggregate outcomes will be recorded publicly.

210. **Private release sample passes.** The 40-model batch completed with 20 workers: **6 exact
    feature-tree rebuilds (15%)**, 5 built mismatches, 10 no-builds, 6 TBD, 12 without feature
    history and 1 missing-geometry error. No previous match was lost; there were no crashes or memory-
    limit events. These aggregate counts are all that enter public documentation. The private baseline
    stays in the local check directory. The remaining 3,958-model scan is now running locally with 20
    workers, incremental JSONL and the same limits; no partial success rate is claimed for it.

211. **Release 0.18.0 prepared.** The changelog's complete post-0.17.3 fix list is retained under
    the new version, with the 43 GB eager-product failure, lazy iteration, watchdog, previous-feature
    crash correction and measured regressions called out explicitly. B-023, B-024 and B-025 are fixed
    in 0.18.0. `logs/survey-0.18.0.md` records 21 / 22 regression matches with zero losses, 29 / 356
    public exact rebuilds, unchanged 0 / 19 NIST structural success, 6 / 40 private-sample exact
    rebuilds, tests and parity. No private identifiers are included. The long remaining private scan
    is diagnostic and is not awaited. `origin/main` is an ancestor of this history, so the release can
    be fast-forwarded normally after the version-stamped test run.

212. **Version-stamped 0.18.0 tests pass.** Python: **120 tests OK (5 skipped)** in 226 seconds.
    Rust: **all 19 tests OK**. The first Rust attempt hit Windows LNK1104 because the active private
    scan had `convert_one.exe` open, not because of a test or code failure; the unchanged standard
    Cargo test command passed in an isolated target directory, which was then removed. The first
    Python harness attempt timed out at 300 seconds under the private scan's CPU load without a test
    failure; a 900-second outer allowance completed normally. No private process was stopped and no
    release test was skipped.

213. **A private two-boss part now rebuilds normally (B-026).** The part reused one sketch for
    different contour sets. Blind direction trials could not produce a valid candidate. Saved
    `FACE_ID_2001` surfaces identify the contours belonging to each boss; saved circular edges resolve
    an existing point as a misread circle's centre and settle arc senses, including two arcs that
    share an existing endpoint. Each shared-sketch use is filtered independently and the clone is
    emitted before its boss. Two-way boolean differences found only residual slivers within tolerance,
    rather than relying on volume alone. The normal Python rebuild now matches in
    about eight seconds. Full Python suite: **123 tests OK (5 skipped)**. Rust parity and full
    regressions are still required. No private model name,
    path, dimensions or per-file report is committed. B-027 remains open for stronger general shape
    acceptance beyond volume/area/box checks.

214. **B-027: final acceptance needs geometric difference, not just totals.** The private sample's
    metric match was not treated as sufficient verification, and its remaining retry was stopped.
    `verify.same_shape` now performs candidate-minus-reference and reference-minus-candidate through
    SolidCraft, requiring one target/tool body each and rejecting failed operations. Both differences
    must fit the existing relative volume tolerance; volume/area/box remain the first filter. Tests
    show identical solids pass, a shifted solid with identical volume and area fails, and a rebuild
    whose shape check fails cannot be accepted. The selected private part passes this stricter Python
    path. The same check is being ported to native Rust and the plugin's staged host commands. Full
    Python suite with B-026, B-027 and local image output: **127 tests OK (5 skipped)**. No
    private identifiers or measurements are recorded here. B-026 is not a release claim until that
    combined verification passes.

215. **B-026/B-027 verified through the real plugin host.** Local comparison images now require
    an accepted design with solid-making features: an imported-solid fallback cannot be passed as
    the rebuilt side, and a failed rebuild removes its stale comparison. The selected private
    two-boss case passes native Rust on its first try and the real host in about four seconds. Its
    saved host output contains two sketches, two boss extrudes and two editable depths, with no
    import feature. The previous six matching private parts all pass the stronger Python gate;
    all six comparison images come from their structures, with zero errors. Python: **130 tests
    OK (5 skipped)**. Rust: **all 32 tests OK**. The stopped full private scan was not restarted.

    The host investigation found two distinct implementation errors. `component.insert_design`
    expects the in-memory document as JSON text, not a JSON object; after correcting that call,
    SolidCraft still denied it because private evaluation is deliberately read-only. That denial
    was not bypassed and the acceptance threshold was not relaxed. Native checks retain two-way
    boolean differences. The host now uses exact face surface/area/centre evidence instead, rejecting
    missing, inexact or mismatched face data. An edge-based prototype was not used because circular
    seams can reverse equivalent edge endpoints and midpoints. The remaining bug was `Timed` not
    forwarding the host's `shape_matches` override; a direct regression test now covers that dispatch.
    No public or NIST success-rate change is claimed from this focused private verification. No
    private model names, paths, dimensions, geometry or per-file results are included.


216. **B-028: shared-sketch dimensions and excess points, fixed only where proven.** Raw inspection
    showed that the first parameter of a dimension could be stale, and that scanning from it through
    later parameters mixed in unrelated handles. The reader now chooses the later same-name parameter
    within the dimension and bounds its handles correctly. Radius/diameter recovery requires agreement
    among KeyWords, a raw parameter and an existing curve. Point/point and point/line constraints are
    written only for a unique geometry-backed reading; handle zero can address the origin directly.
    Contour filtering now deduplicates handles, renumbers curve references after removal, retains a
    required reference line as construction, and removes unrelated points and point-only relations.

    The selected private two-boss case now retains three driving dimensions on its outer sketch and
    two on its circle-only shared use; the latter has four points including the fixed origin, instead
    of the former unrelated point set. Both sketches and both boss extrudes survive the real plugin
    host, with no import feature. Native conversion matches on its first try under the 2 GiB watchdog.
    The six previous private matches still pass with structure-only images and zero errors. Python:
    **135 tests OK (5 skipped)**; Rust: **all 35 tests OK**. Private parity: one file and one design,
    zero differences. No private names, paths, values or geometry are included.

    A remaining point-distance handle layout and an offset association are deliberately unconverted
    (B-028), so this is not a claim that the sketch is fully dimensioned. The approved clean-room
    reference's record-position interpretation did not resolve the sparse handles. Some restored
    constraints also triggered SolidCraft SMLib boolean failures despite the candidate evaluating
    correctly. Native/Python acceptance now uses exact face surface/area/centre evidence only when a
    boolean is unavailable; a measured difference beyond tolerance still rejects, and missing/inexact
    face evidence still rejects. Tests cover both the face-backed acceptance and the prohibition on
    overriding a measured mismatch. The stopped full private scan and public-model investigations
    were not restarted; no NIST improvement is claimed.


217. **B-028 broadened to other private models, without overclaiming.** Two further models showed
    unit conversion, generic/horizontal/vertical distance substitution, unsupported line-to-line
    dimensions and unresolved handles. Generic point distances now require Euclidean agreement;
    horizontal and vertical classes accept only their own component. This makes a unique reference
    possible in the boss/cut example rather than accepting several false candidates. Circle recovery
    can replace an existing misclassified dimension only when the shown value, raw parameter and an
    existing curve agree; otherwise it stays skipped.

    The real host now opens the boss/cut example as two sketches and two extrudes, with all four
    sketch dimensions and no imported-solid feature, in about one second. The revolve example still
    falls back after about 166 seconds; an additional vertical dimension reads in its writer, but the
    other unresolved dimensions and feature-rebuild blockers are not fixed. These are separate results,
    not a blanket dimension or NIST success claim. The original shared-sketch case retains its restored
    dimensions, and the six previous private matches remain six of six with structure-only images and
    zero errors. Private model names, paths and measurements remain local. Remaining reference layouts,
    `sgLLDist` and offsets stay in B-028 as TBD.


218. **Private checking now cycles and reads structure across the model set.** The existing Rust
    sample runner now writes the final design when asked, reports expected versus delivered sketch
    dimensions, supports pinned cases and rotates shuffled chunks so every path is covered before
    reshuffling. Cycle results merge into a private baseline without converting a new loss into the
    accepted baseline. The bounded first cycle completed with **2 editable rebuilds and 4 of 22
    expected dimensions retained**; its conversion error and geometry-warning case stay in the local
    diagnostics. Continuous cycling was then started with per-process memory and time limits. A
    separate full private structural blocker census is running with lower parallelism alongside it.
    No private names, paths, model inventory or per-file results enter this log. Tooling tests cover
    full-cycle coverage, pinned cases, missing saved dimensions and preservation of a regression.
    Full checks: **138 Python tests OK (5 skipped), all 35 Rust tests OK**; privacy check clean.


219. **Full private structural census completed.** All 3,998 selected private parts returned a
    structural record: **3,442 fully decoded at reader level**, seven unread and one read timeout.
    These are not geometric matches or dimension-complete models. Common blockers any-part: 51
    general-3D-sketch, 50 sketch-plane, 49 Fillet_c, 40 extrusion, 36 external-feature and 32
    sketch-text records. Single-blocker groups include 101 pre-2015 numbering, 19 Fillet_c, 16
    edgeRadiusObject_c, 13 emboss and 13 sketch-text cases. The narrow radius/fillet group is the
    next investigation because several independent examples can be compared. No private filenames,
    paths, geometry or per-file outcomes are recorded. The continuous conversion/dimension cycles
    remain active while this reader work proceeds.


220. **B-029 reader fix, with rebuild result explicitly unresolved.** Three independent private
    models with `edgeRadiusObject_c` as their only reader blocker have valid named Fillet records,
    feature IDs and the same parameter/face-reference layout as `Fillet_c`. A guarded mapping now
    reads their radii and edge groups in Python and Rust. All three are fully decoded at reader level;
    **none produces an accepted rebuild**, and each reaches the 300-second budget with no complete
    candidate. This does not yet implicate the fillet kernel: earlier features may stop the sequential
    search. The timeout moves to F-006 for prefix profiling, not a larger budget. The six previous
    private matches remain six of six with zero errors. Full tests: **139 Python OK (5 skipped), all
    35 Rust OK**. The ordinary Rust target was locked by the continuous converter; the unchanged
    standard Cargo test command passed in an isolated target without stopping the cycles. The
    roadmap now states that reader decoding, geometric rebuilding and delivered dimensions are
    separate acceptance gates. No private identifiers or measurements are included.
