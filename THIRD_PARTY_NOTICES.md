# Third-party notices

sw2sc includes code ported from the projects below.

## cadkit-kernel

- Source: https://github.com/civilkit/cadkit-kernel (MIT OR Apache-2.0; used here under MIT)
- Ported: `crates/ck-swedit/src/rib.rs` (`rebuild`), as `sw2sc/features.py` `_ribs` / `_rib_from_faces` and `plugin/sw2sc-core/src/features/read.rs` `ribs` / `rib_from_faces`; the rib emitters in `features.design` and `design.rs` follow it.
- Ported: `crates/ck-swedit/src/hole.rs` (`hole_with`: the placement sketch's normal the hole's axis, a standard axis where principal, at its entry), as the plane candidates of `sw2sc/features.py` `_hole_planes` and `plugin/sw2sc-core/src/features/read.rs` `hole_planes`.
- Ported: `crates/ck-sldprt/src/sketch.rs` (`entities`, and the curve records of `build_sketch`), as `sw2sc/features.py` `_entities` / `_curves_from_records` and `plugin/sw2sc-core/src/features/sketch.rs` `entities` / `curves_from_records`.

```
MIT License

Copyright (c) 2026 The CadKit authors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
