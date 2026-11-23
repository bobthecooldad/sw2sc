"""Small NURBS toolkit (pure Python): evaluation and interpolation.

Textbook algorithms (Cox-de Boor evaluation, chord-length cubic interpolation solved as a
banded linear system). Knots are full (expanded) vectors here; STEP output converts back
to distinct knots + multiplicities.
"""
from __future__ import annotations

import math
from bisect import bisect_right

Vec = tuple


def expand_knots(knots: list[float], mults: list[int]) -> list[float]:
    out: list[float] = []
    for k, m in zip(knots, mults):
        out.extend([k] * max(int(m), 0))
    return out


def compress_knots(full: list[float], eps: float = 0.0) -> tuple[list[float], list[int]]:
    ks: list[float] = []
    ms: list[int] = []
    for k in full:
        if ks and abs(k - ks[-1]) <= eps:
            ms[-1] += 1
        else:
            ks.append(k)
            ms.append(1)
    return ks, ms


def find_span(n: int, p: int, u: float, U: list[float]) -> int:
    """Span index for parameter u; n = number of control points - 1."""
    if u >= U[n + 1]:
        return n
    if u <= U[p]:
        return p
    k = bisect_right(U, u) - 1
    return min(max(k, p), n)


def basis(span: int, u: float, p: int, U: list[float]) -> list[float]:
    N = [1.0] + [0.0] * p
    left = [0.0] * (p + 1)
    right = [0.0] * (p + 1)
    for j in range(1, p + 1):
        left[j] = u - U[span + 1 - j]
        right[j] = U[span + j] - u
        saved = 0.0
        for r in range(j):
            den = right[r + 1] + left[j - r]
            tmp = N[r] / den if den != 0 else 0.0
            N[r] = saved + right[r + 1] * tmp
            saved = left[j - r] * tmp
        N[j] = saved
    return N


class Curve:
    """B-spline curve with homogeneous control points (dim = 2 or 3, plus weights)."""

    def __init__(self, degree: int, knots: list[float], pts: list[tuple], weights: list[float] | None = None):
        self.p = degree
        self.U = knots
        self.P = pts
        self.W = weights
        if len(knots) != len(pts) + degree + 1:
            raise ValueError(f"bad B-spline: {len(knots)} knots, {len(pts)} points, degree {degree}")

    @property
    def domain(self) -> tuple[float, float]:
        return self.U[self.p], self.U[len(self.P)]

    def __call__(self, u: float) -> tuple:
        n = len(self.P) - 1
        s = find_span(n, self.p, u, self.U)
        N = basis(s, u, self.p, self.U)
        dim = len(self.P[0])
        acc = [0.0] * dim
        wsum = 0.0
        for j in range(self.p + 1):
            i = s - self.p + j
            w = self.W[i] if self.W else 1.0
            c = N[j] * w
            wsum += c
            for d in range(dim):
                acc[d] += c * self.P[i][d]
        return tuple(a / wsum for a in acc) if wsum else tuple(acc)


    # -- trimming (Boehm knot insertion on homogeneous points) --
    def _insert(self, u: float) -> None:
        p, U = self.p, self.U
        n = len(self.P) - 1
        k = find_span(n, p, u, U)
        dim = len(self.P[0])
        H = [tuple(c * (self.W[i] if self.W else 1.0) for c in self.P[i]) + ((self.W[i],) if self.W else ())
             for i in range(len(self.P))]
        Q = []
        for i in range(len(H) + 1):
            if i <= k - p:
                Q.append(H[i])
            elif i > k:
                Q.append(H[i - 1])
            else:
                den = U[i + p] - U[i]
                a = (u - U[i]) / den if den else 0.0
                Q.append(tuple(a * x + (1 - a) * y for x, y in zip(H[i], H[i - 1])))
        self.U = U[:k + 1] + [u] + U[k + 1:]
        if self.W:
            self.W = [h[dim] for h in Q]
            self.P = [tuple(c / (h[dim] or 1.0) for c in h[:dim]) for h in Q]
        else:
            self.P = Q

    def sub(self, a: float, b: float) -> "Curve":
        """The piece of the curve between parameters a < b, as a clamped curve."""
        c = Curve(self.p, list(self.U), list(self.P), list(self.W) if self.W else None)
        lo, hi = c.domain
        eps = 1e-12 * max(1.0, abs(hi - lo))

        def snap(u):
            u = min(max(u, lo), hi)
            for k in c.U:
                if abs(k - u) <= eps:
                    return k
            return u
        a, b = snap(a), snap(b)
        if b - a <= eps:
            raise ValueError("empty curve piece")
        for u in (a, b):
            for _ in range(c.p - sum(1 for k in c.U if k == u)):
                c._insert(u)
        ia = c.U.index(a)
        ma = c.U.count(a)
        jb = len(c.U) - 1 - c.U[::-1].index(b)
        mb = c.U.count(b)
        K = [a] * max(0, c.p + 1 - ma) + c.U[ia:jb + 1] + [b] * max(0, c.p + 1 - mb)
        # drop surplus end knots (multiplicity above p+1 cannot occur after insertion)
        p0 = ia + ma - c.p - 1
        npts = len(K) - c.p - 1
        return Curve(c.p, K, c.P[p0:p0 + npts], c.W[p0:p0 + npts] if c.W else None)

    def closest(self, q: tuple, samples: int = 0) -> tuple[float, float]:
        """(parameter, distance) of the curve point nearest q."""
        lo, hi = self.domain
        n = samples or max(64, 4 * len(self.P))
        best = (lo, float("inf"))
        for i in range(n + 1):
            u = lo + (hi - lo) * i / n
            d = math.dist(self(u), q)
            if d < best[1]:
                best = (u, d)
        u, d = best
        h = (hi - lo) / n
        for _ in range(60):
            moved = False
            for uu in (u - h, u + h):
                uu = min(max(uu, lo), hi)
                dd = math.dist(self(uu), q)
                if dd < d:
                    u, d, moved = uu, dd, True
            if not moved:
                h /= 2
                if h < 1e-15 * max(1.0, abs(hi - lo)):
                    break
        return u, d


