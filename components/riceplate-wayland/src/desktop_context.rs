//! Native desktop shortcut context state, shared by pointer and keyboard input.
//! Actions are strictly allowlisted; recipes never inject commands into menus.
pub const WIDTH: u32 = 224;
pub const HEIGHT: u32 = 190;
const FIRST_ROW: u32 = 36;
const ROW_HEIGHT: u32 = 28;
pub const BACK_ROW: u32 = 150;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Action {
    Open,
    NextDisplay,
    AllDisplays,
    ResetPosition,
    Properties,
}

impl Action {
    pub const ALL: [Self; 5] = [
        Self::Open, Self::NextDisplay, Self::AllDisplays,
        Self::ResetPosition, Self::Properties,
    ];
    pub fn label(self) -> &'static str {
        match self {
            Self::Open => "Open",
            Self::NextDisplay => "Next display",
            Self::AllDisplays => "All displays",
            Self::ResetPosition => "Reset position",
            Self::Properties => "Properties",
        }
    }
    pub fn enabled(self, multi_output: bool, can_reset: bool) -> bool {
        match self {
            Self::NextDisplay => multi_output,
            Self::ResetPosition => can_reset,
            _ => true,
        }
    }
    pub fn index(self) -> usize {
        match self {
            Self::Open => 0,
            Self::NextDisplay => 1,
            Self::AllDisplays => 2,
            Self::ResetPosition => 3,
            Self::Properties => 4,
        }
    }
}

pub fn row(action: Action) -> u32 { FIRST_ROW + action.index() as u32 * ROW_HEIGHT }

pub fn hit(x: f64, y: f64) -> Option<Action> {
    if !x.is_finite() || !y.is_finite()
        || x < 5.0 || x >= f64::from(WIDTH - 5)
        || y < f64::from(FIRST_ROW)
        || y >= f64::from(FIRST_ROW + Action::ALL.len() as u32 * ROW_HEIGHT)
    {
        return None;
    }
    Action::ALL.get(((y as u32 - FIRST_ROW) / ROW_HEIGHT) as usize).copied()
}

/// The read-only properties page only accepts a fixed, clearly visible Back
/// affordance; there is no hidden file operation or arbitrary action dispatch.
pub fn back_hit(x: f64, y: f64) -> bool {
    x.is_finite() && y.is_finite() && (5.0..f64::from(WIDTH - 5)).contains(&x)
        && (f64::from(BACK_ROW)..f64::from(BACK_ROW + ROW_HEIGHT)).contains(&y)
}

pub fn navigate(current: Action, delta: i32, multi_output: bool,
                can_reset: bool) -> Action {
    let mut index = current.index() as i32;
    for _ in 0..Action::ALL.len() {
        index = (index + delta).rem_euclid(Action::ALL.len() as i32);
        let action = Action::ALL[index as usize];
        if action.enabled(multi_output, can_reset) { return action; }
    }
    current
}

/// Show only static metadata for an already validated desktop action. This is
/// NOT a filesystem stat and must not imply the target exists or is mounted.
pub fn details(action: &str) -> (&'static str, &'static str) {
    match action {
        "applications" => ("Application", "App launcher"),
        "terminal" => ("Application", "Terminal launcher"),
        "lock" => ("System action", "Lock screen"),
        "trash" => ("Virtual folder", "Trash via Gio"),
        "documents" => ("User folder", "Documents via Gio"),
        "computer" => ("Virtual folder", "Computer via Gio"),
        "network" => ("Virtual folder", "Network via Gio"),
        _ => ("Shortcut", "Supported action"),
    }
}

