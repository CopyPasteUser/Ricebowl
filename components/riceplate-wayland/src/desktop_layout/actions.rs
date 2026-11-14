//! Bounded, fail-closed file actions for the native Desktop.
//!
//! No shell evaluation, recursive file operations, background worker or
//! compositor ownership. This adapter is invoked only on an explicit UI action.
//! Move/Copy/Trash remain delegated to RiceField's UI, never emulated here.
#![allow(dead_code)] // The integration lane owns the Wayland event bindings.

use std::{
    ffi::{CString, OsStr, OsString},
    fs::{self, File},
    io,
    os::{
        fd::{AsRawFd, FromRawFd},
        unix::{ffi::OsStrExt, fs::MetadataExt},
    },
    path::{Path, PathBuf},
    process::{Child, Command},
};

use super::inventory::{self, Birth, Entry, Kind, Snapshot, Stamp, Status};

#[derive(Debug)]
pub enum ActionError {
    Disabled(&'static str),
    InvalidName,
    Stale(&'static str),
    Conflict,
    Io(io::Error),
}
impl From<io::Error> for ActionError {
    fn from(e: io::Error) -> Self { Self::Io(e) }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Backend { RiceField, Gio }

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LaunchCommand {
    pub backend: Backend,
    pub program: &'static str,
    pub arguments: Vec<OsString>,
}
impl LaunchCommand {
    pub fn command(&self) -> Command {
        let mut command = Command::new(self.program);
        command.args(&self.arguments);
        command
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LaunchPlan {
    pub preferred: LaunchCommand,
    pub fallback: Option<LaunchCommand>,
}
impl LaunchPlan {
    /// A running child must be reaped by the integration lane. Only ENOENT
    /// for the RiceField binary permits Gio fallback, matching luna_places.
    pub fn spawn(&self) -> io::Result<(Backend, Child)> {
        match self.preferred.command().spawn() {
            Ok(child) => Ok((self.preferred.backend, child)),
            Err(error) if error.kind() == io::ErrorKind::NotFound
                && self.preferred.backend == Backend::RiceField => {
                let fallback = self.fallback.as_ref().ok_or(error)?;
                fallback.command().spawn().map(|child| (fallback.backend, child))
            }
            Err(error) => Err(error),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OpenMode { Default, Explorer }

fn command(backend: Backend, program: &'static str, arguments: Vec<OsString>)
           -> LaunchCommand {
    LaunchCommand { backend, program, arguments }
}
fn gio_open(target: &Path) -> LaunchCommand {
    command(Backend::Gio, "gio", vec![
        OsString::from("open"), target.as_os_str().to_os_string(),
    ])
}
fn ricefield(target: &Path) -> LaunchCommand {
    command(Backend::RiceField, "ricefield", vec![
        OsString::from("--theme"), OsString::from("xp-luna"),
        OsString::from("--separate-window"), target.as_os_str().to_os_string(),
    ])
}

fn valid_name(name: &OsStr) -> Result<CString, ActionError> {
    let raw = name.as_bytes();
    if raw.is_empty() || raw.len() > 255 || raw == b"." || raw == b".."
        || raw.contains(&b'/') || raw.contains(&0)
        || raw.iter().any(|byte| *byte < 0x20 || *byte == 0x7f) {
        return Err(ActionError::InvalidName);
    }
    CString::new(raw).map_err(|_| ActionError::InvalidName)
}

fn birth_fd(file: &File) -> Option<Birth> {
    let empty = c"";
    let mut result = unsafe { std::mem::zeroed::<libc::statx>() };
    let code = unsafe {
        libc::statx(file.as_raw_fd(), empty.as_ptr(),
            libc::AT_EMPTY_PATH | libc::AT_SYMLINK_NOFOLLOW,
            libc::STATX_BTIME, &mut result)
    };
    (code == 0 && result.stx_mask & libc::STATX_BTIME != 0).then_some(
        Birth { secs: result.stx_btime.tv_sec, nanos: result.stx_btime.tv_nsec })
}

/// Opens source through the already checked XDG Desktop fd and captures the
/// inode, rather than dereferencing a pathname supplied by a recipe or caller.
struct Pinned {
    root: File,
    source: File,
    source_metadata: fs::Metadata,
}
fn pin(snapshot: &Snapshot, desktop: &Path, entry: &Entry)
       -> Result<Pinned, ActionError> {
    if snapshot.status != Status::Available
        || !snapshot.entries.iter().any(|candidate|
            candidate.key == entry.key && candidate.kind == entry.kind
                && candidate.stamp == entry.stamp && candidate.birth == entry.birth) {
        return Err(ActionError::Stale("Entry no longer belongs to this snapshot"));
    }
    valid_name(&entry.key.name)?;
    let root = inventory::open_owned_directory(desktop)?;
    let root_info = root.metadata()?;
    if Some(root_info.dev()) != snapshot.device || Some(root_info.ino()) != snapshot.inode {
        return Err(ActionError::Stale("XDG Desktop directory changed"));
    }
    let basename = valid_name(&entry.key.name)?;
    let raw = unsafe { libc::openat(root.as_raw_fd(), basename.as_ptr(),
        libc::O_PATH | libc::O_NOFOLLOW | libc::O_CLOEXEC) };
    if raw == -1 { return Err(ActionError::Io(io::Error::last_os_error())); }
    let source = unsafe { File::from_raw_fd(raw) };
    let info = source.metadata()?;
    let expected = match entry.kind {
        Kind::File | Kind::DesktopFile => info.is_file(),
        Kind::Directory => info.is_dir(),
        Kind::Symlink => info.file_type().is_symlink(),
    };
    let birth_valid = entry.birth.is_none_or(|birth| birth_fd(&source) == Some(birth));
    if !expected || !birth_valid || info.dev() != entry.key.device
        || info.ino() != entry.key.inode || Stamp::of(&info) != entry.stamp {
        return Err(ActionError::Stale("File replaced or modified since inventory"));
    }
    // Confirm the root pathname still refers to the pinned descriptor. The
    // kernel renameat2 below always acts within this pinned directory.
    verify_root(&root, desktop)?;
    Ok(Pinned { root, source, source_metadata: info })
}

fn verify_root(root: &File, desktop: &Path) -> Result<(), ActionError> {
    let current = inventory::open_owned_directory(desktop)?;
    let source = root.metadata()?;
    let now = current.metadata()?;
    if source.dev() != now.dev() || source.ino() != now.ino() {
        return Err(ActionError::Stale("Desktop directory was replaced"));
    }
    Ok(())
}

fn verified_path(snapshot: &Snapshot, desktop: &Path, entry: &Entry,
                 supported: bool) -> Result<PathBuf, ActionError> {
    if !supported { return Err(ActionError::Disabled("Entry type cannot be opened")); }
    let pinned = pin(snapshot, desktop, entry)?;
    if pinned.source_metadata.uid() != unsafe { libc::geteuid() } {
        return Err(ActionError::Disabled("Entry belongs to another user"));
    }
    Ok(desktop.join(&entry.key.name))
}

/// Construct a fixed-argv, inert execution plan. No process is created until
/// the user invokes the action, and callers should re-create it immediately
/// before dispatch, rather than caching a path over multiple refreshes.
pub fn prepare_open(snapshot: &Snapshot, desktop: &Path, entry: &Entry,
                    mode: OpenMode) -> Result<LaunchPlan, ActionError> {
    if matches!(entry.kind, Kind::Symlink | Kind::DesktopFile) {
        return Err(ActionError::Disabled("Symlink and .desktop execution is disabled"));
    }
    let path = verified_path(snapshot, desktop, entry, true)?;
    let directory = if entry.kind == Kind::Directory {
        path.clone()
    } else {
        desktop.to_owned()
    };
    if mode == OpenMode::Explorer || entry.kind == Kind::Directory {
        Ok(LaunchPlan { preferred: ricefield(&directory),
                        fallback: Some(gio_open(&directory)) })
    } else {
        Ok(LaunchPlan { preferred: gio_open(&path), fallback: None })
    }
}

/// Called by the integration event loop following an explicit user gesture.
/// No shell is ever involved. Return the child for integration-owned reaping.
pub fn open(snapshot: &Snapshot, desktop: &Path, entry: &Entry,
            mode: OpenMode) -> Result<(Backend, Child), ActionError> {
    let plan = prepare_open(snapshot, desktop, entry, mode)?;
    Ok(plan.spawn()?)
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Properties {
    pub name: OsString,
    pub kind: Kind,
    pub size: u64,
    pub owner_uid: u32,
    pub mode: u32,
    pub hard_links: u64,
    pub device: u64,
    pub inode: u64,
}

/// Read-only, descriptor-bound, NOFOLLOW properties. Symlinks and untrusted
/// .desktop files may be inspected but never implicitly executed.
pub fn properties(snapshot: &Snapshot, desktop: &Path, entry: &Entry)
                  -> Result<Properties, ActionError> {
    let pinned = pin(snapshot, desktop, entry)?;
    let meta = &pinned.source_metadata;
    Ok(Properties {
        name: entry.key.name.clone(), kind: entry.kind, size: meta.size(),
        owner_uid: meta.uid(), mode: meta.mode(), hard_links: meta.nlink(),
        device: meta.dev(), inode: meta.ino(),
    })
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RenameReceipt {
    pub old_name: OsString,
    pub new_name: OsString,
    /// A scan and FileSelection/FilePositions reconciliation must follow.
    pub refresh_required: bool,
}

/// Rename ONE verified file/folder within the same pinned Desktop descriptor.
/// RENAME_NOREPLACE is atomic with respect to the target name. No overwrite,
/// no traversing links, and no recursive move/copy implementation.
///
/// This reduces races but cannot make a pathname-based rename conditional on
/// an inode: another same-UID process may replace the source between the last
/// validation and renameat2. The destination is checked after the syscall;
/// ambiguous outcomes require a full rescan rather than blind retry.
pub fn rename(snapshot: &Snapshot, desktop: &Path, entry: &Entry,
              new_name: &OsStr) -> Result<RenameReceipt, ActionError> {
    if !matches!(entry.kind, Kind::File | Kind::Directory) {
        return Err(ActionError::Disabled("Launcher and symlink rename is disabled"));
    }
    let target = valid_name(new_name)?;
    if entry.key.name.as_os_str() == new_name {
        return Err(ActionError::InvalidName);
    }
    let pinned = pin(snapshot, desktop, entry)?;
    if pinned.source_metadata.uid() != unsafe { libc::geteuid() } {
        return Err(ActionError::Disabled("Entry belongs to another user"));
    }
    let source = valid_name(&entry.key.name)?;
    // Preflight is advisory only; RENAME_NOREPLACE is the atomic overwrite
    // protection even when another application creates the destination.
    verify_root(&pinned.root, desktop)?;
    let outcome = unsafe {
        libc::renameat2(pinned.root.as_raw_fd(), source.as_ptr(),
                        pinned.root.as_raw_fd(), target.as_ptr(),
                        libc::RENAME_NOREPLACE)
    };
    if outcome == -1 {
        let error = io::Error::last_os_error();
        if error.raw_os_error() == Some(libc::EEXIST) {
            return Err(ActionError::Conflict);
        }
        if error.raw_os_error() == Some(libc::ENOENT) {
            return Err(ActionError::Stale("Source disappeared before rename"));
        }
        return Err(ActionError::Io(error));
    }
    // Do not return a normal success for an unexpected source replacement.
    // The operation is already committed; the UI must rescan without retry.
    let source_after = unsafe {
        libc::openat(pinned.root.as_raw_fd(), target.as_ptr(),
            libc::O_PATH | libc::O_NOFOLLOW | libc::O_CLOEXEC)
    };
    if source_after == -1 {
        return Err(ActionError::Stale("Rename committed but destination disappeared; rescan"));
    }
    let moved = unsafe { File::from_raw_fd(source_after) };
    let result = moved.metadata()?;
    if result.dev() != pinned.source_metadata.dev()
        || result.ino() != pinned.source_metadata.ino() {
        return Err(ActionError::Stale("Rename committed on a replaced source; rescan"));
    }
    verify_root(&pinned.root, desktop)?;
    Ok(RenameReceipt { old_name: entry.key.name.clone(),
                       new_name: new_name.to_owned(), refresh_required: true })
}

/// Refresh after any external edit or committed rename. Failure leaves the
/// caller's old selection/positions untouched, so it may retry explicitly.
pub fn refresh_after_change(
    before: &Snapshot, desktop: &Path,
    selected: &mut super::file_state::FileSelection,
    positions: &mut super::file_state::FilePositions,
) -> Result<Snapshot, ActionError> {
    let fresh = inventory::scan(desktop)?;
    selected.retain_after_refresh(before, &fresh);
    positions.reconcile(before, &fresh);
    Ok(fresh)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        env,
        os::unix::{ffi::OsStringExt, fs::symlink},
        time::{SystemTime, UNIX_EPOCH},
    };

    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            let nonce = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
            let root = env::temp_dir().join(format!("ricebowl-desktop-actions-{}-{nonce}", std::process::id()));
            fs::create_dir(&root).unwrap();
            Self(root)
        }
        fn snap(&self) -> Snapshot { inventory::scan(&self.0).unwrap() }
        fn entry<'a>(&self, snap: &'a Snapshot, name: &str) -> &'a Entry {
            snap.entries.iter().find(|e| e.key.name == name).unwrap()
        }
    }
    impl Drop for Fixture { fn drop(&mut self) { let _ = fs::remove_dir_all(&self.0); } }

    #[test]
    fn open_is_fixed_argv_and_never_execs_untrusted_launchers() {
        let f = Fixture::new();
        fs::write(f.0.join("x;$(touch HACK).txt"), b"x").unwrap();
        fs::create_dir(f.0.join("Music 🍚")).unwrap();
        fs::write(f.0.join("bad.desktop"), b"[Desktop Entry]\nExec=sh -c evil").unwrap();
        symlink("Music 🍚", f.0.join("link")).unwrap();
        let snap = f.snap();
        let file = f.entry(&snap, "x;$(touch HACK).txt");
        let folder = f.entry(&snap, "Music 🍚");
        let plan = prepare_open(&snap, &f.0, file, OpenMode::Default).unwrap();
        assert_eq!(plan.preferred.program, "gio");
        assert_eq!(plan.preferred.arguments[0], "open");
        assert_eq!(plan.preferred.arguments[1], f.0.join("x;$(touch HACK).txt").as_os_str());
        assert!(plan.fallback.is_none());
        for mode in [OpenMode::Default, OpenMode::Explorer] {
            let plan = prepare_open(&snap, &f.0, folder, mode).unwrap();
            assert_eq!(plan.preferred.program, "ricefield");
            assert_eq!(plan.preferred.arguments[..3],
                       ["--theme", "xp-luna", "--separate-window"]);
            assert_eq!(plan.fallback.as_ref().unwrap().program, "gio");
        }
        for name in ["bad.desktop", "link"] {
            assert!(matches!(prepare_open(&snap, &f.0, f.entry(&snap, name),
                OpenMode::Default), Err(ActionError::Disabled(_))));
            assert!(properties(&snap, &f.0, f.entry(&snap, name)).is_ok());
        }
        // Constructor has no effect; no command was started in this test.
        assert!(!f.0.join("HACK").exists());
    }

    #[test]
    fn rename_no_replace_conflict_and_unicode_directory() {
        let f = Fixture::new();
        fs::write(f.0.join("a"), b"original").unwrap();
        fs::write(f.0.join("occupied"), b"KEEP").unwrap();
        fs::create_dir(f.0.join("Folder")).unwrap();
        let snap = f.snap();
        let a = f.entry(&snap, "a");
        assert!(matches!(rename(&snap, &f.0, a, OsStr::new("occupied")), Err(ActionError::Conflict)));
        assert_eq!(fs::read(f.0.join("occupied")).unwrap(), b"KEEP");
        assert_eq!(fs::read(f.0.join("a")).unwrap(), b"original");
        let receipt = rename(&snap, &f.0, a, OsStr::new("geändert 🍚")).unwrap();
        assert!(receipt.refresh_required);
        assert_eq!(receipt.new_name, "geändert 🍚");
        assert!(!f.0.join("a").exists());
        assert_eq!(fs::read(f.0.join("geändert 🍚")).unwrap(), b"original");
        let newer = f.snap();
        rename(&newer, &f.0, f.entry(&newer, "Folder"), OsStr::new("Ordner")).unwrap();
        assert!(f.0.join("Ordner").is_dir());
    }

    #[test]
    fn reject_traversal_empty_dot_control_nul_and_stale_source() {
        let f = Fixture::new();
        fs::write(f.0.join("a"), b"DATA").unwrap();
        let snap = f.snap();
        let a = f.entry(&snap, "a");
        for name in ["", ".", "..", "../escape", "/tmp/no", "bad\nname", "a\0b"] {
            assert!(matches!(rename(&snap, &f.0, a, OsStr::new(name)),
                             Err(ActionError::InvalidName)));
        }
        let too_long = OsString::from("b".repeat(256));
        assert!(matches!(rename(&snap, &f.0, a, &too_long),
                         Err(ActionError::InvalidName)));
        fs::remove_file(f.0.join("a")).unwrap();
        assert!(rename(&snap, &f.0, a, OsStr::new("renamed")).is_err());
        assert!(!f.0.join("renamed").exists());
    }

    #[test]
    fn raw_filename_bytes_and_hardlinks_have_no_overwrite_path() {
        let f = Fixture::new();
        let raw = OsString::from_vec(vec![b'r', b'a', b'w', 0xfe]);
        let replacement = OsString::from_vec(vec![b'n', b'e', b'w', 0xfd]);
        fs::write(f.0.join(&raw), b"contents").unwrap();
        fs::hard_link(f.0.join(&raw), f.0.join("alias")).unwrap();
        let snap = f.snap();
        let old = snap.entries.iter().find(|e| e.key.name == raw).unwrap();
        let attr = properties(&snap, &f.0, old).unwrap();
        assert_eq!(attr.hard_links, 2);
        rename(&snap, &f.0, old, &replacement).unwrap();
        assert_eq!(fs::read(f.0.join(&replacement)).unwrap(), b"contents");
        assert_eq!(fs::read(f.0.join("alias")).unwrap(), b"contents");
        assert!(f.0.join(&raw).symlink_metadata().is_err());
    }

    #[test]
    fn rename_updates_selection_and_positions_with_rescan() {
        let f = Fixture::new();
        fs::write(f.0.join("before"), b"ok").unwrap();
        let before = f.snap();
        let old = f.entry(&before, "before");
        let mut selected = super::super::file_state::FileSelection::default();
        selected.select(&old.key, false);
        let mut positions = super::super::file_state::FilePositions::default();
        positions.set(&old.key, "eDP-1",
            crate::icon_positions::Coordinates { x: 100, y: 200 }).unwrap();
        rename(&before, &f.0, old, OsStr::new("after")).unwrap();
        let after = refresh_after_change(&before, &f.0, &mut selected, &mut positions).unwrap();
        let key = &after.entries[0].key;
        let birth_stable = old.birth.is_some() && old.birth == after.entries[0].birth;
        assert_eq!(selected.contains(key), birth_stable);
        if birth_stable {
            assert_eq!(positions.coordinates(key, "eDP-1"),
                       Some(crate::icon_positions::Coordinates { x: 100, y: 200 }));
        } else {
            assert!(positions.coordinates(key, "eDP-1").is_none());
        }
    }

    #[test]
    fn symlinked_root_and_outside_destination_are_never_renamed() {
        let f = Fixture::new();
        let desktop = f.0.join("Desktop");
        fs::create_dir(&desktop).unwrap();
        fs::write(desktop.join("a"), b"desktop").unwrap();
        let snap = inventory::scan(&desktop).unwrap();
        let original = snap.entries.first().unwrap();
        let outside = f.0.join("outside");
        fs::create_dir(&outside).unwrap();
        fs::write(outside.join("a"), b"KEEP").unwrap();
        fs::rename(&desktop, f.0.join("moved")).unwrap();
        symlink(&outside, &desktop).unwrap();
        assert!(rename(&snap, &desktop, original, OsStr::new("b")).is_err());
        assert_eq!(fs::read(outside.join("a")).unwrap(), b"KEEP");
        assert!(!outside.join("b").exists());
    }

    #[test]
    fn source_swap_and_missing_desktop_return_recoverable_errors() {
        let f = Fixture::new();
        fs::write(f.0.join("item"), b"old").unwrap();
        let snap = f.snap();
        let entry = f.entry(&snap, "item");
        fs::remove_file(f.0.join("item")).unwrap();
        symlink("/etc/passwd", f.0.join("item")).unwrap();
        assert!(rename(&snap, &f.0, entry, OsStr::new("renamed")).is_err());
        assert!(prepare_open(&snap, &f.0, entry, OpenMode::Default).is_err());
        assert!(!f.0.join("renamed").exists());
        fs::remove_file(f.0.join("item")).unwrap();
        assert!(rename(&snap, &f.0, entry, OsStr::new("renamed")).is_err());
    }
}
