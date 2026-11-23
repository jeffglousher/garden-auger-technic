//! Contained infill regions in CAD definition coordinates.
use anyhow::{Result, ensure};
use serde::Deserialize;

#[derive(Deserialize)]
pub struct Zone {
    pub part: String,
    pub name: String,
    pub center_mm: [f64; 3],
    pub axis: String,
    #[serde(flatten)]
    pub shape: Shape,
}

#[derive(Deserialize)]
#[serde(untagged)]
pub enum Shape {
    Profile {
        profile: Vec<Section>,
        #[serde(default)]
        inner_square: Option<RoundedSquare>,
    },
    Annulus {
        radius_mm: f64,
        inner_radius_mm: f64,
        height_mm: f64,
    },
}

#[derive(Clone, Copy, Deserialize)]
pub struct Section {
    /// Axial position relative to center_mm, positive along the named CAD axis.
    pub position_mm: f64,
    pub radius_mm: f64,
    pub inner_radius_mm: f64,
    #[serde(default)]
    pub square_blend: f64,
}

#[derive(Deserialize)]
pub struct RoundedSquare {
    pub half_width_mm: f64,
    pub corner_radius_mm: f64,
}

impl RoundedSquare {
    fn radius(&self, angle: f64) -> f64 {
        let x = angle.cos().abs();
        let y = angle.sin().abs();
        let flat = self.half_width_mm / x.max(y);
        let c = self.half_width_mm - self.corner_radius_mm;
        if flat * x.min(y) <= c {
            flat
        } else {
            let projection = c * (x + y);
            projection
                + (projection.powi(2) - 2. * c * c + self.corner_radius_mm.powi(2))
                    .max(0.)
                    .sqrt()
        }
    }
}

impl Zone {
    /// Longitudinal modifier outline; its unfilled center remains ordinary infill.
    pub fn outline(&self) -> (Vec<[f64; 2]>, Vec<[f64; 2]>) {
        let sections = self.sections();
        let outer = sections
            .iter()
            .map(|s| [s.position_mm, s.radius_mm])
            .chain(sections.iter().rev().map(|s| [s.position_mm, -s.radius_mm]))
            .collect();
        let inner = sections
            .iter()
            .map(|s| [s.position_mm, self.inner(*s, 0.)])
            .chain(
                sections
                    .iter()
                    .rev()
                    .map(|s| [s.position_mm, -self.inner(*s, 0.)]),
            )
            .collect();
        (outer, inner)
    }

    fn sections(&self) -> Vec<Section> {
        match &self.shape {
            Shape::Profile { profile, .. } => profile.clone(),
            Shape::Annulus {
                radius_mm,
                inner_radius_mm,
                height_mm,
            } => [-height_mm / 2., height_mm / 2.]
                .map(|position_mm| Section {
                    position_mm,
                    radius_mm: *radius_mm,
                    inner_radius_mm: *inner_radius_mm,
                    square_blend: 0.,
                })
                .to_vec(),
        }
    }

    fn inner(&self, section: Section, angle: f64) -> f64 {
        let square = match &self.shape {
            Shape::Profile {
                inner_square: Some(square),
                ..
            } => square.radius(angle),
            _ => section.inner_radius_mm,
        };
        section.inner_radius_mm * (1. - section.square_blend) + square * section.square_blend
    }

    pub fn validate(&self) -> Result<()> {
        ensure!(
            self.center_mm.iter().all(|x| x.is_finite())
                && ["y", "z"].contains(&self.axis.as_str()),
            "Invalid region axis/center: {}",
            self.name
        );
        let sections = self.sections();
        ensure!(
            (2..=128).contains(&sections.len()),
            "Invalid profile section count: {}",
            self.name
        );
        if let Shape::Profile {
            inner_square: Some(square),
            ..
        } = &self.shape
        {
            ensure!(
                square.half_width_mm.is_finite()
                    && square.corner_radius_mm.is_finite()
                    && square.corner_radius_mm > 0.
                    && square.corner_radius_mm <= square.half_width_mm,
                "Invalid rounded-square opening"
            );
        }
        for pair in sections.windows(2) {
            ensure!(
                pair[0].position_mm < pair[1].position_mm,
                "Region sections must increase along the axis: {}",
                self.name
            );
        }
        for section in sections {
            ensure!(
                [
                    section.position_mm,
                    section.radius_mm,
                    section.inner_radius_mm,
                    section.square_blend
                ]
                .iter()
                .all(|x| x.is_finite())
                    && section.inner_radius_mm > 0.
                    && (0. ..=1.).contains(&section.square_blend),
                "Invalid region dimensions: {}",
                self.name
            );
            ensure!(
                section.square_blend == 0.
                    || matches!(
                        &self.shape,
                        Shape::Profile {
                            inner_square: Some(_),
                            ..
                        }
                    ),
                "Square blend requires an opening profile"
            );
            for i in 0..64 {
                ensure!(
                    self.inner(section, i as f64 * std::f64::consts::TAU / 64.) < section.radius_mm,
                    "Region opening crosses its outer boundary: {}",
                    self.name
                );
            }
        }
        Ok(())
    }

