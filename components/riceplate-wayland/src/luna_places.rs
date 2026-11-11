//! Fixed, non-shell location launchers for the opt-in Luna Start menu.
//! Reuses the desktop's configured Gio file handler. No new background process.

use std::{env, path::{Path, PathBuf}, process::Command};

fn xdg_documents_directory() -> Option<PathBuf> {
    // XDG user directories are per-user settings, not necessarily ~/Documents.
    // Probe only on click; no polling or resident helper.
    let result = Command::new("xdg-user-dir").arg("DOCUMENTS").output().ok()?;
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

fn location_command(action: &str) -> Option<Command> {
    let directory = match action {
        // Root is always browsable even when a GVfs 'computer:///' backend is
        // absent. This intentionally does not pretend to provide an XP drive UI.
        "computer" => PathBuf::from("/"),
        "documents" => {
            let home = env::var_os("HOME").map(PathBuf::from)?;
            if !home.is_absolute() || !home.is_dir() { return None; }
            choose_documents(&home, xdg_documents_directory())
        }
        _ => return None,
    };
    let mut command = Command::new("gio");
    command.arg("open").arg(directory);
    Some(command)
}

/// Only two validated, fixed location IDs reach Gio. Never pass an Exec field
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
            .collect::<Vec<_>>(), ["open", "/"]);
        assert!(location_command("logout").is_none());
        assert!(location_command("desktop:untrusted.desktop").is_none());
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
