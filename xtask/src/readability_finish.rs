//! Top-skin-only flow and regional ironing, checked against a native baseline.
use super::preview::{Segment, paths};
use crate::{
    archive::Entries,
    xml::{self, Node},
};
use anyhow::{Context, Result, ensure};
use serde_json::{Value, json};
use std::{collections::BTreeMap, fs, path::Path};

const PROCESS: &str = "Metadata/project_settings.config";
const CONFIG: &str = "Metadata/model_settings.config";
const FLOW: [(&str, &str); 2] = [
    ("top_solid_infill_flow_ratio", "1.05"),
    ("top_surface_speed", "40"),
];
const IRON: [(&str, &str); 4] = [
    ("ironing_type", "top"),
    ("ironing_flow", "10%"),
    ("ironing_speed", "20"),
    ("ironing_spacing", "0.15"),
];
fn set(n: &mut Node, key: &str, value: &str) {
    n.children
        .retain(|m| !m.is("metadata") || m.attrs.get("key").is_none_or(|k| k != key));
    let at = n
        .children
        .iter()
        .position(|m| m.is("part"))
        .unwrap_or(n.children.len());
    n.children
        .insert(at, Node::new("metadata", &[("key", key), ("value", value)]));
}
fn strip(n: &mut Node, keys: &[&str]) {
    n.children.retain(|m| {
        !m.is("metadata")
            || m.attrs
                .get("key")
                .is_none_or(|k| !keys.contains(&k.as_str()))
    });
}
pub(super) fn apply(entries: &mut Entries) -> Result<()> {
    let mut settings: Value = serde_json::from_slice(&entries[PROCESS])?;
    for (k, v) in FLOW {
        settings[k] = json!([v, v]);
    }
    entries.insert(PROCESS.into(), serde_json::to_vec_pretty(&settings)?);
    let mut config = xml::parse(&entries[CONFIG])?;
    for o in config.children.iter_mut().filter(|n| n.is("object")) {
        if o.metadata()
            .get("name")
            .is_some_and(|s| s.contains("background ironing"))
        {
            for (k, v) in IRON {
                set(o, k, v);
            }
        }
        for p in o
            .children
            .iter_mut()
            .filter(|n| n.attrs.get("subtype").is_some_and(|s| s == "modifier_part"))
        {
            set(p, "ironing_type", "no ironing");
        }
    }
    validate(&config)?;
    entries.insert(CONFIG.into(), xml::encode(&config));
    Ok(())
}
pub(super) fn validate(config: &Node) -> Result<()> {
    let objects: Vec<_> = config.children.iter().filter(|n| n.is("object")).collect();
    ensure!(objects.len() == 2, "Expected two finish coupons");
    for o in objects {
        let m = o.metadata();
        if m.get("name")
            .is_some_and(|s| s.contains("background ironing"))
        {
            for (k, v) in IRON {
                ensure!(m.get(k).is_some_and(|s| s == v), "Ironing {k} missing");
            }
        } else {
            ensure!(!m.contains_key("ironing_type"), "Left coupon must not iron");
        }
        let p = o
            .children
            .iter()
            .find(|n| n.attrs.get("subtype").is_some_and(|s| s == "modifier_part"))
            .context("Missing lettering")?;
        ensure!(
            p.metadata()
                .get("ironing_type")
                .is_some_and(|s| s == "no ironing"),
            "Letter ironing must be disabled"
        );
    }
    Ok(())
}
fn baseline(entries: &Entries) -> Result<Entries> {
    let mut entries = entries.clone();
    let source = crate::archive::read(&crate::root().join("print/garden-auger.3mf"))?;
    let original: Value = serde_json::from_slice(&source[PROCESS])?;
    let mut process: Value = serde_json::from_slice(&entries[PROCESS])?;
    for (k, _) in FLOW {
        process[k] = original[k].clone();
    }
    entries.insert(PROCESS.into(), serde_json::to_vec_pretty(&process)?);
    let mut config = xml::parse(&entries[CONFIG])?;
    for o in config.children.iter_mut().filter(|n| n.is("object")) {
        strip(o, &IRON.map(|(k, _)| k));
        for p in o.children.iter_mut().filter(|n| n.is("part")) {
            strip(p, &["ironing_type"]);
        }
    }
    entries.insert(CONFIG.into(), xml::encode(&config));
    Ok(entries)
}
fn totals(paths: &[Segment], object: u32) -> BTreeMap<(i64, String), f64> {
    let mut totals = BTreeMap::new();
    for s in paths.iter().filter(|s| s.object == object) {
        *totals
            .entry(((s.z * 1000.).round() as i64, s.feature.clone()))
            .or_default() += s.extrusion;
    }
    totals
}

