//! On-demand native notification view, backed by RiceBowl's existing Mako bridge.
//! The bridge remains the sole authority for validating active IDs and actions.

use std::{io::Read, process::{Command, Stdio}, thread, time::{Duration, Instant}};

use serde::Deserialize;

const MAX_RESPONSE: u64 = 512 * 1024;
pub const VISIBLE_ROWS: usize = 3;
pub const ROW_TOP: u32 = 90;
pub const ROW_HEIGHT: u32 = 54;
pub const ACTION_TOP: u32 = 155;
pub const ACTION_HEIGHT: u32 = 32;
const OPEN_REFRESH_INTERVAL: Duration = Duration::from_secs(3);
const RETRY_REFRESH_INTERVAL: Duration = Duration::from_secs(12);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Hit { Row(usize), Action(usize), BodyPage(isize), Tab(bool), Back, Refresh, Dismiss }

pub const BODY_WIDTH: usize = 37;
pub const BODY_LINES_PER_PAGE: usize = 2;
pub const COMPACT_ROW_TOP: u32 = 70;
pub const COMPACT_ROW_HEIGHT: u32 = 34;
pub const COMPACT_FOOTER_HEIGHT: u32 = 26;
pub const COMPACT_ACTION_HEIGHT: u32 = 30;

pub fn compact_rows(size: (u32, u32)) -> usize {
    (size.1.saturating_sub(COMPACT_ROW_TOP + COMPACT_FOOTER_HEIGHT)
        / COMPACT_ROW_HEIGHT).clamp(1, VISIBLE_ROWS as u32) as usize
}

pub fn compact_action_top(height: u32) -> u32 {
    if height < 174 { 88 } else { 118 }
}

pub fn compact_action_rows(size: (u32, u32)) -> usize {
    (size.1.saturating_sub(compact_action_top(size.1) + COMPACT_FOOTER_HEIGHT)
        / COMPACT_ACTION_HEIGHT).clamp(1, VISIBLE_ROWS as u32) as usize
}

pub fn compact_body_width(width: u32) -> usize {
    (width.saturating_sub(16) / 8).max(1) as usize
}

pub fn compact_body_rows(height: u32) -> usize {
    if height < 174 { 1 } else { BODY_LINES_PER_PAGE }
}

/// Predictable, bounded word wrapping; preserves authored paragraph breaks.
/// Full original text remains available to accessibility clients.
pub fn body_lines(body: &str) -> Vec<String> {
    body_lines_with_width(body, BODY_WIDTH)
}

