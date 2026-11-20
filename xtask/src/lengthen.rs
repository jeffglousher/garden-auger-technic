//! Native candidate generation. Mating geometry remains in the existing model.
use crate::{archive, cad::Client, coupons, xml};
use anyhow::{Context, Result, ensure};
use base64::{Engine, engine::general_purpose::STANDARD};
use clap::Args;
use serde_json::{Value, json};
use std::{
    fs,
    path::{Path, PathBuf},
};

#[derive(Args)]
pub struct Options {
    #[arg(long, default_value_t = 240.)]
    pub length: f64,
    #[arg(long)]
    pub executable: Option<PathBuf>,
    #[arg(long, default_value = ".build/long-auger")]
    pub evidence: PathBuf,
    /// Replace the model, auger STL and both print-project meshes after native validation.
    #[arg(long)]
    pub install: bool,
}

const OLD_LENGTH: f64 = 144.7;
const PITCH: f64 = 14.;
const THICKNESS: f64 = 1.2;

fn binary_stl(mesh: &xml::Node) -> Result<Vec<u8>> {
    let vertices = mesh
        .children
        .iter()
        .find(|n| n.is("vertices"))
        .context("Missing vertices")?;
    let points: Vec<[f32; 3]> = vertices
        .children
        .iter()
        .filter(|n| n.is("vertex"))
        .map(|p| {
            Ok([
                p.attr("x")?.parse()?,
                p.attr("y")?.parse()?,
                p.attr("z")?.parse()?,
            ])
        })
        .collect::<Result<_>>()?;
    let faces = mesh
        .children
        .iter()
        .find(|n| n.is("triangles"))
        .context("Missing triangles")?;
    let triangles: Vec<_> = faces.children.iter().filter(|n| n.is("triangle")).collect();
    let mut bytes = vec![0; 80];
    bytes.extend((triangles.len() as u32).to_le_bytes());
    for f in triangles {
        let a = points[f.attr("v1")?.parse::<usize>()?];
        let b = points[f.attr("v2")?.parse::<usize>()?];
        let c = points[f.attr("v3")?.parse::<usize>()?];
        let u: [f32; 3] = std::array::from_fn(|i| b[i] - a[i]);
        let v: [f32; 3] = std::array::from_fn(|i| c[i] - a[i]);
        let mut n = [
            u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0],
        ];
        let length = n.iter().map(|x| x * x).sum::<f32>().sqrt();
        if length > 0. {
            n = n.map(|x| x / length);
        }
        for value in n.into_iter().chain(a).chain(b).chain(c) {
            bytes.extend(value.to_le_bytes());
        }
        bytes.extend([0, 0]);
    }
    Ok(bytes)
}

