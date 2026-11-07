use crate::{
    archive::{self, Entries},
    hidden,
    xml::{self, Node},
};
use anyhow::{Context, Result, ensure};
use clap::Args;
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs::{self, File},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    time::Duration,
};
use uuid::Uuid;

const MODEL: &str = "3D/3dmodel.model";
const CONFIG: &str = "Metadata/model_settings.config";
const SETTINGS: &str = "Metadata/project_settings.config";
const INFO: &str = "Metadata/slice_info.config";
const MODIFIERS: &str = "3D/Objects/local_reinforcement.model";
const CORE: &str = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02";
const PRODUCTION: &str = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06";

#[path = "print_containment.rs"]
mod containment;

const REINFORCEMENT_CLEARANCE_MM: f64 = 0.4;

#[derive(Args)]
pub struct Options {
    #[arg(long)]
    pub source: Option<PathBuf>,
    #[arg(long)]
    pub output: Option<PathBuf>,
    /// Installed Bambu Studio executable. Only local --slice/--export-3mf is invoked.
    #[arg(long)]
    pub slicer: Option<PathBuf>,
    /// Slice the same parts with only the global strength settings for comparison.
    #[arg(long)]
    pub no_reinforcement: bool,
    #[arg(long, default_value = ".build/print")]
    pub evidence: PathBuf,
}

#[derive(Deserialize)]
pub struct Spec {
    pub minimum_surface_clearance_mm: f64,
    pub global: BTreeMap<String, String>,
    pub local: BTreeMap<String, String>,
    pub zones: Vec<Zone>,
}
#[derive(Deserialize)]
pub struct Zone {
    pub part: String,
    pub name: String,
    pub center_mm: [f64; 3],
    pub radius_mm: f64,
    pub inner_radius_mm: f64,
    pub height_mm: f64,
    pub axis: String,
}

impl Spec {
    fn validate(&self) -> Result<()> {
        ensure!(
            self.minimum_surface_clearance_mm.is_finite()
                && self.minimum_surface_clearance_mm >= REINFORCEMENT_CLEARANCE_MM,
            "Reinforcement surface clearance must be at least 0.4 mm"
        );
        ensure!(
            self.local.keys().all(|key| matches!(
                key.as_str(),
                "sparse_infill_density" | "sparse_infill_pattern"
            )),
            "Local reinforcement may change infill only; wall and surface settings must stay global"
        );
        ensure!(self.zones.len() < 1000, "Invalid zone count");
        let mut names = BTreeSet::new();
        for z in &self.zones {
            ensure!(
                !z.name.is_empty() && names.insert(&z.name),
                "Empty or duplicate zone name"
            );
            ensure!(
                z.radius_mm.is_finite()
                    && z.radius_mm > 0.
                    && z.inner_radius_mm.is_finite()
                    && z.inner_radius_mm > 0.
                    && z.inner_radius_mm < z.radius_mm
                    && z.height_mm.is_finite()
                    && z.height_mm > 0.,
                "Invalid zone dimensions: {}",
                z.name
            );
            ensure!(
                z.center_mm.iter().all(|x| x.is_finite()) && ["y", "z"].contains(&z.axis.as_str()),
                "Invalid zone axis/center"
            );
        }
        ensure!(
            !self.local.contains_key("name"),
            "Local settings cannot override zone names"
        );
        Ok(())
    }
}

pub fn annular_cylinder(zone: &Zone, offset: [f64; 3]) -> (Vec<[f64; 3]>, Vec<[usize; 3]>) {
    let mut points = Vec::new();
    for radius in [zone.radius_mm, zone.inner_radius_mm] {
        for z in [-zone.height_mm / 2., zone.height_mm / 2.] {
            for i in 0..48 {
                let a = i as f64 * std::f64::consts::TAU / 48.;
                points.push([radius * a.cos(), radius * a.sin(), z]);
            }
        }
    }
    for p in &mut points {
        if zone.axis == "y" {
            *p = [p[0], -p[2], p[1]];
        }
        for a in 0..3 {
            p[a] += zone.center_mm[a] - offset[a];
        }
    }
    let mut faces = Vec::new();
    for i in 0..48 {
        let j = (i + 1) % 48;
        faces.extend([
            [i, j, 48 + j],
            [i, 48 + j, 48 + i],
            [96 + i, 144 + j, 96 + j],
            [96 + i, 144 + i, 144 + j],
            [i, 96 + j, j],
            [i, 96 + i, 96 + j],
            [48 + i, 48 + j, 144 + j],
            [48 + i, 144 + j, 144 + i],
        ]);
    }
    (points, faces)
}

