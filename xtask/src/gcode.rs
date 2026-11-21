//! Native extrusion paths shared by manufacturing previews.
use anyhow::Result;
pub struct Segment {
    pub a: [f64; 2],
    pub b: [f64; 2],
    pub z: f64,
    pub object: u32,
    pub filament: usize,
    pub width: f64,
    pub feature: String,
}
pub fn paths(code: &str) -> Result<Vec<Segment>> {
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
