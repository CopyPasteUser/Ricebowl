//! One-shot XP Luna clock preference read; no watcher or per-frame disk I/O.
//! Invalid files never change non-Luna recipes and always fall back to 24h.
use chrono::NaiveTime;
use serde::Deserialize;
use std::{
    env,
    fs::{self, OpenOptions},
    io::{self, Read},
    os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt},
    path::{Path, PathBuf},
};

const MAX_BYTES: u64 = 256;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Deserialize)]
pub enum ClockFormat {
    #[default]
    #[serde(rename = "24h")]
    Hour24,
    #[serde(rename = "12h")]
    Hour12,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SavedClock {
    version: u8,
    clock_format: ClockFormat,
}

fn parse(data: &[u8]) -> Option<ClockFormat> {
    let state: SavedClock = serde_json::from_slice(data).ok()?;
    (state.version == 1).then_some(state.clock_format)
}

pub fn format_time(now: NaiveTime, format: ClockFormat) -> String {
    match format {
        ClockFormat::Hour24 => now.format("%H:%M").to_string(),
        ClockFormat::Hour12 => now.format("%-I:%M %p").to_string(),
    }
}

fn path() -> Option<PathBuf> {
    let root = env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .or_else(|| env::var_os("HOME").map(|home| PathBuf::from(home).join(".config")))?;
    if !root.is_absolute() { return None; }
    Some(root.join("ricebowl/luna-panel.json"))
}

fn read_private(path: &Path) -> io::Result<Option<ClockFormat>> {
    let Some(directory) = path.parent() else { return Ok(None); };
    let parent = fs::symlink_metadata(directory)?;
    let uid = unsafe { libc::geteuid() };
    if !parent.is_dir() || parent.uid() != uid
        || parent.permissions().mode() & 0o022 != 0
    {
        return Ok(None);
    }
    let mut file = OpenOptions::new().read(true).custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK).open(path)?;
    let meta = file.metadata()?;
    if !meta.is_file() || meta.uid() != uid
        || meta.permissions().mode() & 0o077 != 0 || meta.len() > MAX_BYTES
    {
        return Ok(None);
    }
    let mut content = Vec::with_capacity(meta.len() as usize);
    file.take(MAX_BYTES + 1).read_to_end(&mut content)?;
    if content.len() as u64 > MAX_BYTES { return Ok(None); }
    Ok(parse(&content))
}

/// Read once when the XP Luna recipe starts. Never change the existing generic
/// desktop clock, never create files and never trust a symlink as configuration.
pub fn load() -> ClockFormat {
    let Some(path) = path() else { return ClockFormat::Hour24 };
    match read_private(&path) {
        Ok(Some(format)) => format,
        Ok(None) => ClockFormat::Hour24,
        Err(error) if error.kind() == io::ErrorKind::NotFound =>
            ClockFormat::Hour24,
        Err(error) => {
            eprintln!("RicePlate: Luna clock preference ignored: {error}");
            ClockFormat::Hour24
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn format_is_unambiguous_at_midnight_noon_and_evening() {
        let midnight = NaiveTime::from_hms_opt(0, 5, 0).unwrap();
        let noon = NaiveTime::from_hms_opt(12, 5, 0).unwrap();
        let evening = NaiveTime::from_hms_opt(21, 7, 0).unwrap();
        assert_eq!(format_time(midnight, ClockFormat::Hour24), "00:05");
        assert_eq!(format_time(midnight, ClockFormat::Hour12), "12:05 AM");
        assert_eq!(format_time(noon, ClockFormat::Hour12), "12:05 PM");
        assert_eq!(format_time(evening, ClockFormat::Hour12), "9:07 PM");
    }

    #[test]
    fn private_config_reader_rejects_symlinks_and_public_permissions() {
        use std::os::unix::fs::{DirBuilderExt, symlink};
        use std::time::{SystemTime, UNIX_EPOCH};
        let stamp = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let dir = env::temp_dir().join(format!(
            "ricebowl-luna-clock-{}-{stamp}", std::process::id()));
        fs::DirBuilder::new().mode(0o700).create(&dir).unwrap();
        let file = dir.join("luna-panel.json");
        let other = dir.join("other.json");
        fs::write(&file, br#"{"version":1,"clock_format":"12h"}"#).unwrap();
        fs::set_permissions(&file, fs::Permissions::from_mode(0o600)).unwrap();
        assert_eq!(read_private(&file).unwrap(), Some(ClockFormat::Hour12));
        fs::set_permissions(&file, fs::Permissions::from_mode(0o644)).unwrap();
        assert_eq!(read_private(&file).unwrap(), None);
        fs::remove_file(&file).unwrap();
        fs::write(&other, br#"{"version":1,"clock_format":"24h"}"#).unwrap();
        symlink(&other, &file).unwrap();
        assert!(read_private(&file).is_err());
        fs::remove_file(&file).unwrap();
        fs::remove_file(&other).unwrap();
        fs::remove_dir(&dir).unwrap();
    }

    #[test]
    fn preferences_require_the_exact_versioned_schema() {
        assert_eq!(parse(br#"{"version":1,"clock_format":"12h"}"#), Some(ClockFormat::Hour12));
        assert_eq!(parse(br#"{"version":1,"clock_format":"24h"}"#), Some(ClockFormat::Hour24));
        for invalid in [
            br#"{"version":2,"clock_format":"12h"}"#.as_slice(),
            br#"{"version":1,"clock_format":"12h","shell":"evil"}"#.as_slice(),
            br#"{"version":1,"clock_format":"system"}"#.as_slice(),
            br#"{"version":true,"clock_format":"12h"}"#.as_slice(),
            br#"{ "version":1 }"#.as_slice(),
        ] {
            assert_eq!(parse(invalid), None);
        }
    }
}
