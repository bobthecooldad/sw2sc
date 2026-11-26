"""Turn a parsed Parasolid partition into a neutral B-rep that STEP can carry.

Exact where STEP (and SolidCraft's STEP reader) has the same geometry: planes, cylinders,
cones, spheres, tori, B-spline surfaces and curves, lines, circles, ellipses, and offsets of
analytic surfaces. Approximated with fitted B-splines where it doesn't: intersection curves
(through Parasolid's stored chart points), curves on surfaces (SP-curves), rolling-ball
blend surfaces, offsets of free-form surfaces, swept and spun surfaces.

Geometry meanings follow the published Parasolid XT Format Reference. Lengths stay in
metres here; step.py scales to millimetres.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import nurbs
from .parasolid import Node, Partition

NULL_DOUBLE = -3.14158e13


# --- small vector helpers ------------------------------------------------------------------
def add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def mul(a, s): return (a[0] * s, a[1] * s, a[2] * s)
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def norm(a): return math.sqrt(dot(a, a))


def unit(a):
    n = norm(a)
    return mul(a, 1.0 / n) if n > 1e-300 else (0.0, 0.0, 0.0)


def is_null(x) -> bool:
    return isinstance(x, float) and abs(x - NULL_DOUBLE) < 1e3


class GeomError(Exception):
    pass


# --- neutral B-rep ------------------------------------------------------------------------
@dataclass(eq=False)
class Vertex:
    point: tuple


@dataclass(eq=False)
class Edge:
    start: Vertex | None
    end: Vertex | None
    curve: tuple  # ('line', P, D) | ('circle', C, N, X, r) | ('ellipse', C, N, X, a, b) | ('bspline', Curve)
    same_sense: bool
    approx: bool = False


@dataclass(eq=False)
class Loop:
    edges: list  # [(Edge, orientation)]
    vertex: Vertex | None = None


@dataclass(eq=False)
class Face:
    surface: tuple
    same_sense: bool
    loops: list
    approx: bool = False
    source: str = ""
    colour: tuple | None = None


@dataclass(eq=False)
class Shell:
    faces: list
    closed: bool


@dataclass(eq=False)
class Body:
    kind: str  # solid / sheet / wire / general
    outer: list  # shells
    voids: list = field(default_factory=list)
    name: str = ""
    colour: tuple | None = None


def _colour(part: Partition, node: Node) -> tuple | None:
    """The node's SDL/TYSA colour as three RGB fractions, if it has a valid one."""
    found = None
    a, hops = node.f.get("attributes_groups"), 0
    while a and hops < 64:
        at = part.get(a)
        if at is None or at.name != "ATTRIBUTE":
            break
        hops += 1
        dn = part.get(at.f.get("definition"))
        ident = part.get(dn.f.get("identifier")) if dn else None
        raw = ident.f.get("string") if ident else None
        name = "".join(raw) if isinstance(raw, list) else (raw or "")
        if name in ("SDL/TYSA_COLOUR", "SDL/TYSA_COLOUR_2"):
            values = []
            for ptr in at.f.get("fields") or []:
                nv = part.get(ptr)
                if nv is not None and nv.name == "REAL_VALUES":
                    values.extend(nv.f.get("values") or [])
            if len(values) >= 3 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in values[:3]):
                rgb = tuple(min(1.0, max(0.0, float(v))) for v in values[:3])
                if name == "SDL/TYSA_COLOUR_2":
                    return rgb
                found = rgb
        a = at.f.get("next")
    return found


# --- curves -------------------------------------------------------------------------------
def _bcurve(part: Partition, node: Node) -> nurbs.Curve:
    nc = part.get(node.f["nurbs"])
    if nc is None:
        raise GeomError("B-curve without NURBS data")
    dim = nc.f["vertex_dim"]
    raw = part.get(nc.f["bspline_vertices"]).f["vertices"]
    knots = part.get(nc.f["knots"]).f["knots"]
    mults = part.get(nc.f["knot_mult"]).f["mult"]
    rational = nc.f["rational"]
    pts, w = [], []
    for i in range(nc.f["n_vertices"]):
        v = raw[i * dim:(i + 1) * dim]
        if rational:
            ww = v[-1] or 1.0
            w.append(ww)
            pts.append(tuple(c / ww for c in v[:-1]))
        else:
            pts.append(tuple(v))
    U = nurbs.expand_knots(knots, mults)
    return nurbs.Curve(nc.f["degree"], U, pts, w if rational else None)


def _bsurface(part: Partition, node: Node) -> nurbs.Surface:
    ns = part.get(node.f["nurbs"])
    if ns is None:
        raise GeomError("B-surface without NURBS data")
    dim = ns.f["vertex_dim"]
    raw = part.get(ns.f["bspline_vertices"]).f["vertices"]
    nu, nv = ns.f["n_u_vertices"], ns.f["n_v_vertices"]
    rational = ns.f["rational"]
    U = nurbs.expand_knots(part.get(ns.f["u_knots"]).f["knots"], part.get(ns.f["u_knot_mult"]).f["mult"])
    V = nurbs.expand_knots(part.get(ns.f["v_knots"]).f["knots"], part.get(ns.f["v_knot_mult"]).f["mult"])
    grid, wgrid = [], []
    # Vertices are stored with v varying fastest.
    for i in range(nu):
        row, wrow = [], []
        for j in range(nv):
            k = (i * nv + j) * dim
            v = raw[k:k + dim]
            if rational:
                ww = v[-1] or 1.0
                wrow.append(ww)
                row.append(tuple(c / ww for c in v[:3]))
            else:
                row.append(tuple(v[:3]))
        grid.append(row)
        wgrid.append(wrow)
    return nurbs.Surface(ns.f["u_degree"], ns.f["v_degree"], U, V, grid, wgrid if rational else None)


