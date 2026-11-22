//! Explicit materials for finished parts and disposable supports, checked again in native paths.
use crate::{gcode, lettering, xml::Node};
use anyhow::{Context, Result, ensure};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::Path,
};

#[derive(Deserialize)]
pub struct Materials {
    variants_per_filament: usize,
    filaments: Vec<Filament>,
    parts: BTreeMap<String, Part>,
    process: BTreeMap<String, String>,
}
#[derive(Deserialize)]
struct Filament {
    material: String,
    id: String,
    preset: String,
}
#[derive(Deserialize)]
struct Part {
    filament: usize,
    label: u32,
}

impl Materials {
    pub fn load(root: &Path) -> Result<Self> {
        Ok(serde_json::from_slice(&fs::read(
            root.join("print/materials.json"),
        )?)?)
    }

    fn profiles(&self, settings: &Value) -> Result<()> {
        ensure!(
            self.filaments.len() == 5 && self.parts.len() == 5,
            "Expected five filaments and five parts"
        );
        for (key, expected) in [
            (
                "filament_type",
                self.filaments
                    .iter()
                    .map(|f| &f.material)
                    .collect::<Vec<_>>(),
            ),
            (
                "filament_ids",
                self.filaments.iter().map(|f| &f.id).collect(),
            ),
            (
                "filament_settings_id",
                self.filaments.iter().map(|f| &f.preset).collect(),
            ),
        ] {
            ensure!(
                settings[key] == json!(expected),
                "Material profile mismatch: {key}"
            );
        }
        ensure!(
            settings["filament_is_support"] == json!(["0", "0", "0", "0", "1"]),
            "Dedicated support profile flag changed"
        );
        ensure!(
            settings["filament_map"] == json!(["1", "1", "1", "1", "2"]),
            "Interface must use the auxiliary nozzle"
        );
        for (key, expected) in [
            ("extruder_nozzle_count", json!(["1", "1"])),
            ("extruder_nozzle_diameter", json!(["0.4", "0.4"])),
            ("extruder_nozzle_slot", json!(["0", "1"])),
            (
                "extruder_nozzle_volume_type",
                json!(["Standard", "Standard"]),
            ),
        ] {
            ensure!(
                settings[key] == expected,
                "Incomplete X2D nozzle metadata: {key}"
            );
        }
        for key in ["inherits_group", "different_settings_to_system"] {
            ensure!(
                settings[key]
                    .as_array()
                    .is_some_and(|v| v.len() == self.filaments.len() + 2),
                "Incomplete profile metadata: {key}"
            );
        }
        ensure!(
            self.parts.values().all(|p| (1..=4).contains(&p.filament)),
            "Invalid part filament"
        );
        let indices: Vec<_> = (1..=self.filaments.len())
            .flat_map(|slot| vec![slot.to_string(); self.variants_per_filament])
            .collect();
        ensure!(
            settings["filament_self_index"] == json!(indices),
            "Filament variant index does not cover every material"
        );
        for key in [
            "nozzle_temperature",
            "nozzle_temperature_initial_layer",
            "filament_extruder_variant",
        ] {
            ensure!(
                settings[key]
                    .as_array()
                    .is_some_and(|v| v.len() == indices.len()),
                "Incomplete filament variant values: {key}"
            );
        }
        Ok(())
    }

    /// Replace inherited object/volume overrides with the named part assignment.
    pub fn apply(&self, config: &mut Node, settings: &mut Value) -> Result<()> {
        self.profiles(settings)?;
        for object in config.children.iter_mut().filter(|n| n.is("object")) {
            let metadata = object.metadata();
            let name = metadata.get("name").context("Unnamed material object")?;
            let part = self
                .parts
                .get(name)
                .with_context(|| format!("Unknown material object: {name}"))?;
            Self::assign(object, part.filament, &self.process);
            for normal in object.children.iter_mut().filter(|n| {
                n.is("part") && n.attrs.get("subtype").is_some_and(|s| s == "normal_part")
            }) {
                Self::assign(normal, part.filament, &self.process);
            }
        }
        for (key, value) in &self.process {
            settings[key] = json!(value);
        }
        for plate in config.children.iter_mut().filter(|n| n.is("plate")) {
            for (key, value) in Self::plate_map() {
                plate
                    .children
                    .retain(|n| !n.is("metadata") || n.attrs.get("key").is_none_or(|k| k != key));
                plate
                    .children
                    .push(Node::new("metadata", &[("key", key), ("value", value)]));
            }
        }
        self.validate(config, settings)
    }

    fn plate_map() -> [(&'static str, &'static str); 3] {
        [
            ("filament_map_mode", "Manual"),
            ("filament_maps", "1 1 1 1 2"),
            ("filament_volume_maps", "0 0 0 0 0"),
        ]
    }

