use crate::{archive, hidden};
use anyhow::{Context, Result, bail, ensure};
use clap::Args;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    io::{BufRead, BufReader, Write},
    path::{Path, PathBuf},
    process::{Child, ChildStdin, Command, Stdio},
    sync::mpsc::{self, Receiver},
    thread,
    time::{Duration, Instant},
};

#[derive(Args)]
pub struct Options {
    /// Installed Limo CAD executable; defaults to LIMO_CAD_EXE or the Windows installation.
    #[arg(long)]
    pub executable: Option<PathBuf>,
    #[arg(long, default_value = ".build/verify-model")]
    pub evidence: PathBuf,
}

pub struct Client {
    child: Child,
    input: Option<ChildStdin>,
    lines: Receiver<std::io::Result<String>>,
    sequence: u64,
}

impl Client {
    pub fn start(executable: Option<&Path>) -> Result<Self> {
        let executable = executable
            .map(Path::to_owned)
            .or_else(|| std::env::var_os("LIMO_CAD_EXE").map(PathBuf::from))
            .or_else(|| {
                std::env::var_os("LOCALAPPDATA")
                    .map(|p| PathBuf::from(p).join("limo-cad/bevy/Limo-CAD.exe"))
            })
            .context("Pass --executable or set LIMO_CAD_EXE to an installed Limo CAD engine")?;
        let mut child = hidden(
            Command::new(&executable)
                .arg("--headless")
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::null()),
        )
        .spawn()
        .with_context(|| format!("Start {}", executable.display()))?;
        let input = child.stdin.take();
        let output = child.stdout.take().context("CAD stdout unavailable")?;
        let (tx, lines) = mpsc::channel();
        thread::spawn(move || {
            for line in BufReader::new(output).lines() {
                if tx.send(line).is_err() {
                    break;
                }
            }
        });
        let mut client = Self {
            child,
            input,
            lines,
            sequence: 0,
        };
        client.request("initialize", json!({"protocolVersion":"2025-06-18", "capabilities":{}, "clientInfo":{"name":"garden-auger-xtask","version":"1"}}))?;
        client.send(json!({"jsonrpc":"2.0","method":"notifications/initialized"}))?;
        Ok(client)
    }

    fn send(&mut self, value: Value) -> Result<()> {
        let input = self.input.as_mut().context("CAD stdin closed")?;
        serde_json::to_writer(&mut *input, &value)?;
        input.write_all(b"\n")?;
        input.flush()?;
        Ok(())
    }

    pub fn request(&mut self, method: &str, params: Value) -> Result<Value> {
        self.sequence += 1;
        self.send(json!({"jsonrpc":"2.0","id":self.sequence,"method":method,"params":params}))?;
        let deadline = Instant::now() + Duration::from_secs(300);
        loop {
            let line = self
                .lines
                .recv_timeout(deadline.saturating_duration_since(Instant::now()))
                .with_context(|| format!("CAD {method} timed out or exited"))??;
            let reply: Value =
                serde_json::from_str(&line).context("Invalid CAD JSON-RPC response")?;
            if reply["id"].as_u64() != Some(self.sequence) {
                continue;
            }
            ensure!(
                reply.get("error").is_none(),
                "CAD RPC error: {}",
                reply["error"]
            );
            return reply
                .get("result")
                .cloned()
                .context("CAD RPC response lacks result");
        }
    }

    pub fn call(&mut self, name: &str, arguments: Value) -> Result<Value> {
        let reply = self.request("tools/call", json!({"name":name,"arguments":arguments}))?;
        decode_tool(reply).with_context(|| format!("CAD tool {name}"))
    }

    pub fn load(&mut self, root: &Path) -> Result<()> {
        let archive = archive::read(&root.join("garden-auger.limo"))?;
        let manifest: Value =
            serde_json::from_slice(archive::required(&archive, "manifest.json")?)?;
        ensure!(
            manifest["format"] == "limo-cad-project" && manifest["application"] == "Limo CAD",
            "Project manifest must use the current Limo CAD identity"
        );
        let model: Value = serde_json::from_slice(archive::required(&archive, "model.json")?)?;
        validate_labels(&model)?;
        validate_locator_fits(&model)?;
        self.call(
            "cad_load_project_model",
            json!({"model_json":serde_json::to_string(&model)?}),
        )?;
        Ok(())
    }

    pub fn scene(&mut self) -> Result<Scene> {
        let scene: Scene = serde_json::from_value(self.call("solid_scene", json!({}))?)?;
        ensure!(
            scene.errors.is_empty(),
            "CAD scene errors: {:?}",
            scene.errors
        );
        for body in &scene.bodies {
            body.mesh.validate()?;
        }
        Ok(scene)
    }
}