/// Position in the chosen wl_output's logical coordinates, never outside its
/// work area; no global pointer coordinates or cross-output assumptions.
pub fn placement(icon: (u32, u32), pointer: (f64, f64),
                 output: (u32, u32), panel_height: u32, top_panel: bool)
                 -> Option<(u32, u32)> {
    if !pointer.0.is_finite() || !pointer.1.is_finite()
        || pointer.0 < 0.0 || pointer.1 < 0.0
        || pointer.0 >= f64::from(crate::recipe::ICON_WIDTH)
        || pointer.1 >= f64::from(crate::recipe::ICON_HEIGHT) {
        return None;
    }
    let upper = if top_panel { panel_height } else { 0 };
    let bottom = if top_panel { 0 } else { panel_height };
    if output.0 < WIDTH || output.1 < HEIGHT.saturating_add(upper).saturating_add(bottom) {
        return None;
    }
    let x = icon.0.saturating_add(pointer.0.round() as u32)
        .min(output.0 - WIDTH);
    let y = icon.1.saturating_add(pointer.1.round() as u32)
        .clamp(upper, output.1 - HEIGHT - bottom);
    Some((x, y))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rows_disabled_navigation_and_back_are_bounded() {
        for action in Action::ALL {
            assert_eq!(hit(20.0, f64::from(row(action) + 14)), Some(action));
        }
        for (x, y) in [(-1.0, 46.0), (224.0, 46.0), (7.0, 35.0),
                        (7.0, 190.0), (f64::NAN, 40.0), (50.0, f64::INFINITY)] {
            assert_eq!(hit(x, y), None);
        }
        assert!(!Action::NextDisplay.enabled(false, true));
        assert!(!Action::ResetPosition.enabled(true, false));
        assert!(Action::Properties.enabled(false, false));
        assert_eq!(navigate(Action::Open, 1, false, false), Action::AllDisplays);
        assert_eq!(navigate(Action::AllDisplays, 1, false, false), Action::Properties);
        assert_eq!(navigate(Action::Properties, -1, false, true), Action::ResetPosition);
        assert_eq!(navigate(Action::Open, -1, true, true), Action::Properties);
        assert!(back_hit(20.0, f64::from(BACK_ROW + 12)));
        for (x, y) in [(2.0, 163.0), (224.0, 163.0), (20.0, 149.0),
                        (20.0, 178.0), (f64::NAN, 160.0)] {
            assert!(!back_hit(x, y));
        }
    }

    #[test]
    fn metadata_is_allowlisted_and_never_treated_as_file_attributes() {
        assert_eq!(details("trash"), ("Virtual folder", "Trash via Gio"));
        assert_eq!(details("network"), ("Virtual folder", "Network via Gio"));
        assert_eq!(details("terminal"), ("Application", "Terminal launcher"));
        assert_eq!(details("dangerous arbitrary shell string"),
                   ("Shortcut", "Supported action"));
    }

    #[test]
    fn popup_stays_within_logical_output_and_clear_of_panel() {
        assert_eq!(placement((24, 400), (44.0, 35.0), (1366, 768), 40, false),
                   Some((68, 435)));
        assert_eq!(placement((1000, 700), (100.0, 80.0), (1024, 768), 40, false),
                   Some((800, 538)));
        assert_eq!(placement((0, 0), (2.0, 2.0), (224, 250), 40, true),
                   Some((0, 40)));
        assert_eq!(placement((0, 0), (2.0, 2.0), (200, 250), 40, false), None);
        assert_eq!(placement((0, 0), (2.0, 2.0), (224, 200), 40, true), None);
        assert_eq!(placement((0, 0), (f64::NAN, 2.0), (1366, 768), 40, false), None);
        assert_eq!(placement((0, 0), (-1.0, 0.0), (1366, 768), 40, false), None);
    }
}


/// File-backed desktop actions are not recipe commands. This typed policy is
/// separate from the original seven virtual shortcuts and does not invoke a
/// process or mutate user files. The integration lane owns the UI/confirmation.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FileAction {
    Open, OpenInExplorer, Rename, MoveToTrash, Properties,
    // Complex file transfers belong to RiceField's own file-operation UX.
    Move, Copy,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FilePermission { Disabled, Ready, UserEdit, ExplicitConfirmation }

#[allow(dead_code)]
pub fn file_permission(action: FileAction, kind: crate::desktop_layout::inventory::Kind)
                       -> FilePermission {
    use crate::desktop_layout::inventory::Kind;
    use FileAction::*;
    use FilePermission::*;
    match (action, kind) {
        (Properties, _) => Ready,
        (_, Kind::DesktopFile | Kind::Symlink) => Disabled,
        (Open | OpenInExplorer, Kind::File | Kind::Directory) => Ready,
        (Rename, Kind::File | Kind::Directory) => UserEdit,
        (MoveToTrash, Kind::File | Kind::Directory) => ExplicitConfirmation,
        (Move | Copy, _) => Disabled,
    }
}

/// Activation describes a verified file intent, not an executable command.
/// The returned pathname is advisory; the caller must revalidate right before
/// Gio/RiceField handoff, especially if another process can change the Desktop.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FileOpenIntent {
    DefaultApplication(std::path::PathBuf),
    DirectoryInRiceField(std::path::PathBuf),
}

