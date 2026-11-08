use crate::{
    archive::{self, Entries},
    cad::Client,
    lettering,
    xml::{self, Node},
};
use anyhow::{Context, Result, ensure};
use base64::{Engine, engine::general_purpose::STANDARD};
use clap::Args;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs::{self, File},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    time::Duration,
};
use uuid::Uuid;

const CORE: &str = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02";
const PROD: &str = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06";
const REL: &str = "http://schemas.openxmlformats.org/package/2006/relationships";
const REL_MODEL: &str = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel";
const BASE: f64 = 3.8;
const TEXT_HEIGHT: f64 = 2.72;

#[derive(Args)]
pub struct Options {
    #[arg(long)]
    pub slicer: Option<PathBuf>,
    #[arg(long)]
    pub executable: Option<PathBuf>,
    #[arg(long)]
    pub output: Option<PathBuf>,
    #[arg(long, default_value = ".build/coupon-review")]
    pub evidence: PathBuf,
}

struct Coupon {
    name: String,
    body: u64,
    origin: [f64; 2],
    size: [f64; 2],
}

fn canonical(client: &mut Client) -> Result<Value> {
    let v = client.call("cad_project_model", json!({}))?;
    if v.get("format").is_some() {
        Ok(v)
    } else {
        Ok(serde_json::from_str(
            v.as_str()
                .or_else(|| v["model_json"].as_str())
                .context("Missing model JSON")?,
        )?)
    }
}

fn outline(origin: [f64; 2], size: [f64; 2], notches: usize) -> Vec<[f64; 2]> {
    let mut p = vec![[0., 0.]];
    for i in 0..notches {
        let x = 2. + 3. * i as f64;
        p.extend([[x, 0.], [x, 1.2], [x + 1.2, 1.2], [x + 1.2, 0.]]);
    }
    p.extend([[size[0], 0.], [size[0], size[1]], [0., size[1]]]);
    p.into_iter()
        .map(|p| [p[0] + origin[0], p[1] + origin[1]])
        .collect()
}

fn base(
    client: &mut Client,
    name: &str,
    origin: [f64; 2],
    size: [f64; 2],
    height: f64,
    notches: usize,
) -> Result<Coupon> {
    let old: BTreeSet<_> = client.scene()?.bodies.iter().map(|b| b.id).collect();
    let sketch = format!("{name} flat base profile");
    client.call(
        "sketch_begin",
        json!({"name":sketch,"plane":{"type":"origin_plane","plane":"xy"}}),
    )?;
    client.call("sketch_set_grid_snap", json!({"enabled":false}))?;
    let points = outline(origin, size, notches);
    for (a, b) in points
        .iter()
        .zip(points.iter().cycle().skip(1))
        .take(points.len())
    {
        client.call(
            "sketch_add_line",
            json!({"from":{"x":a[0],"y":a[1]},"to_raw":{"x":b[0],"y":b[1]},"ctrl_held":true}),
        )?;
    }
    client.call("sketch_finish", json!({}))?;
    client.call("solid_extrude",json!({"sketch_name":sketch,"profile_indices":[0],"operation":"new_body","extent":{"type":"distance","distance":height},"flip":false,"taper_angle_deg":0,"target_body_ids":[]}))?;
    let doc = client.call("cad_document", json!({}))?;
    let id = doc["features"]
        .as_array()
        .context("Missing history")?
        .last()
        .context("Empty history")?["id"]
        .as_u64()
        .context("Missing feature ID")?;
    client.call(
        "solid_rename_feature",
        json!({"feature_id":id,"name":format!("{name} base - {height} mm")}),
    )?;
    let scene = client.scene()?;
    let bodies: Vec<_> = scene
        .bodies
        .iter()
        .filter(|b| !old.contains(&b.id))
        .collect();
    ensure!(bodies.len() == 1, "Base did not create exactly one body");
    client.call("set_body_appearance",json!({"body_id":bodies[0].id,"filament_type":"PETG","material_name":"PETG","color_name":"Coupon orange","color":{"r":255,"g":103,"b":31,"a":255}}))?;
    Ok(Coupon {
        name: name.into(),
        body: bodies[0].id,
        origin,
        size,
    })
}

