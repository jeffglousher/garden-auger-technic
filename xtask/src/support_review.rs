//! Relate the manufactured flat faces to the actual native support toolpaths.
use crate::{archive, gcode, xml};
use anyhow::{Context, Result, ensure};
use clap::Args;
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
};

#[derive(Args)]
pub struct Options {
    /// Directory from a successful build-print --slicer run.
    #[arg(long)]
    pub slice: PathBuf,
    /// Defaults to the published contrasting-color project; accepts a separate trial.
    #[arg(long)]
    pub project: Option<PathBuf>,
    #[arg(long, default_value = ".build/long-auger/support-review")]
    pub output: PathBuf,
}

type P3 = [f64; 3];
type Triangle = [P3; 3];
struct Patch {
    triangles: Vec<Triangle>,
    area: f64,
    bounds: [[f64; 2]; 2],
}
struct PathSegment {
    a: P3,
    b: P3,
    width: f64,
    interface: bool,
}

fn child<'a>(n: &'a xml::Node, name: &str) -> Result<&'a xml::Node> {
    n.children
        .iter()
        .find(|n| n.is(name))
        .with_context(|| format!("Missing {name}"))
}
fn values(s: &str) -> Result<Vec<f64>> {
    s.split_whitespace().map(|s| Ok(s.parse()?)).collect()
}
fn land(y: f64) -> f64 {
    crate::lengthen::flight_land(y, 240.)
}
fn inside(p: [f64; 2], t: &Triangle) -> bool {
    if ((t[1][0] - t[0][0]) * (t[2][1] - t[0][1]) - (t[1][1] - t[0][1]) * (t[2][0] - t[0][0])).abs()
        < 1e-12
    {
        return false;
    }
    let cross = |a: P3, b: P3| (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]);
    let d = [cross(t[0], t[1]), cross(t[1], t[2]), cross(t[2], t[0])];
    d.iter().all(|d| *d >= -1e-9) || d.iter().all(|d| *d <= 1e-9)
}
fn distance(p: [f64; 2], a: [f64; 2], b: [f64; 2]) -> (f64, f64) {
    let v = [b[0] - a[0], b[1] - a[1]];
    let n = v[0] * v[0] + v[1] * v[1];
    let t = if n == 0. {
        0.
    } else {
        (((p[0] - a[0]) * v[0] + (p[1] - a[1]) * v[1]) / n).clamp(0., 1.)
    };
    ((p[0] - a[0] - t * v[0]).hypot(p[1] - a[1] - t * v[1]), t)
}

fn definition(m: &[f64], offset: P3, p: P3) -> P3 {
    let q = [p[0] - (m[9] - 307.2), p[1] - m[10], p[2] - m[11]];
    std::array::from_fn(|i| (0..3).map(|k| m[3 * i + k] * q[k]).sum::<f64>() + offset[i])
}

fn patches(points: &[P3], faces: &[[usize; 3]], sign: f64) -> Vec<Patch> {
    let selected: Vec<_> = faces
        .iter()
        .filter(|f| {
            f.iter().all(|&i| {
                points[i][1] < 104. && (points[i][2] - sign * land(points[i][1])).abs() < 0.002
            })
        })
        .copied()
        .collect();
    let mut links = BTreeMap::<usize, Vec<usize>>::new();
    for (i, f) in selected.iter().enumerate() {
        for v in f {
            links.entry(*v).or_default().push(i);
        }
    }
    let mut seen = vec![false; selected.len()];
    let mut patches = Vec::new();
    for i in 0..selected.len() {
        if seen[i] {
            continue;
        }
        let mut todo = vec![i];
        let mut triangles = Vec::new();
        let mut area = 0.;
        let mut bounds = [[f64::INFINITY; 2], [f64::NEG_INFINITY; 2]];
        while let Some(i) = todo.pop() {
            if seen[i] {
                continue;
            }
            seen[i] = true;
            let t = selected[i].map(|v| points[v]);
            for p in t {
                for a in 0..2 {
                    bounds[0][a] = bounds[0][a].min(p[a]);
                    bounds[1][a] = bounds[1][a].max(p[a]);
                }
            }
            let u: [f64; 3] = std::array::from_fn(|a| t[1][a] - t[0][a]);
            let v: [f64; 3] = std::array::from_fn(|a| t[2][a] - t[0][a]);
            area += 0.5
                * ((u[1] * v[2] - u[2] * v[1]).powi(2)
                    + (u[2] * v[0] - u[0] * v[2]).powi(2)
                    + (u[0] * v[1] - u[1] * v[0]).powi(2))
                .sqrt();
            for v in selected[i] {
                todo.extend(links[&v].iter().copied().filter(|i| !seen[*i]));
            }
            triangles.push(t);
        }
        if area > 0.01 {
            patches.push(Patch {
                triangles,
                area,
                bounds,
            });
        }
    }
    patches.sort_by(|a, b| a.bounds[0][1].total_cmp(&b.bounds[0][1]));
    patches
}

