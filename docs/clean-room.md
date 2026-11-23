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
