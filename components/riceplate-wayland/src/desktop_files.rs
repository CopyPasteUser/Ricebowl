//! XDG Desktop directory inventory and safe local-file dispatch for Luna.
//!
//! The desktop is user data, never a recipe and never a source of shell code.
//! Scan only on a bounded timer or explicit refresh, not per painted frame.
//! Never enumerate symlink targets, trust .desktop Exec lines, or overwrite
//! another file during a rename. Gio remains the MIME / trash authority.

use std::{
    ffi::{OsStr, OsString, CString},
    fs, io,
    os::unix::{ffi::OsStrExt, fs::MetadataExt},
    path::{Path, PathBuf},
    process::Command,
};

/// Synthetic action IDs live only in memory, never inside a user Recipe.
pub fn action_for(kind: Kind, index: usize) -> String {
    let prefix = match kind {
        Kind::File => "desktop-file:",
        Kind::Directory => "desktop-folder:",
        Kind::Symlink => "desktop-link:",
    };
    format!("{prefix}{index}")
}
pub fn action_index(action: &str) -> Option<usize> {
    ["desktop-file:", "desktop-folder:", "desktop-link:"]
        .iter().find_map(|&prefix| action.strip_prefix(prefix))
        .and_then(|number| number.parse().ok())
}

pub const MAX_ENTRIES: usize = 48;
const MAX_SCAN: usize = 512;
const MAX_NAME_BYTES: usize = 255;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind { Directory, File, Symlink }

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Entry {
    pub name: OsString,
    pub path: PathBuf,
    pub kind: Kind,
    pub device: u64,
    pub inode: u64,
}

impl Entry {
    /// A presentation label is lossy; the original OsString is always used
    /// for filesystem operations, so invalid UTF-8 cannot alias another file.
    pub fn label(&self) -> String {
        let label = self.name.to_string_lossy();
        let mut clipped: String = label.chars().take(42).collect();
        if label.chars().count() > 42 { clipped.push('…'); }
        clipped
    }

    pub fn is_openable(&self) -> bool { self.kind != Kind::Symlink }
}

fn verify_root(root: &Path) -> io::Result<()> {
    if !root.is_absolute() {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "Desktop directory must be absolute"));
    }
    let meta = fs::symlink_metadata(root)?;
    if !meta.file_type().is_dir() || meta.uid() != unsafe { libc::geteuid() } {
        return Err(io::Error::new(io::ErrorKind::PermissionDenied, "Unsafe Desktop directory"));
    }
    Ok(())
}

fn kind(meta: &fs::Metadata) -> Option<Kind> {
    let mode = meta.file_type();
    if mode.is_symlink() { Some(Kind::Symlink) }
    else if mode.is_dir() { Some(Kind::Directory) }
    else if mode.is_file() { Some(Kind::File) }
    else { None } // no sockets/devices/FIFOs in desktop shortcuts
}

/// Reject huge or hostile directory trees without ever reading their files.
pub fn scan_at(root: &Path) -> io::Result<Vec<Entry>> {
    verify_root(root)?;
    let mut entries = Vec::new();
    let mut seen = 0usize;
    for item in fs::read_dir(root)? {
        let item = item?;
        seen += 1;
        if seen > MAX_SCAN {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "Desktop has too many entries"));
        }
        let name = item.file_name();
        let bytes = name.as_bytes();
        if bytes.first() == Some(&b'.') || bytes.is_empty() || bytes.len() > MAX_NAME_BYTES {
            continue;
        }
        // Entries may vanish between read_dir and lstat (editors often
        // atomically replace temporary files). Skip only ENOENT, not EACCES.
        let meta = match fs::symlink_metadata(item.path()) {
            Ok(meta) => meta,
            Err(error) if error.kind() == io::ErrorKind::NotFound => continue,
            Err(error) => return Err(error),
        };
        if let Some(kind) = kind(&meta) {
            entries.push(Entry { name, path: item.path(), kind,
                                 device: meta.dev(), inode: meta.ino() });
        }
    }
    // Stable raw-byte ordering: locale changes cannot retarget index clicks.
    entries.sort_unstable_by(|a,b| a.name.as_bytes().cmp(b.name.as_bytes()));
    entries.truncate(MAX_ENTRIES);
    Ok(entries)
}

