"""Combine part STEP files into one STEP file that places each part, for the Import feature of
a linked subassembly.

Each source file's geometry and representations are kept (entity numbers shifted); its
product entities are dropped. One root product's shape representation places every part
with a MAPPED_ITEM, the AP214 way of instancing a representation (ISO 10303-43).
Only STEP text written by step.py is combined: one entity per line.
"""
from __future__ import annotations

import re

from . import __version__

_ENTITY = re.compile(r"^#(\d+)=(.*);$")
_REF = re.compile(r"#(\d+)")
_DROP = ("APPLICATION_CONTEXT(", "APPLICATION_PROTOCOL_DEFINITION(", "PRODUCT_CONTEXT(", "PRODUCT(",
         "PRODUCT_RELATED_PRODUCT_CATEGORY(", "PRODUCT_DEFINITION_FORMATION(", "PRODUCT_DEFINITION_CONTEXT(",
         "PRODUCT_DEFINITION(", "PRODUCT_DEFINITION_SHAPE(", "SHAPE_DEFINITION_REPRESENTATION(")


def _num(x: float) -> str:
    s = repr(float(x))
    if "e" in s or "E" in s:
        m, e = s.lower().split("e")
        return (m if "." in m else m + ".") + f"E{int(e)}"
    return s if "." in s else s + "."


def _str(s: str) -> str:
    return "'" + "".join(ch if 32 <= ord(ch) < 127 and ch not in "'\\" else ("''" if ch == "'" else "_") for ch in s) + "'"


class StepAssembly:
    def __init__(self, name: str):
        self.name = name
        self.lines: list[str] = []
        self._reps: dict[int, tuple[str, str, str]] = {}  # id(text) -> (rep, origin, context)

    def add(self, text: str) -> str:
        self.lines.append(text)
        return f"#{len(self.lines)}"

    def _take(self, step: str) -> tuple[str, str, str]:
        """Copy a part file's entities in; return its (shape representation, origin axis,
        geometric context) ids."""
        key = id(step)
        if key in self._reps:
            return self._reps[key]
        body = step.split("DATA;", 1)[-1].split("ENDSEC;", 1)[0]
        entities = []
        for line in body.splitlines():
            m = _ENTITY.match(line.strip())
            if m:
                entities.append((int(m.group(1)), m.group(2)))
        kept = [(n, t) for n, t in entities if not t.startswith(_DROP)]
        base = len(self.lines)
        renum = {n: base + i + 1 for i, (n, _) in enumerate(kept)}

        def fix(t: str) -> str:
            return _REF.sub(lambda m: f"#{renum.get(int(m.group(1)), 0)}", t)
        rep = origin = ctx = None
        for n, t in kept:
            out = fix(t)
            if re.search(r"#0\b", out):
                raise ValueError("part STEP refers to a dropped entity")
            self.lines.append(out)
            if t.startswith(("ADVANCED_BREP_SHAPE_REPRESENTATION(", "MANIFOLD_SURFACE_SHAPE_REPRESENTATION(")) and rep is None:
                rep = f"#{renum[n]}"
                refs = _REF.findall(out)
                origin, ctx = f"#{refs[0]}", f"#{refs[-1]}"
        if rep is None:
            raise ValueError("part STEP has no shape representation")
        self._reps[key] = (rep, origin, ctx)
        return self._reps[key]

    def write(self, placements: list[tuple[str, str, list]]) -> str:
        """placements: (part name, part STEP text, 4x4 column-major mm matrix)."""
        items, ctx = [], None
        maps: dict[int, str] = {}
        for name, step, m in placements:
            rep, origin, pctx = self._take(step)
            ctx = ctx or pctx
            if id(step) not in maps:
                maps[id(step)] = self.add(f"REPRESENTATION_MAP({origin},{rep})")
            loc = self.add(f"CARTESIAN_POINT('',({_num(m[3][0])},{_num(m[3][1])},{_num(m[3][2])}))")
            z = self.add(f"DIRECTION('',({_num(m[2][0])},{_num(m[2][1])},{_num(m[2][2])}))")
            x = self.add(f"DIRECTION('',({_num(m[0][0])},{_num(m[0][1])},{_num(m[0][2])}))")
            target = self.add(f"AXIS2_PLACEMENT_3D('',{loc},{z},{x})")
            items.append(self.add(f"MAPPED_ITEM({_str(name)},{maps[id(step)]},{target})"))
        if not items:
            raise ValueError("nothing to place")
        app = self.add("APPLICATION_CONTEXT('automotive design')")
        self.add(f"APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,{app})")
        pctx = self.add(f"PRODUCT_CONTEXT('',{app},'mechanical')")
        prod = self.add(f"PRODUCT({_str(self.name)},{_str(self.name)},'',({pctx}))")
        pdf = self.add(f"PRODUCT_DEFINITION_FORMATION('','',{prod})")
        pdc = self.add(f"PRODUCT_DEFINITION_CONTEXT('part definition',{app},'design')")
        pd = self.add(f"PRODUCT_DEFINITION('design','',{pdf},{pdc})")
        pds = self.add(f"PRODUCT_DEFINITION_SHAPE('','',{pd})")
        rep = self.add(f"SHAPE_REPRESENTATION({_str(self.name)},({','.join(items)}),{ctx})")
        self.add(f"SHAPE_DEFINITION_REPRESENTATION({pds},{rep})")
        head = ["ISO-10303-21;", "HEADER;", "FILE_DESCRIPTION(('assembled by sw2sc'),'2;1');",
                f"FILE_NAME({_str(self.name + '.step')},'1970-01-01T00:00:00',(''),(''),'sw2sc {__version__}','sw2sc','');",
                "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 3 1 1 }'));", "ENDSEC;", "DATA;"]
        body = [f"#{i + 1}={t};" for i, t in enumerate(self.lines)]
        return "\n".join(head + body + ["ENDSEC;", "END-ISO-10303-21;", ""])


