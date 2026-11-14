//! File-icon selection and per-output coordinates, separate from the seven
//! immutable recipe/system shortcuts. No Wayland objects or file operations.
#![allow(dead_code)] // Consumed by the future compositor glue.

use std::{
    collections::{BTreeMap, BTreeSet},
    env,
    fs::{self, File, OpenOptions},
    io::{self, Read, Write},
    os::unix::{ffi::OsStrExt, fs::{DirBuilderExt, MetadataExt, OpenOptionsExt}},
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use super::inventory::{Entry, Key, Snapshot};
use crate::{icon_positions::Coordinates, desktop_layout::MAX_SAVED_POSITION};

const MAX_BYTES: u64 = 128 * 1024;
const MAX_RECORDS: usize = 256;
const MAX_OUTPUTS: usize = 8;

fn identity(k: &Key) -> (u64, u64) { (k.device, k.inode) }

/// Only transfer selection and coordinates across a rename when a device/inode
/// pair occurs exactly once in both snapshots (never conflate hardlinks).
fn successor(before: &Snapshot, after: &Snapshot, old: &Key) -> Option<Key> {
    if after.entries.iter().any(|e| &e.key == old) { return Some(old.clone()); }
    let id = identity(old);
    if before.entries.iter().filter(|e| identity(&e.key) == id).count() != 1 {
        return None;
    }
    let mut matching = after.entries.iter().filter(|e| identity(&e.key) == id);
    let candidate = matching.next()?;
    matching.next().is_none().then(|| candidate.key.clone())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ChooseMode { Replace, Toggle, Range }

#[derive(Debug, Default)]
pub struct FileSelection {
    selected: BTreeSet<Key>,
    anchor: Option<Key>,
}

impl FileSelection {
    pub fn count(&self) -> usize { self.selected.len() }
    pub fn contains(&self, key: &Key) -> bool { self.selected.contains(key) }
    pub fn clear(&mut self) { self.selected.clear(); self.anchor = None; }

    pub fn select(&mut self, key: &Key, toggle: bool) {
        if toggle {
            if !self.selected.remove(key) { self.selected.insert(key.clone()); }
        } else {
            self.selected.clear();
            self.selected.insert(key.clone());
        }
        self.anchor = Some(key.clone());
    }

    /// Mouse and keyboard use the same policy. A stale key, including one
    /// removed between selection and event handling, cannot be selected.
    pub fn choose(&mut self, key: &Key, mode: ChooseMode, visible: &[Entry]) -> bool {
        let Some(index) = visible.iter().position(|entry| &entry.key == key) else {
            return false;
        };
        match mode {
            ChooseMode::Replace => self.select(key, false),
            ChooseMode::Toggle => self.select(key, true),
            ChooseMode::Range => {
                let start = self.anchor.as_ref()
                    .and_then(|anchor| visible.iter().position(|item| &item.key == anchor))
                    .unwrap_or(index);
                self.selected = visible[start.min(index)..=start.max(index)]
                    .iter().map(|entry| entry.key.clone()).collect();
                self.anchor = visible.get(start).map(|entry| entry.key.clone());
            }
        }
        true
    }

    pub fn select_all(&mut self, visible: &[Entry]) {
        self.selected = visible.iter().map(|e| e.key.clone()).collect();
        self.anchor = visible.first().map(|e| e.key.clone());
    }

    pub fn retain_after_refresh(&mut self, before: &Snapshot, after: &Snapshot) {
        self.selected = self.selected.iter()
            .filter_map(|key| successor(before, after, key)).collect();
        self.anchor = self.anchor.as_ref().and_then(|key| successor(before, after, key));
        if self.anchor.as_ref().is_some_and(|key| !self.selected.contains(key)) {
            self.anchor = self.selected.iter().next().cloned();
        }
    }
}

fn key_id(key: &Key) -> String {
    let mut h = Sha256::new();
    h.update(key.device.to_le_bytes());
    h.update(key.inode.to_le_bytes());
    h.update(key.name.as_bytes());
    format!("{:x}", h.finalize())
}

fn safe_output(name: &str) -> bool {
    !name.is_empty() && name.len() <= 64 && name.bytes().all(|byte|
        byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Position {
    output: String,
    x: u32,
    y: u32,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FilePositions { records: BTreeMap<String, Position> }

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Stored { schema_version: u32, records: BTreeMap<String, Position> }

impl FilePositions {
    pub fn record_count(&self) -> usize { self.records.len() }

    /// A newly detected file lives on primary only until dragged elsewhere.
    /// An offline assigned output temporarily falls back to primary.
    pub fn visible_on(&self, key: &Key, name: &str, primary: bool,
                      connected: &[String]) -> bool {
        match self.records.get(&key_id(key)) {
            None => primary,
            Some(saved) if connected.iter().any(|output| output == &saved.output) =>
                name == saved.output,
            Some(_) => primary,
        }
    }

    pub fn coordinates(&self, key: &Key, output: &str) -> Option<Coordinates> {
        self.records.get(&key_id(key)).filter(|r| r.output == output)
            .map(|r| Coordinates { x: r.x, y: r.y })
    }

    pub fn set(&mut self, key: &Key, output: &str, coords: Coordinates)
               -> io::Result<()> {
        if !safe_output(output) || coords.x > MAX_SAVED_POSITION
            || coords.y > MAX_SAVED_POSITION {
            return Err(io::ErrorKind::InvalidInput.into());
        }
        let digest = key_id(key);
        if !self.records.contains_key(&digest) && self.records.len() >= MAX_RECORDS {
            return Err(io::Error::new(io::ErrorKind::InvalidInput, "Too many file positions"));
        }
        let unique_outputs: BTreeSet<_> = self.records.values().map(|r| &r.output).collect();
        if !self.records.values().any(|r| r.output == output) && unique_outputs.len() >= MAX_OUTPUTS {
            return Err(io::Error::new(io::ErrorKind::InvalidInput, "Too many displays"));
        }
        self.records.insert(digest, Position {
            output: output.to_owned(), x: coords.x, y: coords.y,
        });
        Ok(())
    }

    pub fn reconcile(&mut self, before: &Snapshot, after: &Snapshot) {
        // A truncated/unavailable scan is incomplete: do not discard icons
        // merely because a resource fell outside the visible window or the
        // XDG directory was temporarily removed.
        if after.truncated || before.truncated
            || after.status != super::inventory::Status::Available
            || before.status != super::inventory::Status::Available { return; }
        let mut renamed = Vec::new();
        for old in &before.entries {
            let old_id = key_id(&old.key);
            if let Some(position) = self.records.remove(&old_id) {
                if let Some(new_key) = successor(before, after, &old.key) {
                    renamed.push((key_id(&new_key), position));
                }
            }
        }
        for (key, position) in renamed { self.records.insert(key, position); }
        // Also collect stale entries loaded from prior sessions, even when
        // they were never visible in the immediately preceding snapshot.
        let live: BTreeSet<_> = after.entries.iter().map(|e| key_id(&e.key)).collect();
        self.records.retain(|id, _| live.contains(id));
    }

    fn decode(raw: &[u8]) -> io::Result<Self> {
        let stored: Stored = serde_json::from_slice(raw)
            .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;
        if stored.schema_version != 1 || stored.records.len() > MAX_RECORDS
            || stored.records.keys().any(|s| s.len() != 64
                || !s.bytes().all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase()))
            || stored.records.values().any(|r|
                !safe_output(&r.output) || r.x > MAX_SAVED_POSITION || r.y > MAX_SAVED_POSITION)
            || stored.records.values().map(|r| &r.output).collect::<BTreeSet<_>>().len() > MAX_OUTPUTS {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "Invalid file-icon positions"));
        }
        Ok(Self { records: stored.records })
    }

    pub fn load_at(path: &Path) -> io::Result<Self> {
        let file = match OpenOptions::new().read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC).open(path) {
            Ok(file) => file,
            Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(Self::default()),
            Err(e) => return Err(e),
        };
        let meta = file.metadata()?;
        if !meta.is_file() || meta.uid() != unsafe { libc::geteuid() }
            || meta.mode() & 0o077 != 0 || meta.len() > MAX_BYTES {
            return Err(io::Error::new(io::ErrorKind::PermissionDenied, "Non-private file-icon positions"));
        }
        let mut bytes = Vec::new();
        file.take(MAX_BYTES + 1).read_to_end(&mut bytes)?;
        if bytes.len() as u64 > MAX_BYTES { return Err(io::ErrorKind::InvalidData.into()); }
        Self::decode(&bytes)
    }

    /// The caller supplies an owner-private directory; reject a symlinked
    /// directory or existing symlink destination before atomic replacement.
    pub fn save_at(&self, path: &Path) -> io::Result<()> {
        let parent = path.parent().ok_or(io::ErrorKind::InvalidInput)?;
        let dir = fs::symlink_metadata(parent)?;
        if !dir.is_dir() || dir.file_type().is_symlink()
            || dir.uid() != unsafe { libc::geteuid() } || dir.mode() & 0o077 != 0 {
            return Err(io::Error::new(io::ErrorKind::PermissionDenied, "Non-private config directory"));
        }
        if let Ok(existing) = fs::symlink_metadata(path) {
            if !existing.is_file() || existing.file_type().is_symlink()
                || existing.uid() != unsafe { libc::geteuid() } || existing.mode() & 0o077 != 0 {
                return Err(io::Error::new(io::ErrorKind::PermissionDenied, "Unsafe position file occupant"));
            }
        }
        let bytes = serde_json::to_vec(&Stored { schema_version: 1,
            records: self.records.clone() }).map_err(io::Error::other)?;
        if bytes.len() as u64 > MAX_BYTES { return Err(io::ErrorKind::InvalidInput.into()); }
        let n = SystemTime::now().duration_since(UNIX_EPOCH)
            .map_err(io::Error::other)?.as_nanos();
        let temp = parent.join(format!(".native-file-positions-{}-{n}.tmp", std::process::id()));
        let result = (|| {
            let mut file = OpenOptions::new().write(true).create_new(true).mode(0o600).open(&temp)?;
            file.write_all(&bytes)?;
            file.sync_all()?;
            fs::rename(&temp, path)
        })();
        if result.is_err() { let _ = fs::remove_file(temp); }
        result
    }

    pub fn default_path() -> io::Result<Option<PathBuf>> {
        if env::var("RICEBOWL_DE_NESTED").ok().as_deref() == Some("1") { return Ok(None); }
        let home = PathBuf::from(env::var_os("HOME").ok_or(io::ErrorKind::NotFound)?);
        let base = env::var_os("XDG_CONFIG_HOME").map(PathBuf::from)
            .unwrap_or_else(|| home.join(".config"));
        if !base.is_absolute() { return Err(io::ErrorKind::InvalidInput.into()); }
        Ok(Some(base.join("ricebowl/native-file-positions.json")))
    }

    pub fn prepare_storage(path: &Path) -> io::Result<()> {
        let directory = path.parent().ok_or(io::ErrorKind::InvalidInput)?;
        let config = directory.parent().ok_or(io::ErrorKind::InvalidInput)?;
        // Only create one level after validating that its owner controls it.
        let info = fs::symlink_metadata(config)?;
        if !info.is_dir() || info.file_type().is_symlink()
            || info.uid() != unsafe { libc::geteuid() } {
            return Err(io::Error::new(io::ErrorKind::PermissionDenied, "Invalid XDG config root"));
        }
        if !directory.exists() {
            fs::DirBuilder::new().mode(0o700).create(directory)?;
        }
        let info = fs::symlink_metadata(directory)?;
        if !info.is_dir() || info.file_type().is_symlink()
            || info.uid() != unsafe { libc::geteuid() } || info.mode() & 0o077 != 0 {
            return Err(io::Error::new(io::ErrorKind::PermissionDenied, "Invalid position directory"));
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use super::super::inventory::{scan, Status};
    use std::os::unix::fs::symlink;

    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            let n = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
            let path = env::temp_dir().join(format!("ricebowl-file-state-{}-{n}", std::process::id()));
            fs::DirBuilder::new().mode(0o700).create(&path).unwrap();
            Self(path)
        }
    }
    impl Drop for Fixture { fn drop(&mut self) { let _ = fs::remove_dir_all(&self.0); } }

    #[test]
    fn rename_preserves_selection_and_position_but_delete_revokes_both() {
        let f = Fixture::new();
        fs::write(f.0.join("a"), b"hello").unwrap();
        let old = scan(&f.0).unwrap();
        let key = &old.entries[0].key;
        let mut selection = FileSelection::default();
        selection.select(key, false);
        let mut positions = FilePositions::default();
        positions.set(key, "eDP-1", Coordinates { x: 300, y: 120 }).unwrap();
        fs::rename(f.0.join("a"), f.0.join("b")).unwrap();
        let changed = scan(&f.0).unwrap();
        selection.retain_after_refresh(&old, &changed);
        positions.reconcile(&old, &changed);
        assert!(selection.contains(&changed.entries[0].key));
        assert_eq!(positions.coordinates(&changed.entries[0].key, "eDP-1"),
                   Some(Coordinates { x: 300, y: 120 }));
        fs::remove_file(f.0.join("b")).unwrap();
        let gone = scan(&f.0).unwrap();
        assert_eq!(gone.status, Status::Available);
        selection.retain_after_refresh(&changed, &gone);
        positions.reconcile(&changed, &gone);
        assert_eq!(selection.count(), 0);
        assert_eq!(positions.record_count(), 0);
    }

    #[test]
    fn output_disconnection_falls_back_to_primary_without_losing_position() {
        let f = Fixture::new();
        fs::write(f.0.join("a"), b"x").unwrap();
        let key = &scan(&f.0).unwrap().entries[0].key.clone();
        let mut positions = FilePositions::default();
        assert!(positions.visible_on(key, "eDP-1", true, &[]));
        positions.set(key, "HDMI-A-1", Coordinates { x: 500, y: 500 }).unwrap();
        assert!(!positions.visible_on(key, "eDP-1", true, &["eDP-1".into(), "HDMI-A-1".into()]));
        assert!(positions.visible_on(key, "HDMI-A-1", false, &["eDP-1".into(), "HDMI-A-1".into()]));
        assert!(positions.visible_on(key, "eDP-1", true, &["eDP-1".into()]));
        assert_eq!(positions.coordinates(key, "HDMI-A-1"),
                   Some(Coordinates { x: 500, y: 500 }));
    }

    #[test]
    fn owner_private_persistence_roundtrip_corrupt_and_symlink_rejected() {
        let f = Fixture::new();
        let data = f.0.join("positions.json");
        let mut positions = FilePositions::default();
        fs::write(f.0.join("a"), b"x").unwrap();
        let snap = scan(&f.0).unwrap();
        positions.set(&snap.entries[0].key, "eDP-1",
                      Coordinates { x: 30, y: 50 }).unwrap();
        positions.save_at(&data).unwrap();
        assert_eq!(FilePositions::load_at(&data).unwrap(), positions);
        fs::write(&data, b"invalid JSON").unwrap();
        assert!(FilePositions::load_at(&data).is_err());
        fs::remove_file(&data).unwrap();
        let target = f.0.join("protected");
        fs::write(&target, b"KEEP").unwrap();
        symlink(&target, &data).unwrap();
        assert!(positions.save_at(&data).is_err());
        assert_eq!(fs::read(&target).unwrap(), b"KEEP");
    }
 
    #[test]
    fn bounded_range_selection_rejects_stale_entries_and_does_not_cross_visible_set() {
        let f = Fixture::new();
        for name in ["a", "b", "c", "d"] { fs::write(f.0.join(name), b"x").unwrap(); }
        let snap = scan(&f.0).unwrap();
        let mut state = FileSelection::default();
        assert!(state.choose(&snap.entries[0].key, ChooseMode::Replace, &snap.entries));
        assert!(state.choose(&snap.entries[2].key, ChooseMode::Range, &snap.entries));
        assert_eq!(state.count(), 3);
        assert!(state.choose(&snap.entries[1].key, ChooseMode::Toggle, &snap.entries));
        assert_eq!(state.count(), 2);
        fs::remove_file(f.0.join("c")).unwrap();
        let after = scan(&f.0).unwrap();
        state.retain_after_refresh(&snap, &after);
        assert_eq!(state.count(), 1);
        assert!(!state.choose(&snap.entries[2].key, ChooseMode::Replace, &after));
        assert_eq!(state.count(), 1);
    }

}