pub(super) fn audit(
    entries: &Entries,
    sliced: &Entries,
    slicer: &Path,
    out: &Path,
    filament: usize,
    labels: &[super::Label],
) -> Result<Value> {
    let baseline = baseline(entries)?;
    // Only the two top-role process settings and regional ironing may change.
    // Normal meshes and filament calibration stay identical.
    ensure!(
        entries
            .iter()
            .all(|(k, v)| k == CONFIG || k == PROCESS || baseline.get(k) == Some(v)),
        "Non-regional data changed"
    );
    let (reference, _) = super::slice(&baseline, slicer, out, filament, false, &[8., 8.])?;
    let a = paths(std::str::from_utf8(&reference["Metadata/plate_1.gcode"])?)?;
    let b = paths(std::str::from_utf8(&sliced["Metadata/plate_1.gcode"])?)?;
    let mut objects = vec![];
    for object in [102, 104] {
        let before = totals(&a, object);
        let after = totals(&b, object);
        let top = before
            .keys()
            .map(|(z, _)| *z)
            .max()
            .context("No baseline paths")?;
        let mut rows = vec![];
        for ((z, feature), old) in &before {
            let new = *after
                .get(&(*z, feature.clone()))
                .context("Missing extrusion role")?;
            let expected = if feature == "Top surface" { 1.05 } else { 1. };
            ensure!(
                (new / old - expected).abs() < 0.003,
                "Unexpected local flow at {object}/{z}/{feature}: {}",
                new / old
            );
            ensure!(
                feature != "Top surface" || *z == top,
                "Unexpected buried top surface"
            );
            rows.push(json!({"z_mm":*z as f64/1000.,"feature":feature,"baseline_e_mm":old,"trial_e_mm":new,"ratio":new/old}));
        }
        let iron: Vec<_> = b
            .iter()
            .filter(|s| s.object == object && s.feature == "Ironing")
            .collect();
        ensure!(
            (object == 104) != iron.is_empty(),
            "Ironing escaped right coupon"
        );
        ensure!(
            iron.iter()
                .all(|s| (s.z * 1000.).round() as i64 == top && s.speed <= 20.001),
            "Ironing escaped top plane or speed limit"
        );
        let label = &labels[usize::from(object == 104)];
        let origin = [if object == 102 { 70. } else { 130. }, 70.];
        for s in &iron {
            let steps = ((s.b[0] - s.a[0]).hypot(s.b[1] - s.a[1]) / 0.1)
                .ceil()
                .max(1.) as usize;
            for i in 0..=steps {
                let q = std::array::from_fn(|a| {
                    s.a[a] + (s.b[a] - s.a[a]) * i as f64 / steps as f64 - origin[a] - 1.2
                });
                ensure!(
                    label.loops.iter().filter(|p| super::contains(p, q)).count() % 2 == 0,
                    "Ironing crosses letter ink"
                );
            }
        }
        ensure!(
            b.iter()
                .filter(|s| s.object == object && s.feature == "Top surface")
                .all(|s| s.speed <= 40.001),
            "Top speed limit ignored"
        );
        ensure!(
            after
                .keys()
                .all(|k| before.contains_key(k) || k.1 == "Ironing"),
            "Unexpected new role"
        );
        objects.push(json!({"object":object,"top_z_mm":top as f64/1000.,"extrusion_roles":rows,"ironing_segments":iron.len(),"ironing_e_mm":iron.iter().map(|s|s.extrusion).sum::<f64>()}));
    }
    let report = json!({"only_global_top_flow_and_speed_changed":true,"material_settings_unchanged":true,"ironing_centerlines_avoid_letter_ink_sample_mm":0.1,"native_extrusion_comparison":objects,"physical_finish_confirmed":false});
    fs::write(
        out.parent().unwrap().join("finish-audit.json"),
        serde_json::to_vec_pretty(&report)?,
    )?;
    Ok(report)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn finish_keeps_material_flow_and_baseline_text_settings() -> Result<()> {
        let config = br#"<config><object id="2"><metadata key="name" value="top flow"/><part subtype="modifier_part"><metadata key="top_surface_pattern" value="concentric"/></part></object><object id="4"><metadata key="name" value="background ironing"/><part subtype="modifier_part"><metadata key="extruder" value="3"/></part></object></config>"#;
        let mut entries = Entries::from([
            (CONFIG.into(), config.to_vec()),
            ("mesh".into(), vec![1, 2, 3]),
            (
                PROCESS.into(),
                br#"{"filament_flow_ratio":["0.95"],"wall_loops":"3"}"#.to_vec(),
            ),
        ]);
        apply(&mut entries)?;
        validate(&xml::parse(&entries[CONFIG])?)?;
        let reference = baseline(&entries)?;
        assert_eq!(reference["mesh"], vec![1, 2, 3]);
        let text = std::str::from_utf8(&reference[CONFIG])?;
        assert!(text.contains("concentric") && text.contains("extruder"));
        assert!(
            !text.contains("key=\"ironing_type\"") && !text.contains("key=\"top_surface_speed\"")
        );
        let process: Value = serde_json::from_slice(&entries[PROCESS])?;
        assert_eq!(process["filament_flow_ratio"], json!(["0.95"]));
        assert_eq!(process["wall_loops"], "3");
        Ok(())
    }
}