fn validate_labels(model: &Value) -> Result<()> {
    for sketch_id in [395, 397] {
        let sketch = model["sketches"]
            .as_array()
            .context("Missing sketches")?
            .iter()
            .find(|s| s["feature_id"] == sketch_id)
            .context("Missing housing label sketch")?;
        let points: Vec<_> = sketch["snapshot"]["entities"]
            .as_array()
            .context("Missing label entities")?
            .iter()
            .filter(|e| e[1]["type"] == "point")
            .map(|e| &e[1]["position"])
            .collect();
        ensure!(!points.is_empty(), "Housing label is empty");
        for (axis, lo, hi) in [("x", -29.9, 9.4), ("y", 152.7, 193.)] {
            let mut coordinates = points
                .iter()
                .map(|p| p[axis].as_f64().context("Invalid label point"))
                .collect::<Result<Vec<_>>>()?;
            coordinates.sort_by(f64::total_cmp);
            coordinates.dedup_by(|a, b| (*a - *b).abs() < 1e-6);
            ensure!(
                coordinates[0] >= lo && coordinates[coordinates.len() - 1] <= hi,
                "Housing label extends beyond the pocket floor margin"
            );
            ensure!(
                coordinates.windows(2).all(|p| p[1] - p[0] >= 0.799),
                "Housing label detail is smaller than the 0.8 mm print grid"
            );
        }
        ensure!(
            (sketch["basis"]["origin"][2]
                .as_f64()
                .context("Missing lettering plane")?
                .abs()
                - 10.2)
                .abs()
                < 1e-7,
            "Lettering profiles must sit on the flat pocket floor"
        );
    }
    ensure!(
        model["extrudes"]
            .as_array()
            .context("Missing extrudes")?
            .iter()
            .all(|e| e["feature_id"] != 396 && e["feature_id"] != 398),
        "Flush lettering must not cut recesses in the housing"
    );
    Ok(())
}

fn validate_locator_fits(model: &Value) -> Result<()> {
    let sketches = model["sketches"].as_array().context("Missing sketches")?;
    for id in [371, 375, 379, 383] {
        let radii = |id| -> Result<Vec<f64>> {
            let axis = model["revolves"]
                .as_array()
                .context("Missing revolves")?
                .iter()
                .find(|r| r["feature_id"] == id + 1)
                .context("Missing locator revolve")?["axis_origin"]["x"]
                .as_f64()
                .context("Invalid locator axis")?;
            let s = sketches
                .iter()
                .find(|s| s["feature_id"] == id)
                .context("Missing locator sketch")?;
            Ok(s["snapshot"]["entities"]
                .as_array()
                .context("Missing locator points")?
                .iter()
                .filter(|e| e[1]["type"] == "point")
                .filter_map(|e| e[1]["position"]["x"].as_f64())
                .map(|x| x - axis)
                .filter(|&r| r > 0.1)
                .collect())
        };
        let pin = radii(id)?.into_iter().fold(0., f64::max);
        let socket = radii(id + 2)?.into_iter().fold(f64::INFINITY, f64::min);
        ensure!(
            (pin - 2.35).abs() < 1e-7 && (socket - 2.5).abs() < 1e-7,
            "Locator must retain the selected 0.15 mm radial clearance: pin radius {pin}, socket radius {socket}"
        );
    }
    Ok(())
}