fn install(root: &Path, out: &Path) -> Result<()> {
    let native = archive::read(&out.join("auger-native.3mf"))?;
    let mut model = xml::parse(archive::required(&native, "3D/3dmodel.model")?)?;
    let object = model
        .child_mut("resources")?
        .children
        .iter_mut()
        .find(|n| n.is("object"))
        .context("Native auger missing")?;
    let mut mesh = object.child_mut("mesh")?.clone();
    coupons::check_mesh(&mesh)?;
    // Keep the standalone artifact compact, with exactly the native 3MF triangulation.
    fs::write(out.join("auger.stl"), binary_stl(&mesh)?)?;
    let mut bounds = [[f64::INFINITY; 3], [f64::NEG_INFINITY; 3]];
    for p in mesh
        .child_mut("vertices")?
        .children
        .iter()
        .filter(|n| n.is("vertex"))
    {
        for (i, axis) in ["x", "y", "z"].iter().enumerate() {
            let v = p.attr(axis)?.parse::<f64>()?;
            bounds[0][i] = bounds[0][i].min(v);
            bounds[1][i] = bounds[1][i].max(v);
        }
    }
    let center: [f64; 3] = std::array::from_fn(|i| (bounds[0][i] + bounds[1][i]) / 2.);
    ensure!(
        (bounds[1][1] - bounds[0][1] - 240.).abs() < 0.05,
        "Production layout requires 240 mm"
    );
    for p in mesh
        .child_mut("vertices")?
        .children
        .iter_mut()
        .filter(|n| n.is("vertex"))
    {
        for (i, axis) in ["x", "y", "z"].iter().enumerate() {
            let v = p.attr(axis)?.parse::<f64>()? - center[i];
            p.attrs.insert((*axis).into(), v.to_string());
        }
    }
    let faces = mesh
        .child_mut("triangles")?
        .children
        .iter()
        .filter(|n| n.is("triangle"))
        .count();
    let backup = out.join("before");
    fs::create_dir_all(&backup)?;
    for path in [
        "garden-auger.limo",
        "print/parts/auger.stl",
        "print/garden-auger.3mf",
        "print/garden-auger-single-color.3mf",
    ] {
        let saved = backup.join(path);
        if !saved.exists() {
            fs::create_dir_all(saved.parent().unwrap())?;
            fs::copy(root.join(path), saved)?;
        }
    }
    for path in [
        "print/garden-auger.3mf",
        "print/garden-auger-single-color.3mf",
    ] {
        let mut entries = archive::read(&root.join(path))?;
        let mut part = xml::parse(archive::required(&entries, "3D/Objects/object_3.model")?)?;
        *part
            .child_mut("resources")?
            .child_mut("object")?
            .child_mut("mesh")? = mesh.clone();
        entries.insert("3D/Objects/object_3.model".into(), xml::encode(&part));
        let mut config = xml::parse(archive::required(
            &entries,
            "Metadata/model_settings.config",
        )?)?;
        let obj = config
            .children
            .iter_mut()
            .find(|n| n.is("object") && n.attrs.get("id").is_some_and(|id| id == "8"))
            .context("Auger object missing")?;
        let normal = obj
            .children
            .iter_mut()
            .find(|n| n.is("part") && n.attrs.get("id").is_some_and(|id| id == "7"))
            .context("Auger part missing")?;
        for (i, axis) in ["x", "y", "z"].iter().enumerate() {
            let key = format!("source_offset_{axis}");
            let meta = normal
                .children
                .iter_mut()
                .find(|n| n.attrs.get("key") == Some(&key))
                .context("Offset missing")?;
            meta.attrs.insert("value".into(), center[i].to_string());
        }
        if let Some(stat) = normal.children.iter_mut().find(|n| n.is("mesh_stat")) {
            stat.attrs.insert("face_count".into(), faces.to_string());
        }
        entries.insert(
            "Metadata/model_settings.config".into(),
            xml::encode(&config),
        );
        let mut model = xml::parse(archive::required(&entries, "3D/3dmodel.model")?)?;
        let item = model
            .child_mut("build")?
            .children
            .iter_mut()
            .find(|n| n.is("item") && n.attrs.get("objectid").is_some_and(|id| id == "8"))
            .context("Auger build item missing")?;
        item.attrs.insert(
            "transform".into(),
            format!(
                "0.422618262 0.906307787 0 -0.906307787 0.422618262 0 0 0 1 445.45 181 {}",
                (bounds[1][2] - bounds[0][2]) / 2.
            ),
        );
        // Plate 2 starts at X307.2 in Bambu's saved 1.2-bed-spacing coordinates.
        // A 25-degree angle clears the second nozzle's X20.5 limit and the gantry rod.
        let bushing = model
            .child_mut("build")?
            .children
            .iter_mut()
            .find(|n| n.is("item") && n.attrs.get("objectid").is_some_and(|id| id == "10"))
            .context("Bushing build item missing")?;
        bushing.attrs.insert(
            "transform".into(),
            "1 0 0 0 0 -1 0 1 0 484.194716094 41.9894338304 4.9".into(),
        );
        entries.insert("3D/3dmodel.model".into(), xml::encode(&model));
        // Rebuild removes stale previews and sliced estimates. Native slicing follows separately.
        let staged = out.join(Path::new(path).file_name().unwrap());
        archive::write(&staged, &entries)?;
    }
    // All native and package checks above precede replacement of authoritative artifacts.
    fs::copy(out.join("candidate.limo"), root.join("garden-auger.limo"))?;
    fs::copy(out.join("auger.stl"), root.join("print/parts/auger.stl"))?;
    for file in ["garden-auger.3mf", "garden-auger-single-color.3mf"] {
        fs::copy(out.join(file), root.join("print").join(file))?;
    }
    Ok(())
}