pub fn body_lines_with_width(body: &str, width: usize) -> Vec<String> {
    let width = width.clamp(1, BODY_WIDTH);
    let mut lines = Vec::new();
    for paragraph in body.split('\n') {
        let mut line = String::new();
        for word in paragraph.split_whitespace() {
            let length = line.chars().count();
            if length > 0 && length + 1 + word.chars().count() > width {
                lines.push(std::mem::take(&mut line));
            } else if length > 0 { line.push(' '); }
            for character in word.chars() {
                if line.chars().count() == width {
                    lines.push(std::mem::take(&mut line));
                }
                line.push(character);
            }
        }
        lines.push(line);
    }
    lines
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct Action {
    pub key: String,
    pub label: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Notice {
    pub id: u32,
    pub summary: String,
    pub body: String,
    pub app_name: String,
    pub urgency: String,
    pub actions: Vec<Action>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Snapshot {
    pub active: Vec<Notice>,
    pub history: Vec<Notice>,
}

#[derive(Debug, Default)]
pub struct State {
    pub open: bool,
    pub loading: bool,
    pub error: Option<&'static str>,
    pub notices: Vec<Notice>,
    pub history: Vec<Notice>,
    pub show_history: bool,
    pub selected: usize,
    pub detail_id: Option<u32>,
    pub selected_action: usize,
    pub body_page: usize,
    pub revision: u64,
    pub silent_loading: bool,
    pub sync_error: bool,
    next_refresh: Option<Instant>,
    // The native font can advance 16px instead of the legacy 8px. Keep
    // wrapping, pagination, pointer hits and accessibility on one width.
    glyph_scale: u32,
}

impl State {
    pub fn configure_glyph_scale(&mut self, scale: u32) {
        self.glyph_scale = scale.clamp(1, 2);
        self.body_page = self.body_page.min(self.body_page_count().saturating_sub(1));
    }

    fn glyph_scale(&self) -> u32 { self.glyph_scale.max(1) }

    pub fn body_text_width(&self) -> usize {
        (BODY_WIDTH / self.glyph_scale() as usize).max(1)
    }

    pub fn compact_text_width(&self, width: u32) -> usize {
        (compact_body_width(width) / self.glyph_scale() as usize).max(1)
    }

    pub fn body_text_lines(&self, body: &str) -> Vec<String> {
        body_lines_with_width(body, self.body_text_width())
    }

    pub fn close(&mut self) {
        self.open = false;
        self.loading = false;
        self.notices.clear(); // Private notification text must not be retained.
        self.history.clear();
        self.show_history = false;
        self.error = None;
        self.selected = 0;
        self.detail_id = None;
        self.selected_action = 0;
        self.body_page = 0;
        self.silent_loading = false;
        self.sync_error = false;
        self.next_refresh = None;
    }

    pub fn begin(&mut self) -> u64 {
        self.open = true;
        self.loading = true;
        self.error = None;
        self.silent_loading = false;
        self.sync_error = false;
        self.next_refresh = None;
        self.revision = self.revision.wrapping_add(1);
        self.revision
    }

    /// Deterministic, non-polling compositor screenshot state. The production
    /// notification bridge is still the sole source of live notifications.
    pub fn show_preview(&mut self, snapshot: Snapshot) {
        let revision = self.begin();
        self.update(revision, Ok(snapshot));
        self.next_refresh = None;
    }

    /// Re-read Mako only while the user keeps the center open. No permanent
    /// notification poller is installed and in-flight mutations take priority.
    pub fn refresh_timeout(&self, now: Instant) -> Option<Duration> {
        (self.open && !self.loading && !self.silent_loading)
            .then(|| self.next_refresh.map(|when| when.saturating_duration_since(now)))
            .flatten()
    }

    pub fn begin_background(&mut self, now: Instant) -> Option<u64> {
        self.refresh_timeout(now).filter(|remaining| remaining.is_zero())?;
        self.silent_loading = true;
        self.next_refresh = None;
        self.revision = self.revision.wrapping_add(1);
        Some(self.revision)
    }

    pub fn update(&mut self, revision: u64, result: Result<Snapshot, &'static str>) -> bool {
        if !self.open || revision != self.revision { return false; }
        let background = self.silent_loading;
        self.loading = false;
        self.silent_loading = false;
        self.next_refresh = Some(Instant::now() + if result.is_ok() {
            OPEN_REFRESH_INTERVAL
        } else { RETRY_REFRESH_INTERVAL });
        match result {
            Ok(snapshot) => {
                let prior_detail = self.detail_notice().cloned();
                let prior_action_key = self.selected_action().map(|(_, action)| action.key.clone());
                let previous_id = self.detail_id.or_else(||
                    self.visible_notices().get(self.selected).map(|notice| notice.id));
                self.notices = snapshot.active;
                self.history = snapshot.history;
                self.selected = previous_id.and_then(|id| self.visible_notices()
                    .iter().position(|notice| notice.id == id))
                    .unwrap_or_else(|| if background { self.visible_notices().len() }
                                    else { self.selected.min(self.visible_notices().len().saturating_sub(1)) });
                // Do not retain an actionable detail if a host restart reused
                // the same numeric ID for different message content.
                if self.detail_id.is_some() && (self.detail_notice().is_none()
                    || prior_detail.as_ref().is_some_and(|old| self.detail_notice().is_some_and(|new|
                        old.app_name != new.app_name || old.summary != new.summary
                        || old.body != new.body))) {
                    self.close_detail();
                }
                let next_action = prior_action_key.as_ref().and_then(|key|
                    self.detail_notice().and_then(|notice|
                        notice.actions.iter().position(|action| &action.key == key)));
                self.selected_action = next_action.unwrap_or_else(|| {
                    if prior_action_key.is_some() {
                        self.detail_notice().map_or(0, |notice| notice.actions.len())
                    } else {
                        self.selected_action.min(self.detail_notice()
                            .map_or(0, |notice| notice.actions.len().saturating_sub(1)))
                    }
                });
                self.body_page = self.body_page.min(self.body_page_count().saturating_sub(1));
                self.error = None;
                self.sync_error = false;
            }
            Err(_) if background => self.sync_error = true,
            Err(message) => self.error = Some(message),
        }
        true
    }

    pub fn select(&mut self, delta: isize) {
        if self.visible_notices().is_empty() { return; }
        self.selected = (self.selected as isize + delta)
            .clamp(0, self.visible_notices().len() as isize - 1) as usize;
    }

    pub fn select_tab(&mut self, history: bool) {
        self.show_history = history;
        self.selected = 0;
        self.close_detail();
    }

    pub fn open_detail(&mut self, index: usize) -> bool {
        if self.loading || self.error.is_some() { return false; }
        let Some(notice) = self.visible_notices().get(index) else { return false; };
        self.detail_id = Some(notice.id);
        self.selected = index;
        self.selected_action = 0;
        self.body_page = 0;
        true
    }

    pub fn close_detail(&mut self) {
        self.detail_id = None;
        self.selected_action = 0;
        self.body_page = 0;
    }

    pub fn detail_notice(&self) -> Option<&Notice> {
        let id = self.detail_id?;
        self.visible_notices().iter().find(|notice| notice.id == id)
    }

    pub fn select_action(&mut self, delta: isize) {
        let count = self.detail_notice().map_or(0, |notice| notice.actions.len());
        if count == 0 { return; }
        self.selected_action = (self.selected_action as isize + delta)
            .clamp(0, count as isize - 1) as usize;
    }

    pub fn body_page_count(&self) -> usize {
        self.detail_notice().map_or(1, |notice|
            self.body_text_lines(&notice.body).len().div_ceil(BODY_LINES_PER_PAGE).max(1))
    }

    pub fn change_body_page(&mut self, delta: isize) {
        self.body_page = (self.body_page as isize + delta)
            .clamp(0, self.body_page_count() as isize - 1) as usize;
    }

    pub fn compact_body_page_count(&self, size: (u32, u32)) -> usize {
        self.detail_notice().map_or(1, |notice|
            body_lines_with_width(&notice.body, self.compact_text_width(size.0)).len()
                .div_ceil(compact_body_rows(size.1)).max(1))
    }

    pub fn change_compact_body_page(&mut self, delta: isize, size: (u32, u32)) {
        self.body_page = (self.body_page as isize + delta)
            .clamp(0, self.compact_body_page_count(size) as isize - 1) as usize;
    }

    pub fn compact_first_row(&self, size: (u32, u32)) -> usize {
        (self.selected / compact_rows(size)) * compact_rows(size)
    }

    pub fn compact_first_action_row(&self, size: (u32, u32)) -> usize {
        (self.selected_action / compact_action_rows(size)) * compact_action_rows(size)
    }

    pub fn first_action_row(&self) -> usize {
        (self.selected_action / VISIBLE_ROWS) * VISIBLE_ROWS
    }

    pub fn action_at(&self, index: usize) -> Option<(u32, &Action)> {
        if self.show_history || self.loading || self.error.is_some() || self.sync_error {
            return None;
        }
        let notice = self.detail_notice()?;
        notice.actions.get(index).map(|action| (notice.id, action))
    }

    pub fn selected_action(&self) -> Option<(u32, &Action)> {
        self.action_at(self.selected_action)
    }

    pub fn visible_notices(&self) -> &[Notice] {
        if self.show_history { &self.history } else { &self.notices }
    }

    pub fn first_row(&self) -> usize {
        (self.selected / VISIBLE_ROWS) * VISIBLE_ROWS
    }

    pub fn selected_id(&self) -> Option<u32> {
        (!self.show_history && !self.loading && self.error.is_none() && !self.sync_error)
            .then(|| self.notices.get(self.selected))
            .flatten().map(|n| n.id)
    }

    pub fn hit(&self, x: f64, y: f64) -> Option<Hit> {
        if !self.open || !x.is_finite() || !y.is_finite()
            || !(0.0..320.0).contains(&x) || !(0.0..304.0).contains(&y) {
            return None;
        }
        if self.detail_id.is_none() && (40.0..86.0).contains(&y) {
            return Some(Hit::Tab(x >= 160.0));
        }
        if (260.0..304.0).contains(&y) {
            return Some(if x < 90.0 { Hit::Back }
                         else if x < 177.0 { Hit::Refresh }
                         else if self.selected_id().is_some() { Hit::Dismiss }
                         else { return None });
        }
        if self.detail_id.is_some() {
            if (90.0..138.0).contains(&y) && self.body_page_count() > 1 {
                return Some(Hit::BodyPage(if x < 160.0 { -1 } else { 1 }));
            }
            if (f64::from(ACTION_TOP)..f64::from(ACTION_TOP + VISIBLE_ROWS as u32 * ACTION_HEIGHT))
                .contains(&y) {
                let index = self.first_action_row() +
                    ((y as u32 - ACTION_TOP) / ACTION_HEIGHT) as usize;
                return self.action_at(index).map(|_| Hit::Action(index));
            }
            return None;
        }
        if (f64::from(ROW_TOP)..f64::from(ROW_TOP + VISIBLE_ROWS as u32 * ROW_HEIGHT))
            .contains(&y) && !self.loading && self.error.is_none() {
            let index = self.first_row() + ((y as u32 - ROW_TOP) / ROW_HEIGHT) as usize;
            return (index < self.visible_notices().len()).then_some(Hit::Row(index));
        }
        None
    }

    /// Share exact compact hit geometry with the painter and accessibility
    /// viewport. Unsupported microscopic outputs keep the scaled old view.
    pub fn compact_hit(&self, x: f64, y: f64, size: (u32, u32)) -> Option<Hit> {
        if !self.open || !x.is_finite() || !y.is_finite()
            || x < 0.0 || y < 0.0 || x >= f64::from(size.0) || y >= f64::from(size.1) {
            return None;
        }
        let width = f64::from(size.0);
        let footer = f64::from(size.1.saturating_sub(COMPACT_FOOTER_HEIGHT));
        if y >= footer {
            return Some(if x < width / 3.0 { Hit::Back }
                else if x < width * 2.0 / 3.0 { Hit::Refresh }
                else if self.selected_id().is_some() { Hit::Dismiss }
                else { return None });
        }
        if self.detail_id.is_none() {
            if (30.0..64.0).contains(&y) { return Some(Hit::Tab(x >= width / 2.0)); }
            if y >= f64::from(COMPACT_ROW_TOP) {
                let row = ((y as u32 - COMPACT_ROW_TOP) / COMPACT_ROW_HEIGHT) as usize;
                if row < compact_rows(size) {
                    let index = self.compact_first_row(size) + row;
                    if !self.loading && self.error.is_none() && index < self.visible_notices().len() {
                        return Some(Hit::Row(index));
                    }
                }
            }
        } else {
            let top = compact_action_top(size.1);
            if y >= f64::from(top) {
                let row = ((y as u32 - top) / COMPACT_ACTION_HEIGHT) as usize;
                if row < compact_action_rows(size) {
                    let index = self.compact_first_action_row(size) + row;
                    return self.action_at(index).map(|_| Hit::Action(index));
                }
            } else if (66.0..f64::from(top)).contains(&y)
                      && self.compact_body_page_count(size) > 1 {
                return Some(Hit::BodyPage(if x < width / 2.0 { -1 } else { 1 }));
            }
        }
        None
    }
}

#[derive(Debug)]
pub enum Request {
    Refresh(u64),
    Dismiss(u64, u32),
    Invoke(u64, u32, String),
}

pub enum Intent {
    Refresh,
    Dismiss(u32),
    Invoke(u32, String),
}

impl Request {
    pub fn revision(&self) -> u64 {
        match self {
            Self::Refresh(revision) | Self::Dismiss(revision, _)
            | Self::Invoke(revision, _, _) => *revision,
        }
    }
}

#[derive(Deserialize)]
struct Record {
    id: u32,
    summary: String,
    body: String,
    #[serde(default)]
    app_name: String,
    #[serde(default)]
    urgency: String,
    #[serde(default)]
    actions: Vec<Action>,
}

pub fn parse(raw: &[u8]) -> Result<Snapshot, &'static str> {
    if raw.len() > MAX_RESPONSE as usize { return Err("Notification data too large"); }
    // The existing bridge may return extra metadata/history; consume only
    // active, sanitized records and never persist or replay notification actions.
    let value: serde_json::Value = serde_json::from_slice(raw)
        .map_err(|_| "Invalid notification data")?;
    if value.get("ok") != Some(&serde_json::Value::Bool(true))
        || value.get("truncated") == Some(&serde_json::Value::Bool(true)) {
        return Err("Notification list unavailable");
    }
    Ok(Snapshot {
        active: parse_records(&value, "active")?,
        history: parse_records(&value, "history")?,
    })
}

fn parse_records(value: &serde_json::Value, field: &str) -> Result<Vec<Notice>, &'static str> {
    let array = value.get(field).and_then(|v| v.as_array())
        .ok_or("Invalid notification data")?;
    if array.len() > 64 { return Err("Notification list too long"); }
    let mut notices = Vec::new();
    for entry in array {
        let mut record: Record = serde_json::from_value(entry.clone())
            .map_err(|_| "Invalid notification data")?;
        if record.id == 0 || record.summary.chars().count() > 160
            || record.body.chars().count() > 2048
            || record.app_name.chars().count() > 80 || record.urgency.chars().count() > 32
            || record.actions.len() > 8 || record.actions.iter().any(|action| {
                action.key.is_empty() || action.key.chars().count() > 80
                    || action.label.is_empty() || action.label.chars().count() > 80
                    || action.key.chars().any(char::is_control)
                    || action.label.chars().any(char::is_control)
            })
            || record.actions.iter().enumerate().any(|(index, action)|
                record.actions[..index].iter().any(|other| other.key == action.key))
            || notices.iter().any(|item: &Notice| item.id == record.id) {
            return Err("Invalid notification data");
        }
        if field == "history" { record.actions.clear(); }
        notices.push(Notice {
            id: record.id, summary: record.summary, body: record.body,
            app_name: record.app_name, urgency: record.urgency,
            actions: record.actions,
        });
    }
    Ok(notices)
}

fn call_cli(arguments: &[&str]) -> Result<Vec<u8>, &'static str> {
    let mut child = Command::new("ricebowl").args(arguments)
        .stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::null())
        .spawn().map_err(|_| "RicePop CLI unavailable")?;
    let stdout = child.stdout.take().ok_or("RicePop CLI unavailable")?;
    // Drain concurrently: waiting before reading can deadlock on a large pipe.
    let reader = thread::spawn(move || {
        let mut data = Vec::new();
        stdout.take(MAX_RESPONSE + 1).read_to_end(&mut data).map(|_| data)
    });
    let started = Instant::now();
    let success = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status.success(),
            Ok(None) if started.elapsed() < Duration::from_secs(9) => {
                thread::sleep(Duration::from_millis(20));
            }
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                break false;
            }
        }
    };
    let output = reader.join().map_err(|_| "RicePop CLI failed")?
        .map_err(|_| "RicePop CLI failed")?;
    if !success || output.len() > MAX_RESPONSE as usize {
        return Err("Notification host unavailable");
    }
    Ok(output)
}

