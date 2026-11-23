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
const PITCH: f64 = 24.;
const EDGE_THICKNESS: f64 = 3.2;
const ENTRY_EDGE_THICKNESS: f64 = 2.0;
const ROOT_THICKNESS: f64 = 6.4;
const FRONT_RADIUS: f64 = 15.5;
const REAR_RADIUS: f64 = 17.;
const LEAD_IN: f64 = 14.;
const FLAT_DEPTH: f64 = 0.6;
const PILOT_HALF_THICKNESS: f64 = 1.4;
const PILOT_FACE_RADIUS: f64 = 3.4;
const PILOT_BEVEL_LENGTH: f64 = 9.;
const PILOT_BLEND_LENGTH: f64 = 17.2;
const PILOT_BEVELS: [&str; 2] = ["Upper pilot bevel", "Lower pilot bevel"];

fn flight_start(length: f64) -> f64 {
    -(length - OLD_LENGTH) - 0.9
}

fn lead_end(length: f64) -> f64 {
    flight_start(length) + LEAD_IN
}

pub fn flight_slope(length: f64) -> f64 {
    (REAR_RADIUS - FRONT_RADIUS) / (103.9 - lead_end(length))
}
pub fn flight_land(y: f64, length: f64) -> f64 {
    FRONT_RADIUS + (y - lead_end(length)) * flight_slope(length) - FLAT_DEPTH
}

fn flight_radius(y: f64, length: f64) -> f64 {
    if y < lead_end(length) {
        2.7 + (y - flight_start(length)) / LEAD_IN * (FRONT_RADIUS - 2.7)
    } else {
        flight_land(y, length) + FLAT_DEPTH
    }
}

fn flight_edge_thickness(y: f64, length: f64) -> f64 {
    let t = ((y - flight_start(length)) / LEAD_IN).clamp(0., 1.);
    ENTRY_EDGE_THICKNESS + (EDGE_THICKNESS - ENTRY_EDGE_THICKNESS) * t
}

/// Existing revolved core profile, retained so the drive's torsional section is not reduced.
fn core_radius(y: f64, length: f64) -> f64 {
    let delta = length - OLD_LENGTH;
    let stations = [
        (-delta - 1., 2.),
        (-delta + 12., 7.),
        (-delta + 90., 10.),
        (105., 12.),
    ];
    for pair in stations.windows(2) {
        let [(a, ra), (b, rb)] = [pair[0], pair[1]];
        if y <= b {
            return ra + (rb - ra) * (y - a) / (b - a);
        }
    }
    12.
}

fn print_transform(mesh: &xml::Node) -> Result<String> {
    let angle = 25_f64.to_radians();
    let (s, c) = angle.sin_cos();
    let (sn, cs) = flight_slope(240.).atan().sin_cos();
    let min = mesh
        .children
        .iter()
        .find(|n| n.is("vertices"))
        .context("Missing vertices")?
        .children
        .iter()
        .filter(|n| n.is("vertex"))
        .map(|p| Ok(sn * p.attr("y")?.parse::<f64>()? + cs * p.attr("z")?.parse::<f64>()?))
        .collect::<Result<Vec<f64>>>()?
        .into_iter()
        .fold(f64::INFINITY, f64::min);
    Ok([
        s,
        c,
        0.,
        -c * cs,
        s * cs,
        sn,
        c * sn,
        -s * sn,
        cs,
        445.45,
        181.,
        -min,
    ]
    .iter()
    .map(f64::to_string)
    .collect::<Vec<_>>()
    .join(" "))
}

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
        item.attrs
            .insert("transform".into(), print_transform(&mesh)?);
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
        // Geometry is new; an interrupted workflow must not display prior slice estimates.
        crate::print::invalidate(&mut entries)?;
        let staged = out.join(Path::new(path).file_name().unwrap());
        archive::write(&staged, &entries)?;
    }
    // All native and package checks above precede replacement of authoritative artifacts.
    fs::copy(out.join("candidate.limo"), root.join("garden-auger.limo"))?;
    fs::create_dir_all(root.join("cad"))?;
    fs::copy(
        out.join("flight-source.limo"),
        root.join("cad/auger-flight.limo"),
    )?;
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

