use std::collections::HashMap;

use sw2sc_core::design::{design, Choices, Picks};
use sw2sc_core::features::{Feature, Sketch, FRONT};

fn features(rotation: [f64; 9]) -> Vec<Feature> {
    let mut sketch = Sketch::new("Sketch1", 0);
    for (id, (x, y)) in [(1, (0.0, 0.0)), (2, (0.01, 0.0)), (3, (0.01, 0.01)), (4, (0.0, 0.01))] {
        sketch.points.insert(id, (x, y));
    }
    sketch.lines = vec![(1, 2), (2, 3), (3, 4), (4, 1)];
    sketch.add_plane(&(FRONT, [0.0; 3]), "test", false);
    let mut sk = Feature::new("sketch", "Sketch1", 0, "moProfileFeature_c");
    sk.sketch = Some(sketch);
    let mut boss = Feature::new("boss", "Boss-Extrude1", 1, "moExtrusion_c");
    boss.profile = Some("Sketch1".into());
    boss.depth_mm = Some(5.0);
    let mut mv = Feature::new("move", "Body-Move/Copy1", 2, "moMoveCopyBody_c");
    mv.rotation = Some(rotation);
    mv.translate = Some([10.0, 20.0, 30.0]);
    vec![sk, boss, mv]
}

#[test]
fn body_rotation_and_translation_become_a_rigid_matrix() {
    let mut feats = features([0.0, -1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]);
    let d = design("Part", &mut feats, &Choices::new(), &HashMap::new(), true, &Picks::new(), None);
    let mv = d["features"].as_array().unwrap().last().unwrap();
    assert_eq!(mv["matrix"], serde_json::json!([[0.0, -1.0, 0.0, 10.0], [1.0, 0.0, 0.0, 20.0],
                                                [0.0, 0.0, 1.0, 30.0], [0.0, 0.0, 0.0, 1.0]]));
    assert!(mv.get("translate").is_none());
}

#[test]
fn identity_body_move_keeps_translate() {
    let mut feats = features([1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]);
    let d = design("Part", &mut feats, &Choices::new(), &HashMap::new(), true, &Picks::new(), None);
    let mv = d["features"].as_array().unwrap().last().unwrap();
    assert_eq!(mv["translate"], serde_json::json!(["10.0", "20.0", "30.0"]));
    assert!(mv.get("matrix").is_none());
}
