//! Small NURBS toolkit: evaluation, trimming and interpolation (port of `sw2sc/nurbs.py`).
//! Textbook algorithms (Cox-de Boor evaluation, chord-length cubic interpolation solved as a
//! banded linear system). Knots are full (expanded) vectors here.

pub type P = Vec<f64>;

pub fn dist(a: &[f64], b: &[f64]) -> f64 {
    a.iter().zip(b).map(|(x, y)| (x - y) * (x - y)).sum::<f64>().sqrt()
}

pub fn expand_knots(knots: &[f64], mults: &[i64]) -> Vec<f64> {
    let mut out = Vec::new();
    for (k, m) in knots.iter().zip(mults) {
        for _ in 0..(*m).max(0) {
            out.push(*k);
        }
    }
    out
}

/// Knots this close are one (a rounding error apart; see the Python).
pub fn knot_eps(full: &[f64]) -> f64 {
    1e-12 * full.iter().fold(1.0f64, |m, k| m.max(k.abs()))
}

pub fn compress_knots(full: &[f64], eps: f64) -> (Vec<f64>, Vec<i64>) {
    let (mut ks, mut ms): (Vec<f64>, Vec<i64>) = (vec![], vec![]);
    for &k in full {
        if ks.last().is_some_and(|l| (k - l).abs() <= eps) {
            *ms.last_mut().unwrap() += 1;
        } else {
            ks.push(k);
            ms.push(1);
        }
    }
    (ks, ms)
}

/// Span index for parameter u; n = number of control points - 1.
pub fn find_span(n: usize, p: usize, u: f64, uk: &[f64]) -> usize {
    if u >= uk[n + 1] {
        return n;
    }
    if u <= uk[p] {
        return p;
    }
    let k = uk.partition_point(|x| *x <= u) as isize - 1; // bisect_right - 1
    (k.max(p as isize) as usize).min(n)
}

pub fn basis(span: usize, u: f64, p: usize, uk: &[f64]) -> Vec<f64> {
    let mut n = vec![0.0; p + 1];
    n[0] = 1.0;
    let mut left = vec![0.0; p + 1];
    let mut right = vec![0.0; p + 1];
    for j in 1..=p {
        left[j] = u - uk[span + 1 - j];
        right[j] = uk[span + j] - u;
        let mut saved = 0.0;
        for r in 0..j {
            let den = right[r + 1] + left[j - r];
            let tmp = if den != 0.0 { n[r] / den } else { 0.0 };
            n[r] = saved + right[r + 1] * tmp;
            saved = left[j - r] * tmp;
        }
        n[j] = saved;
    }
    n
}

#[derive(Clone, Debug)]
pub struct Curve {
    pub p: usize,
    pub u: Vec<f64>,
    pub pts: Vec<P>,
    pub w: Option<Vec<f64>>,
}

#[derive(Debug)]
pub struct NurbsError(pub String);

impl Curve {
    pub fn new(degree: usize, knots: Vec<f64>, pts: Vec<P>, weights: Option<Vec<f64>>) -> Result<Self, NurbsError> {
        if knots.len() != pts.len() + degree + 1 {
            return Err(NurbsError(format!("bad B-spline: {} knots, {} points, degree {}", knots.len(), pts.len(), degree)));
        }
        Ok(Curve { p: degree, u: knots, pts, w: weights })
    }

    pub fn domain(&self) -> (f64, f64) {
        (self.u[self.p], self.u[self.pts.len()])
    }

    pub fn at(&self, u: f64) -> P {
        let n = self.pts.len() - 1;
        let s = find_span(n, self.p, u, &self.u);
        let nb = basis(s, u, self.p, &self.u);
        let dim = self.pts[0].len();
        let mut acc = vec![0.0; dim];
        let mut wsum = 0.0;
        for (j, b) in nb.iter().enumerate().take(self.p + 1) {
            let i = s - self.p + j;
            let w = self.w.as_ref().map_or(1.0, |w| w[i]);
            let c = b * w;
            wsum += c;
            for d in 0..dim {
                acc[d] += c * self.pts[i][d];
            }
        }
        if wsum != 0.0 { acc.iter().map(|a| a / wsum).collect() } else { acc }
    }