fn section(template: &Value, id: u64, y: f64, radius: f64, theta: f64, length: f64) -> Value {
    let mut s = template.clone();
    let edge_half = std::f64::consts::PI * flight_edge_thickness(y, length) / PITCH;
    let root_half = std::f64::consts::PI * ROOT_THICKNESS / PITCH;
    let shoulder = (core_radius(y, length) + 0.6).min(radius - 0.5);
    let mut entities = vec![];
    for (i, (r, t)) in [
        (0.05, theta - root_half),
        (shoulder, theta - root_half),
        (radius, theta - edge_half),
        (radius, theta + edge_half),
        (shoulder, theta + root_half),
        (0.05, theta + root_half),
    ]
    .into_iter()
    .enumerate()
    {
        entities.push(json!([i+1,{"type":"point","position":{"x":r*t.cos(),"y":r*t.sin()}}]));
    }
    entities.extend([
        json!([7,{"type":"line","start":1,"end":2}]),
        json!([8,{"type":"line","start":2,"end":3}]),
        json!([9,{"type":"arc","center":{"x":0.,"y":0.},"radius":radius,"start_angle":theta-edge_half,"end_angle":theta+edge_half}]),
        json!([10,{"type":"line","start":4,"end":5}]),
        json!([11,{"type":"line","start":5,"end":6}]),
        json!([12,{"type":"arc","center":{"x":0.,"y":0.},"radius":0.05,"start_angle":theta-root_half,"end_angle":theta+root_half}]),
    ]);
    s["feature_id"] = json!(id);
    s["name"] = json!(format!("Flight section {id} at Y {y:.3} mm"));
    s["basis"] = json!({"origin":[0.,y,0.],"u":[1.,0.,0.],"v":[0.,0.,-1.],"normal":[0.,1.,0.]});
    s["snapshot"] = json!({"constraints":[],"dim_modes":{},"dim_params":{},"dim_placements":{},"entities":entities,"fix_targets":{},"generated_points":[],"next_constraint":0,"next_entity":12,"offset_sides":{},"params":{"next_id":0,"next_name":0,"params":[]},"reference_edges":[]});
    s["entity_id_high_water"] = json!(12);
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
        let pilot_bevel = PILOT_BEVELS
            .iter()
            .any(|name| sketch["name"] == format!("{name} profile"));
        if ![238, 280, 285].contains(&id) && !pilot_bevel {
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
                || pilot_bevel
                || (id == 238 && [1, 2, 3, 4].contains(&entity_id))
                || (id == 285 && [6, 7, 13].contains(&entity_id))
            {
                p[axis] = json!(value - move_front);
            }
        }
        sketch["profile_identities"] = json!({"next":0,"records":[]});
    }
}

fn set_pilot_blank(model: &mut Value, tip: f64) -> Result<()> {
    let sketch = model["sketches"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|s| s["feature_id"] == 280)
        .context("Missing pilot profile")?;
    // Revolve a thick backing blank. Its rear edge sits inside the existing core.
    let outline = [
        [0., tip],
        [PILOT_FACE_RADIUS, tip],
        [5.8, tip + PILOT_BEVEL_LENGTH],
        [7.1, tip + 16.],
        [6.9, tip + PILOT_BLEND_LENGTH],
        [0., tip + PILOT_BLEND_LENGTH],
    ];
    let mut entities = Vec::new();
    for (i, [x, y]) in outline.into_iter().enumerate() {
        entities.push(json!([i+1,{"type":"point","position":{"x":x,"y":y}}]));
        entities.push(
            json!([outline.len()+i+1,{"type":"line","start":i+1,"end":(i+1)%outline.len()+1}]),
        );
    }
    entities.sort_by_key(|e| e[0].as_u64());
    sketch["snapshot"]["entities"] = json!(entities);
    sketch["snapshot"]["next_entity"] = json!(outline.len() * 2);
    sketch["entity_id_high_water"] = json!(outline.len() * 2);
    sketch["profile_identities"] = json!({"next":0,"records":[]});
    let name = "Chisel pilot backing profile";
    sketch["name"] = json!(name);
    let revolve = model["revolves"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|f| f["feature_id"] == 281)
        .context("Missing pilot revolve")?;
    revolve["sketch_name"] = json!(name);
    revolve["name"] = json!("Revolve backed chisel pilot blank");
    let join = model["body_features"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|f| f["feature_id"] == 282)
        .context("Missing pilot join")?;
    join["name"] = json!("Join pilot blank to first flight");
    for feature in model["document"]["history"]["features"]
        .as_array_mut()
        .unwrap()
    {
        let name = match feature["id"].as_u64() {
            Some(280) => name,
            Some(281) => "Revolve backed chisel pilot blank",
            Some(282) => "Join pilot blank to first flight",
            _ => continue,
        };
        feature["name"] = json!(name);
    }
    Ok(())
}

