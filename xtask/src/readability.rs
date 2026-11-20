//! Print trials for clearer curved lettering. Production CAD stays unchanged.
use crate::{archive, cad::Client, coupons, lettering, xml};
use anyhow::{Context, Result, ensure};
use clap::Args;
use serde_json::{Value, json};
use std::{
    fs::{self, File},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    time::Duration,
};
use ttf_parser::{Face, OutlineBuilder};

#[path = "readability_preview.rs"]
mod preview;

const HEIGHT: f64 = coupons::TEXT_HEIGHT;
const DEPTH: f64 = 0.72;
const GAP: f64 = 1.2;
const ROW_GAP: f64 = 1.6;
const LINES: [&str; 4] = ["GA-L1", "M3X18", "D4X6.7", "M3X5.7"];
type Loop = Vec<[f64; 2]>;
type MeshData = (Vec<[f64; 3]>, Vec<[usize; 3]>);

#[derive(Args)]
pub struct Options {
    #[arg(long)]
    pub slicer: PathBuf,
    #[arg(long)]
    pub executable: Option<PathBuf>,
    /// Heavy sans-serif TrueType font. Windows defaults to Impact.
    #[arg(long)]
    pub font: Option<PathBuf>,
    #[arg(long, default_value = ".build/lettering-readability")]
    pub evidence: PathBuf,
}

struct Outline {
    loops: Vec<Loop>,
    current: Loop,
    scale: f64,
}
impl Outline {
    fn p(&self, x: f32, y: f32) -> [f64; 2] {
        [x as f64 * self.scale, y as f64 * self.scale]
    }
    fn quad(&mut self, a: [f64; 2], b: [f64; 2], c: [f64; 2], depth: u8) {
        if depth >= 12 || distance(b, a, c) < 0.015 {
            self.current.push(c);
            return;
        }
        let ab = mid(a, b);
        let bc = mid(b, c);
        let m = mid(ab, bc);
        self.quad(a, ab, m, depth + 1);
        self.quad(m, bc, c, depth + 1);
    }
    fn cubic(&mut self, a: [f64; 2], b: [f64; 2], c: [f64; 2], d: [f64; 2], depth: u8) {
        if depth >= 12 || distance(b, a, d).max(distance(c, a, d)) < 0.015 {
            self.current.push(d);
            return;
        }
        let ab = mid(a, b);
        let bc = mid(b, c);
        let cd = mid(c, d);
        let abc = mid(ab, bc);
        let bcd = mid(bc, cd);
        let m = mid(abc, bcd);
        self.cubic(a, ab, abc, m, depth + 1);
        self.cubic(m, bcd, cd, d, depth + 1);
    }
}
fn mid(a: [f64; 2], b: [f64; 2]) -> [f64; 2] {
    [(a[0] + b[0]) / 2., (a[1] + b[1]) / 2.]
}
fn distance(p: [f64; 2], a: [f64; 2], b: [f64; 2]) -> f64 {
    let d = (b[0] - a[0]).hypot(b[1] - a[1]);
    if d < 1e-12 {
        (p[0] - a[0]).hypot(p[1] - a[1])
    } else {
        ((b[0] - a[0]) * (a[1] - p[1]) - (a[0] - p[0]) * (b[1] - a[1])).abs() / d
    }
}
impl OutlineBuilder for Outline {
    fn move_to(&mut self, x: f32, y: f32) {
        self.current = vec![self.p(x, y)];
    }
    fn line_to(&mut self, x: f32, y: f32) {
        self.current.push(self.p(x, y));
    }
    fn quad_to(&mut self, x1: f32, y1: f32, x: f32, y: f32) {
        self.quad(
            *self.current.last().unwrap(),
            self.p(x1, y1),
            self.p(x, y),
            0,
        );
    }
    fn curve_to(&mut self, x1: f32, y1: f32, x2: f32, y2: f32, x: f32, y: f32) {
        self.cubic(
            *self.current.last().unwrap(),
            self.p(x1, y1),
            self.p(x2, y2),
            self.p(x, y),
            0,
        );
    }
    fn close(&mut self) {
        let mut p = std::mem::take(&mut self.current);
        p.dedup_by(|a, b| (a[0] - b[0]).hypot(a[1] - b[1]) < 1e-8);
        if p.len() > 1 && (p[0][0] - p[p.len() - 1][0]).hypot(p[0][1] - p[p.len() - 1][1]) < 1e-8 {
            p.pop();
        }
        loop {
            let n = p.len();
            if n < 3 {
                break;
            }
            let drop = (0..n).find(|&i| distance(p[i], p[(i + n - 1) % n], p[(i + 1) % n]) < 1e-9);
            if let Some(i) = drop {
                p.remove(i);
            } else {
                break;
            }
        }
        if p.len() >= 3 {
            self.loops.push(p);
        }
    }
}
fn area(p: &[[f64; 2]]) -> f64 {
    p.iter()
        .zip(p.iter().cycle().skip(1))
        .take(p.len())
        .map(|(a, b)| a[0] * b[1] - a[1] * b[0])
        .sum::<f64>()
        / 2.
}
fn contains(p: &[[f64; 2]], q: [f64; 2]) -> bool {
    p.iter()
        .zip(p.iter().cycle().skip(1))
        .take(p.len())
        .filter(|(a, b)| {
            (a[1] > q[1]) != (b[1] > q[1])
                && q[0] < a[0] + (b[0] - a[0]) * (q[1] - a[1]) / (b[1] - a[1])
        })
        .count()
        % 2
        == 1
}

