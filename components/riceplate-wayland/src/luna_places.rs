//! Fixed, non-shell location launchers for the opt-in Luna Start menu.
//! Reuses the desktop's configured Gio file handler. No new background process.

use std::{env, fs, os::unix::fs::MetadataExt, path::{Path, PathBuf}, process::Command};

fn xdg_user_directory(kind: &str) -> Option<PathBuf> {
    // Fixed XDG directory types only. Never pass a recipe-supplied value
    // to an executable. Probe on click, not in a resident poll.
    if !matches!(kind, "DOCUMENTS" | "PICTURES" | "MUSIC") { return None; }
    let result = Command::new("xdg-user-dir").arg(kind).output().ok()?;
    if !result.status.success() { return None; }
    let text = String::from_utf8(result.stdout).ok()?;
    let directory = PathBuf::from(text.trim());
    (directory.is_absolute() && directory.is_dir()).then_some(directory)
}

fn choose_documents(home: &Path, preferred: Option<PathBuf>) -> PathBuf {
    if let Some(directory) = preferred.filter(|path| path.is_absolute() && path.is_dir()) {
        return directory;
    }
    let conventional = home.join("Documents");
    if conventional.is_dir() { conventional } else { home.to_path_buf() }
}

// Unlike Documents, an absent media folder must not silently open $HOME:
// a My Pictures/Music shortcut should never navigate to an unrelated place.
fn choose_media(home: &Path, preferred: Option<PathBuf>, name: &str) -> Option<PathBuf> {
    if let Some(directory) = preferred.filter(|path|
        path.is_absolute() && path.is_dir() && path != home) {
        return Some(directory);
    }
    let conventional = home.join(name);
    conventional.is_dir().then_some(conventional)
}

fn location_command(action: &str) -> Option<Command> {
    if action == "network" {
        // GVfs owns network discovery, SMB/SFTP mounts and authentication.
        // Never enumerate, mount, or synthesize remote hosts in RicePlate.
        let mut command = Command::new("gio");
        command.arg("open").arg("network:///");
        return Some(command);
    }
    if action == "trash" {
        // GIO understands trash:/// as a virtual location when the user's
        // file-manager/GVfs backend supports it. Never manipulate files or
        // call gio trash here: this action only opens the view.
        let mut command = Command::new("gio");
        command.arg("open").arg("trash:///");
        return Some(command);
    }
    let directory = match action {
        // Root is always browsable even when a GVfs 'computer:///' backend is
        // absent. This intentionally does not pretend to provide an XP drive UI.
        "computer" => PathBuf::from("/"),
        "documents" => {
            let home = env::var_os("HOME").map(PathBuf::from)?;
            if !home.is_absolute() || !home.is_dir() { return None; }
            choose_documents(&home, xdg_user_directory("DOCUMENTS"))
        }
        "pictures" | "music" => {
            let home = env::var_os("HOME").map(PathBuf::from)?;
            if !home.is_absolute() || !home.is_dir() { return None; }
            let (kind, name) = if action == "pictures" {
                ("PICTURES", "Pictures")
            } else {
                ("MUSIC", "Music")
            };
            choose_media(&home, xdg_user_directory(kind), name)?
        }
        _ => return None,
    };
    let mut command = Command::new("gio");
    command.arg("open").arg(directory);
    Some(command)
}

/// The only local locations RiceField 1.0 accepts here: absolute filesystem
/// paths. Virtual GVfs locations (trash/network) must remain in the user's
/// default Gio/GVfs handler because RiceField does not claim those URIs.
/// The option is exclusive to the opt-in Luna recipe.
fn ricefield_command(action: &str, fallback: &Command) -> Option<Command> {
    if !matches!(action, "computer" | "documents" | "pictures" | "music") {
        return None;
    }
    let mut args = fallback.get_args();
    if args.next()? != "open" { return None; }
    let target = Path::new(args.next()?);
    if !target.is_absolute() || !target.is_dir() || args.next().is_some() { return None; }
    ricefield_local_command(target)
}