pub fn build(mut entries: Entries, spec: &Spec) -> Result<Entries> {
    spec.validate()?;
    let mut model = xml::parse(archive::required(&entries, MODEL)?)?;
    // Bambu's native reader expects the core element names without prefixes.
    model.use_default_namespace(CORE)?;
    // The printer displays this title as the job name. Keep it specific to the part.
    let title = model.children.iter().position(|node| {
        node.is("metadata") && node.attrs.get("name").is_some_and(|name| name == "Title")
    });
    if let Some(index) = title {
        model.children[index].set_text("Garden auger");
    } else {
        let mut title = Node::new("metadata", &[("name", "Title")]);
        title.set_text("Garden auger");
        model.children.insert(0, title);
    }
    // New attributes use p; keep all existing qualified attributes and bindings intact.
    ensure!(
        model.attrs.get("xmlns:p").is_none_or(|ns| ns == PRODUCTION),
        "Unexpected p namespace binding"
    );
    model.attrs.insert("xmlns:p".into(), PRODUCTION.into());
    let mut config = xml::parse(archive::required(&entries, CONFIG)?)?;
    let mut normals = BTreeMap::new();
    for (index, obj) in config
        .children
        .iter_mut()
        .enumerate()
        .filter(|(_, n)| n.is("object"))
    {
        let old_ids: BTreeSet<_> = obj
            .children
            .iter()
            .filter(|n| {
                n.is("part") && n.attrs.get("subtype").is_some_and(|s| s == "modifier_part")
            })
            .map(|n| n.attr("id").map(str::to_owned))
            .collect::<Result<_>>()?;
        let id = obj.attr("id")?.to_owned();
        let resource = model
            .child_mut("resources")?
            .children
            .iter_mut()
            .find(|n| n.is("object") && n.attrs.get("id") == Some(&id))
            .context("Object resource missing")?;
        let components = resource.child_mut("components")?;
        components.children.retain(|n| {
            !n.is("component")
                || !n
                    .attrs
                    .get("objectid")
                    .is_some_and(|id| old_ids.contains(id))
        });
        obj.children.retain(|n| {
            !n.is("part") || !n.attrs.get("subtype").is_some_and(|s| s == "modifier_part")
        });
        ensure!(
            components
                .children
                .iter()
                .filter(|n| n.is("component"))
                .count()
                == 1,
            "Expected one normal component"
        );
        let normal_parts: Vec<_> = obj
            .children
            .iter_mut()
            .filter(|n| n.is("part") && n.attrs.get("subtype").is_some_and(|s| s == "normal_part"))
            .collect();
        ensure!(normal_parts.len() == 1, "Expected one normal part");
        let normal = normal_parts.into_iter().next().unwrap();
        let source = normal
            .children
            .iter_mut()
            .find(|n| n.is("metadata") && n.attrs.get("key").is_some_and(|k| k == "source_file"))
            .context("Normal part source_file missing")?;
        source
            .attrs
            .insert("value".into(), "garden-auger.limo".into());
        let metadata = normal.metadata();
        let mut offset: [f64; 3] = [0.; 3];
        for (a, key) in ["source_offset_x", "source_offset_y", "source_offset_z"]
            .iter()
            .enumerate()
        {
            offset[a] = metadata
                .get(*key)
                .context("Source offset missing")?
                .parse()?;
            ensure!(offset[a].is_finite(), "Invalid source offset");
        }
        let name = obj
            .metadata()
            .get("name")
            .context("Object name missing")?
            .clone();
        ensure!(
            normals.insert(name, (index, id, offset)).is_none(),
            "Duplicate object name"
        );
    }
    ensure!(normals.len() == 5, "Expected five printable objects");
    let normal_meshes = validate_normal_meshes(&entries, &model)?;
    let mut mod_model = Node::new("model", &[("xmlns", CORE), ("unit", "millimeter")]);
    let mut resources = Node::new("resources", &[]);
    for (i, zone) in spec.zones.iter().enumerate() {
        let number = (101 + i).to_string();
        let (index, id, offset) = normals
            .get(&zone.part)
            .with_context(|| format!("Unknown part {}", zone.part))?;
        let (points, triangles) = annular_cylinder(zone, *offset);
        let modifier = containment::Mesh {
            points,
            faces: triangles,
        };
        containment::verify(
            &modifier,
            &normal_meshes[id],
            spec.minimum_surface_clearance_mm,
        )
        .with_context(|| format!("Invalid reinforcement region: {}", zone.name))?;
        let containment::Mesh {
            points,
            faces: triangles,
        } = modifier;
        let mut record = Node::new("object", &[("id", &number), ("type", "model")]);
        let mut mesh = Node::new("mesh", &[]);
        let mut vertices = Node::new("vertices", &[]);
        let mut faces = Node::new("triangles", &[]);
        for p in points {
            vertices.children.push(Node::new(
                "vertex",
                &[
                    ("x", &format!("{:.9}", p[0])),
                    ("y", &format!("{:.9}", p[1])),
                    ("z", &format!("{:.9}", p[2])),
                ],
            ));
        }
        for f in &triangles {
            faces.children.push(Node::new(
                "triangle",
                &[
                    ("v1", &f[0].to_string()),
                    ("v2", &f[1].to_string()),
                    ("v3", &f[2].to_string()),
                ],
            ));
        }
        mesh.children.extend([vertices, faces]);
        record.children.push(mesh);
        resources.children.push(record);
        let ident = Uuid::new_v5(
            &Uuid::NAMESPACE_URL,
            format!("garden-auger/{}", zone.name).as_bytes(),
        )
        .to_string();
        let resource = model
            .child_mut("resources")?
            .children
            .iter_mut()
            .find(|n| n.is("object") && n.attrs.get("id") == Some(id))
            .unwrap();
        resource.child_mut("components")?.children.push(Node::new(
            "component",
            &[
                // A source may use prefixed core elements with no default namespace.
                ("xmlns", CORE),
                ("p:path", &format!("/{MODIFIERS}")),
                ("objectid", &number),
                ("p:UUID", &ident),
                ("transform", "1 0 0 0 1 0 0 0 1 0 0 0"),
            ],
        ));
        let mut part = Node::new("part", &[("id", &number), ("subtype", "modifier_part")]);
        part.children.push(Node::new(
            "metadata",
            &[("key", "name"), ("value", &zone.name)],
        ));
        for (key, value) in &spec.local {
            part.children
                .push(Node::new("metadata", &[("key", key), ("value", value)]));
        }
        part.children.push(Node::new(
            "mesh_stat",
            &[
                ("face_count", &triangles.len().to_string()),
                ("edges_fixed", "0"),
                ("degenerate_facets", "0"),
                ("facets_removed", "0"),
                ("facets_reversed", "0"),
                ("backwards_edges", "0"),
            ],
        ));
        config.children[*index].children.push(part);
    }
    mod_model.children.push(resources);
    entries.insert(MODIFIERS.into(), xml::encode(&mod_model));
    entries.insert(MODEL.into(), xml::encode(&model));
    entries.insert(CONFIG.into(), xml::encode(&config));
    let mut settings: Value = serde_json::from_slice(archive::required(&entries, SETTINGS)?)?;
    for (k, v) in &spec.global {
        settings[k] = json!(v);
    }
    entries.insert(SETTINGS.into(), serde_json::to_vec_pretty(&settings)?);
    Ok(entries)
}