    fn assign(node: &mut Node, filament: usize, process: &BTreeMap<String, String>) {
        node.children.retain(|n| {
            !n.is("metadata")
                || n.attrs
                    .get("key")
                    .is_none_or(|k| k != "extruder" && !process.contains_key(k))
        });
        node.children.push(Node::new(
            "metadata",
            &[("key", "extruder"), ("value", &filament.to_string())],
        ));
    }

    pub fn validate(&self, config: &Node, settings: &Value) -> Result<()> {
        self.profiles(settings)?;
        for (key, expected) in &self.process {
            ensure!(
                settings[key].as_str() == Some(expected),
                "Material process changed: {key}"
            );
        }
        let mut found = BTreeSet::new();
        for object in config.children.iter().filter(|n| n.is("object")) {
            let metadata = object.metadata();
            let name = metadata.get("name").context("Unnamed material object")?;
            let part = self
                .parts
                .get(name)
                .with_context(|| format!("Unknown material object: {name}"))?;
            ensure!(
                found.insert(name.clone()),
                "Duplicate material object: {name}"
            );
            let normals: Vec<_> = object
                .children
                .iter()
                .filter(|n| {
                    n.is("part") && n.attrs.get("subtype").is_some_and(|s| s == "normal_part")
                })
                .collect();
            ensure!(normals.len() == 1, "Expected one normal part: {name}");
            let assigned = part.filament.to_string();
            ensure!(
                metadata.get("extruder") == Some(&assigned),
                "Wrong object material: {name}"
            );
            for node in [object, normals[0]] {
                let m = node.metadata();
                ensure!(
                    m.get("extruder").is_none_or(|slot| slot == &assigned),
                    "Wrong part material: {name}"
                );
                ensure!(
                    self.process.keys().all(|k| !m.contains_key(k)),
                    "Material override on {name}"
                );
            }
        }
        ensure!(found.len() == self.parts.len(), "Missing material objects");
        let plates: Vec<_> = config.children.iter().filter(|n| n.is("plate")).collect();
        ensure!(plates.len() == 2, "Expected two material plate maps");
        for plate in plates {
            let metadata = plate.metadata();
            for (key, value) in Self::plate_map() {
                ensure!(
                    metadata.get(key).is_some_and(|v| v == value),
                    "Plate material map changed: {key}"
                );
            }
        }
        Ok(())
    }

    pub fn validate_paths(
        &self,
        code: &str,
        expected: &[&str],
        paint: &[lettering::Region],
    ) -> Result<Value> {
        // The native template emits this wait after selecting a filament. Check the
        // commanded interface temperature too: a missing variant index can fall back
        // to another material even while the displayed profile name stays correct.
        let mut tool = None;
        let mut interface_wait = false;
        for line in code.lines().map(str::trim) {
            if let Some(v) = line.strip_prefix('T').or_else(|| line.strip_prefix(";VT")) {
                tool = v
                    .split_whitespace()
                    .next()
                    .and_then(|v| v.parse::<usize>().ok());
            }
            if tool == Some(4)
                && let Some(v) = line.strip_prefix(";VM109 S")
            {
                let temperature: f64 = v
                    .split_whitespace()
                    .next()
                    .context("Missing interface temperature")?
                    .parse()?;
                ensure!(
                    (temperature - 210.).abs() < 0.01,
                    "Wrong dedicated interface temperature: {temperature}"
                );
                interface_wait = true;
            }
        }
        let mut report: BTreeMap<String, BTreeSet<usize>> = BTreeMap::new();
        let mut printed = BTreeSet::new();
        for segment in gcode::paths(code)? {
            let (name, part) = self
                .parts
                .iter()
                .find(|(_, p)| p.label == segment.object)
                .with_context(|| format!("Unknown extrusion object: {}", segment.object))?;
            let slot = segment.filament + 1;
            let allowed = if segment.feature.starts_with("Support") {
                let interface = segment.feature.starts_with("Support interface");
                let key = if interface {
                    "support_interface_filament"
                } else {
                    "support_filament"
                };
                slot.to_string() == self.process[key] && part.label == 108
            } else {
                printed.insert(part.label.to_string());
                slot == part.filament || paint.iter().any(|p| p.part == *name && p.filament == slot)
            };
            ensure!(
                allowed,
                "Wrong extrusion material: {name}, {}, filament {slot}",
                segment.feature
            );
            report
                .entry(format!(
                    "{name}: {}",
                    if segment.feature.starts_with("Support") {
                        &segment.feature
                    } else {
                        "part"
                    }
                ))
                .or_default()
                .insert(slot);
        }
        ensure!(
            printed == expected.iter().map(|s| s.to_string()).collect(),
            "Missing part extrusion: {printed:?}"
        );
        if expected.contains(&"108") {
            ensure!(
                interface_wait,
                "Dedicated interface temperature wait missing"
            );
        }
        Ok(json!(report))
    }

