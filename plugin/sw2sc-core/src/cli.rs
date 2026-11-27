//! [`Evaluator`] over `solidcraft-cli`, for running the converter natively (tests, comparing
//! with the Python). The plugin uses the host's `evaluate` interface instead.

use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Instant;

use serde_json::{json, Value};

use crate::verify::{eval_from, Eval, Evaluator};

pub struct CliEvaluator {
    pub cli: PathBuf,
    dir: PathBuf,
    start: Instant,
    n: u64,
}

impl CliEvaluator {
    pub fn new(cli: impl Into<PathBuf>) -> Self {
        let dir = std::env::temp_dir().join(format!("sw2sc-rs-{}", std::process::id()));
        let _ = std::fs::create_dir_all(&dir);
        CliEvaluator { cli: cli.into(), dir, start: Instant::now(), n: 0 }
    }

    /// SOLIDCRAFT_CLI, else the installed app's.
    pub fn find() -> Option<Self> {
        let env = std::env::var("SOLIDCRAFT_CLI").ok().map(PathBuf::from);
        let installed = PathBuf::from(r"C:\Program Files\SolidCraft\solidcraft-cli.exe");
        [env, Some(installed)].into_iter().flatten().find(|p| p.is_file()).map(Self::new)
    }

    fn write(&mut self, design: &Value) -> PathBuf {
        self.n += 1;
        let p = self.dir.join(format!("d{}.solidcraft", self.n % 4));
        let _ = std::fs::write(&p, serde_json::to_vec(design).unwrap());
        p
    }

    fn eval_raw(&self, path: &Path, script: Option<&Path>) -> Option<Value> {
        let mut command = Command::new(&self.cli);
        command.arg("eval").arg(script.unwrap_or(path));
        if script.is_some() {
            command.arg("--in").arg(path);
        }
        let out = command.output().ok()?;
        serde_json::from_slice(&out.stdout).ok()
    }

    /// `model.<what>` for each body of the design, the results joined.
    fn per_body(&mut self, design: &Value, what: &str, key: &str) -> Option<Value> {
        let src = self.write(design);
        let ev = self.eval_raw(&src, None)?;
        let names: Vec<String> = ev["bodies"].as_array()?.iter().filter_map(|b| b["name"].as_str().map(String::from)).collect();
        if names.is_empty() {
            return None;
        }
        let script = self.dir.join("script.json");
        let out = self.dir.join("out.json");
        let cmds: Vec<Value> = names.iter().map(|n| json!({"command": format!("model.{what}"), "params": {"body": n}})).collect();
        std::fs::write(&script, serde_json::to_vec(&json!({"commands": cmds})).ok()?).ok()?;
        let _ = std::fs::remove_file(&out);
        Command::new(&self.cli).arg("run").arg(&script).arg("--in").arg(&src).arg("--results").arg("--json-out").arg(&out).output().ok()?;
        let res: Value = serde_json::from_slice(&std::fs::read(&out).ok()?).ok()?;
        let all: Vec<Value> = res.as_array()?.iter().flat_map(|r| r[key].as_array().cloned().unwrap_or_default()).collect();
        Some(Value::Array(all))
    }
}

impl Evaluator for CliEvaluator {
    fn evaluate(&mut self, design: &Value) -> Option<Eval> {
        let p = self.write(design);
        self.eval_raw(&p, None).map(|d| eval_from(&d))
    }

    fn edges(&mut self, design: &Value) -> Option<Value> {
        self.per_body(design, "edges", "edges")
    }

    fn faces(&mut self, design: &Value) -> Option<Value> {
        self.per_body(design, "faces", "faces")
    }

    fn difference_volume(&mut self, target: &Value, tool: &Value) -> Option<f64> {
        let target_path = self.write(target);
        let tool_path = self.write(tool);
        let target_eval = self.eval_raw(&target_path, None)?;
        let tool_eval = self.eval_raw(&tool_path, None)?;
        let names = |d: &Value| {
            d["bodies"].as_array().map_or(vec![], |bodies| bodies.iter().filter_map(|b| b["name"].as_str().filter(|n| !n.is_empty()).map(String::from)).collect::<Vec<_>>())
        };
        let target_names = names(&target_eval);
        let tool_names = names(&tool_eval);
        if target_names.len() != 1 || tool_names.len() != 1 {
            return None;
        }
        let tmp = self.dir.join(format!("shape-{}", self.n));
        std::fs::create_dir_all(&tmp).ok()?;
        let result = (|| {
            let insert = tmp.join("insert.json");
            let combined = tmp.join("combined.solidcraft");
            let reply = tmp.join("insert-result.json");
            let script = json!({"commands": [{"command": "component.insert_design", "params": {"path": tool_path, "name": "Reference"}}]});
            std::fs::write(&insert, serde_json::to_vec(&script).ok()?).ok()?;
            let result = Command::new(&self.cli)
                .arg("run")
                .arg(&insert)
                .arg("--in")
                .arg(&target_path)
                .arg("--results")
                .arg("--json-out")
                .arg(&reply)
                .arg("--save")
                .arg(&combined)
                .output()
                .ok()?;
            if !result.status.success() {
                return None;
            }
            let inserted: Value = serde_json::from_slice(&std::fs::read(&reply).ok()?).ok()?;
            let created = inserted.as_array()?.last()?.get("created_bodies")?.as_array()?;
            if created.len() != 1 {
                return None;
            }
            let cut = tmp.join("cut.json");
            let script = json!({"commands": [{"command": "solid.combine", "params": {"target": target_names[0], "tools": created, "operation": "cut"}}]});
            std::fs::write(&cut, serde_json::to_vec(&script).ok()?).ok()?;
            let evaluated = self.eval_raw(&combined, Some(&cut))?;
            if !eval_from(&evaluated).errors.is_empty() {
                return None;
            }
            evaluated["total"]["volume_mm3"].as_f64()
        })();
        let _ = std::fs::remove_dir_all(&tmp);
        result
    }

    fn now(&self) -> f64 {
        self.start.elapsed().as_secs_f64()
    }
}
