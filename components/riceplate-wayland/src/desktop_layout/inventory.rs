//! Read-only, bounded XDG Desktop inventory. No shell, icon surfaces or file mutations.
//! A snapshot is tied to a pinned directory descriptor, never to a recipe command.
#![allow(dead_code)] // Integrated by the Desktop lane's future main.rs glue.

use std::{
    env,
    ffi::{CString, OsStr, OsString},
    fs::{self, File},
    io::{self, Read},
    os::{fd::{AsRawFd, FromRawFd}, unix::{ffi::OsStrExt, fs::MetadataExt}},
    path::{Component, Path, PathBuf},
};

pub const MAX_INSPECTED: usize = 512;
pub const MAX_VISIBLE: usize = 96;
const MAX_USER_DIRS_BYTES: u64 = 16 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    File,
    Directory,
    /// A data file, NOT an executable command. Explicit trust/launch policy is a later gate.
    DesktopFile,
    /// Visible but non-activatable. Never traverse this link for metadata or opening.
    Symlink,
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct Key {
    pub device: u64,
    pub inode: u64,
    pub name: OsString,
}

#[derive(Debug, Clone)]
pub struct Entry {
    pub key: Key,
    pub kind: Kind,
    pub label: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Status { Available, Missing, Disabled }

#[derive(Debug)]
pub struct Snapshot {
    pub status: Status,
    pub entries: Vec<Entry>,
    pub truncated: bool,
    pub device: Option<u64>,
    pub inode: Option<u64>,
}

impl Snapshot {
    fn empty(status: Status) -> Self {
        Self { status, entries: Vec::new(), truncated: false, device: None, inode: None }
    }