pub fn run(request: &Request) -> Result<Snapshot, &'static str> {
    match request {
        Request::Dismiss(_, notification_id) => {
            let id = notification_id.to_string();
            let output = call_cli(&["de", "notification-dismiss", "--notification-id", &id, "--json"])?;
            let reply: serde_json::Value = serde_json::from_slice(&output)
                .map_err(|_| "Dismissal response invalid")?;
            if reply.get("ok") != Some(&serde_json::Value::Bool(true))
                || reply.get("dismissed") != Some(&serde_json::Value::Bool(true))
                || reply.get("notification_id").and_then(|value| value.as_u64()) != Some(u64::from(*notification_id)) {
                return Err("Notification could not be dismissed");
            }
        }
        Request::Invoke(_, notification_id, key) => {
            let id = notification_id.to_string();
            let output = call_cli(&["de", "notification-invoke", "--notification-id", &id,
                                     "--action-key", key, "--json"])?;
            let reply: serde_json::Value = serde_json::from_slice(&output)
                .map_err(|_| "Action response invalid")?;
            if reply.get("ok") != Some(&serde_json::Value::Bool(true))
                || reply.get("invoked") != Some(&serde_json::Value::Bool(true))
                || reply.get("notification_id").and_then(|value| value.as_u64()) != Some(u64::from(*notification_id))
                || reply.get("action_key").and_then(|value| value.as_str()) != Some(key.as_str()) {
                return Err("Notification action unavailable");
            }
        }
        Request::Refresh(_) => {}
    }
    parse(&call_cli(&["de", "notifications", "--json"])?)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn compact_notification_hit_and_paging_keep_rows_reachable() {
        let size = (168, 144);
        let mut state = State::default();
        let current = state.begin();
        let notices = (1..=5).map(|id| Notice {
            id, summary: format!("Notification {id}"), app_name: "App".into(),
            body: "An important message with more than nineteen characters".into(),
            actions: (0..4).map(|index| Action {
                key: index.to_string(), label: format!("Action {index}"),
            }).collect(), urgency: String::new(),
        }).collect();
        assert!(state.update(current, Ok(Snapshot { active: notices, history: vec![] })));
        assert_eq!(compact_rows(size), 1);
        assert_eq!(state.compact_hit(15.0, 80.0, size), Some(Hit::Row(0)));
        state.select(3);
        assert_eq!(state.compact_first_row(size), 3);
        assert_eq!(state.compact_hit(15.0, 80.0, size), Some(Hit::Row(3)));
        assert_eq!(state.compact_hit(160.0, 135.0, size), Some(Hit::Dismiss));
        assert_eq!(state.compact_hit(170.0, 80.0, size), None);
        assert!(state.open_detail(3));
        assert!(state.compact_body_page_count(size) > 1);
        assert_eq!(state.compact_hit(145.0, 76.0, size), Some(Hit::BodyPage(1)));
        state.change_compact_body_page(1, size);
        assert_eq!(state.body_page, 1);
        assert_eq!(compact_action_rows(size), 1);
        state.select_action(2);
        assert_eq!(state.compact_first_action_row(size), 2);
        assert_eq!(state.compact_hit(15.0, 95.0, size), Some(Hit::Action(2)));
        assert_eq!(state.compact_hit(f64::NAN, 95.0, size), None);
        assert_eq!(state.compact_hit(15.0, 144.0, size), None);
    }

    #[test]
    fn compact_body_wrap_preserves_all_content_without_narrow_clipping() {
        let text = "A longer text that needs wrapping";
        let lines = body_lines_with_width(text, 12);
        assert!(lines.len() > 2);
        assert!(lines.iter().all(|line| line.chars().count() <= 12));
        assert_eq!(lines.join(" "), text);
        assert_eq!(compact_rows((240, 304)), VISIBLE_ROWS);
        assert_eq!(compact_action_rows((240, 304)), VISIBLE_ROWS);
    }

    #[test]
    fn active_only_malformed_or_ambiguous_data_fails_closed() {
        let fixture = br#"{"ok":true,"active":[{"id":42,"summary":"Hello","body":"News","app_name":"App"}],"history":[{"id":99,"summary":"","body":""}]}"#;
        assert_eq!(parse(fixture).unwrap(), Snapshot {
            active: vec![Notice { id: 42, summary: "Hello".into(), body: "News".into(),
                                  app_name: "App".into(), ..Notice::default() }],
            history: vec![Notice { id: 99, ..Notice::default() }],
        });
        for bad in [br#"{"ok":false,"active":[],"history":[]}"#.as_slice(),
                    br#"{"ok":true,"truncated":true,"active":[],"history":[]}"#,
                    br#"{"ok":true,"active":[{"id":0,"summary":"x","body":""}],"history":[]}"#,
                    br#"{"ok":true,"active":[{"id":1,"summary":"x","body":""},{"id":1,"summary":"y","body":""}],"history":[]}"#,
                    br#"{"ok":true,"active":[{"id":1,"summary":2,"body":""}],"history":[]}"#,
                    br#"{"ok":true,"active":[]}"#] {
            assert!(parse(bad).is_err());
        }
    }

    #[test]
    fn selection_and_stale_response_are_bounded() {
        let mut state = State::default();
        let old = state.begin();
        let current = state.begin();
        assert!(!state.update(old, Ok(Snapshot { active: vec![], history: vec![] })));
        let items = (1..=8).map(|id| Notice { id, summary: "x".into(),
                                               ..Notice::default() }).collect();
        assert!(state.update(current, Ok(Snapshot { active: items, history: vec![Notice {
            id: 77, summary: "Old".into(), body: "Past".into(), ..Notice::default()
        }] })));
        state.select(7);
        assert_eq!(state.first_row(), 6);
        assert_eq!(state.selected_id(), Some(8));
        state.select(1);
        assert_eq!(state.selected_id(), Some(8));
        state.select_tab(true);
        assert_eq!(state.visible_notices().len(), 1);
        assert_eq!(state.selected_id(), None);
        assert_eq!(state.hit(250.0, 55.0), Some(Hit::Tab(true)));
        state.open = false;
        assert!(!state.update(current, Ok(Snapshot { active: vec![], history: vec![] })));
        state.close();
        assert!(state.notices.is_empty());
        assert!(state.history.is_empty());
    }

    #[test]
    fn notification_buttons_are_explicit_and_hit_regions_bounded() {
        let mut state = State::default();
        let revision = state.begin();
        state.update(revision, Ok(Snapshot { active: vec![Notice {
            id: 4, summary: "x".into(), ..Notice::default()
        }], history: vec![] }));
        assert_eq!(state.hit(10.0, 91.0), Some(Hit::Row(0)));
        assert_eq!(state.hit(10.0, 145.0), None);
        assert_eq!(state.hit(10.0, 275.0), Some(Hit::Back));
        assert_eq!(state.hit(115.0, 275.0), Some(Hit::Refresh));
        assert_eq!(state.hit(280.0, 275.0), Some(Hit::Dismiss));
        assert_eq!(state.hit(-2.0, 275.0), None);
        assert_eq!(state.hit(f64::NAN, 275.0), None);
    }

    #[test]
    fn details_keep_history_read_only_and_stale_actions_non_invokable() {
        let data = br#"{"ok":true,"active":[{"id":7,"summary":"Mail","body":"Read me","app_name":"Mail","urgency":"normal","actions":[{"key":"default","label":"Open"},{"key":"reply","label":"Reply"}]}],"history":[{"id":8,"summary":"Past","body":"Old","actions":[{"key":"default","label":"Nope"}]}]}"#;
        let mut state = State::default();
        let revision = state.begin();
        assert!(state.update(revision, parse(data)));
        assert!(state.open_detail(0));
        assert_eq!(state.detail_notice().unwrap().app_name, "Mail");
        assert_eq!(state.selected_action().unwrap().1.key, "default");
        state.select_action(1);
        assert_eq!(state.selected_action().unwrap().1.label, "Reply");
        assert_eq!(state.hit(20.0, ACTION_TOP as f64 + ACTION_HEIGHT as f64 + 2.0),
                   Some(Hit::Action(1)));
        state.select_tab(true);
        assert!(state.open_detail(0));
        assert_eq!(state.detail_notice().unwrap().actions.len(), 0);
        assert_eq!(state.selected_action(), None);
        assert_eq!(state.hit(20.0, ACTION_TOP as f64 + 2.0), None);
        state.select_tab(false);
        assert!(state.open_detail(0));
        let next = state.begin();
        assert!(state.update(next, parse(br#"{"ok":true,"active":[],"history":[]}"#)));
        assert_eq!(state.detail_id, None);
        assert_eq!(state.selected_action(), None);
        state.close();
        assert!(state.notices.is_empty());
    }

    #[test]
    fn open_only_live_refresh_preserves_selection_and_retries_failures() {
        let now = Instant::now();
        let mut state = State::default();
        assert_eq!(state.refresh_timeout(now), None);
        let initial = state.begin();
        assert_eq!(state.refresh_timeout(now), None);
        assert!(state.update(initial, Ok(Snapshot { active: vec![Notice {
            id: 4, summary: "First".into(), ..Notice::default()
        }, Notice { id: 8, summary: "Second".into(), ..Notice::default() }], history: vec![] })));
        assert!(state.refresh_timeout(now).is_some());
        state.select(1);
        assert!(state.open_detail(1));
        let background = state.begin_background(now + Duration::from_secs(4)).unwrap();
        assert_eq!(state.refresh_timeout(now + Duration::from_secs(4)), None);
        assert_eq!(state.begin_background(now + Duration::from_secs(4)), None);
        assert!(state.update(background, Ok(Snapshot { active: vec![Notice {
            id: 8, summary: "Second".into(), ..Notice::default()
        }], history: vec![] })));
        assert_eq!(state.selected, 0);
        assert_eq!(state.detail_notice().unwrap().summary, "Second");
        let retry = state.begin_background(now + Duration::from_secs(8)).unwrap();
        assert!(state.update(retry, Err("Host offline")));
        assert!(state.sync_error);
        assert!(state.detail_notice().is_some());
        assert_eq!(state.selected_id(), None);
        assert_eq!(state.selected_action(), None);
        assert_eq!(state.begin_background(now + Duration::from_secs(10)), None);
        let recovered = state.begin_background(now + Duration::from_secs(21)).unwrap();
        assert!(state.update(recovered, Ok(Snapshot { active: vec![], history: vec![] })));
        assert!(!state.sync_error);
        assert_eq!(state.detail_id, None);
        state.close();
        assert_eq!(state.refresh_timeout(now + Duration::from_secs(60)), None);
        assert_eq!(state.begin_background(now + Duration::from_secs(60)), None);
    }

    #[test]
    fn full_notification_body_is_word_wrapped_and_paged_without_truncation() {
        let message = format!("Grüße aus München\n{}", "日本語 café ".repeat(30));
        let lines = body_lines(&message);
        assert!(lines.len() > BODY_LINES_PER_PAGE);
        assert!(lines.iter().all(|line| line.chars().count() <= BODY_WIDTH));
        assert_eq!(lines[0], "Grüße aus München");
        assert!(lines.iter().any(|line| line.contains("café")));
        let mut state = State::default();
        let revision = state.begin();
        assert!(state.update(revision, Ok(Snapshot { active: vec![Notice {
            id: 5, body: message, ..Notice::default()
        }], history: vec![] })));
        assert!(state.open_detail(0));
        assert!(state.body_page_count() > 1);
        assert_eq!(state.hit(220.0, 104.0), Some(Hit::BodyPage(1)));
        state.change_body_page(1);
        assert_eq!(state.body_page, 1);
        state.change_body_page(500);
        assert_eq!(state.body_page, state.body_page_count() - 1);
        state.close_detail();
        assert_eq!(state.body_page, 0);
        state.close();
        assert_eq!(state.body_page_count(), 1);
    }

    #[test]
    fn private_font_reflows_full_and_compact_detail_without_losing_pages() {
        let message = "A long private message with many Unicode Wörter and more lines than fit on a single page. ".repeat(5);
        let mut state = State::default();
        state.show_preview(Snapshot { active: vec![Notice {
            id: 17, body: message.clone(), summary: "Private".into(),
            ..Notice::default()
        }], history: vec![] });
        assert_eq!(state.refresh_timeout(Instant::now()), None);
        assert!(state.open_detail(0));
        let default_pages = state.body_page_count();
        assert_eq!(state.body_text_width(), BODY_WIDTH);
        state.configure_glyph_scale(2);
        assert_eq!(state.body_text_width(), BODY_WIDTH / 2);
        assert_eq!(state.compact_text_width(168), compact_body_width(168) / 2);
        assert!(state.body_page_count() > default_pages);
        assert!(state.body_text_lines(&message).iter().all(|line|
            line.chars().count() <= state.body_text_width()));
        assert_eq!(state.hit(220.0, 104.0), Some(Hit::BodyPage(1)));
        state.change_body_page(100);
        assert_eq!(state.body_page + 1, state.body_page_count());
        state.change_compact_body_page(100, (168, 144));
        assert_eq!(state.body_page + 1, state.compact_body_page_count((168, 144)));
        state.configure_glyph_scale(1);
        assert!(state.body_page < state.body_page_count());
        state.close();
        assert!(state.notices.is_empty());
    }

    #[test]
    fn live_refresh_cannot_silently_retarget_action_or_reused_id() {
        let now = Instant::now();
        let make = |summary: &str, actions: Vec<Action>| Snapshot {
            active: vec![Notice { id: 12, summary: summary.into(), app_name: "Mail".into(),
                                   actions, ..Notice::default() }], history: vec![],
        };
        let action = |key: &str| Action { key: key.into(), label: key.into() };
        let mut state = State::default();
        let initial = state.begin();
        assert!(state.update(initial, Ok(make("Inbox", vec![action("open"), action("delete")]))));
        assert!(state.open_detail(0));
        state.select_action(1);
        let revision = state.begin_background(now + Duration::from_secs(4)).unwrap();
        assert!(state.update(revision, Ok(make("Inbox", vec![action("delete"), action("open")]))));
        assert_eq!(state.selected_action().unwrap().1.key, "delete");
        let revision = state.begin_background(now + Duration::from_secs(8)).unwrap();
        assert!(state.update(revision, Ok(make("Inbox", vec![action("open")]))));
        assert_eq!(state.selected_action(), None); // Must select again.
        let revision = state.begin_background(now + Duration::from_secs(12)).unwrap();
        assert!(state.update(revision, Ok(make("Different message", vec![action("open")]))));
        assert!(state.detail_notice().is_none()); // Numeric ID reused.
        let revision = state.begin_background(now + Duration::from_secs(16)).unwrap();
        assert!(state.update(revision, Ok(Snapshot { active: vec![], history: vec![] })));
        assert_eq!(state.selected_id(), None); // No accidental new selection.
    }
}
