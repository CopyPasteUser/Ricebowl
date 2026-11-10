//! Bounded discovery of installed XDG desktop entries for native menu search.
//! Desktop-file Exec fields are never interpreted here: activation is delegated
//! to `gio launch` with the verified file path, without a shell.

use std::{collections::{HashMap, HashSet}, env, fs,
          os::unix::fs::PermissionsExt, path::{Path, PathBuf}};

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
    let locale = ["LC_ALL", "LC_MESSAGES", "LANG"].iter()
        .find_map(|key| env::var(key).ok().filter(|value| !value.is_empty()))
        .unwrap_or_default();
    scan_roots(&roots, env::var("XDG_CURRENT_DESKTOP").unwrap_or_default().as_str(),
               &locale)
}

fn scan_roots(roots: &[PathBuf], current_desktop: &str, locale: &str) -> Vec<App> {
    let mut seen = HashSet::new();
    let mut apps = Vec::new();
    let mut visited_files = 0;
    for root in roots {
        let dir = root.join("applications");
        if !dir.is_absolute() { continue; }
        scan_dir(&dir, &dir, 0, current_desktop, locale, &mut seen, &mut apps,
                 &mut visited_files);
        if visited_files >= MAX_FILES { break; }
    }
    apps.sort_by(|a, b| a.name.to_lowercase().cmp(&b.name.to_lowercase())
                 .then(a.action.cmp(&b.action)));
    apps.truncate(MAX_APPS);
    apps
}