fn map_sketch(sketch: &mut Value, map: impl Fn(f64, f64) -> [f64; 2]) {
    for e in sketch["snapshot"]["entities"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .filter(|e| e[1]["type"] == "point")
    {
        let p = &mut e[1]["position"];
        let q = map(p["x"].as_f64().unwrap(), p["y"].as_f64().unwrap());
        p["x"] = json!(q[0]);
        p["y"] = json!(q[1]);
    }
    for r in sketch["profile_identities"]["records"]
        .as_array_mut()
        .unwrap()
    {
        for p in r["shape"].as_array_mut().unwrap() {
            let q = map(
                p[0].as_i64().unwrap() as f64 / 1e6,
                p[1].as_i64().unwrap() as f64 / 1e6,
            );
            *p = json!([(q[0] * 1e6).round() as i64, (q[1] * 1e6).round() as i64]);
        }
    }
}

fn history(model: &mut Value, id: u64, kind: &str, name: &str) {
    model["document"]["history"]["features"]
        .as_array_mut()
        .unwrap()
        .push(json!({"id":id,"kind":kind,"name":name,"suppressed":false,"status":{"state":"ok"}}));
}

fn add_locators(model: &mut Value, source: &Value, coupons: &[Coupon]) -> Result<()> {
    for (i, c) in coupons.iter().take(4).enumerate() {
        let socket = i == 3;
        let source_id = if socket { 373 } else { 371 };
        let id = 1001 + i as u64 * 2;
        let mut sketch = source["sketches"]
            .as_array()
            .unwrap()
            .iter()
            .find(|s| s["feature_id"] == source_id)
            .unwrap()
            .clone();
        let mut revolve = source["revolves"]
            .as_array()
            .unwrap()
            .iter()
            .find(|r| r["feature_id"] == source_id + 1)
            .unwrap()
            .clone();
        let axis = revolve["axis_origin"]["x"].as_f64().unwrap();
        let x = c.origin[0] + 9.;
        let diameter = if socket { 5.0 } else { [4.9, 4.8, 4.7][i] };
        map_sketch(&mut sketch, |px, z| {
            let radius = px - axis;
            [
                x + radius
                    + if !socket && radius > 0.1 {
                        (diameter - 4.8) / 2.
                    } else {
                        0.
                    },
                if socket { BASE - z } else { BASE + z },
            ]
        });
        let name = format!("{} locating profile", c.name);
        sketch["feature_id"] = json!(id);
        sketch["name"] = json!(name);
        sketch["basis"]["origin"] = json!([0., c.origin[1] + 7., 0.]);
        // These are new coupon sketches. Let native profile discovery assign their
        // identities, including the reversed socket loop after print orientation.
        sketch["profile_identities"] = json!({"next":0,"records":[]});
        history(model, id, "sketch", &name);
        model["sketches"].as_array_mut().unwrap().push(sketch);
        let name = format!(
            "{} - copied housing {}",
            c.name,
            if socket {
                "5 mm bore and entry"
            } else {
                "pin and lead chamfer"
            }
        );
        revolve["feature_id"] = json!(id + 1);
        revolve["name"] = json!(name);
        revolve["sketch_name"] = json!(format!("{} locating profile", c.name));
        revolve["axis_origin"]["x"] = json!(x);
        revolve["target_body_ids"] = json!([c.body]);
        revolve["new_body_ids"] = json!([700 + i]);
        history(model, id + 1, "revolve", &name);
        model["revolves"].as_array_mut().unwrap().push(revolve);
    }
    Ok(())
}

fn mesh_node(points: &[[f64; 3]], faces: &[[usize; 3]]) -> Node {
    let mut mesh = Node::new("mesh", &[]);
    let mut vertices = Node::new("vertices", &[]);
    let mut triangles = Node::new("triangles", &[]);
    for p in points {
        vertices.children.push(Node::new(
            "vertex",
            &[
                ("x", &p[0].to_string()),
                ("y", &p[1].to_string()),
                ("z", &p[2].to_string()),
            ],
        ));
    }
    for f in faces {
        triangles.children.push(Node::new(
            "triangle",
            &[
                ("v1", &f[0].to_string()),
                ("v2", &f[1].to_string()),
                ("v3", &f[2].to_string()),
            ],
        ));
    }
    mesh.children.extend([vertices, triangles]);
    mesh
}

fn check_mesh(mesh: &Node) -> Result<()> {
    let vertices = mesh
        .children
        .iter()
        .find(|n| n.is("vertices"))
        .context("No vertices")?
        .children
        .iter()
        .filter(|n| n.is("vertex"))
        .count();
    let triangles = mesh
        .children
        .iter()
        .find(|n| n.is("triangles"))
        .context("No triangles")?;
    let mut edges = BTreeMap::<(usize, usize), (usize, i32)>::new();
    for t in triangles.children.iter().filter(|n| n.is("triangle")) {
        let f = [
            t.attr("v1")?.parse::<usize>()?,
            t.attr("v2")?.parse::<usize>()?,
            t.attr("v3")?.parse::<usize>()?,
        ];
        ensure!(f.iter().all(|&i| i < vertices), "Invalid vertex index");
        for (a, b) in [(f[0], f[1]), (f[1], f[2]), (f[2], f[0])] {
            let e = edges.entry((a.min(b), a.max(b))).or_default();
            e.0 += 1;
            e.1 += if a < b { 1 } else { -1 };
        }
    }
    ensure!(
        !edges.is_empty() && edges.values().all(|&(n, w)| n == 2 && w == 0),
        "Coupon mesh is not a closed oriented manifold"
    );
    Ok(())
}

fn metadata(node: &mut Node, key: &str, value: &str) {
    node.children
        .push(Node::new("metadata", &[("key", key), ("value", value)]));
}
fn identity() -> &'static str {
    "1 0 0 0 1 0 0 0 1 0 0 0"
}

