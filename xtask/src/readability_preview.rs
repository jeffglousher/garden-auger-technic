//! Native extrusion path diagrams, deliberately not a photograph of printed PETG.
use super::{Label, coupons};
use anyhow::{Context, Result, ensure};
use serde_json::Value;
use std::{fs, path::Path};

struct Segment {
    a: [f64; 2],
    b: [f64; 2],
    z: f64,
    object: u32,
    filament: usize,
    width: f64,
    feature: String,
}
fn paths(code: &str) -> Result<Vec<Segment>> {
    let (mut xy, mut z, mut object, mut filament, mut relative, mut previous_e) =
        ([0.; 2], 0., 0, 0, true, 0.);
    let mut feature = "";
    let mut width = 0.42;
    let mut segments = vec![];
    for line in code.lines() {
        if let Some(v) = line.strip_prefix("; LINE_WIDTH: ") {
            width = v.parse()?;
            continue;
        }
        if let Some(v) = line.strip_prefix("; Z_HEIGHT: ") {
            z = v.parse()?;
            continue;
        }
        if let Some(v) = line.strip_prefix("; FEATURE: ") {
            feature = v;
            continue;
        }
        if let Some(v) = line.strip_prefix("; start printing object, unique label id: ") {
            object = v.parse()?;
            continue;
        }
        if line.starts_with("; stop printing object") {
            object = 0;
            continue;
        }
        let mut words = line.split(';').next().unwrap_or("").split_whitespace();
        let Some(cmd) = words.next() else { continue };
        if let Some(t) = cmd.strip_prefix('T').and_then(|v| v.parse::<usize>().ok()) {
            filament = t;
            continue;
        }
        if cmd == "M83" {
            relative = true;
            continue;
        }
        if cmd == "M82" {
            relative = false;
            continue;
        }
        if cmd == "G92" {
            for word in words {
                if let Some(e) = word.strip_prefix('E') {
                    previous_e = e.parse()?;
                }
            }
            continue;
        }
        if !["G0", "G1", "G2", "G3"].contains(&cmd) {
            continue;
        }
        let (mut end, mut e, mut ij, mut moved) = (xy, 0., [0.; 2], false);
        for word in words {
            if word.len() < 2 {
                continue;
            }
            let Ok(v) = word[1..].parse::<f64>() else {
                continue;
            };
            match &word[..1] {
                "X" => {
                    end[0] = v;
                    moved = true
                }
                "Y" => {
                    end[1] = v;
                    moved = true
                }
                "E" => {
                    e = if relative { v } else { v - previous_e };
                    previous_e = v
                }
                "I" => ij[0] = v,
                "J" => ij[1] = v,
                _ => {}
            }
        }
        if object > 0 && e > 0. && feature != "Custom" && (moved || cmd == "G2" || cmd == "G3") {
            let mut points = vec![end];
            if ["G2", "G3"].contains(&cmd) && ij != [0., 0.] {
                let c = [xy[0] + ij[0], xy[1] + ij[1]];
                let r = ij[0].hypot(ij[1]);
                let a = (xy[1] - c[1]).atan2(xy[0] - c[0]);
                let b = (end[1] - c[1]).atan2(end[0] - c[0]);
                let mut sweep = (b - a).rem_euclid(std::f64::consts::TAU);
                if cmd == "G2" {
                    sweep -= std::f64::consts::TAU
                } else if sweep.abs() < 1e-8 {
                    sweep = std::f64::consts::TAU
                }
                let n = (r * sweep.abs() / 0.05).ceil().max(1.) as usize;
                points = (1..=n)
                    .map(|i| {
                        if i == n {
                            end
                        } else {
                            let t = a + sweep * i as f64 / n as f64;
                            [c[0] + r * t.cos(), c[1] + r * t.sin()]
                        }
                    })
                    .collect();
            }
            let mut a = xy;
            for b in points {
                segments.push(Segment {
                    a,
                    b,
                    z,
                    object,
                    filament,
                    width,
                    feature: feature.into(),
                });
                a = b;
            }
        }
        xy = end;
    }
    Ok(segments)
}