def mat_mul(a, b):
    """Column-major 4x4 product a*b (apply b, then a)."""
    return [[sum(a[k][r] * b[c][k] for k in range(4)) for r in range(4)] for c in range(4)]


IDENTITY = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]


def leaf_placements(design: dict, linked_leaves) -> list[tuple[str, str, list]]:
    """Every part placement in a design, in the design's frame: (name, STEP text, matrix).

    linked_leaves(link) returns the placements inside a linked *assembly* design (relative to
    its own frame), or None when the link is a part (its Import STEP is then the part)."""
    feats = {f["id"]: f for f in design.get("features", []) if f.get("type") == "import"}
    links = {int(k): v for k, v in (design.get("links") or {}).items()}
    own = {}  # component -> list of placements in its own frame
    for f in feats.values():
        c = f.get("component", 0)
        link = links.get(c)
        inner = linked_leaves(link) if link else None
        if inner is None:
            own.setdefault(c, []).append((f.get("name", ""), f["step"], IDENTITY))
        else:
            own.setdefault(c, []).extend(inner)
    by_parent: dict[int, list[dict]] = {}
    for o in design.get("occurrences", []):
        by_parent.setdefault(o.get("parent", 0), []).append(o)
    # hidden placements (SolidWorks hidden or suppressed instances) are left out of the geometry
    hidden = {tuple(p) for p in (design.get("visibility") or {}).get("hidden_occurrences", [])}
    out = []

    def walk(comp, m, path, depth):
        for name, step, inner in own.get(comp, []):
            out.append((name, step, mat_mul(m, inner)))
        if depth > 64:
            return
        for o in by_parent.get(comp, []):
            p = path + (o["id"],)
            if p not in hidden:
                walk(o["component"], mat_mul(m, o["transform"]), p, depth + 1)
    walk(0, IDENTITY, (), 0)
    return out