#[derive(Default)]
pub struct Model {
    root: Option<PathBuf>,
    entries: Vec<Entry>,
}

impl Model {
    pub fn open() -> io::Result<Self> {
        let root = crate::luna_desktop_ipc::desktop_folder()?;
        let entries = scan_at(&root)?;
        Ok(Self { root: Some(root), entries })
    }

    pub fn entries(&self) -> &[Entry] { &self.entries }
    pub fn root(&self) -> Option<&Path> { self.root.as_deref() }

    /// Preserve the old stable snapshot on IO failures; do not convert an
    /// inaccessible Desktop into an empty list and destroy focused surfaces.
    pub fn refresh(&mut self) -> io::Result<bool> {
        let Some(root) = self.root.as_ref() else { return Ok(false) };
        let newer = scan_at(root)?;
        if newer == self.entries { return Ok(false); }
        self.entries = newer;
        Ok(true)
    }

    pub fn entry(&self, index: usize) -> Option<&Entry> { self.entries.get(index) }

    fn validated(&self, index: usize) -> io::Result<&Entry> {
        let entry = self.entry(index).ok_or_else(|| io::Error::new(
            io::ErrorKind::NotFound, "Desktop entry no longer exists"))?;
        let root = self.root.as_ref().ok_or_else(|| io::Error::new(
            io::ErrorKind::NotFound, "Desktop not available"))?;
        verify_root(root)?;
        if entry.path.parent() != Some(root.as_path()) {
            return Err(io::Error::new(io::ErrorKind::PermissionDenied, "Outside Desktop directory"));
        }
        let actual = fs::symlink_metadata(&entry.path)?;
        if kind(&actual) != Some(entry.kind) || !entry.is_openable()
            || actual.dev() != entry.device || actual.ino() != entry.inode {
            return Err(io::Error::new(io::ErrorKind::PermissionDenied,
                "Desktop entry changed or is a symlink"));
        }
        Ok(entry)
    }

    /// Create argv, not a shell command. RiceField's real documented CLI
    /// supports --theme and --separate-window for local paths; Gio retains
    /// all file MIME associations and is the fallback for local folders.
    pub fn open_command(&self, index: usize, prefer_ricefield: bool) -> io::Result<Command> {
        let entry = self.validated(index)?;
        let mut cmd = if prefer_ricefield && entry.kind == Kind::Directory {
            let mut cmd = Command::new("ricefield");
            cmd.args(["--theme", "xp-luna", "--separate-window"]);
            cmd
        } else {
            let mut cmd = Command::new("gio");
            cmd.arg("open");
            cmd
        };
        cmd.arg(&entry.path);
        Ok(cmd)
    }

    /// File operations remain in RiceField; open the containing directory
    /// with the same validated argv contract rather than reimplementing copy.
    pub fn explorer_command(&self, index: usize) -> io::Result<Command> {
        let entry = self.validated(index)?;
        let parent = entry.path.parent().ok_or_else(|| io::Error::new(
            io::ErrorKind::InvalidInput, "No containing directory"))?;
        let mut cmd = Command::new("ricefield");
        cmd.args(["--theme", "xp-luna", "--separate-window"]).arg(parent);
        Ok(cmd)
    }

    pub fn gio_explorer_command(&self, index: usize) -> io::Result<Command> {
        let entry = self.validated(index)?;
        let parent = entry.path.parent().ok_or_else(|| io::Error::new(
            io::ErrorKind::InvalidInput, "No parent directory"))?;
        let mut cmd = Command::new("gio");
        cmd.arg("open").arg(parent);
        Ok(cmd)
    }

