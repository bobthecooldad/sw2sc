"""Write a neutral B-rep (xtgeom.Body list) as a STEP AP214 file (ISO 10303-21).

Entity choices follow the public AP214 / Part 42 definitions. Coordinates are written in
millimetres (input is metres).
"""
from __future__ import annotations

from . import __version__, nurbs
from .xtgeom import Body, Edge, Face, Loop, Shell, Vertex

SCALE = 1000.0


def _r(x: float) -> str:
    s = repr(float(x))
    if "inf" in s or "nan" in s:
        raise ValueError("non-finite number")
    if "e" in s or "E" in s:
        m, e = s.lower().split("e")
        if "." not in m:
            m += "."
        return f"{m}E{int(e)}"
    return s if "." in s else s + "."


def _str(s: str) -> str:
    out = []
    for ch in s:
        if ch == "'":
            out.append("''")
        elif ch == "\\":
            out.append("\\\\")
        elif 32 <= ord(ch) < 127:
            out.append(ch)
        else:
            out.append("\\X2\\%04X\\X0\\" % ord(ch) if ord(ch) < 0x10000 else "_")
    return "'" + "".join(out) + "'"


class Writer:
    def __init__(self):
        self.lines: list[str] = []
        self.cache: dict = {}
        self.face_sources: dict[str, str] = {}  # STEP id -> Parasolid surface type (diagnostics)

    def add(self, text: str) -> str:
        self.lines.append(text)
        return f"#{len(self.lines)}"

    def point(self, p, scale=True) -> str:
        k = SCALE if scale else 1.0
        key = ("P", round(p[0] * k, 12), round(p[1] * k, 12), round(p[2] * k, 12))
        if key not in self.cache:
            self.cache[key] = self.add(f"CARTESIAN_POINT('',({_r(p[0] * k)},{_r(p[1] * k)},{_r(p[2] * k)}))")
        return self.cache[key]

    def direction(self, d) -> str:
        key = ("D", round(d[0], 14), round(d[1], 14), round(d[2], 14))
        if key not in self.cache:
            self.cache[key] = self.add(f"DIRECTION('',({_r(d[0])},{_r(d[1])},{_r(d[2])}))")
        return self.cache[key]

    def axis2(self, p, z, x) -> str:
        # make x exactly perpendicular to z
        dz = sum(a * b for a, b in zip(x, z))
        x = tuple(a - dz * b for a, b in zip(x, z))
        n = sum(a * a for a in x) ** 0.5 or 1.0
        x = tuple(a / n for a in x)
        return self.add(f"AXIS2_PLACEMENT_3D('',{self.point(p)},{self.direction(z)},{self.direction(x)})")

    # ---- curves ----
    def curve(self, spec) -> str:
        kind = spec[0]
        if kind == "line":
            v = self.add(f"VECTOR('',{self.direction(spec[2])},1.)")
            return self.add(f"LINE('',{self.point(spec[1])},{v})")
        if kind == "circle":
            return self.add(f"CIRCLE('',{self.axis2(spec[1], spec[2], spec[3])},{_r(spec[4] * SCALE)})")
        if kind == "ellipse":
            return self.add(f"ELLIPSE('',{self.axis2(spec[1], spec[2], spec[3])},{_r(spec[4] * SCALE)},{_r(spec[5] * SCALE)})")
        if kind == "bspline":
            return self.bcurve(spec[1])
        raise ValueError(f"curve {kind}")

    def bcurve(self, c: nurbs.Curve) -> str:
        ks, ms = nurbs.compress_knots(c.U, nurbs.knot_eps(c.U))
        pts = ",".join(self.point(p) for p in c.P)
        knots = ",".join(_r(k) for k in ks)
        mults = ",".join(str(m) for m in ms)
        if not c.W:
            return self.add(f"B_SPLINE_CURVE_WITH_KNOTS('',{c.p},({pts}),.UNSPECIFIED.,.F.,.F.,({mults}),({knots}),.UNSPECIFIED.)")
        w = ",".join(_r(x) for x in c.W)
        return self.add(f"(BOUNDED_CURVE()B_SPLINE_CURVE({c.p},({pts}),.UNSPECIFIED.,.F.,.F.)"
                        f"B_SPLINE_CURVE_WITH_KNOTS(({mults}),({knots}),.UNSPECIFIED.)CURVE()"
                        f"GEOMETRIC_REPRESENTATION_ITEM()RATIONAL_B_SPLINE_CURVE(({w}))REPRESENTATION_ITEM(''))")

    # ---- surfaces ----
    def surface(self, spec) -> str:
        kind = spec[0]
        if kind == "plane":
            return self.add(f"PLANE('',{self.axis2(spec[1], spec[2], spec[3])})")
        if kind == "cylinder":
            return self.add(f"CYLINDRICAL_SURFACE('',{self.axis2(spec[1], spec[2], spec[3])},{_r(spec[4] * SCALE)})")
        if kind == "cone":
            return self.add(f"CONICAL_SURFACE('',{self.axis2(spec[1], spec[2], spec[3])},{_r(spec[4] * SCALE)},{_r(spec[5])})")
        if kind == "sphere":
            return self.add(f"SPHERICAL_SURFACE('',{self.axis2(spec[1], spec[2], spec[3])},{_r(spec[4] * SCALE)})")
        if kind == "torus":
            return self.add(f"TOROIDAL_SURFACE('',{self.axis2(spec[1], spec[2], spec[3])},{_r(spec[4] * SCALE)},{_r(spec[5] * SCALE)})")
        if kind == "bspline":
            return self.bsurface(spec[1])
        raise ValueError(f"surface {kind}")

    def bsurface(self, s: nurbs.Surface) -> str:
        uk, um = nurbs.compress_knots(s.U, nurbs.knot_eps(s.U))
        vk, vm = nurbs.compress_knots(s.V, nurbs.knot_eps(s.V))
        rows = ",".join("(" + ",".join(self.point(p) for p in row) + ")" for row in s.G)
        common = (f"({','.join(map(str, um))}),({','.join(map(str, vm))}),"
                  f"({','.join(_r(k) for k in uk)}),({','.join(_r(k) for k in vk)}),.UNSPECIFIED.")
        if not s.W:
            return self.add(f"B_SPLINE_SURFACE_WITH_KNOTS('',{s.pu},{s.pv},({rows}),.UNSPECIFIED.,.F.,.F.,.F.,{common})")
        w = ",".join("(" + ",".join(_r(x) for x in row) + ")" for row in s.W)
        return self.add(f"(BOUNDED_SURFACE()B_SPLINE_SURFACE({s.pu},{s.pv},({rows}),.UNSPECIFIED.,.F.,.F.,.F.)"
                        f"B_SPLINE_SURFACE_WITH_KNOTS({common})GEOMETRIC_REPRESENTATION_ITEM()"
                        f"RATIONAL_B_SPLINE_SURFACE(({w}))REPRESENTATION_ITEM('')SURFACE())")

    # ---- topology ----
    def vertex(self, v: Vertex) -> str:
        key = ("V", id(v))
        if key not in self.cache:
            self.cache[key] = self.add(f"VERTEX_POINT('',{self.point(v.point)})")
        return self.cache[key]

    def edge(self, e: Edge) -> str:
        key = ("E", id(e))
        if key not in self.cache:
            c = self.curve(e.curve)
            self.cache[key] = self.add(
                f"EDGE_CURVE('',{self.vertex(e.start)},{self.vertex(e.end)},{c},{'.T.' if e.same_sense else '.F.'})")
        return self.cache[key]

    def loop(self, lp: Loop) -> str:
        if lp.vertex is not None:
            return self.add(f"VERTEX_LOOP('',{self.vertex(lp.vertex)})")
        oes = [self.add(f"ORIENTED_EDGE('',*,*,{self.edge(e)},{'.T.' if o else '.F.'})") for e, o in lp.edges]
        return self.add(f"EDGE_LOOP('',({','.join(oes)}))")

    def face(self, f: Face) -> str:
        bounds = [self.add(f"FACE_BOUND('',{self.loop(lp)},.T.)") for lp in f.loops]
        s = self.surface(f.surface)
        fid = self.add(f"ADVANCED_FACE('',({','.join(bounds)}),{s},{'.T.' if f.same_sense else '.F.'})")
        self.face_sources[fid] = f.source + (" (approx)" if f.approx else "")
        return fid

    def shell(self, sh: Shell, closed: bool) -> str:
        faces = []
        for f in sh.faces:
            faces.append(self.face(f))
        kind = "CLOSED_SHELL" if closed else "OPEN_SHELL"
        return self.add(f"{kind}('',({','.join(faces)}))")