fn scan_dir(root: &Path, dir: &Path, depth: usize, current_desktop: &str, locale: &str,
            seen: &mut HashSet<String>, apps: &mut Vec<App>, visited: &mut usize) {
    if depth > MAX_DEPTH || *visited >= MAX_FILES { return; }
    let Ok(items) = fs::read_dir(dir) else { return; };
    let mut entries: Vec<_> = items.filter_map(Result::ok).take(MAX_FILES).collect();
    entries.sort_by_key(|entry| entry.file_name());
    for entry in entries {
        if *visited >= MAX_FILES { break; }
        let Ok(kind) = entry.file_type() else { continue; };
        if kind.is_dir() {
            scan_dir(root, &entry.path(), depth + 1, current_desktop, locale, seen, apps, visited);
            continue;
        }
        if !kind.is_file() || entry.path().extension().is_none_or(|ext| ext != "desktop") {
            continue;
        }
        *visited += 1;
        let path = entry.path();
        let Ok(relative) = path.strip_prefix(root) else { continue; };
        let Some(id) = desktop_id(relative) else { continue; };
        // Even a hidden or invalid high-priority entry masks a system entry.
        if !seen.insert(id.clone()) { continue; }
        let Ok(metadata) = entry.metadata() else { continue; };
        if metadata.len() > MAX_FILE_BYTES { continue; }
        let Ok(data) = fs::read_to_string(&path) else { continue; };
        if let Some((name, search_text)) = parse_entry(&data, current_desktop, locale) {
            apps.push(App { action: format!("desktop:{id}"), name, search_text,
                            path });
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

/// Desktop Entry Specification locale fallbacks: language_country@modifier,
/// language_country, language@modifier, language, then the untranslated key.
fn locale_fallbacks(locale: &str) -> Vec<String> {
    if locale.len() > 64 || locale.is_empty() { return Vec::new(); }
    let (base, modifier) = locale.split_once('@').map_or((locale, None),
        |(base, modifier)| (base, Some(modifier)));
    let base = base.split('.').next().unwrap_or("");
    let (language, country) = base.split_once('_').map_or((base, None),
        |(language, country)| (language, Some(country)));
    if matches!(language, "C" | "POSIX") || language.is_empty()
        || !language.bytes().all(|ch| ch.is_ascii_alphabetic())
        || country.is_some_and(|value| value.is_empty() ||
            !value.bytes().all(|ch| ch.is_ascii_alphanumeric()))
        || modifier.is_some_and(|value| value.is_empty() ||
            !value.bytes().all(|ch| ch.is_ascii_alphanumeric() || ch == b'_' || ch == b'-')) {
        return Vec::new();
    }
    let mut keys = Vec::new();
    if let Some(country) = country {
        if let Some(modifier) = modifier {
            keys.push(format!("{language}_{country}@{modifier}"));
        }
        keys.push(format!("{language}_{country}"));
    }
    if let Some(modifier) = modifier { keys.push(format!("{language}@{modifier}")); }
    keys.push(language.to_owned());
    keys
}

fn localized_value(fields: &HashMap<&str, &str>, key: &str,
                   locales: &[String], limit: usize) -> Option<String> {
    // A broken translation must not hide a valid app; walk progressively
    // less-specific translations before using the mandatory plain key.
    locales.iter().filter_map(|locale| fields.get(format!("{key}[{locale}]").as_str()))
        .chain(fields.get(key))
        .filter_map(|value| display_text(value, limit))
        .find(|value| !value.is_empty())
}

/// Decode standard desktop-file text escaping without exposing control chars
/// to the native menu's bounded text layout or search renderer.
fn display_text(value: &str, limit: usize) -> Option<String> {
    let mut text = String::new();
    let mut count = 0;
    let mut chars = value.chars();
    while let Some(ch) = chars.next() {
        let decoded = if ch == '\\' {
            match chars.next()? {
                's' | 'n' | 't' | 'r' => ' ',
                '\\' => '\\',
                ';' => ';',
                _ => return None,
            }
        } else if ch.is_control() { ' ' } else { ch };
        if count >= limit { break; }
        text.push(decoded);
        count += 1;
    }
    Some(text.trim().to_owned())
}

fn parse_entry(data: &str, current_desktop: &str, locale: &str) -> Option<(String, String)> {
    let mut in_section = false;
    let mut seen_section = false;
    let mut fields = HashMap::new();
    for line in data.lines() {
        let line = line.trim();
        if line.starts_with('[') {
            in_section = line == "[Desktop Entry]";
            if in_section {
                if seen_section { return None; }
                seen_section = true;
            }
            continue;
        }
        if !in_section || line.is_empty() || line.starts_with('#') { continue; }
        let Some((key, value)) = line.split_once('=') else { continue; };
        if fields.insert(key.trim(), value.trim()).is_some() { return None; }
    }
    let field = |key: &str| fields.get(key).copied().unwrap_or("");
    let only_show = field("OnlyShowIn");
    let not_show = field("NotShowIn");
    let try_exec = field("TryExec");
    if field("Type") != "Application"
        || (field("Exec").is_empty() && field("DBusActivatable") != "true")
        || field("Hidden") == "true" || field("NoDisplay") == "true"
        || (!only_show.is_empty() && !desktop_matches(only_show, current_desktop))
        || (!not_show.is_empty() && desktop_matches(not_show, current_desktop))
        || (!try_exec.is_empty() && !executable_exists(try_exec)) { return None; }
    let locales = locale_fallbacks(locale);
    if !fields.contains_key("Name") { return None; }
    let name = localized_value(&fields, "Name", &locales, 80)?;
    // Search remains useful with the untranslated app name and keywords too.
    let mut terms = vec![name.clone()];
    for key in ["Name", "GenericName", "Keywords"] {
        for value in [localized_value(&fields, key, &locales, 1024),
                      fields.get(key).and_then(|value| display_text(value, 1024))]
            .into_iter().flatten() {
            terms.push(value.replace(';', " "));
        }
    }
    let search_text = terms.join(" ").to_lowercase();
    Some((name, search_text))
}

fn desktop_matches(list: &str, current: &str) -> bool {
    current.split(':').any(|desktop| !desktop.is_empty()
        && list.split(';').any(|item| item == desktop))
}

fn executable_exists(value: &str) -> bool {
    let is_executable = |path: &Path| fs::metadata(path).is_ok_and(|metadata|
        metadata.is_file() && metadata.permissions().mode() & 0o111 != 0);
    if value.contains('/') { return Path::new(value).is_absolute()
        && is_executable(Path::new(value)); }
    env::split_paths(&env::var_os("PATH").unwrap_or_default())
        .any(|dir| dir.is_absolute() && is_executable(&dir.join(value)))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn filters_hidden_and_desktop_specific_entries() {
        let sample = "[Desktop Entry]\nType=Application\nExec=player\nName=Player\nGenericName=Media tool\nKeywords=video;music;\nOnlyShowIn=RiceBowl;GNOME;\n";
        let (name, query) = parse_entry(sample, "RiceBowl:XFCE", "de_DE.UTF-8").unwrap();
        assert_eq!(name, "Player");
        assert!(query.contains("video music"));
        assert!(parse_entry(sample, "KDE", "").is_none());
        assert!(parse_entry(&sample.replace("Name=Player", "Name=Player\nHidden=true"), "RiceBowl", "").is_none());
        assert!(parse_entry(&sample.replace("Name=Player", "Name=Player\nNoDisplay=true"), "RiceBowl", "").is_none());
        assert!(parse_entry(&sample.replace("Type=Application", "Type=Link"), "RiceBowl", "").is_none());
        assert!(parse_entry(&sample.replace("OnlyShowIn=RiceBowl;GNOME;", "NotShowIn=RiceBowl;"), "RiceBowl", "").is_none());
    }

    #[test]
    fn only_valid_ids_and_entries_are_indexed() {
        assert_eq!(desktop_id(Path::new("org/example.desktop")), Some("org-example.desktop".into()));
        assert!(desktop_id(Path::new("name with spaces.desktop")).is_none());
        assert!(desktop_id(Path::new("not-a-desktop.txt")).is_none());
        assert!(parse_entry("[Desktop Entry]\nType=Application\nExec=visible\nName=Visible", "", "").is_some());
        assert!(parse_entry("[Desktop Entry]\nType=Application\nName=Visible", "", "").is_none());
        assert!(parse_entry("[Desktop Entry]\nType=Application\nDBusActivatable=true\nName=Visible", "", "").is_some());
        assert!(parse_entry("[Desktop Entry]\nType=Application\nExec=visible\nName=Visible\nTryExec=missing-impossible-app-xyz", "", "").is_none());
    }

    #[test]
    fn desktop_file_sections_cannot_replace_main_name() {
        let data = "[Desktop Entry]\nType=Application\nExec=good\nName=Good\n[Desktop Action Evil]\nName=Bad\n";
        assert_eq!(parse_entry(data, "", "").unwrap().0, "Good");
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
        let apps = scan_roots(&[user, system], "RiceBowl", "de_DE.UTF-8");
        assert_eq!(apps.len(), 1);
        assert_eq!(apps[0].action, "desktop:org-Browser.desktop");
        assert!(apps[0].matches("internet"));
        fs::remove_dir_all(base).unwrap();
    }

    #[test]
    fn locale_fallback_order_and_posix_locale() {
        assert_eq!(locale_fallbacks("sr_RS.UTF-8@latin"),
                   ["sr_RS@latin", "sr_RS", "sr@latin", "sr"]);
        assert_eq!(locale_fallbacks("de_DE.UTF-8"), ["de_DE", "de"]);
        for locale in ["C", "C.UTF-8", "POSIX", "", "de;unsafe", "de_", "de@"] {
            assert!(locale_fallbacks(locale).is_empty(), "{locale}");
        }
    }

    #[test]
    fn localized_names_generic_names_and_keywords_remain_searchable() {
        let sample = "[Desktop Entry]\nType=Application\nExec=player\nName=File Manager\nName[de]=Dateimanager\nName[de_DE]=Dateiverwaltung\nGenericName=Browse Files\nGenericName[de]=Dateien durchsuchen\nKeywords=files;folders;\nKeywords[de]=Dateien;Ordner;\n";
        let (name, search) = parse_entry(sample, "RiceBowl", "de_DE.UTF-8").unwrap();
        assert_eq!(name, "Dateiverwaltung");
        for term in ["dateiverwaltung", "file manager", "dateien", "ordner", "browse files", "folders"] {
            assert!(search.contains(term), "missing {term}: {search}");
        }
        assert_eq!(parse_entry(sample, "RiceBowl", "de_AT.UTF-8").unwrap().0,
                   "Dateimanager");
        assert_eq!(parse_entry(sample, "RiceBowl", "fr_FR.UTF-8").unwrap().0,
                   "File Manager");
        assert_eq!(parse_entry(sample, "RiceBowl", "C.UTF-8").unwrap().0,
                   "File Manager");
    }

    #[test]
    fn malformed_localization_falls_back_without_rendering_controls() {
        let sample = "[Desktop Entry]\nType=Application\nExec=player\nName=File\\sManager\nName[de_DE]=Broken\\qTranslation\nName[de]=Datei\\sManager\nKeywords=audio\\;video;playlists;\n";
        let (name, search) = parse_entry(sample, "", "de_DE.UTF-8").unwrap();
        assert_eq!(name, "Datei Manager");
        assert!(search.contains("file manager"));
        assert!(search.contains("audio video"));
        assert_eq!(parse_entry(sample, "", "C").unwrap().0, "File Manager");
        assert!(parse_entry("[Desktop Entry]\nType=Application\nExec=player\nName=Broken\\q", "", "").is_none());
    }

    #[test]
    fn malformed_duplicates_and_repeated_main_section_are_rejected() {
        let prefix = "[Desktop Entry]\nType=Application\nExec=player\nName=Player\n";
        assert!(parse_entry(&format!("{prefix}Name=Shadow"), "", "").is_none());
        assert!(parse_entry(&format!("{prefix}Name[de]=Erste\nName[de]=Zweite"), "", "de").is_none());
        assert!(parse_entry(&format!("{prefix}[Other]\nName=Other\n[Desktop Entry]\nName=Shadow"), "", "").is_none());
    }

    #[test]
    fn try_exec_must_be_an_executable_file() {
        let suffix = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let base = env::temp_dir().join(format!("riceplate-exec-{}-{suffix}", std::process::id()));
        fs::create_dir_all(&base).unwrap();
        let binary = base.join("launcher");
        fs::write(&binary, "#!/bin/sh\n").unwrap();
        let data = format!("[Desktop Entry]\nType=Application\nExec=player\nName=Player\nTryExec={}\n", binary.display());
        assert!(parse_entry(&data, "", "").is_none());
        fs::set_permissions(&binary, fs::Permissions::from_mode(0o755)).unwrap();
        assert!(parse_entry(&data, "", "").is_some());
        assert!(!executable_exists("relative/fake"));
        fs::remove_dir_all(base).unwrap();
    }
}
