use crate::archive;
use anyhow::{Context, Result, ensure};
use serde::Deserialize;
use serde_json::Value;
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::Path,
};

const GRID: f64 = 0.8;
type MeshData = (Vec<[f64; 3]>, Vec<[usize; 3]>);

#[derive(Clone)]
pub struct Region {
    pub name: String,
    pub part: String,
    pub body_id: u64,
    pub filament: usize,
    pub surface: f64,
    pub points: Vec<[f64; 3]>,
    pub faces: Vec<[usize; 3]>,
}

/// A color-only mask with the same filament is merged away by Bambu. A local
/// surface pattern keeps the letter outlines in its toolpaths without relief.
pub fn print_settings(filament: usize) -> BTreeMap<String, String> {
    let mut settings = BTreeMap::from([("extruder".into(), filament.to_string())]);
    if filament == 1 {
        settings.insert("top_surface_pattern".into(), "concentric".into());
    }
    settings
}

#[derive(Deserialize)]
struct Settings {
    depth_mm: f64,
    filament: usize,
    regions: Vec<Definition>,
}
#[derive(Deserialize)]
struct Definition {
    name: String,
    part: String,
    body_id: u64,
    sketch_id: u64,
}

pub fn load(root: &Path) -> Result<Vec<Region>> {
    let settings: Settings = serde_json::from_slice(&fs::read(root.join("print/lettering.json"))?)?;
    ensure!(
        (settings.depth_mm - 0.72).abs() < 1e-9,
        "Lettering mask depth must be 0.72 mm"
    );
    ensure!(
        [1, 3].contains(&settings.filament),
        "Lettering uses the housing or gray PETG slot"
    );
    ensure!(
        settings.regions.len() == 2,
        "Both housing lettering regions are required"
    );
    let entries = archive::read(&root.join("garden-auger.limo"))?;
    let model: Value = serde_json::from_slice(archive::required(&entries, "model.json")?)?;
    settings
        .regions
        .into_iter()
        .map(|d| {
            ensure!(
                [(46, 395), (26, 397)].contains(&(d.body_id, d.sketch_id)),
                "Unexpected lettering attachment"
            );
            let s = model["sketches"]
                .as_array()
                .context("Missing sketches")?
                .iter()
                .find(|s| s["feature_id"] == d.sketch_id)
                .context("Lettering profile missing")?;
            let surface = s["basis"]["origin"][2]
                .as_f64()
                .context("Missing lettering plane")?;
            ensure!(
                (surface.abs() - 10.2).abs() < 1e-7,
                "Lettering must be flush with the pocket floor"
            );
            ensure!(
                s["basis"]["normal"] == serde_json::json!([0., 0., 1.]),
                "Lettering plane changed"
            );
            let (cells, origin) = cells(s)?;
            let inward = if surface < 0. {
                -settings.depth_mm
            } else {
                settings.depth_mm
            };
            let (points, faces) = mesh(
                &cells,
                origin,
                surface.min(surface + inward),
                surface.max(surface + inward),
            )?;
            Ok(Region {
                name: d.name,
                part: d.part,
                body_id: d.body_id,
                filament: settings.filament,
                surface,
                points,
                faces,
            })
        })
        .collect()
}

