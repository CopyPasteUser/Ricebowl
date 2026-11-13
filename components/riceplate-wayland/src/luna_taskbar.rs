//! XP Luna-only taskbar behavior. One private read at login, no watcher,
//! shell evaluation, global XFCE changes or auto-start side effects.
use serde::Deserialize;
use std::{env, fs::{self, OpenOptions}, io::{self, Read},
          os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt},
          path::{Path, PathBuf}};

const MAX_BYTES: u64 = 256;
pub const HANDLE_HEIGHT: u32 = 3;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Options {
    pub auto_hide: bool,
    pub quick_launch: bool,
    pub group_similar_windows: bool,
}
impl Default for Options {
    fn default() -> Self {
        Self { auto_hide: false, quick_launch: true, group_similar_windows: true }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Stored {
    version: u8,
    auto_hide: bool,
    quick_launch: bool,
    #[serde(default)]
    group_similar_windows: Option<bool>,
}

fn parse(raw: &[u8]) -> Option<Options> {
    let entry: Stored = serde_json::from_slice(raw).ok()?;
    // v1 preferences remain valid and preserve the previous grouping.
    // v2 requires an explicit grouping value; an unknown schema fails closed.
    let grouped = match (entry.version, entry.group_similar_windows) {
        (1, None) => true,
        (2, Some(value)) => value,
        _ => return None,
    };
    Some(Options {
        auto_hide: entry.auto_hide, quick_launch: entry.quick_launch,
        group_similar_windows: grouped,
    })
}

fn path() -> Option<PathBuf> {
    let root = env::var_os("XDG_CONFIG_HOME").map(PathBuf::from)
        .or_else(|| env::var_os("HOME").map(|value| PathBuf::from(value).join(".config")))?;
    root.is_absolute().then(|| root.join("ricebowl/luna-taskbar.json"))
}

fn read_private(path: &Path) -> io::Result<Option<Options>> {
    let Some(parent) = path.parent() else { return Ok(None) };
    let info = fs::symlink_metadata(parent)?;
    let uid = unsafe { libc::geteuid() };
    if !info.is_dir() || info.uid() != uid ||
        info.permissions().mode() & 0o022 != 0 { return Ok(None); }
    let file = OpenOptions::new().read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK).open(path)?;
    let meta = file.metadata()?;
    if !meta.is_file() || meta.uid() != uid ||
       meta.permissions().mode() & 0o077 != 0 || meta.len() > MAX_BYTES {
        return Ok(None);
    }
    let mut buf = Vec::with_capacity(meta.len() as usize);
    file.take(MAX_BYTES + 1).read_to_end(&mut buf)?;
    if buf.len() as u64 > MAX_BYTES { return Ok(None); }
    Ok(parse(&buf))
}

pub fn load() -> Options {
    let Some(path) = path() else { return Options::default() };
    match read_private(&path) {
        Ok(Some(value)) => value,
        Ok(None) => Options::default(),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Options::default(),
        Err(error) => {
            eprintln!("RicePlate: ignored unsafe Luna taskbar preferences: {error}");
            Options::default()
        }
    }
}

pub fn is_quick_launch(id: &str) -> bool {
    matches!(id, "applications" | "terminal" | "show-desktop")
}

pub fn panel_height(options: Options, collapsed: bool, full_height: u32) -> u32 {
    if options.auto_hide && collapsed { HANDLE_HEIGHT } else { full_height }
}

/// Pure policy shared by pointer Leave and popup dismissal. The compositor
/// owns pointer focus; do not infer that moving inside a popup is still inside
/// the taskbar, or collapse while any taskbar-owned popup is open.
pub fn should_collapse(options: Options, pointer_inside: bool, popup_open: bool) -> bool {
    options.auto_hide && !pointer_inside && !popup_open
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn options_are_bounded_and_reject_unsupported_types() {
        assert_eq!(parse(br#"{"version":1,"auto_hide":true,"quick_launch":false}"#),
            Some(Options {auto_hide:true,quick_launch:false,group_similar_windows:true}));
        assert_eq!(parse(br#"{"version":2,"auto_hide":false,"quick_launch":true,"group_similar_windows":false}"#),
            Some(Options {auto_hide:false,quick_launch:true,group_similar_windows:false}));
        for raw in [
            br#"{"version":2,"auto_hide":true,"quick_launch":true}"#.as_slice(),
            br#"{"version":1,"auto_hide":true,"quick_launch":true,"group_similar_windows":false}"#,
            br#"{"version":2,"auto_hide":true,"quick_launch":true,"group_similar_windows":1}"#,
            br#"{"version":3,"auto_hide":true,"quick_launch":true,"group_similar_windows":true}"#,
            br#"{"version":1,"auto_hide":1,"quick_launch":true}"#,
            br#"{"version":1,"auto_hide":false}"#,
            br#"{"version":1,"auto_hide":false,"quick_launch":true,"command":"rm"}"#,
        ] { assert_eq!(parse(raw), None); }
        assert_eq!(panel_height(Options::default(), true, 40), 40);
        assert_eq!(panel_height(Options {auto_hide:true,quick_launch:true,group_similar_windows:true}, true, 40), 3);
        assert_eq!(panel_height(Options {auto_hide:true,quick_launch:true,group_similar_windows:true}, false, 40), 40);
        assert!(is_quick_launch("show-desktop"));
        assert!(!is_quick_launch("wifi-toggle"));
        let auto = Options { auto_hide: true, quick_launch: true, group_similar_windows: true };
        assert!(should_collapse(auto, false, false));
        assert!(!should_collapse(auto, true, false));
        assert!(!should_collapse(auto, false, true));
        assert!(!should_collapse(Options::default(), false, false));
    }

    #[test]
    fn read_private_rejects_world_readable_and_symlinked_settings() {
        use std::{os::unix::fs::{DirBuilderExt, symlink},time::{SystemTime,UNIX_EPOCH}};
        let nanos = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let dir = env::temp_dir().join(format!("riceplate-taskbar-{}-{nanos}",std::process::id()));
        fs::DirBuilder::new().mode(0o700).create(&dir).unwrap();
        let path = dir.join("luna-taskbar.json");
        fs::write(&path, br#"{"version":1,"auto_hide":true,"quick_launch":true}"#).unwrap();
        fs::set_permissions(&path,fs::Permissions::from_mode(0o600)).unwrap();
        assert_eq!(read_private(&path).unwrap().unwrap().auto_hide,true);
        fs::set_permissions(&path,fs::Permissions::from_mode(0o644)).unwrap();
        assert_eq!(read_private(&path).unwrap(),None);
        fs::remove_file(&path).unwrap();
        let target = dir.join("target.json");
        fs::write(&target,b"{}").unwrap();
        symlink(&target,&path).unwrap();
        assert!(read_private(&path).is_err());
        fs::remove_file(path).unwrap();
        fs::remove_file(target).unwrap();
        fs::remove_dir(dir).unwrap();
    }
}
