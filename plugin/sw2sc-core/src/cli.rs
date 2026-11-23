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

    fn eval_raw(&self, path: &Path) -> Option<Value> {
        let out = Command::new(&self.cli).arg("eval").arg(path).output().ok()?;
        serde_json::from_slice(&out.stdout).ok()
    }

    /// `model.<what>` for each body of the design, the results joined.
    fn per_body(&mut self, design: &Value, what: &str, key: &str) -> Option<Value> {
        let src = self.write(design);
        let ev = self.eval_raw(&src)?;
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
        self.eval_raw(&p).map(|d| eval_from(&d))
    }

    fn edges(&mut self, design: &Value) -> Option<Value> {
        self.per_body(design, "edges", "edges")
    }

    fn faces(&mut self, design: &Value) -> Option<Value> {
        self.per_body(design, "faces", "faces")
    }

    fn now(&self) -> f64 {
        self.start.elapsed().as_secs_f64()
    }
}
