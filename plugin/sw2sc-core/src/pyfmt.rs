//! Python's number formatting, where the Python writes numbers into strings (expressions such as
//! `repr(round(x, 9))`), so the port writes the same text.

/// Python's `round(x, nd)`: the nearest decimal with `nd` places.
pub fn round(x: f64, nd: usize) -> f64 {
    if !x.is_finite() {
        return x;
    }
    format!("{x:.nd$}").parse().unwrap_or(x)
}

/// The shortest round-trip digits of `x` (no sign) and its decimal exponent: x = 0.d1d2… × 10^(e+1).
fn digits(x: f64) -> (String, i32) {
    let s = format!("{:e}", x.abs()); // e.g. "1.2345e-5": shortest round-trip, as Python's repr
    let (m, e) = s.split_once('e').unwrap();
    (m.replace('.', ""), e.parse().unwrap())
}

/// Python's `repr(float)`.
pub fn repr(x: f64) -> String {
    if x.is_nan() {
        return "nan".into();
    }
    if x.is_infinite() {
        return if x > 0.0 { "inf".into() } else { "-inf".into() };
    }
    if x == 0.0 {
        return if x.is_sign_negative() { "-0.0".into() } else { "0.0".into() };
    }
    let sign = if x < 0.0 { "-" } else { "" };
    let (d, e) = digits(x);
    if (-4..16).contains(&e) {
        let body = if e >= 0 {
            let int_len = (e + 1) as usize;
            if d.len() <= int_len {
                format!("{}{}.0", d, "0".repeat(int_len - d.len()))
            } else {
                format!("{}.{}", &d[..int_len], &d[int_len..])
            }
        } else {
            format!("0.{}{}", "0".repeat((-e - 1) as usize), d)
        };
        format!("{sign}{body}")
    } else {
        let mant = if d.len() > 1 { format!("{}.{}", &d[..1], &d[1..]) } else { d.clone() };
        format!("{sign}{mant}e{}{:02}", if e < 0 { '-' } else { '+' }, e.abs())
    }
}

/// Python's `format(x, "g")`: 6 significant digits, trailing zeros dropped.
pub fn g(x: f64) -> String {
    if x == 0.0 {
        return "0".into();
    }
    if !x.is_finite() {
        return repr(x);
    }
    let sci = format!("{:.5e}", x); // 6 significant digits, rounded
    let (m, e) = sci.split_once('e').unwrap();
    let e: i32 = e.parse().unwrap();
    if (-4..6).contains(&e) {
        let decimals = (5 - e).max(0) as usize;
        let s = format!("{:.*}", decimals, x);
        if s.contains('.') {
            s.trim_end_matches('0').trim_end_matches('.').to_string()
        } else {
            s
        }
    } else {
        let m = if m.contains('.') { m.trim_end_matches('0').trim_end_matches('.').to_string() } else { m.to_string() };
        format!("{m}e{}{:02}", if e < 0 { '-' } else { '+' }, e.abs())
    }
}

/// Python's `str()` of a JSON-ish number value (an int stays an int).
pub fn str_num(v: &serde_json::Value) -> String {
    match v {
        serde_json::Value::Number(n) if n.is_f64() => repr(n.as_f64().unwrap()),
        other => other.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reprs() {
        for (x, s) in [
            (1.0, "1.0"), (12.5, "12.5"), (1e-5, "1e-05"), (0.0001, "0.0001"), (1e16, "1e+16"),
            (123456789.0, "123456789.0"), (-2.5, "-2.5"), (0.1 + 0.2, "0.30000000000000004"),
            (1.5e-7, "1.5e-07"), (1e15, "1000000000000000.0"),
        ] {
            assert_eq!(repr(x), s, "{x}");
        }
        assert_eq!(g(4.0), "4");
        assert_eq!(g(0.7), "0.7");
        assert_eq!(g(1.25), "1.25");
        assert_eq!(round(2.675, 2), 2.67);
    }
}