fn validate_normal_meshes(
    entries: &Entries,
    model: &Node,
) -> Result<BTreeMap<String, containment::Mesh>> {
    let mut meshes = BTreeMap::new();
    let encoded = xml::encode(model);
    let document = roxmltree::Document::parse(std::str::from_utf8(&encoded)?)?;
    for component in document
        .descendants()
        .filter(|node| node.has_tag_name((CORE, "component")))
    {
        let path = component
            .attribute((PRODUCTION, "path"))
            .context("Component path missing")?
            .trim_start_matches('/');
        let payload = std::str::from_utf8(archive::required(entries, path)?)?;
        let mesh_document = roxmltree::Document::parse(payload)?;
        let object = mesh_document
            .descendants()
            .find(|node| {
                node.has_tag_name((CORE, "object"))
                    && node.attribute("id") == component.attribute("objectid")
            })
            .context("Normal mesh object missing")?;
        let mut vertices: Vec<[f64; 3]> = Vec::new();
        for node in object
            .descendants()
            .filter(|node| node.has_tag_name((CORE, "vertex")))
        {
            let mut point = [0.; 3];
            for (i, axis) in ["x", "y", "z"].iter().enumerate() {
                point[i] = node
                    .attribute(*axis)
                    .context("Vertex coordinate missing")?
                    .parse()?;
            }
            vertices.push(point);
        }
        ensure!(
            !vertices.is_empty() && vertices.iter().flatten().all(|v| v.is_finite()),
            "Invalid manufacturing vertices: {path}"
        );
        let mut edges: BTreeMap<(usize, usize), (usize, i32)> = BTreeMap::new();
        let mut faces = Vec::new();
        for triangle in object
            .descendants()
            .filter(|node| node.has_tag_name((CORE, "triangle")))
        {
            let mut f = [0usize; 3];
            for (i, key) in ["v1", "v2", "v3"].iter().enumerate() {
                f[i] = triangle
                    .attribute(*key)
                    .context("Triangle vertex missing")?
                    .parse()?;
            }
            ensure!(
                f.iter().all(|&i| i < vertices.len())
                    && f[0] != f[1]
                    && f[1] != f[2]
                    && f[2] != f[0],
                "Invalid manufacturing triangle: {path}"
            );
            for (a, b) in [(f[0], f[1]), (f[1], f[2]), (f[2], f[0])] {
                let edge = edges.entry((a.min(b), a.max(b))).or_default();
                edge.0 += 1;
                edge.1 += if a < b { 1 } else { -1 };
            }
            faces.push(f);
        }
        ensure!(
            !edges.is_empty()
                && edges
                    .values()
                    .all(|&(count, direction)| count == 2 && direction == 0),
            "Manufacturing mesh must be welded, closed and consistently oriented: {path}"
        );
        let id = component
            .parent()
            .and_then(|n| n.parent())
            .and_then(|n| n.attribute("id"))
            .context("Normal component parent missing")?;
        meshes.insert(
            id.to_owned(),
            containment::Mesh {
                points: vertices,
                faces,
            },
        );
    }
    Ok(meshes)
}

