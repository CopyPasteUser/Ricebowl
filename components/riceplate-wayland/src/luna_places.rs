//! Fixed, non-shell location launchers for the opt-in Luna Start menu.
//! Reuses the desktop's configured Gio file handler. No new background process.

use std::{env, path::{Path, PathBuf}, process::Command};

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
    if let Some(directory) = preferred.filter(|path| path.is_absolute() && path.is_dir()) {
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

/// Only validated, fixed location IDs reach Gio. Never pass an Exec field
/// or recipe-supplied path to a shell, and never claim a launch succeeded on
/// spawn failure.
pub fn launch(action: &str) -> bool {
    let Some(mut command) = location_command(action) else {
        eprintln!("RicePlate: {action} location unavailable");
        return false;
    };
    match command.spawn() {
        Ok(_) => true,
        Err(error) => {
            eprintln!("RicePlate: cannot open {action} location: {error}");
            false
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
        assert_eq!(choose_media(&home, Some(home.clone()), "Pictures"), Some(home.clone()));
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
