//! Compare programmed infill, keeping the physical-strength claim separate.
use crate::{archive, gcode, print, xml};
use anyhow::{Context, Result, ensure};
use clap::Args;
use serde_json::{Value, json};
use std::{
    fs,
    path::{Path, PathBuf},
};

#[derive(Args)]
pub struct Options {
    #[arg(long)]
    pub slice: PathBuf,
    #[arg(long)]
    pub reference_slice: PathBuf,
    #[arg(long, default_value = ".build/strength-review")]
    pub output: PathBuf,
}

fn job(lane: &Path) -> Result<(archive::Entries, archive::Entries)> {
    let pair: Value = serde_json::from_slice(&fs::read(lane.join("native-pair.json"))?)?;
    ensure!(
        pair == print::native_pair(lane)?,
        "Native slice pair changed: {}",
        lane.display()
    );
    let result: Value = serde_json::from_slice(&fs::read(lane.join("result.json"))?)?;
    ensure!(result["return_code"] == 0, "Native job did not pass");
    Ok((
        archive::read(&lane.join("input.3mf"))?,
        archive::read(&lane.join("sliced.3mf"))?,
    ))
}

fn comparable(a: &archive::Entries, b: &archive::Entries) -> Result<()> {
    for i in 1..=5 {
        let name = format!("3D/Objects/object_{i}.model");
        ensure!(
            archive::required(a, &name)? == archive::required(b, &name)?,
            "Comparison part geometry changed: {name}"
        );
    }
    ensure!(
        archive::required(a, "Metadata/project_settings.config")?
            == archive::required(b, "Metadata/project_settings.config")?,
        "Comparison global process/material settings changed"
    );
    for path in ["3D/3dmodel.model", "Metadata/model_settings.config"] {
        let mut trees = Vec::new();
        for entries in [a, b] {
            let mut tree = xml::parse(archive::required(entries, path)?)?;
            if path == "3D/3dmodel.model" {
                tree.children.retain(|n| n.is("build"));
            } else {
                for object in &mut tree.children {
                    object.children.retain(|n| {
                        !(n.is("part")
                            && n.attrs.get("subtype").is_some_and(|s| s == "modifier_part"))
                    });
                }
            }
            trees.push(xml::encode(&tree));
        }
        ensure!(
            trees[0] == trees[1],
            "Comparison placement/object/normal settings changed: {path}"
        );
    }
    Ok(())
}

fn placement(input: &archive::Entries, id: &str) -> Result<(Vec<f64>, [f64; 3])> {
    let model = xml::parse(archive::required(input, "3D/3dmodel.model")?)?;
    let item = model
        .children
        .iter()
        .find(|n| n.is("build"))
        .context("Missing build")?
        .children
        .iter()
        .find(|n| n.is("item") && n.attrs.get("objectid").is_some_and(|v| v == id))
        .context("Missing placement")?;
    let m = item
        .attr("transform")?
        .split_whitespace()
        .map(|v| Ok(v.parse()?))
        .collect::<Result<Vec<f64>>>()?;
    ensure!(
        m.len() == 12 && m.iter().all(|v| v.is_finite()),
        "Invalid placement"
    );
    for i in 0..3 {
        for j in 0..3 {
            let d = (0..3).map(|k| m[3 * i + k] * m[3 * j + k]).sum::<f64>();
            ensure!(
                (d - if i == j { 1. } else { 0. }).abs() < 1e-7,
                "Nonrigid placement"
            );
        }
    }
    let config = xml::parse(archive::required(input, "Metadata/model_settings.config")?)?;
    let object = config
        .children
        .iter()
        .find(|n| n.is("object") && n.attrs.get("id").is_some_and(|v| v == id))
        .context("Missing print object")?;
    let meta = object
        .children
        .iter()
        .find(|n| n.is("part") && n.attrs.get("subtype").is_some_and(|v| v == "normal_part"))
        .context("Missing normal part")?
        .metadata();
    let offset = ["x", "y", "z"].map(|a| meta[&format!("source_offset_{a}")].parse().unwrap());
    Ok((m, offset))
}

