//! Private, bounded XDG application recents for opt-in native XP Luna only.
//! No Exec fields or user-controlled commands are stored or evaluated.

use std::{
    collections::HashSet,
    env,
    error::Error,
    fs::{self, DirBuilder, OpenOptions},
    io::{Read, Write},
    os::unix::fs::{DirBuilderExt, MetadataExt, OpenOptionsExt},
    path::{Path, PathBuf},
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

// Never traverse a substituted private history directory, including when
// reading or clearing history. The parent ricebowl directory may be shared
// with other RiceBowl settings, but must still be owned and non-symlinked.
fn check_parents(location: &Path) -> Result<(), Box<dyn Error>> {
    let directory = location.parent().ok_or("Missing recent applications directory")?;
    let root = directory.parent().ok_or("Missing RiceBowl configuration directory")?;
    for parent in [root, directory] {
        let meta = fs::symlink_metadata(parent)?;
        if !meta.is_dir() || meta.file_type().is_symlink()
            || meta.uid() != unsafe { libc::geteuid() } {
            return Err("Unsafe XP Luna history parent directory".into());
        }
    }
    if fs::symlink_metadata(directory)?.mode() & 0o077 != 0 {
        return Err("XP Luna history directory must be private".into());
    }
    Ok(())
}

pub fn restore(id: &str) -> Result<Vec<String>, Box<dyn Error>> {
    let Some(location) = path(id) else { return Ok(Vec::new()); };
    restore_at(&location, id)
}

fn restore_at(location: &Path, id: &str) -> Result<Vec<String>, Box<dyn Error>> {
    if location.parent().is_some_and(|parent| fs::symlink_metadata(parent).is_ok()) { check_parents(location)?; }
    let file = match OpenOptions::new().read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC).open(location) {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
            Err(error) => return Err(error.into()),
        };
    let meta = file.metadata()?;
    if !meta.is_file() || meta.uid() != unsafe { libc::geteuid() }
        || meta.mode() & 0o077 != 0 || meta.len() > MAX_BYTES {
        return Err("XP Luna recent applications require a private regular file".into());
    }
    let mut bytes = Vec::new();
    file.take(MAX_BYTES + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_BYTES {
        return Err("XP Luna recent applications file is oversized".into());
    }
    parse(&bytes, id)
}

pub fn save(id: &str, apps: &[String]) -> Result<(), Box<dyn Error>> {
    let Some(location) = path(id) else { return Ok(()); };
    save_at(&location, id, apps)
}

fn save_at(location: &Path, id: &str, apps: &[String]) -> Result<(), Box<dyn Error>> {
    if id != RICE_ID || !valid(apps) { return Err("Unsupported XP Luna app history".into()); }
    let directory = location.parent().ok_or("Missing recent applications directory")?;
    let root = directory.parent().ok_or("Missing RiceBowl configuration directory")?;
    fs::create_dir_all(root)?;
    let root_meta = fs::symlink_metadata(root)?;
    if !root_meta.is_dir() || root_meta.file_type().is_symlink()
        || root_meta.uid() != unsafe { libc::geteuid() } {
        return Err("RiceBowl configuration directory is not user-owned".into());
    }
    if !directory.exists() { DirBuilder::new().mode(0o700).create(directory)?; }
    let dir_meta = fs::symlink_metadata(directory)?;
    if !dir_meta.is_dir() || dir_meta.file_type().is_symlink()
        || dir_meta.uid() != unsafe { libc::geteuid() } || dir_meta.mode() & 0o077 != 0 {
        return Err("Recent applications directory must be owner-private".into());
    }
    check_parents(location)?;
    match fs::symlink_metadata(location) {
        Ok(meta) if !meta.is_file() || meta.file_type().is_symlink()
            || meta.uid() != unsafe { libc::geteuid() } || meta.mode() & 0o077 != 0 =>
                return Err("Refusing to overwrite an unmanaged history file".into()),
        Err(error) if error.kind() != std::io::ErrorKind::NotFound => return Err(error.into()),
        _ => {}
    }
    let bytes = serde_json::to_vec(&History {
        schema_version: 1, recipe: id.to_owned(), apps: apps.to_vec(),
    })?;
    if bytes.len() as u64 > MAX_BYTES { return Err("Recent applications file is oversized".into()); }
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    let temporary = directory.join(format!(".{id}-{}-{nonce}.tmp", std::process::id()));
    let result = (|| -> Result<(), Box<dyn Error>> {
        let mut file = OpenOptions::new().write(true).create_new(true).mode(0o600).open(&temporary)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
        fs::rename(&temporary, location)?;
        Ok(())
    })();
    if result.is_err() { let _ = fs::remove_file(temporary); }
    result
}

/// Explicit privacy escape hatch. No Wayland compositor or XDG app discovery
/// required; only delete an owner-private regular history file.
pub fn clear() -> Result<(), Box<dyn Error>> {
    let Some(location) = path(RICE_ID) else {
        return Err("History clearing is disabled in nested preview mode".into());
    };
    if location.parent().is_some_and(|parent| fs::symlink_metadata(parent).is_ok()) { check_parents(&location)?; }
    match fs::symlink_metadata(&location) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error.into()),
        Ok(meta) if meta.is_file() && !meta.file_type().is_symlink()
            && meta.uid() == unsafe { libc::geteuid() } && meta.mode() & 0o077 == 0 =>
                Ok(fs::remove_file(location)?),
        Ok(_) => Err("Refusing to delete an unmanaged history file".into()),
    }
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
}