    pub fn gio_open_command(&self, index: usize) -> io::Result<Command> {
        let entry = self.validated(index)?;
        let mut cmd = Command::new("gio");
        cmd.arg("open").arg(&entry.path);
        Ok(cmd)
    }

    /// Safe local rename: atomic RENAME_NOREPLACE, no implicit overwrite,
    /// no path separators and no traversal. Never follow an old symlink.
    #[cfg(target_os = "linux")]
    pub fn rename(&mut self, index: usize, name: &OsStr) -> io::Result<PathBuf> {
        let source = self.validated(index)?.path.clone();
        let root = self.root.as_ref().ok_or_else(|| io::Error::new(
            io::ErrorKind::NotFound, "No Desktop directory"))?;
        let bytes = name.as_bytes();
        if bytes.is_empty() || bytes.len() > MAX_NAME_BYTES
            || bytes == b"." || bytes == b".." || bytes[0] == b'.'
            || bytes.iter().any(|b| matches!(*b, b'/' | 0..=31 | 127)) {
            return Err(io::Error::new(io::ErrorKind::InvalidInput, "Unsafe rename target"));
        }
        let target = root.join(name);
        if source == target { return Ok(source); }
        let a = CString::new(source.as_os_str().as_bytes()).map_err(|_| {
            io::Error::new(io::ErrorKind::InvalidInput, "Invalid source name")
        })?;
        let b = CString::new(target.as_os_str().as_bytes()).map_err(|_| {
            io::Error::new(io::ErrorKind::InvalidInput, "Invalid destination name")
        })?;
        // RENAME_NOREPLACE is Linux-specific and fails closed when missing.
        let result = unsafe {
            libc::syscall(libc::SYS_renameat2, libc::AT_FDCWD, a.as_ptr(),
                          libc::AT_FDCWD, b.as_ptr(), libc::RENAME_NOREPLACE)
        };
        if result != 0 { return Err(io::Error::last_os_error()); }
        self.refresh()?;
        Ok(target)
    }

