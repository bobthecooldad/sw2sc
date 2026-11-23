//! The SolidCraft importer: a SolidWorks part (`.sldprt`) in, a SolidCraft design out, with its
//! feature tree where the tree rebuilds to the part's own solid.
//!
//! The converter is `sw2sc-core`; this crate gives it SolidCraft through the importer world:
//! the file through `source`, the result through `design`, and the rebuild check through
//! `evaluate` (the staged design measured in a private session, as `solidcraft-cli eval` does).

wit_bindgen::generate!({ path: "wit", world: "importer-plugin" });

use craft::plugin::types::{FieldFailure, PluginError};
use craft::plugin::{clock, control, design, evaluate, log, source};
use exports::craft::plugin::importer::Guest;
use serde_json::{json, Value};
use sw2sc_core::convert::convert_part;
use sw2sc_core::swfile::SwFile;
use sw2sc_core::verify::{eval_from, Eval, Evaluator};

const CHUNK: usize = 1 << 20;

struct HostEvaluator {
    start_ms: u64,
}

impl HostEvaluator {
    /// Stage a design and run commands on it, one reply per command (None for a failed one).
    fn run(&mut self, d: &Value, commands: &[(&str, Value)]) -> Option<Vec<Value>> {
        evaluate::reset();
        let bytes = serde_json::to_vec(d).ok()?;
        for chunk in bytes.chunks(CHUNK) {
            evaluate::stage(chunk).ok()?;
        }
        let mut out = Vec::new();
        for (cmd, args) in commands {
            let reply = evaluate::run(cmd, &args.to_string()).ok()?;
            let v: Value = serde_json::from_str(&reply).ok()?;
            if v.get("error").is_some_and(|e| !e.is_null()) && v.as_object().is_some_and(|o| o.len() == 1) {
                return None;
            }
            out.push(v);
        }
        Some(out)
    }

    fn per_body(&mut self, d: &Value, what: &str) -> Option<Value> {
        let r = self.run(d, &[("inspect.measure", json!({}))])?;
        let names: Vec<String> = r[0]["bodies"].as_array()?.iter().filter_map(|b| b["name"].as_str().map(String::from)).collect();
        if names.is_empty() {
            return None;
        }
        let cmds: Vec<(&str, Value)> = names.iter().map(|n| (if what == "edges" { "model.edges" } else { "model.faces" }, json!({"body": n}))).collect();
        // (the design is staged already: a run after staging uses it; staging again would reset)
        let mut all = Vec::new();
        for (cmd, args) in cmds {
            let reply = evaluate::run(cmd, &args.to_string()).ok()?;
            let v: Value = serde_json::from_str(&reply).ok()?;
            all.extend(v[what].as_array().cloned().unwrap_or_default());
        }
        Some(Value::Array(all))
    }
}

impl Evaluator for HostEvaluator {
    fn evaluate(&mut self, d: &Value) -> Option<Eval> {
        let r = self.run(d, &[("inspect.measure", json!({})), ("document.inspect", json!({}))])?;
        let merged = json!({"bodies": r[0]["bodies"], "total": r[0]["total"], "timeline": r[1]["timeline"]});
        Some(eval_from(&merged))
    }

    fn edges(&mut self, d: &Value) -> Option<Value> {
        self.per_body(d, "edges")
    }

    fn faces(&mut self, d: &Value) -> Option<Value> {
        self.per_body(d, "faces")
    }

    fn now(&self) -> f64 {
        if control::cancelled() {
            return f64::INFINITY; // the user cancelled: the search's time is up
        }
        clock::now().saturating_sub(self.start_ms) as f64 / 1000.0
    }
}

fn invalid(field: &str, reason: impl ToString) -> PluginError {
    PluginError::InvalidInput(FieldFailure { field: field.into(), reason: reason.to_string() })
}

struct Importer;

impl Guest for Importer {
    fn import_file(_entry: String, file: source::FileInfo, _options: String) -> Result<String, PluginError> {
        let mut bytes = Vec::with_capacity(file.size as usize);
        while (bytes.len() as u64) < file.size {
            let chunk = source::read("", bytes.len() as u64, CHUNK as u32)?;
            if chunk.is_empty() {
                break;
            }
            bytes.extend_from_slice(&chunk);
            control::progress(0.1 * bytes.len() as f32 / file.size.max(1) as f32, "Reading the part");
        }
        let name = file.name.rsplit_once('.').map_or(file.name.as_str(), |(n, _)| n).to_string();
        let sw = SwFile::from_bytes(&file.name, &bytes).map_err(|e| invalid("file", e.0))?;
        if sw.streams.keys().any(|k| k.contains("Assembly")) && !sw.streams.contains_key(sw2sc_core::features::STREAM) {
            return Err(PluginError::Unsupported("assemblies are not converted by this plugin yet; open their parts".into()));
        }
        control::progress(0.15, "Reading the feature tree and the solid");
        let mut ev = HostEvaluator { start_ms: clock::now() };
        let (d, report) = convert_part(&sw, &name, &file.name, &mut ev).map_err(|e| PluginError::Unsupported(e))?;
        log::log(log::Level::Info, &report.summary);
        control::progress(0.95, "Writing the design");
        let text = serde_json::to_vec(&d).map_err(|e| invalid("design", e))?;
        for chunk in text.chunks(CHUNK) {
            design::write(chunk)?;
        }
        Ok(report.to_json().to_string())
    }
}

export!(Importer);