class Converter:
    def __init__(self, part: Partition):
        self.p = part
        self.warnings: list[str] = []
        self._vertices: dict[int, Vertex] = {}
        self._edges: dict[int, Edge] = {}
        self._surf_eval: dict[int, object] = {}
        self._depth = 0

    def warn(self, msg: str) -> None:
        if msg not in self.warnings and len(self.warnings) < 200:
            self.warnings.append(msg)

    # ---- surface evaluation (natural parameterisation, with natural normal) ----
    def surface_fn(self, idx: int):
        """(point(u, v), domain) for a surface node; domain may be None (unbounded)."""
        if idx in self._surf_eval:
            return self._surf_eval[idx]
        n = self.p.get(idx)
        if n is None:
            raise GeomError("missing surface")
        t, f = n.name, n.f
        dom = None
        if t == "PLANE":
            P, N, X = f["pvec"], f["normal"], f["x_axis"]
            Y = cross(N, X)
            fn = lambda u, v: add(P, add(mul(X, u), mul(Y, v)))
        elif t == "CYLINDER":
            P, A, X, r = f["pvec"], f["axis"], f["x_axis"], f["radius"]
            Y = cross(A, X)
            fn = lambda u, v: add(add(P, mul(X, r * math.cos(u))), add(mul(Y, r * math.sin(u)), mul(A, v)))
            dom = ((0.0, 2 * math.pi), None)
        elif t == "CONE":
            P, A, X, r = f["pvec"], f["axis"], f["x_axis"], f["radius"]
            tn = f["sin_half_angle"] / f["cos_half_angle"]
            Y = cross(A, X)
            fn = lambda u, v: add(add(P, mul(A, v)), mul(add(mul(X, math.cos(u)), mul(Y, math.sin(u))), r + v * tn))
            dom = ((0.0, 2 * math.pi), None)
        elif t == "SPHERE":
            C, A, X, r = f["centre"], f["axis"], f["x_axis"], f["radius"]
            Y = cross(A, X)
            fn = lambda u, v: add(C, add(mul(add(mul(X, math.cos(u)), mul(Y, math.sin(u))), r * math.cos(v)), mul(A, r * math.sin(v))))
            dom = ((0.0, 2 * math.pi), (-math.pi / 2, math.pi / 2))
        elif t == "TORUS":
            C, A, X, a, b = f["centre"], f["axis"], f["x_axis"], f["major_radius"], f["minor_radius"]
            Y = cross(A, X)
            fn = lambda u, v: add(C, add(mul(add(mul(X, math.cos(u)), mul(Y, math.sin(u))), a + b * math.cos(v)), mul(A, b * math.sin(v))))
            dom = ((0.0, 2 * math.pi), (-math.pi, math.pi))
        elif t == "B_SURFACE":
            s = _bsurface(self.p, n)
            fn = s
            dom = s.domain
        elif t == "OFFSET_SURF":
            base, bdom = self.surface_fn(f["surface"])
            bnode = self.p.get(f["surface"])
            sign = -1.0 if bnode.f.get("sense") == "-" else 1.0
            d = f["offset"] * sign

            def fn(u, v, base=base, d=d):
                return add(base(u, v), mul(_fd_normal(base, u, v), d))
            dom = bdom
        elif t == "SPUN_SURF":
            prof = self.curve_fn(f["profile"])[0]
            B, A = f["base"], unit(f["axis"])

            def fn(u, v, prof=prof, B=B, A=A):
                q = sub(prof(v), B)
                along = mul(A, dot(q, A))
                rad = sub(q, along)
                return add(B, add(along, add(mul(rad, math.cos(u)), mul(cross(A, rad), math.sin(u)))))
            pd = self.curve_fn(f["profile"])[1]
            dom = ((0.0, 2 * math.pi), pd)
        elif t == "SWEPT_SURF":
            sec, sd = self.curve_fn(f["section"])
            D = unit(f["sweep"])
            fn = lambda u, v, sec=sec, D=D: add(sec(u), mul(D, v))
            dom = (sd, None)
        else:
            raise GeomError(f"surface type {t} not supported")
        self._surf_eval[idx] = (fn, dom)
        return fn, dom

    def curve_fn(self, idx: int):
        n = self.p.get(idx)
        if n is None:
            raise GeomError("missing curve")
        t, f = n.name, n.f
        if t == "LINE":
            P, D = f["pvec"], f["direction"]
            return (lambda s: add(P, mul(D, s))), None
        if t == "CIRCLE":
            C, N, X, r = f["centre"], f["normal"], f["x_axis"], f["radius"]
            Y = cross(N, X)
            return (lambda s: add(C, add(mul(X, r * math.cos(s)), mul(Y, r * math.sin(s))))), (0.0, 2 * math.pi)
        if t == "ELLIPSE":
            C, N, X, a, b = f["centre"], f["normal"], f["x_axis"], f["major_radius"], f["minor_radius"]
            Y = cross(N, X)
            return (lambda s: add(C, add(mul(X, a * math.cos(s)), mul(Y, b * math.sin(s))))), (0.0, 2 * math.pi)
        if t == "B_CURVE":
            c = _bcurve(self.p, n)
            if len(c.P[0]) != 3:
                raise GeomError("2D B-curve used as a 3D curve")
            return c, c.domain
        if t == "TRIMMED_CURVE":
            return self.curve_fn(f["basis_curve"])
        if t == "SP_CURVE":
            sfn, _ = self.surface_fn(f["surface"])
            c2 = _bcurve(self.p, self.p.get(f["b_curve"]))
            return (lambda s: sfn(*c2(s)[:2])), c2.domain
        if t == "INTERSECTION":
            pts = self.chart_points(n)
            c = nurbs.interpolate(pts, 3) if len(pts) > 1 else None
            if c is None:
                raise GeomError("empty intersection chart")
            return c, c.domain
        raise GeomError(f"curve type {t} not supported")

    def refined_chart(self, idx: int) -> list[tuple]:
        """An intersection curve's chart, densified, with every point put exactly on the
        curve (on both surfaces; for a fillet boundary, at the foot of the spine)."""
        key = ("chart", idx)
        if key in self._surf_eval:
            return self._surf_eval[key]
        n = self.p.get(idx)
        pts = self.chart_points(n)
        out = pts
        try:
            if len(pts) >= 2:
                dense = pts
                closed = math.dist(pts[0], pts[-1]) < 1e-9
                while len(dense) < 33 and not closed:
                    c = nurbs.interpolate(dense, 3)
                    lo, hi = c.domain
                    k = 2 * (len(dense) - 1)
                    dense = [c(lo + (hi - lo) * i / k) for i in range(k + 1)]
                step = max(math.dist(a, b) for a, b in zip(dense, dense[1:]))
                s0, s1 = n.f["surface"]
                n0, n1 = self.p.get(s0), self.p.get(s1)
                bb = n0 if (n0 is not None and n0.name == "BLEND_BOUND") else (
                    n1 if (n1 is not None and n1.name == "BLEND_BOUND") else None)
                fixed = []
                for q in dense:
                    if bb is not None:
                        blend = self.p.get(bb.f["blend"])
                        c = self.spine_point(blend.index, q)
                        cands = [self.foot(si, c)[0] for si in blend.f["surface"]]
                        q2 = min(cands, key=lambda x: math.dist(x, q))
                    else:
                        q2 = self.solve_two(q, s0, 0.0, s1, 0.0, 12)
                    fixed.append(q2 if math.dist(q, q2) <= step else q)
                out = fixed
        except (GeomError, ValueError, ZeroDivisionError, AttributeError, TypeError, KeyError):
            out = pts
        self._surf_eval[key] = out
        return out

    def chart_points(self, n: Node) -> list[tuple]:
        ch = self.p.get(n.f["chart"])
        if ch is None:
            raise GeomError("intersection without chart")
        return list(ch.f["hvec"])

    # ---- closest point on a surface: (foot, natural unit normal at the foot) ----
    def foot(self, idx: int, p, depth: int = 0):
        n = self.p.get(idx)
        if n is None or depth > 6:
            raise GeomError("no surface to project onto")
        t, f = n.name, n.f
        if t == "PLANE":
            N = unit(f["normal"])
            return sub(p, mul(N, dot(sub(p, f["pvec"]), N))), N
        if t == "CYLINDER":
            A = unit(f["axis"])
            q = sub(p, f["pvec"])
            h = dot(q, A)
            R = unit(sub(q, mul(A, h)))
            return add(f["pvec"], add(mul(A, h), mul(R, f["radius"]))), R
        if t == "CONE":
            A = unit(f["axis"])
            ca, sa = f["cos_half_angle"], f["sin_half_angle"]
            q = sub(p, f["pvec"])
            h = dot(q, A)
            radial = sub(q, mul(A, h))
            rho = norm(radial)
            R = unit(radial)
            # in the (h, rho) half-plane the cone is the line rho = r + h*tan(a),
            # with outward normal (-sin a, cos a)
            d = (rho - f["radius"] - h * sa / ca) * ca
            h2, rho2 = h + d * sa, rho - d * ca
            return add(f["pvec"], add(mul(A, h2), mul(R, rho2))), unit(sub(mul(R, ca), mul(A, sa)))
        if t == "SPHERE":
            R = unit(sub(p, f["centre"]))
            return add(f["centre"], mul(R, f["radius"])), R
        if t == "TORUS":
            A = unit(f["axis"])
            q = sub(p, f["centre"])
            h = dot(q, A)
            R = unit(sub(q, mul(A, h)))
            c = add(f["centre"], mul(R, f["major_radius"]))
            N = unit(sub(p, c))
            return add(c, mul(N, f["minor_radius"])), N
        if t == "OFFSET_SURF":
            base = self.p.get(f["surface"])
            sign = -1.0 if base.f.get("sense") == "-" else 1.0
            d = f["offset"] * sign
            # the foot on an offset surface lies on the same normal line as the foot on its base
            fb, nb = self.foot(f["surface"], p, depth + 1)
            return add(fb, mul(nb, d)), nb
        if t == "BLENDED_EDGE":
            c = self.spine_point(idx, p)
            N = unit(sub(p, c))
            return add(c, mul(N, self.blend_radius(n))), N  # radius 0: the cliff edge itself
        if t == "BLEND_BOUND":
            blend = self.p.get(f["blend"])
            return self.foot(blend.f["surface"][1 - f["boundary"]], p, depth + 1)
        if t in ("B_SURFACE", "SWEPT_SURF", "SPUN_SURF"):
            return self._foot_numeric(idx, p)
        raise GeomError(f"cannot project onto {t}")

    def _foot_numeric(self, idx: int, p):
        fn, dom = self.surface_fn(idx)
        if dom is None or dom[0] is None or dom[1] is None:
            raise GeomError("cannot project onto an unbounded swept surface")
        (u0, u1), (v0, v1) = dom
        key = ("grid", idx)
        if key not in self._surf_eval:
            m = 14
            self._surf_eval[key] = [(u0 + (u1 - u0) * i / m, v0 + (v1 - v0) * j / m,
                                     fn(u0 + (u1 - u0) * i / m, v0 + (v1 - v0) * j / m))
                                    for i in range(m + 1) for j in range(m + 1)]
        u, v, _ = min(self._surf_eval[key],
                      key=lambda g: (g[2][0] - p[0]) ** 2 + (g[2][1] - p[1]) ** 2 + (g[2][2] - p[2]) ** 2)
        hu, hv = (u1 - u0) * 1e-6, (v1 - v0) * 1e-6

        def tangents(u, v):
            ua, ub = max(u - hu, u0), min(u + hu, u1)
            va, vb = max(v - hv, v0), min(v + hv, v1)
            return (mul(sub(fn(ub, v), fn(ua, v)), 1.0 / (ub - ua)),
                    mul(sub(fn(u, vb), fn(u, va)), 1.0 / (vb - va)))

        def ext(u, v):
            """The surface, continued along its border tangents outside its patch (a fillet
            may run a little past the patch its support is stored on)."""
            uc, vc = min(max(u, u0), u1), min(max(v, v0), v1)
            q = fn(uc, vc)
            if uc == u and vc == v:
                return q, None
            su, sv = tangents(uc, vc)
            return add(q, add(mul(su, u - uc), mul(sv, v - vc))), (su, sv)
        lim_u, lim_v = 0.5 * (u1 - u0), 0.5 * (v1 - v0)
        for _ in range(30):  # Gauss-Newton on the tangent plane
            q, t = ext(u, v)
            su, sv = t if t else tangents(u, v)
            r = sub(p, q)
            a, b, c = dot(su, su), dot(su, sv), dot(sv, sv)
            det = a * c - b * b
            if abs(det) < 1e-300:
                break
            du = (c * dot(r, su) - b * dot(r, sv)) / det
            dv = (a * dot(r, sv) - b * dot(r, su)) / det
            u = min(max(u + du, u0 - lim_u), u1 + lim_u)
            v = min(max(v + dv, v0 - lim_v), v1 + lim_v)
            if abs(du) < (u1 - u0) * 1e-13 and abs(dv) < (v1 - v0) * 1e-13:
                break
        q, t = ext(u, v)
        su, sv = t if t else tangents(u, v)
        return q, unit(cross(su, sv))

    def blend_radius(self, n: Node) -> float:
        r = n.f["range"][0]
        return abs(r) if not is_null(r) else 0.0

    def blend_targets(self, n: Node):
        """Signed distances of the spine from the two supporting surfaces."""
        out = []
        for i in (0, 1):
            s = self.p.get(n.f["surface"][i])
            sign = -1.0 if (s is not None and s.f.get("sense") == "-") else 1.0
            if s is not None and s.name == "BLENDED_EDGE" and self.blend_radius(s) == 0.0:
                out.append(abs(n.f["range"][i]))  # distance from a cliff edge has no sign
            else:
                out.append(n.f["range"][i] * sign)
        return out

    def solve_two(self, p, s0: int, d0: float, s1: int, d1: float, iters: int = 30):
        """Move p (the least distance) so that its signed distance from surface s0 is d0 and
        from s1 is d1. Newton steps in the plane of the two normals."""
        for _ in range(iters):
            f0, n0 = self.foot(s0, p)
            f1, n1 = self.foot(s1, p)
            e0 = d0 - dot(sub(p, f0), n0)
            e1 = d1 - dot(sub(p, f1), n1)
            if abs(e0) < 1e-13 and abs(e1) < 1e-13:
                break
            g = dot(n0, n1)
            det = 1.0 - g * g
            if det < 1e-10:
                p = add(p, mul(n0, e0))
                break
            a = (e0 - g * e1) / det
            b = (e1 - g * e0) / det
            p = add(p, add(mul(n0, a), mul(n1, b)))
        return p

    def spine_polyline(self, idx: int) -> list:
        """Dense points on a blend's spine, exactly at the blend's offsets from its supports."""
        key = ("spine", idx)
        if key in self._surf_eval:
            return self._surf_eval[key]
        n = self.p.get(idx)
        spine = self.p.get(n.f["spine"])
        if spine is None:
            raise GeomError("blend without spine")
        if spine.name == "INTERSECTION":
            pts = self.chart_points(spine)
        else:
            cfn, dom = self.curve_fn(n.f["spine"])
            if dom is None:
                raise GeomError("unbounded spine")
            pts = [cfn(dom[0] + (dom[1] - dom[0]) * i / 48) for i in range(49)]
        self._surf_eval[key] = pts  # guards against a blend that supports itself
        if self.blend_radius(n) == 0.0:
            return pts
        s0, s1 = n.f["surface"]
        d0, d1 = self.blend_targets(n)
        try:
            while 2 <= len(pts) < 49:
                c = nurbs.interpolate(pts, 3)
                lo, hi = c.domain
                k = 2 * (len(pts) - 1)
                pts = [c(lo + (hi - lo) * i / k) for i in range(k + 1)]
            pts = [self.solve_two(q, s0, d0, s1, d1) for q in pts]
        except (GeomError, ValueError, ZeroDivisionError):
            pts = self._surf_eval[key]  # a support we cannot project onto: keep the stored points
        self._surf_eval[key] = pts
        return pts

    def spine_point(self, idx: int, p):
        """The spine point whose cross-section circle passes nearest p."""
        n = self.p.get(idx)
        sp = self.p.get(n.f["spine"])
        while sp is not None and sp.name == "TRIMMED_CURVE":
            sp = self.p.get(sp.f["basis_curve"])
        if sp is not None and sp.name == "LINE":
            D = unit(sp.f["direction"])
            return add(sp.f["pvec"], mul(D, dot(sub(p, sp.f["pvec"]), D)))
        if sp is not None and sp.name == "CIRCLE":
            N = unit(sp.f["normal"])
            q = sub(p, sp.f["centre"])
            radial = sub(q, mul(N, dot(q, N)))
            if norm(radial) > 1e-12:
                return add(sp.f["centre"], mul(unit(radial), sp.f["radius"]))
        pts = self.spine_polyline(idx)
        s, _ = _project_param(pts, p)
        q = _at(pts, s)
        if self._depth < 3 and self.blend_radius(n) > 0.0:
            self._depth += 1
            try:
                s0, s1 = n.f["surface"]
                d0, d1 = self.blend_targets(n)
                q2 = self.solve_two(q, s0, d0, s1, d1, 6)
                span = math.dist(pts[0], pts[1]) if len(pts) > 1 else 0.0
                if math.dist(q, q2) <= max(span, 1e-9):
                    q = q2
            except (GeomError, ValueError, ZeroDivisionError):
                pass
            finally:
                self._depth -= 1
        return q

    def _line_spine(self, sp: Node, bpts: list) -> list:
        D = unit(sp.f["direction"])
        ts = [dot(sub(q, sp.f["pvec"]), D) for q in bpts]
        lo, hi = min(ts), max(ts)
        pad = 0.05 * (hi - lo) + 1e-6
        return [add(sp.f["pvec"], mul(D, lo - pad + (hi - lo + 2 * pad) * i / 8)) for i in range(9)]

    # ---- conversion of one curve for an edge (start -> end) ----
    def edge_curve(self, cnode_idx: int, start: tuple | None, end: tuple | None):
        """Return (curve spec, same_sense, approx) for an edge running start -> end."""
        n = self.p.get(cnode_idx)
        if n is None:
            raise GeomError("edge without curve")
        t, f = n.name, n.f
        sense = f.get("sense", "+") != "-"
        if t == "TRIMMED_CURVE":
            basis = self.p.get(f["basis_curve"])
            bsense = basis.f.get("sense", "+") != "-"
            spec, ss, approx = self.edge_curve(f["basis_curve"], start, end)
            if approx:
                return spec, ss, approx
            return spec, sense == bsense, False
        if t == "LINE":
            return ("line", f["pvec"], unit(f["direction"])), sense, False
        if t == "CIRCLE":
            return ("circle", f["centre"], unit(f["normal"]), unit(f["x_axis"]), f["radius"]), sense, False
        if t == "ELLIPSE":
            return ("ellipse", f["centre"], unit(f["normal"]), unit(f["x_axis"]),
                    f["major_radius"], f["minor_radius"]), sense, False
        if t == "B_CURVE":
            c = _bcurve(self.p, n)
            if len(c.P[0]) == 3:
                return ("bspline", c), sense, False
        # Approximate: a dense polyline in the curve's own direction, then cut to the edge.
        if t == "INTERSECTION":
            pts = self.refined_chart(cnode_idx)
        else:
            fn, dom = self.curve_fn(cnode_idx)
            if dom is None:
                raise GeomError(f"unbounded {t}")
            k = 64
            pts = [fn(dom[0] + (dom[1] - dom[0]) * i / k) for i in range(k + 1)]
        if not sense:
            pts = pts[::-1]
        return ("bspline", _fit_between(pts, start, end)), True, True

    # ---- surfaces for STEP ----
    def face_surface(self, idx: int, loops=None):
        """(spec, flip, approx) - flip=True when the STEP surface's normal is the opposite of
        the Parasolid surface's natural normal."""
        n = self.p.get(idx)
        if n is None:
            raise GeomError("face without surface")
        t, f = n.name, n.f
        if t == "PLANE":
            return ("plane", f["pvec"], unit(f["normal"]), unit(f["x_axis"])), False, False
        if t == "CYLINDER":
            return ("cylinder", f["pvec"], unit(f["axis"]), unit(f["x_axis"]), f["radius"]), False, False
        if t == "CONE":
            # In the files the radius grows along +axis (radius at pvec + t*tan(half angle),
            # checked against the vertices of the sample cone faces), as in STEP's cone.
            semi = math.atan2(f["sin_half_angle"], f["cos_half_angle"])
            return ("cone", f["pvec"], unit(f["axis"]), unit(f["x_axis"]), f["radius"], semi), False, False
        if t == "SPHERE":
            return ("sphere", f["centre"], unit(f["axis"]), unit(f["x_axis"]), f["radius"]), False, False
        if t == "TORUS":
            if f["major_radius"] <= f["minor_radius"]:
                return self._sampled(idx, loops), False, True
            return ("torus", f["centre"], unit(f["axis"]), unit(f["x_axis"]),
                    f["major_radius"], f["minor_radius"]), False, False
        if t == "B_SURFACE":
            return ("bspline", _bsurface(self.p, n)), False, False
        if t == "OFFSET_SURF":
            base = self.p.get(f["surface"])
            if base is not None and base.name == "BLENDED_EDGE":
                # an offset rolling-ball blend is a rolling-ball blend about the same spine
                return ("blend", f["surface"]), None, True
            exact = self._offset_exact(n)
            if exact is not None:
                return exact
            return self._sampled(idx, loops), False, True
        if t in ("SPUN_SURF", "SWEPT_SURF"):
            return self._sampled(idx, loops), False, True
        if t == "BLENDED_EDGE":
            return ("blend", idx), None, True  # built per face (needs the face's extent)
        raise GeomError(f"surface type {t} not supported")

    def _offset_exact(self, n: Node):
        base = self.p.get(n.f["surface"])
        if base is None:
            return None
        sign = -1.0 if base.f.get("sense") == "-" else 1.0
        d = n.f["offset"] * sign
        b = base.f
        if base.name == "PLANE":
            N = unit(b["normal"])
            return ("plane", add(b["pvec"], mul(N, d)), N, unit(b["x_axis"])), False, False
        if base.name == "CYLINDER" and b["radius"] + d > 1e-9:
            return ("cylinder", b["pvec"], unit(b["axis"]), unit(b["x_axis"]), b["radius"] + d), False, False
        if base.name == "SPHERE" and b["radius"] + d > 1e-9:
            return ("sphere", b["centre"], unit(b["axis"]), unit(b["x_axis"]), b["radius"] + d), False, False
        if base.name == "TORUS" and b["minor_radius"] + d > 1e-9 and b["major_radius"] > b["minor_radius"] + d:
            return ("torus", b["centre"], unit(b["axis"]), unit(b["x_axis"]), b["major_radius"],
                    b["minor_radius"] + d), False, False
        if base.name == "CONE":
            ca, sa = b["cos_half_angle"], b["sin_half_angle"]
            A = unit(b["axis"])
            r = b["radius"] + d / ca  # outward offset, radius measured at the same pvec
            if r > 1e-9:
                return ("cone", b["pvec"], A, unit(b["x_axis"]), r, math.atan2(sa, ca)), False, False
        return None

    def _sampled(self, idx: int, loops=None):
        fn, dom = self.surface_fn(idx)
        node = self.p.get(idx)
        if dom is None:
            raise GeomError(f"unbounded {node.name} surface")
        du, dv = dom
        if dv is None and node.name == "SWEPT_SURF" and loops:
            D = unit(node.f["sweep"])
            pts = [p for lp in loops for e, _ in lp.edges for p in _edge_samples(e, 8)]
            sec = [dot(fn(du[0] + (du[1] - du[0]) * i / 32, 0.0), D) for i in range(33)]
            lo = min(dot(p, D) for p in pts) - max(sec)
            hi = max(dot(p, D) for p in pts) - min(sec)
            pad = 0.05 * (hi - lo) + 1e-6
            dv = (lo - pad, hi + pad)
        if du is None or dv is None:
            raise GeomError(f"unbounded {node.name} surface")
        return ("bspline", _sample_surface(fn, du, dv))

    # ---- topology ----
    def vertex(self, idx: int) -> Vertex | None:
        if not idx:
            return None
        if idx not in self._vertices:
            vn = self.p.get(idx)
            pt = self.p.get(vn.f["point"]) if vn else None
            if pt is None:
                raise GeomError("vertex without point")
            self._vertices[idx] = Vertex(tuple(pt.f["pvec"]))
        return self._vertices[idx]

    def edge(self, idx: int) -> Edge:
        if idx in self._edges:
            return self._edges[idx]
        en = self.p.get(idx)
        fin = self.p.get(en.f["fin"])
        if fin is None:
            raise GeomError("edge without fin")
        other = self.p.get(fin.f["other"])
        # edge->fin is a positive fin: its vertex ends the edge; the next fin's vertex starts it.
        end = self.vertex(fin.f["vertex"])
        start = self.vertex(other.f["vertex"]) if other else end
        cidx = en.f["curve"]
        if not cidx:
            # tolerant edge: use the SP-curve of a fin
            f2, guard = fin, 0
            while f2 is not None and not f2.f.get("curve") and guard < 64:
                f2 = self.p.get(f2.f["other"])
                guard += 1
            cidx = f2.f.get("curve") if f2 else 0
            if not cidx:
                raise GeomError("edge without curve")
        spec, ss, approx = self.edge_curve(cidx, start.point if start else None, end.point if end else None)
        if spec[0] == "bspline" and not approx and start is not None and end is not None:
            spec = ("bspline", _trim_to_edge(spec[1], start.point, end.point, ss))
        if start is None and end is None:
            # ring edge: STEP needs a vertex. On a face of revolution, put it on that surface's
            # seam (its x axis) so every ring loop of the face has its vertex at the same angle.
            pt = self._ring_vertex_point(en, spec)
            start = end = Vertex(pt)
        e = Edge(start, end, spec, ss, approx)
        self._edges[idx] = e
        return e

    def _ring_vertex_point(self, en: Node, spec):
        if spec[0] in ("circle", "ellipse"):
            C, N = spec[1], spec[2]
            fin, guard = self.p.get(en.f["fin"]), 0
            while fin is not None and guard < 16:
                lp = self.p.get(fin.f["loop"])
                if lp:
                    sn = self.p.get(self.p.get(lp.f["face"]).f["surface"])
                    if sn is not None and sn.name in ("CYLINDER", "CONE", "SPHERE", "TORUS"):
                        X = sn.f["x_axis"]
                        Xp = sub(X, mul(N, dot(X, N)))
                        if norm(Xp) > 1e-9:
                            Xp = unit(Xp)
                            if spec[0] == "circle":
                                return add(C, mul(Xp, spec[4]))
                            Xe, Ye = spec[3], cross(N, spec[3])
                            ang = math.atan2(dot(Xp, Ye), dot(Xp, Xe))
                            return add(C, add(mul(Xe, spec[4] * math.cos(ang)), mul(Ye, spec[5] * math.sin(ang))))
                fin = self.p.get(fin.f["other"])
                guard += 1
        return _curve_point(spec)

    def loop(self, idx: int) -> Loop:
        ln = self.p.get(idx)
        first = ln.f["fin"]
        fin_node = self.p.get(first)
        if fin_node is not None and not fin_node.f.get("edge"):
            return Loop([], self.vertex(fin_node.f["vertex"]))
        out, cur, guard = [], first, 0
        while True:
            fn = self.p.get(cur)
            if fn is None:
                raise GeomError("broken fin ring")
            out.append((self.edge(fn.f["edge"]), fn.f["sense"] != "-"))
            cur = fn.f["forward"]
            guard += 1
            if cur == first or not cur or guard > 100000:
                break
        return Loop(out)

    def face(self, idx: int) -> Face:
        fn = self.p.get(idx)
        sidx = fn.f["surface"]
        snode = self.p.get(sidx)
        if snode is None:
            raise GeomError("face without surface")
        loops = []
        li, guard = fn.f["loop"], 0
        while li and guard < 100000:
            loops.append(self.loop(li))
            li = self.p.get(li).f["next"]
            guard += 1
        spec, flip, approx = self.face_surface(sidx, loops)
        natural = (fn.f["sense"] != "-") == (snode.f.get("sense", "+") != "-")
        colour = _colour(self.p, fn)
        if spec[0] == "blend":
            spec = ("bspline", self._blend_surface(self.p.get(spec[1]), loops))
            same = self._orient_by_neighbours(spec, loops, idx)
            return Face(spec, same, loops, True, snode.name, colour)
        if approx and spec[0] == "bspline" and snode.name in ("SPUN_SURF", "SWEPT_SURF", "OFFSET_SURF", "TORUS"):
            # The sampled surface keeps the natural parameterisation, so the natural normal.
            pass
        return Face(spec, natural != bool(flip), loops, approx, snode.name, colour)

    # ---- blends ----
    def _blend_surface(self, snode: Node, loops: list) -> nurbs.Surface:
        try:
            return self._blend_surface_exact(snode, loops)
        except (GeomError, ValueError, ZeroDivisionError, IndexError) as e:
            self.warn(f"fillet {snode.f.get('node_id')}: exact construction failed ({e}); fitted instead")
            return self._blend_surface_fit(snode, loops)

    def _blend_surface_exact(self, snode: Node, loops: list) -> nurbs.Surface:
        """Rolling-ball blend: for each spine point C, the cross-section is the arc of radius r
        about C from its foot on one supporting surface to its foot on the other."""
        idx = snode.index
        r = self.blend_radius(snode)
        if r <= 0:
            raise GeomError("no radius")
        bpts = [q for lp in loops for e, _ in lp.edges for q in _edge_samples(e, 9)]
        if len(bpts) < 3:
            raise GeomError("no boundary")
        sp = self.p.get(snode.f["spine"])
        if sp is not None and sp.name == "LINE":
            spine = self._line_spine(sp, bpts)
        else:
            spine = self.spine_polyline(idx)
        if len(spine) < 2:
            raise GeomError("no spine")
        # the radius this face really has (a face on an offset of the blend differs)
        gaps = sorted(_project_param(spine, q)[1] for q in bpts)
        r_face = gaps[len(gaps) // 2]
        if abs(r_face - r) > 0.02 * r:
            if r_face <= 0:
                raise GeomError("face lies on the spine")
        else:
            r_face = r
        # the stretch of spine the face covers
        params = [_project_param(spine, q)[0] for q in bpts]
        n_seg = len(spine) - 1
        closed = math.dist(spine[0], spine[-1]) < 1e-9
        lo, hi = min(params), max(params)
        if closed and hi - lo > 0.9 * n_seg:
            lo, hi = 0.0, float(n_seg)
            whole = True
        else:
            pad = 0.03 * (hi - lo) + 0.25
            lo, hi = max(0.0, lo - pad), min(float(n_seg), hi + pad)
            whole = False
        if hi - lo < 1e-9:
            raise GeomError("face covers no spine")
        s0, s1 = snode.f["surface"]
        d0, d1 = self.blend_targets(snode)
        rows_n, cols_n = 49, 25
        rows = []
        for i in range(rows_n):
            c = _at(spine, lo + (hi - lo) * i / (rows_n - 1))
            c = self.solve_two(c, s0, d0, s1, d1, 12)
            f0, _ = self.foot(s0, c)
            f1, _ = self.foot(s1, c)
            if abs(math.dist(f0, c) - r) > 1e-4 * r or abs(math.dist(f1, c) - r) > 1e-4 * r:
                raise GeomError("supports are not at the blend radius from the spine")
            a, b = unit(sub(f0, c)), unit(sub(f1, c))
            ang = math.acos(max(-1.0, min(1.0, dot(a, b))))
            ta = _at(spine, lo + (hi - lo) * max(i - 1, 0) / (rows_n - 1))
            tb = _at(spine, lo + (hi - lo) * min(i + 1, rows_n - 1) / (rows_n - 1))
            tdir = unit(sub(tb, ta))
            if ang < 1e-7:
                # the feet one point: the ball fills both supports (a pipe of the blend's radius bent
                # round a corner), so the blend is the tube of that radius round the spine: a whole
                # circle square to the spine, from the spine plane's normal on every row
                g = tuple(sp.f["normal"]) if sp is not None and "normal" in sp.f else (0.0, 0.0, 1.0)
                if abs(dot(g, tdir)) > 0.999:
                    g = (1.0, 0.0, 0.0) if abs(tdir[0]) < 0.9 else (0.0, 1.0, 0.0)
                u1 = unit(sub(g, mul(tdir, dot(g, tdir))))
                u2 = cross(tdir, u1)
                rows.append([add(c, mul(add(mul(u1, math.cos(2 * math.pi * k / (cols_n - 1))),
                                            mul(u2, math.sin(2 * math.pi * k / (cols_n - 1)))), r_face))
                             for k in range(cols_n)])
                continue
            if ang > math.pi - 1e-7:
                # the feet opposite each other (a full round between parallel faces): the half circle
                # square to the spine, on the side the face's own boundary is (its end edges are
                # that half circle)
                yv = unit(cross(tdir, a))
                up = min(math.dist(add(c, mul(yv, r_face)), q) for q in bpts)
                down = min(math.dist(add(c, mul(yv, -r_face)), q) for q in bpts)
                bperp = yv if up <= down else mul(yv, -1.0)
                ang = math.pi
            else:
                bperp = unit(sub(b, mul(a, dot(a, b))))
            ext = 0.04 * ang
            rows.append([add(c, mul(add(mul(a, math.cos(-ext + (ang + 2 * ext) * k / (cols_n - 1))),
                                        mul(bperp, math.sin(-ext + (ang + 2 * ext) * k / (cols_n - 1)))), r_face))
                         for k in range(cols_n)])
        if not whole:
            rows = _extend_rows(rows, 0.02)
        return nurbs.interpolate_grid(rows, 3)

    def _blend_surface_fit(self, snode: Node, loops: list) -> nurbs.Surface:
        f = snode.f
        r = abs(f["range"][0]) if not is_null(f["range"][0]) else 0.0
        spine_idx = f["spine"]
        spine = self.p.get(spine_idx)
        if spine is None:
            raise GeomError("blend without spine")
        if spine.name == "INTERSECTION":
            centres = self.chart_points(spine)
        else:
            cfn, dom = self.curve_fn(spine_idx)
            if dom is None:
                # limit to the face's extent along a line spine
                pts = [e.start.point for lp in loops for e, _ in lp.edges if e.start]
                P0 = cfn(0.0)
                D = sub(cfn(1.0), P0)
                ts = [dot(sub(p, P0), D) / dot(D, D) for p in pts] or [0.0, 1.0]
                dom = (min(ts), max(ts))
            centres = [cfn(dom[0] + (dom[1] - dom[0]) * i / 32) for i in range(33)]
        centres = _resample(centres, 48)
        # contact directions: from the boundary edges of the face, the points at distance r
        bpts = []
        for lp in loops:
            for e, _ in lp.edges:
                bpts.extend(_edge_samples(e, 12))
        if len(bpts) < 4:
            raise GeomError("blend face without boundary")
        # The radius this face actually has (an offset blend differs from the blend's range):
        # the typical distance from the spine to the face boundary.
        dists = sorted(min(math.dist(c, p) for p in bpts) for c in centres[::max(1, len(centres) // 12)])
        measured = dists[len(dists) // 2] if dists else r
        if r <= 0 or abs(measured - r) > 0.02 * r:
            r = measured
        if r <= 0:
            raise GeomError("blend radius is zero")
        rows = []
        for c in centres:
            near = [p for p in bpts if abs(math.dist(p, c) - r) < max(0.02 * r, 1e-7)]
            if len(near) < 2:
                near = sorted(bpts, key=lambda p: abs(math.dist(p, c) - r))[:6]
            # the two contact directions: the pair of near points farthest apart in angle
            dirs = [unit(sub(p, c)) for p in near]
            a, b = max(((x, y) for i, x in enumerate(dirs) for y in dirs[i + 1:]),
                       key=lambda xy: -dot(xy[0], xy[1]), default=(dirs[0], dirs[-1]))
            ang = math.acos(max(-1.0, min(1.0, dot(a, b))))
            if ang < 1e-6:
                rows.append([add(c, mul(a, r))] * 9)
                continue
            ax = unit(cross(a, b))
            bperp = cross(ax, a)
            ext = 0.08 * ang
            row = []
            for k in range(9):
                th = -ext + (ang + 2 * ext) * k / 8
                row.append(add(c, mul(add(mul(a, math.cos(th)), mul(bperp, math.sin(th))), r)))
            rows.append(row)
        # extend a little past both spine ends so the face's end edges lie inside
        rows = _extend_rows(rows, 0.04)
        return nurbs.interpolate_grid(rows, 3)

    def _orient_by_neighbours(self, spec, loops, face_idx) -> bool:
        """Orientation of a fitted surface: match the outward normal of a tangent neighbour."""
        surf = spec[1]
        votes = 0
        for lp in loops:
            for e, _ in lp.edges:
                nb = self._neighbour_normal(e, face_idx)
                if nb is None:
                    continue
                p, n_out = nb
                n_fit = _surface_normal_near(surf, p)
                if n_fit is None:
                    continue
                votes += 1 if dot(n_fit, n_out) > 0 else -1
        return votes >= 0

    def _neighbour_normal(self, edge: Edge, face_idx: int):
        # find the parasolid edge for this neutral edge
        for eidx, e in self._edges.items():
            if e is edge:
                break
        else:
            return None
        en = self.p.get(eidx)
        fin, guard = self.p.get(en.f["fin"]), 0
        while fin is not None and guard < 16:
            lp = self.p.get(fin.f["loop"])
            if lp and lp.f["face"] != face_idx:
                fnode = self.p.get(lp.f["face"])
                snode = self.p.get(fnode.f["surface"])
                if snode is not None and snode.name in ("PLANE", "CYLINDER", "SPHERE", "TORUS", "CONE", "B_SURFACE"):
                    p = _edge_samples(edge, 2)[1]
                    n = self._exact_normal(snode, p)
                    if n is not None:
                        natural = (fnode.f["sense"] != "-") == (snode.f.get("sense", "+") != "-")
                        return p, n if natural else mul(n, -1.0)
            fin = self.p.get(fin.f["other"])
            guard += 1
        return None

    def _exact_normal(self, s: Node, p):
        f = s.f
        if s.name == "PLANE":
            return unit(f["normal"])
        if s.name == "CYLINDER":
            A = unit(f["axis"])
            q = sub(p, f["pvec"])
            return unit(sub(q, mul(A, dot(q, A))))
        if s.name == "SPHERE":
            return unit(sub(p, f["centre"]))
        if s.name == "TORUS":
            A = unit(f["axis"])
            q = sub(p, f["centre"])
            rad = unit(sub(q, mul(A, dot(q, A))))
            c = add(f["centre"], mul(rad, f["major_radius"]))
            return unit(sub(p, c))
        if s.name == "CONE":
            A = unit(f["axis"])
            q = sub(p, f["pvec"])
            R = unit(sub(q, mul(A, dot(q, A))))
            ca, sa = f["cos_half_angle"], f["sin_half_angle"]
            return unit(sub(mul(R, ca), mul(A, sa)))
        if s.name == "B_SURFACE":
            return _surface_normal_near(_bsurface(self.p, s), p)
        return None

    # ---- bodies ----
    def body(self, bn: Node) -> list[Body]:
        btype = {1: "solid", 2: "wire", 3: "sheet", 6: "general"}.get(bn.f["body_type"], "general")
        colour = _colour(self.p, bn)
        out: list[Body] = []
        seen: set[int] = set()
        sheet_shells: list[Shell] = []
        ri, guard = bn.f["region"], 0
        while ri and guard < 100000:
            rn = self.p.get(ri)
            guard += 1
            solid_region = rn.f["type"] == "S"
            if btype == "solid" and not solid_region:
                ri = rn.f["next"]
                continue
            shells: list[Shell] = []
            si, g1 = rn.f["shell"], 0
            while si and g1 < 100000:
                sn = self.p.get(si)
                g1 += 1
                faces = []
                for chain, nxt in (("face", "next"), ("front_face", "next_front")):
                    fi, g2 = sn.f.get(chain, 0), 0
                    while fi and g2 < 1000000:
                        g2 += 1
                        if fi not in seen:
                            seen.add(fi)
                            try:
                                faces.append(self.face(fi))
                            except Exception as e:  # one bad face must not lose the body
                                self.warn(f"face {self.p.get(fi).f.get('node_id')} left out: {type(e).__name__}: {e}")
                        fi = self.p.get(fi).f[nxt]
                if faces:
                    shells.append(Shell(faces, closed=btype == "solid"))
                si = sn.f["next"]
            if btype == "solid" and shells:
                shells.sort(key=lambda sh: -_shell_size(sh))
                out.append(Body("solid", [shells[0]], shells[1:], colour=colour))
            else:
                sheet_shells.extend(shells)
            ri = rn.f["next"]
        if sheet_shells:
            out.append(Body("sheet" if btype != "solid" else "solid", sheet_shells, [], colour=colour))
        return out

    def bodies(self) -> list[Body]:
        out = []
        for bn in self.p.of_type("BODY"):
            try:
                out.extend(self.body(bn))
            except (GeomError, KeyError, AttributeError, TypeError, ValueError) as e:
                self.warn(f"body skipped: {e}")
        return out


def _shell_size(sh: Shell) -> float:
    pts = [e.start.point for f in sh.faces for lp in f.loops for e, _ in lp.edges if e.start]
    if not pts:
        return 0.0
    lo = [min(p[i] for p in pts) for i in range(3)]
    hi = [max(p[i] for p in pts) for i in range(3)]
    return math.dist(lo, hi)


# --- helpers -------------------------------------------------------------------------------
def _fd_normal(fn, u, v, h=1e-6):
    p = fn(u, v)
    du = sub(fn(u + h, v), p)
    dv = sub(fn(u, v + h), p)
    return unit(cross(du, dv))


def _sample_surface(fn, du, dv, nu=24, nv=24) -> nurbs.Surface:
    grid = [[fn(du[0] + (du[1] - du[0]) * i / (nu - 1), dv[0] + (dv[1] - dv[0]) * j / (nv - 1))
             for j in range(nv)] for i in range(nu)]
    return nurbs.interpolate_grid(grid, 3)


def _surface_normal_near(s: nurbs.Surface, p, n=12):
    (u0, u1), (v0, v1) = s.domain
    best = None
    for i in range(n + 1):
        for j in range(n + 1):
            u = u0 + (u1 - u0) * i / n
            v = v0 + (v1 - v0) * j / n
            d = math.dist(s(u, v), p)
            if best is None or d < best[0]:
                best = (d, u, v)
    _, u, v = best
    hu, hv = (u1 - u0) * 1e-5, (v1 - v0) * 1e-5
    uu = min(max(u, u0 + hu), u1 - hu)
    vv = min(max(v, v0 + hv), v1 - hv)
    return unit(cross(sub(s(uu + hu, vv), s(uu - hu, vv)), sub(s(uu, vv + hv), s(uu, vv - hv))))


def _curve_point(spec):
    if spec[0] == "line":
        return spec[1]
    if spec[0] == "circle":
        return add(spec[1], mul(spec[3], spec[4]))
    if spec[0] == "ellipse":
        return add(spec[1], mul(spec[3], spec[4]))
    c = spec[1]
    return c(c.domain[0])


def _edge_samples(e: Edge, k: int) -> list[tuple]:
    spec = e.curve
    s, t = e.start.point, e.end.point
    if spec[0] == "line":
        return [add(s, mul(sub(t, s), i / (k - 1))) for i in range(k)]
    if spec[0] in ("circle", "ellipse"):
        C, N, X = spec[1], spec[2], spec[3]
        a = spec[4]
        b = spec[5] if spec[0] == "ellipse" else a
        Y = cross(N, X)

        def ang(p):
            q = sub(p, C)
            return math.atan2(dot(q, Y) / b, dot(q, X) / a)
        a0, a1 = ang(s), ang(t)
        if e.same_sense:
            if a1 <= a0 + 1e-12:
                a1 += 2 * math.pi
        else:
            if a1 >= a0 - 1e-12:
                a1 -= 2 * math.pi
        return [add(C, add(mul(X, a * math.cos(a0 + (a1 - a0) * i / (k - 1))),
                           mul(Y, b * math.sin(a0 + (a1 - a0) * i / (k - 1))))) for i in range(k)]
    c = spec[1]
    u0, u1 = c.domain
    pts = [c(u0 + (u1 - u0) * i / (k - 1)) for i in range(k)]
    return pts if e.same_sense else pts[::-1]


def _trim_to_edge(c: nurbs.Curve, start, end, same_sense: bool) -> nurbs.Curve:
    """An edge may use only a piece of its B-curve; STEP readers take the curve's own ends
    as the edge's, so cut the curve to the piece between the edge's vertices."""
    lo, hi = c.domain
    tol = 1e-8
    p_lo, p_hi = c(lo), c(hi)
    a, b = (start, end) if same_sense else (end, start)
    if math.dist(p_lo, a) < tol and math.dist(p_hi, b) < tol:
        return c
    if math.dist(a, b) < tol:
        return c  # closed edge on the whole curve
    ua, da = c.closest(a)
    ub, db = c.closest(b)
    if math.dist(p_lo, a) < tol:
        ua = lo
    if math.dist(p_hi, b) < tol:
        ub = hi
    if ub - ua <= 1e-12 * max(1.0, hi - lo) or max(da, db) > 1e-5:
        return c  # wraps a closed curve's seam, or vertices are not on it: leave whole
    try:
        return c.sub(ua, ub)
    except (ValueError, IndexError):
        return c


def _resample(pts, k):
    if len(pts) <= k:
        return pts
    step = (len(pts) - 1) / (k - 1)
    return [pts[round(i * step)] for i in range(k)]


def _extend_rows(rows, frac):
    if len(rows) < 2:
        return rows
    first = [add(a, mul(sub(a, b), frac * (len(rows) - 1))) for a, b in zip(rows[0], rows[1])]
    last = [add(a, mul(sub(a, b), frac * (len(rows) - 1))) for a, b in zip(rows[-1], rows[-2])]
    return [first] + rows + [last]


def _project_param(pts, q):
    """Closest position on a polyline: (segment index + fraction, distance)."""
    best = (0.0, float("inf"))
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        ab = sub(b, a)
        L = dot(ab, ab)
        t = 0.0 if L == 0 else max(0.0, min(1.0, dot(sub(q, a), ab) / L))
        d = math.dist(add(a, mul(ab, t)), q)
        if d < best[1]:
            best = (i + t, d)
    return best


def _at(pts, s):
    i = min(int(s), len(pts) - 2)
    t = s - i
    return add(pts[i], mul(sub(pts[i + 1], pts[i]), t))


def _fit_between(pts, start, end) -> nurbs.Curve:
    """B-spline through the part of a polyline (in curve direction) from start to end."""
    if start is None or end is None:
        q = pts
    else:
        closed = math.dist(pts[0], pts[-1]) < 1e-7
        s0, _ = _project_param(pts, start)
        s1, _ = _project_param(pts, end)
        if math.dist(start, end) < 1e-9 and closed:
            # full closed curve starting at the vertex
            i = int(s0)
            loop = pts[:-1]
            q = [start] + loop[i + 1:] + loop[:i + 1] + [start]
        elif s1 > s0:
            q = [start] + pts[int(s0) + 1:int(math.ceil(s1))] + [end]
        elif closed:
            q = [start] + pts[int(s0) + 1:-1] + pts[:int(math.ceil(s1))] + [end]
        else:
            # edge runs against the polyline: reverse
            rp = pts[::-1]
            n = len(pts) - 1
            r0, r1 = n - s0, n - s1
            q = [start] + rp[int(r0) + 1:int(math.ceil(r1))] + [end]
    q = _resample(q, 240) if len(q) > 240 else q
    if len(q) == 2:
        mid = add(q[0], mul(sub(q[1], q[0]), 0.5))
        q = [q[0], mid, q[1]]
    return nurbs.interpolate(q, 3)