/// Construct the same XP-themed RiceField invocation for an owned, real
/// filesystem directory (including a folder just created on the Desktop).
/// Keep this distinct from virtual GVfs URIs such as trash:///.
fn ricefield_local_command(target: &Path) -> Option<Command> {
    if !target.is_absolute() || !target.is_dir() { return None; }
    let mut cmd = Command::new("ricefield");
    cmd.args(["--theme", "xp-luna", "--separate-window"]).arg(target);
    Some(cmd)
}

/// Only the result of Luna's checked desktop-folder creation is passed here.
/// Do not accept missing/relative/symlinked directories as file-manager
/// targets; never interpret their names as executable arguments.
fn created_folder_commands(path: &Path) -> Option<(Command, Command)> {
    let meta = fs::symlink_metadata(path).ok()?;
    if !path.is_absolute() || !meta.is_dir()
        || meta.uid() != unsafe { libc::geteuid() } {
        return None;
    }
    let ricefield = ricefield_local_command(path)?;
    let mut gio = Command::new("gio");
    gio.arg("open").arg(path);
    Some((ricefield, gio))
}

/// Only a missing RiceField binary permits Gio fallback. A denied or broken
/// executable must report an error instead of silently masking the failure.
fn spawn_preferred(context: &str, preferred: Option<Command>, mut fallback: Command) -> bool {
    if let Some(mut cmd) = preferred {
        match cmd.spawn() {
            Ok(_) => return true,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => {
                eprintln!("RicePlate: cannot launch RiceField for {context}: {error}");
                return false;
            }
        }
    }
    match fallback.spawn() {
        Ok(_) => true,
        Err(error) => {
            eprintln!("RicePlate: cannot open {context} location: {error}");
            false
        }
    }
}

/// Open the actual folder created by the Luna background context menu in
/// RiceField's XP view, or through the configured Gio handler if absent.
/// This never changes the file association or launches an arbitrary command.
pub fn open_created_folder(path: &Path) -> bool {
    let Some((ricefield, gio)) = created_folder_commands(path) else {
        eprintln!("RicePlate: refusing unsafe or missing created Desktop folder");
        return false;
    };
    spawn_preferred("created Desktop folder", Some(ricefield), gio)
}

