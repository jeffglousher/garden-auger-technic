use crate::{
    archive,
    cad::{Client, Scene},
    xml,
};
use anyhow::{Context, Result, ensure};
use clap::Args;
use fontdue::Font;
use image::{Rgb, RgbImage, imageops};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    borrow::Cow,
    collections::{BTreeMap, BTreeSet},
    fs::{self, File},
    path::{Path, PathBuf},
};

type V3 = [f64; 3];
const BACK: [u8; 3] = [242, 245, 248];
const INK: [u8; 3] = [32, 43, 58];
const FRAMES: usize = 48;

#[derive(Args)]
pub struct Options {
    #[arg(long)]
    pub executable: Option<PathBuf>,
    /// Destination for all five gallery images. Inputs are never modified.
    #[arg(long)]
    pub output: Option<PathBuf>,
    /// TrueType font for callouts; defaults to Segoe UI on Windows or DejaVu Sans on Linux.
    #[arg(long)]
    pub font: Option<PathBuf>,
    #[arg(long, default_value = ".build/gallery-rust")]
    pub evidence: PathBuf,
}

#[derive(Clone, Deserialize)]
struct Pose {
    body_id: u64,
    rotation: [f64; 4],
    translation: V3,
}
struct Geometry {
    points: Vec<V3>,
    faces: Vec<[usize; 3]>,
    color: [u8; 3],
}
struct Assembly {
    scene: Scene,
    base: BTreeMap<u64, Pose>,
    exploded: BTreeMap<u64, Pose>,
}

fn add(a: V3, b: V3) -> V3 {
    std::array::from_fn(|i| a[i] + b[i])
}
fn sub(a: V3, b: V3) -> V3 {
    std::array::from_fn(|i| a[i] - b[i])
}
fn scale(a: V3, t: f64) -> V3 {
    a.map(|v| v * t)
}
fn dot(a: V3, b: V3) -> f64 {
    (0..3).map(|i| a[i] * b[i]).sum()
}
fn cross(a: V3, b: V3) -> V3 {
    [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]
}
fn unit(a: V3) -> V3 {
    scale(a, 1. / dot(a, a).sqrt().max(1e-12))
}
fn rotate(p: V3, q: [f64; 4]) -> V3 {
    let t = scale(cross([q[0], q[1], q[2]], p), 2.);
    add(p, add(scale(t, q[3]), cross([q[0], q[1], q[2]], t)))
}
fn color(id: u64) -> Result<[u8; 3]> {
    Ok(match id {
        1 => [87, 102, 120],
        15 | 90 => [234, 124, 43],
        26 | 46 => [239, 184, 46],
        216 => [163, 173, 187],
        221 => [36, 168, 157],
        _ => anyhow::bail!("Unknown gallery body {id}"),
    })
}

impl Assembly {
    fn poses(solution: &Value) -> Result<BTreeMap<u64, Pose>> {
        ensure!(solution["solved"] == true, "Named view is not solved");
        let poses: Vec<Pose> = serde_json::from_value(solution["body_poses"].clone())?;
        let mut result = BTreeMap::new();
        for pose in poses {
            ensure!(
                pose.translation
                    .iter()
                    .chain(&pose.rotation)
                    .all(|v| v.is_finite()),
                "Non-finite view pose"
            );
            ensure!(
                (pose.rotation.iter().map(|x| x * x).sum::<f64>() - 1.).abs() < 1e-6,
                "Non-unit pose quaternion"
            );
            ensure!(
                result.insert(pose.body_id, pose).is_none(),
                "Duplicate view body pose"
            );
        }
        Ok(result)
    }
    fn geometry(&self, amount: f64, spin: f64) -> Result<Vec<Geometry>> {
        let mut result = Vec::new();
        for body in &self.scene.bodies {
            let pose = &self.base[&body.id];
            let exploded = &self.exploded[&body.id];
            let mut points = Vec::new();
            for p in body.mesh.positions.as_chunks::<3>().0.iter() {
                let mut p = add(rotate([p[0], p[1], p[2]], pose.rotation), pose.translation);
                if [15, 90, 216].contains(&body.id) {
                    let a = spin.to_radians();
                    p = [
                        p[0] * a.cos() + p[2] * a.sin(),
                        p[1],
                        -p[0] * a.sin() + p[2] * a.cos(),
                    ];
                }
                points.push(add(
                    p,
                    scale(sub(exploded.translation, pose.translation), amount),
                ));
            }
            result.push(Geometry {
                points,
                faces: body
                    .mesh
                    .indices
                    .as_chunks::<3>()
                    .0
                    .iter()
                    .map(|f| [f[0], f[1], f[2]])
                    .collect(),
                color: color(body.id)?,
            });
        }
        Ok(result)
    }
}

