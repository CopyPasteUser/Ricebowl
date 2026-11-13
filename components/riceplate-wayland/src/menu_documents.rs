//! On-demand, read-only GTK XBEL recent document integration for Luna.
//! Never scans the filesystem or monitors activity; only explicit UI access
//! reads this optional user-owned source. Remote URIs are never exposed.

use std::{
    collections::HashSet, env, ffi::OsString, fs::{self, OpenOptions}, io::Read,
    os::unix::{ffi::OsStringExt, fs::{MetadataExt, OpenOptionsExt}},
    path::{Path, PathBuf},
};

pub const MAX_DOCUMENTS: usize = 16;
const MAX_BOOKMARKS: usize = 256;
const MAX_XBEL_BYTES: u64 = 256 * 1024;
const MAX_HREF_BYTES: usize = 4096;

#[derive(Debug, Clone)]
pub struct Document {
    pub label: String,
    pub path: PathBuf,
}

pub const ACTIONS: [&str; MAX_DOCUMENTS] = [
    "menu-document:0", "menu-document:1", "menu-document:2", "menu-document:3",
    "menu-document:4", "menu-document:5", "menu-document:6", "menu-document:7",
    "menu-document:8", "menu-document:9", "menu-document:10", "menu-document:11",
    "menu-document:12", "menu-document:13", "menu-document:14", "menu-document:15",
];

pub fn index(action: &str) -> Option<usize> {
    ACTIONS.iter().position(|token| *token == action)
}

fn recent_path() -> Option<PathBuf> {
    // A nested preview does not scan or collect activity. The explicit
    // Recent Documents action may read the caller's XDG recent list, including
    // a private XDG_DATA_HOME test fixture. No reads occur on ordinary menu
    // open and nothing is persisted by this module.
    let root = env::var_os("XDG_DATA_HOME").filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .or_else(|| env::var_os("HOME").map(|home| PathBuf::from(home).join(".local/share")))?;
    root.is_absolute().then(|| root.join("recently-used.xbel"))
}

pub fn discover() -> Vec<Document> {
    let Some(path) = recent_path() else { return Vec::new(); };
    match read_documents(&path) {
        Ok(documents) => documents,
        Err(error) => {
            eprintln!("RicePlate: cannot read recent documents: {error}");
            Vec::new()
        }
    }
}

fn read_documents(path: &Path) -> std::io::Result<Vec<Document>> {
    let file = match OpenOptions::new().read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC).open(path) {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound =>
                return Ok(Vec::new()),
            Err(error) => return Err(error),
        };
    let metadata = file.metadata()?;
    if !metadata.is_file() || metadata.uid() != unsafe { libc::geteuid() }
        || metadata.mode() & 0o022 != 0 || metadata.len() > MAX_XBEL_BYTES {
        return Ok(Vec::new());
    }
    let mut data = Vec::new();
    file.take(MAX_XBEL_BYTES + 1).read_to_end(&mut data)?;
    if data.len() as u64 > MAX_XBEL_BYTES { return Ok(Vec::new()); }
    let Ok(data) = std::str::from_utf8(&data) else { return Ok(Vec::new()); };
    Ok(parse_xbel(data))
}

/// A deliberately restricted XBEL bookmark reader: no DTD expansion,
/// network fetch, XML processor or arbitrary sub-element interpretation.
/// Malformed entries are skipped rather than evaluated as actions.
fn parse_xbel(data: &str) -> Vec<Document> {
    // This deliberately small reader is *not* an XML entity processor.
    // Reject DTDs and skip comments/CDATA so an old, commented-out bookmark
    // cannot be surfaced as a live "Recent Document" action.
    if data.contains("<!DOCTYPE") || data.contains("<!ENTITY") {
        return Vec::new();
    }
    let mut rest = data;
    let mut candidates = Vec::new();
    let mut examined = 0;
    while let Some(start) = rest.find('<') {
        rest = &rest[start + 1..];
        if let Some(comment) = rest.strip_prefix("!--") {
            let Some(end) = comment.find("-->") else { break; };
            rest = &comment[end + 3..];
            continue;
        }
        if let Some(cdata) = rest.strip_prefix("![CDATA[") {
            let Some(end) = cdata.find("]]>") else { break; };
            rest = &cdata[end + 3..];
            continue;
        }
        if !rest.starts_with("bookmark") {
            let Some(end) = rest.find('>') else { break; };
            rest = &rest[end + 1..];
            continue;
        }
        rest = &rest["bookmark".len()..];
        let Some(end) = rest.find('>') else { break; };
        if !rest.starts_with(char::is_whitespace) {
            rest = &rest[end + 1..];
            continue;
        }
        examined += 1;
        if examined > MAX_BOOKMARKS { break; }
        if end > MAX_HREF_BYTES { rest = &rest[end + 1..]; continue; }
        let header = &rest[..end];
        if let Some(href) = attribute(header, "href").and_then(unescape_xml) {
            if let Some(path) = file_uri(&href) {
                // Exclude inaccessible files before surfacing a launch target;
                // an existence-only stat would misleadingly expose unreadable
                // bookmarks. A subsequent Gio open still revalidates at use.
                if fs::metadata(&path).is_ok_and(|meta| meta.is_file())
                    && OpenOptions::new().read(true).open(&path).is_ok() {
                    let label = path.file_name().map(|value| value.to_string_lossy())
                        .unwrap_or_default().chars()
                        .map(|ch| if ch.is_control() { ' ' } else { ch })
                        .take(48).collect::<String>();
                    if !label.trim().is_empty() {
                        let when = attribute(header, "visited")
                            .or_else(|| attribute(header, "modified"))
                            .or_else(|| attribute(header, "added"))
                            .unwrap_or("").to_owned();
                        candidates.push((when, Document { label, path }));
                    }
                }
            }
        }
        rest = &rest[end + 1..];
    }
    candidates.sort_by(|a, b| b.0.cmp(&a.0));
    let mut seen = HashSet::new();
    candidates.into_iter().filter_map(|(_, document)| {
        seen.insert(document.path.clone()).then_some(document)
    }).take(MAX_DOCUMENTS).collect()
}

