# SolidCraft feature request: Extrude cut "flip side" (keep the profile, remove the rest)

**What:** an option on `solid.extrude` with `operation: cut`, e.g. `flip: true`. Within the
extrude's extent, it removes everything *outside* the selected profiles and keeps what's inside.
This is SolidWorks' "Flip side to cut", which is common in SolidWorks parts.

**Checked:** `C:\dev\solidcraft` at 1f8df8628 (main) and every remote branch. Nothing for it in the
commit messages or the code (`flip_side`, "flip side", "cut outside").

**Why sw2sc needs it:** NIST CTC 03's Cut-Extrude1 is one. Read as a plain cut, its faces face the
wrong way from the part's.

**Workaround in sw2sc meanwhile:** a copy of the sketch with a 20 m square added around its loops,
then a cut of that square's region (its outer loop the square, the sketch's loops its holes):
`profiles: {type: curves, loops: [[the square's four lines]]}`. Checked on a 100 × 100 × 20 box
with an r10 circle cut 10 deep and flipped: 103141.59 mm³, as expected. Its limits: it isn't
editable as one feature, and the square's size is a guess at "larger than the part".

**Also seen (Offset Face):** on CTC 03 after Cut-Extrude1, `offset_face` by -5.08 on the pocket
faces at z = 111.125 fails with "offset faces: the wall is too thick: it leaves no room inside
the body". Picking two faces in one call gives "no face at" the second point, which is a point
`model.faces` itself reported. Moving a face on a simple notch works in both directions.
SolidWorks' Move Face lets the neighbouring faces follow here.
