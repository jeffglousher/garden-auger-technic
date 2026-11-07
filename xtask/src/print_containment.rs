use anyhow::{Result, ensure};

type Point = [f64; 3];
type Triangle = [Point; 3];

pub struct Mesh {
    pub points: Vec<Point>,
    pub faces: Vec<[usize; 3]>,
}

impl Mesh {
    fn triangles(&self) -> impl Iterator<Item = Triangle> + '_ {
        self.faces.iter().map(|face| face.map(|i| self.points[i]))
    }

    fn contains(&self, point: Point) -> bool {
        // An oblique ray avoids the model's axis-aligned edges. Deduplicate shared edges.
        let direction = [1., 0.432353, 0.173397];
        let mut hits: Vec<_> = self
            .triangles()
            .filter_map(|triangle| ray(point, direction, triangle))
            .filter(|&distance| distance > 1e-8)
            .collect();
        hits.sort_by(f64::total_cmp);
        hits.dedup_by(|a, b| (*a - *b).abs() < 1e-7);
        hits.len() % 2 == 1
    }
}

/// Check the complete triangulated boundaries, including holes and chamfers.
/// Separated boundaries plus the two inside tests also reject an enclosed parent void.
pub fn verify(modifier: &Mesh, parent: &Mesh, clearance: f64) -> Result<()> {
    ensure!(
        parent.contains(modifier.points[0]),
        "Reinforcement is outside its part"
    );
    let bounds = bounds(&modifier.points);
    let nearby: Vec<_> = parent
        .triangles()
        .filter(|triangle| boxes_near(bounds, self::bounds(triangle), clearance))
        .collect();
    for triangle in modifier.triangles() {
        let local = self::bounds(&triangle);
        for &other in &nearby {
            if boxes_near(local, self::bounds(&other), clearance) {
                ensure!(
                    triangle_distance_squared(triangle, other) >= clearance.powi(2) - 1e-10,
                    "Reinforcement must stay at least {clearance} mm inside every part surface"
                );
            }
        }
    }
    for &point in &parent.points {
        if (0..3).all(|a| point[a] > bounds[0][a] && point[a] < bounds[1][a]) {
            ensure!(
                !modifier.contains(point),
                "Reinforcement encloses a part void"
            );
        }
    }
    Ok(())
}

fn bounds(points: &[Point]) -> [Point; 2] {
    std::array::from_fn(|side| {
        std::array::from_fn(|a| {
            points.iter().map(|p| p[a]).fold(
                if side == 0 {
                    f64::INFINITY
                } else {
                    f64::NEG_INFINITY
                },
                if side == 0 { f64::min } else { f64::max },
            )
        })
    })
}

fn boxes_near(a: [Point; 2], b: [Point; 2], gap: f64) -> bool {
    (0..3).all(|i| a[0][i] <= b[1][i] + gap && b[0][i] <= a[1][i] + gap)
}

fn sub(a: Point, b: Point) -> Point {
    std::array::from_fn(|i| a[i] - b[i])
}
fn add(a: Point, b: Point) -> Point {
    std::array::from_fn(|i| a[i] + b[i])
}
fn scale(a: Point, t: f64) -> Point {
    a.map(|x| x * t)
}
fn dot(a: Point, b: Point) -> f64 {
    a.into_iter().zip(b).map(|(x, y)| x * y).sum()
}
fn cross(a: Point, b: Point) -> Point {
    [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]
}

fn ray(origin: Point, direction: Point, [a, b, c]: Triangle) -> Option<f64> {
    let e1 = sub(b, a);
    let e2 = sub(c, a);
    let h = cross(direction, e2);
    let determinant = dot(e1, h);
    if determinant.abs() < 1e-12 {
        return None;
    }
    let s = sub(origin, a);
    let u = dot(s, h) / determinant;
    let q = cross(s, e1);
    let v = dot(direction, q) / determinant;
    if u < -1e-10 || v < -1e-10 || u + v > 1. + 1e-10 {
        return None;
    }
    Some(dot(e2, q) / determinant)
}

