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

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Hit { Row(usize), Action(usize), Tab(bool), Back, Refresh, Dismiss }

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
    pub revision: u64,
}

impl State {
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
    }

    pub fn begin(&mut self) -> u64 {
        self.open = true;
        self.loading = true;
        self.error = None;
        self.revision = self.revision.wrapping_add(1);
        self.revision
    }

    pub fn update(&mut self, revision: u64, result: Result<Snapshot, &'static str>) -> bool {
        if !self.open || revision != self.revision { return false; }
        self.loading = false;
        match result {
            Ok(snapshot) => {
                let previous_id = self.detail_id.or_else(||
                    self.visible_notices().get(self.selected).map(|notice| notice.id));
                self.notices = snapshot.active;
                self.history = snapshot.history;
                self.selected = previous_id.and_then(|id| self.visible_notices()
                    .iter().position(|notice| notice.id == id))
                    .unwrap_or_else(|| self.selected.min(self.visible_notices().len().saturating_sub(1)));
                if self.detail_id.is_some() && self.detail_notice().is_none() {
                    self.close_detail();
                }
                self.selected_action = self.selected_action.min(self.detail_notice()
                    .map_or(0, |notice| notice.actions.len().saturating_sub(1)));
                self.error = None;
            }
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
        true
    }

    pub fn close_detail(&mut self) {
        self.detail_id = None;
        self.selected_action = 0;
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

    pub fn first_action_row(&self) -> usize {
        (self.selected_action / VISIBLE_ROWS) * VISIBLE_ROWS
    }

    pub fn action_at(&self, index: usize) -> Option<(u32, &Action)> {
        if self.show_history || self.loading || self.error.is_some() { return None; }
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
        (!self.show_history && !self.loading && self.error.is_none())
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
}
