"""Self-consistency check of converted geometry: how far each face's edges lie from the
face's surface, grouped by the Parasolid surface type. No SolidCraft needed.

usage: python tools/selfcheck.py <part files...>
"""
import collections
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sw2sc import geometry, parasolid, xtgeom  # noqa: E402
from sw2sc.swfile import SwFile  # noqa: E402
from sw2sc.xtgeom import add, cross, dot, mul, norm, sub, unit  # noqa: E402


def dist_to_surface(spec, p):
    k = spec[0]
    if k == "plane":
        return abs(dot(sub(p, spec[1]), spec[2]))
    if k == "cylinder":
        q = sub(p, spec[1])
        return abs(norm(sub(q, mul(spec[2], dot(q, spec[2])))) - spec[4])
    if k == "cone":
        P, A, r, a = spec[1], spec[2], spec[4], spec[5]
        q = sub(p, P)
        t = dot(q, A)
        rad = norm(sub(q, mul(A, t)))
        return abs((rad - (r + t * math.tan(a))) * math.cos(a))
    if k == "sphere":
        return abs(norm(sub(p, spec[1])) - spec[4])
    if k == "torus":
        C, A, R, r = spec[1], spec[2], spec[4], spec[5]
        q = sub(p, C)
        h = dot(q, A)
        rad = norm(sub(q, mul(A, h)))
        return abs(math.hypot(rad - R, h) - r)
    if k == "bspline":
        s = spec[1]
        (u0, u1), (v0, v1) = s.domain
        best = (float("inf"), 0, 0)
        n = 16
        for i in range(n + 1):
            for j in range(n + 1):
                u, v = u0 + (u1 - u0) * i / n, v0 + (v1 - v0) * j / n
                d = math.dist(s(u, v), p)
                if d < best[0]:
                    best = (d, u, v)
        d, u, v = best
        hu, hv = (u1 - u0) / n, (v1 - v0) / n
        for _ in range(30):  # pattern search refinement
            improved = False
            for du, dv in ((hu, 0), (-hu, 0), (0, hv), (0, -hv)):
                uu, vv = min(max(u + du, u0), u1), min(max(v + dv, v0), v1)
                dd = math.dist(s(uu, vv), p)
                if dd < d:
                    d, u, v, improved = dd, uu, vv, True
            if not improved:
                hu, hv = hu / 2, hv / 2
        return d
    return float("nan")


def check(path):
    out = collections.defaultdict(list)
    for _nm, data in geometry.parasolid_sources(SwFile(path)):
        conv = xtgeom.Converter(parasolid.read(data))
        for b in conv.bodies():
            for sh in b.outer + b.voids:
                for f in sh.faces:
                    worst = 0.0
                    for lp in f.loops:
                        for e, _ in lp.edges:
                            for p in xtgeom._edge_samples(e, 5):
                                worst = max(worst, dist_to_surface(f.surface, p))
                    out[f.source + (" ~" if f.approx else "")].append(worst * 1000.0)  # mm
    return out


if __name__ == "__main__":
    agg = collections.defaultdict(list)
    for path in sys.argv[1:]:
        for k, v in check(path).items():
            agg[k].extend(v)
    print(f"{'surface':22} {'faces':>6} {'>1e-3mm':>8} {'>0.1mm':>7} {'worst mm':>10}")
    for k, v in sorted(agg.items(), key=lambda kv: -len(kv[1])):
        print(f"{k:22} {len(v):6} {sum(x > 1e-3 for x in v):8} {sum(x > 0.1 for x in v):7} {max(v):10.4g}")
