//! Bounded discovery of installed XDG desktop entries for native menu search.
//! Desktop-file Exec fields are never interpreted here: activation is delegated
//! to `gio launch` with the verified file path, without a shell.

use std::{collections::HashSet, env, fs, path::{Path, PathBuf}};

pub const MAX_APPS: usize = 512;
const MAX_FILES: usize = 4096;
const MAX_FILE_BYTES: u64 = 64 * 1024;
const MAX_DEPTH: usize = 3;

#[derive(Debug, Clone)]
pub struct App {
    pub action: String,
    pub name: String,
    pub search_text: String,
    pub path: PathBuf,
}

impl App {
    pub fn matches(&self, query: &str) -> bool {
        self.search_text.contains(query)
    }
}

pub fn discover() -> Vec<App> {
    let mut roots = Vec::new();
    if let Some(path) = env::var_os("XDG_DATA_HOME").filter(|value| !value.is_empty()) {
        roots.push(PathBuf::from(path));
    } else if let Some(home) = env::var_os("HOME") {
        roots.push(PathBuf::from(home).join(".local/share"));
    }
    let dirs = env::var_os("XDG_DATA_DIRS")
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "/usr/local/share:/usr/share".into());
    roots.extend(env::split_paths(&dirs));
    scan_roots(&roots, env::var("XDG_CURRENT_DESKTOP").unwrap_or_default().as_str())
}

fn scan_roots(roots: &[PathBuf], current_desktop: &str) -> Vec<App> {
    let mut seen = HashSet::new();
    let mut apps = Vec::new();
    let mut visited_files = 0;
    for root in roots {
        let dir = root.join("applications");
        if !dir.is_absolute() { continue; }
        scan_dir(&dir, &dir, 0, current_desktop, &mut seen, &mut apps,
                 &mut visited_files);
        if visited_files >= MAX_FILES { break; }
    }
    apps.sort_by(|a, b| a.name.to_lowercase().cmp(&b.name.to_lowercase())
                 .then(a.action.cmp(&b.action)));
    apps.truncate(MAX_APPS);
    apps
}

fn scan_dir(root: &Path, dir: &Path, depth: usize, current_desktop: &str,
            seen: &mut HashSet<String>, apps: &mut Vec<App>, visited: &mut usize) {
    if depth > MAX_DEPTH || *visited >= MAX_FILES { return; }
    let Ok(items) = fs::read_dir(dir) else { return; };
    let mut entries: Vec<_> = items.filter_map(Result::ok).take(MAX_FILES).collect();
    entries.sort_by_key(|entry| entry.file_name());
    for entry in entries {
        if *visited >= MAX_FILES { break; }
        let Ok(kind) = entry.file_type() else { continue; };
        if kind.is_dir() {
            scan_dir(root, &entry.path(), depth + 1, current_desktop, seen, apps, visited);
            continue;
        }
        if !kind.is_file() || entry.path().extension().is_none_or(|ext| ext != "desktop") {
            continue;
        }
        *visited += 1;
        let Ok(relative) = entry.path().strip_prefix(root) else { continue; };
        let Some(id) = desktop_id(relative) else { continue; };
        // Even a hidden or invalid high-priority entry masks a system entry.
        if !seen.insert(id.clone()) { continue; }
        let Ok(metadata) = entry.metadata() else { continue; };
        if metadata.len() > MAX_FILE_BYTES { continue; }
        let Ok(data) = fs::read_to_string(entry.path()) else { continue; };
        if let Some((name, search_text)) = parse_entry(&data, current_desktop) {
            apps.push(App { action: format!("desktop:{id}"), name, search_text,
                            path: entry.path() });
        }
    }
}