// The saved lettering is an orthogonal 0.8 mm stencil. Even/odd crossings preserve
// counters in letters such as A, B and R without filling their inner loops.
fn cells(sketch: &Value) -> Result<(BTreeSet<[i32; 2]>, [f64; 2])> {
    let entities = sketch["snapshot"]["entities"]
        .as_array()
        .context("Missing lettering entities")?;
    let mut points = BTreeMap::new();
    for e in entities.iter().filter(|e| e[1]["type"] == "point") {
        points.insert(
            e[0].as_u64().context("Invalid point ID")?,
            [
                e[1]["position"]["x"]
                    .as_f64()
                    .context("Invalid lettering point")?,
                e[1]["position"]["y"]
                    .as_f64()
                    .context("Invalid lettering point")?,
            ],
        );
    }
    ensure!(!points.is_empty(), "Empty lettering");
    let lo: [f64; 2] =
        std::array::from_fn(|i| points.values().map(|p| p[i]).fold(f64::INFINITY, f64::min));
    let hi: [f64; 2] = std::array::from_fn(|i| {
        points
            .values()
            .map(|p| p[i])
            .fold(f64::NEG_INFINITY, f64::max)
    });
    ensure!(
        lo[0] >= -29.9 && hi[0] <= 9.4 + 1e-7 && lo[1] >= 152.7 && hi[1] <= 193. + 1e-7,
        "Lettering exceeds its pocket margin"
    );
    for p in points.values() {
        for i in 0..2 {
            let q = (p[i] - lo[i]) / GRID;
            ensure!(
                (q - q.round()).abs() < 1e-6,
                "Lettering is off the 0.8 mm grid"
            );
        }
    }
    let mut edges = Vec::new();
    let mut degree = BTreeMap::<u64, usize>::new();
    for e in entities.iter().filter(|e| e[1]["type"] == "line") {
        let a = e[1]["start"].as_u64().context("Missing line start")?;
        let b = e[1]["end"].as_u64().context("Missing line end")?;
        let (p, q) = (
            *points.get(&a).context("Missing point")?,
            *points.get(&b).context("Missing point")?,
        );
        ensure!(
            (p[0] - q[0]).abs() < 1e-7 || (p[1] - q[1]).abs() < 1e-7,
            "Nonorthogonal lettering edge"
        );
        *degree.entry(a).or_default() += 1;
        *degree.entry(b).or_default() += 1;
        edges.push((p, q));
    }
    ensure!(
        degree.len() == points.len() && degree.values().all(|&n| n == 2),
        "Lettering loops must be closed"
    );
    let nx = ((hi[0] - lo[0]) / GRID).round() as i32;
    let ny = ((hi[1] - lo[1]) / GRID).round() as i32;
    ensure!(
        nx > 0 && ny > 0 && nx * ny <= 4096,
        "Invalid lettering grid bounds"
    );
    let mut cells = BTreeSet::new();
    for x in 0..nx {
        for y in 0..ny {
            let p = [
                lo[0] + (x as f64 + 0.5) * GRID,
                lo[1] + (y as f64 + 0.5) * GRID,
            ];
            let crossings = edges
                .iter()
                .filter(|(a, b)| {
                    (a[1] > p[1]) != (b[1] > p[1])
                        && p[0] < a[0] + (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1])
                })
                .count();
            if crossings % 2 == 1 {
                cells.insert([x, y]);
            }
        }
    }
    ensure!(!cells.is_empty(), "No solid lettering cells");
    Ok((cells, lo))
}