/// Prefer the existing installed RiceField 1.0 for real local Explorer
/// navigation in the XP profile, but keep working Gio fallback for machines
/// without RiceField. This does not change desktop file associations.
pub fn launch(action: &str, prefer_ricefield: bool) -> bool {
    let Some(mut fallback) = location_command(action) else {
        eprintln!("RicePlate: {action} location unavailable");
        return false;
    };
    let preferred = prefer_ricefield.then(|| ricefield_command(action, &fallback)).flatten();
    spawn_preferred(action, preferred, fallback)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn xp_ricefield_uses_real_theme_and_separate_window_for_local_places_only() {
        for action in ["computer", "documents", "pictures", "music"] {
            if let Some(gio) = location_command(action) {
                let cmd = ricefield_command(action, &gio)
                    .expect("existing local location accepted by RiceField");
                assert_eq!(cmd.get_program(), "ricefield");
                let args = cmd.get_args().map(|arg| arg.to_string_lossy().into_owned())
                    .collect::<Vec<_>>();
                assert_eq!(&args[0..3], &["--theme", "xp-luna", "--separate-window"]);
                assert!(Path::new(&args[3]).is_absolute());
                assert_eq!(args.len(), 4);
            }
        }
        for action in ["network", "trash"] {
            let fallback = location_command(action).unwrap();
            assert!(ricefield_command(action, &fallback).is_none());
        }
        let mut malicious = Command::new("gio");
        malicious.arg("open").arg("--dangerous");
        assert!(ricefield_command("computer", &malicious).is_none());
        let mut extra = Command::new("gio");
        extra.arg("open").arg("/").arg("/etc");
        assert!(ricefield_command("computer", &extra).is_none());
        let mut relative = Command::new("gio");
        relative.arg("open").arg("relative/path");
        assert!(ricefield_command("computer", &relative).is_none());
    }


    #[test]
    fn newly_created_desktop_folder_uses_actual_absolute_path_and_xp_theme() {
        use std::{os::unix::fs::symlink, time::{SystemTime, UNIX_EPOCH}};
        let n = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let root = env::temp_dir().join(format!("riceplate-new-folder-{}-{n}",std::process::id()));
        fs::create_dir(&root).unwrap();
        let folder = root.join("New Folder (2)");
        fs::create_dir(&folder).unwrap();
        let (ricefield, gio) = created_folder_commands(&folder).unwrap();
        assert_eq!(ricefield.get_program(), "ricefield");
        assert_eq!(ricefield.get_args().map(|s| s.to_string_lossy().into_owned())
                   .collect::<Vec<_>>(),
                   vec!["--theme", "xp-luna", "--separate-window",
                        folder.to_str().unwrap()]);
        assert_eq!(gio.get_program(), "gio");
        assert_eq!(gio.get_args().map(|s| s.to_string_lossy().into_owned())
                   .collect::<Vec<_>>(),
                   vec!["open", folder.to_str().unwrap()]);
        let shortcut = root.join("shortcut");
        symlink(&folder, &shortcut).unwrap();
        assert!(created_folder_commands(&shortcut).is_none(),
                "symlink must not be passed as a newly created folder");
        assert!(created_folder_commands(&root.join("missing")).is_none());
        assert!(created_folder_commands(Path::new("relative")).is_none());
        let ordinary_file = root.join("document.txt");
        fs::write(&ordinary_file, b"hello").unwrap();
        assert!(created_folder_commands(&ordinary_file).is_none());
        fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn computer_is_a_fixed_gio_location_without_shell() {
        let command = location_command("computer").expect("fixed computer launcher");
        assert_eq!(command.get_program(), "gio");
        assert_eq!(command.get_args().map(|s| s.to_string_lossy().into_owned())
            .collect::<Vec<_>>(), vec!["open".to_owned(), "/".to_owned()]);
        assert!(location_command("logout").is_none());
        assert!(location_command("desktop:untrusted.desktop").is_none());
    }

    #[test]
    fn recycle_bin_is_a_fixed_read_only_navigation_request() {
        let command = location_command("trash").expect("fixed desktop location");
        assert_eq!(command.get_program(), "gio");
        assert_eq!(command.get_args().map(|value|
            value.to_string_lossy().into_owned()).collect::<Vec<_>>(),
            vec!["open".to_owned(), "trash:///".to_owned()]);
        assert!(location_command("trash;rm -rf").is_none());
        let command = location_command("network").expect("GVfs network location");
        assert_eq!(command.get_program(), "gio");
        assert_eq!(command.get_args().map(|value|
            value.to_string_lossy().into_owned()).collect::<Vec<_>>(),
            vec!["open".to_owned(), "network:///".to_owned()]);
        assert!(location_command("network;touch /tmp/pwned").is_none());
    }

    #[test]
    fn media_places_do_not_fall_back_to_unrelated_home() {
        let home = std::env::current_dir().expect("checkout exists");
        // Disabled xdg-user-dir media locations can resolve to $HOME.
        // An XP media shortcut must not silently navigate there instead.
        assert!(choose_media(&home, Some(home.clone()),
            "__ricebowl_absent_media_directory__").is_none());
        assert!(choose_media(&home, Some(PathBuf::from("relative")),
            "__ricebowl_absent_media_directory__").is_none());
        assert!(choose_media(&home, Some(PathBuf::from(
            "/definitely-not-a-ricebowl-media-directory")),
            "__ricebowl_absent_media_directory__").is_none());
        assert!(xdg_user_directory("EXEC").is_none());
        for action in ["pictures", "music"] {
            let result = location_command(action);
            // A real user may or may not have configured media directories;
            // when available this is always a fixed, shell-free Gio open.
            if let Some(command) = result {
                assert_eq!(command.get_program(), "gio");
                assert_eq!(command.get_args().count(), 2);
            }
        }
    }

    #[test]
    fn documents_prefers_an_existing_absolute_xdg_directory() {
        let home = std::env::current_dir().expect("CI checkout exists");
        assert_eq!(choose_documents(&home, Some(home.clone())), home);
        let expected = if home.join("Documents").is_dir() {
            home.join("Documents")
        } else {
            home.clone()
        };
        assert_eq!(choose_documents(&home, Some(PathBuf::from("relative"))), expected);
        assert_eq!(choose_documents(&home, Some(PathBuf::from(
            "/definitely-not-a-ricebowl-documents-directory"))), expected);
    }
}