class Surface:
    def __init__(self, pu: int, pv: int, U: list[float], V: list[float], grid: list[list[tuple]],
                 weights: list[list[float]] | None = None):
        self.pu, self.pv, self.U, self.V, self.G, self.W = pu, pv, U, V, grid, weights
        if len(U) != len(grid) + pu + 1 or len(V) != len(grid[0]) + pv + 1:
            raise ValueError("bad B-spline surface dimensions")

    @property
    def domain(self):
        return (self.U[self.pu], self.U[len(self.G)]), (self.V[self.pv], self.V[len(self.G[0])])

    def __call__(self, u: float, v: float) -> tuple:
        nu, nv = len(self.G) - 1, len(self.G[0]) - 1
        su = find_span(nu, self.pu, u, self.U)
        sv = find_span(nv, self.pv, v, self.V)
        Nu = basis(su, u, self.pu, self.U)
        Nv = basis(sv, v, self.pv, self.V)
        acc = [0.0, 0.0, 0.0]
        wsum = 0.0
        for a in range(self.pu + 1):
            i = su - self.pu + a
            for b in range(self.pv + 1):
                j = sv - self.pv + b
                w = self.W[i][j] if self.W else 1.0
                c = Nu[a] * Nv[b] * w
                wsum += c
                q = self.G[i][j]
                acc[0] += c * q[0]
                acc[1] += c * q[1]
                acc[2] += c * q[2]
        return (acc[0] / wsum, acc[1] / wsum, acc[2] / wsum) if wsum else tuple(acc)


# --- interpolation ------------------------------------------------------------------------

def _solve(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    """Gaussian elimination with partial pivoting (systems here are small and banded)."""
    n = len(A)
    M = [row[:] + b[:] for row, b in zip(A, B)]
    k = len(B[0])
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) < 1e-300:
            raise ValueError("singular interpolation system")
        M[c], M[piv] = M[piv], M[c]
        inv = 1.0 / M[c][c]
        for r in range(c + 1, min(n, c + 8)):
            f = M[r][c] * inv
            if f:
                Mr, Mc = M[r], M[c]
                for j in range(c, n + k):
                    Mr[j] -= f * Mc[j]
    X = [[0.0] * k for _ in range(n)]
    for r in range(n - 1, -1, -1):
        for j in range(k):
            s = M[r][n + j] - sum(M[r][c] * X[c][j] for c in range(r + 1, min(n, r + 8)))
            X[r][j] = s / M[r][r]
    return X


def chord_params(pts: list[tuple]) -> list[float]:
    d = [0.0]
    for a, b in zip(pts, pts[1:]):
        d.append(d[-1] + math.dist(a, b))
    total = d[-1] or 1.0
    return [x / total for x in d]


def interpolate(pts: list[tuple], degree: int = 3, params: list[float] | None = None,
                dedupe: bool = True) -> Curve:
    """Curve through all points (clamped, averaged knots)."""
    q = [pts[0]]
    for x in pts[1:]:
        if not dedupe or math.dist(x, q[-1]) > 1e-12:
            q.append(x)
    if len(q) < 2:
        q = [pts[0], pts[-1]]
    n = len(q)
    p = min(degree, n - 1)
    t = params if params and len(params) == n else chord_params(q)
    U = [0.0] * (p + 1)
    for j in range(1, n - p):
        U.append(sum(t[j:j + p]) / p)
    U += [1.0] * (p + 1)
    if p == 1:
        return Curve(1, U, q)
    A = []
    for i in range(n):
        s = find_span(n - 1, p, t[i], U)
        row = [0.0] * n
        for j, b in enumerate(basis(s, t[i], p, U)):
            row[s - p + j] = b
        A.append(row)
    X = _solve(A, [list(x) for x in q])
    return Curve(p, U, [tuple(x) for x in X])


def interpolate_grid(grid: list[list[tuple]], degree: int = 3) -> Surface:
    """Surface through a rows x cols grid of points (rows -> u, cols -> v)."""
    rows, cols = len(grid), len(grid[0])
    tu = [sum(x) / cols for x in zip(*[chord_params([grid[i][j] for i in range(rows)]) for j in range(cols)])]
    tv = [sum(x) / rows for x in zip(*[chord_params(grid[i]) for i in range(rows)])]
    # make strictly increasing
    for t in (tu, tv):
        for i in range(1, len(t)):
            if t[i] <= t[i - 1]:
                t[i] = t[i - 1] + 1e-9
        span = t[-1] - t[0] or 1.0
        for i in range(len(t)):
            t[i] = (t[i] - t[0]) / span
    # interpolate along v for each row, then along u for each control column
    rows_c = [interpolate(grid[i], degree, tv, dedupe=False) for i in range(rows)]
    V = rows_c[0].U
    cols_c = [interpolate([rows_c[i].P[j] for i in range(rows)], degree, tu, dedupe=False)
              for j in range(len(V) - rows_c[0].p - 1)]
    U = cols_c[0].U
    G = [[cols_c[j].P[i] for j in range(len(cols_c))] for i in range(len(cols_c[0].P))]
    return Surface(cols_c[0].p, rows_c[0].p, U, V, G)