struct Camera {
    width: u32,
    height: u32,
    right: V3,
    up: V3,
    direction: V3,
    target: V3,
    scale: f64,
}
impl Camera {
    fn new(size: (u32, u32), az: f64, elevation: f64, target: V3, scale: f64) -> Self {
        let (a, e) = (az.to_radians(), elevation.to_radians());
        let direction = [a.cos() * e.cos(), a.sin() * e.cos(), e.sin()];
        let right = [-a.sin(), a.cos(), 0.];
        Self {
            width: size.0,
            height: size.1,
            right,
            up: cross(direction, right),
            direction,
            target,
            scale,
        }
    }
    fn project(&self, p: V3) -> V3 {
        let p = sub(p, self.target);
        [
            self.width as f64 / 2. + dot(p, self.right) * self.scale,
            self.height as f64 / 2. - dot(p, self.up) * self.scale,
            dot(p, self.direction),
        ]
    }
}

fn render(geometry: &[Geometry], camera: &Camera) -> RgbImage {
    let mut image = RgbImage::from_pixel(camera.width, camera.height, Rgb(BACK));
    let mut depth = vec![f64::NEG_INFINITY; (camera.width * camera.height) as usize];
    let light = unit([-0.35, -0.5, 0.8]);
    for mesh in geometry {
        let screen: Vec<_> = mesh.points.iter().map(|p| camera.project(*p)).collect();
        for face in &mesh.faces {
            let p = face.map(|i| mesh.points[i]);
            let normal = unit(cross(sub(p[1], p[0]), sub(p[2], p[0])));
            if dot(normal, camera.direction) <= 1e-7 {
                continue;
            }
            let brightness = 0.48 + 0.52 * dot(normal, light).max(0.);
            let rgb = Rgb(mesh
                .color
                .map(|c| (c as f64 * brightness).clamp(0., 255.) as u8));
            let [a, b, c] = face.map(|i| screen[i]);
            let denominator = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1]);
            if denominator.abs() < 1e-10 {
                continue;
            }
            let xmin = a[0].min(b[0]).min(c[0]).floor().max(0.) as u32;
            let xmax = a[0]
                .max(b[0])
                .max(c[0])
                .ceil()
                .min(camera.width as f64 - 1.) as u32;
            let ymin = a[1].min(b[1]).min(c[1]).floor().max(0.) as u32;
            let ymax = a[1]
                .max(b[1])
                .max(c[1])
                .ceil()
                .min(camera.height as f64 - 1.) as u32;
            if xmin >= camera.width || ymin >= camera.height {
                continue;
            }
            for y in ymin..=ymax {
                for x in xmin..=xmax {
                    let u = ((b[1] - c[1]) * (x as f64 + 0.5 - c[0])
                        + (c[0] - b[0]) * (y as f64 + 0.5 - c[1]))
                        / denominator;
                    let v = ((c[1] - a[1]) * (x as f64 + 0.5 - c[0])
                        + (a[0] - c[0]) * (y as f64 + 0.5 - c[1]))
                        / denominator;
                    let t = 1. - u - v;
                    let z = u * a[2] + v * b[2] + t * c[2];
                    let index = (y * camera.width + x) as usize;
                    if u >= -1e-6 && v >= -1e-6 && t >= -1e-6 && z > depth[index] {
                        depth[index] = z;
                        image.put_pixel(x, y, rgb);
                    }
                }
            }
        }
    }
    image
}