    /// Boehm knot insertion on homogeneous points.
    fn insert(&mut self, u: f64) {
        let p = self.p;
        let n = self.pts.len() - 1;
        let k = find_span(n, p, u, &self.u);
        let dim = self.pts[0].len();
        let h: Vec<Vec<f64>> = (0..self.pts.len())
            .map(|i| {
                let w = self.w.as_ref().map_or(1.0, |w| w[i]);
                let mut v: Vec<f64> = self.pts[i].iter().map(|c| c * w).collect();
                if let Some(ws) = &self.w {
                    v.push(ws[i]);
                }
                v
            })
            .collect();
        let mut q: Vec<Vec<f64>> = Vec::new();
        for i in 0..=h.len() {
            if i + p <= k {
                q.push(h[i].clone());
            } else if i > k {
                q.push(h[i - 1].clone());
            } else {
                let den = self.u[i + p] - self.u[i];
                let a = if den != 0.0 { (u - self.u[i]) / den } else { 0.0 };
                q.push(h[i].iter().zip(&h[i - 1]).map(|(x, y)| a * x + (1.0 - a) * y).collect());
            }
        }
        let mut nu = self.u[..=k].to_vec();
        nu.push(u);
        nu.extend_from_slice(&self.u[k + 1..]);
        self.u = nu;
        if self.w.is_some() {
            self.w = Some(q.iter().map(|hh| hh[dim]).collect());
            self.pts = q.iter().map(|hh| {
                let w = if hh[dim] != 0.0 { hh[dim] } else { 1.0 };
                hh[..dim].iter().map(|c| c / w).collect()
            }).collect();
        } else {
            self.pts = q;
        }
    }

    /// The piece of the curve between parameters a < b, as a clamped curve.
    pub fn sub(&self, a: f64, b: f64) -> Result<Curve, NurbsError> {
        let mut c = self.clone();
        let (lo, hi) = c.domain();
        let eps = 1e-12 * 1f64.max((hi - lo).abs());
        let snap = |u: f64, ks: &[f64]| -> f64 {
            let u = u.max(lo).min(hi);
            ks.iter().copied().find(|k| (k - u).abs() <= eps).unwrap_or(u)
        };
        let (a, b) = (snap(a, &c.u), snap(b, &c.u));
        if b - a <= eps {
            return Err(NurbsError("empty curve piece".into()));
        }
        for u in [a, b] {
            let have = c.u.iter().filter(|k| **k == u).count();
            for _ in 0..c.p.saturating_sub(have) {
                c.insert(u);
            }
        }
        let ia = c.u.iter().position(|k| *k == a).ok_or(NurbsError("knot".into()))?;
        let ma = c.u.iter().filter(|k| **k == a).count();
        let jb = c.u.len() - 1 - c.u.iter().rev().position(|k| *k == b).ok_or(NurbsError("knot".into()))?;
        let mb = c.u.iter().filter(|k| **k == b).count();
        let mut kk = vec![a; (c.p + 1).saturating_sub(ma)];
        kk.extend_from_slice(&c.u[ia..=jb]);
        kk.extend(vec![b; (c.p + 1).saturating_sub(mb)]);
        let p0 = (ia + ma) as isize - c.p as isize - 1;
        let npts = kk.len() - c.p - 1;
        if p0 < 0 || p0 as usize + npts > c.pts.len() {
            return Err(NurbsError("piece out of range".into()));
        }
        let p0 = p0 as usize;
        Curve::new(c.p, kk, c.pts[p0..p0 + npts].to_vec(), c.w.as_ref().map(|w| w[p0..p0 + npts].to_vec()))
    }

    /// (parameter, distance) of the curve point nearest q.
    pub fn closest(&self, q: &[f64], samples: usize) -> (f64, f64) {
        let (lo, hi) = self.domain();
        let n = if samples > 0 { samples } else { 64.max(4 * self.pts.len()) };
        let mut best = (lo, f64::INFINITY);
        for i in 0..=n {
            let u = lo + (hi - lo) * i as f64 / n as f64;
            let d = dist(&self.at(u), q);
            if d < best.1 {
                best = (u, d);
            }
        }
        let (mut u, mut d) = best;
        let mut h = (hi - lo) / n as f64;
        for _ in 0..60 {
            let mut moved = false;
            for uu in [u - h, u + h] {
                let uu = uu.max(lo).min(hi);
                let dd = dist(&self.at(uu), q);
                if dd < d {
                    u = uu;
                    d = dd;
                    moved = true;
                }
            }
            if !moved {
                h /= 2.0;
                if h < 1e-15 * 1f64.max((hi - lo).abs()) {
                    break;
                }
            }
        }
        (u, d)
    }
}

