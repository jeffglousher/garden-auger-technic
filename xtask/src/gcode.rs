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
    pub filament_feed_mm: f64,
}
pub fn paths(code: &str) -> Result<Vec<Segment>> {
    let (mut xy, mut z, mut object, mut filament, mut relative, mut previous_e) =
        ([0.; 2], 0., 0, 0, true, 0.);
    let mut feature = "";
    let mut width = 0.42;
    let mut segments = vec![];
    for line in code.lines() {
        // Bambu initializes the preview tool with this virtual-tool marker; a T command
        // need not appear before the first object's extrusion.
        if let Some(tool) = line
            .strip_prefix(";VT")
            .and_then(|v| v.split_whitespace().next())
        {
            filament = tool.parse()?;
            continue;
        }
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
                    previous_e = if relative { previous_e + v } else { v }
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
            let lengths: Vec<_> = points
                .iter()
                .map(|b| {
                    let length = (b[0] - a[0]).hypot(b[1] - a[1]);
                    a = *b;
                    length
                })
                .collect();
            let total: f64 = lengths.iter().sum();
            a = xy;
            for (b, length) in points.into_iter().zip(lengths) {
                if length < 1e-10 {
                    continue;
                }
                segments.push(Segment {
                    a,
                    b,
                    z,
                    object,
                    filament,
                    width,
                    feature: feature.into(),
                    filament_feed_mm: e * length / total,
                });
                a = b;
            }
        }
        xy = end;
    }
    Ok(segments)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn feed_is_conserved_across_arcs_and_extrusion_modes() -> Result<()> {
        let code = "M83\n; start printing object, unique label id: 108\n; FEATURE: Sparse infill\nG1 X10 E2\nG2 X20 I5 E3\nM82\nG1 X21 E6\nG92 E0\nG1 X22 E1\nG1 E0.5\n";
        let segments = paths(code)?;
        let feed: f64 = segments.iter().map(|s| s.filament_feed_mm).sum();
        assert!((feed - 7.).abs() < 1e-9);
        assert!(segments.len() > 100);
        assert!(segments.iter().all(|s| s.filament_feed_mm > 0.));
        Ok(())
    }
    #[test]
    fn virtual_initial_tool_and_tool_changes_apply_to_moving_extrusion_only() -> Result<()> {
        let code = ";VT2 H-1\nM83\n; start printing object, unique label id: 106\n; FEATURE: Outer wall\nG1 X10 E1\n; stop printing object\nT4 H-1\nG1 X20 E1\n; start printing object, unique label id: 108\nG1 E.4\n; FEATURE: Support interface\nG1 X21 E1\n";
        let paths = paths(code)?;
        assert_eq!(paths.len(), 2);
        assert_eq!((paths[0].object, paths[0].filament), (106, 2));
        assert_eq!((paths[1].object, paths[1].filament), (108, 4));
        Ok(())
    }
}