#[allow(dead_code)]
pub fn file_open_intent(
    snapshot: &crate::desktop_layout::inventory::Snapshot,
    desktop: &std::path::Path,
    entry: &crate::desktop_layout::inventory::Entry,
    explorer: bool,
) -> std::io::Result<FileOpenIntent> {
    use crate::desktop_layout::inventory::Kind;
    let action = if explorer { FileAction::OpenInExplorer } else { FileAction::Open };
    if file_permission(action, entry.kind) != FilePermission::Ready {
        return Err(std::io::Error::new(std::io::ErrorKind::PermissionDenied,
                                       "Desktop entry is not an executable file target"));
    }
    let path = snapshot.current_path(desktop, entry)?;
    if explorer || entry.kind == Kind::Directory {
        let destination = if entry.kind == Kind::Directory {
            path
        } else {
            path.parent().ok_or(std::io::ErrorKind::InvalidInput)?.to_path_buf()
        };
        Ok(FileOpenIntent::DirectoryInRiceField(destination))
    } else {
        Ok(FileOpenIntent::DefaultApplication(path))
    }
}

#[cfg(test)]
mod file_action_tests {
    use super::*;
    use crate::desktop_layout::inventory::{scan, Kind};
    use std::{env, fs, os::unix::fs::symlink,
              time::{SystemTime, UNIX_EPOCH}};

    #[test]
    fn typed_context_is_not_arbitrary_exec_or_destructive_without_confirmation() {
        assert_eq!(file_permission(FileAction::Open, Kind::File), FilePermission::Ready);
        assert_eq!(file_permission(FileAction::Open, Kind::Directory), FilePermission::Ready);
        assert_eq!(file_permission(FileAction::Rename, Kind::Directory), FilePermission::UserEdit);
        assert_eq!(file_permission(FileAction::MoveToTrash, Kind::File),
                   FilePermission::ExplicitConfirmation);
        for kind in [Kind::DesktopFile, Kind::Symlink] {
            assert_eq!(file_permission(FileAction::Open, kind), FilePermission::Disabled);
            assert_eq!(file_permission(FileAction::OpenInExplorer, kind), FilePermission::Disabled);
            assert_eq!(file_permission(FileAction::Properties, kind), FilePermission::Ready);
        }
    }

    #[test]
    fn file_and_folder_intents_are_validated_and_stale_items_are_revoked() {
        let n = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let dir = env::temp_dir().join(format!("ricebowl-file-actions-{}-{n}", std::process::id()));
        fs::create_dir(&dir).unwrap();
        fs::write(dir.join("notes.txt"), b"text").unwrap();
        fs::create_dir(dir.join("Folder")).unwrap();
        fs::write(dir.join("untrusted.desktop"), b"Exec=sh -c bad").unwrap();
        symlink("notes.txt", dir.join("link")).unwrap();
        let snap = scan(&dir).unwrap();
        let file = snap.entries.iter().find(|e| e.label == "notes.txt").unwrap();
        let folder = snap.entries.iter().find(|e| e.label == "Folder").unwrap();
        let desktop = snap.entries.iter().find(|e| e.kind == Kind::DesktopFile).unwrap();
        let link = snap.entries.iter().find(|e| e.kind == Kind::Symlink).unwrap();
        assert_eq!(file_open_intent(&snap, &dir, file, false).unwrap(),
                   FileOpenIntent::DefaultApplication(dir.join("notes.txt")));
        assert_eq!(file_open_intent(&snap, &dir, file, true).unwrap(),
                   FileOpenIntent::DirectoryInRiceField(dir.clone()));
        assert_eq!(file_open_intent(&snap, &dir, folder, false).unwrap(),
                   FileOpenIntent::DirectoryInRiceField(dir.join("Folder")));
        assert!(file_open_intent(&snap, &dir, desktop, false).is_err());
        assert!(file_open_intent(&snap, &dir, link, false).is_err());
        fs::remove_file(dir.join("notes.txt")).unwrap();
        assert!(file_open_intent(&snap, &dir, file, false).is_err());
        fs::remove_dir_all(dir).unwrap();
    }
}


/// The compositor translates actual seat-owned input into these intents.
/// This model does not generate key events or claim focus itself.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FileGesture {
    DoubleClick,
    Enter,
    F2,
    RightClick,
    Context(FileAction),
    Escape,
}