struct Label {
    cap: f64,
    loops: Vec<Loop>,
    region: lettering::Region,
    size: [f64; 2],
}
fn label(face: &Face<'_>, cap: f64) -> Result<Label> {
    let h = face
        .glyph_bounding_box(face.glyph_index('H').context("Font lacks H")?)
        .context("Font has no capital outline")?;
    let scale = cap / f64::from(h.y_max - h.y_min);
    let mut all = vec![];
    for (row, line) in LINES.iter().enumerate() {
        let mut x = 0.;
        for ch in line.chars() {
            let mut b = Outline {
                loops: vec![],
                current: vec![],
                scale,
            };
            let id = face
                .glyph_index(ch)
                .with_context(|| format!("Font lacks {ch}"))?;
            face.outline_glyph(id, &mut b)
                .context("Malformed font outline")?;
            let lo = b
                .loops
                .iter()
                .flatten()
                .map(|p| p[0])
                .fold(f64::INFINITY, f64::min);
            let hi = b
                .loops
                .iter()
                .flatten()
                .map(|p| p[0])
                .fold(f64::NEG_INFINITY, f64::max);
            for p in b.loops.iter_mut().flatten() {
                p[0] += x - lo;
                p[1] += (3 - row) as f64 * (cap + ROW_GAP);
            }
            x += hi - lo + GAP;
            all.extend(b.loops);
        }
    }
    let lo: [f64; 2] = std::array::from_fn(|a| {
        all.iter()
            .flatten()
            .map(|p| p[a])
            .fold(f64::INFINITY, f64::min)
    });
    for p in all.iter_mut().flatten() {
        for a in 0..2 {
            p[a] -= lo[a];
        }
    }
    let size = std::array::from_fn(|a| all.iter().flatten().map(|p| p[a]).fold(0., f64::max) + 2.4);
    let (points, faces) = extrude(&all, HEIGHT - DEPTH, HEIGHT)?;
    let region = lettering::Region {
        name: format!("{cap} mm heavy curved lettering"),
        part: String::new(),
        body_id: 0,
        filament: 3,
        surface: HEIGHT,
        points,
        faces,
    };
    Ok(Label {
        cap,
        loops: all,
        region,
        size,
    })
}

