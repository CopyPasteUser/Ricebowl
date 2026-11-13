//! File-icon positions, independent of immutable recipe shortcut layouts.
//! A file is keyed by (device,inode); a rename keeps position and a replaced
//! file never inherits the deleted file's coordinates. Names are not persisted.
//! Stored layouts are owner-private and never alter the source Desktop files.

use std::{
    collections::BTreeMap, env, fs::{self, DirBuilder, OpenOptions},
    io::{self, Read, Write}, os::unix::fs::{DirBuilderExt, MetadataExt, OpenOptionsExt},
    path::{Path, PathBuf}, time::{SystemTime, UNIX_EPOCH},
};
use serde::{Deserialize, Serialize};
use crate::{desktop_files::Entry, desktop_layout::MAX_SAVED_POSITION};

const MAX_BYTES: u64 = 48 * 1024;
const MAX_FILES: usize = 48;
const MAX_OUTPUTS: usize = 8;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Point { pub x: u32, pub y: u32 }

#[derive(Debug, Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Saved {
    schema_version: u32,
    files: BTreeMap<String, BTreeMap<String, Point>>,
}

#[derive(Debug, Default)]
pub struct Store {
    files: BTreeMap<String, BTreeMap<String, Point>>,
    path: Option<PathBuf>,
}

fn identity(file: &Entry) -> String {
    format!("{:x}-{:x}", file.device, file.inode)
}
fn output_ok(name: &str) -> bool {
    !name.is_empty() && name.len() <= 64 && name.bytes().all(|c|
        c.is_ascii_alphanumeric() || matches!(c, b'.' | b'_' | b'-'))
}
fn bounded(files: &BTreeMap<String, BTreeMap<String, Point>>) -> bool {
    files.len() <= MAX_FILES
        && files.iter().all(|(key, outputs)| {
            let Some((dev, ino)) = key.split_once('-') else { return false };
            !dev.is_empty() && !ino.is_empty() && dev.len() <= 16 && ino.len() <= 16
                && dev.bytes().chain(ino.bytes()).all(|b| b.is_ascii_hexdigit())
                && outputs.len() <= MAX_OUTPUTS
                && outputs.iter().all(|(name, p)| output_ok(name)
                    && p.x <= MAX_SAVED_POSITION && p.y <= MAX_SAVED_POSITION)
        })
}

fn location() -> Option<PathBuf> {
    if env::var("RICEBOWL_DE_NESTED").as_deref() == Ok("1") { return None }
    let base = env::var_os("XDG_CONFIG_HOME").map(PathBuf::from)
        .or_else(|| env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")))?;
    base.is_absolute().then(|| base.join("ricebowl/native-file-icon-positions.json"))
}

impl Store {
    pub fn restore() -> Self {
        let Some(path) = location() else { return Self::default() };
        match read_at(&path) {
            Ok(files) => Self { files, path: Some(path) },
            Err(error) if error.kind() == io::ErrorKind::NotFound =>
                Self { files: BTreeMap::new(), path: Some(path) },
            Err(error) => {
                eprintln!("RicePlate: refusing unsafe file icon position data: {error}");
                Self { path: None, ..Self::default() }
            }
        }
    }
    pub fn get(&self, file: &Entry, output: &str) -> Option<Point> {
        self.files.get(&identity(file))?.get(output).copied()
    }
    /// A disappeared inode must not use up the bounded store forever. Keep
    /// positions across simple rename (same inode), but not delete+replace.
    pub fn retain_entries(&mut self, entries: &[Entry]) -> bool {
        let before = self.files.len();
        self.files.retain(|id, _| entries.iter().any(|item| identity(item) == *id));
        before != self.files.len()
    }
    pub fn set(&mut self, file: &Entry, output: &str, point: Point)
        -> io::Result<()>
    {
        if !output_ok(output) || point.x > MAX_SAVED_POSITION
            || point.y > MAX_SAVED_POSITION {
            return Err(io::Error::new(io::ErrorKind::InvalidInput, "Invalid output or coordinates"));
        }
        let key = identity(file);
        if !self.files.contains_key(&key) && self.files.len() >= MAX_FILES {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "Too many file positions"));
        }
        let outputs = self.files.entry(key).or_default();
        if !outputs.contains_key(output) && outputs.len() >= MAX_OUTPUTS {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "Too many output positions"));
        }
        outputs.insert(output.to_owned(), point);
        Ok(())
    }
    pub fn save(&self) -> io::Result<()> {
        let Some(path) = self.path.as_ref() else { return Ok(()) };
        write_at(path, &self.files)
    }
}

