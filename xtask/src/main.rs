mod archive;
mod cad;
mod gallery;
mod lettering;
mod print;
mod xml;

use anyhow::Result;
use clap::{Parser, Subcommand};
use std::{
    path::{Path, PathBuf},
    process::{Child, Command, ExitStatus},
    time::{Duration, Instant},
};

#[derive(Parser)]
#[command(about = "Garden auger: native CAD validation, local slicing and gallery generation")]
struct Cli {
    #[command(subcommand)]
    command: Task,
}

#[derive(Subcommand)]
enum Task {
    /// Reopen the model and validate names, body bounds and exact nominal interference.
    VerifyModel(cad::Options),
    /// Rebuild local reinforcement; optionally slice both plates locally (no printer connection).
    BuildPrint(print::Options),
    /// Render the gallery from current native meshes and saved named-view poses.
    Gallery(gallery::Options),
}

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .to_owned()
}

fn main() -> Result<()> {
    match Cli::parse().command {
        Task::VerifyModel(options) => cad::verify(&root(), &options),
        Task::BuildPrint(options) => print::run(&root(), &options),
        Task::Gallery(options) => gallery::run(&root(), &options),
    }
}

fn hidden(command: &mut Command) -> &mut Command {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    command
}

// Some native Windows applications reject Rust's canonical \\?\ path spelling.
// Keep canonical filesystem identity, but pass conventional absolute paths to them.
fn native_absolute(path: &Path) -> Result<PathBuf> {
    let path = std::fs::canonicalize(path)?;
    #[cfg(windows)]
    {
        use std::path::{Component, Prefix};
        let mut components = path.components();
        if let Some(Component::Prefix(prefix)) = components.next() {
            let mut ordinary = match prefix.kind() {
                Prefix::VerbatimDisk(drive) => PathBuf::from(format!("{}:\\", drive as char)),
                Prefix::VerbatimUNC(server, share) => {
                    let mut p = PathBuf::from(r"\\");
                    p.push(server);
                    p.push(share);
                    p
                }
                _ => return Ok(path),
            };
            for component in components {
                if !matches!(component, Component::RootDir) {
                    ordinary.push(component.as_os_str());
                }
            }
            return Ok(ordinary);
        }
    }
    Ok(path)
}

fn wait(child: &mut Child, timeout: Duration) -> Result<ExitStatus> {
    let start = Instant::now();
    loop {
        if let Some(status) = child.try_wait()? {
            return Ok(status);
        }
        if start.elapsed() >= timeout {
            let _ = child.kill();
            let _ = child.wait();
            anyhow::bail!("Child process exceeded {} seconds", timeout.as_secs());
        }
        std::thread::sleep(Duration::from_millis(20));
    }
}