fn preview(name: &str) -> bool {
    name.strip_prefix("Metadata/").is_some_and(|s| {
        ["plate_", "plate_no_light_", "top_", "pick_"]
            .iter()
            .any(|p| {
                s.strip_prefix(p)
                    .is_some_and(|s| s.starts_with(|c: char| c.is_ascii_digit()))
            })
    })
}

fn relationship_target(rels: &str, target: &str) -> String {
    let base = rels.rsplit_once("/_rels/").map_or("", |(p, _)| p);
    let joined = if target.starts_with('/') {
        target.trim_start_matches('/').to_owned()
    } else {
        format!("{base}/{target}")
    };
    let mut parts = Vec::new();
    for part in joined.split('/') {
        match part {
            "" | "." => {}
            ".." => {
                parts.pop();
            }
            _ => parts.push(part),
        }
    }
    parts.join("/")
}

fn invalidate(entries: &mut Entries) -> Result<()> {
    entries.retain(|name, _| !preview(name) && !name.ends_with(".gcode"));
    let mut info = xml::parse(archive::required(entries, INFO)?)?;
    info.children.retain(|n| n.is("header"));
    entries.insert(INFO.into(), xml::encode(&info));
    let names = entries.keys().cloned().collect::<BTreeSet<_>>();
    for (name, data) in entries.iter_mut().filter(|(n, _)| n.ends_with(".rels")) {
        let mut rels = xml::parse(data)?;
        rels.children.retain(|rel| {
            !rel.is("Relationship")
                || rel.attrs.get("TargetMode").is_some_and(|s| s == "External")
                || rel
                    .attrs
                    .get("Target")
                    .is_some_and(|t| names.contains(&relationship_target(name, t)))
        });
        *data = xml::encode(&rels);
    }
    Ok(())
}