// Earcut may skip a collinear contour vertex or bridge through another vertex.
// Split those triangle edges before extrusion so the cap and side share edges.
fn conform(tris: &[usize], points: &[[f64; 2]]) -> Vec<[usize; 3]> {
    let mut pending: Vec<_> = tris.as_chunks::<3>().0.to_vec();
    let mut out = vec![];
    while let Some(f) = pending.pop() {
        let split = (0..3).find_map(|j| {
            let (a, b, c) = (f[j], f[(j + 1) % 3], f[(j + 2) % 3]);
            points
                .iter()
                .enumerate()
                .find(|(p, q)| {
                    !f.contains(p)
                        && distance(**q, points[a], points[b]) < 1e-8
                        && (q[0] - points[a][0]) * (q[0] - points[b][0])
                            + (q[1] - points[a][1]) * (q[1] - points[b][1])
                            < -1e-10
                })
                .map(|(p, _)| (a, b, c, p))
        });
        if let Some((a, b, c, p)) = split {
            pending.extend([[a, p, c], [p, b, c]]);
        } else {
            out.push(f);
        }
    }
    out
}
fn extrude(loops: &[Loop], lo: f64, hi: f64) -> Result<MeshData> {
    let parents: Vec<_> = loops
        .iter()
        .enumerate()
        .map(|(i, p)| {
            loops
                .iter()
                .enumerate()
                .filter(|(j, q)| i != *j && area(q).abs() > area(p).abs() && contains(q, p[0]))
                .min_by(|(_, a), (_, b)| area(a).abs().total_cmp(&area(b).abs()))
                .map(|(j, _)| j)
        })
        .collect();
    let depth = |mut i: usize| {
        let mut n = 0;
        while let Some(p) = parents[i] {
            i = p;
            n += 1;
        }
        n
    };
    let mut points = vec![];
    let mut faces = vec![];
    for (i, outer) in loops.iter().enumerate().filter(|(i, _)| depth(*i) % 2 == 0) {
        let mut rings = vec![outer.clone()];
        rings.extend(
            loops
                .iter()
                .enumerate()
                .filter(|(j, _)| parents[*j] == Some(i))
                .map(|(_, p)| p.clone()),
        );
        for (j, p) in rings.iter_mut().enumerate() {
            if (area(p) > 0.) != (j == 0) {
                p.reverse();
            }
        }
        let flat: Vec<_> = rings.iter().flatten().copied().collect();
        let xy: Vec<_> = flat.iter().flatten().copied().collect();
        let mut holes = vec![];
        let mut n = rings[0].len();
        for p in rings.iter().skip(1) {
            holes.push(n);
            n += p.len();
        }
        let tris = earcutr::earcut(&xy, &holes, 2).context("Font triangulation failed")?;
        let base = points.len();
        points.extend(flat.iter().map(|p| [p[0], p[1], lo]));
        points.extend(flat.iter().map(|p| [p[0], p[1], hi]));
        for mut f in conform(&tris, &flat) {
            let [a, b, c] = f.map(|i| flat[i]);
            if (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) < 0. {
                f.swap(1, 2)
            }
            faces.push([base + f[2], base + f[1], base + f[0]]);
            faces.push(f.map(|i| base + n + i));
        }
        let mut offset = 0;
        for ring in rings {
            for j in 0..ring.len() {
                let a = base + offset + j;
                let b = base + offset + (j + 1) % ring.len();
                faces.extend([[a, b, b + n], [a, b + n, a + n]]);
            }
            offset += ring.len();
        }
    }
    if let Err(error) = coupons::check_mesh(&coupons::mesh_node(&points, &faces)) {
        let mut edges = std::collections::BTreeMap::<(usize, usize), (usize, i32)>::new();
        for f in &faces {
            for (a, b) in [(f[0], f[1]), (f[1], f[2]), (f[2], f[0])] {
                let e = edges.entry((a.min(b), a.max(b))).or_default();
                e.0 += 1;
                e.1 += if a < b { 1 } else { -1 };
            }
        }
        let bad: Vec<_> = edges
            .iter()
            .filter(|(_, v)| **v != (2, 0))
            .take(6)
            .map(|(&(a, b), v)| (points[a], points[b], v))
            .collect();
        anyhow::bail!("{error}: {bad:?}");
    }
    Ok((points, faces))
}