    pub fn contains(&self, point: [f64; 3]) -> bool {
        let q: [f64; 3] = std::array::from_fn(|i| point[i] - self.center_mm[i]);
        let (position, x, y) = if self.axis == "y" {
            (q[1], q[0], -q[2])
        } else {
            (q[2], q[0], q[1])
        };
        let sections = self.sections();
        for pair in sections.windows(2) {
            let [a, b] = [pair[0], pair[1]];
            if (a.position_mm..=b.position_mm).contains(&position) {
                let t = (position - a.position_mm) / (b.position_mm - a.position_mm);
                let angle = y.atan2(x);
                let inner = self.inner(a, angle) * (1. - t) + self.inner(b, angle) * t;
                let outer = a.radius_mm * (1. - t) + b.radius_mm * t;
                return (inner..=outer).contains(&x.hypot(y));
            }
        }
        false
    }

    pub fn mesh(&self, offset: [f64; 3]) -> (Vec<[f64; 3]>, Vec<[usize; 3]>) {
        let n = if matches!(self.shape, Shape::Annulus { .. }) {
            48
        } else {
            64
        };
        let sections = self.sections();
        let rings = sections.len();
        let mut points = Vec::new();
        for inner in [false, true] {
            for &section in &sections {
                for i in 0..n {
                    let angle = i as f64 * std::f64::consts::TAU / n as f64;
                    let r = if inner {
                        self.inner(section, angle)
                    } else {
                        section.radius_mm
                    };
                    let mut p = [r * angle.cos(), r * angle.sin(), section.position_mm];
                    if self.axis == "y" {
                        p = [p[0], p[2], -p[1]];
                    }
                    points.push(std::array::from_fn(|a| {
                        p[a] + self.center_mm[a] - offset[a]
                    }));
                }
            }
        }
        let mut faces = Vec::new();
        let hole = rings * n;
        for k in 0..rings - 1 {
            for i in 0..n {
                let j = (i + 1) % n;
                let a = k * n + i;
                let b = k * n + j;
                let c = (k + 1) * n + j;
                let d = (k + 1) * n + i;
                faces.extend([
                    [a, b, c],
                    [a, c, d],
                    [hole + a, hole + c, hole + b],
                    [hole + a, hole + d, hole + c],
                ]);
            }
        }
        for i in 0..n {
            let j = (i + 1) % n;
            faces.extend([[i, hole + j, j], [i, hole + i, hole + j]]);
            let top = (rings - 1) * n;
            faces.extend([
                [top + i, top + j, hole + top + j],
                [top + i, hole + top + j, hole + top + i],
            ]);
        }
        (points, faces)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn tapered_load_path_is_closed_and_keeps_the_square_socket_open() -> Result<()> {
        let zone: Zone = serde_json::from_value(
            serde_json::json!({"part":"test","name":"load path","center_mm":[0,0,0],"axis":"y","inner_square":{"half_width_mm":7.9,"corner_radius_mm":1.9},"profile":[{"position_mm":0,"radius_mm":4,"inner_radius_mm":3},{"position_mm":24,"radius_mm":11,"inner_radius_mm":3},{"position_mm":30,"radius_mm":13,"inner_radius_mm":3,"square_blend":1},{"position_mm":42,"radius_mm":13,"inner_radius_mm":3,"square_blend":1}]}),
        )?;
        zone.validate()?;
        assert!(zone.contains([3.5, 0., 0.]));
        assert!(zone.contains([8.2, 36., 0.]));
        assert!(!zone.contains([7.7, 36., 0.]));
        assert!(!zone.contains([7.2, 36., 7.2]));
        let (points, faces) = zone.mesh([0.; 3]);
        let mut edges = std::collections::BTreeMap::new();
        let mut volume = 0.;
        for face in faces {
            let [a, b, c] = face.map(|i| points[i]);
            volume += (a[0] * (b[1] * c[2] - b[2] * c[1])
                + a[1] * (b[2] * c[0] - b[0] * c[2])
                + a[2] * (b[0] * c[1] - b[1] * c[0]))
                / 6.;
            for i in 0..3 {
                let (a, b) = (face[i], face[(i + 1) % 3]);
                let v = edges.entry((a.min(b), a.max(b))).or_insert((0, 0));
                v.0 += 1;
                v.1 += if a < b { 1 } else { -1 };
            }
        }
        assert!(volume > 0.);
        assert!(edges.values().all(|v| *v == (2, 0)));
        Ok(())
    }
}