pub fn run(root: &Path, options: &Options) -> Result<()> {
    let mut spec: Spec = serde_json::from_slice(&fs::read(root.join("print/reinforcement.json"))?)?;
    if options.no_reinforcement {
        spec.zones.clear();
    }
    let source = options
        .source
        .clone()
        .unwrap_or_else(|| root.join("print/garden-auger.3mf"));
    let output = options
        .output
        .clone()
        .unwrap_or_else(|| root.join("print/garden-auger.3mf"));
    let mut entries = build(archive::read(&source)?, &spec)?;
    invalidate(&mut entries)?;
    if let Some(slicer) = &options.slicer {
        fs::create_dir_all(&options.evidence)?;
        let lane = tempfile::Builder::new()
            .prefix("slice-")
            .tempdir_in(fs::canonicalize(&options.evidence)?)?
            .keep();
        let lane = crate::native_absolute(&lane)?;
        archive::write(&lane.join("input.3mf"), &entries)?;
        let log = File::create(lane.join("native.log"))?;
        let mut child = hidden(
            Command::new(crate::native_absolute(slicer)?)
                .args(["--slice", "0", "--export-3mf", "sliced.3mf", "--outputdir"])
                .arg(&lane)
                .arg(lane.join("input.3mf"))
                .stdout(Stdio::from(log.try_clone()?))
                .stderr(Stdio::from(log)),
        )
        .spawn()
        .context("Start local Bambu Studio slice")?;
        let status = crate::wait(&mut child, Duration::from_secs(600))?;
        ensure!(
            status.success(),
            "Bambu Studio failed: {status}; see {}",
            lane.display()
        );
        let native: Value = serde_json::from_slice(&fs::read(lane.join("result.json"))?)?;
        let sliced = archive::read(&lane.join("sliced.3mf"))?;
        let summary = validate_slice(&sliced, &native, &spec)?;
        fs::write(
            lane.join("summary.json"),
            serde_json::to_vec_pretty(&summary)?,
        )?;
        for (name, data) in &sliced {
            if preview(name) && name.ends_with(".png") {
                entries.insert(name.clone(), data.clone());
            }
        }
        entries.insert(INFO.into(), archive::required(&sliced, INFO)?.to_vec());
        println!("{}", serde_json::to_string(&summary)?);
        println!("Slice evidence: {}", lane.display());
    }
    archive::write(&output, &entries)?;
    println!("{}", output.display());
    Ok(())
}

fn validate_slice(sliced: &Entries, native: &Value, spec: &Spec) -> Result<Value> {
    ensure!(
        native["return_code"] == 0,
        "Native slicing failed: {native}"
    );
    let plates = native["sliced_plates"]
        .as_array()
        .context("Missing sliced plates")?;
    ensure!(plates.len() == 2, "Expected two sliced plates");
    let mut seconds = 0.;
    let mut grams = 0.;
    for (plate, count) in plates.iter().zip([2, 3]) {
        ensure!(
            plate["objects"]
                .as_array()
                .context("Missing plate objects")?
                .len()
                == count,
            "Unexpected plate object count"
        );
        ensure!(
            empty_warning(&plate["warning_message"]),
            "Native slice warnings: {}",
            plate["warning_message"]
        );
        seconds += plate["total_predication"]
            .as_f64()
            .context("Missing time estimate")?;
        for f in plate["filaments"]
            .as_array()
            .context("Missing filament estimates")?
        {
            grams += f["total_used_g"]
                .as_f64()
                .context("Missing filament weight")?;
        }
    }
    let config = xml::parse(archive::required(sliced, CONFIG)?)?;
    let mods: Vec<_> = config
        .children
        .iter()
        .filter(|n| n.is("object"))
        .flat_map(|n| &n.children)
        .filter(|n| n.is("part") && n.attrs.get("subtype").is_some_and(|s| s == "modifier_part"))
        .collect();
    ensure!(mods.len() == spec.zones.len(), "Modifier count changed");
    let names: BTreeSet<_> = mods
        .iter()
        .map(|n| {
            n.metadata()
                .get("name")
                .cloned()
                .context("Unnamed modifier")
        })
        .collect::<Result<_>>()?;
    ensure!(
        names == spec.zones.iter().map(|z| z.name.clone()).collect(),
        "Modifier names changed"
    );
    for part in &mods {
        let settings = part.metadata();
        for (k, v) in &spec.local {
            ensure!(settings.get(k) == Some(v), "Modifier {k} changed");
        }
    }
    for (i, expected) in [(1, vec!["102", "104"]), (2, vec!["106", "108", "110"])] {
        let code = std::str::from_utf8(archive::required(
            sliced,
            &format!("Metadata/plate_{i}.gcode"),
        )?)?;
        validate_gcode(code, &expected, i == 2)?;
    }
    ensure!(
        seconds.is_finite() && seconds > 0. && grams.is_finite() && grams > 0.,
        "Invalid native estimates"
    );
    Ok(json!({"seconds":seconds,"grams":grams,"modifiers":mods.len(),"printer_command_sent":false}))
}