fn model_file(id: &str, mesh: Node) -> Vec<u8> {
    let mut model = Node::new("model", &[("xmlns", CORE), ("unit", "millimeter")]);
    let mut resources = Node::new("resources", &[]);
    let mut object = Node::new("object", &[("id", id), ("type", "model")]);
    object.children.push(mesh);
    resources.children.push(object);
    model.children.push(resources);
    xml::encode(&model)
}

fn component(id: &str, path: &str) -> Node {
    let uuid = Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!("garden-auger-coupon/{id}").as_bytes(),
    )
    .to_string();
    Node::new(
        "component",
        &[
            ("objectid", id),
            ("p:path", &format!("/{path}")),
            ("p:UUID", &uuid),
            ("transform", identity()),
        ],
    )
}

fn package(
    root: &Path,
    client: &mut Client,
    coupons: &[Coupon],
    letter: &lettering::Region,
    out: &Path,
) -> Result<Entries> {
    let source = archive::read(&root.join("print/garden-auger.3mf"))?;
    let mut entries = Entries::new();
    entries.insert(
        "[Content_Types].xml".into(),
        source["[Content_Types].xml"].clone(),
    );
    entries.insert("_rels/.rels".into(), source["_rels/.rels"].clone());
    let mut settings: Value = serde_json::from_slice(&source["Metadata/project_settings.config"])?;
    settings["print_sequence"] = json!("by layer");
    settings["enable_prime_tower"] = json!("0");
    settings["printing_by_object_gcode"] = json!("");
    settings["print_settings_id"] = json!("Garden auger coupons - matching housing process");
    for key in ["filament_colour", "filament_multi_colour"] {
        settings[key][0] = json!("#FF671F");
        settings[key][2] = json!("#000080");
    }
    entries.insert(
        "Metadata/project_settings.config".into(),
        serde_json::to_vec_pretty(&settings)?,
    );
    let mut model = Node::new(
        "model",
        &[
            ("xmlns", CORE),
            ("xmlns:p", PROD),
            ("unit", "millimeter"),
            ("requiredextensions", "p"),
        ],
    );
    let mut title = Node::new("metadata", &[("name", "Title")]);
    title.set_text("Garden auger fit and lettering coupons");
    model.children.push(title);
    for (name, value) in [
        ("Application", "BambuStudio-02.08.02.61"),
        ("BambuStudio:3mfVersion", "1"),
    ] {
        let mut meta = Node::new("metadata", &[("name", name)]);
        meta.set_text(value);
        model.children.push(meta);
    }
    let mut resources = Node::new("resources", &[]);
    let mut build = Node::new("build", &[]);
    let mut config = Node::new("config", &[]);
    let mut rels = Node::new("Relationships", &[("xmlns", REL)]);
    let mut plate = Node::new("plate", &[]);
    for (k, v) in [
        ("plater_id", "1"),
        ("plater_name", "Locator fit and flush lettering coupons"),
        ("locked", "false"),
        ("print_sequence", "by layer"),
        ("filament_map_mode", "Auto For Match"),
        ("filament_maps", "1 1 1 1"),
        ("filament_volume_maps", "0 0 0 0"),
    ] {
        metadata(&mut plate, k, v);
    }
    for (i, c) in coupons.iter().enumerate() {
        let normal = (i * 2 + 1).to_string();
        let id = (i * 2 + 2).to_string();
        let path = format!("3D/Objects/coupon_{}.model", i + 1);
        let result=client.call("solid_export_3mf",json!({"body_ids":[c.body],"scope":"definition","linear_deflection":0.05,"angular_deflection":0.25}))?;
        let bytes = STANDARD.decode(
            result["bytes_base64"]
                .as_str()
                .context("No native mesh data")?,
        )?;
        let native_path = out.join(format!("native-{}.3mf", i + 1));
        fs::write(&native_path, bytes)?;
        let native = archive::read(&native_path)?;
        let payload = native
            .iter()
            .find(|(n, _)| n.ends_with(".model"))
            .context("No exported model")?;
        let native = xml::parse(payload.1)?;
        let mut mesh = native
            .children
            .iter()
            .find(|n| n.is("resources"))
            .and_then(|r| {
                r.children
                    .iter()
                    .find_map(|o| o.children.iter().find(|m| m.is("mesh")))
            })
            .context("No native mesh")?
            .clone();
        check_mesh(&mesh)?;
        for v in mesh
            .child_mut("vertices")?
            .children
            .iter_mut()
            .filter(|n| n.is("vertex"))
        {
            for (a, key) in ["x", "y"].into_iter().enumerate() {
                let x = v.attr(key)?.parse::<f64>()? - c.origin[a];
                v.attrs.insert(key.into(), format!("{x:.9}"));
            }
        }
        entries.insert(path.clone(), model_file(&normal, mesh));
        rels.children.push(Node::new(
            "Relationship",
            &[
                ("Id", &format!("part{}", i + 1)),
                ("Target", &format!("/{path}")),
                ("Type", REL_MODEL),
            ],
        ));
        let mut resource = Node::new("object", &[("id", &id), ("type", "model")]);
        let mut components = Node::new("components", &[]);
        components.children.push(component(&normal, &path));
        let mut obj = Node::new("object", &[("id", &id)]);
        metadata(&mut obj, "name", &c.name);
        metadata(&mut obj, "extruder", "1");
        let mut part = Node::new("part", &[("id", &normal), ("subtype", "normal_part")]);
        metadata(&mut part, "name", &c.name);
        metadata(&mut part, "matrix", "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1");
        metadata(
            &mut part,
            "source_file",
            "experiments/garden-auger-coupons.limo",
        );
        obj.children.push(part);
        if i >= 4 {
            let ink = (201 + i).to_string();
            let ink_path = format!("3D/Objects/lettering_{}.model", i - 3);
            let lo: [f64; 2] = std::array::from_fn(|a| {
                letter
                    .points
                    .iter()
                    .map(|p| p[a])
                    .fold(f64::INFINITY, f64::min)
            });
            let points: Vec<_> = letter
                .points
                .iter()
                .map(|p| {
                    [
                        p[0] - lo[0] + 1.2,
                        p[1] - lo[1] + 1.2,
                        p[2] - letter.surface + TEXT_HEIGHT,
                    ]
                })
                .collect();
            let mesh = mesh_node(&points, &letter.faces);
            check_mesh(&mesh)?;
            entries.insert(ink_path.clone(), model_file(&ink, mesh));
            rels.children.push(Node::new(
                "Relationship",
                &[
                    ("Id", &format!("ink{i}")),
                    ("Target", &format!("/{ink_path}")),
                    ("Type", REL_MODEL),
                ],
            ));
            components.children.push(component(&ink, &ink_path));
            let mut part = Node::new("part", &[("id", &ink), ("subtype", "modifier_part")]);
            metadata(
                &mut part,
                "name",
                if i == 4 {
                    "Same-color flush lettering"
                } else {
                    "Contrasting-color flush lettering"
                },
            );
            metadata(&mut part, "extruder", if i == 4 { "1" } else { "3" });
            obj.children.push(part);
        }
        resource.children.push(components);
        resources.children.push(resource);
        config.children.push(obj);
        build.children.push(Node::new(
            "item",
            &[
                ("objectid", &id),
                (
                    "transform",
                    &format!("1 0 0 0 1 0 0 0 1 {} {} 0", c.origin[0], c.origin[1]),
                ),
                ("printable", "1"),
            ],
        ));
        let mut instance = Node::new("model_instance", &[]);
        metadata(&mut instance, "object_id", &id);
        metadata(&mut instance, "instance_id", "0");
        metadata(&mut instance, "identify_id", &(102 + i * 2).to_string());
        plate.children.push(instance);
    }
    config.children.push(plate);
    model.children.extend([resources, build]);
    entries.insert("3D/3dmodel.model".into(), xml::encode(&model));
    entries.insert(
        "Metadata/model_settings.config".into(),
        xml::encode(&config),
    );
    entries.insert("3D/_rels/3dmodel.model.rels".into(), xml::encode(&rels));
    Ok(entries)
}