fn feed(
    paths: &[gcode::Segment],
    object: u32,
    m: &[f64],
    offset: [f64; 3],
    zone: &print::Zone,
    range: [f64; 2],
) -> f64 {
    let mut total = 0.;
    for s in paths
        .iter()
        .filter(|s| s.object == object && s.feature.to_ascii_lowercase().contains("infill"))
    {
        let length = (s.b[0] - s.a[0]).hypot(s.b[1] - s.a[1]);
        let count = (length / 0.4).ceil().max(1.) as usize;
        for i in 0..count {
            let t = (i as f64 + 0.5) / count as f64;
            let q = [
                s.a[0] + t * (s.b[0] - s.a[0]) - (m[9] - 307.2),
                s.a[1] + t * (s.b[1] - s.a[1]) - m[10],
                s.z - m[11],
            ];
            let p = std::array::from_fn(|a| {
                (0..3).map(|k| m[3 * a + k] * q[k]).sum::<f64>() + offset[a]
            });
            if (range[0]..range[1]).contains(&p[1]) && zone.contains(p) {
                total += s.filament_feed_mm / count as f64;
            }
        }
    }
    total
}

fn section(
    input: &archive::Entries,
    path: &str,
    id: Option<&str>,
    offset: [f64; 3],
) -> Result<String> {
    let text = std::str::from_utf8(archive::required(input, path)?)?;
    let doc = roxmltree::Document::parse(text)?;
    let object = doc
        .descendants()
        .find(|n| {
            n.tag_name().name() == "object" && id.is_none_or(|id| n.attribute("id") == Some(id))
        })
        .context("Missing section mesh")?;
    let points = object
        .descendants()
        .filter(|n| n.tag_name().name() == "vertex")
        .map(|n| {
            let mut p = [0.; 3];
            for (i, a) in ["x", "y", "z"].iter().enumerate() {
                p[i] = n
                    .attribute(*a)
                    .context("Missing coordinate")?
                    .parse::<f64>()?
                    + offset[i];
            }
            Ok(p)
        })
        .collect::<Result<Vec<_>>>()?;
    let mut segments = Vec::new();
    for node in object
        .descendants()
        .filter(|n| n.tag_name().name() == "triangle")
    {
        let mut triangle = [[0.; 3]; 3];
        for (i, a) in ["v1", "v2", "v3"].iter().enumerate() {
            triangle[i] = points[node
                .attribute(*a)
                .context("Missing vertex index")?
                .parse::<usize>()?];
        }
        let mut cuts = Vec::new();
        for i in 0..3 {
            let (a, b) = (triangle[i], triangle[(i + 1) % 3]);
            let z = 0.017;
            if (a[2] - z) * (b[2] - z) < 0. {
                let t = (z - a[2]) / (b[2] - a[2]);
                cuts.push([a[1] + t * (b[1] - a[1]), a[0] + t * (b[0] - a[0])]);
            }
        }
        if cuts.len() == 2 {
            segments.push((cuts[0], cuts[1]));
        }
    }
    let key = |p: [f64; 2]| {
        [
            (p[0] * 10000.).round() as i64,
            (p[1] * 10000.).round() as i64,
        ]
    };
    let mut adjacency = std::collections::BTreeMap::<[i64; 2], Vec<usize>>::new();
    for (i, (a, b)) in segments.iter().enumerate() {
        if key(*a) != key(*b) {
            adjacency.entry(key(*a)).or_default().push(i);
            adjacency.entry(key(*b)).or_default().push(i);
        }
    }
    let mut used = vec![false; segments.len()];
    let mut result = String::new();
    for i in 0..segments.len() {
        if used[i] || key(segments[i].0) == key(segments[i].1) {
            continue;
        }
        let start = key(segments[i].0);
        let mut end = key(segments[i].1);
        used[i] = true;
        result.push_str(&format!(
            "M{:.4},{:.4}L{:.4},{:.4}",
            segments[i].0[0], -segments[i].0[1], segments[i].1[0], -segments[i].1[1]
        ));
        while end != start {
            let next = adjacency
                .get(&end)
                .and_then(|edges| edges.iter().find(|&&edge| !used[edge]))
                .copied()
                .context("Open manufacturing mesh section")?;
            used[next] = true;
            let (a, b) = segments[next];
            let p = if key(a) == end { b } else { a };
            end = key(p);
            result.push_str(&format!("L{:.4},{:.4}", p[0], -p[1]));
        }
        result.push('Z');
    }
    Ok(result)
}