impl Drop for Client {
    fn drop(&mut self) {
        self.input.take();
        let _ = crate::wait(&mut self.child, Duration::from_secs(15));
    }
}

fn decode_tool(reply: Value) -> Result<Value> {
    ensure!(reply["isError"] != true, "{reply}");
    if let Some(value) = reply.get("structuredContent") {
        return Ok(
            if value
                .as_object()
                .is_some_and(|m| m.len() == 1 && m.contains_key("value"))
            {
                value["value"].clone()
            } else {
                value.clone()
            },
        );
    }
    let text = reply["content"]
        .as_array()
        .and_then(|a| a.iter().find(|c| c["type"] == "text"))
        .and_then(|c| c["text"].as_str())
        .context("CAD tool returned no text or structured content")?;
    Ok(serde_json::from_str(text).unwrap_or_else(|_| Value::String(text.into())))
}

#[derive(Serialize, Deserialize)]
pub struct Scene {
    pub bodies: Vec<Body>,
    pub errors: Vec<Value>,
}
#[derive(Serialize, Deserialize)]
pub struct Body {
    pub id: u64,
    pub mesh: Mesh,
}
#[derive(Serialize, Deserialize)]
pub struct Mesh {
    pub positions: Vec<f64>,
    pub indices: Vec<usize>,
}

impl Mesh {
    fn validate(&self) -> Result<()> {
        ensure!(
            !self.positions.is_empty() && self.positions.len().is_multiple_of(3),
            "Invalid mesh positions"
        );
        ensure!(
            self.positions.iter().all(|n| n.is_finite()),
            "Non-finite mesh coordinates"
        );
        ensure!(
            !self.indices.is_empty() && self.indices.len().is_multiple_of(3),
            "Invalid mesh faces"
        );
        ensure!(
            self.indices.iter().all(|i| *i < self.positions.len() / 3),
            "Mesh index out of range"
        );
        Ok(())
    }
    pub fn bounds(&self) -> [[f64; 3]; 2] {
        let mut bounds = [[f64::INFINITY; 3], [f64::NEG_INFINITY; 3]];
        for p in self.positions.as_chunks::<3>().0.iter() {
            for a in 0..3 {
                bounds[0][a] = bounds[0][a].min(p[a]);
                bounds[1][a] = bounds[1][a].max(p[a]);
            }
        }
        bounds
    }
}

pub fn verify(root: &Path, options: &Options) -> Result<()> {
    let reference: Value = serde_json::from_slice(&fs::read(root.join("docs/validation.json"))?)?;
    let mut client = Client::start(options.executable.as_deref())?;
    client.load(root)?;
    let document = client.call("cad_document", json!({}))?;
    let features = document["features"]
        .as_array()
        .context("Missing document features")?;
    ensure!(
        Some(features.len() as u64) == reference["model"]["feature_count"].as_u64(),
        "Feature count changed"
    );
    for f in features {
        let name = f["name"].as_str().context("Unnamed feature")?;
        ensure!(
            !name.is_empty() && !generic_name(name),
            "Feature needs a descriptive name: {name}"
        );
    }
    let scene = client.scene()?;
    let expected: BTreeMap<u64, [[f64; 3]; 2]> =
        serde_json::from_value(reference["model"]["bounds_mm"].clone())?;
    ensure!(
        scene.bodies.iter().map(|b| b.id).collect::<BTreeSet<_>>()
            == expected.keys().copied().collect(),
        "Scene body IDs changed"
    );
    for body in &scene.bodies {
        let bounds = body.mesh.bounds();
        ensure!(
            bounds
                .iter()
                .flatten()
                .zip(expected[&body.id].iter().flatten())
                .all(|(v, e)| (v - e).abs() < 1e-5),
            "Body {} bounds changed: {:?}",
            body.id,
            bounds
        );
    }
    let check = client.call(
        "assembly_interference_check",
        json!({"occurrence_ids":[3,6,7,8,14,16],"clearance_threshold_mm":2}),
    )?;
    validate_interference(&check)?;
    fs::create_dir_all(&options.evidence)?;
    let report = json!({"feature_count":features.len(),"bodies":scene.bodies.len(),"exact_nominal_interference":check,"model_sha256":archive::sha(&fs::read(root.join("garden-auger.limo"))?)});
    fs::write(
        options.evidence.join("summary.json"),
        serde_json::to_vec_pretty(&report)?,
    )?;
    println!(
        "PASS: named model reopens, seven body bounds match, exact nominal assembly has no interference."
    );
    Ok(())
}

