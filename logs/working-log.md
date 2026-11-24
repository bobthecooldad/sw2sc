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