pub fn run(root: &Path, options: &Options) -> Result<()> {
    fs::create_dir_all(&options.evidence)?;
    let out = crate::native_absolute(&options.evidence)?;
    let production = archive::read(&root.join("garden-auger.limo"))?;
    let source: Value = serde_json::from_slice(&production["model.json"])?;
    let letter = lettering::load(root)?
        .into_iter()
        .find(|r| r.body_id == 46)
        .context("Lower label missing")?;
    let size: [f64; 2] = std::array::from_fn(|a| {
        letter
            .points
            .iter()
            .map(|p| p[a])
            .fold(f64::NEG_INFINITY, f64::max)
            - letter
                .points
                .iter()
                .map(|p| p[a])
                .fold(f64::INFINITY, f64::min)
            + 2.4
    });
    let mut client = Client::start(options.executable.as_deref())?;
    ensure!(
        client.scene()?.bodies.is_empty(),
        "Coupon process must start blank"
    );
    let mut coupons = Vec::new();
    for (i, d) in [4.9, 4.8, 4.7].into_iter().enumerate() {
        coupons.push(base(
            &mut client,
            &format!("{} notch pin - diameter {d} mm", i + 1),
            [70. + i as f64 * 30., 70.],
            [18., 14.],
            BASE,
            i + 1,
        )?);
    }
    coupons.push(base(
        &mut client,
        "Common 5.00 mm socket",
        [160., 70.],
        [18., 14.],
        BASE,
        0,
    )?);
    coupons.push(base(
        &mut client,
        "Same-color PETG writing",
        [75., 110.],
        size,
        TEXT_HEIGHT,
        0,
    )?);
    coupons.push(base(
        &mut client,
        "Contrast PETG writing",
        [130., 110.],
        size,
        TEXT_HEIGHT,
        0,
    )?);
    let mut model = canonical(&mut client)?;
    add_locators(&mut model, &source, &coupons)?;
    for (i, c) in coupons.iter().enumerate().skip(4) {
        let mut sketch = source["sketches"]
            .as_array()
            .unwrap()
            .iter()
            .find(|s| s["feature_id"] == 395)
            .unwrap()
            .clone();
        let id = 1801 + i as u64;
        let name = format!("{} flush lettering profile", c.name);
        let lo: [f64; 2] = std::array::from_fn(|a| {
            letter
                .points
                .iter()
                .map(|p| p[a])
                .fold(f64::INFINITY, f64::min)
        });
        map_sketch(&mut sketch, |x, y| {
            [x - lo[0] + c.origin[0] + 1.2, y - lo[1] + c.origin[1] + 1.2]
        });
        sketch["basis"]["origin"] = json!([0., 0., TEXT_HEIGHT]);
        sketch["feature_id"] = json!(id);
        sketch["name"] = json!(name);
        history(&mut model, id, "sketch", &name);
        model["sketches"].as_array_mut().unwrap().push(sketch);
    }
    model["document"]["name"] = json!("Garden auger fit and lettering coupons");
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
    let scene = client.scene()?;
    ensure!(scene.bodies.len() == 6, "Expected six coupon bodies");
    for (i, c) in coupons.iter().enumerate() {
        let mesh = &scene
            .bodies
            .iter()
            .find(|b| b.id == c.body)
            .context("Coupon body missing")?
            .mesh;
        let b = mesh.bounds();
        let height = if i < 3 {
            BASE + 1.8
        } else if i == 3 {
            BASE
        } else {
            TEXT_HEIGHT
        };
        ensure!(
            (b[0][0] - c.origin[0]).abs() < 1e-5
                && (b[1][0] - c.origin[0] - c.size[0]).abs() < 1e-5
                && (b[0][1] - c.origin[1]).abs() < 1e-5
                && (b[1][1] - c.origin[1] - c.size[1]).abs() < 1e-5
                && b[0][2].abs() < 1e-5
                && (b[1][2] - height).abs() < 1e-5,
            "Coupon {} bounds {b:?}, expected origin {:?}, size {:?}",
            c.name,
            c.origin,
            c.size
        );
        if i < 4 {
            let rings = if i == 3 {
                vec![(2.5, BASE - 2.2), (2.5, BASE - 0.2), (2.6, BASE)]
            } else {
                let r = [4.9, 4.8, 4.7][i] / 2.;
                vec![(r, BASE), (r, BASE + 1.4), (r - 0.4, BASE + 1.8)]
            };
            for (r, z) in rings {
                ensure!(
                    mesh.positions
                        .as_chunks::<3>()
                        .0
                        .iter()
                        .any(
                            |p| ((p[0] - c.origin[0] - 9.).hypot(p[1] - c.origin[1] - 7.) - r)
                                .abs()
                                < 1e-4
                                && (p[2] - z).abs() < 1e-5
                        ),
                    "{} missing native profile ring radius {r}, Z {z}",
                    c.name
                );
            }
        }
    }
    fs::write(out.join("scene.json"), serde_json::to_vec(&scene)?)?;
    let mut cad_entries = production;
    cad_entries.insert(
        "model.json".into(),
        serde_json::to_vec(&canonical(&mut client)?)?,
    );
    archive::write(
        &root.join("experiments/garden-auger-coupons.limo"),
        &cad_entries,
    )?;
    let mut entries = package(root, &mut client, &coupons, &letter, &out)?;
    drop(client);
    archive::write(&out.join("input.3mf"), &entries)?;
    if let Some(slicer) = &options.slicer {
        let log = File::create(out.join("native.log"))?;
        let mut child = crate::hidden(
            Command::new(crate::native_absolute(slicer)?)
                .args(["--slice", "0", "--export-3mf", "sliced.3mf", "--outputdir"])
                .arg(&out)
                .arg(out.join("input.3mf"))
                .stdout(Stdio::from(log.try_clone()?))
                .stderr(Stdio::from(log)),
        )
        .spawn()?;
        ensure!(
            crate::wait(&mut child, Duration::from_secs(600))?.success(),
            "Coupon slice failed; see {}",
            out.display()
        );
        let result: Value = serde_json::from_slice(&fs::read(out.join("result.json"))?)?;
        let sliced = archive::read(&out.join("sliced.3mf"))?;
        let summary = validate(&result, &sliced)?;
        fs::write(
            out.join("summary.json"),
            serde_json::to_vec_pretty(&summary)?,
        )?;
        println!("{}", serde_json::to_string(&summary)?);
        for (name, data) in &sliced {
            if name.starts_with("Metadata/")
                && (name.ends_with(".png") || name == "Metadata/slice_info.config")
            {
                entries.insert(name.clone(), data.clone());
            }
        }
    }
    let output = options
        .output
        .clone()
        .unwrap_or_else(|| root.join("print/garden-auger-coupons.3mf"));
    archive::write(&output, &entries)?;
    println!("{}", output.display());
    Ok(())
}