fn native_sketch(template: &Value, label: &Label, c: &coupons::Coupon, id: u64) -> Value {
    let mut sketch = template.clone();
    let mut entities = vec![];
    let mut last = 0u64;
    for p in &label.loops {
        let start = last + 1;
        for q in p {
            last += 1;
            entities.push(json!([last,{"type":"point","position":{"x":q[0]+c.origin[0]+1.2,"y":q[1]+c.origin[1]+1.2}}]));
        }
        for j in 0..p.len() {
            last += 1;
            entities.push(json!([last,{"type":"line","start":start+j as u64,"end":start+(j+1)as u64%p.len()as u64}]));
        }
    }
    sketch["snapshot"] = json!({"constraints":[],"dim_modes":{},"dim_params":{},"dim_placements":{},"entities":entities,"fix_targets":{},"generated_points":[],"next_constraint":0,"next_entity":last,"offset_sides":{},"params":{"next_id":0,"next_name":0,"params":[]},"reference_edges":[]});
    sketch["entity_id_high_water"] = json!(last);
    sketch["profile_identities"] = json!({"next":0,"records":[]});
    sketch["grid_snap"] = json!(false);
    sketch["feature_id"] = json!(id);
    sketch["name"] = json!(format!("{} font outline profile", c.name));
    sketch["basis"]["origin"] = json!([0., 0., HEIGHT]);
    sketch
}

fn slice(
    entries: &archive::Entries,
    slicer: &Path,
    out: &Path,
    filament: usize,
) -> Result<(archive::Entries, Value)> {
    fs::create_dir_all(out)?;
    let out = crate::native_absolute(out)?;
    archive::write(&out.join("input.3mf"), entries)?;
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
        "Native lettering slice failed: {}",
        out.display()
    );
    let result: Value = serde_json::from_slice(&fs::read(out.join("result.json"))?)?;
    ensure!(result["return_code"] == 0, "Native slice returned failure");
    let plates = result["sliced_plates"].as_array().context("No plates")?;
    ensure!(plates.len() == 1, "Expected one plate");
    let p = &plates[0];
    ensure!(
        p["objects"].as_array().is_some_and(|o| o.len() == 2),
        "Expected two lettering coupons"
    );
    ensure!(
        p["warning_message"] == "" || p["warning_message"].as_array().is_some_and(Vec::is_empty),
        "Slice warning: {}",
        p["warning_message"]
    );
    let sliced = archive::read(&out.join("sliced.3mf"))?;
    let code = std::str::from_utf8(&sliced["Metadata/plate_1.gcode"])?;
    ensure!(
        code.contains("; wall_loops = 3")
            && code.contains("; layer_height = 0.24")
            && code.contains("; top_shell_layers = 5")
            && code.contains("; top_shell_thickness = 1.2")
            && code.contains("; top_solid_infill_flow_ratio = 1,1")
            && code.contains("; ironing_type = no ironing")
            && code.contains("; nozzle_diameter = 0.4,0.4")
            && code.contains("; print_sequence = by layer"),
        "Coupon process changed"
    );
    ensure!(
        !code.lines().any(|l| l.starts_with("; FEATURE: ")
            && ["Support", "Brim", "Skirt", "Raft", "Prime tower", "Ironing"]
                .iter()
                .any(|f| l.contains(f))),
        "Unexpected support or adhesion geometry"
    );
    let filaments = p["filaments"].as_array().context("No filaments")?;
    ensure!(
        filaments
            .iter()
            .all(|f| f["id"] == 1 || (filament == 3 && f["id"] == 3)),
        "Unexpected material"
    );
    ensure!(
        filaments
            .iter()
            .any(|f| f["id"] == filament && f["main_used_g"].as_f64().is_some_and(|g| g > 0.)),
        "Missing lettering filament"
    );
    let config = xml::parse(&sliced["Metadata/model_settings.config"])?;
    for object in config.children.iter().filter(|o| o.is("object")) {
        let part = object
            .children
            .iter()
            .find(|p| p.attrs.get("subtype").is_some_and(|v| v == "modifier_part"))
            .context("Native lettering region missing")?;
        let meta = part.metadata();
        for (k, v) in lettering::print_settings(filament) {
            ensure!(meta.get(&k) == Some(&v), "Lettering {k} did not roundtrip");
        }
    }
    let grams: f64 = filaments
        .iter()
        .map(|f| f["total_used_g"].as_f64().unwrap())
        .sum();
    let summary = json!({"seconds":p["total_predication"],"grams":grams,"filament_cost":grams*17.99/1000.,"cap_heights_mm":[7.,8.],"character_gap_mm":GAP,"row_gap_mm":ROW_GAP,"mode":if filament==1{"single-color texture"}else{"AMS flush color"},"printer_command_sent":false});
    fs::write(
        out.join("summary.json"),
        serde_json::to_vec_pretty(&summary)?,
    )?;
    Ok((sliced, summary))
}