fn mesh(cells: &BTreeSet<[i32; 2]>, origin: [f64; 2], lo: f64, hi: f64) -> Result<MeshData> {
    let mut points = Vec::new();
    let mut faces = Vec::new();
    let mut ids = BTreeMap::new();
    for &[x, y] in cells {
        let mut v = [0; 8];
        for (i, (dx, dy, z)) in [
            (0, 0, 0),
            (1, 0, 0),
            (1, 1, 0),
            (0, 1, 0),
            (0, 0, 1),
            (1, 0, 1),
            (1, 1, 1),
            (0, 1, 1),
        ]
        .into_iter()
        .enumerate()
        {
            let (vx, vy) = (x + dx, y + dy);
            let adjacent = [[vx - 1, vy - 1], [vx, vy - 1], [vx - 1, vy], [vx, vy]];
            let bits = adjacent
                .iter()
                .enumerate()
                .fold(0, |bits, (i, p)| bits | ((cells.contains(p) as u8) << i));
            // Keep diagonally touching ink islands topologically separate.
            let island = if bits == 0b1001 || bits == 0b0110 {
                1 + adjacent.iter().position(|&p| p == [x, y]).unwrap()
            } else {
                0
            };
            v[i] = *ids.entry((vx, vy, z, island)).or_insert_with(|| {
                let i = points.len();
                points.push([
                    origin[0] + vx as f64 * GRID,
                    origin[1] + vy as f64 * GRID,
                    if z == 0 { lo } else { hi },
                ]);
                i
            });
        }
        for [a, b, c] in [[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7]] {
            faces.push([v[a], v[b], v[c]]);
        }
        for (neighbour, quad) in [
            ([x, y - 1], [0, 1, 5, 4]),
            ([x + 1, y], [1, 2, 6, 5]),
            ([x, y + 1], [2, 3, 7, 6]),
            ([x - 1, y], [3, 0, 4, 7]),
        ] {
            if !cells.contains(&neighbour) {
                let [a, b, c, d] = quad.map(|i| v[i]);
                faces.extend([[a, b, c], [a, c, d]]);
            }
        }
    }
    let mut edges = BTreeMap::<(usize, usize), (usize, i32)>::new();
    for f in &faces {
        for (a, b) in [(f[0], f[1]), (f[1], f[2]), (f[2], f[0])] {
            let e = edges.entry((a.min(b), a.max(b))).or_default();
            e.0 += 1;
            e.1 += if a < b { 1 } else { -1 };
        }
    }
    ensure!(
        edges.values().all(|&(n, w)| n == 2 && w == 0),
        "Lettering mask is not a closed oriented mesh"
    );
    Ok((points, faces))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn stencil_counters_are_not_filled_and_open_loops_fail() -> Result<()> {
        let mut entities = Vec::new();
        for (base, lo, hi) in [
            (1, [-29., 166.], [-26.6, 168.4]),
            (9, [-28.2, 166.8], [-27.4, 167.6]),
        ] {
            for (i, p) in [
                [lo[0], lo[1]],
                [hi[0], lo[1]],
                [hi[0], hi[1]],
                [lo[0], hi[1]],
            ]
            .into_iter()
            .enumerate()
            {
                entities.push(
                    serde_json::json!([base+i,{"type":"point","position":{"x":p[0],"y":p[1]}}]),
                );
                entities.push(
                    serde_json::json!([base+4+i,{"type":"line","start":base+i,"end":base+(i+1)%4}]),
                );
            }
        }
        let mut s = serde_json::json!({"snapshot":{"entities":entities}});
        let (ink, _) = cells(&s)?;
        assert_eq!(ink.len(), 8);
        assert!(!ink.contains(&[1, 1]));
        s["snapshot"]["entities"].as_array_mut().unwrap().pop();
        assert!(cells(&s).is_err());
        Ok(())
    }
    #[test]
    fn holes_and_diagonally_touching_ink_remain_manifold() -> Result<()> {
        let mut cells: BTreeSet<_> = (0..3).flat_map(|x| (0..3).map(move |y| [x, y])).collect();
        cells.remove(&[1, 1]);
        for cells in [cells, BTreeSet::from([[0, 0], [1, 1]])] {
            let (p, f) = mesh(&cells, [0., 0.], 0., 0.72)?;
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
            assert!((volume - cells.len() as f64 * GRID * GRID * 0.72).abs() < 1e-9);
        }
        Ok(())
    }
    #[test]
    fn current_lettering_uses_two_flush_petg_masks() -> Result<()> {
        let regions = load(&crate::root())?;
        assert_eq!(regions.len(), 2);
        for r in regions {
            assert!([1, 3].contains(&r.filament));
            assert!(r.points.len() > 100);
            assert!(
                r.points
                    .iter()
                    .all(|p| p[2].abs() >= 10.2 - 1e-8 && p[2].abs() <= 10.92 + 1e-8)
            );
        }
        Ok(())
    }
}