fn point_triangle(p: Point, [a, b, c]: Triangle) -> f64 {
    let ab = sub(b, a);
    let ac = sub(c, a);
    let ap = sub(p, a);
    let d1 = dot(ab, ap);
    let d2 = dot(ac, ap);
    if d1 <= 0. && d2 <= 0. {
        return dot(ap, ap);
    }
    let bp = sub(p, b);
    let d3 = dot(ab, bp);
    let d4 = dot(ac, bp);
    if d3 >= 0. && d4 <= d3 {
        return dot(bp, bp);
    }
    let vc = d1 * d4 - d3 * d2;
    if vc <= 0. && d1 >= 0. && d3 <= 0. {
        let v = sub(p, add(a, scale(ab, d1 / (d1 - d3))));
        return dot(v, v);
    }
    let cp = sub(p, c);
    let d5 = dot(ab, cp);
    let d6 = dot(ac, cp);
    if d6 >= 0. && d5 <= d6 {
        return dot(cp, cp);
    }
    let vb = d5 * d2 - d1 * d6;
    if vb <= 0. && d2 >= 0. && d6 <= 0. {
        let v = sub(p, add(a, scale(ac, d2 / (d2 - d6))));
        return dot(v, v);
    }
    let va = d3 * d6 - d5 * d4;
    if va <= 0. && d4 - d3 >= 0. && d5 - d6 >= 0. {
        let v = sub(
            p,
            add(b, scale(sub(c, b), (d4 - d3) / ((d4 - d3) + (d5 - d6)))),
        );
        return dot(v, v);
    }
    let n = cross(ab, ac);
    dot(ap, n).powi(2) / dot(n, n)
}

fn segment_distance(p: Point, q: Point, r: Point, s: Point) -> f64 {
    let d1 = sub(q, p);
    let d2 = sub(s, r);
    let offset = sub(p, r);
    let a = dot(d1, d1);
    let e = dot(d2, d2);
    let b = dot(d1, d2);
    let c = dot(d1, offset);
    let f = dot(d2, offset);
    let denominator = a * e - b * b;
    let mut u = if denominator > 1e-16 {
        (b * f - c * e) / denominator
    } else {
        0.
    }
    .clamp(0., 1.);
    let mut v = (b * u + f) / e;
    if v < 0. {
        v = 0.;
        u = (-c / a).clamp(0., 1.);
    } else if v > 1. {
        v = 1.;
        u = ((b - c) / a).clamp(0., 1.);
    }
    let delta = sub(add(p, scale(d1, u)), add(r, scale(d2, v)));
    dot(delta, delta)
}

fn triangle_distance_squared(a: Triangle, b: Triangle) -> f64 {
    let mut distance = f64::INFINITY;
    for i in 0..3 {
        for (triangle, other) in [(a, b), (b, a)] {
            let direction = sub(triangle[(i + 1) % 3], triangle[i]);
            if ray(triangle[i], direction, other)
                .is_some_and(|t| (-1e-10..=1. + 1e-10).contains(&t))
            {
                return 0.;
            }
            distance = distance.min(point_triangle(triangle[i], other));
        }
        for j in 0..3 {
            distance = distance.min(segment_distance(a[i], a[(i + 1) % 3], b[j], b[(j + 1) % 3]));
        }
    }
    distance
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cube(lo: f64, hi: f64) -> Mesh {
        Mesh {
            points: vec![
                [lo, lo, lo],
                [hi, lo, lo],
                [hi, hi, lo],
                [lo, hi, lo],
                [lo, lo, hi],
                [hi, lo, hi],
                [hi, hi, hi],
                [lo, hi, hi],
            ],
            faces: vec![
                [0, 2, 1],
                [0, 3, 2],
                [4, 5, 6],
                [4, 6, 7],
                [0, 1, 5],
                [0, 5, 4],
                [1, 2, 6],
                [1, 6, 5],
                [2, 3, 7],
                [2, 7, 6],
                [3, 0, 4],
                [3, 4, 7],
            ],
        }
    }

    #[test]
    fn inside_test_and_enclosed_void_are_both_required() -> Result<()> {
        let mut parent = cube(-10., 10.);
        let modifier = cube(-4., 4.);
        verify(&modifier, &parent, 0.4)?;
        assert!(verify(&parent, &modifier, 0.4).is_err());
        assert!(verify(&cube(-9.8, 9.8), &parent, 0.4).is_err());
        let void = cube(-1., 1.);
        parent.points.extend(void.points);
        parent.faces.extend(
            void.faces
                .into_iter()
                .map(|[a, b, c]| [a + 8, c + 8, b + 8]),
        );
        assert!(verify(&modifier, &parent, 0.4).is_err());
        Ok(())
    }

    #[test]
    fn crossing_faces_and_parallel_clearance() {
        let a = [[0., 0., 0.], [4., 0., 0.], [0., 4., 0.]];
        let crossing = [[1., 1., -2.], [1., 1., 2.], [3., 3., 1.]];
        assert_eq!(triangle_distance_squared(a, crossing), 0.);
        assert!(
            (triangle_distance_squared(a, a.map(|p| add(p, [0., 0., 0.4]))) - 0.16).abs() < 1e-10
        );
    }
}