pub fn run(root: &Path, options: &Options) -> Result<()> {
    fs::create_dir_all(&options.evidence)?;
    let out = crate::native_absolute(&options.evidence)?;
    let font = options.font.clone().unwrap_or_else(|| {
        PathBuf::from(if cfg!(windows) {
            "C:/Windows/Fonts/impact.ttf"
        } else {
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        })
    });
    let data = fs::read(&font).with_context(|| {
        format!(
            "Read {}; pass --font for another heavy sans-serif",
            font.display()
        )
    })?;
    let face = Face::parse(&data, 0)?;
    let labels = [label(&face, 7.)?, label(&face, 8.)?];
    let mut client = Client::start(options.executable.as_deref())?;
    let mut bases = vec![];
    for (i, label) in labels.iter().enumerate() {
        bases.push(coupons::base(
            &mut client,
            &format!("{} mm heavy text", label.cap),
            [70. + i as f64 * 60., 70.],
            label.size,
            HEIGHT,
            0,
        )?);
    }
    let source = archive::read(&root.join("garden-auger.limo"))?;
    let original: Value = serde_json::from_slice(&source["model.json"])?;
    let template = original["sketches"]
        .as_array()
        .unwrap()
        .iter()
        .find(|s| s["feature_id"] == 395)
        .context("Label sketch template missing")?;
    let mut model = coupons::canonical(&mut client)?;
    for (i, (label, c)) in labels.iter().zip(&bases).enumerate() {
        let id = 1001 + i as u64;
        let sketch = native_sketch(template, label, c, id);
        coupons::history(&mut model, id, "sketch", sketch["name"].as_str().unwrap());
        model["sketches"].as_array_mut().unwrap().push(sketch);
    }
    model["document"]["name"] = json!("Garden auger heavy lettering trials");
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
    ensure!(scene.bodies.len() == 2, "Unexpected native bodies");
    for c in &bases {
        let b = scene
            .bodies
            .iter()
            .find(|b| b.id == c.body)
            .context("Missing base")?
            .mesh
            .bounds();
        ensure!(
            (b[1][0] - b[0][0] - c.size[0]).abs() < 1e-5
                && (b[1][1] - b[0][1] - c.size[1]).abs() < 1e-5
                && (b[1][2] - HEIGHT).abs() < 1e-5,
            "Native coupon dimensions changed"
        );
    }
    let mut cad = source;
    cad.insert(
        "model.json".into(),
        serde_json::to_vec(&coupons::canonical(&mut client)?)?,
    );
    archive::write(
        &root.join("experiments/garden-auger-lettering-coupons.limo"),
        &cad,
    )?;
    let mut summaries = vec![];
    for (mode, filament) in [("ams", 3), ("single-color", 1)] {
        let paints = labels
            .iter()
            .enumerate()
            .map(|(i, l)| (i, (&l.region, filament)))
            .collect();
        let mut entries = coupons::package(
            root,
            &mut client,
            &bases,
            &paints,
            &out,
            "experiments/garden-auger-lettering-coupons.limo",
        )?;
        let mut model = xml::parse(&entries["3D/3dmodel.model"])?;
        model
            .children
            .iter_mut()
            .find(|n| n.is("metadata") && n.attrs.get("name").is_some_and(|n| n == "Title"))
            .context("Print title missing")?
            .set_text(&format!("Garden auger {mode} lettering coupons"));
        entries.insert("3D/3dmodel.model".into(), xml::encode(&model));
        let mut metadata = xml::parse(&entries["Metadata/model_settings.config"])?;
        for p in metadata.children.iter_mut().filter(|n| n.is("plate")) {
            for m in p.children.iter_mut().filter(|n| {
                n.is("metadata") && n.attrs.get("key").is_some_and(|k| k == "plater_name")
            }) {
                m.attrs
                    .insert("value".into(), format!("{mode} - 7 and 8 mm heavy text"));
            }
        }
        entries.insert(
            "Metadata/model_settings.config".into(),
            xml::encode(&metadata),
        );
        let (sliced, summary) = slice(&entries, &options.slicer, &out.join(mode), filament)?;
        for (name, data) in sliced {
            if name.starts_with("Metadata/")
                && (name.ends_with(".png") || name == "Metadata/slice_info.config")
            {
                entries.insert(name, data);
            }
        }
        let path = root.join(format!("print/garden-auger-lettering-{mode}-coupons.3mf"));
        archive::write(&path, &entries)?;
        summaries.push(summary);
        println!("{}", path.display());
    }
    let report = json!({"font_file_sha256":archive::sha(&data),"font_file":font.file_name().unwrap().to_string_lossy(),"lines":LINES,"curve_tolerance_mm":0.015,"labels":labels.iter().map(|l|json!({"cap_mm":l.cap,"coupon_size_mm":[l.size[0],l.size[1],HEIGHT],"points":l.region.points.len(),"triangles":l.region.faces.len()})).collect::<Vec<_>>(),"slices":summaries,"production_model_changed":false,"physical_readability_confirmed":false});
    fs::write(
        out.join("summary.json"),
        serde_json::to_vec_pretty(&report)?,
    )?;
    preview::write(&out, &bases, &labels, &summaries)?;
    println!("{}", serde_json::to_string(&report)?);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn curved_outline_holes_extrude_as_closed_meshes() -> Result<()> {
        let loops = vec![
            vec![[0., 0.], [6., 0.], [6., 8.], [0., 8.]],
            vec![[1.5, 1.5], [4.5, 1.5], [4.5, 6.5], [1.5, 6.5]],
        ];
        let (p, f) = extrude(&loops, 0., 0.72)?;
        let volume: f64 = f
            .iter()
            .map(|f| {
                let [a, b, c] = f.map(|i| p[i]);
                (a[0] * (b[1] * c[2] - b[2] * c[1])
                    + a[1] * (b[2] * c[0] - b[0] * c[2])
                    + a[2] * (b[0] * c[1] - b[1] * c[0]))
                    / 6.
            })
            .sum();
        ensure!(
            (volume - (48. - 15.) * 0.72).abs() < 1e-8,
            "Counters were filled"
        );
        Ok(())
    }
    #[test]
    fn skipped_collinear_boundary_vertices_are_restored() {
        let points = [[0., 0.], [4., 0.], [0., 4.], [2., 0.]];
        let tris = conform(&[0, 1, 2], &points);
        assert_eq!(tris.len(), 2);
        assert!(tris.iter().all(|f| f.contains(&3)));
    }
}