fn generic_name(name: &str) -> bool {
    [
        "Sketch",
        "Extrude",
        "Revolve",
        "Plane",
        "Fillet",
        "Chamfer",
        "Combine",
        "SplitBody",
        "MoveCopy",
    ]
    .iter()
    .any(|p| {
        name.strip_prefix(p)
            .is_some_and(|s| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit()))
    })
}

fn validate_interference(check: &Value) -> Result<()> {
    ensure!(
        check["exact"] == true,
        "Interference result is not exact: {check}"
    );
    let pairs = check["pairs"]
        .as_array()
        .context("Interference result lacks pairs")?;
    ensure!(!pairs.is_empty(), "Interference result is empty");
    for pair in pairs {
        match pair["interfering"].as_bool() {
            Some(false) => {}
            _ => bail!("Interfering or incomplete pair: {pair}"),
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn labels_keep_printable_detail_without_recesses() -> Result<()> {
        let entries = archive::read(&crate::root().join("garden-auger.limo"))?;
        let mut model: Value = serde_json::from_slice(&entries["model.json"])?;
        validate_labels(&model)?;
        model["sketches"]
            .as_array_mut()
            .unwrap()
            .iter_mut()
            .find(|e| e["feature_id"] == 395)
            .unwrap()["basis"]["origin"][2] = json!(-10.19);
        assert!(validate_labels(&model).is_err());
        Ok(())
    }
    #[test]
    fn zero_clearance_locators_are_rejected() -> Result<()> {
        let entries = archive::read(&crate::root().join("garden-auger.limo"))?;
        let mut model: Value = serde_json::from_slice(&entries["model.json"])?;
        validate_locator_fits(&model)?;
        let s = model["sketches"]
            .as_array_mut()
            .unwrap()
            .iter_mut()
            .find(|s| s["feature_id"] == 371)
            .unwrap();
        for e in s["snapshot"]["entities"]
            .as_array_mut()
            .unwrap()
            .iter_mut()
            .filter(|e| e[1]["type"] == "point")
        {
            let x = e[1]["position"]["x"].as_f64().unwrap();
            if x > -26.9 {
                e[1]["position"]["x"] = json!(x + 0.15);
            }
        }
        assert!(validate_locator_fits(&model).is_err());
        Ok(())
    }
    #[test]
    fn rejects_incomplete_interference_and_tool_errors() {
        assert!(validate_interference(&json!({"exact":true,"pairs":[]})).is_err());
        assert!(validate_interference(&json!({"exact":true,"pairs":[{}]})).is_err());
        assert!(
            validate_interference(&json!({"exact":true,"pairs":[{"interfering":true}]})).is_err()
        );
        assert!(decode_tool(json!({"isError":true,"structuredContent":42})).is_err());
        assert_eq!(
            decode_tool(json!({"structuredContent":{"value":{"a":1}}})).unwrap(),
            json!({"a":1})
        );
        assert_eq!(
            decode_tool(json!({"content":[{"type":"text","text":"[1,2]"}]})).unwrap(),
            json!([1, 2])
        );
    }
    #[test]
    fn rejects_invalid_meshes_and_only_generic_names() {
        assert!(
            Mesh {
                positions: vec![0., 0., 0.],
                indices: vec![0, 1, 2]
            }
            .validate()
            .is_err()
        );
        assert!(generic_name("Sketch12"));
        assert!(!generic_name("Sketch servo ear"));
    }
}