fn provenance(
    current: &archive::Entries,
    input: &archive::Entries,
    sliced: &archive::Entries,
    code: &[u8],
) -> Result<()> {
    for path in [
        "3D/3dmodel.model",
        "3D/Objects/object_3.model",
        "Metadata/model_settings.config",
        "Metadata/project_settings.config",
    ] {
        ensure!(
            archive::required(current, path)? == archive::required(input, path)?,
            "Slice input is stale or different: {path}"
        );
    }
    ensure!(
        archive::required(sliced, "Metadata/plate_2.gcode")? == code,
        "G-code does not match native sliced archive"
    );
    Ok(())
}

fn svg_paths(segments: &[&gcode::Segment], world: bool) -> String {
    let mut groups = BTreeMap::<(String, i64), String>::new();
    for s in segments {
        let color = if s.feature == "Support interface" {
            "#168b8b"
        } else if s.feature.starts_with("Support") {
            "#697586"
        } else {
            match s.filament {
                1 => "#e58330",
                2 => "#929cab",
                3 => "#168b8b",
                _ => "#d4a328",
            }
        };
        let d = groups
            .entry((color.into(), (s.width * 1000.).round() as i64))
            .or_default();
        let a = s.a;
        let b = s.b;
        d.push_str(&format!(
            "M{:.3},{:.3}L{:.3},{:.3}",
            a[0],
            if world { 256. - a[1] } else { -a[1] },
            b[0],
            if world { 256. - b[1] } else { -b[1] }
        ));
    }
    groups
        .into_iter()
        .map(|((c, w), d)| {
            format!(
                "<path d='{d}' fill='none' stroke='{c}' stroke-width='{}' stroke-linecap='round'/>",
                w as f64 / 1000.
            )
        })
        .collect()
}

