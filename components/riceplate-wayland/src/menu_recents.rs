//! Private, bounded XDG application recents for opt-in native XP Luna only.
//! No Exec fields or user-controlled commands are stored or evaluated.

use std::{
    collections::HashSet,
    env,
    error::Error,
    ffi::{CStr, CString},
    fs::{self, File},
    io::{self, Read, Write},
    os::{
        fd::{AsRawFd, FromRawFd},
        unix::{ffi::OsStrExt, fs::MetadataExt},
    },
    path::{Component, Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};
use serde::{Deserialize, Serialize};

pub const MAX_RECENT: usize = 8;
const MAX_BYTES: u64 = 2048;
const RICE_ID: &str = "xp-luna-columns";

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct History {
    schema_version: u32,
    recipe: String,
    apps: Vec<String>,
}

fn path(id: &str) -> Option<PathBuf> {
    if id != RICE_ID || env::var("RICEBOWL_DE_NESTED").ok().as_deref() == Some("1") {
        return None;
    }
    let config = env::var_os("XDG_CONFIG_HOME").map(PathBuf::from)
        .or_else(|| env::var_os("HOME").map(|home| PathBuf::from(home).join(".config")))?;
    config.is_absolute().then(|| config.join("ricebowl/native-menu-recents").join(format!("{id}.json")))
}

fn valid(apps: &[String]) -> bool {
    let mut seen = HashSet::new();
    apps.len() <= MAX_RECENT && apps.iter().all(|app| {
        let Some(id) = app.strip_prefix("desktop:") else { return false; };
        id.len() <= 160 && id.ends_with(".desktop")
            && id.bytes().all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-'))
            && seen.insert(app.as_str())
    })
}

fn parse(bytes: &[u8], id: &str) -> Result<Vec<String>, Box<dyn Error>> {
    let data: History = serde_json::from_slice(bytes)?;
    if data.schema_version != 1 || data.recipe != id || id != RICE_ID || !valid(&data.apps) {
        return Err("Invalid XP Luna recent applications".into());
    }
    Ok(data.apps)
}

// Keep the entire path walk anchored to open directory descriptors. A
// symlink-substituted parent (including an ancestor of XDG_CONFIG_HOME) is
// rejected with O_NOFOLLOW; a rename after opening cannot redirect later
// read/write/rename/unlink operations into an attacker-selected directory.
fn open_at(parent: &File, name: &CStr, flags: i32, mode: libc::mode_t) -> io::Result<File> {
    let fd = unsafe {
        libc::openat(parent.as_raw_fd(), name.as_ptr(),
                     flags | libc::O_CLOEXEC | libc::O_NOFOLLOW, mode)
    };
    if fd < 0 { return Err(io::Error::last_os_error()); }
    Ok(unsafe { File::from_raw_fd(fd) })
}

fn child_directory(parent: &File, name: &CStr, create: bool)
    -> Result<Option<File>, Box<dyn Error>>
{
    let flags = libc::O_RDONLY | libc::O_DIRECTORY;
    match open_at(parent, name, flags, 0) {
        Ok(directory) => Ok(Some(directory)),
        Err(error) if error.kind() == io::ErrorKind::NotFound && create => {
            let created = unsafe { libc::mkdirat(parent.as_raw_fd(), name.as_ptr(), 0o700) };
            if created != 0 {
                let error = io::Error::last_os_error();
                if error.kind() != io::ErrorKind::AlreadyExists {
                    return Err(error.into());
                }
            }
            Ok(Some(open_at(parent, name, flags, 0)?))
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(error.into()),
    }
}

// Walk even the XDG_CONFIG_HOME ancestors from the filesystem root using
// O_DIRECTORY|O_NOFOLLOW; a replaced ancestor can no longer retarget the
// history operation. Only the intended XDG tree is created when saving.
fn absolute_directory(path: &Path, create: bool)
    -> Result<Option<File>, Box<dyn Error>>
{
    if !path.is_absolute() { return Err("Absolute XDG configuration path required".into()); }
    let mut directory = File::open("/")?;
    for component in path.components() {
        match component {
            Component::RootDir => {}
            Component::Normal(name) => {
                let name = CString::new(name.as_bytes())?;
                let Some(next) = child_directory(&directory, &name, create)? else {
                    return Ok(None);
                };
                directory = next;
            }
            _ => return Err("Unsafe XDG configuration path component".into()),
        }
    }
    Ok(Some(directory))
}

fn history_directory(location: &Path, create: bool)
    -> Result<Option<File>, Box<dyn Error>>
{
    let directory = location.parent().ok_or("Missing recent applications directory")?;
    let root = directory.parent().ok_or("Missing RiceBowl configuration directory")?;
    let base = root.parent().ok_or("Missing XDG configuration directory")?;
    let Some(base_fd) = absolute_directory(base, create)? else { return Ok(None); };
    let root_name = CString::new(root.file_name().ok_or("Missing RiceBowl directory name")?.as_bytes())?;
    let Some(root_fd) = child_directory(&base_fd, &root_name, create)? else {
        return Ok(None);
    };
    if root_fd.metadata()?.uid() != unsafe { libc::geteuid() } {
        return Err("Unsafe RiceBowl configuration directory owner".into());
    }
    let history_name = CString::new(directory.file_name()
        .ok_or("Missing XP Luna history directory name")?.as_bytes())?;
    let Some(history_fd) = child_directory(&root_fd, &history_name, create)? else {
        return Ok(None);
    };
    let metadata = history_fd.metadata()?;
    if metadata.uid() != unsafe { libc::geteuid() } || metadata.mode() & 0o077 != 0 {
        return Err("XP Luna history directory must be owner-private".into());
    }
    Ok(Some(history_fd))
}

fn history_name(location: &Path) -> Result<CString, Box<dyn Error>> {
    Ok(CString::new(location.file_name()
        .ok_or("Missing XP Luna history filename")?.as_bytes())?)
}

fn checked_history_file(directory: &File, name: &CStr)
    -> Result<Option<File>, Box<dyn Error>>
{
    // O_NONBLOCK stops substituted FIFOs from blocking before fstat can
    // reject the non-regular file. The descriptor never follows a symlink.
    let file = match open_at(directory, name, libc::O_RDONLY | libc::O_NONBLOCK, 0) {
        Ok(file) => file,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    let metadata = file.metadata()?;
    if !metadata.is_file() || metadata.uid() != unsafe { libc::geteuid() }
        || metadata.mode() & 0o077 != 0 || metadata.nlink() != 1
        || metadata.len() > MAX_BYTES
    {
        return Err("XP Luna recent applications require a private regular file".into());
    }
    Ok(Some(file))
}

pub fn restore(id: &str) -> Result<Vec<String>, Box<dyn Error>> {
    let Some(location) = path(id) else { return Ok(Vec::new()); };
    restore_at(&location, id)
}

fn restore_from(directory: &File, name: &CStr, id: &str)
    -> Result<Vec<String>, Box<dyn Error>>
{
    let Some(file) = checked_history_file(directory, name)? else {
        return Ok(Vec::new());
    };
    let mut bytes = Vec::new();
    file.take(MAX_BYTES + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_BYTES {
        return Err("XP Luna recent applications file is oversized".into());
    }
    parse(&bytes, id)
}

fn restore_at(location: &Path, id: &str) -> Result<Vec<String>, Box<dyn Error>> {
    let Some(directory) = history_directory(location, false)? else {
        return Ok(Vec::new());
    };
    restore_from(&directory, &history_name(location)?, id)
}

pub fn save(id: &str, apps: &[String]) -> Result<(), Box<dyn Error>> {
    let Some(location) = path(id) else { return Ok(()); };
    save_at(&location, id, apps)
}

fn save_to(directory: &File, name: &CStr, id: &str, apps: &[String])
    -> Result<(), Box<dyn Error>>
{
    // A pre-existing file must be owned, private and regular. The atomic
    // rename is relative to the same already-validated directory descriptor.
    let _existing = checked_history_file(directory, name)?;
    let bytes = serde_json::to_vec(&History {
        schema_version: 1, recipe: id.to_owned(), apps: apps.to_vec(),
    })?;
    if bytes.len() as u64 > MAX_BYTES {
        return Err("Recent applications file is oversized".into());
    }
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    let temp_name = CString::new(format!(".{id}-{}-{nonce}.tmp", std::process::id()))?;
    let result = (|| -> Result<(), Box<dyn Error>> {
        let mut file = open_at(directory, &temp_name,
            libc::O_WRONLY | libc::O_CREAT | libc::O_EXCL, 0o600)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
        let renamed = unsafe {
            libc::renameat(directory.as_raw_fd(), temp_name.as_ptr(),
                           directory.as_raw_fd(), name.as_ptr())
        };
        if renamed != 0 { return Err(io::Error::last_os_error().into()); }
        directory.sync_all()?; // also make the rename durable
        Ok(())
    })();
    if result.is_err() {
        unsafe { libc::unlinkat(directory.as_raw_fd(), temp_name.as_ptr(), 0); }
    }
    result
}

fn save_at(location: &Path, id: &str, apps: &[String]) -> Result<(), Box<dyn Error>> {
    if id != RICE_ID || !valid(apps) {
        return Err("Unsupported XP Luna app history".into());
    }
    let directory = history_directory(location, true)?
        .ok_or("Cannot create XP Luna history directory")?;
    save_to(&directory, &history_name(location)?, id, apps)
}

/// Explicit privacy escape hatch, anchored to the same private directory FD.
/// A successful unlink is synced so deletion survives a sudden power loss.
pub fn clear() -> Result<(), Box<dyn Error>> {
    let Some(location) = path(RICE_ID) else {
        return Err("History clearing is disabled in nested preview mode".into());
    };
    clear_at(&location)
}

fn clear_from(directory: &File, name: &CStr) -> Result<(), Box<dyn Error>> {
    let Some(_file) = checked_history_file(directory, name)? else {
        return Ok(());
    };
    if unsafe { libc::unlinkat(directory.as_raw_fd(), name.as_ptr(), 0) } != 0 {
        return Err(io::Error::last_os_error().into());
    }
    directory.sync_all()?;
    Ok(())
}

fn clear_at(location: &Path) -> Result<(), Box<dyn Error>> {
    let Some(directory) = history_directory(location, false)? else {
        return Ok(());
    };
    clear_from(&directory, &history_name(location)?)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::symlink;

    fn location() -> PathBuf {
        let nonce = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let root = env::temp_dir().join(format!("riceplate-recents-{}-{nonce}", std::process::id()));
        fs::create_dir(&root).unwrap();
        root.join("ricebowl/native-menu-recents/xp-luna-columns.json")
    }

    #[test]
    fn private_history_roundtrips_and_does_not_run_commands() {
        let location = location();
        let entries = vec!["desktop:org.example.Editor.desktop".into(),
                           "desktop:utilities-terminal.desktop".into()];
        save_at(&location, RICE_ID, &entries).unwrap();
        assert_eq!(restore_at(&location, RICE_ID).unwrap(), entries);
        assert_eq!(fs::metadata(&location).unwrap().mode() & 0o077, 0);
        assert_eq!(fs::metadata(location.parent().unwrap()).unwrap().mode() & 0o077, 0);
        fs::remove_dir_all(location.ancestors().nth(3).unwrap()).unwrap();
    }

    #[test]
    fn repeated_saves_replace_history_without_leaking_temporary_files() {
        let location = location();
        let first = vec!["desktop:org.example.First.desktop".to_owned()];
        let second = vec!["desktop:org.example.Second.desktop".to_owned()];
        save_at(&location, RICE_ID, &first).unwrap();
        save_at(&location, RICE_ID, &second).unwrap();
        assert_eq!(restore_at(&location, RICE_ID).unwrap(), second);
        let names: Vec<_> = fs::read_dir(location.parent().unwrap()).unwrap()
            .map(|entry| entry.unwrap().file_name()).collect();
        assert_eq!(names.len(), 1);
        assert_eq!(names[0].as_os_str(), location.file_name().unwrap());
        fs::remove_dir_all(location.ancestors().nth(3).unwrap()).unwrap();
    }

    #[test]
    fn privacy_clear_removes_history_and_preserves_unmanaged_files() {
        let location = location();
        let entries = vec!["desktop:org.example.Editor.desktop".to_owned()];
        save_at(&location, RICE_ID, &entries).unwrap();
        let keep = location.parent().unwrap().join("keep.txt");
        fs::write(&keep, b"KEEP").unwrap();
        clear_at(&location).unwrap();
        assert!(!location.exists());
        assert_eq!(fs::read(&keep).unwrap(), b"KEEP");
        assert!(restore_at(&location, RICE_ID).unwrap().is_empty());
        clear_at(&location).unwrap();
        fs::remove_dir_all(location.ancestors().nth(3).unwrap()).unwrap();
    }

    #[test]
    fn invalid_history_is_rejected_without_partial_use() {
        let location = location();
        let good = "desktop:org.example.App.desktop".to_owned();
        assert!(!valid(&[good.clone(), good.clone()]));
        assert!(!valid(&["desktop:../../bad.desktop".into()]));
        assert!(!valid(&["terminal".into()]));
        assert!(!valid(&vec![good.clone(); 9]));
        for bad in [
            br#"{"schema_version":1,"recipe":"xp-luna","apps":[]}"#.as_slice(),
            br#"{"schema_version":2,"recipe":"xp-luna-columns","apps":[]}"#.as_slice(),
            br#"{"schema_version":1,"recipe":"xp-luna-columns","apps":"bad"}"#.as_slice(),
            br#"{"schema_version":1,"recipe":"xp-luna-columns","apps":[],"exec":"sh"}"#.as_slice(),
        ] {
            assert!(parse(bad, RICE_ID).is_err());
        }
        assert!(save_at(&location, "classic", &[good]).is_err());
        fs::remove_dir_all(location.ancestors().nth(3).unwrap()).unwrap();
    }

    #[test]
    fn substituted_history_parent_is_rejected() {
        let location = location();
        save_at(&location, RICE_ID, &[]).unwrap();
        let parent = location.parent().unwrap();
        let replacement = parent.with_file_name("replacement");
        fs::rename(parent, &replacement).unwrap();
        symlink(&replacement, parent).unwrap();
        assert!(restore_at(&location, RICE_ID).is_err());
        assert!(save_at(&location, RICE_ID, &[]).is_err());
        fs::remove_file(parent).unwrap();
        fs::rename(&replacement, parent).unwrap();
        fs::remove_dir_all(location.ancestors().nth(3).unwrap()).unwrap();
    }

    #[test]
    fn substituted_ricebowl_root_is_rejected_without_touching_history() {
        let location = location();
        save_at(&location, RICE_ID, &[]).unwrap();
        let root = location.parent().unwrap().parent().unwrap();
        let replacement = root.with_file_name("ricebowl-replacement");
        fs::rename(root, &replacement).unwrap();
        symlink(&replacement, root).unwrap();
        assert!(restore_at(&location, RICE_ID).is_err());
        assert!(save_at(&location, RICE_ID, &[]).is_err());
        fs::remove_file(root).unwrap();
        fs::rename(&replacement, root).unwrap();
        fs::remove_dir_all(location.ancestors().nth(3).unwrap()).unwrap();
    }

    #[test]
    fn dangling_history_directory_symlink_is_not_treated_as_missing() {
        let location = location();
        let root = location.parent().unwrap().parent().unwrap();
        fs::create_dir(root).unwrap();
        symlink(root.join("missing-target"), location.parent().unwrap()).unwrap();
        assert!(restore_at(&location, RICE_ID).is_err());
        fs::remove_dir_all(location.ancestors().nth(3).unwrap()).unwrap();
    }

    #[test]
    fn dangling_ricebowl_root_symlink_is_rejected() {
        let location = location();
        let root = location.parent().unwrap().parent().unwrap();
        symlink(root.with_file_name("missing-root"), root).unwrap();
        assert!(restore_at(&location, RICE_ID).is_err());
        fs::remove_dir_all(location.ancestors().nth(3).unwrap()).unwrap();
    }

    #[test]
    fn non_private_history_parent_is_rejected() {
        let location = location();
        save_at(&location, RICE_ID, &[]).unwrap();
        let directory = location.parent().unwrap();
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(directory, fs::Permissions::from_mode(0o755)).unwrap();
        assert!(restore_at(&location, RICE_ID).is_err());
        assert!(save_at(&location, RICE_ID, &[]).is_err());
        fs::set_permissions(directory, fs::Permissions::from_mode(0o700)).unwrap();
        fs::remove_dir_all(location.ancestors().nth(3).unwrap()).unwrap();
    }

    #[test]
    fn hardlinked_history_is_rejected_and_privacy_clear_preserves_other_link() {
        let location = location();
        let entries = vec!["desktop:org.example.Editor.desktop".to_owned()];
        save_at(&location, RICE_ID, &entries).unwrap();
        let other = location.parent().unwrap().join("other-link.json");
        fs::hard_link(&location, &other).unwrap();
        let original = fs::read(&other).unwrap();
        assert!(restore_at(&location, RICE_ID).is_err());
        assert!(save_at(&location, RICE_ID, &entries).is_err());
        assert!(clear_at(&location).is_err());
        assert_eq!(fs::read(&other).unwrap(), original);
        assert!(location.exists());
        fs::remove_dir_all(location.ancestors().nth(3).unwrap()).unwrap();
    }

    #[test]
    fn nofollow_and_private_file_rules_preserve_unmanaged_data() {
        let location = location();
        save_at(&location, RICE_ID, &[]).unwrap();
        let victim = location.ancestors().nth(2).unwrap().join("keep.txt");
        fs::write(&victim, b"KEEP").unwrap();
        fs::remove_file(&location).unwrap();
        symlink(&victim, &location).unwrap();
        assert!(restore_at(&location, RICE_ID).is_err());
        assert!(save_at(&location, RICE_ID, &[]).is_err());
        assert_eq!(fs::read(&victim).unwrap(), b"KEEP");
        fs::remove_dir_all(location.ancestors().nth(3).unwrap()).unwrap();
    }
    #[test]
    fn pinned_history_descriptor_cannot_be_redirected_after_parent_swap() {
        let location = location();
        let first = vec!["desktop:org.example.First.desktop".to_owned()];
        let second = vec!["desktop:org.example.Second.desktop".to_owned()];
        save_at(&location, RICE_ID, &first).unwrap();
        let pinned = history_directory(&location, false).unwrap().unwrap();
        let name = history_name(&location).unwrap();
        let parent = location.parent().unwrap();
        let moved = parent.with_file_name("moved-history");
        fs::rename(parent, &moved).unwrap();
        // A symlink in the original position cannot retarget the already
        // opened descriptor. This is the critical check/use race regression.
        symlink(&moved, parent).unwrap();
        assert!(restore_at(&location, RICE_ID).is_err());
        assert!(save_at(&location, RICE_ID, &second).is_err());
        assert!(clear_at(&location).is_err());
        assert_eq!(restore_from(&pinned, &name, RICE_ID).unwrap(), first);
        save_to(&pinned, &name, RICE_ID, &second).unwrap();
        assert_eq!(restore_from(&pinned, &name, RICE_ID).unwrap(), second);
        clear_from(&pinned, &name).unwrap();
        assert!(!moved.join(location.file_name().unwrap()).exists());
        assert!(fs::symlink_metadata(parent).unwrap().file_type().is_symlink());
        fs::remove_file(parent).unwrap();
        fs::rename(&moved, parent).unwrap();
        fs::remove_dir_all(location.ancestors().nth(3).unwrap()).unwrap();
    }

    #[test]
    fn symlinked_xdg_config_ancestor_is_rejected() {
        let location = location();
        let config_base = location.ancestors().nth(3).unwrap();
        let moved = config_base.with_file_name(format!(
            "{}-relocated", config_base.file_name().unwrap().to_string_lossy()));
        fs::rename(config_base, &moved).unwrap();
        symlink(&moved, config_base).unwrap();
        assert!(save_at(&location, RICE_ID, &[]).is_err());
        assert!(restore_at(&location, RICE_ID).is_err());
        assert!(clear_at(&location).is_err());
        fs::remove_file(config_base).unwrap();
        fs::remove_dir_all(moved).unwrap();
    }

    #[test]
    fn named_pipe_is_rejected_without_blocking() {
        let location = location();
        save_at(&location, RICE_ID, &[]).unwrap();
        fs::remove_file(&location).unwrap();
        let path = CString::new(location.as_os_str().as_bytes()).unwrap();
        assert_eq!(unsafe { libc::mkfifo(path.as_ptr(), 0o600) }, 0);
        assert!(restore_at(&location, RICE_ID).is_err());
        assert!(save_at(&location, RICE_ID, &[]).is_err());
        assert!(clear_at(&location).is_err());
        fs::remove_dir_all(location.ancestors().nth(3).unwrap()).unwrap();
    }

}