def write(bodies: list[Body], name: str, face_sources: dict | None = None) -> str:
    w = Writer()
    ctx = w.add("APPLICATION_CONTEXT('automotive design')")
    w.add(f"APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,{ctx})")
    pctx = w.add(f"PRODUCT_CONTEXT('',{ctx},'mechanical')")
    prod = w.add(f"PRODUCT({_str(name)},{_str(name)},'',({pctx}))")
    w.add(f"PRODUCT_RELATED_PRODUCT_CATEGORY('part',$,({prod}))")
    pdf = w.add(f"PRODUCT_DEFINITION_FORMATION('','',{prod})")
    pdc = w.add(f"PRODUCT_DEFINITION_CONTEXT('part definition',{ctx},'design')")
    pd = w.add(f"PRODUCT_DEFINITION('design','',{pdf},{pdc})")
    pds = w.add(f"PRODUCT_DEFINITION_SHAPE('','',{pd})")
    mm = w.add("(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.))")
    rad = w.add("(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.))")
    sr = w.add("(NAMED_UNIT(*)SI_UNIT($,.STERADIAN.)SOLID_ANGLE_UNIT())")
    unc = w.add(f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-05),{mm},'distance_accuracy_value','')")
    gctx = w.add(f"(GEOMETRIC_REPRESENTATION_CONTEXT(3)GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT(({unc}))"
                 f"GLOBAL_UNIT_ASSIGNED_CONTEXT(({mm},{rad},{sr}))REPRESENTATION_CONTEXT('',''))")
    origin = w.axis2((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0))
    solids, sheets = [], []
    for i, b in enumerate(bodies):
        label = _str(b.name or f"{name} body {i + 1}" if len(bodies) > 1 else (b.name or name))
        if b.kind == "solid" and b.outer:
            outer = w.shell(b.outer[0], True)
            if b.voids:
                vs = [w.add(f"ORIENTED_CLOSED_SHELL('',*,{w.shell(v, True)},.F.)") for v in b.voids]
                solids.append(w.add(f"BREP_WITH_VOIDS({label},{outer},({','.join(vs)}))"))
            else:
                solids.append(w.add(f"MANIFOLD_SOLID_BREP({label},{outer})"))
        elif b.outer:
            shells = [w.shell(sh, False) for sh in b.outer]
            sheets.append(w.add(f"SHELL_BASED_SURFACE_MODEL({label},({','.join(shells)}))"))
    rep = w.add(f"ADVANCED_BREP_SHAPE_REPRESENTATION({_str(name)},({','.join([origin] + solids)}),{gctx})")
    w.add(f"SHAPE_DEFINITION_REPRESENTATION({pds},{rep})")
    if sheets:
        srep = w.add(f"MANIFOLD_SURFACE_SHAPE_REPRESENTATION({_str(name)},({','.join([origin] + sheets)}),{gctx})")
        w.add(f"SHAPE_REPRESENTATION_RELATIONSHIP('','',{rep},{srep})")
    if face_sources is not None:
        face_sources.update(w.face_sources)
    stamp = "1970-01-01T00:00:00"  # fixed: the same part always gives the same text
    head = ["ISO-10303-21;", "HEADER;",
            "FILE_DESCRIPTION(('converted by sw2sc'),'2;1');",
            f"FILE_NAME({_str(name + '.step')},'{stamp}',(''),(''),'sw2sc {__version__}','sw2sc','');",
            "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 3 1 1 }'));", "ENDSEC;", "DATA;"]
    body = [f"#{i + 1}={line};" for i, line in enumerate(w.lines)]
    return "\n".join(head + body + ["ENDSEC;", "END-ISO-10303-21;", ""])