pub fn run(root: &Path, options: &Options) -> Result<()> {
    let project = options
        .project
        .clone()
        .unwrap_or_else(|| root.join("print/garden-auger.3mf"));
    let current = archive::read(&project)?;
    let input = archive::read(&options.slice.join("input.3mf"))?;
    let sliced = archive::read(&options.slice.join("sliced.3mf"))?;
    let code = fs::read(options.slice.join("plate_2.gcode"))?;
    provenance(&current, &input, &sliced, &code)?;
    let native: Value = serde_json::from_slice(&fs::read(options.slice.join("result.json"))?)?;
    ensure!(native["return_code"] == 0, "Native slice did not pass");
    let config = xml::parse(archive::required(
        &current,
        "Metadata/model_settings.config",
    )?)?;
    let object = config
        .children
        .iter()
        .find(|n| n.is("object") && n.attrs.get("id").is_some_and(|id| id == "8"))
        .context("Missing auger object")?;
    let part = object
        .children
        .iter()
        .find(|n| n.is("part") && n.attrs.get("id").is_some_and(|id| id == "7"))
        .context("Missing auger part")?;
    let meta = part.metadata();
    let offset: P3 = std::array::from_fn(|i| {
        meta[&format!("source_offset_{}", ["x", "y", "z"][i])]
            .parse()
            .unwrap()
    });
    let model = xml::parse(archive::required(&current, "3D/3dmodel.model")?)?;
    let item = child(&model, "build")?
        .children
        .iter()
        .find(|n| n.is("item") && n.attrs.get("objectid").is_some_and(|id| id == "8"))
        .context("Missing auger placement")?;
    let m = values(item.attr("transform")?)?;
    ensure!(
        m.len() == 12 && m.iter().all(|v| v.is_finite()),
        "Invalid auger placement"
    );
    for i in 0..3 {
        for j in 0..3 {
            let dot = (0..3).map(|k| m[3 * i + k] * m[3 * j + k]).sum::<f64>();
            ensure!(
                (dot - if i == j { 1. } else { 0. }).abs() < 1e-7,
                "Scaled or skewed auger placement"
            );
        }
    }
    let mesh_file = xml::parse(archive::required(&current, "3D/Objects/object_3.model")?)?;
    let mesh = child(child(child(&mesh_file, "resources")?, "object")?, "mesh")?;
    let points: Vec<P3> = child(mesh, "vertices")?
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
    let faces: Vec<[usize; 3]> = child(mesh, "triangles")?
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
    let lower = patches(&points, &faces, -1.);
    let upper = patches(&points, &faces, 1.);
    ensure!(
        !lower.is_empty() && !upper.is_empty(),
        "Manufacturing mesh lacks flight flats"
    );
    let code = std::str::from_utf8(&code)?;
    let all = gcode::paths(code)?;
    let paths: Vec<_> = all
        .iter()
        .filter(|s| s.object == 108)
        .map(|s| PathSegment {
            a: definition(&m, offset, [s.a[0], s.a[1], s.z]),
            b: definition(&m, offset, [s.b[0], s.b[1], s.z]),
            width: s.width,
            interface: s.feature == "Support interface",
        })
        .collect();
    let mut contacts = Vec::new();
    let mut svg = String::from(
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='-108 -22 255 44' style='background:#fff' role='img' aria-label='Actual support interface beneath lower flight flats; axial position in millimetres'>",
    );
    for patch in &lower {
        let candidates: Vec<_> = paths
            .iter()
            .filter(|s| {
                s.interface
                    && s.a[0].min(s.b[0]) <= patch.bounds[1][0] + s.width
                    && s.a[0].max(s.b[0]) >= patch.bounds[0][0] - s.width
                    && s.a[1].min(s.b[1]) <= patch.bounds[1][1] + s.width
                    && s.a[1].max(s.b[1]) >= patch.bounds[0][1] - s.width
            })
            .collect();
        let (mut samples, mut covered) = (0, 0);
        let mut closest_gap = f64::INFINITY;
        let mut x = patch.bounds[0][0] + 0.1;
        while x < patch.bounds[1][0] {
            let mut y = patch.bounds[0][1] + 0.1;
            while y < patch.bounds[1][1] {
                let p = [x, y];
                if patch.triangles.iter().any(|t| inside(p, t)) {
                    samples += 1;
                    let covered_here = candidates.iter().any(|s| {
                        let (distance, t) = distance(p, [s.a[0], s.a[1]], [s.b[0], s.b[1]]);
                        let z = s.a[2] + t * (s.b[2] - s.a[2]);
                        let gap = -land(y) - z;
                        if (-0.12..=0.36).contains(&gap) && distance <= s.width / 2. {
                            closest_gap = closest_gap.min(gap);
                            true
                        } else {
                            false
                        }
                    });
                    if covered_here {
                        covered += 1;
                    }
                }
                y += 0.2;
            }
            x += 0.2;
        }
        for t in &patch.triangles {
            svg.push_str(&format!(
                "<path d='M{},{}L{},{}L{},{}Z' fill='#e5e7eb' stroke='none'/>",
                t[0][1], -t[0][0], t[1][1], -t[1][0], t[2][1], -t[2][0]
            ));
        }
        for s in &candidates {
            let y = (s.a[1] + s.b[1]) / 2.;
            if (-0.12..=0.36).contains(&(-land(y) - (s.a[2] + s.b[2]) / 2.)) {
                svg.push_str(&format!("<path d='M{:.3},{:.3}L{:.3},{:.3}' fill='none' stroke='#168b8b' stroke-width='{}'/>",s.a[1],-s.a[0],s.b[1],-s.b[0],s.width));
            }
        }
        contacts.push(json!({"axial_bounds_mm":[patch.bounds[0][1],patch.bounds[1][1]],"planar_area_mm2":patch.area,"sample_count":samples,"samples_with_interface_bead":covered,"sampled_coverage_fraction":if samples==0{0.}else{covered as f64/samples as f64},"closest_programmed_gap_mm":if closest_gap.is_finite(){Some(closest_gap)}else{None}}));
    }
    svg.push_str("<text x='-105' y='-17' font-size='3' font-family='Arial'>Lower flight flats (gray) and actual interface bead footprints (teal)</text><text x='-105' y='20' font-size='2.7' font-family='Arial'>Axial position, mm; 0.2 mm sample grid; nominal bead widths, not a physical adhesion test</text></svg>");
    fs::create_dir_all(&options.output)?;
    fs::write(options.output.join("flight-contact.svg"), svg)?;
    let first: Vec<_> = all.iter().filter(|s| (s.z - 0.2).abs() < 0.001).collect();
    let mut first_svg = String::from(
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='-4 -12 264 282' style='background:#fff' role='img' aria-label='Actual first-layer footprints on the 256 mm plate, printed by object'><rect width='256' height='256' fill='#f8fafc' stroke='#64748b' stroke-width='.4'/>",
    );
    first_svg.push_str(&svg_paths(&first, true));
    first_svg.push_str("<text x='0' y='-5' font-size='5' font-family='Arial'>Actual first-layer footprints, 256 mm bed</text><text x='0' y='265' font-size='4' font-family='Arial'>Gray: auger supports; orange: auger; other colors: adapter and bushing</text></svg>");
    fs::write(options.output.join("first-layer.svg"), first_svg)?;
    let process: Value = serde_json::from_slice(archive::required(
        &current,
        "Metadata/project_settings.config",
    )?)?;
    let slicer = code
        .lines()
        .find_map(|l| l.strip_prefix("; BambuStudio "))
        .context("Missing slicer version")?;
    let report = json!({"source_project_sha256":archive::sha(&fs::read(&project)?),"source_gcode_sha256":archive::sha(code.as_bytes()),"source_matches_selected_project":true,"native_slicer_version":slicer,"lower_flight_flat_patches":lower.len(),"upper_flight_flat_patches":upper.len(),"sample_grid_mm":0.2,"interface_gap_window_mm":[-0.12,0.36],"support_type":process["support_type"],"support_interface_filament":process["support_interface_filament"],"support_top_z_distance":process["support_top_z_distance"],"contacts":contacts,"physical_stability_verified":false,"printer_command_sent":false});
    fs::write(
        options.output.join("summary.json"),
        serde_json::to_vec_pretty(&report)?,
    )?;
    println!("{}", serde_json::to_string(&report)?);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn tilted_placement_roundtrips_all_three_axes() {
        let (s, c) = 25_f64.to_radians().sin_cos();
        let (sn, cs) = crate::lengthen::flight_slope(240.).atan().sin_cos();
        let m = [
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
            16.,
        ];
        let p = [4., -85., -10.];
        let q = std::array::from_fn(|i| {
            (0..3).map(|j| m[3 * j + i] * p[j]).sum::<f64>() + m[9 + i]
                - if i == 0 { 307.2 } else { 0. }
        });
        let back = definition(&m, [0., 19.5, 0.], q);
        for i in 0..3 {
            assert!((back[i] - p[i] - if i == 1 { 19.5 } else { 0. }).abs() < 1e-8);
        }
    }
    #[test]
    fn sampling_handles_triangle_edges_and_finite_bead_lengths() {
        let t = [[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]];
        assert!(inside([0.5, 0.5], &t));
        assert!(!inside([1., 1.], &t));
        assert!(!inside([0., 0.], &[[0., 0., 0.]; 3]));
        assert_eq!(distance([2., 0.], [0., 0.], [1., 0.]).0, 1.);
    }
    #[test]
    fn mismatched_slice_is_rejected() {
        let current = archive::Entries::from([("3D/3dmodel.model".into(), b"new".to_vec())]);
        let old = archive::Entries::from([("3D/3dmodel.model".into(), b"old".to_vec())]);
        assert!(provenance(&current, &old, &old, b"").is_err());
    }
}