#[derive(Clone, Debug)]
pub struct Surface {
    pub pu: usize,
    pub pv: usize,
    pub u: Vec<f64>,
    pub v: Vec<f64>,
    pub g: Vec<Vec<[f64; 3]>>,
    pub w: Option<Vec<Vec<f64>>>,
}

impl Surface {
    pub fn new(pu: usize, pv: usize, u: Vec<f64>, v: Vec<f64>, g: Vec<Vec<[f64; 3]>>, w: Option<Vec<Vec<f64>>>) -> Result<Self, NurbsError> {
        if g.is_empty() || u.len() != g.len() + pu + 1 || v.len() != g[0].len() + pv + 1 {
            return Err(NurbsError("bad B-spline surface dimensions".into()));
        }
        Ok(Surface { pu, pv, u, v, g, w })
    }

    pub fn domain(&self) -> ((f64, f64), (f64, f64)) {
        ((self.u[self.pu], self.u[self.g.len()]), (self.v[self.pv], self.v[self.g[0].len()]))
    }

    pub fn at(&self, u: f64, v: f64) -> [f64; 3] {
        let (nu, nv) = (self.g.len() - 1, self.g[0].len() - 1);
        let su = find_span(nu, self.pu, u, &self.u);
        let sv = find_span(nv, self.pv, v, &self.v);
        let bu = basis(su, u, self.pu, &self.u);
        let bv = basis(sv, v, self.pv, &self.v);
        let mut acc = [0.0; 3];
        let mut wsum = 0.0;
        for (a, nua) in bu.iter().enumerate() {
            let i = su - self.pu + a;
            for (b, nvb) in bv.iter().enumerate() {
                let j = sv - self.pv + b;
                let w = self.w.as_ref().map_or(1.0, |w| w[i][j]);
                let c = nua * nvb * w;
                wsum += c;
                let q = self.g[i][j];
                acc[0] += c * q[0];
                acc[1] += c * q[1];
                acc[2] += c * q[2];
            }
        }
        if wsum != 0.0 { [acc[0] / wsum, acc[1] / wsum, acc[2] / wsum] } else { acc }
    }
}

/// Gaussian elimination with partial pivoting (systems here are small and banded).
fn solve(a: &[Vec<f64>], b: &[Vec<f64>]) -> Result<Vec<Vec<f64>>, NurbsError> {
    let n = a.len();
    let k = b[0].len();
    let mut m: Vec<Vec<f64>> = a.iter().zip(b).map(|(r, bb)| r.iter().chain(bb.iter()).copied().collect()).collect();
    for c in 0..n {
        let mut piv = c;
        for r in c..n {
            if m[r][c].abs() > m[piv][c].abs() {
                piv = r;
            }
        }
        if m[piv][c].abs() < 1e-300 {
            return Err(NurbsError("singular interpolation system".into()));
        }
        m.swap(c, piv);
        let inv = 1.0 / m[c][c];
        for r in (c + 1)..n.min(c + 8) {
            let f = m[r][c] * inv;
            if f != 0.0 {
                let mc = m[c].clone();
                for j in c..n + k {
                    m[r][j] -= f * mc[j];
                }
            }
        }
    }
    let mut x = vec![vec![0.0; k]; n];
    for r in (0..n).rev() {
        for j in 0..k {
            let s = m[r][n + j] - ((r + 1)..n.min(r + 8)).map(|c| m[r][c] * x[c][j]).sum::<f64>();
            x[r][j] = s / m[r][r];
        }
    }
    Ok(x)
}