fn read_at(path: &Path) -> io::Result<BTreeMap<String, BTreeMap<String, Point>>> {
    if let Some(parent) = path.parent() {
        let meta = fs::symlink_metadata(parent)?;
        if !meta.file_type().is_dir() || meta.uid() != unsafe { libc::geteuid() }
            || meta.mode() & 0o077 != 0 {
            return Err(io::Error::new(io::ErrorKind::PermissionDenied, "Unsafe positions directory"));
        }
    }
    let file = OpenOptions::new().read(true).custom_flags(libc::O_NOFOLLOW).open(path)?;
    let meta = file.metadata()?;
    if !meta.is_file() || meta.uid() != unsafe { libc::geteuid() }
        || meta.mode() & 0o077 != 0 || meta.len() > MAX_BYTES {
        return Err(io::Error::new(io::ErrorKind::PermissionDenied, "Unsafe positions file"));
    }
    let mut content = Vec::new();
    file.take(MAX_BYTES + 1).read_to_end(&mut content)?;
    if content.len() as u64 > MAX_BYTES {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "Oversized positions"));
    }
    let data: Saved = serde_json::from_slice(&content).map_err(|error|
        io::Error::new(io::ErrorKind::InvalidData, error))?;
    if data.schema_version != 1 || !bounded(&data.files) {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "Invalid position schema"));
    }
    Ok(data.files)
}
fn write_at(path: &Path, data: &BTreeMap<String, BTreeMap<String, Point>>)
    -> io::Result<()>
{
    if !bounded(data) { return Err(io::Error::new(io::ErrorKind::InvalidData,"Invalid positions")); }
    let parent = path.parent().ok_or_else(|| io::Error::new(
        io::ErrorKind::InvalidInput, "Invalid position location"))?;
    if !parent.exists() { DirBuilder::new().recursive(true).mode(0o700).create(parent)?; }
    let meta = fs::symlink_metadata(parent)?;
    if !meta.file_type().is_dir() || meta.uid() != unsafe { libc::geteuid() }
        || meta.mode() & 0o077 != 0 {
        return Err(io::Error::new(io::ErrorKind::PermissionDenied, "Unsafe RiceBowl config directory"));
    }
    match fs::symlink_metadata(path) {
        Ok(meta) => if !meta.file_type().is_file() || meta.uid() != unsafe { libc::geteuid() }
            || meta.mode() & 0o077 != 0 {
            return Err(io::Error::new(io::ErrorKind::PermissionDenied, "Unsafe existing positions"));
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => (),
        Err(error) => return Err(error),
    }
    let data = serde_json::to_vec(&Saved { schema_version: 1, files: data.clone() })
        .map_err(io::Error::other)?;
    if data.len() as u64 > MAX_BYTES {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "Positions exceed budget"));
    }
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH)
        .map_err(|_| io::Error::new(io::ErrorKind::Other, "Clock invalid"))?.as_nanos();
    let temporary = parent.join(format!(".native-file-icon-{}-{nonce}.tmp", std::process::id()));
    let result = (|| {
        let mut file = OpenOptions::new().write(true).create_new(true).mode(0o600).open(&temporary)?;
        file.write_all(&data)?;
        file.sync_all()?;
        fs::rename(&temporary, path)?;
        Ok(())
    })();
    if result.is_err() { let _ = fs::remove_file(&temporary); }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{ffi::OsString, os::unix::fs::{symlink, PermissionsExt}};

    fn entry(dev:u64,ino:u64) -> Entry {
        Entry { name:OsString::from("renamed.txt"),path:PathBuf::from("/tmp/renamed.txt"),
                kind:crate::desktop_files::Kind::File,device:dev,inode:ino }
    }
    fn temp() -> PathBuf {
        let now=SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let base=env::temp_dir().join(format!("riceplate-file-positions-{}-{now}",std::process::id()));
        fs::DirBuilder::new().mode(0o700).create(&base).unwrap();
        base
    }
    #[test]
    fn positions_are_per_display_and_follow_file_inode_not_filename() {
        let mut store=Store::default();
        store.set(&entry(1,10),"HDMI-A-1",Point{x:24,y:144}).unwrap();
        store.set(&entry(1,10),"DP-1",Point{x:88,y:32}).unwrap();
        assert_eq!(store.get(&entry(1,10),"DP-1"),Some(Point{x:88,y:32}));
        assert_eq!(store.get(&entry(1,10),"HDMI-A-1"),Some(Point{x:24,y:144}));
        assert!(store.get(&entry(1,11),"DP-1").is_none());
        assert!(store.set(&entry(1,10),"bad/name",Point{x:0,y:0}).is_err());
        assert!(!store.retain_entries(&[entry(1,10)]));
        assert!(store.retain_entries(&[entry(1,11)]));
        assert!(store.get(&entry(1,10),"DP-1").is_none());
    }
    #[test]
    fn private_roundtrip_and_symlink_refusal() {
        let root=temp();
        let folder=root.join("config");
        DirBuilder::new().mode(0o700).create(&folder).unwrap();
        let path=folder.join("icons.json");
        let mut store=Store::default();
        store.set(&entry(5,7),"eDP-1",Point{x:200,y:160}).unwrap();
        write_at(&path,&store.files).unwrap();
        assert_eq!(read_at(&path).unwrap(),store.files);
        assert_eq!(fs::symlink_metadata(&path).unwrap().mode() & 0o077,0);
        fs::remove_file(&path).unwrap();
        let marker=root.join("marker");
        fs::write(&marker,b"must-not-change").unwrap();
        symlink(&marker,&path).unwrap();
        assert!(write_at(&path,&store.files).is_err());
        assert_eq!(fs::read(&marker).unwrap(),b"must-not-change");
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn malformed_profiles_do_not_discard_safe_saved_layout() {
        let root=temp();let path=root.join("icons.json");
        let bad=Saved {schema_version:1,files:BTreeMap::from([(
            "1-a".into(),BTreeMap::from([("../../../bad".into(),Point{x:0,y:0})]))])};
        fs::write(&path,serde_json::to_vec(&bad).unwrap()).unwrap();
        fs::set_permissions(&path,fs::Permissions::from_mode(0o600)).unwrap();
        assert!(read_at(&path).is_err());
        fs::remove_dir_all(root).unwrap();
    }
}
