//! A SolidWorks part as a SolidCraft design with its feature tree (port of the part path of
//! `solidcraft.convert` and `_feature_tree` in `sw2sc/solidcraft.py`).
//!
//! The tree read from the file is used when every feature converts and its rebuild matches the
//! solid SolidWorks saved (read from the part's Parasolid body); otherwise the part keeps that
//! solid, and the report says which features are still TBD.

use std::collections::HashMap;

use serde_json::{json, Value};

use crate::features::{read, Feature};
use crate::search::{rebuild, Outcome};
use crate::step::{part_to_step, VERSION};
use crate::swfile::SwFile;
use crate::verify::{fully_decoded, mismatch_signature, same, Evaluator};

pub const FORMAT: &str = "solidcraft/28";
pub const METADATA_KEY: &str = "io.sw2sc.solidworks";

/// What happened to the part, for the import report.
#[derive(Debug, Default)]
pub struct Report {
    /// The tree was rebuilt and matches the solid.
    pub tree: bool,
    pub summary: String,
    /// (severity, title, subject, message, code)
    pub items: Vec<(String, String, String, String, String)>,
    pub details: Value,
}

impl Report {
    fn item(&mut self, severity: &str, title: &str, subject: &str, message: &str, code: &str) {
        self.items.push((severity.into(), title.into(), subject.into(), message.into(), code.into()));
    }

    /// The loss report SolidCraft's importer interface takes.
    pub fn to_json(&self) -> Value {
        json!({
            "summary": self.summary,
            "items": self.items.iter().map(|(s, t, sub, m, c)| json!({"severity": s, "title": t, "subject": sub, "message": m, "code": c})).collect::<Vec<_>>(),
            "details": self.details,
        })
    }
}

/// The feature tree for the design's metadata: each feature's name, kind and whether it converted.
pub fn tree_summary(feats: &[Feature]) -> Vec<Value> {
    feats
        .iter()
        .map(|f| {
            let sk_bad = f.kind == "sketch" && f.sketch.as_ref().is_some_and(|s| s.planes.is_empty() || !s.problems.is_empty());
            let tbd = f.kind == "tbd" || !f.reason.is_empty() || sk_bad;
            // an absorbed feature is in the tree, making no solid (an unused sketch, a reference
            // axis …): no blocker
            let status = if f.kind == "absorbed" { "kept" } else if tbd { "tbd" } else { "read" };
            let mut item = json!({"name": f.name, "kind": f.kind, "status": status});
            if status == "kept" && !f.reason.is_empty() {
                item["why"] = json!(f.reason);
            }
            if status == "tbd" {
                let why = if !f.reason.is_empty() {
                    f.reason.clone()
                } else if let Some(s) = f.sketch.as_ref().filter(|s| !s.problems.is_empty()) {
                    s.problems.join("; ")
                } else if f.kind == "sketch" {
                    "sketch plane not read".into()
                } else {
                    String::new()
                };
                item["why"] = json!(why);
                if f.kind == "tbd" {
                    item["solidworks_class"] = json!(f.cls);
                }
            }
            item
        })
        .collect()
}

fn identity() -> Value {
    json!([[1.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 0, 1.0, 0], [0, 0, 0, 1.0]])
}

