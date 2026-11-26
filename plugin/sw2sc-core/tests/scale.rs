//! A scale's origin is found by the rebuild (as the Python's ScaleTests). Needs solidcraft-cli.
use std::collections::HashMap;

use serde_json::json;
use sw2sc_core::cli::CliEvaluator;
use sw2sc_core::design::{design, Choices, Picks};
use sw2sc_core::features::{Feature, Sketch, FRONT};
use sw2sc_core::search::rebuild;
use sw2sc_core::verify::{Evaluator, TIME_BUDGET};

#[test]
fn rebuild_budget_is_five_minutes() {
    assert_eq!(TIME_BUDGET, 300.0);
}

#[test]
fn the_rebuild_finds_what_a_scale_is_about() {
    let Some(mut ev) = CliEvaluator::find() else { return };
    // an L-shaped plate, 10 mm thick, scaled 1.06 about its centre of mass
    let mut s = Sketch::new("Sketch1", 0);
    for (k, (x, y)) in [(1, (0.0, 0.0)), (2, (40.0, 0.0)), (3, (40.0, 10.0)), (4, (10.0, 10.0)), (5, (10.0, 30.0)), (6, (0.0, 30.0))] {
        s.points.insert(k, (x / 1000.0, y / 1000.0));
    }
    s.lines = vec![(1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 1)];
    s.add_plane(&(FRONT, [0.0; 3]), "test", false);
    let mut sk = Feature::new("sketch", "Sketch1", 0, "moProfileFeature_c");
    sk.sketch = Some(s);
    let mut boss = Feature::new("boss", "Boss-Extrude1", 1, "moExtrusion_c");
    boss.depth_mm = Some(10.0);
    boss.profile = Some("Sketch1".into());
    let mut sc = Feature::new("scale", "Scale1", 2, "moScale_c");
    sc.scale = Some([1.06; 3]);
    let mut feats = vec![sk, boss, sc];
    let planes = HashMap::new();
    let pre = design("t", &mut feats, &Choices::new(), &planes, true, &Picks::new(), Some("Boss-Extrude1"));
    let com = ev.evaluate(&pre).unwrap().com.unwrap();
    let mut reference = design("t", &mut feats, &Choices::new(), &planes, true, &Picks::new().with("scale:Scale1", json!(com)), None);
    reference.as_object_mut().unwrap().remove("pending");
    let (built, _out) = rebuild(&mut feats, &reference, "t", &mut ev);
    let built = built.expect("a rebuild that matches");
    let g = built["features"].as_array().unwrap().iter().find(|x| x["type"] == "scale").unwrap().clone();
    assert_eq!(g["factor"], "1.06");
    let o: Vec<f64> = g["origin"].as_array().unwrap().iter().map(|v| v.as_f64().unwrap()).collect();
    for k in 0..3 {
        assert!((o[k] - com[k]).abs() < 1e-6, "origin {o:?} against the centre of mass {com:?}");
    }
}