struct Text {
    font: Font,
}
impl Text {
    fn load(path: Option<&Path>) -> Result<Self> {
        let path = path.map(Path::to_owned).unwrap_or_else(|| {
            if cfg!(windows) {
                PathBuf::from("C:/Windows/Fonts/segoeui.ttf")
            } else {
                PathBuf::from("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
            }
        });
        let font = Font::from_bytes(
            fs::read(&path).with_context(|| {
                format!("Read font {}; pass --font for another TTF", path.display())
            })?,
            fontdue::FontSettings::default(),
        )
        .map_err(|e| anyhow::anyhow!(e))?;
        Ok(Self { font })
    }
    fn draw(
        &self,
        image: &mut RgbImage,
        text: &str,
        x: i32,
        y: i32,
        size: f32,
        color: [u8; 3],
    ) -> i32 {
        let mut cursor = x as f32;
        let ascent = self.font.horizontal_line_metrics(size).unwrap().ascent;
        for ch in text.chars() {
            let (m, bitmap) = self.font.rasterize(ch, size);
            let top = y + (ascent.round() as i32) - m.ymin - m.height as i32;
            for row in 0..m.height {
                for col in 0..m.width {
                    let (px, py) = (
                        cursor.round() as i32 + m.xmin + col as i32,
                        top + row as i32,
                    );
                    if px >= 0 && py >= 0 && px < image.width() as i32 && py < image.height() as i32
                    {
                        let alpha = bitmap[row * m.width + col] as f32 / 255.;
                        let old = image.get_pixel(px as u32, py as u32).0;
                        image.put_pixel(
                            px as u32,
                            py as u32,
                            Rgb(std::array::from_fn(|a| {
                                (color[a] as f32 * alpha + old[a] as f32 * (1. - alpha)).round()
                                    as u8
                            })),
                        );
                    }
                }
            }
            cursor += m.advance_width;
        }
        cursor.round() as i32
    }
}

fn line(image: &mut RgbImage, a: V3, b: V3, color: [u8; 3]) {
    let steps = (a[0] - b[0]).abs().max((a[1] - b[1]).abs()).ceil() as usize;
    for i in 0..=steps {
        let t = i as f64 / steps.max(1) as f64;
        let p = add(a, scale(sub(b, a), t));
        for (dx, dy) in [(0, 0), (1, 0)] {
            let (x, y) = (p[0].round() as i32 + dx, p[1].round() as i32 + dy);
            if x >= 0 && y >= 0 && x < image.width() as i32 && y < image.height() as i32 {
                image.put_pixel(x as u32, y as u32, Rgb(color));
            }
        }
    }
}

fn exploded(assembly: &Assembly, text: &Text) -> Result<RgbImage> {
    let camera = Camera::new((1500, 1080), -55., 32., [0., 125., 35.], 3.6);
    let mut image = render(&assembly.geometry(1., 0.)?, &camera);
    text.draw(&mut image, "How it fits together", 65, 40, 36., INK);
    let callouts = [
        ("Upper housing", [-35., 176., 90.], (60, 150)),
        ("Auger + rotating shield", [0., 25., 16.], (60, 470)),
        ("Lower housing + grips", [60., 194., -12.], (60, 930)),
        ("Servo", [0., 250., 40.], (1120, 160)),
        ("Drive adapter", [0., 189., 50.], (1120, 415)),
        ("PLA wear bushing", [13., 130.85, 46.], (1120, 825)),
    ];
    for (label, point, (x, y)) in callouts {
        let end_x = text.draw(&mut image, label, x, y, 23., INK);
        let end = [
            if x > 750 {
                (x + 5) as f64
            } else {
                (end_x - 5) as f64
            },
            (y + 40) as f64,
            0.,
        ];
        let p = camera.project(point);
        let elbow = [(p[0] + end[0]) / 2., end[1], 0.];
        line(&mut image, p, elbow, [104, 119, 138]);
        line(&mut image, elbow, end, [104, 119, 138]);
        for dy in -5..=5 {
            for dx in -5..=5 {
                if dx * dx + dy * dy <= 25 {
                    let (xx, yy) = (p[0] as i32 + dx, p[1] as i32 + dy);
                    if xx >= 0 && yy >= 0 && xx < 1500 && yy < 1080 {
                        image.put_pixel(xx as u32, yy as u32, Rgb(INK));
                    }
                }
            }
        }
    }
    Ok(image)
}

fn labels(assembly: &Assembly, text: &Text) -> Result<RgbImage> {
    let mut sheet = RgbImage::from_pixel(1600, 720, Rgb(BACK));
    for (i, (id, label, lo, hi)) in [
        (46, "Lower housing", [-28., 165., -11.], [7., 192., -9.8]),
        (26, "Upper housing", [-29., 173., 9.8], [7., 192., 11.]),
    ]
    .into_iter()
    .enumerate()
    {
        let body = assembly
            .scene
            .bodies
            .iter()
            .find(|b| b.id == id)
            .context("Label body missing")?;
        let source = body.mesh.positions.as_chunks::<3>().0;
        let mut points: Vec<V3> = Vec::new();
        let mut surface = Vec::new();
        let mut recess = Vec::new();
        for f in body.mesh.indices.as_chunks::<3>().0.iter() {
            let polygon = clip_triangle(f.map(|i| source[i]), lo, hi);
            if polygon.len() < 3 {
                continue;
            }
            let engraved = polygon.iter().all(|p| (p[2].abs() - 10.6).abs() < 1e-4);
            let first = points.len();
            points.extend(polygon);
            for i in first + 1..points.len() - 1 {
                let tri = [first, i, i + 1];
                if engraved {
                    recess.push(tri);
                } else {
                    surface.push(tri);
                }
            }
        }
        ensure!(
            !recess.is_empty() && !surface.is_empty(),
            "Engraved label crop empty: {label}"
        );
        if id == 26 {
            for p in &mut points {
                *p = [-p[0], p[1], -p[2]];
            }
        }
        let mut bounds = [[f64::INFINITY; 3], [f64::NEG_INFINITY; 3]];
        for tri in surface.iter().chain(&recess) {
            for idx in tri {
                for a in 0..3 {
                    bounds[0][a] = bounds[0][a].min(points[*idx][a]);
                    bounds[1][a] = bounds[1][a].max(points[*idx][a]);
                }
            }
        }
        let target = scale(add(bounds[0], bounds[1]), 0.5);
        let mut camera = Camera::new((760, 550), -83.66, 69.3, target, 1.);
        let (mut sx, mut sy) = (0_f64, 0_f64);
        for p in &points {
            let q = camera.project(*p);
            sx = sx.max((q[0] - 380.).abs());
            sy = sy.max((q[1] - 275.).abs());
        }
        camera.scale = (335. / sx).min(230. / sy);
        let geometry = [
            Geometry {
                points: points.clone(),
                faces: surface,
                color: color(id)?,
            },
            Geometry {
                points,
                faces: recess,
                color: [95, 65, 24],
            },
        ];
        let image = render(&geometry, &camera);
        imageops::replace(&mut sheet, &image, 20 + i as i64 * 800, 95);
        text.draw(&mut sheet, label, 35 + i as i32 * 800, 25, 30., INK);
    }
    text.draw(
        &mut sheet,
        "Recessed part IDs, screw sizes and insert details",
        35,
        665,
        24.,
        INK,
    );
    Ok(sheet)
}

fn clip_triangle(triangle: [V3; 3], lo: V3, hi: V3) -> Vec<V3> {
    let mut polygon = triangle.to_vec();
    for axis in 0..3 {
        for (limit, sign) in [(lo[axis], 1.), (hi[axis], -1.)] {
            if polygon.is_empty() {
                return polygon;
            }
            let mut next = Vec::new();
            for i in 0..polygon.len() {
                let a = polygon[i];
                let b = polygon[(i + 1) % polygon.len()];
                let (da, db) = (sign * (a[axis] - limit), sign * (b[axis] - limit));
                if da >= 0. {
                    next.push(a);
                }
                if (da >= 0.) != (db >= 0.) {
                    next.push(add(a, scale(sub(b, a), da / (da - db))));
                }
            }
            polygon = next;
        }
    }
    polygon
}

fn rectangle(image: &mut RgbImage, x: u32, y: u32, w: u32, h: u32, color: [u8; 3]) {
    for yy in y..(y + h).min(image.height()) {
        for xx in x..(x + w).min(image.width()) {
            image.put_pixel(xx, yy, Rgb(color));
        }
    }
}

fn plates(entries: &archive::Entries, text: &Text) -> Result<RgbImage> {
    let info = xml::parse(archive::required(entries, "Metadata/slice_info.config")?)?;
    let plates: Vec<_> = info.children.iter().filter(|n| n.is("plate")).collect();
    ensure!(
        plates.len() == 2,
        "Two current sliced plate estimates required; run build-print --slicer first"
    );
    let mut sheet = RgbImage::from_pixel(1600, 850, Rgb(BACK));
    text.draw(&mut sheet, "Ready for the printer", 45, 25, 36., INK);
    for (i, plate) in plates.iter().enumerate() {
        let metadata = plate.metadata();
        let seconds: f64 = metadata
            .get("prediction")
            .context("Missing plate time")?
            .parse()?;
        let grams: f64 = metadata
            .get("weight")
            .context("Missing plate weight")?
            .parse()?;
        ensure!(
            seconds.is_finite() && seconds > 0. && grams.is_finite() && grams > 0.,
            "Invalid plate estimates"
        );
        let minutes = (seconds / 60.).round() as u64;
        let x = 35 + i as u32 * 800;
        let y = 100;
        rectangle(&mut sheet, x, y, 760, 680, [230, 235, 241]);
        text.draw(
            &mut sheet,
            [
                "Plate 1  - Housing halves",
                "Plate 2  - Auger, adapter + bushing",
            ][i],
            x as i32 + 25,
            y as i32 + 22,
            28.,
            INK,
        );
        text.draw(
            &mut sheet,
            &format!("{} h {} min  - {grams:.1} g", minutes / 60, minutes % 60),
            x as i32 + 25,
            y as i32 + 66,
            26.,
            INK,
        );
        rectangle(&mut sheet, x + 45, y + 125, 670, 485, [48, 57, 68]);
        for g in 1..8 {
            let gx = (x + 45) as f64 + g as f64 * 670. / 8.;
            let gy = (y + 125) as f64 + g as f64 * 485. / 8.;
            line(
                &mut sheet,
                [gx, (y + 125) as f64, 0.],
                [gx, (y + 610) as f64, 0.],
                [64, 75, 88],
            );
            line(
                &mut sheet,
                [(x + 45) as f64, gy, 0.],
                [(x + 715) as f64, gy, 0.],
                [64, 75, 88],
            );
        }
        let im = image::load_from_memory(archive::required(
            entries,
            &format!("Metadata/plate_{}.png", i + 1),
        )?)?
        .thumbnail(650, 485)
        .to_rgba8();
        let (ox, oy) = (
            x + (760 - im.width()) / 2,
            y + 125 + (485 - im.height()) / 2,
        );
        for (px, py, p) in im.enumerate_pixels() {
            let old = sheet.get_pixel(ox + px, oy + py).0;
            let a = p[3] as f64 / 255.;
            sheet.put_pixel(
                ox + px,
                oy + py,
                Rgb(std::array::from_fn(|k| {
                    (p[k] as f64 * a + old[k] as f64 * (1. - a)).round() as u8
                })),
            );
        }
        text.draw(
            &mut sheet,
            if i == 0 {
                "PETG"
            } else {
                "PETG first  - PLA bushing last"
            },
            x as i32 + 25,
            y as i32 + 630,
            23.,
            INK,
        );
    }
    text.draw(&mut sheet,"Native slicer previews and estimates  - Print by object  - Cooling and plate changes add time",45,805,21.,[89,105,123]);
    Ok(sheet)
}

// Fixed shared palette: six material shade ramps plus the background. No frame-to-frame quantization drift.
fn palette() -> Vec<u8> {
    let mut palette = BACK.to_vec();
    for id in [1, 15, 26, 216, 221] {
        let rgb = color(id).unwrap();
        for i in 0..48 {
            let brightness = 0.48 + 0.52 * i as f64 / 47.;
            palette.extend(rgb.map(|c| (c as f64 * brightness) as u8));
        }
    }
    palette.resize(768, 0);
    palette
}
fn encode_animation(assembly: &Assembly, path: &Path, mode: &str) -> Result<()> {
    let (width, height, delay) = if mode == "turntable" {
        (900, 600, 10)
    } else {
        (900, 650, 12)
    };
    let palette = palette();
    let mut encoder = gif::Encoder::new(File::create(path)?, width, height, &palette)?;
    encoder.set_repeat(gif::Repeat::Infinite)?;
    // Each raster color maps once per movie rather than searching the palette per pixel.
    let mut lookup = BTreeMap::new();
    for i in 0..FRAMES {
        let t = i as f64 / FRAMES as f64;
        let (geometry, camera) = if mode == "turntable" {
            (
                assembly.geometry(0., 1080. * t)?,
                Camera::new((900, 600), -55. + 360. * t, 30., [0., 110., 0.], 2.7),
            )
        } else {
            (
                assembly.geometry((1. - (std::f64::consts::TAU * t).cos()) / 2., 1440. * t)?,
                Camera::new((900, 650), -55., 32., [0., 120., 30.], 2.15),
            )
        };
        let image = render(&geometry, &camera);
        let mut pixels = Vec::with_capacity((width as usize) * (height as usize));
        for p in image.pixels() {
            let index = *lookup.entry(p.0).or_insert_with(|| {
                palette
                    .as_chunks::<3>()
                    .0
                    .iter()
                    .enumerate()
                    .min_by_key(|(_, rgb)| {
                        (0..3)
                            .map(|k| (p[k] as i32 - rgb[k] as i32).pow(2))
                            .sum::<i32>()
                    })
                    .unwrap()
                    .0 as u8
            });
            pixels.push(index);
        }
        let frame = gif::Frame {
            width,
            height,
            delay,
            dispose: gif::DisposalMethod::Background,
            buffer: Cow::Owned(pixels),
            ..Default::default()
        };
        encoder.write_frame(&frame)?;
        if i % 12 == 0 {
            println!("{mode}: frame {i}/{FRAMES}");
        }
    }
    Ok(())
}

fn check_gif(path: &Path, review: &Path) -> Result<()> {
    let mut options = gif::DecodeOptions::new();
    options.set_color_output(gif::ColorOutput::RGBA);
    let mut reader = options.read_info(File::open(path)?)?;
    let mut count = 0;
    let mut hashes = BTreeSet::new();
    let mut sheet = RgbImage::from_pixel(900, 175, Rgb(BACK));
    while let Some(frame) = reader.read_next_frame()? {
        if count % 12 == 0 {
            let image = RgbImage::from_fn(frame.width as u32, frame.height as u32, |x, y| {
                let i = (y as usize * frame.width as usize + x as usize) * 4;
                Rgb([frame.buffer[i], frame.buffer[i + 1], frame.buffer[i + 2]])
            });
            let thumb = imageops::resize(
                &image,
                225,
                (175_u32).min(frame.height as u32 / 4),
                imageops::FilterType::Triangle,
            );
            imageops::replace(&mut sheet, &thumb, (count / 12 * 225) as i64, 0);
        }
        count += 1;
        hashes.insert(archive::sha(&frame.buffer));
    }
    ensure!(
        count == FRAMES && hashes.len() > FRAMES / 2,
        "Incomplete or static animation: {}",
        path.display()
    );
    sheet.save(review)?;
    Ok(())
}

pub fn run(root: &Path, options: &Options) -> Result<()> {
    let output = options
        .output
        .clone()
        .unwrap_or_else(|| root.join("docs/images"));
    let text = Text::load(options.font.as_deref())?;
    let print = archive::read(&root.join("print/garden-auger.3mf"))?;
    // Validate slice data before starting the expensive native CAD replay.
    let plate_image = plates(&print, &text)?;
    let mut client = Client::start(options.executable.as_deref())?;
    client.load(root)?;
    let scene = client.scene()?;
    let complete = client.call("named_view_solution", json!({"name":"Complete assembly"}))?;
    let exploded_view = client.call("named_view_solution", json!({"name":"Exploded assembly"}))?;
    let base = Assembly::poses(&complete)?;
    let exploded_poses = Assembly::poses(&exploded_view)?;
    let ids = scene.bodies.iter().map(|b| b.id).collect::<BTreeSet<_>>();
    ensure!(
        ids == base.keys().copied().collect() && ids == exploded_poses.keys().copied().collect(),
        "Named-view body IDs differ from current scene"
    );
    let assembly = Assembly {
        scene,
        base,
        exploded: exploded_poses,
    };
    drop(client);
    fs::create_dir_all(&options.evidence)?;
    fs::write(
        options.evidence.join("scene.json"),
        serde_json::to_vec(&assembly.scene)?,
    )?;
    fs::write(
        options.evidence.join("complete-solution.json"),
        serde_json::to_vec(&complete)?,
    )?;
    fs::write(
        options.evidence.join("exploded-solution.json"),
        serde_json::to_vec(&exploded_view)?,
    )?;
    let stage = tempfile::tempdir_in(&options.evidence)?;
    exploded(&assembly, &text)?.save(stage.path().join("exploded.png"))?;
    labels(&assembly, &text)?.save(stage.path().join("inside-labels.png"))?;
    plate_image.save(stage.path().join("print-plates.png"))?;
    for mode in ["turntable", "exploding-drive"] {
        let path = stage.path().join(format!("{mode}.gif"));
        encode_animation(&assembly, &path, mode)?;
        check_gif(&path, &options.evidence.join(format!("{mode}-review.png")))?;
    }
    fs::create_dir_all(&output)?;
    let mut hashes = BTreeMap::new();
    for name in [
        "exploded.png",
        "inside-labels.png",
        "print-plates.png",
        "turntable.gif",
        "exploding-drive.gif",
    ] {
        let data = fs::read(stage.path().join(name))?;
        hashes.insert(name, archive::sha(&data));
        let mut temp = tempfile::NamedTempFile::new_in(&output)?;
        use std::io::Write;
        temp.write_all(&data)?;
        temp.as_file().sync_all()?;
        temp.persist(output.join(name)).map_err(|e| e.error)?;
    }
    let manifest = json!({"renderer":"Rust cargo xtask gallery","source":"Current native solid_scene meshes and named_view_solution poses; external rasterization/callouts/GIF encoding","model_sha256":archive::sha(&fs::read(root.join("garden-auger.limo"))?),"print_sha256":archive::sha(&fs::read(root.join("print/garden-auger.3mf"))?),"frames_per_animation":FRAMES,"images":hashes});
    fs::write(
        options.evidence.join("manifest.json"),
        serde_json::to_vec_pretty(&manifest)?,
    )?;
    println!(
        "PASS: five gallery images generated and both 48-frame animations decoded: {}",
        output.display()
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn pose_rotation_and_depth_buffer() {
        let p = rotate(
            [0., 0., 1.],
            [
                std::f64::consts::FRAC_1_SQRT_2,
                0.,
                0.,
                std::f64::consts::FRAC_1_SQRT_2,
            ],
        );
        assert!((p[1] + 1.).abs() < 1e-12 && p[2].abs() < 1e-12);
        let camera = Camera::new((40, 40), 0., 90., [0., 0., 0.], 10.);
        let geometry = |z, color| Geometry {
            points: vec![[-1., -1., z], [1., -1., z], [0., 1., z]],
            faces: vec![[0, 1, 2]],
            color,
        };
        let image = render(
            &[geometry(1., [255, 0, 0]), geometry(0., [0, 255, 0])],
            &camera,
        );
        let p = image.get_pixel(20, 20);
        assert!(p[0] > 100 && p[1] == 0);
    }
    #[test]
    fn missing_pose_status_is_rejected() {
        assert!(Assembly::poses(&json!({"body_poses":[]})).is_err());
    }

    #[test]
    fn triangle_crossing_crop_boundary_is_clipped_not_discarded() {
        let polygon = clip_triangle(
            [[-10., -10., 0.], [10., -10., 0.], [0., 10., 0.]],
            [-1., -1., -1.],
            [1., 1., 1.],
        );
        assert_eq!(polygon.len(), 4);
        assert!(
            polygon
                .iter()
                .all(|p| p[0].abs() <= 1. && p[1].abs() <= 1. && p[2] == 0.)
        );
        let area: f64 = polygon
            .iter()
            .enumerate()
            .map(|(i, a)| {
                let b = polygon[(i + 1) % polygon.len()];
                a[0] * b[1] - a[1] * b[0]
            })
            .sum();
        assert!((area - 8.).abs() < 1e-10);
    }
}