    /// A selected item is safe only while its directory and no-follow inode
    /// still match. This does not authorize execution of .desktop files.
    pub fn current_path(&self, desktop: &Path, entry: &Entry) -> io::Result<PathBuf> {
        if self.status != Status::Available
            || !self.entries.iter().any(|seen| seen.key == entry.key && seen.kind == entry.kind) {
            return Err(io::Error::new(io::ErrorKind::PermissionDenied, "Entry is not in this snapshot"));
        }
        let (Some(dev), Some(ino)) = (self.device, self.inode) else {
            return Err(io::ErrorKind::NotFound.into());
        };
        let root = open_owned_directory(desktop)?;
        let root_meta = root.metadata()?;
        if root_meta.dev() != dev || root_meta.ino() != ino {
            return Err(io::Error::new(io::ErrorKind::NotFound, "Desktop directory changed"));
        }
        let relative = Path::new(&entry.key.name);
        let anchored = PathBuf::from(format!("/proc/self/fd/{}", root.as_raw_fd())).join(relative);
        let info = fs::symlink_metadata(anchored)?;
        let kind = classify(&entry.key.name, &info);
        if kind != entry.kind || matches!(kind, Kind::Symlink | Kind::DesktopFile)
            || info.dev() != entry.key.device || info.ino() != entry.key.inode {
            return Err(io::Error::new(io::ErrorKind::NotFound, "Desktop entry replaced"));
        }
        // Revalidate the path used by the eventual external opener; a different
        // same-UID process can still race after this check, so callers must not
        // treat it as an atomic authorization for destructive operations.
        let current = open_owned_directory(desktop)?.metadata()?;
        if current.dev() != dev || current.ino() != ino {
            return Err(io::Error::new(io::ErrorKind::NotFound, "Desktop path replaced"));
        }
        Ok(desktop.join(&entry.key.name))
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DesktopLocation { Disabled, Path(PathBuf) }

/// XDG user-dirs.dirs syntax: quoted path with optional $HOME prefix.
/// Never evaluate substitutions or source the file in a shell.
pub fn resolve_desktop(home: &Path, config: Option<&str>) -> io::Result<DesktopLocation> {
    valid_absolute(home)?;
    let mut configured: Option<String> = None;
    if let Some(contents) = config {
        for line in contents.lines() {
            let line = line.trim();
            let Some(rhs) = line.strip_prefix("XDG_DESKTOP_DIR=") else { continue };
            let rhs = rhs.trim();
            let value = rhs.strip_prefix('"').and_then(|s| s.strip_suffix('"'))
                .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "Invalid XDG desktop value"))?;
            if value.contains('"') || value.contains('\\') || value.contains('\0') {
                return Err(io::Error::new(io::ErrorKind::InvalidData, "Unsafe XDG desktop value"));
            }
            configured = Some(value.to_owned());
        }
    }
    let candidate = match configured {
        Some(value) if value == "$HOME" || value == "$HOME/" => return Ok(DesktopLocation::Disabled),
        Some(value) if value.starts_with("$HOME/") =>
            home.join(value.trim_start_matches("$HOME/")),
        Some(value) if value.starts_with('/') => PathBuf::from(value),
        Some(_) => return Err(io::Error::new(io::ErrorKind::InvalidData, "Non-absolute XDG desktop value")),
        None => home.join("Desktop"),
    };
    valid_absolute(&candidate)?;
    if candidate == home { return Ok(DesktopLocation::Disabled); }
    Ok(DesktopLocation::Path(candidate))
}

pub fn current_location() -> io::Result<DesktopLocation> {
    let home = PathBuf::from(env::var_os("HOME").ok_or(io::ErrorKind::NotFound)?);
    valid_absolute(&home)?;
    let config = match env::var_os("XDG_CONFIG_HOME") {
        Some(path) => { let path = PathBuf::from(path); valid_absolute(&path)?; path },
        None => home.join(".config"),
    };
    let config_file = config.join("user-dirs.dirs");
    let contents = match File::open(&config_file) {
        Ok(file) => {
            let mut bytes = Vec::new();
            file.take(MAX_USER_DIRS_BYTES + 1).read_to_end(&mut bytes)?;
            if bytes.len() as u64 > MAX_USER_DIRS_BYTES {
                return Err(io::Error::new(io::ErrorKind::InvalidData, "XDG user-dirs file too large"));
            }
            Some(String::from_utf8(bytes).map_err(|_| io::ErrorKind::InvalidData)?)
        }
        Err(err) if err.kind() == io::ErrorKind::NotFound => None,
        Err(err) => return Err(err),
    };
    resolve_desktop(&home, contents.as_deref())
}

pub fn scan_current() -> io::Result<(DesktopLocation, Snapshot)> {
    let location = current_location()?;
    let result = match &location {
        DesktopLocation::Path(path) => scan(path)?,
        DesktopLocation::Disabled => Snapshot::empty(Status::Disabled),
    };
    Ok((location, result))
}

fn valid_absolute(path: &Path) -> io::Result<()> {
    if !path.is_absolute() || path.components().any(|part|
        matches!(part, Component::ParentDir | Component::CurDir)) {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "Invalid desktop path"));
    }
    Ok(())
}

pub(super) fn open_owned_directory(path: &Path) -> io::Result<File> {
    valid_absolute(path)?;
    // O_NOFOLLOW on the final basename alone is insufficient: a replaced
    // intermediate parent could redirect a read into another directory.
    // Walk every component relative to an already-open parent descriptor.
    let mut file = File::open("/")?;
    for part in path.components() {
        let Component::Normal(name) = part else { continue };
        let name = CString::new(name.as_bytes()).map_err(|_| io::ErrorKind::InvalidInput)?;
        let raw = unsafe { libc::openat(file.as_raw_fd(), name.as_ptr(),
            libc::O_RDONLY | libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC) };
        if raw < 0 { return Err(io::Error::last_os_error()); }
        file = unsafe { File::from_raw_fd(raw) };
    }
    let meta = file.metadata()?;
    if !meta.is_dir() || meta.uid() != unsafe { libc::geteuid() } {
        return Err(io::Error::new(io::ErrorKind::PermissionDenied, "Desktop is not owner-controlled"));
    }
    Ok(file)
}