    pub fn validate_info(&self, info: &Node) -> Result<()> {
        let mut found = false;
        for filament in info
            .children
            .iter()
            .filter(|n| n.is("plate"))
            .flat_map(|p| &p.children)
            .filter(|n| n.is("filament") && n.attrs.get("id").is_some_and(|id| id == "5"))
        {
            for (key, expected) in [
                ("tray_info_idx", "GFS05"),
                ("group_id", "1"),
                ("used_for_object", "false"),
                ("used_for_support", "true"),
            ] {
                ensure!(
                    filament.attrs.get(key).is_some_and(|v| v == expected),
                    "Native dedicated interface role changed: {key}"
                );
            }
            found = true;
        }
        ensure!(found, "Native dedicated interface usage missing");
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{archive, xml};
    #[test]
    fn repairs_part_overrides_and_rejects_wrong_profiles_and_native_readback() -> Result<()> {
        let policy = Materials::load(&crate::root())?;
        let entries = archive::read(&crate::root().join("print/garden-auger.3mf"))?;
        let mut config = xml::parse(&entries["Metadata/model_settings.config"])?;
        let mut settings: Value =
            serde_json::from_slice(&entries["Metadata/project_settings.config"])?;
        policy.apply(&mut config, &mut settings)?;
        let object = config.children.iter_mut().find(|n| n.is("object")).unwrap();
        object.children.push(Node::new(
            "metadata",
            &[("key", "wall_filament"), ("value", "4")],
        ));
        let normal = object.children.iter_mut().find(|n| n.is("part")).unwrap();
        normal
            .children
            .iter_mut()
            .find(|n| n.attrs.get("key").is_some_and(|k| k == "extruder"))
            .unwrap()
            .attrs
            .insert("value".into(), "4".into());
        assert!(policy.validate(&config, &settings).is_err());
        policy.apply(&mut config, &mut settings)?;
        policy.validate(&config, &settings)?;
        let mut missing_index = settings.clone();
        missing_index["filament_self_index"]
            .as_array_mut()
            .unwrap()
            .truncate(24);
        assert!(policy.validate(&config, &missing_index).is_err());
        settings["support_interface_filament"] = json!("4");
        assert!(policy.validate(&config, &settings).is_err());
        settings["filament_settings_id"][3] = json!("Bambu PLA Glow");
        assert!(policy.apply(&mut config, &mut settings).is_err());
        Ok(())
    }
    #[test]
    fn actual_extrusion_catches_pla_in_structural_parts_and_supports() -> Result<()> {
        let policy = Materials::load(&crate::root())?;
        for (label, tool) in [(102, 0), (104, 0), (106, 2), (110, 3)] {
            let code = format!(
                "M83\nT{tool}\n; start printing object, unique label id: {label}\n; FEATURE: Outer wall\nG1 X10 Y10 E1\n"
            );
            policy.validate_paths(&code, &[&label.to_string()], &[])?;
            let wrong = if tool == 3 { 1 } else { 3 };
            assert!(
                policy
                    .validate_paths(
                        &code.replace(&format!("T{tool}"), &format!("T{wrong}")),
                        &[&label.to_string()],
                        &[]
                    )
                    .is_err()
            );
        }
        let code = "M83\nT4\n;VM109 S210\n; start printing object, unique label id: 108\n; FEATURE: Support interface\nG1 X10 E1\nT1\n; FEATURE: Support\nG1 X11 E1\n; FEATURE: Outer wall\nG1 X12 E1\n";
        policy.validate_paths(code, &["108"], &[])?;
        assert!(
            policy
                .validate_paths(&code.replacen("T4", "T3", 1), &["108"], &[])
                .is_err()
        );
        assert!(policy.validate_paths("", &["108"], &[]).is_err());
        assert!(
            policy
                .validate_paths(&code.replace("S210", "S250"), &["108"], &[])
                .is_err()
        );
        assert!(
            policy
                .validate_paths(&code.replace(";VM109 S210\n", ""), &["108"], &[])
                .is_err()
        );
        Ok(())
    }

    #[test]
    fn dedicated_support_must_use_auxiliary_nozzle_and_never_be_a_part() -> Result<()> {
        let policy = Materials::load(&crate::root())?;
        let xml = r#"<config><plate><filament id="5" tray_info_idx="GFS05" group_id="1" used_for_object="false" used_for_support="true"/></plate></config>"#;
        policy.validate_info(&crate::xml::parse(xml.as_bytes())?)?;
        assert!(
            policy
                .validate_info(&crate::xml::parse(
                    xml.replace("group_id=\"1\"", "group_id=\"0\"").as_bytes()
                )?)
                .is_err()
        );
        assert!(
            policy
                .validate_info(&crate::xml::parse(
                    xml.replace("used_for_object=\"false\"", "used_for_object=\"true\"")
                        .as_bytes()
                )?)
                .is_err()
        );
        Ok(())
    }
}
