//! Private native Start-menu favorites. Data-only fixed actions, never commands.
//! Optional overrides do not modify source recipes or nested preview sessions.

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

use crate::{native_menu::MAX_PINS, recipe::NativeMenu};

const MAX_BYTES: u64 = 1024;

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SavedPins {
    schema_version: u32,
    recipe: String,
    pins: Vec<String>,
}

fn path(id: &str) -> Option<PathBuf> {
    if env::var("RICEBOWL_DE_NESTED").ok().as_deref() == Some("1") {
        return None;
    }
    let config = env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .or_else(|| env::var_os("HOME").map(|home| PathBuf::from(home).join(".config")))?;
    config.is_absolute().then(|| config.join("ricebowl/native-menu-pins").join(format!("{id}.json")))
}

/// Desktop identifiers are never file paths or executable strings. A pinned
/// desktop ID is displayed/activated only if normal XDG discovery currently
/// contains it; this syntactic check is just the untrusted persistence gate.
fn desktop_id(id: &str) -> bool {
    let Some(file) = id.strip_prefix("desktop:") else { return false; };
    file.len() >= ".desktop".len() + 1 && file.len() <= 160
        && file.ends_with(".desktop") && file.bytes().all(|byte|
            byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
}

fn valid(id: &str, menu: &NativeMenu, pins: &[String]) -> bool {
    let allowed: HashSet<&str> = menu.groups.iter()
        .flat_map(|group| group.actions.iter().map(String::as_str)).collect();
    let mut seen = HashSet::new();
    pins.len() <= MAX_PINS && pins.iter().all(|pin|
        (allowed.contains(pin.as_str()) || (id == "xp-luna-columns" && desktop_id(pin)))
            && seen.insert(pin.as_str()))
        && !id.is_empty() && id.len() <= 32
        && id.as_bytes()[0].is_ascii_lowercase()
        && id.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
}

fn parse(raw: &[u8], id: &str, menu: &NativeMenu) -> Result<Vec<String>, Box<dyn Error>> {
    let saved: SavedPins = serde_json::from_slice(raw)?;
    if saved.schema_version != 1 || saved.recipe != id || !valid(id, menu, &saved.pins) {
        return Err("Saved menu favorites do not match this rice".into());
    }
    Ok(saved.pins)
}

pub fn restore(id: &str, menu: &NativeMenu) -> Result<Vec<String>, Box<dyn Error>> {
    let Some(location) = path(id) else { return Ok(Vec::new()); };
    restore_at(&location, id, menu)
}

fn restore_at(location: &Path, id: &str, menu: &NativeMenu) -> Result<Vec<String>, Box<dyn Error>> {
    let file = match OpenOptions::new().read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC).open(location) {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
            Err(error) => return Err(error.into()),
        };
    let meta = file.metadata()?;
    if !meta.is_file() || meta.uid() != unsafe { libc::geteuid() }
        || meta.mode() & 0o077 != 0 || meta.len() > MAX_BYTES {
        return Err("Native menu favorites require a private regular file".into());
    }
    let mut bytes = Vec::new();
    file.take(MAX_BYTES + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_BYTES {
        return Err("Native menu favorites file is oversized".into());
    }
    parse(&bytes, id, menu)
}

pub fn save(id: &str, menu: &NativeMenu, pins: &[String]) -> Result<(), Box<dyn Error>> {
    let Some(location) = path(id) else { return Ok(()); };
    save_at(&location, id, menu, pins)
}

fn save_at(location: &Path, id: &str, menu: &NativeMenu,
           pins: &[String]) -> Result<(), Box<dyn Error>> {
    if !valid(id, menu, pins) { return Err("Unsupported or duplicate menu favorite".into()); }
    let directory = location.parent().ok_or("Missing favorites directory")?;
    let root = directory.parent().ok_or("Missing RiceBowl configuration directory")?;
    fs::create_dir_all(root)?;
    let root_meta = fs::symlink_metadata(root)?;
    if !root_meta.is_dir() || root_meta.file_type().is_symlink()
        || root_meta.uid() != unsafe { libc::geteuid() } {
        return Err("RiceBowl configuration directory is not owned by this user".into());
    }
    if !directory.exists() { DirBuilder::new().mode(0o700).create(directory)?; }
    let dir_meta = fs::symlink_metadata(directory)?;
    if !dir_meta.is_dir() || dir_meta.file_type().is_symlink()
        || dir_meta.uid() != unsafe { libc::geteuid() } || dir_meta.mode() & 0o077 != 0 {
        return Err("Native favorites directory must be owner-private".into());
    }
    match fs::symlink_metadata(location) {
        Ok(meta) if !meta.is_file() || meta.file_type().is_symlink()
            || meta.uid() != unsafe { libc::geteuid() } || meta.mode() & 0o077 != 0 =>
                return Err("Refusing to replace an unmanaged favorites file".into()),
        Err(error) if error.kind() != std::io::ErrorKind::NotFound => return Err(error.into()),
        _ => {}
    }
    let bytes = serde_json::to_vec(&SavedPins {
        schema_version: 1, recipe: id.to_owned(), pins: pins.to_vec(),
    })?;
    if bytes.len() as u64 > MAX_BYTES { return Err("Too many favorite bytes".into()); }
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::symlink;

    const TEST_ID: &str = "mockup-desktop";

    fn menu() -> NativeMenu {
        crate::recipe::parse(include_str!("../../../tests/fixtures/riceplate-desktop-v5.json"),
                             Some(TEST_ID)).unwrap().menu.unwrap()
    }

    fn location() -> PathBuf {
        let nonce = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let root = env::temp_dir().join(format!("riceplate-pins-{}-{nonce}", std::process::id()));
        fs::create_dir(&root).unwrap();
        root.join("ricebowl/native-menu-pins/mockup-desktop.json")
    }

    #[test]
    fn restores_private_favorites_without_changing_recipe() {
        let location = location();
        let data = menu();
        let action = data.groups[0].actions[0].clone();
        let pins = vec![action];
        save_at(&location, TEST_ID, &data, &pins).unwrap();
        assert_eq!(restore_at(&location, TEST_ID, &data).unwrap(), pins);
        assert_eq!(fs::metadata(&location).unwrap().mode() & 0o077, 0);
        assert_eq!(fs::metadata(location.parent().unwrap()).unwrap().mode() & 0o077, 0);
        fs::remove_dir_all(location.ancestors().nth(3).unwrap()).unwrap();
    }

    #[test]
    fn refuses_cross_rice_unknown_duplicate_and_traversal() {
        let data = menu();
        let first = data.groups[0].actions[0].clone();
        let saved = SavedPins { schema_version: 1, recipe: "other".into(), pins: vec![first.clone()] };
        assert!(parse(&serde_json::to_vec(&saved).unwrap(), TEST_ID, &data).is_err());
        assert!(!valid("../classic", &data, &[first.clone()]));
        assert!(!valid(TEST_ID, &data, &[first.clone(), first]));
        assert!(!valid(TEST_ID, &data, &["not-a-recipe-action".into()]));
    }

    #[test]
    fn will_not_follow_symlinks_or_overwrite_foreign_data() {
        let location = location();
        let data = menu();
        save_at(&location, TEST_ID, &data, &[]).unwrap();
        let victim = location.ancestors().nth(2).unwrap().join("untouched.txt");
        fs::write(&victim, b"KEEP").unwrap();
        fs::remove_file(&location).unwrap();
        symlink(&victim, &location).unwrap();
        assert!(restore_at(&location, TEST_ID, &data).is_err());
        assert!(save_at(&location, TEST_ID, &data, &[]).is_err());
        assert_eq!(fs::read(victim).unwrap(), b"KEEP");
        fs::remove_dir_all(location.ancestors().nth(3).unwrap()).unwrap();
    }
    #[test]
    fn xp_pins_allow_only_bounded_desktop_ids_and_never_paths() {
        let luna = crate::recipe::parse(
            include_str!("../../../examples/wayland/xp-luna-columns.json"),
            Some("xp-luna-columns")).unwrap().menu.unwrap();
        let app = "desktop:org.example.Editor.desktop".to_owned();
        assert!(valid("xp-luna-columns", &luna, &[app.clone()]));
        assert!(!valid("mockup-desktop", &menu(), &[app.clone()]));
        for invalid in ["desktop:../escape.desktop", "desktop:/tmp/code.desktop",
                        "desktop:bad name.desktop", "desktop:bad;cmd.desktop",
                        "desktop:..\\code.desktop", "menu-category:games",
                        "desktop:.desktop"] {
            assert!(!valid("xp-luna-columns", &luna, &[invalid.into()]), "{invalid}");
        }
        assert!(!valid("xp-luna-columns", &luna, &[app.clone(), app.clone()]));
        assert!(!valid("xp-luna-columns", &luna, &vec![app; MAX_PINS + 1]));
    }

}