fn validate(result: &Value, entries: &Entries) -> Result<Value> {
    ensure!(result["return_code"] == 0, "Native coupon slice failed");
    let plates = result["sliced_plates"]
        .as_array()
        .context("Missing plates")?;
    ensure!(plates.len() == 1, "Expected one coupon plate");
    let p = &plates[0];
    ensure!(
        p["objects"].as_array().is_some_and(|o| o.len() == 6),
        "Expected six coupon objects"
    );
    ensure!(
        p["warning_message"].as_str() == Some("")
            || p["warning_message"].as_array().is_some_and(Vec::is_empty),
        "Coupon slice warnings: {}",
        p["warning_message"]
    );
    let code = std::str::from_utf8(archive::required(entries, "Metadata/plate_1.gcode")?)?;
    let ids: BTreeSet<_> = code
        .lines()
        .filter_map(|l| l.strip_prefix("; start printing object, unique label id: "))
        .map(str::trim)
        .collect();
    ensure!(
        ids == BTreeSet::from(["102", "104", "106", "108", "110", "112"]),
        "Coupon objects missing"
    );
    for line in code.lines().map(str::trim) {
        if let Some(f) = line.strip_prefix("; FEATURE: ") {
            ensure!(
                !["support", "brim", "skirt", "raft", "prime tower"]
                    .iter()
                    .any(|s| f.to_lowercase().contains(s)),
                "Unexpected coupon feature: {f}"
            );
        }
    }
    ensure!(
        code.contains("; print_sequence = by layer")
            && code.contains("; wall_loops = 3")
            && code.contains("; layer_height = 0.24"),
        "Coupon process changed"
    );
    ensure!(
        p["filaments"]
            .as_array()
            .is_some_and(|f| f.iter().all(|f| f["id"] == 1 || f["id"] == 3)
                && f.iter()
                    .any(|f| f["id"] == 3 && f["main_used_g"].as_f64().is_some_and(|g| g > 0.))),
        "Expected only the two PETG colors"
    );
    let grams: f64 = p["filaments"]
        .as_array()
        .unwrap()
        .iter()
        .map(|f| f["total_used_g"].as_f64().unwrap())
        .sum();
    Ok(
        json!({"seconds":p["total_predication"],"filament_g":grams,"filament_cost":grams*17.99/1000.,"objects":6,"plate_count":1,"pin_diameters_mm":[4.9,4.8,4.7],"socket_diameter_mm":5.0,"pin_height_mm":1.8,"socket_depth_mm":2.2,"coupon_base_mm":BASE,"writing_surface_mm":TEXT_HEIGHT,"lettering_depth_mm":0.72,"colors":["PETG orange","PETG blue"],"printer_command_sent":false}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn coupon_phases_and_notches_preserve_the_housing_test() -> Result<()> {
        assert!(((20.6 - BASE) / 0.24 - 70.).abs() < 1e-9);
        assert!(((10.4 - TEXT_HEIGHT) / 0.24 - 32.).abs() < 1e-9);
        for n in 1..=3 {
            let p = outline([0., 0.], [18., 14.], n);
            let area: f64 = p
                .iter()
                .zip(p.iter().cycle().skip(1))
                .take(p.len())
                .map(|(a, b)| a[0] * b[1] - a[1] * b[0])
                .sum::<f64>()
                / 2.;
            assert!((area - (252. - n as f64 * 1.44)).abs() < 1e-9);
        }
        Ok(())
    }
}