fn polygon(points: &[[f64; 2]]) -> String {
    points
        .iter()
        .enumerate()
        .map(|(i, p)| format!("{}{:.3},{:.3}", if i == 0 { "M" } else { "L" }, p[0], -p[1]))
        .collect::<String>()
        + "Z"
}

fn diagram(
    input: &archive::Entries,
    reference: &archive::Entries,
    spec: &print::Spec,
) -> Result<String> {
    let mut svg = String::from(
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1000 540' style='background:#fff' role='img' aria-label='Continuous internal torque reinforcement and previous disconnected bands'><style>text{font-family:Arial;fill:#263746}.label{font-size:16px}.note{font-size:13px}</style><text x='20' y='26' font-size='21'>Follow the torque: servo hub → adapter peg → socket → shaft → flights</text><text x='20' y='50' class='note'>Gray: actual material section | Teal: 100% infill region | Dashed orange: previous regions</text>",
    );
    for (part, id, mesh, transform, label) in [
        (
            "PETG - One-piece auger",
            "8",
            "3D/Objects/object_3.model",
            "translate(390 142) scale(3.75)",
            "Auger: one connected region, tapered away over one 24 mm flight pitch",
        ),
        (
            "PETG - Square adapter",
            "6",
            "3D/Objects/object_4.model",
            "translate(-900 390) scale(7.5)",
            "Adapter: square peg connects to the servo hub",
        ),
    ] {
        let (_, offset) = placement(input, id)?;
        let material = section(input, mesh, None, offset)?;
        let zone = spec
            .zones
            .iter()
            .find(|z| z.part == part)
            .context("Missing diagram region")?;
        let (outer, inner) = zone.outline();
        svg.push_str(&format!("<g transform='{transform}'><path d='{material}' fill='#e5eaee' fill-rule='evenodd' stroke='#526575' stroke-width='.16'/><path d='{}{}' fill='#168b8b' fill-opacity='.75' fill-rule='evenodd'/>", polygon(&outer), polygon(&inner)));
        let config = xml::parse(archive::required(
            reference,
            "Metadata/model_settings.config",
        )?)?;
        let object = config
            .children
            .iter()
            .find(|n| n.is("object") && n.attrs.get("id").is_some_and(|v| v == id))
            .context("Missing reference object")?;
        for region in object.children.iter().filter(|n| {
            n.is("part") && n.attrs.get("subtype").is_some_and(|v| v == "modifier_part")
        }) {
            let outline = section(
                reference,
                "3D/Objects/local_reinforcement.model",
                Some(region.attr("id")?),
                offset,
            )?;
            svg.push_str(&format!("<path d='{outline}' fill='none' stroke='#ca6e27' stroke-width='.3' stroke-dasharray='1.2 .7'/>"));
        }
        svg.push_str("</g>");
        svg.push_str(&format!(
            "<text x='20' y='{}' class='label'>{label}</text>",
            if id == "8" { 235 } else { 270 }
        ));
    }
    svg.push_str("<text x='400' y='335' class='label'>A socket-shaped opening follows its loaded flats.</text><text x='400' y='360' class='note'>The shaft's low-radius center stays at 20% gyroid.</text><text x='400' y='382' class='note'>Three walls and the outer shape are unchanged.</text><text x='20' y='522' class='note'>Manufacturing mesh section at CAD Z0.017 mm; modifier outline at Z0. No new cavity or external rib is added. Physical strength still needs testing.</text></svg>");
    Ok(svg)
}