fn attribute<'a>(header: &'a str, key: &str) -> Option<&'a str> {
    let prefix = format!("{key}=\"");
    for (at, _) in header.match_indices(&prefix) {
        if at == 0 || !header.as_bytes()[at - 1].is_ascii_whitespace() { continue; }
        let value = &header[at + prefix.len()..];
        if let Some(end) = value.find('"') { return Some(&value[..end]); }
    }
    None
}

fn unescape_xml(value: &str) -> Option<String> {
    if value.len() > MAX_HREF_BYTES { return None; }
    let mut result = String::new();
    let mut remaining = value;
    while !remaining.is_empty() {
        if let Some(tail) = remaining.strip_prefix('&') {
            let end = tail.find(';')?;
            if end > 12 { return None; }
            let entity = &tail[..end];
            let ch = match entity {
                "amp" => '&', "quot" => '"', "apos" => '\'', "lt" => '<', "gt" => '>',
                _ if entity.starts_with("#x") => u32::from_str_radix(&entity[2..], 16)
                    .ok().and_then(char::from_u32)?,
                _ if entity.starts_with('#') => entity[1..].parse::<u32>()
                    .ok().and_then(char::from_u32)?,
                _ => return None,
            };
            if ch.is_control() { return None; }
            result.push(ch);
            remaining = &tail[end + 1..];
        } else {
            let ch = remaining.chars().next()?;
            if ch.is_control() { return None; }
            result.push(ch);
            remaining = &remaining[ch.len_utf8()..];
        }
    }
    Some(result)
}

fn file_uri(uri: &str) -> Option<PathBuf> {
    let encoded = uri.strip_prefix("file://")?;
    if !encoded.starts_with('/') || encoded.starts_with("//")
        || encoded.contains('?') || encoded.contains('#')
        || encoded.len() > MAX_HREF_BYTES { return None; }
    let src = encoded.as_bytes();
    let mut output = Vec::with_capacity(src.len());
    let mut i = 0;
    while i < src.len() {
        let byte = if src[i] == b'%' {
            let high = src.get(i + 1)?.to_ascii_lowercase();
            let low = src.get(i + 2)?.to_ascii_lowercase();
            let digit = |v: u8| match v {
                b'0'..=b'9' => Some(v - b'0'),
                b'a'..=b'f' => Some(v - b'a' + 10),
                _ => None,
            };
            i += 3;
            digit(high)? * 16 + digit(low)?
        } else {
            let byte = src[i];
            i += 1;
            byte
        };
        if byte == 0 || byte < 0x20 || byte == 0x7f { return None; }
        output.push(byte);
    }
    let path = PathBuf::from(OsString::from_vec(output));
    path.is_absolute().then_some(path)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{os::unix::fs::{symlink, PermissionsExt},
              time::{SystemTime, UNIX_EPOCH}};

    #[test]
    fn rejects_remote_and_broken_file_uris() {
        assert!(file_uri("https://example.com/readme").is_none());
        assert!(file_uri("file://server/private").is_none());
        assert!(file_uri("file:///a/%00secret").is_none());
        assert!(file_uri("file:///a/%gg").is_none());
        assert!(file_uri("file:///a/?query").is_none());
        assert_eq!(file_uri("file:///tmp/My%20Document.txt"),
                   Some(PathBuf::from("/tmp/My Document.txt")));
        assert!(index("menu-document:16").is_none());
        assert!(index("desktop:evil.desktop").is_none());
    }

    #[test]
    fn reads_only_existing_local_documents_and_deduplicates() {
        let nonce = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let dir = env::temp_dir().join(format!("riceplate-xbel-{}-{nonce}", std::process::id()));
        fs::create_dir(&dir).unwrap();
        let file = dir.join("My file.txt");
        fs::write(&file, b"document").unwrap();
        let uri = format!("file://{}", file.display()).replace(' ', "%20");
        let xbel = format!(
            "<xbel><bookmark href=\"{uri}\" visited=\"2026-11-13T12:00:00Z\"/>\\n             <bookmark href=\"{uri}\" visited=\"2026-11-12T12:00:00Z\"/>             <bookmark href=\"https://example.com/file\"/></xbel>");
        let docs = parse_xbel(&xbel);
        assert_eq!(docs.len(), 1);
        // XML comments and CDATA must not fabricate live bookmark actions;
        // refuse document type declarations rather than expanding entities.
        let single = format!("<bookmark href=\"{uri}\"/>");
        let guarded = format!(
            "<xbel><!--{single}--><![CDATA[{single}]]>{single}</xbel>");
        assert_eq!(parse_xbel(&guarded).len(), 1);
        assert!(parse_xbel(&format!(
            "<!DOCTYPE xbel [<!ENTITY ignored \"file://example\">]><xbel>{single}</xbel>"
        )).is_empty());
        assert_eq!(docs[0].label, "My file.txt");
        assert_eq!(docs[0].path, file);
        let link = dir.join("recently-used.xbel");
        symlink(&file, &link).unwrap();
        assert!(read_documents(&link).is_err());
        fs::remove_file(&link).unwrap();
        fs::write(&link, xbel).unwrap();
        fs::set_permissions(&link, fs::Permissions::from_mode(0o666)).unwrap();
        assert!(read_documents(&link).unwrap().is_empty(),
                "World-writable recent-document sources are untrusted");
        fs::remove_dir_all(dir).unwrap();
    }
}