/// The part as SolidCraft design JSON, with the loss report.
pub fn convert_part(sw: &SwFile, name: &str, file_name: &str, ev: &mut dyn Evaluator) -> Result<(Value, Report), String> {
    let mut rep = Report::default();
    let (step, warnings, left_out) = part_to_step(sw, name);
    for w in warnings.iter().filter(|w| !w.starts_with("face ")) {
        rep.item("info", "Notes from reading the geometry", name, w, "geometry");
    }
    if left_out > 0 {
        rep.item("degraded", "Faces left out of the solid", name, &format!("{left_out} faces left out; the body will be open"), "faces_left_out");
    }
    let Some(step) = step else {
        return Err(warnings.first().cloned().unwrap_or_else(|| "no geometry in the part".into()));
    };
    let base = json!({
        "format": FORMAT, "name": name, "units": "mm", "params": [],
        "metadata": {METADATA_KEY: {"converter": format!("sw2sc {} (plugin)", VERSION.trim())}},
        "components": [{"id": 1, "name": name, "parent": 0, "metadata": {METADATA_KEY: {"file": file_name}}}],
        "occurrences": [{"id": 2, "component": 1, "parent": 0, "name": format!("{name}:1"), "transform": identity(), "grounded": true}],
        "features": [{"id": 3, "name": name, "suppressed": false, "component": 1, "type": "import", "file": file_name, "step": step}],
        "next_id": 4,
    });
    let feats = match read(sw) {
        Some(f) => f,
        None => {
            rep.summary = format!("{name}: the solid only (this file's feature stream isn't numbered yet)");
            rep.item("dropped", "Feature tree not read", name, "the file's feature stream isn't numbered yet; the part comes in as its solid", "tree_not_read");
            return Ok((base, rep));
        }
    };
    let mut design = base;
    let summary = tree_summary(&feats);
    design["metadata"][METADATA_KEY]["feature_tree"] = json!(summary);
    for s in &summary {
        let (name, why) = (s["name"].as_str().unwrap_or(""), s["why"].as_str().unwrap_or(""));
        if s["status"] == "tbd" {
            rep.item("dropped", "Features not converted yet", name, why, "feature_tbd");
        } else if s["status"] == "kept" {
            rep.item("info", "Kept in the tree, making no solid", name, why, "feature_kept");
        }
    }
    let mut feats = feats;
    let decoded = fully_decoded(&feats);
    let (built, outcome): (Option<Value>, Outcome) = if decoded { rebuild(&mut feats, &design, name, ev) } else { (None, Outcome::default()) };
    rep.details = json!({
        "feature_tree": summary,
        "rebuild": {"tries": outcome.tries, "timed_out": outcome.timed_out,
                    "closest": if built.is_none() && decoded { json!(mismatch_signature(outcome.closest.as_ref(), outcome.reference.as_ref())) } else { Value::Null }},
    });
    let Some(built) = built else {
        if decoded {
            rep.summary = format!("{name}: its solid, with the feature tree in the metadata (the tree's rebuild didn't match the solid)");
            rep.item("degraded", "Feature tree read but not used", name,
                     &format!("its rebuild didn't match the part's own solid: {}", mismatch_signature(outcome.closest.as_ref(), outcome.reference.as_ref())),
                     "tree_mismatch");
        } else if feats.iter().all(|f| ["import", "sketch", "plane", "absorbed"].contains(&f.kind.as_str()))
            && (feats.is_empty() || feats.iter().any(|f| f.kind == "import"))
        {
            // an imported body, or a mirror of another part file: no history in this file to rebuild
            rep.summary = format!("{name}: its solid (the part has no feature history of its own: an imported or derived body)");
            rep.item("info", "No feature history in this file", name, "an imported body, or a part derived from another part file", "no_history");
        } else {
            rep.summary = format!("{name}: its solid, with the feature tree in the metadata (not every feature converts yet)");
        }
        return Ok((design, rep));
    };
    // the rebuilt features, numbered after the part's own, in its component
    let base_id = design["next_id"].as_i64().unwrap_or(4);
    let bf = built["features"].as_array().cloned().unwrap_or_default();
    let remap: HashMap<i64, i64> = bf.iter().enumerate().map(|(i, f)| (f["id"].as_i64().unwrap_or(0), base_id + i as i64)).collect();
    let fref = regex::Regex::new(r"F(\d+):").unwrap();
    let mut feats_out = Vec::new();
    for f in &bf {
        let mut g = f.clone();
        g["id"] = json!(remap[&f["id"].as_i64().unwrap_or(0)]);
        if let Some(s) = g.get("sketch").and_then(Value::as_i64) {
            g["sketch"] = json!(remap.get(&s).copied().unwrap_or(s));
        }
        if let Some(s) = g.get("points").and_then(|p| p.get("sketch")).and_then(Value::as_i64) {
            g["points"]["sketch"] = json!(remap.get(&s).copied().unwrap_or(s)); // a hole's sketch
        }
        if let Some(names) = g.get("edge_names").and_then(Value::as_array).cloned() {
            // a fillet's edges are named after the features that made them
            let renamed: Vec<Value> = names
                .iter()
                .map(|n| {
                    let n = n.as_str().unwrap_or("");
                    json!(fref.replace_all(n, |c: &regex::Captures| {
                        let id: i64 = c[1].parse().unwrap_or(0);
                        format!("F{}:", remap.get(&id).copied().unwrap_or(id))
                    }).into_owned())
                })
                .collect();
            g["edge_names"] = json!(renamed);
        }
        g["component"] = json!(1);
        feats_out.push(g);
    }
    let mut final_design = design.clone();
    final_design["format"] = built["format"].clone();
    final_design["next_id"] = json!(base_id + feats_out.len() as i64);
    let mut params = design["params"].as_array().cloned().unwrap_or_default();
    params.extend(built["params"].as_array().cloned().unwrap_or_default());
    final_design["params"] = json!(params);
    final_design["features"] = json!(feats_out);
    // the final design, components and all, must still match the imported solid
    let a = ev.evaluate(&design);
    let b = ev.evaluate(&final_design);
    if !same(b.as_ref(), a.as_ref()) {
        rep.summary = format!("{name}: its solid, with the feature tree in the metadata (the rebuilt design didn't match)");
        rep.item("degraded", "Feature tree read but not used", name, "the rebuilt design, placed in its component, didn't match the solid", "tree_mismatch");
        return Ok((design, rep));
    }
    rep.tree = true;
    let n = feats_out.len();
    rep.summary = format!("{name}: rebuilt from its {n} features (matches the solid SolidWorks saved)");
    Ok((final_design, rep))
}
