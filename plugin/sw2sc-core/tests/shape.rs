//! Geometric acceptance of generated solids, using solidcraft-cli when it is available.
use std::collections::HashMap;

use sw2sc_core::cli::CliEvaluator;
use sw2sc_core::design::{design, Choices, Picks};
use sw2sc_core::features::{Feature, Sketch, FRONT};
use sw2sc_core::verify::{same_shape, same_shape_by_faces, Eval, Evaluator};

struct NoDifference(CliEvaluator);

impl Evaluator for NoDifference {
    fn evaluate(&mut self, design: &serde_json::Value) -> Option<Eval> { self.0.evaluate(design) }
    fn edges(&mut self, design: &serde_json::Value) -> Option<serde_json::Value> { self.0.edges(design) }
    fn faces(&mut self, design: &serde_json::Value) -> Option<serde_json::Value> { self.0.faces(design) }
    fn difference_volume(&mut self, _target: &serde_json::Value, _tool: &serde_json::Value) -> Option<f64> { None }
    fn now(&self) -> f64 { self.0.now() }
}

fn box_design(move_by: f64) -> serde_json::Value {
    let mut sk = Sketch::new("Sketch1", 0);
    for (k, (x, y)) in [(1, (0.0, 0.0)), (2, (10.0, 0.0)), (3, (10.0, 10.0)), (4, (0.0, 10.0))] {
        sk.points.insert(k, (x / 1000.0, y / 1000.0));
    }
    sk.lines = vec![(1, 2), (2, 3), (3, 4), (4, 1)];
    sk.add_plane(&(FRONT, [0.0; 3]), "test", false);
    let mut sketch = Feature::new("sketch", "Sketch1", 0, "moProfileFeature_c");
    sketch.sketch = Some(sk);
    let mut boss = Feature::new("boss", "Boss-Extrude1", 1, "moExtrusion_c");
    boss.profile = Some("Sketch1".into());
    boss.depth_mm = Some(10.0);
    let mut feats = vec![sketch, boss];
    if move_by != 0.0 {
        let mut movement = Feature::new("move", "Move", 2, "moMoveCopyBody_c");
        movement.translate = Some([move_by, 0.0, 0.0]);
        feats.push(movement);
    }
    design("Box", &mut feats, &Choices::new(), &HashMap::new(), true, &Picks::new(), None)
}

#[test]
fn identical_solids_pass_and_a_shifted_solid_fails() {
    let Some(mut ev) = CliEvaluator::find() else { return };
    let reference = box_design(0.0);
    let same = box_design(0.0);
    let shifted = box_design(20.0);
    assert!(same_shape(&mut ev, &reference, &same));
    assert!(!same_shape(&mut ev, &reference, &shifted));
    assert!(same_shape_by_faces(&mut ev, &reference, &same));
    assert!(!same_shape_by_faces(&mut ev, &reference, &shifted));
    let mut without_booleans = NoDifference(ev);
    assert!(same_shape(&mut without_booleans, &reference, &same));
    assert!(!same_shape(&mut without_booleans, &reference, &shifted));
}