pub fn run(root: &Path, options: &Options) -> Result<()> {
    let (current, native) = job(&options.slice)?;
    let (reference, old_native) = job(&options.reference_slice)?;
    comparable(&current, &reference)?;
    let spec = print::load_spec(root)?;
    let mut rebuilt = print::build(current.clone(), &spec)?;
    print::invalidate(&mut rebuilt)?;
    ensure!(
        rebuilt == current,
        "Current slice does not match the current reinforcement specification"
    );
    let code = archive::required(&native, "Metadata/plate_2.gcode")?;
    let old_code = archive::required(&old_native, "Metadata/plate_2.gcode")?;
    let paths = gcode::paths(std::str::from_utf8(code)?)?;
    let old_paths = gcode::paths(std::str::from_utf8(old_code)?)?;
    let mut measurements = Vec::new();
    for (part, id, object, bands) in [
        (
            "PETG - One-piece auger",
            "8",
            108,
            vec![
                ("Shaft taper", [48., 72.]),
                ("Loaded shaft", [72., 104.]),
                ("Shoulder and journal", [104., 124.]),
                ("Socket floor transition", [124., 127.]),
                ("Socket walls", [127., 138.7]),
            ],
        ),
        (
            "PETG - Square adapter",
            "6",
            106,
            vec![
                ("Square drive peg", [130.3, 141.7]),
                ("Peg-to-hub transition", [141.7, 143.7]),
                ("Servo hub", [143.7, 151.6]),
            ],
        ),
    ] {
        let zone = spec
            .zones
            .iter()
            .find(|z| z.part == part)
            .context("Missing load-path region")?;
        let (m, offset) = placement(&current, id)?;
        for (name, range) in bands {
            let after = feed(&paths, object, &m, offset, zone, range);
            let before = feed(&old_paths, object, &m, offset, zone, range);
            measurements.push(json!({"part":part,"region":name,"CAD_Y_range_mm":range,"current_infill_feed_mm":after,"reference_infill_feed_mm":before,"ratio":if before>0.{Some(after/before)}else{None}}));
        }
    }
    let report = json!({"method":"Positive moving infill filament feed, including subdivided arcs; 0.4 mm midpoint sampling in CAD coordinates. This measures programmed feed, not physical strength or calibrated deposition.","identical_normal_meshes_placement_process_and_materials":true,"current_specification_matches_slice_input":true,"current_input_sha256":archive::sha(&fs::read(options.slice.join("input.3mf"))?),"reference_input_sha256":archive::sha(&fs::read(options.reference_slice.join("input.3mf"))?),"current_gcode_sha256":archive::sha(code),"reference_gcode_sha256":archive::sha(old_code),"measurements":measurements,"physical_strength_verified":false});
    fs::create_dir_all(&options.output)?;
    fs::write(
        options.output.join("summary.json"),
        serde_json::to_vec_pretty(&report)?,
    )?;
    fs::write(
        options.output.join("torque-paths.svg"),
        diagram(&current, &reference, &spec)?,
    )?;
    println!("{}", serde_json::to_string(&report)?);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn comparison_rejects_geometry_and_process_changes() -> Result<()> {
        let mut entries = archive::read(&crate::root().join("print/garden-auger.3mf"))?;
        let original = entries.clone();
        entries
            .get_mut("3D/Objects/object_3.model")
            .unwrap()
            .push(b' ');
        assert!(comparable(&entries, &original).is_err());
        entries = original.clone();
        entries
            .get_mut("Metadata/project_settings.config")
            .unwrap()
            .push(b' ');
        assert!(comparable(&entries, &original).is_err());
        comparable(&original, &original)?;
        Ok(())
    }
}