fn flat_cut(
    client: &mut Client,
    template: &Value,
    name: &str,
    points: &[[f64; 2]],
    body: u64,
) -> Result<()> {
    let mut model = coupons::canonical(client)?;
    let id = model["document"]["history"]["features"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|f| f["id"].as_u64())
        .max()
        .unwrap_or(0)
        + 1;
    let mut sketch = template.clone();
    let mut entities = vec![];
    for (i, p) in points.iter().enumerate() {
        entities.push(json!([i+1,{"type":"point","position":{"x":p[0],"y":p[1]}}]));
    }
    for i in 0..points.len() {
        entities
            .push(json!([points.len()+i+1,{"type":"line","start":i+1,"end":(i+1)%points.len()+1}]));
    }
    sketch["snapshot"] = json!({"constraints":[],"dim_modes":{},"dim_params":{},"dim_placements":{},"entities":entities,"fix_targets":{},"generated_points":[],"next_constraint":0,"next_entity":points.len()*2,"offset_sides":{},"params":{"next_id":0,"next_name":0,"params":[]},"reference_edges":[]});
    sketch["entity_id_high_water"] = json!(points.len() * 2);
    sketch["profile_identities"] = json!({"next":0,"records":[]});
    sketch["feature_id"] = json!(id);
    let profile = format!("{name} profile");
    sketch["name"] = json!(profile);
    sketch["basis"] =
        json!({"origin":[-30.,0.,0.],"u":[0.,1.,0.],"v":[0.,0.,1.],"normal":[1.,0.,0.]});
    coupons::history(&mut model, id, "sketch", &profile);
    model["sketches"].as_array_mut().unwrap().push(sketch);
    model["document"]["history"]["rollback_index"] = json!(
        model["document"]["history"]["features"]
            .as_array()
            .unwrap()
            .len()
    );
    client.call(
        "cad_load_project_model",
        json!({"model_json":serde_json::to_string(&model)?}),
    )?;
    client.call("solid_extrude",json!({"sketch_name":profile,"profile_indices":[0],"operation":"cut","extent":{"type":"distance","distance":60.},"flip":false,"taper_angle_deg":0.,"target_body_ids":[body]}))?;
    let doc = client.call("cad_document", json!({}))?;
    let feature = doc["features"].as_array().unwrap().last().unwrap()["id"]
        .as_u64()
        .unwrap();
    client.call(
        "solid_rename_feature",
        json!({"feature_id":feature,"name":name}),
    )?;
    Ok(())
}

fn section(template: &Value, id: u64, y: f64, radius: f64, theta: f64) -> Value {
    let mut s = template.clone();
    let half = std::f64::consts::PI * THICKNESS / PITCH;
    let (a, b) = (theta - half, theta + half);
    let mut entities = vec![];
    for (i, (r, t)) in [(0.05, a), (radius, a), (radius, b), (0.05, b)]
        .into_iter()
        .enumerate()
    {
        entities.push(json!([i+1,{"type":"point","position":{"x":r*t.cos(),"y":r*t.sin()}}]));
    }
    entities.extend([
        json!([5,{"type":"line","start":1,"end":2}]),
        json!([6,{"type":"arc","center":{"x":0.,"y":0.},"radius":radius,"start_angle":a,"end_angle":b}]),
        json!([7,{"type":"line","start":3,"end":4}]),
        json!([8,{"type":"arc","center":{"x":0.,"y":0.},"radius":0.05,"start_angle":a,"end_angle":b}]),
    ]);
    s["feature_id"] = json!(id);
    s["name"] = json!(format!("Flight section {id} at Y {y:.3} mm"));
    s["basis"] = json!({"origin":[0.,y,0.],"u":[1.,0.,0.],"v":[0.,0.,-1.],"normal":[0.,1.,0.]});
    s["snapshot"] = json!({"constraints":[],"dim_modes":{},"dim_params":{},"dim_placements":{},"entities":entities,"fix_targets":{},"generated_points":[],"next_constraint":0,"next_entity":8,"offset_sides":{},"params":{"next_id":0,"next_name":0,"params":[]},"reference_edges":[]});
    s["entity_id_high_water"] = json!(8);
    s["profile_identities"] = json!({"next":0,"records":[]});
    s["grid_snap"] = json!(false);
    s
}