fn classify(name: &OsStr, info: &fs::Metadata) -> Kind {
    if info.file_type().is_symlink() { Kind::Symlink }
    else if info.is_dir() { Kind::Directory }
    else if name.as_bytes().ends_with(b".desktop") && info.is_file() { Kind::DesktopFile }
    else { Kind::File }
}

pub fn scan(desktop: &Path) -> io::Result<Snapshot> {
    let root = match open_owned_directory(desktop) {
        Ok(root) => root,
        Err(error) if error.kind() == io::ErrorKind::NotFound =>
            return Ok(Snapshot::empty(Status::Missing)),
        Err(error) => return Err(error),
    };
    let root_meta = root.metadata()?;
    let pinned = PathBuf::from(format!("/proc/self/fd/{}", root.as_raw_fd()));
    let mut entries = Vec::new();
    let mut truncated = false;
    let mut inspected = 0;
    for item in fs::read_dir(&pinned)? {
        if inspected == MAX_INSPECTED { truncated = true; break; }
        inspected += 1;
        let item = item?;
        let name = item.file_name();
        if name.as_bytes().first() == Some(&b'.') { continue; }
        let info = match fs::symlink_metadata(item.path()) {
            Ok(info) => info,
            Err(error) if error.kind() == io::ErrorKind::NotFound => continue,
            Err(error) => return Err(error),
        };
        if !info.file_type().is_symlink() && !info.is_dir() && !info.is_file() {
            continue; // sockets, devices and FIFOs are never desktop activation targets.
        }
        let label = name.to_string_lossy().chars().take(128).collect();
        entries.push(Entry {
            key: Key { device: info.dev(), inode: info.ino(), name: name.clone() },
            kind: classify(&name, &info),
            label,
        });
    }
    entries.sort_by(|a, b| a.key.name.as_bytes().cmp(b.key.name.as_bytes()));
    if entries.len() > MAX_VISIBLE {
        entries.truncate(MAX_VISIBLE);
        truncated = true;
    }
    // Never publish a snapshot of a root that was swapped during enumeration.
    let current = open_owned_directory(desktop)?.metadata()?;
    if current.dev() != root_meta.dev() || current.ino() != root_meta.ino() {
        return Err(io::Error::new(io::ErrorKind::WouldBlock, "Desktop directory replaced during scan"));
    }
    Ok(Snapshot { status: Status::Available, entries, truncated,
        device: Some(root_meta.dev()), inode: Some(root_meta.ino()) })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::{ffi::OsStringExt, fs::symlink};
    use std::time::{SystemTime, UNIX_EPOCH};
    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            let n = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
            let root = env::temp_dir().join(format!("ricebowl-inventory-{}-{n}", std::process::id()));
            fs::create_dir(&root).unwrap();
            Self(root)
        }
    }
    impl Drop for Fixture { fn drop(&mut self) { let _ = fs::remove_dir_all(&self.0); } }

    #[test]
    fn xdg_config_is_not_executed_and_home_disabling_is_respected() {
        let home = Path::new("/home/example");
        assert_eq!(resolve_desktop(home, None).unwrap(),
                   DesktopLocation::Path(home.join("Desktop")));
        assert_eq!(resolve_desktop(home, Some("XDG_DESKTOP_DIR=\"$HOME/Schreibtisch\"")).unwrap(),
                   DesktopLocation::Path(home.join("Schreibtisch")));
        assert_eq!(resolve_desktop(home, Some("XDG_DESKTOP_DIR=\"$HOME/\"")).unwrap(),
                   DesktopLocation::Disabled);
        for payload in ["XDG_DESKTOP_DIR=\"$HOME/../private\"",
                        "XDG_DESKTOP_DIR=\"$(touch /tmp/pwn)\"",
                        "XDG_DESKTOP_DIR=/tmp/foo",
                        "XDG_DESKTOP_DIR=\"/tmp/\\evil\""] {
            assert!(resolve_desktop(home, Some(payload)).is_err());
        }
    }

    #[test]
    fn empty_one_unicode_non_utf8_and_inert_desktop_files() {
        let f = Fixture::new();
        assert!(scan(&f.0).unwrap().entries.is_empty());
        fs::write(f.0.join("hello.txt"), b"one").unwrap();
        let one = scan(&f.0).unwrap();
        assert_eq!(one.entries.len(), 1);
        assert_eq!(one.entries[0].kind, Kind::File);
        fs::create_dir(f.0.join("Dir 🍚")).unwrap();
        fs::write(f.0.join("broken.desktop"), b"[Desktop Entry]\nExec=sh -c evil\n").unwrap();
        let invalid = OsString::from_vec(vec![b'b', b'a', b'd', 0xff]);
        fs::write(f.0.join(&invalid), b"bytes").unwrap();
        fs::write(f.0.join(".hidden"), b"ignored").unwrap();
        let snap = scan(&f.0).unwrap();
        assert_eq!(snap.entries.len(), 4);
        assert!(snap.entries.iter().any(|e| e.kind == Kind::Directory && e.label == "Dir 🍚"));
        let unsafe_launcher = snap.entries.iter().find(|e| e.kind == Kind::DesktopFile).unwrap();
        assert!(snap.current_path(&f.0, unsafe_launcher).is_err());
        assert!(snap.entries.iter().any(|e| e.kind == Kind::DesktopFile));
        assert!(snap.entries.iter().any(|e| e.key.name == invalid));
        assert_eq!(snap.current_path(&f.0, &snap.entries[0]).unwrap().parent(), Some(f.0.as_path()));
    }

    #[test]
    fn thousands_of_files_are_bounded_and_missing_is_reported() {
        let f = Fixture::new();
        for i in 0..550 { fs::write(f.0.join(format!("file-{i:04}")), b"x").unwrap(); }
        let snap = scan(&f.0).unwrap();
        assert_eq!(snap.entries.len(), MAX_VISIBLE);
        assert!(snap.truncated);
        assert!(scan(&f.0.join("absent")).unwrap().status == Status::Missing);
    }

    #[test]
    fn no_symlink_traversal_and_replacement_revokes_access() {
        let f = Fixture::new();
        fs::write(f.0.join("target"), b"ok").unwrap();
        symlink("target", f.0.join("link")).unwrap();
        let snap = scan(&f.0).unwrap();
        let link = snap.entries.iter().find(|e| e.key.name == "link").unwrap();
        assert_eq!(link.kind, Kind::Symlink);
        assert!(snap.current_path(&f.0, link).is_err());
        let target = snap.entries.iter().find(|e| e.key.name == "target").unwrap();
        fs::remove_file(f.0.join("target")).unwrap();
        fs::write(f.0.join("target"), b"other").unwrap();
        assert!(snap.current_path(&f.0, target).is_err());
        symlink(&f.0, f.0.with_extension("alias")).unwrap();
        assert!(scan(&f.0.with_extension("alias")).is_err());
        let nested = f.0.join("parent");
        fs::create_dir(&nested).unwrap();
        fs::create_dir(nested.join("Desktop")).unwrap();
        symlink(&nested, f.0.join("parent-link")).unwrap();
        assert!(scan(&f.0.join("parent-link/Desktop")).is_err(),
                "intermediate symlinks must also be rejected");
        fs::remove_file(f.0.with_extension("alias")).unwrap();
    }
 
    #[test]
    fn unreadable_desktop_and_foreign_entries_fail_closed() {
        use std::os::unix::fs::PermissionsExt;
        let f = Fixture::new();
        fs::write(f.0.join("normal"), b"ok").unwrap();
        let snap = scan(&f.0).unwrap();
        let mut forged = snap.entries[0].clone();
        forged.key.name = OsString::from("arbitrary");
        assert!(snap.current_path(&f.0, &forged).is_err());
        if unsafe { libc::geteuid() } != 0 {
            fs::set_permissions(&f.0, fs::Permissions::from_mode(0o000)).unwrap();
            assert!(scan(&f.0).is_err());
            fs::set_permissions(&f.0, fs::Permissions::from_mode(0o700)).unwrap();
        }
    }

}