    /// Gio provides trash semantics; never call rm/unlink on a user file.
    pub fn trash_command(&self, index: usize) -> io::Result<Command> {
        let entry = self.validated(index)?;
        let mut cmd = Command::new("gio");
        cmd.arg("trash").arg(&entry.path);
        Ok(cmd)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{os::unix::{ffi::OsStringExt, fs::DirBuilderExt},
              time::{SystemTime, UNIX_EPOCH}};

    fn temp() -> PathBuf {
        let n = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let root = std::env::temp_dir().join(format!("riceplate-desktop-{}-{n}", std::process::id()));
        fs::DirBuilder::new().mode(0o700).create(&root).unwrap();
        root
    }

    #[test]
    fn native_actions_are_typed_and_never_interpret_path_as_command() {
        assert_eq!(action_for(Kind::Directory, 12), "desktop-folder:12");
        assert_eq!(action_for(Kind::Symlink, 9), "desktop-link:9");
        assert_eq!(action_index("desktop-file:7"), Some(7));
        assert_eq!(action_index("desktop-folder:12"), Some(12));
        assert_eq!(action_index("desktop-link:9"), Some(9));
        assert_eq!(action_index("desktop-file:../../tmp"), None);
        assert_eq!(action_index("logout"), None);
    }

    #[test]
    fn stable_listing_unicode_hidden_symlink_and_special_file_handling() {
        let root = temp();
        fs::create_dir(root.join("Bücher")).unwrap();
        fs::write(root.join("a story.txt"), b"hello").unwrap();
        fs::write(root.join(".hidden"), b"secret").unwrap();
        std::os::unix::fs::symlink("/etc/passwd", root.join("bad link")).unwrap();
        let raw = OsString::from_vec(b"raw-\xff.bin".to_vec());
        fs::write(root.join(&raw), b"raw").unwrap();
        let entries = scan_at(&root).unwrap();
        assert_eq!(entries.len(), 4);
        assert!(entries.iter().any(|e| e.name == "Bücher" && e.kind == Kind::Directory));
        assert!(entries.iter().any(|e| e.name == "bad link" && e.kind == Kind::Symlink));
        assert!(!entries.iter().any(|e| e.name == ".hidden"));
        assert!(entries.iter().any(|e| e.name == raw && e.kind == Kind::File));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn refresh_reports_actual_changes_and_does_not_destroy_state_on_error() {
        let root = temp();
        fs::write(root.join("old"), b"x").unwrap();
        let mut model = Model { root: Some(root.clone()), entries: scan_at(&root).unwrap() };
        assert!(!model.refresh().unwrap());
        fs::write(root.join("next"), b"y").unwrap();
        assert!(model.refresh().unwrap());
        assert_eq!(model.entries().len(), 2);
        fs::remove_dir_all(&root).unwrap();
        assert!(model.refresh().is_err());
        assert_eq!(model.entries().len(), 2);
    }

    #[test]
    fn opens_use_only_argv_and_gio_owns_file_mime() {
        let root = temp();
        fs::create_dir(root.join("Folder")).unwrap();
        fs::write(root.join("doc.txt"), b"x").unwrap();
        std::os::unix::fs::symlink("/etc/passwd", root.join("link")).unwrap();
        let model = Model { root: Some(root.clone()), entries: scan_at(&root).unwrap() };
        let folder = model.entries().iter().position(|e| e.name == "Folder").unwrap();
        let cmd = model.open_command(folder, true).unwrap();
        assert_eq!(cmd.get_program(), "ricefield");
        assert_eq!(cmd.get_args().count(), 4);
        let doc = model.entries().iter().position(|e| e.name == "doc.txt").unwrap();
        let cmd = model.open_command(doc, true).unwrap();
        assert_eq!(cmd.get_program(), "gio");
        assert_eq!(cmd.get_args().next().unwrap(), "open");
        let link = model.entries().iter().position(|e| e.name == "link").unwrap();
        assert!(model.open_command(link, true).is_err());
        assert!(model.trash_command(link).is_err());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    #[cfg(target_os = "linux")]
    fn rename_unicode_never_overwrites_and_rejects_traversal() {
        let root = temp();
        fs::write(root.join("old"), b"keep").unwrap();
        fs::write(root.join("target"), b"do-not-overwrite").unwrap();
        let mut model = Model { root: Some(root.clone()), entries: scan_at(&root).unwrap() };
        let id = model.entries().iter().position(|e| e.name == "old").unwrap();
        assert!(model.rename(id, OsStr::new("target")).is_err());
        assert_eq!(fs::read(root.join("target")).unwrap(), b"do-not-overwrite");
        for bad in ["../escape", "/tmp/outside", "", ".hidden", "path/name"] {
            assert!(model.rename(id, OsStr::new(bad)).is_err(), "{bad}");
        }
        let renamed = model.rename(id, OsStr::new("Grüße 🚀")).unwrap();
        assert_eq!(fs::read(renamed).unwrap(), b"keep");
        assert!(!root.join("old").exists());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn replacement_same_name_is_never_misidentified_as_original_click() {
        let root = temp();
        let path = root.join("important.txt");
        fs::write(&path, b"original").unwrap();
        let model = Model { root: Some(root.clone()), entries: scan_at(&root).unwrap() };
        fs::rename(&path, root.join("old-important.txt")).unwrap();
        fs::write(&path, b"replacement").unwrap();
        assert!(model.open_command(0, false).is_err());
        assert!(model.trash_command(0).is_err());
        assert_eq!(fs::read(path).unwrap(), b"replacement");
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn model_rejects_symlink_desktop_root() {
        let root = temp();
        let linked = root.with_extension("link");
        std::os::unix::fs::symlink(&root, &linked).unwrap();
        assert!(scan_at(&linked).is_err());
        fs::remove_file(linked).unwrap();
        fs::remove_dir_all(root).unwrap();
    }
}