fn desktop_id(relative: &Path) -> Option<String> {
    let segments: Vec<_> = relative.components()
        .map(|piece| piece.as_os_str().to_str())
        .collect::<Option<_>>()?;
    if segments.is_empty() { return None; }
    let id = segments.join("-");
    (id.len() <= 160 && id.ends_with(".desktop") && id.bytes().all(|byte|
        byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-')))
        .then_some(id)
}

fn parse_entry(data: &str, current_desktop: &str) -> Option<(String, String)> {
    let mut in_section = false;
    let mut is_application = false;
    let mut hidden = false;
    let mut no_display = false;
    let mut has_exec = false;
    let mut dbus_activatable = false;
    let mut name = None;
    let mut generic = "";
    let mut keywords = "";
    let mut only_show = "";
    let mut not_show = "";
    let mut try_exec = "";
    for line in data.lines() {
        let line = line.trim();
        if line.starts_with('[') {
            in_section = line == "[Desktop Entry]";
            continue;
        }
        if !in_section || line.is_empty() || line.starts_with('#') { continue; }
        let Some((key, value)) = line.split_once('=') else { continue; };
        let value = value.trim();
        match key {
            "Type" => is_application = value == "Application",
            "Hidden" => hidden = value == "true",
            "NoDisplay" => no_display = value == "true",
            "Exec" => has_exec = !value.is_empty(),
            "DBusActivatable" => dbus_activatable = value == "true",
            "Name" => name = Some(value),
            "GenericName" => generic = value,
            "Keywords" => keywords = value,
            "OnlyShowIn" => only_show = value,
            "NotShowIn" => not_show = value,
            "TryExec" => try_exec = value,
            _ => {},
        }
    }
    if !is_application || !has_exec && !dbus_activatable || hidden || no_display
        || (!only_show.is_empty() && !desktop_matches(only_show, current_desktop))
        || (!not_show.is_empty() && desktop_matches(not_show, current_desktop))
        || (!try_exec.is_empty() && !executable_exists(try_exec)) { return None; }
    let name = name?.chars().filter(|ch| !ch.is_control()).take(80).collect::<String>();
    if name.trim().is_empty() { return None; }
    let search_text = format!("{name} {generic} {}", keywords.replace(';', " "))
        .to_lowercase();
    Some((name, search_text))
}

fn desktop_matches(list: &str, current: &str) -> bool {
    current.split(':').any(|desktop| !desktop.is_empty()
        && list.split(';').any(|item| item == desktop))
}

fn executable_exists(value: &str) -> bool {
    if value.contains('/') { return Path::new(value).is_file(); }
    env::split_paths(&env::var_os("PATH").unwrap_or_default())
        .any(|dir| dir.join(value).is_file())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn filters_hidden_and_desktop_specific_entries() {
        let sample = "[Desktop Entry]\nType=Application\nExec=player\nName=Player\nGenericName=Media tool\nKeywords=video;music;\nOnlyShowIn=RiceBowl;GNOME;\n";
        let (name, query) = parse_entry(sample, "RiceBowl:XFCE").unwrap();
        assert_eq!(name, "Player");
        assert!(query.contains("video music"));
        assert!(parse_entry(sample, "KDE").is_none());
        assert!(parse_entry(&sample.replace("Name=Player", "Name=Player\nHidden=true"), "RiceBowl").is_none());
        assert!(parse_entry(&sample.replace("Name=Player", "Name=Player\nNoDisplay=true"), "RiceBowl").is_none());
        assert!(parse_entry(&sample.replace("Type=Application", "Type=Link"), "RiceBowl").is_none());
        assert!(parse_entry(&sample.replace("OnlyShowIn=RiceBowl;GNOME;", "NotShowIn=RiceBowl;"), "RiceBowl").is_none());
    }

    #[test]
    fn only_valid_ids_and_entries_are_indexed() {
        assert_eq!(desktop_id(Path::new("org/example.desktop")), Some("org-example.desktop".into()));
        assert!(desktop_id(Path::new("name with spaces.desktop")).is_none());
        assert!(desktop_id(Path::new("not-a-desktop.txt")).is_none());
        assert!(parse_entry("[Desktop Entry]\nType=Application\nExec=visible\nName=Visible", "").is_some());
        assert!(parse_entry("[Desktop Entry]\nType=Application\nName=Visible", "").is_none());
        assert!(parse_entry("[Desktop Entry]\nType=Application\nDBusActivatable=true\nName=Visible", "").is_some());
        assert!(parse_entry("[Desktop Entry]\nType=Application\nExec=visible\nName=Visible\nTryExec=missing-impossible-app-xyz", "").is_none());
    }

    #[test]
    fn desktop_file_sections_cannot_replace_main_name() {
        let data = "[Desktop Entry]\nType=Application\nExec=good\nName=Good\n[Desktop Action Evil]\nName=Bad\n";
        assert_eq!(parse_entry(data, "").unwrap().0, "Good");
    }

    #[test]
    fn user_hidden_entry_masks_system_app_and_nested_ids_are_stable() {
        let suffix = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let base = env::temp_dir().join(format!("riceplate-app-catalog-{}-{suffix}", std::process::id()));
        let user = base.join("user");
        let system = base.join("system");
        let user_apps = user.join("applications");
        let system_apps = system.join("applications/org");
        fs::create_dir_all(&user_apps).unwrap();
        fs::create_dir_all(&system_apps).unwrap();
        fs::write(user_apps.join("org-Editor.desktop"),
                  "[Desktop Entry]\nType=Application\nHidden=true\n").unwrap();
        fs::write(system_apps.join("Editor.desktop"),
                  "[Desktop Entry]\nType=Application\nExec=editor\nName=System Editor\n").unwrap();
        fs::write(system_apps.join("Browser.desktop"),
                  "[Desktop Entry]\nType=Application\nExec=browser\nName=Browser\nKeywords=web;internet;\n").unwrap();
        let apps = scan_roots(&[user, system], "RiceBowl");
        assert_eq!(apps.len(), 1);
        assert_eq!(apps[0].action, "desktop:org-Browser.desktop");
        assert!(apps[0].matches("internet"));
        fs::remove_dir_all(base).unwrap();
    }
}
