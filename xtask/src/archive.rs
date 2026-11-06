use anyhow::{Context, Result, ensure};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    fs::{self, File},
    io::{Read, Write},
    path::Path,
};
use zip::{ZipArchive, ZipWriter, write::SimpleFileOptions};

pub type Entries = BTreeMap<String, Vec<u8>>;

pub fn read(path: &Path) -> Result<Entries> {
    let mut archive =
        ZipArchive::new(File::open(path).with_context(|| format!("Open {}", path.display()))?)?;
    let mut entries = Entries::new();
    for i in 0..archive.len() {
        let mut entry = archive.by_index(i)?;
        let mut data = Vec::new();
        entry.read_to_end(&mut data)?; // Includes the ZIP CRC check.
        ensure!(
            entries.insert(entry.name().to_owned(), data).is_none(),
            "Duplicate ZIP entry {}",
            entry.name()
        );
    }
    Ok(entries)
}

pub fn write(path: &Path, entries: &Entries) -> Result<()> {
    let parent = path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    fs::create_dir_all(parent)?;
    // Finish the archive before replacing the destination, including in-place rebuilds.
    let mut temp = tempfile::NamedTempFile::new_in(parent)?;
    {
        let mut writer = ZipWriter::new(temp.as_file_mut());
        for (name, data) in entries {
            writer.start_file(
                name,
                SimpleFileOptions::default().compression_method(zip::CompressionMethod::Deflated),
            )?;
            writer.write_all(data)?;
        }
        writer.finish()?;
    }
    temp.as_file().sync_all()?;
    temp.persist(path).map_err(|e| e.error)?;
    Ok(())
}

pub fn required<'a>(entries: &'a Entries, name: &str) -> Result<&'a [u8]> {
    entries
        .get(name)
        .map(Vec::as_slice)
        .with_context(|| format!("Missing archive entry {name}"))
}

pub fn sha(data: &[u8]) -> String {
    format!("{:x}", Sha256::digest(data))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn finished_archives_replace_existing_outputs() -> Result<()> {
        let folder = tempfile::tempdir()?;
        let path = folder.path().join("candidate.3mf");
        fs::write(&path, b"previous data")?;
        let entries = Entries::from([("mesh.model".into(), b"mesh data".to_vec())]);
        write(&path, &entries)?;
        assert_eq!(read(&path)?, entries);
        Ok(())
    }
}