pub fn run(root: &Path, options: &Options) -> Result<()> {
    ensure!(
        options.length.is_finite() && (180. ..=245.).contains(&options.length),
        "Use 180–245 mm for the 256 mm plate"
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
    let start = flight_start(options.length);
    let end = 103.9;
    let steps = ((end - start) / (PITCH / 24.)).ceil() as usize;
    let mut client = Client::start(options.executable.as_deref())?;
    let mut flight = coupons::canonical(&mut client)?;
    let mut sections = vec![];
    for i in 0..=steps {
        let y = start + (end - start) * i as f64 / steps as f64;
        let radius = flight_radius(y, options.length);
        // The existing flight turns clockwise in X/Z as Y increases.
        let theta = (-240.8 + 360. * y / PITCH).to_radians();
        let sketch = section(template, 1000 + i as u64, y, radius, theta, options.length);
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
        let name = format!(
            "Soil flight turn {} - 24 mm pitch, 6.4 mm root, 3.2 mm edge",
            chunk + 1
        );
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
        let land = |y: f64| flight_land(y, options.length);
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
    let mut editable = coupons::canonical(&mut client)?;
    editable["document"]["name"] = json!("Garden auger reinforced soil flight and print flats");
    editable["visibility"]["hidden_sketch_names"] = json!(
        editable["sketches"]
            .as_array()
            .unwrap()
            .iter()
            .map(|s| s["name"].clone())
            .collect::<Vec<_>>()
    );
    let mut appearance = source["body_appearances"]
        .as_array()
        .unwrap()
        .iter()
        .find(|a| a["body_id"] == 15)
        .context("Missing auger appearance")?
        .clone();
    appearance["body_id"] = json!(body);
    editable["body_appearances"] = json!([appearance]);
    editable["views"] = json!([{"id":"496ac57c-83a6-4b17-b5d1-a1f760910895","name":"Flight and support flats","camera":{"position":[160.,-170.,180.],"target":[0.,4.,0.],"up":[0.,0.,1.]},"print_layout":false,"visible_body_ids":[body]}]);
    flight_project.insert("model.json".into(), serde_json::to_vec(&editable)?);
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
        "Reinforced soil flight - {} mm, 24 mm pitch",
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
    let new_tip = 139.5 - options.length;
    set_pilot_blank(&mut model, new_tip)?;
    println!("Replaying complete assembly candidate");
    client.call(
        "cad_load_project_model",
        json!({"model_json":serde_json::to_string(&model)?}),
    )?;
    // The paired flats form a finite 2.8 mm land rather than a zero-thickness edge.
    // Terminate the cuts outside the blank to blend them out before the first full turn.
    for (name, sign) in PILOT_BEVELS.into_iter().zip([1., -1.]) {
        if source["document"]["history"]["features"]
            .as_array()
            .unwrap()
            .iter()
            .any(|f| f["name"] == name)
        {
            continue;
        }
        let slope = (6.1 - PILOT_HALF_THICKNESS) / PILOT_BEVEL_LENGTH;
        let points = [
            [new_tip - 1., sign * (PILOT_HALF_THICKNESS - slope)],
            [new_tip + PILOT_BEVEL_LENGTH, sign * 6.1],
            [new_tip + PILOT_BEVEL_LENGTH, sign * 25.],
            [new_tip - 1., sign * 25.],
        ];
        flat_cut(&mut client, template, name, &points, 90)?;
    }
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
    let report = json!({"previous_length_mm":current_length,"length_mm":options.length,"extension_mm":move_front,"pitch_mm":PITCH,"axial_edge_thickness_mm":EDGE_THICKNESS,"entry_edge_thickness_mm":ENTRY_EDGE_THICKNESS,"axial_root_thickness_mm":ROOT_THICKNESS,"working_flight_start_diameter_mm":FRONT_RADIUS*2.,"maximum_flight_diameter_mm":REAR_RADIUS*2.,"lead_in_length_mm":LEAD_IN,"flat_depth_mm":FLAT_DEPTH,"core_profile_unchanged":true,"bounds_mm":bounds,"loft_sections":steps+1,"candidate_only":!options.install,"printer_command_sent":false});
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
    fn manufacturing_mesh_has_backed_chisel_and_open_flight_channels() -> Result<()> {
        let entries = archive::read(&crate::root().join("print/garden-auger.3mf"))?;
        let config = xml::parse(&entries["Metadata/model_settings.config"])?;
        let object = config
            .children
            .iter()
            .find(|n| n.is("object") && n.attrs.get("id").is_some_and(|id| id == "8"))
            .context("Missing auger")?;
        let metadata = object
            .children
            .iter()
            .find(|n| n.is("part") && n.attrs.get("subtype").is_some_and(|s| s == "normal_part"))
            .context("Missing normal auger")?
            .metadata();
        let offset: [f64; 3] = ["source_offset_x", "source_offset_y", "source_offset_z"]
            .map(|key| metadata[key].parse().unwrap());
        let mut node = xml::parse(&entries["3D/Objects/object_3.model"])?;
        let node = node
            .child_mut("resources")?
            .child_mut("object")?
            .child_mut("mesh")?;
        let points = node
            .child_mut("vertices")?
            .children
            .iter()
            .filter(|n| n.is("vertex"))
            .map(|n| {
                Ok([
                    n.attr("x")?.parse::<f64>()? + offset[0],
                    n.attr("y")?.parse::<f64>()? + offset[1],
                    n.attr("z")?.parse::<f64>()? + offset[2],
                ])
            })
            .collect::<Result<_>>()?;
        let faces = node
            .child_mut("triangles")?
            .children
            .iter()
            .filter(|n| n.is("triangle"))
            .map(|n| {
                Ok([
                    n.attr("v1")?.parse()?,
                    n.attr("v2")?.parse()?,
                    n.attr("v3")?.parse()?,
                ])
            })
            .collect::<Result<_>>()?;
        let mesh = crate::print::containment::Mesh { points, faces };
        // The original cone had negligible section this close to its point.
        // Check that both bevels leave an intentional flat land and a broad backing.
        let near_tip = 139.5 - 240. + 0.1;
        for sign in [-1., 1.] {
            ensure!(
                mesh.contains([sign * 3.1, near_tip, 0.]),
                "Pilot land lacks width"
            );
            ensure!(
                mesh.contains([0., near_tip, sign * 1.3]),
                "Pilot land lacks thickness"
            );
            ensure!(
                !mesh.contains([0., near_tip, sign * 1.8]),
                "Pilot bevel missing"
            );
            ensure!(
                mesh.contains([0., near_tip + 8., sign * 5.2]),
                "Pilot bevel lacks backing"
            );
        }
        // Probe the actual fused manufacturing mesh, away from the flats. A thin
        // flight or a filled-in channel fails independently of the profile constants.
        for turn in -4..=3 {
            let y = (240.8 / 360. + f64::from(turn)) * PITCH;
            for (radius, inside, outside) in [
                (core_radius(y, 240.) + 0.3, 2.8, 4.),
                (flight_radius(y, 240.) - 0.25, 1.4, 2.4),
            ] {
                for sign in [-1., 1.] {
                    ensure!(
                        mesh.contains([radius, y + sign * inside, 0.]),
                        "Flight lacks required thickness at Y{y}, R{radius}"
                    );
                    ensure!(
                        !mesh.contains([radius, y + sign * outside, 0.]),
                        "Soil channel is blocked at Y{y}, R{radius}"
                    );
                }
            }
        }
        Ok(())
    }
    #[test]
    fn print_orientation_levels_native_lands_and_keeps_the_mesh_on_bed() -> Result<()> {
        let entries = archive::read(&crate::root().join("print/garden-auger.3mf"))?;
        let mut model = xml::parse(&entries["3D/Objects/object_3.model"])?;
        let mesh = model
            .child_mut("resources")?
            .child_mut("object")?
            .child_mut("mesh")?;
        let m: Vec<f64> = print_transform(mesh)?
            .split_whitespace()
            .map(str::parse)
            .collect::<std::result::Result<_, _>>()?;
        let mut bottom = f64::INFINITY;
        let mut top = f64::NEG_INFINITY;
        let mut heights = Vec::new();
        for p in &mesh.child_mut("vertices")?.children {
            if !p.is("vertex") {
                continue;
            }
            let y = p.attr("y")?.parse::<f64>()?;
            let z = p.attr("z")?.parse::<f64>()?;
            let height = m[5] * y + m[8] * z + m[11];
            bottom = bottom.min(height);
            top = top.max(height);
            if y + 19.5 < 104. && (z + flight_land(y + 19.5, 240.)).abs() < 0.002 {
                heights.push(height);
            }
        }
        ensure!(
            bottom.abs() < 1e-7 && heights.len() > 40,
            "Missing bed contact or flight lands"
        );
        ensure!(
            (36.8..37.).contains(&top),
            "Shield print height changed: {top}"
        );
        let lo = heights.iter().copied().fold(f64::INFINITY, f64::min);
        let hi = heights.iter().copied().fold(f64::NEG_INFINITY, f64::max);
        ensure!(
            hi - lo < 0.003 && (1.5..2.5).contains(&lo),
            "Flight lands are not level: {lo}..{hi}"
        );
        Ok(())
    }
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
            if ![238, 280, 285].contains(&id)
                && !PILOT_BEVELS
                    .iter()
                    .any(|name| sketch["name"] == format!("{name} profile"))
            {
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
