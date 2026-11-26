//! Revolves and revolved cuts are built at their place in the history. Needs solidcraft-cli.
use std::collections::HashMap;

use serde_json::json;
use sw2sc_core::cli::CliEvaluator;
use sw2sc_core::design::{design, Choices, Picks};
use sw2sc_core::features::{Feature, Sketch, FRONT};
use sw2sc_core::search::rebuild;

#[test]
fn the_rebuild_builds_a_revolve_and_revolved_cut() {
    let Some(mut ev) = CliEvaluator::find() else { return };
    let mut s = Sketch::new("Sketch1", 0);
    for (k, (x, y)) in [(1, (10.0, 0.0)), (2, (20.0, 0.0)), (3, (20.0, 10.0)), (4, (10.0, 10.0))] {
        s.points.insert(k, (x / 1000.0, y / 1000.0));
    }
    s.lines = vec![(1, 2), (2, 3), (3, 4), (4, 1)];
    s.add_plane(&(FRONT, [0.0; 3]), "test", false);
    let mut sk = Feature::new("sketch", "Sketch1", 0, "moProfileFeature_c");
    sk.sketch = Some(s);
    let mut boss = Feature::new("revolve", "Revolve1", 1, "moRevolution_c");
    boss.profile = Some("Sketch1".into());
    boss.angle_deg = 360.0;
    let mut cut = Feature::new("revcut", "Cut-Revolve1", 2, "moRevCut_c");
    cut.profile = Some("Sketch1".into());
    cut.angle_deg = 90.0;
    let mut feats = vec![sk, boss, cut];
    let mut choices = Choices::new();
    choices.insert("Revolve1".into(), json!([0, 1]));
    choices.insert("Cut-Revolve1".into(), json!([0, 1]));
    let planes = HashMap::new();
    let reference = design("t", &mut feats, &choices, &planes, true, &Picks::new(), None);
    let (built, _out) = rebuild(&mut feats, &reference, "t", &mut ev);
    let built = built.expect("a rebuild that matches");
    let revolves: Vec<_> = built["features"].as_array().unwrap().iter().filter(|x| x["type"] == "revolve").collect();
    assert_eq!(revolves.len(), 2);
    assert_eq!(revolves[0]["operation"], "new_body");
    assert_eq!(revolves[0]["angle"], "360.0");
    assert_eq!(revolves[1]["operation"], "cut");
    assert_eq!(revolves[1]["angle"], "90.0");
    assert_eq!(revolves[0]["axis"], json!({"type": "sketch_axis", "axis": "x"}));
    assert_eq!(revolves[1]["axis"], json!({"type": "sketch_axis", "axis": "x"}));
}