fn translate_front(model: &mut Value, move_front: f64) {
    if move_front.abs() < 1e-9 {
        return;
    }
    for sketch in model["sketches"].as_array_mut().unwrap() {
        let id = sketch["feature_id"].as_u64().unwrap();
        if ![238, 280, 285].contains(&id) {
            continue;
        }
        for entity in sketch["snapshot"]["entities"].as_array_mut().unwrap() {
            if entity[1]["type"] != "point" {
                continue;
            }
            let entity_id = entity[0].as_u64().unwrap();
            let p = &mut entity[1]["position"];
            let axis = if id == 280 { "y" } else { "x" };
            let value = p[axis].as_f64().unwrap();
            if id == 280
                || (id == 238 && [1, 2, 3, 4].contains(&entity_id))
                || (id == 285 && [6, 7, 13].contains(&entity_id))
            {
                p[axis] = json!(value - move_front);
            }
        }
        sketch["profile_identities"] = json!({"next":0,"records":[]});
    }
}

pub fn run(root: &Path, options: &Options) -> Result<()> {
    ensure!(
        options.length.is_finite() && (180. ..=245.).contains(&options.length),
        "Use 180–245 mm for the straight 256 mm plate layout"
    );
    fs::create_dir_all(&options.evidence)?;
    let out = crate::native_absolute(&options.evidence)?;
    let original = archive::read(&root.join("garden-auger.limo"))?;
    let source: Value = serde_json::from_slice(&original["model.json"])?;
    let template = source["sketches"]
        .as_array()
        .unwrap()
        .iter()
        .find(|s| s["feature_id"] == 238)
        .context("Missing auger profile")?;
    let delta = options.length - OLD_LENGTH;
    let tip = source["sketches"]
        .as_array()
        .unwrap()
        .iter()
        .find(|s| s["feature_id"] == 280)
        .context("Missing tip profile")?["snapshot"]["entities"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|e| e[1]["position"]["y"].as_f64())
        .fold(f64::INFINITY, f64::min);
    let current_length = 139.5 - tip;
    let move_front = options.length - current_length;
    let start = -delta - 0.9;
    let end = 103.9;
    let steps = ((end - start) / (PITCH / 24.)).ceil() as usize;
    let mut client = Client::start(options.executable.as_deref())?;
    let mut flight = coupons::canonical(&mut client)?;
    let mut sections = vec![];
    for i in 0..=steps {
        let y = start + (end - start) * i as f64 / steps as f64;
        let radius = if y < -delta + 1. {
            2.7 + (y - start) / 1.9 * 7.3
        } else {
            10. + (y + delta - 1.) / (end + delta - 1.) * 5.5
        };
        // The existing flight turns clockwise in X/Z as Y increases.
        let theta = (-240.8 + 360. * y / PITCH).to_radians();
        let sketch = section(template, 1000 + i as u64, y, radius, theta);
        let name = sketch["name"].as_str().unwrap().to_owned();
        coupons::history(&mut flight, 1000 + i as u64, "sketch", &name);
        flight["sketches"].as_array_mut().unwrap().push(sketch);
        sections.push(json!({"sketch_name":name,"profile_index":0}));
    }
    let mut bodies = vec![];
    for (chunk, start_index) in (0..steps).step_by(24).enumerate() {
        let stop = (start_index + 24).min(steps);
        let id = 2000 + chunk as u64;
        let body = chunk as u64 + 1;
        let name = format!("Helical flight turn {} - 14 mm pitch", chunk + 1);
        flight["lofts"].as_array_mut().unwrap().push(json!({"feature_id":id,"name":name,"sections":sections[start_index..=stop],"ruled":false,"continuity":"g1","operation":"new_body","target_body_ids":[],"new_body_id":body,"guide_rail":null,"centerline":null}));
        coupons::history(&mut flight, id, "loft", &name);
        bodies.push(body);
    }
    coupons::history(
        &mut flight,
        2100,
        "combine",
        "Join continuous helical turns",
    );
    flight["body_features"].as_array_mut().unwrap().push(json!({"type":"combine","feature_id":2100,"name":"Join continuous helical turns","target_body_id":1,"tool_body_ids":bodies[1..],"operation":"join","keep_tools":false}));
    flight["document"]["history"]["rollback_index"] = json!(
        flight["document"]["history"]["features"]
            .as_array()
            .unwrap()
            .len()
    );
    println!("Building native flight from {} sections", sections.len());
    client.call(
        "cad_load_project_model",
        json!({"model_json":serde_json::to_string(&flight)?}),
    )?;
    for sign in [-1., 1.] {
        let y0 = start - 1.;
        let y1 = end + 1.;
        let land = |y: f64| 10. + (y + delta - 1.) / (end + delta - 1.) * 5.5 - 0.6;
        let polygon = [
            [y0, sign * land(y0)],
            [y1, sign * land(y1)],
            [y1, sign * 30.],
            [y0, sign * 30.],
        ];
        flat_cut(
            &mut client,
            template,
            if sign > 0. {
                "Upper flight support flat - 0.6 mm"
            } else {
                "Lower flight support flat - 0.6 mm"
            },
            &polygon,
            1,
        )?;
    }
    let scene = client.scene()?;
    ensure!(
        scene.bodies.len() == 1,
        "Flight loft did not create one body"
    );
    let body = scene.bodies[0].id;
    let mut flight_project = original.clone();
    flight_project.insert(
        "model.json".into(),
        serde_json::to_vec(&coupons::canonical(&mut client)?)?,
    );
    archive::write(&out.join("flight-source.limo"), &flight_project)?;
    let exported = client.call("solid_export_step", json!({"body_ids":[body]}))?;
    let encoded = exported
        .get("bytes_base64")
        .or_else(|| exported.get("data_base64"))
        .or_else(|| exported.get("step_base64"))
        .and_then(Value::as_str)
        .with_context(|| {
            format!(
                "STEP output keys: {:?}",
                exported.as_object().map(|o| o.keys().collect::<Vec<_>>())
            )
        })?;
    fs::write(out.join("flight.step"), STANDARD.decode(encoded)?)?;
    let mut model = source.clone();
    let import = model["body_features"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|f| f["feature_id"] == 102)
        .context("Flight import missing")?;
    import["data_base64"] = json!(encoded);
    import["file_name"] = json!(format!("auger-flight-{}mm.step", options.length));
    let import_name = json!(format!(
        "Extended auger flight - {} mm assembly",
        options.length
    ));
    import["name"] = import_name.clone();
    for f in model["document"]["history"]["features"]
        .as_array_mut()
        .unwrap()
    {
        if f["id"] == 102 {
            f["name"] = import_name.clone();
        }
    }
    translate_front(&mut model, move_front);
    println!("Replaying complete assembly candidate");
    client.call(
        "cad_load_project_model",
        json!({"model_json":serde_json::to_string(&model)?}),
    )?;
    let shield_flats_present = source["document"]["history"]["features"]
        .as_array()
        .unwrap()
        .iter()
        .any(|f| {
            f["name"]
                .as_str()
                .is_some_and(|n| n == "Upper shield print flat - 0.6 mm")
        });
    for sign in if shield_flats_present {
        vec![]
    } else {
        vec![-1., 1.]
    } {
        let polygon = [
            [102., sign * 18.4],
            [107., sign * 18.4],
            [107., sign * 25.],
            [102., sign * 25.],
        ];
        flat_cut(
            &mut client,
            template,
            if sign > 0. {
                "Upper shield print flat - 0.6 mm"
            } else {
                "Lower shield print flat - 0.6 mm"
            },
            &polygon,
            15,
        )?;
    }
    let changed = client.scene()?;
    fs::write(out.join("scene.json"), serde_json::to_vec(&changed)?)?;
    let mut candidate = original;
    candidate.insert(
        "model.json".into(),
        serde_json::to_vec(&coupons::canonical(&mut client)?)?,
    );
    archive::write(&out.join("candidate.limo"), &candidate)?;
    let check = client.call(
        "assembly_interference_check",
        json!({"occurrence_ids":[3,6,7,8,14,16],"clearance_threshold_mm":2}),
    )?;
    fs::write(
        out.join("interference.json"),
        serde_json::to_vec_pretty(&check)?,
    )?;
    ensure!(
        check["pairs"]
            .as_array()
            .is_some_and(|p| p.iter().all(|p| p["interfering"] == false)),
        "Candidate has assembly interference"
    );
    println!("Fusing auger only for manufacturing export");
    client.call(
        "solid_combine",
        json!({"target_body_id":15,"tool_body_ids":[90],"operation":"join","keep_tools":false}),
    )?;
    let fused = client.scene()?;
    let b = fused
        .bodies
        .iter()
        .find(|b| b.id == 15)
        .context("Fused auger missing")?;
    let bounds = b.mesh.bounds();
    ensure!(
        (bounds[1][1] - bounds[0][1] - options.length).abs() < 0.05,
        "Unexpected auger length: {bounds:?}"
    );
    for (tool, name) in [
        ("solid_export_stl", "auger.stl"),
        ("solid_export_3mf", "auger-native.3mf"),
    ] {
        let data=client.call(tool,json!({"body_ids":[15],"scope":"definition","linear_deflection":0.05,"angular_deflection":0.25}))?;
        let encoded = data["bytes_base64"]
            .as_str()
            .context("Missing export bytes")?;
        fs::write(out.join(name), STANDARD.decode(encoded)?)?;
    }
    let report = json!({"previous_length_mm":current_length,"length_mm":options.length,"extension_mm":move_front,"pitch_mm":PITCH,"axial_blade_thickness_mm":THICKNESS,"bounds_mm":bounds,"loft_sections":steps+1,"candidate_only":!options.install,"printer_command_sent":false});
    fs::write(
        out.join("candidate-summary.json"),
        serde_json::to_vec_pretty(&report)?,
    )?;
    println!("{}", serde_json::to_string(&report)?);
    if options.install {
        install(root, &out)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn extension_preserves_rear_interfaces_and_other_parts() -> Result<()> {
        let entries = archive::read(&crate::root().join("garden-auger.limo"))?;
        let mut model: Value = serde_json::from_slice(&entries["model.json"])?;
        let before = model.clone();
        translate_front(&mut model, 95.3);
        for key in ["extrudes", "revolves", "body_features", "assembly"] {
            assert_eq!(model[key], before[key], "{key}");
        }
        for sketch in model["sketches"].as_array().unwrap() {
            let id = sketch["feature_id"].as_u64().unwrap();
            let old = before["sketches"]
                .as_array()
                .unwrap()
                .iter()
                .find(|s| s["feature_id"] == id)
                .unwrap();
            if ![238, 280, 285].contains(&id) {
                assert_eq!(sketch, old);
            }
            if id == 238 {
                for e in sketch["snapshot"]["entities"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .filter(|e| e[0].as_u64().unwrap() > 4)
                {
                    assert_eq!(
                        Some(e),
                        old["snapshot"]["entities"]
                            .as_array()
                            .unwrap()
                            .iter()
                            .find(|o| o[0] == e[0])
                    );
                }
            }
        }
        let mut repeated = before.clone();
        translate_front(&mut repeated, 0.);
        assert_eq!(repeated["sketches"], before["sketches"]);
        Ok(())
    }
    #[test]
    fn binary_stl_has_exact_native_facets() -> Result<()> {
        let mesh = coupons::mesh_node(&[[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]], &[[0, 1, 2]]);
        let data = binary_stl(&mesh)?;
        assert_eq!(data.len(), 134);
        assert_eq!(u32::from_le_bytes(data[80..84].try_into().unwrap()), 1);
        assert_eq!(f32::from_le_bytes(data[92..96].try_into().unwrap()), 1.);
        Ok(())
    }
}