pub fn chord_params(pts: &[P]) -> Vec<f64> {
    let mut d = vec![0.0];
    for w in pts.windows(2) {
        d.push(d.last().unwrap() + dist(&w[0], &w[1]));
    }
    let total = if *d.last().unwrap() != 0.0 { *d.last().unwrap() } else { 1.0 };
    d.iter().map(|x| x / total).collect()
}

/// Curve through all points (clamped, averaged knots).
pub fn interpolate(pts: &[P], degree: usize, params: Option<&[f64]>, dedupe: bool) -> Result<Curve, NurbsError> {
    let mut q: Vec<P> = vec![pts[0].clone()];
    for x in &pts[1..] {
        if !dedupe || dist(x, q.last().unwrap()) > 1e-12 {
            q.push(x.clone());
        }
    }
    if q.len() < 2 {
        q = vec![pts[0].clone(), pts[pts.len() - 1].clone()];
    }
    let n = q.len();
    let p = degree.min(n - 1);
    let t: Vec<f64> = match params {
        Some(ps) if ps.len() == n => ps.to_vec(),
        _ => chord_params(&q),
    };
    let mut uk = vec![0.0; p + 1];
    for j in 1..(n - p) {
        uk.push(t[j..j + p].iter().sum::<f64>() / p as f64);
    }
    uk.extend(vec![1.0; p + 1]);
    if p == 1 {
        return Curve::new(1, uk, q, None);
    }
    let mut a = Vec::with_capacity(n);
    for &ti in t.iter().take(n) {
        let s = find_span(n - 1, p, ti, &uk);
        let mut row = vec![0.0; n];
        for (j, b) in basis(s, ti, p, &uk).iter().enumerate() {
            row[s - p + j] = *b;
        }
        a.push(row);
    }
    let x = solve(&a, &q)?;
    Curve::new(p, uk, x, None)
}

/// Surface through a rows x cols grid of points (rows -> u, cols -> v).
pub fn interpolate_grid(grid: &[Vec<[f64; 3]>], degree: usize) -> Result<Surface, NurbsError> {
    let (rows, cols) = (grid.len(), grid[0].len());
    let colp: Vec<Vec<f64>> = (0..cols).map(|j| chord_params(&(0..rows).map(|i| grid[i][j].to_vec()).collect::<Vec<_>>())).collect();
    let mut tu: Vec<f64> = (0..rows).map(|i| colp.iter().map(|c| c[i]).sum::<f64>() / cols as f64).collect();
    let rowp: Vec<Vec<f64>> = (0..rows).map(|i| chord_params(&grid[i].iter().map(|x| x.to_vec()).collect::<Vec<_>>())).collect();
    let mut tv: Vec<f64> = (0..cols).map(|j| rowp.iter().map(|r| r[j]).sum::<f64>() / rows as f64).collect();
    // make strictly increasing (as the Python, t[0] moved to 0 first and the rest from it)
    for t in [&mut tu, &mut tv] {
        for i in 1..t.len() {
            if t[i] <= t[i - 1] {
                t[i] = t[i - 1] + 1e-9;
            }
        }
        let span = if t[t.len() - 1] - t[0] != 0.0 { t[t.len() - 1] - t[0] } else { 1.0 };
        for i in 0..t.len() {
            t[i] = (t[i] - t[0]) / span;
        }
    }
    let rows_c: Vec<Curve> = (0..rows)
        .map(|i| interpolate(&grid[i].iter().map(|x| x.to_vec()).collect::<Vec<_>>(), degree, Some(&tv), false))
        .collect::<Result<_, _>>()?;
    let vk = rows_c[0].u.clone();
    let ncols = vk.len() - rows_c[0].p - 1;
    let cols_c: Vec<Curve> = (0..ncols)
        .map(|j| interpolate(&(0..rows).map(|i| rows_c[i].pts[j].clone()).collect::<Vec<_>>(), degree, Some(&tu), false))
        .collect::<Result<_, _>>()?;
    let uk = cols_c[0].u.clone();
    let g: Vec<Vec<[f64; 3]>> = (0..cols_c[0].pts.len()).map(|i| cols_c.iter().map(|c| [c.pts[i][0], c.pts[i][1], c.pts[i][2]]).collect()).collect();
    Surface::new(cols_c[0].p, rows_c[0].p, uk, vk, g, None)
}