fn empty_warning(value: &Value) -> bool {
    match value {
        Value::String(s) => s.is_empty(),
        Value::Array(a) => a.is_empty(),
        _ => false,
    }
}

fn validate_gcode(code: &str, expected: &[&str], pla: bool) -> Result<()> {
    let mut ids: Vec<&str> = code
        .lines()
        .filter_map(|l| l.strip_prefix("; start printing object, unique label id: "))
        .map(str::trim)
        .collect();
    ids.dedup();
    ensure!(ids == expected, "Wrong object print order: {ids:?}");
    ensure!(
        code.lines()
            .any(|l| l.trim() == "; print_sequence = by object")
            && code.lines().any(|l| l.trim() == "; wall_loops = 3"),
        "Global print process changed"
    );
    ensure!(
        !code.contains("; FEATURE: Prime tower"),
        "Unexpected prime tower"
    );
    if pla {
        let wait = code
            .rfind("M190 S55")
            .context("PLA temperature wait missing")?;
        let start = code
            .find("; start printing object, unique label id: 110")
            .context("PLA object missing")?;
        ensure!(
            wait < start,
            "PLA temperature wait occurs after the object starts"
        );
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn spec() -> Spec {
        serde_json::from_slice(&fs::read(crate::root().join("print/reinforcement.json")).unwrap())
            .unwrap()
    }
    #[test]
    fn mesh_winding_and_axis_offset_are_correct() {
        let mut zone = spec().zones.remove(8);
        let (points, faces) = annular_cylinder(&zone, [1., 2., 3.]);
        assert_eq!((points.len(), faces.len()), (192, 384));
        assert_eq!(
            points[0],
            [
                zone.center_mm[0] - 1. + zone.radius_mm,
                zone.center_mm[1] - 2. + zone.height_mm / 2.,
                zone.center_mm[2] - 3.
            ]
        );
        let mut volume = 0.;
        for [i, j, k] in faces {
            let (a, b, c) = (points[i], points[j], points[k]);
            volume += (a[0] * (b[1] * c[2] - b[2] * c[1])
                + a[1] * (b[2] * c[0] - b[0] * c[2])
                + a[2] * (b[0] * c[1] - b[1] * c[0]))
                / 6.;
        }
        assert!(
            (volume
                / (std::f64::consts::PI
                    * (zone.radius_mm.powi(2) - zone.inner_radius_mm.powi(2))
                    * zone.height_mm)
                - 1.)
                .abs()
                < 0.004
        );
        zone.radius_mm = 0.;
        let mut s = spec();
        s.zones = vec![zone];
        assert!(s.validate().is_err());
    }
    #[test]
    fn protruding_regions_and_regions_crossing_holes_are_rejected() -> Result<()> {
        let source = archive::read(&crate::root().join("print/garden-auger.3mf"))?;
        let mut spec = spec();
        spec.zones.truncate(1);
        spec.zones[0].center_mm[2] = -0.5;
        assert!(build(source.clone(), &spec).is_err());
        spec.zones[0].center_mm[2] = -4.5;
        spec.zones[0].inner_radius_mm = 1.;
        assert!(build(source, &spec).is_err());
        Ok(())
    }
    #[test]
    fn reinforcement_cannot_change_walls_or_surfaces_and_baseline_has_no_modifiers() -> Result<()> {
        let mut spec = spec();
        for key in ["wall_loops", "top_shell_layers", "brim_type", "line_width"] {
            spec.local.insert(key.into(), "5".into());
            assert!(spec.validate().is_err(), "{key} must stay global");
            spec.local.remove(key);
        }
        spec.zones.clear();
        let source = archive::read(&crate::root().join("print/garden-auger.3mf"))?;
        let baseline = build(source.clone(), &spec)?;
        let config = xml::parse(&baseline[CONFIG])?;
        assert!(
            !config
                .children
                .iter()
                .flat_map(|node| &node.children)
                .any(|node| node.is("part")
                    && node
                        .attrs
                        .get("subtype")
                        .is_some_and(|value| value == "modifier_part"))
        );
        for (path, data) in source
            .iter()
            .filter(|(path, _)| path.starts_with("3D/Objects/") && path.as_str() != MODIFIERS)
        {
            assert_eq!(baseline.get(path), Some(data));
        }
        Ok(())
    }
    #[test]
    fn rebuild_preserves_normal_meshes_and_is_idempotent() -> Result<()> {
        let mut source = archive::read(&crate::root().join("print/garden-auger.3mf"))?;
        let mut model = xml::parse(&source[MODEL])?;
        model
            .children
            .iter_mut()
            .find(|node| {
                node.is("metadata") && node.attrs.get("name").is_some_and(|name| name == "Title")
            })
            .context("Missing project title")?
            .set_text("Stale export title");
        source.insert(MODEL.into(), xml::encode(&model));
        let rebuilt = build(source.clone(), &spec())?;
        for (name, data) in &source {
            if name.starts_with("3D/Objects/") && name != MODIFIERS {
                assert_eq!(Some(data), rebuilt.get(name), "{name}");
            }
        }
        assert_eq!(rebuilt, build(rebuilt.clone(), &spec())?);
        let text = std::str::from_utf8(&rebuilt[MODEL])?;
        let doc = roxmltree::Document::parse(text)?;
        assert_eq!(
            doc.descendants()
                .find(|node| node.has_tag_name((CORE, "metadata"))
                    && node.attribute("name") == Some("Title"))
                .and_then(|node| node.text()),
            Some("Garden auger")
        );
        assert_eq!(
            doc.descendants()
                .filter(|n| n.attribute((PRODUCTION, "path")) == Some(&format!("/{MODIFIERS}")))
                .count(),
            9
        );
        Ok(())
    }
    #[test]
    fn open_manufacturing_mesh_is_rejected_before_slicing() -> Result<()> {
        let mut source = archive::read(&crate::root().join("print/garden-auger.3mf"))?;
        let path = "3D/Objects/object_1.model";
        let mut model = xml::parse(&source[path])?;
        let object = model
            .child_mut("resources")?
            .children
            .iter_mut()
            .find(|node| node.is("object"))
            .context("Missing mesh object")?;
        let triangles = object.child_mut("mesh")?.child_mut("triangles")?;
        let first = triangles
            .children
            .iter()
            .position(|node| node.is("triangle"))
            .context("Missing triangle")?;
        triangles.children.remove(first);
        source.insert(path.into(), xml::encode(&model));
        assert!(build(source, &spec()).is_err());
        Ok(())
    }

    #[test]
    fn prefixed_core_and_aliased_production_sources_preserve_component_namespaces() -> Result<()> {
        fn prefix_elements(node: &mut Node) {
            if !node.name.is_empty() && !node.name.contains(':') {
                node.name = format!("c:{}", node.name);
            }
            for child in &mut node.children {
                prefix_elements(child);
            }
        }
        fn normal_references(doc: &roxmltree::Document<'_>) -> BTreeSet<(String, String, String)> {
            doc.descendants()
                .filter(|n| n.tag_name().name() == "component")
                .filter(|n| n.attribute((PRODUCTION, "path")) != Some(&format!("/{MODIFIERS}")))
                .map(|n| {
                    (
                        n.attribute("objectid").unwrap().into(),
                        n.attribute((PRODUCTION, "path")).unwrap().into(),
                        n.attribute((PRODUCTION, "UUID")).unwrap_or("").into(),
                    )
                })
                .collect()
        }
        for default in [None, Some(PRODUCTION)] {
            let mut source = archive::read(&crate::root().join("print/garden-auger.3mf"))?;
            let mut model = xml::parse(&source[MODEL])?;
            prefix_elements(&mut model);
            model.attrs.remove("xmlns");
            model.attrs.insert("xmlns:c".into(), CORE.into());
            if let Some(uri) = default {
                model.attrs.insert("xmlns".into(), uri.into());
            }
            let model = xml::encode(&model);
            let before = roxmltree::Document::parse(std::str::from_utf8(&model)?)?;
            let expected = normal_references(&before);
            assert_eq!(expected.len(), 5);
            source.insert(MODEL.into(), model);
            let rebuilt = build(source, &spec())?;
            let doc = roxmltree::Document::parse(std::str::from_utf8(&rebuilt[MODEL])?)?;
            assert_eq!(doc.root_element().lookup_namespace_uri(None), Some(CORE));
            assert!(std::str::from_utf8(&rebuilt[MODEL])?.contains("<model "));
            let modifiers: Vec<_> = doc
                .descendants()
                .filter(|n| n.attribute((PRODUCTION, "path")) == Some(&format!("/{MODIFIERS}")))
                .collect();
            assert_eq!(modifiers.len(), 9);
            assert!(
                modifiers
                    .iter()
                    .all(|n| n.tag_name().namespace() == Some(CORE))
            );
            assert_eq!(normal_references(&doc), expected);
            assert_eq!(rebuilt, build(rebuilt.clone(), &spec())?);
        }
        Ok(())
    }
    #[test]
    fn stale_statistics_gcode_previews_and_links_are_removed() -> Result<()> {
        let mut entries = archive::read(&crate::root().join("print/garden-auger.3mf"))?;
        entries.insert("Metadata/plate_1.gcode".into(), vec![]);
        invalidate(&mut entries)?;
        assert!(!entries.keys().any(|n| preview(n) || n.ends_with(".gcode")));
        assert!(
            !xml::parse(&entries[INFO])?
                .children
                .iter()
                .any(|n| n.is("plate"))
        );
        for (name, data) in entries.iter().filter(|(n, _)| n.ends_with(".rels")) {
            for rel in xml::parse(data)?
                .children
                .iter()
                .filter(|n| n.is("Relationship"))
            {
                assert!(
                    rel.attrs.get("TargetMode").is_some_and(|m| m == "External")
                        || entries.contains_key(&relationship_target(name, rel.attr("Target")?))
                );
            }
        }
        assert_eq!(
            relationship_target("3D/_rels/3dmodel.model.rels", "Objects/one.model"),
            "3D/Objects/one.model"
        );
        Ok(())
    }
    #[test]
    fn bad_order_missing_wait_and_wrong_process_fail() {
        let code = "; print_sequence = by object\n; wall_loops = 3\nM190 S55\n; start printing object, unique label id: 110\n";
        assert!(validate_gcode(code, &["110"], true).is_ok());
        assert!(validate_gcode(code, &["102"], true).is_err());
        assert!(validate_gcode(&code.replace("M190 S55", ""), &["110"], true).is_err());
        assert!(
            validate_gcode(
                &code.replace("wall_loops = 3", "wall_loops = 5"),
                &["110"],
                true
            )
            .is_err()
        );
    }

    #[test]
    fn native_warning_shapes_and_failed_slice_protect_output() -> Result<()> {
        assert!(empty_warning(&json!("")));
        assert!(empty_warning(&json!([])));
        assert!(!empty_warning(&json!("floating cantilever")));
        assert!(!empty_warning(&Value::Null));
        let lane = tempfile::tempdir()?;
        let output = lane.path().join("existing.3mf");
        fs::write(&output, b"keep this saved candidate")?;
        let options = Options {
            source: None,
            output: Some(output.clone()),
            slicer: Some(lane.path().join("missing-slicer")),
            no_reinforcement: false,
            evidence: lane.path().join("evidence"),
        };
        assert!(run(&crate::root(), &options).is_err());
        assert_eq!(fs::read(output)?, b"keep this saved candidate");
        Ok(())
    }
}