/// No filesystem mutation occurs during gesture resolution. A destructive
/// action must enter a separate confirmation state in the integration UI.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FileUiIntent {
    Open(crate::desktop_layout::actions::OpenMode),
    ShowProperties,
    EditName,
    ShowContextMenu,
    ConfirmTrashDelegation,
    Cancelled,
    Disabled(&'static str),
}

#[derive(Debug)]
pub enum FileActionFeedback {
    Ready(FileUiIntent),
    Started(crate::desktop_layout::actions::Backend, u32),
    Renamed(crate::desktop_layout::actions::RenameReceipt),
    Failed(crate::desktop_layout::actions::ActionError),
    Cancelled,
    Disabled(&'static str),
}

/// One-file actions always require exactly one selected, visible file item.
/// Right-click may show a menu without starting any operation. Ctrl/Shift
/// multi-selection remains possible, but no implicit batch launch/delete.
#[allow(dead_code)]
pub fn file_gesture_intent(
    gesture: FileGesture,
    kind: crate::desktop_layout::inventory::Kind,
    selected_count: usize,
) -> FileUiIntent {
    use FileGesture::*;
    use FileUiIntent as Intent;
    let chosen = match gesture {
        Escape => return Intent::Cancelled,
        RightClick => return Intent::ShowContextMenu,
        DoubleClick | Enter => FileAction::Open,
        F2 => FileAction::Rename,
        Context(action) => action,
    };
    if selected_count != 1 {
        return Intent::Disabled("Select exactly one Desktop item");
    }
    match file_permission(chosen, kind) {
        FilePermission::Disabled =>
            Intent::Disabled("Use RiceField for this item or operation"),
        FilePermission::Ready => match chosen {
            FileAction::Open => Intent::Open(crate::desktop_layout::actions::OpenMode::Default),
            FileAction::OpenInExplorer =>
                Intent::Open(crate::desktop_layout::actions::OpenMode::Explorer),
            FileAction::Properties => Intent::ShowProperties,
            _ => Intent::Disabled("Unsupported file action"),
        },
        FilePermission::UserEdit => Intent::EditName,
        FilePermission::ExplicitConfirmation => Intent::ConfirmTrashDelegation,
    }
}

#[cfg(test)]
mod file_gesture_tests {
    use super::*;
    use crate::desktop_layout::{actions::OpenMode, inventory::Kind};

    #[test]
    fn direct_input_is_pure_and_requires_exactly_one_selected_file() {
        assert_eq!(file_gesture_intent(FileGesture::DoubleClick, Kind::File, 1),
                   FileUiIntent::Open(OpenMode::Default));
        assert_eq!(file_gesture_intent(FileGesture::Enter, Kind::Directory, 1),
                   FileUiIntent::Open(OpenMode::Default));
        assert_eq!(file_gesture_intent(FileGesture::F2, Kind::File, 1),
                   FileUiIntent::EditName);
        assert_eq!(file_gesture_intent(FileGesture::RightClick, Kind::File, 3),
                   FileUiIntent::ShowContextMenu);
        for count in [0, 2, 96] {
            assert!(matches!(file_gesture_intent(FileGesture::Enter, Kind::File, count),
                             FileUiIntent::Disabled(_)));
            assert!(matches!(file_gesture_intent(FileGesture::F2, Kind::Directory, count),
                             FileUiIntent::Disabled(_)));
        }
    }

    #[test]
    fn no_implicit_execute_trash_or_batch_operation() {
        assert_eq!(file_gesture_intent(FileGesture::Context(FileAction::Properties),
                   Kind::Symlink, 1), FileUiIntent::ShowProperties);
        for kind in [Kind::DesktopFile, Kind::Symlink] {
            for gesture in [FileGesture::DoubleClick, FileGesture::Enter, FileGesture::F2] {
                assert!(matches!(file_gesture_intent(gesture, kind, 1),
                                 FileUiIntent::Disabled(_)));
            }
        }
        assert_eq!(file_gesture_intent(
            FileGesture::Context(FileAction::MoveToTrash), Kind::File, 1),
            FileUiIntent::ConfirmTrashDelegation);
        for action in [FileAction::Move, FileAction::Copy] {
            assert!(matches!(file_gesture_intent(FileGesture::Context(action), Kind::File, 1),
                             FileUiIntent::Disabled(_)));
        }
        assert_eq!(file_gesture_intent(FileGesture::Escape, Kind::File, 1),
                   FileUiIntent::Cancelled);
    }
}