pub(super) fn write(
    out: &Path,
    bases: &[coupons::Coupon],
    labels: &[Label],
    summaries: &[Value],
) -> Result<()> {
    let mut body = String::from(
        "<h2>Heavy lettering for a 0.4 mm nozzle</h2><p>Real curved outlines, 1.2 mm clear gaps between characters. Left: 7 mm capitals. Right: 8 mm capitals. Both stay nominally flush.</p>",
    );
    for (i, (mode, title)) in [
        ("ams", "AMS · contrasting PETG"),
        ("single-color", "Single color · PETG texture"),
    ]
    .into_iter()
    .enumerate()
    {
        let code = fs::read_to_string(out.join(mode).join("plate_1.gcode"))?;
        let all = paths(&code)?;
        let mut svg = String::from(
            "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 51' style='background:#fff;color:#293542;font-family:Arial,sans-serif' role='img' aria-label='Actual native sliced surface paths for two lettering coupons'>",
        );
        for (j, (c, l)) in bases.iter().zip(labels).enumerate() {
            let object = 102 + j as u32 * 2;
            let top = all
                .iter()
                .filter(|s| s.object == object)
                .map(|s| s.z)
                .reduce(f64::max)
                .context("Missing coupon extrusion")?;
            let selected: Vec<_> = all
                .iter()
                .filter(|s| s.object == object && (s.z - top).abs() < 0.01)
                .collect();
            ensure!(selected.len() > 100, "Missing text surface paths");
            let x = j as f64 * 52.;
            let heading = format!("{} mm caps", l.cap);
            svg.push_str(&format!("<g transform='translate({x},6)'><text x='0' y='-2' font-size='3' fill='currentColor'>{heading}</text>"));
            let mut groups = std::collections::BTreeMap::<(usize, i64), String>::new();
            for s in selected.iter().filter(|s| s.feature != "Ironing") {
                let d = groups
                    .entry((s.filament, (s.width * 10000.).round() as i64))
                    .or_default();
                let a = [s.a[0] - c.origin[0], c.size[1] - (s.a[1] - c.origin[1])];
                let b = [s.b[0] - c.origin[0], c.size[1] - (s.b[1] - c.origin[1])];
                d.push_str(&format!("M{:.3},{:.3}L{:.3},{:.3}", a[0], a[1], b[0], b[1]));
            }
            for ((filament, width), d) in groups {
                let color = if mode == "single-color" {
                    "#9c7350"
                } else if filament == 2 {
                    "#194da7"
                } else {
                    "#e58330"
                };
                svg.push_str(&format!("<path d='{d}' fill='none' stroke='{color}' stroke-width='{}' stroke-linecap='round'/>",width as f64/10000.));
            }
            svg.push_str(&format!("<text x='0' y='{:.2}' font-size='2.5' fill='currentColor'>{:.1} × {:.1} mm</text></g>",c.size[1]+4.,c.size[0],c.size[1]));
        }
        svg.push_str("</svg>");
        fs::write(out.join(format!("{mode}-surface-paths.svg")), &svg)?;
        let image = out
            .join(format!("{mode}-surface-paths.svg"))
            .to_string_lossy()
            .replace('\\', "/");
        body.push_str(&format!("<section><h3>{title}</h3><img src='{image}' alt='Native surface paths for two lettering coupons'><p class='small'>Native slice: about {} min · {:.1} g. {}</p></section>",(summaries[i]["seconds"].as_f64().unwrap()/60.).round(),summaries[i]["grams"].as_f64().unwrap(),if mode=="ams"{"Orange base with blue letter paths. Map both to PETG."}else{"One filament only. Path direction defines the letters; physical contrast depends on lighting."}));
    }
    body.push_str("<p class='small'>Nominal bead-width footprints from Bambu Studio, not photos or a prediction of PETG reflection. These use each path's programmed width. Five top layers, normal top-surface flow and ironing off. No engraving, raised text, supports, brim or tower. Physical finish still needs a print.</p>");
    let html = format!(
        "<!doctype html><html><head><meta charset='utf-8'><style>body{{font-family:var(--font-sans);color:var(--foreground)}}h2{{font-size:22px;margin:0 0 8px}}h3{{font-size:17px;margin:0 0 12px}}p{{line-height:1.5;margin:8px 0 16px}}section{{padding:16px;border:1px solid var(--border);border-radius:var(--radius);margin:16px 0}}img{{width:100%;height:auto;display:block}}.small{{font-size:13px;color:var(--foreground);opacity:.75;margin-bottom:0}}</style></head><body>{body}</body></html>"
    );
    fs::write(out.join("preview.html"), html)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn surface_diagrams_follow_curves_and_exclude_travel() -> Result<()> {
        let p = paths(
            "M83\n; Z_HEIGHT: 2.84\n; FEATURE: Top surface\n; start printing object, unique label id: 102\nG1 X1 Y0\nG3 X0 Y1 I-1 J0 E1\nG1 X0 Y2 E-1\n; stop printing object\nG1 X10 Y10 E2\n",
        )?;
        ensure!(
            p.len() > 20
                && p.iter()
                    .all(|s| s.object == 102 && (s.z - 2.84).abs() < 1e-8),
            "Bad arc/travel filtering"
        );
        ensure!(p.last().unwrap().b == [0., 1.], "Wrong arc end");
        Ok(())
    }
}
