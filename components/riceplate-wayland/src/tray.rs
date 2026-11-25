//! Small, bounded view of live StatusNotifier items for a native RicePlate.
//! The D-Bus host is handled by `status-notifier`; no arbitrary recipe paths
//! or commands can reach the bus. Pixmaps are untrusted and size checked.

use status_notifier::{Item, MenuNode, Pixmap, ToggleState, ToggleType};
use std::collections::HashSet;

pub const WIDTH: u32 = 112;
pub const SLOT_WIDTH: u32 = 28;
pub const VISIBLE_ITEMS: usize = 4;
pub const MAX_ITEMS: usize = 32;
pub const POPUP_WIDTH: u32 = 288;
pub const POPUP_HEIGHT: u32 = 240;
pub const POPUP_ROWS: usize = 5;
pub const POPUP_ROW_TOP: u32 = 44;
pub const POPUP_ROW_HEIGHT: u32 = 30;

/// A secondary click must not dispatch a remote DBusMenu action. This is
/// checked on the real Wayland pointer path, not only when painting a menu.
pub fn menu_activation_button(button: u32) -> bool {
    button == 0x110 // Linux BTN_LEFT; shared protocol value for all rices.
}

/** A registered item may disappear and another process may register using
 * the same *well-known* D-Bus name. A previously opened menu belongs to the
 * former connection, even when its replacement publishes identical node IDs.
 *
 * The StatusNotifier host reports Added/Removed for lifecycle transitions.
 * A change to labels, icons or checkmarks is not a lifecycle transition and
 * continues to use MenuPopup::sync to preserve valid keyboard selection.
 */
pub fn revokes_remote_menu(
    open_bus_name: Option<&str>,
    event_bus_name: &str,
    event: status_notifier::Event,
) -> bool {
    open_bus_name.is_some_and(|bus_name| !bus_name.is_empty() && bus_name == event_bus_name)
        && matches!(
            event,
            status_notifier::Event::Added | status_notifier::Event::Removed
        )
}

pub fn screen_coords(
    output_origin: (i32, i32),
    output_size: (u32, u32),
    panel_height: u32,
    top_panel: bool,
    popup: bool,
    local: (f64, f64),
) -> (i32, i32) {
    let left = if popup {
        output_size.0.saturating_sub(POPUP_WIDTH + 8)
    } else {
        0
    };
    let top = if popup {
        if top_panel {
            panel_height + 8
        } else {
            output_size
                .1
                .saturating_sub(panel_height + 8 + POPUP_HEIGHT)
        }
    } else if top_panel {
        0
    } else {
        output_size.1.saturating_sub(panel_height)
    };
    (
        output_origin
            .0
            .saturating_add(left as i32)
            .saturating_add(local.0 as i32),
        output_origin
            .1
            .saturating_add(top as i32)
            .saturating_add(local.1 as i32),
    )
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PopupHit {
    Item(usize),
    Previous,
    Next,
    Close,
}

#[derive(Debug, Default)]
pub struct Popup {
    pub visible: bool,
    pub first: usize,
    pub selected: usize,
}

impl Popup {
    pub fn open(&mut self, entries: usize) {
        self.visible = true;
        self.first = (VISIBLE_ITEMS - 1).min(entries.saturating_sub(1));
        self.selected = self.first;
    }

    pub fn close(&mut self) {
        self.visible = false;
        self.first = 0;
        self.selected = 0;
    }

    pub fn select(&mut self, delta: isize, count: usize) {
        if count == 0 {
            return;
        }
        self.selected = self.selected.saturating_add_signed(delta).min(count - 1);
        if self.selected < self.first {
            self.first = self.selected;
        }
        if self.selected >= self.first + POPUP_ROWS {
            self.first = self.selected + 1 - POPUP_ROWS;
        }
    }

    pub fn page(&mut self, delta: isize, count: usize) {
        if count == 0 {
            return;
        }
        if (delta > 0 && self.first + POPUP_ROWS >= count) || (delta < 0 && self.first == 0) {
            return;
        }
        let last = count - 1;
        self.first = self
            .first
            .saturating_add_signed(delta.saturating_mul(POPUP_ROWS as isize))
            .min(last);
        self.selected = self.first;
    }

    pub fn hit(&self, x: f64, y: f64, count: usize) -> Option<PopupHit> {
        if !x.is_finite()
            || !y.is_finite()
            || x < 0.0
            || y < 0.0
            || x >= f64::from(POPUP_WIDTH)
            || y >= f64::from(POPUP_HEIGHT)
        {
            return None;
        }
        if y < 36.0 && x >= f64::from(POPUP_WIDTH - 44) {
            return Some(PopupHit::Close);
        }
        if y >= f64::from(POPUP_ROW_TOP)
            && y < f64::from(POPUP_ROW_TOP + POPUP_ROWS as u32 * POPUP_ROW_HEIGHT)
        {
            let index = self.first + ((y as u32 - POPUP_ROW_TOP) / POPUP_ROW_HEIGHT) as usize;
            return (index < count).then_some(PopupHit::Item(index));
        }
        if y >= 202.0 {
            return Some(if x < f64::from(POPUP_WIDTH / 2) {
                PopupHit::Previous
            } else {
                PopupHit::Next
            });
        }
        None
    }
}

// The SNI menu tree belongs to an untrusted D-Bus peer. Snapshot only bounded,
// visible content; never retain arbitrary PNG blobs or source-provided paths.
const MAX_MENU_NODES: usize = 128;
const MAX_MENU_DEPTH: usize = 6;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MenuKind {
    Action { checked: bool, radio: bool },
    Submenu(Vec<MenuRow>),
    Separator,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MenuRow {
    pub id: i32,
    pub label: String,
    pub enabled: bool,
    pub kind: MenuKind,
}

impl MenuRow {
    pub fn selectable(&self) -> bool {
        self.enabled && !matches!(&self.kind, MenuKind::Separator)
    }
}

fn snapshot_rows(nodes: &[MenuNode], budget: &mut usize, depth: usize) -> Vec<MenuRow> {
    if depth >= MAX_MENU_DEPTH {
        return Vec::new();
    }
    let mut result = Vec::new();
    for node in nodes {
        if *budget == 0 {
            break;
        }
        let row = match node {
            MenuNode::Item {
                id,
                label,
                enabled,
                visible,
                toggle_type,
                toggle_state,
                ..
            } if *visible => Some(MenuRow {
                id: *id,
                label: label.chars().filter(|c| !c.is_control()).take(42).collect(),
                enabled: *enabled,
                kind: MenuKind::Action {
                    checked: *toggle_state == ToggleState::On,
                    radio: *toggle_type == ToggleType::Radio,
                },
            }),
            MenuNode::Menu {
                id,
                label,
                enabled,
                visible,
                children,
            } if *visible => {
                *budget -= 1;
                let children = snapshot_rows(children, budget, depth + 1);
                result.push(MenuRow {
                    id: *id,
                    label: label.chars().filter(|c| !c.is_control()).take(42).collect(),
                    enabled: *enabled && !children.is_empty(),
                    kind: MenuKind::Submenu(children),
                });
                continue;
            }
            MenuNode::Separator { id, visible } if *visible => Some(MenuRow {
                id: *id,
                label: String::new(),
                enabled: false,
                kind: MenuKind::Separator,
            }),
            _ => None,
        };
        if let Some(row) = row {
            *budget -= 1;
            result.push(row);
        }
    }
    result
}

/// DBusMenu item IDs identify the remote action, including submenu parents.
/// A malformed peer reusing an ID cannot be allowed to change the meaning of
/// a focused row or of a later menu_clicked call. The existing snapshot cap
/// bounds this validation to at most MAX_MENU_NODES entries.
fn unique_menu_ids(rows: &[MenuRow], seen: &mut HashSet<i32>) -> bool {
    for row in rows {
        // DBusMenu separators have no executable action and some hosts reuse
        // their sentinel/root ID for them. Never reject an otherwise valid
        // provider merely because its decorative separators share that ID.
        if !matches!(&row.kind, MenuKind::Separator) && !seen.insert(row.id) {
            return false;
        }
        if let MenuKind::Submenu(children) = &row.kind {
            if !unique_menu_ids(children, seen) {
                return false;
            }
        }
    }
    true
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MenuHit {
    Row(usize),
    Back,
    Close,
    Previous,
    Next,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MenuChoice {
    None,
    Open(i32),
    Click(i32),
}

#[derive(Debug, Default)]
pub struct MenuPopup {
    pub visible: bool,
    pub bus_name: String,
    pub title: String,
    pub root_id: i32,
    rows: Vec<MenuRow>,
    path: Vec<i32>,
    pub first: usize,
    pub selected: usize,
}

impl MenuPopup {
    fn snapshot(root: &MenuNode) -> Option<(i32, Vec<MenuRow>)> {
        let MenuNode::Menu {
            id,
            enabled: true,
            visible: true,
            children,
            ..
        } = root
        else {
            return None;
        };
        let mut budget = MAX_MENU_NODES;
        let rows = snapshot_rows(children, &mut budget, 0);
        let mut seen = HashSet::with_capacity(MAX_MENU_NODES + 1);
        seen.insert(*id);
        (!rows.is_empty() && unique_menu_ids(&rows, &mut seen)).then_some((*id, rows))
    }

    pub fn open(&mut self, bus_name: &str, title: &str, root: &MenuNode) -> bool {
        // A failed switch must revoke the previous provider's executable
        // rows. Otherwise an empty/malformed replacement leaves a stale
        // menu visible with actions from the former D-Bus owner.
        let snapshot = Self::snapshot(root);
        self.close();
        let Some((root_id, rows)) = snapshot else {
            return false;
        };
        self.visible = true;
        self.bus_name = bus_name.to_owned();
        self.title = title.chars().take(42).collect();
        self.root_id = root_id;
        self.rows = rows;
        self.ensure_selection(1);
        true
    }

    /// A local panel menu shares the SNI input/paging surface without sending
    /// synthetic D-Bus events to application-owned StatusNotifier items.
    pub fn open_local(&mut self, title: &str, rows: Vec<MenuRow>) -> bool {
        // Empty local status menus must not preserve a previously visible
        // provider-owned menu or its stale keyboard selection.
        self.close();
        if rows.is_empty() {
            return false;
        }
        self.visible = true;
        self.title = title.chars().filter(|c| !c.is_control()).take(42).collect();
        self.rows = rows.into_iter().take(MAX_MENU_NODES).collect();
        self.ensure_selection(1);
        true
    }

    pub fn is_local(&self) -> bool {
        self.visible && self.bus_name.is_empty()
    }

    /// The actual Wayland pointer hover may update either a native Luna
    /// status menu or a provider-owned DBusMenu. Local rows MUST NOT emit
    /// SNI D-Bus events to an empty (or stale) bus name.
    pub fn remote_hover_id(&self, index: usize) -> Option<i32> {
        if self.is_local() {
            return None;
        }
        self.visible_row(index)
            .filter(|row| row.selectable())
            .map(|row| row.id)
    }

    pub fn close(&mut self) {
        *self = Self::default();
    }

    pub fn opened_ids(&self) -> Vec<i32> {
        if !self.visible || self.is_local() {
            return Vec::new();
        }
        std::iter::once(self.root_id)
            .chain(self.path.iter().copied())
            .collect()
    }

    pub fn parent_id(&self) -> i32 {
        self.path.last().copied().unwrap_or(self.root_id)
    }

    pub fn rows(&self) -> &[MenuRow] {
        let mut rows = self.rows.as_slice();
        for &id in &self.path {
            // A provider may disable an already-open parent without removing
            // its children. Never keep dispatching actions through that parent.
            let Some(MenuRow {
                enabled: true,
                kind: MenuKind::Submenu(children),
                ..
            }) = rows.iter().find(|row| row.id == id)
            else {
                return &[];
            };
            rows = children;
        }
        rows
    }

    /// Only an action on the *currently rendered page* is eligible for
    /// activation. An AT-SPI target or delayed pointer event may refer to a
    /// row from an earlier page after the user navigates or a provider syncs.
    fn visible_row(&self, index: usize) -> Option<&MenuRow> {
        if !self.visible || index < self.first || index >= self.first.saturating_add(POPUP_ROWS) {
            return None;
        }
        self.rows().get(index)
    }

    fn ensure_selection(&mut self, delta: isize) {
        let rows = self.rows();
        if rows.is_empty() {
            self.first = 0;
            self.selected = 0;
            return;
        }
        let index = self.selected.min(rows.len() - 1);
        let target = if rows[index].selectable() {
            Some(index)
        } else {
            let forward = (index..rows.len()).find(|&i| rows[i].selectable());
            let backward = (0..index).rev().find(|&i| rows[i].selectable());
            if delta < 0 {
                backward.or(forward)
            } else {
                forward.or(backward)
            }
        };
        self.selected = target.unwrap_or(index);
        if self.selected < self.first {
            self.first = self.selected;
        }
        if self.selected >= self.first + POPUP_ROWS {
            self.first = self.selected + 1 - POPUP_ROWS;
        }
    }

    pub fn select(&mut self, delta: isize) {
        let rows = self.rows();
        if rows.is_empty() {
            return;
        }
        // After an asynchronous provider update removes/renames a focused
        // action, there is deliberately NO implicit replacement activation.
        // An actual next/previous key press selects a fresh live identity.
        if self.selected == usize::MAX {
            self.selected = if delta < 0 {
                rows.iter().rposition(MenuRow::selectable)
            } else {
                rows.iter().position(MenuRow::selectable)
            }
            .unwrap_or(usize::MAX);
            if self.selected != usize::MAX {
                self.ensure_selection(delta);
            }
            return;
        }
        let len = rows.len();
        let mut cursor = self.selected.min(len - 1);
        for _ in 0..len {
            cursor = cursor.saturating_add_signed(delta.signum()).min(len - 1);
            if rows[cursor].selectable() {
                break;
            }
        }
        self.selected = cursor;
        self.ensure_selection(delta);
    }

    pub fn page(&mut self, delta: isize) {
        let count = self.rows().len();
        if count == 0
            || (delta < 0 && self.first == 0)
            || (delta > 0 && self.first + POPUP_ROWS >= count)
        {
            return;
        }
        self.first = self
            .first
            .saturating_add_signed(delta.signum() * POPUP_ROWS as isize)
            .min(count.saturating_sub(1));
        self.selected = self.first;
        self.ensure_selection(delta);
    }

    pub fn choice(&mut self, index: usize) -> MenuChoice {
        let Some(row) = self.visible_row(index) else {
            return MenuChoice::None;
        };
        if !row.selectable() {
            return MenuChoice::None;
        }
        let (id, submenu) = (row.id, matches!(&row.kind, MenuKind::Submenu(_)));
        if submenu {
            if self.path.len() >= MAX_MENU_DEPTH {
                return MenuChoice::None;
            }
            self.path.push(id);
            self.first = 0;
            self.selected = 0;
            self.ensure_selection(1);
            MenuChoice::Open(id)
        } else {
            MenuChoice::Click(id)
        }
    }

    pub fn back(&mut self) -> Option<i32> {
        let id = self.path.pop()?;
        self.first = 0;
        self.selected = 0;
        self.ensure_selection(1);
        Some(id)
    }

    /// Update live checkmarks/labels while open without retaining stale node IDs.
    /// If the provider removes a parent menu, callers close its former path.
    pub fn sync(&mut self, root: &MenuNode) -> Vec<i32> {
        let Some((id, rows)) = Self::snapshot(root) else {
            return self.opened_ids();
        };
        if id != self.root_id {
            return self.opened_ids();
        }
        if self.rows == rows {
            return Vec::new();
        }
        // A keyboard highlight is an action *identity*, not a volatile row
        // index. Labels and menu type participate in that identity: a peer
        // cannot silently repurpose an ID while the user is about to press Enter.
        // Changes to a checked/radio state alone may preserve the selection.
        let focused = self
            .rows()
            .get(self.selected)
            .filter(|row| row.selectable())
            .map(|row| (row.id, row.label.clone(), std::mem::discriminant(&row.kind)));
        // A provider may reuse a submenu ID for a different live menu while
        // the user has it open. Track the entire parent path's identity, not
        // merely its IDs: otherwise Enter could dispatch an old child under a
        // silently repurposed parent after an asynchronous D-Bus update.
        let old_path_labels = {
            let mut parents = self.rows.as_slice();
            let mut labels = Vec::with_capacity(self.path.len());
            for &id in &self.path {
                let Some(row) = parents.iter().find(|row| row.id == id) else {
                    break;
                };
                let MenuKind::Submenu(children) = &row.kind else {
                    break;
                };
                labels.push(row.label.clone());
                parents = children;
            }
            labels
        };
        self.rows = rows;
        let mut parents = self.rows.as_slice();
        let mut retained = 0;
        for (&id, label) in self.path.iter().zip(&old_path_labels) {
            let Some(row) = parents
                .iter()
                .find(|row| row.id == id && row.enabled && row.label.as_str() == label.as_str())
            else {
                break;
            };
            let MenuKind::Submenu(children) = &row.kind else {
                break;
            };
            retained += 1;
            parents = children;
        }
        // Close descendants before ancestors, matching menu_closed ordering.
        // Do not silently transfer focus to a replacement row.
        let removed: Vec<i32> = self.path.drain(retained..).rev().collect();
        if self.path.is_empty() && self.rows.is_empty() {
            return vec![self.root_id];
        }
        // Even an identical child ID/label cannot inherit a keyboard
        // selection if it moved out of a revoked submenu context.
        let restored = if removed.is_empty() {
            focused.and_then(|(id, label, kind)| {
                self.rows().iter().position(|row| {
                    row.selectable()
                        && row.id == id
                        && row.label == label
                        && std::mem::discriminant(&row.kind) == kind
                })
            })
        } else {
            None
        };
        self.first = self.first.min(self.rows().len().saturating_sub(1));
        if let Some(index) = restored {
            self.selected = index;
            if index < self.first {
                self.first = index;
            }
            if index >= self.first + POPUP_ROWS {
                self.first = index + 1 - POPUP_ROWS;
            }
        } else {
            // None is represented by an out-of-range index so Enter/Space
            // cannot target the item that happened to replace the old row.
            self.selected = usize::MAX;
        }
        removed
    }

    pub fn hit(&self, x: f64, y: f64) -> Option<MenuHit> {
        if !x.is_finite()
            || !y.is_finite()
            || x < 0.0
            || y < 0.0
            || x >= f64::from(POPUP_WIDTH)
            || y >= f64::from(POPUP_HEIGHT)
        {
            return None;
        }
        if y < 36.0 {
            return (x >= f64::from(POPUP_WIDTH - 44))
                .then_some(MenuHit::Close)
                .or_else(|| (x < 40.0 && !self.path.is_empty()).then_some(MenuHit::Back));
        }
        if y >= f64::from(POPUP_ROW_TOP)
            && y < f64::from(POPUP_ROW_TOP + POPUP_ROWS as u32 * POPUP_ROW_HEIGHT)
        {
            let index = self.first + ((y as u32 - POPUP_ROW_TOP) / POPUP_ROW_HEIGHT) as usize;
            return (index < self.rows().len()).then_some(MenuHit::Row(index));
        }
        (y >= 202.0).then_some(if x < f64::from(POPUP_WIDTH / 2) {
            MenuHit::Previous
        } else {
            MenuHit::Next
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Icon {
    pub width: u32,
    pub height: u32,
    pub argb: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Entry {
    pub bus_name: String,
    pub title: String,
    pub icon: Option<Icon>,
    pub is_menu: bool,
    pub needs_attention: bool,
}

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct State {
    pub entries: Vec<Entry>,
}

impl State {
    pub fn from_items<'a>(items: impl Iterator<Item = (&'a String, &'a Item)>) -> Self {
        // Select the highest-priority items before applying the memory cap.
        // Truncating the incoming D-Bus iteration first would silently hide
        // a NeedsAttention item that arrived after the first 32 entries.
        // Keep the candidate set bounded even for a hostile item inventory.
        let mut entries: Vec<Entry> = Vec::with_capacity(MAX_ITEMS);
        for (name, item) in items {
            if !matches!(item.status.as_str(), "Active" | "NeedsAttention")
                || name.len() > 255
                || item.title.len() > 512
            {
                continue;
            }
            let needs_attention = item.status == "NeedsAttention";
            let position = entries.partition_point(|current| {
                (current.needs_attention && !needs_attention)
                    || (current.needs_attention == needs_attention
                        && current.bus_name.as_str() < name.as_str())
            });
            if position >= MAX_ITEMS {
                continue;
            }
            let pixmaps = if needs_attention && !item.attention_icon_pixmap.is_empty() {
                &item.attention_icon_pixmap
            } else {
                &item.icon_pixmap
            };
            entries.insert(
                position,
                Entry {
                    bus_name: name.clone(),
                    title: item.title.chars().take(48).collect(),
                    icon: choose_pixmap(pixmaps),
                    is_menu: item.item_is_menu,
                    needs_attention,
                },
            );
            entries.truncate(MAX_ITEMS);
        }
        Self { entries }
    }

    pub fn visible_count(&self) -> usize {
        if self.entries.len() > VISIBLE_ITEMS {
            VISIBLE_ITEMS - 1
        } else {
            self.entries.len()
        }
    }

    pub fn overflow_count(&self) -> usize {
        self.entries.len().saturating_sub(self.visible_count())
    }

    pub fn item_at(&self, slot: usize) -> Option<&Entry> {
        if slot >= self.visible_count() {
            return None;
        }
        self.entries.get(slot)
    }
}

fn choose_pixmap(pixmaps: &[Pixmap]) -> Option<Icon> {
    pixmaps
        .iter()
        .filter_map(|pixmap| {
            let [w, h] = pixmap.dimensions;
            if !(1..=64).contains(&w)
                || !(1..=64).contains(&h)
                || pixmap.image_data.len() != (w * h * 4) as usize
            {
                return None;
            }
            Some(Icon {
                width: w as u32,
                height: h as u32,
                argb: pixmap.image_data.clone(),
            })
        })
        .min_by_key(|icon| {
            (
                icon.width.abs_diff(20) + icon.height.abs_diff(20),
                icon.width * icon.height,
            )
        })
}

/// Copy a bounded ARGB32 (network-order) icon into an opaque 20x20 tile.
/// Sampling is nearest-neighbour. Alpha is explicitly blended into the theme.
pub fn paint_icon(
    canvas: &mut [u8],
    canvas_width: u32,
    canvas_height: u32,
    x: u32,
    y: u32,
    icon: &Icon,
) {
    for dy in 0..20 {
        for dx in 0..20 {
            let tx = x + dx;
            let ty = y + dy;
            if tx >= canvas_width || ty >= canvas_height {
                continue;
            }
            let sx = dx * icon.width / 20;
            let sy = dy * icon.height / 20;
            let src = ((sy * icon.width + sx) * 4) as usize;
            let dst = ((ty * canvas_width + tx) * 4) as usize;
            let a = u32::from(icon.argb[src]);
            // Wayland's Argb8888 shared memory is BGRA in little-endian memory.
            for (channel, rgb_index) in [(0, 3), (1, 2), (2, 1)] {
                let foreground = u32::from(icon.argb[src + rgb_index]);
                let background = u32::from(canvas[dst + channel]);
                canvas[dst + channel] =
                    ((foreground * a + background * (255 - a) + 127) / 255) as u8;
            }
            canvas[dst + 3] = 255;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn item(status: &str, title: &str) -> Item {
        Item {
            status: status.into(),
            title: title.into(),
            ..Item::default()
        }
    }

    #[test]
    fn owner_lifecycle_revokes_remote_actions_but_not_live_property_updates() {
        use status_notifier::Event;
        let owner = Some("org.test.SNIFixture");
        for event in [Event::Removed, Event::Added] {
            assert!(revokes_remote_menu(owner, "org.test.SNIFixture", event));
            assert!(!revokes_remote_menu(owner, "org.test.Unrelated", event));
            assert!(!revokes_remote_menu(None, "org.test.SNIFixture", event));
            assert!(!revokes_remote_menu(Some(""), "org.test.SNIFixture", event));
        }
        assert!(!revokes_remote_menu(
            owner,
            "org.test.SNIFixture",
            Event::UpdatedMenu
        ));
        assert!(!revokes_remote_menu(
            owner,
            "org.test.SNIFixture",
            Event::UpdatedStatus
        ));
        assert!(!revokes_remote_menu(
            owner,
            "org.test.SNIFixture",
            Event::UpdatedTitle
        ));
    }

    #[test]
    fn reused_menu_ids_after_owner_replacement_require_new_open_and_focus() {
        use status_notifier::Event;
        let old = MenuNode::Menu {
            id: 0,
            label: "root".into(),
            enabled: true,
            visible: true,
            children: vec![MenuNode::Item {
                id: 42,
                label: "Old provider action".into(),
                enabled: true,
                visible: true,
                icon_name: String::new(),
                icon_data: status_notifier::IconData(Vec::new()),
                toggle_type: ToggleType::None,
                toggle_state: ToggleState::Off,
            }],
        };
        let mut popup = MenuPopup::default();
        assert!(popup.open("org.test.SNIFixture", "Old", &old));
        assert_eq!(popup.choice(0), MenuChoice::Click(42));
        assert!(revokes_remote_menu(
            Some(&popup.bus_name),
            "org.test.SNIFixture",
            Event::Removed
        ));
        // The production bus-event consumer revokes state BEFORE hiding the
        // surface. Closing must not send menu_closed to a new service owner.
        popup.close();
        assert!(!popup.visible);
        assert_eq!(popup.choice(0), MenuChoice::None);
        assert_eq!(popup.remote_hover_id(0), None);
        assert!(popup.open("org.test.SNIFixture", "New", &old));
        assert_eq!(popup.choice(0), MenuChoice::Click(42));
    }

    #[test]
    fn picks_valid_small_pixmap_and_blends_network_argb() {
        let valid = Pixmap {
            dimensions: [1, 1],
            image_data: vec![128, 200, 60, 20],
        };
        assert!(choose_pixmap(&[
            Pixmap {
                dimensions: [10000, 10000],
                image_data: vec![0]
            },
            Pixmap {
                dimensions: [2, 2],
                image_data: vec![0; 3]
            }
        ])
        .is_none());
        let icon = choose_pixmap(&[valid]).unwrap();
        let mut canvas = vec![255_u8; 20 * 20 * 4];
        paint_icon(&mut canvas, 20, 20, 0, 0, &icon);
        assert_eq!(canvas[3], 255);
        // BGR order: blue is the last RGB byte in protocol ARGB.
        assert!((137..=139).contains(&canvas[0]));
        assert!((156..=158).contains(&canvas[1]));
        assert!((227..=229).contains(&canvas[2]));
    }

    #[test]
    fn popup_coordinates_are_output_local_even_on_second_monitor() {
        assert_eq!(
            screen_coords((1920, 0), (1920, 1080), 36, false, false, (50.0, 18.0)),
            (1970, 1062)
        );
        assert_eq!(
            screen_coords((1920, 0), (1920, 1080), 36, false, true, (10.0, 20.0)),
            (3554, 816)
        );
        assert_eq!(
            screen_coords((-1280, 0), (1280, 800), 44, true, true, (10.0, 20.0)),
            (-286, 72)
        );
    }

    #[test]
    fn ignores_passive_prioritizes_attention_and_bounds_visible_slots() {
        let mut raw = Vec::new();
        for idx in 0..6 {
            raw.push((format!("org.test.Item{idx}"), item("Active", "App")));
        }
        raw[5].1.status = "NeedsAttention".into();
        raw[1].1.status = "Passive".into();
        let state = State::from_items(raw.iter().map(|(name, item)| (name, item)));
        assert_eq!(state.entries.len(), 5);
        assert_eq!(state.entries[0].bus_name, "org.test.Item5");
        assert_eq!(state.visible_count(), 3);
        assert_eq!(state.overflow_count(), 2);
        assert_eq!(state.item_at(0).unwrap().bus_name, "org.test.Item5");
        assert!(state.item_at(3).is_none());
    }

    #[test]
    fn late_attention_item_is_not_dropped_by_bounded_tray_inventory() {
        let mut items: Vec<(String, Item)> = (0..(MAX_ITEMS + 8))
            .map(|idx| (format!("org.test.Item{idx:03}"), item("Active", "App")))
            .collect();
        // The original take(MAX_ITEMS) discarded this item before sorting.
        items[MAX_ITEMS + 7].1.status = "NeedsAttention".into();
        let initial = State::from_items(items.iter().map(|(name, item)| (name, item)));
        assert_eq!(initial.entries.len(), MAX_ITEMS);
        assert_eq!(initial.entries[0].bus_name, "org.test.Item039");
        assert!(initial.entries[0].needs_attention);
        assert_eq!(initial.visible_count(), VISIBLE_ITEMS - 1);
        assert_eq!(initial.overflow_count(), MAX_ITEMS - VISIBLE_ITEMS + 1);
        // D-Bus HashMap enumeration order must not affect which alerts live
        // inside the cap or the index used for keyboard/pointer focus.
        items.reverse();
        let reversed = State::from_items(items.iter().map(|(name, item)| (name, item)));
        assert_eq!(initial, reversed);
        assert_eq!(initial.entries.last().unwrap().bus_name, "org.test.Item030");
        assert!(initial
            .entries
            .iter()
            .all(|entry| entry.bus_name != "org.test.Item031"));
    }

    #[test]
    fn overflow_popup_paginates_and_rejects_out_of_bounds_actions() {
        let mut popup = Popup::default();
        popup.open(17);
        assert!(popup.visible);
        assert_eq!(popup.first, 3);
        assert_eq!(popup.hit(18.0, 44.0, 17), Some(PopupHit::Item(3)));
        popup.page(1, 17);
        assert_eq!(popup.first, 8);
        assert_eq!(popup.hit(18.0, 44.0, 17), Some(PopupHit::Item(8)));
        popup.page(100, 17);
        assert_eq!(popup.first, 16);
        popup.select(-99, 17);
        assert_eq!(popup.selected, 0);
        assert_eq!(popup.first, 0);
        assert_eq!(popup.hit(18.0, 44.0, 0), None);
        assert_eq!(popup.hit(f64::NAN, 20.0, 17), None);
        assert_eq!(popup.hit(260.0, 8.0, 17), Some(PopupHit::Close));
        popup.close();
        assert!(!popup.visible);

        popup.open(4);
        popup.page(1, 4);
        assert_eq!(
            popup.first, 3,
            "no phantom next page past a short final page"
        );
    }

    fn leaf(id: i32, label: &str, enabled: bool, visible: bool) -> MenuNode {
        MenuNode::Item {
            id,
            label: label.into(),
            enabled,
            visible,
            icon_name: String::new(),
            icon_data: status_notifier::IconData(Vec::new()),
            toggle_type: ToggleType::None,
            toggle_state: ToggleState::Unknown,
        }
    }

    fn root(children: Vec<MenuNode>) -> MenuNode {
        MenuNode::Menu {
            id: 0,
            label: "root".into(),
            enabled: true,
            visible: true,
            children,
        }
    }

    #[test]
    fn local_luna_menu_has_no_remote_bus_or_events_and_rejects_disabled_rows() {
        let mut popup = MenuPopup::default();
        assert!(popup.open_local(
            "Volume Control",
            vec![
                MenuRow {
                    id: 0,
                    label: "Unavailable".into(),
                    enabled: false,
                    kind: MenuKind::Action {
                        checked: false,
                        radio: false
                    }
                },
                MenuRow {
                    id: 105,
                    label: "Volume up".into(),
                    enabled: true,
                    kind: MenuKind::Action {
                        checked: false,
                        radio: false
                    }
                },
            ]
        ));
        assert!(popup.is_local());
        assert!(popup.opened_ids().is_empty());
        assert_eq!(popup.selected, 1);
        assert_eq!(popup.choice(0), MenuChoice::None);
        assert_eq!(popup.choice(1), MenuChoice::Click(105));
        popup.close();
        assert!(!popup.is_local());
    }

    #[test]
    fn menu_filters_hidden_rows_and_nested_disabled_actions() {
        let source = root(vec![
            leaf(1, "Hidden", true, false),
            MenuNode::Separator {
                id: 2,
                visible: true,
            },
            leaf(3, "Unavailable", false, true),
            MenuNode::Menu {
                id: 4,
                label: "Preferences".into(),
                enabled: true,
                visible: true,
                children: vec![leaf(5, "Open preferences", true, true)],
            },
            leaf(6, "Quit", true, true),
        ]);
        let mut popup = MenuPopup::default();
        assert!(popup.open("org.test.app", "Test", &source));
        assert_eq!(popup.rows().len(), 4);
        assert_eq!(
            popup.selected, 2,
            "disabled rows and separators are skipped"
        );
        assert_eq!(popup.choice(0), MenuChoice::None);
        assert_eq!(popup.choice(1), MenuChoice::None);
        assert_eq!(popup.choice(2), MenuChoice::Open(4));
        assert_eq!(popup.parent_id(), 4);
        assert_eq!(popup.opened_ids(), vec![0, 4]);
        assert_eq!(popup.choice(0), MenuChoice::Click(5));
        assert_eq!(popup.back(), Some(4));
        assert_eq!(popup.parent_id(), 0);
        assert_eq!(popup.choice(3), MenuChoice::Click(6));
        assert_eq!(popup.hit(10.0, 18.0), None);
        assert_eq!(popup.hit(256.0, 18.0), Some(MenuHit::Close));
        assert_eq!(popup.hit(f64::NAN, 44.0), None);
    }

    #[test]
    fn menu_keeps_toggles_and_clears_removed_submenu_state() {
        let toggled = MenuNode::Item {
            id: 8,
            label: "Check".into(),
            enabled: true,
            visible: true,
            icon_name: String::new(),
            icon_data: status_notifier::IconData(Vec::new()),
            toggle_type: ToggleType::Checkmark,
            toggle_state: ToggleState::On,
        };
        let mut menu = MenuPopup::default();
        assert!(menu.open(
            "service",
            "Title",
            &root(vec![MenuNode::Menu {
                id: 4,
                label: "Settings".into(),
                enabled: true,
                visible: true,
                children: vec![toggled],
            }])
        ));
        assert_eq!(menu.choice(0), MenuChoice::Open(4));
        assert!(matches!(
            menu.rows()[0].kind,
            MenuKind::Action { checked: true, .. }
        ));
        assert_eq!(
            menu.sync(&root(vec![leaf(22, "Different", true, true)])),
            vec![4]
        );
        assert!(menu.path.is_empty());
        assert_eq!(menu.rows()[0].id, 22);
        menu.close();
        assert!(menu.opened_ids().is_empty());
        assert!(!menu.open("service", "no menu", &MenuNode::Empty));
    }

    #[test]
    fn menu_bounds_untrusted_depth_and_node_count() {
        // DBusMenu child IDs must not reuse the root ID (0).
        let oversized = root((1..=500).map(|n| leaf(n, "abc", true, true)).collect());
        let mut popup = MenuPopup::default();
        assert!(popup.open("app", "App", &oversized));
        assert_eq!(popup.rows().len(), MAX_MENU_NODES);
        popup.page(1);
        assert_eq!(popup.first, 5);
        assert_eq!(popup.hit(18.0, 44.0), Some(MenuHit::Row(5)));
        popup.select(1);
        assert_eq!(popup.selected, 6);
    }
    #[test]
    fn dbusmenu_live_reorder_preserves_keyboard_target_by_id_not_row_number() {
        let mut menu = MenuPopup::default();
        assert!(menu.open(
            "org.test.app",
            "Live",
            &root(vec![
                leaf(1, "First", true, true),
                leaf(2, "Original target", true, true),
                leaf(3, "Third", true, true),
            ])
        ));
        menu.select(1);
        assert_eq!(menu.selected, 1);
        assert!(menu
            .sync(&root(vec![
                leaf(9, "New arrival", true, true),
                leaf(1, "First", true, true),
                leaf(3, "Third", true, true),
                leaf(2, "Original target", true, true),
            ]))
            .is_empty());
        assert_eq!(menu.selected, 3);
        assert_eq!(menu.choice(menu.selected), MenuChoice::Click(2));
    }

    #[test]
    fn changed_removed_or_disabled_dbusmenu_target_requires_a_fresh_keypress() {
        let mut menu = MenuPopup::default();
        assert!(menu.open(
            "org.test.app",
            "Live",
            &root(vec![
                leaf(10, "Before", true, true),
                leaf(11, "Next", true, true),
            ])
        ));
        assert!(menu
            .sync(&root(vec![
                leaf(10, "Repurposed", true, true),
                leaf(11, "Next", true, true),
            ]))
            .is_empty());
        assert_eq!(menu.selected, usize::MAX);
        assert_eq!(menu.choice(menu.selected), MenuChoice::None);
        menu.select(1);
        assert_eq!(menu.selected, 0);
        assert_eq!(menu.choice(menu.selected), MenuChoice::Click(10));
        assert!(menu
            .sync(&root(vec![
                leaf(10, "Repurposed", false, true),
                leaf(11, "Next", true, true),
            ]))
            .is_empty());
        assert_eq!(menu.choice(menu.selected), MenuChoice::None);
        menu.select(1);
        assert_eq!(menu.choice(menu.selected), MenuChoice::Click(11));
        assert!(menu
            .sync(&root(vec![leaf(12, "Unrelated", true, true),]))
            .is_empty());
        assert_eq!(menu.choice(menu.selected), MenuChoice::None);
        menu.select(-1);
        assert_eq!(menu.choice(menu.selected), MenuChoice::Click(12));
    }

    #[test]
    fn live_submenu_update_preserves_valid_child_and_revokes_removed_child() {
        let mut menu = MenuPopup::default();
        assert!(menu.open(
            "service",
            "Live",
            &root(vec![MenuNode::Menu {
                id: 4,
                label: "Options".into(),
                enabled: true,
                visible: true,
                children: vec![leaf(5, "A", true, true), leaf(6, "B", true, true)]
            },])
        ));
        assert_eq!(menu.choice(0), MenuChoice::Open(4));
        menu.select(1);
        assert_eq!(menu.choice(menu.selected), MenuChoice::Click(6));
        assert!(menu
            .sync(&root(vec![MenuNode::Menu {
                id: 4,
                label: "Options".into(),
                enabled: true,
                visible: true,
                children: vec![
                    leaf(7, "C", true, true),
                    leaf(6, "B", true, true),
                    leaf(5, "A", true, true)
                ]
            },]))
            .is_empty());
        assert_eq!(menu.selected, 1);
        assert_eq!(menu.choice(menu.selected), MenuChoice::Click(6));
        assert_eq!(
            menu.sync(&root(vec![leaf(8, "No submenu", true, true)])),
            vec![4]
        );
        assert_eq!(menu.choice(menu.selected), MenuChoice::None);
    }

    #[test]
    fn duplicate_remote_action_ids_are_rejected_on_open_and_live_update() {
        let mut menu = MenuPopup::default();
        assert!(!menu.open(
            "service",
            "Invalid",
            &root(vec![leaf(1, "A", true, true), leaf(1, "B", true, true)])
        ));
        assert!(!menu.open(
            "service",
            "Invalid root reuse",
            &root(vec![leaf(0, "Root ID reused", true, true)])
        ));
        assert!(!menu.visible);
        assert!(!menu.open(
            "service",
            "Invalid",
            &root(vec![
                MenuNode::Menu {
                    id: 4,
                    label: "Options".into(),
                    enabled: true,
                    visible: true,
                    children: vec![leaf(9, "A", true, true)]
                },
                leaf(9, "Duplicate nested id", true, true),
            ])
        ));
        assert!(menu.open("service", "Valid", &root(vec![leaf(1, "A", true, true)])));
        assert_eq!(
            menu.sync(&root(vec![
                leaf(1, "A", true, true),
                leaf(1, "B", true, true),
            ])),
            vec![0],
            "consumer closes the stale remote menu immediately"
        );
    }

    #[test]
    fn duplicate_separator_ids_are_non_actions_but_duplicate_commands_still_fail() {
        let mut menu = MenuPopup::default();
        assert!(menu.open(
            "service",
            "Normal provider",
            &root(vec![
                MenuNode::Separator {
                    id: 0,
                    visible: true
                },
                leaf(14, "Open", true, true),
                MenuNode::Separator {
                    id: 0,
                    visible: true
                },
            ])
        ));
        assert_eq!(menu.selected, 1);
        assert_eq!(menu.choice(0), MenuChoice::None);
        assert_eq!(menu.choice(1), MenuChoice::Click(14));
        assert_eq!(menu.choice(2), MenuChoice::None);
        menu.close();
        assert!(!menu.open(
            "service",
            "Ambiguous commands",
            &root(vec![
                leaf(14, "Open", true, true),
                leaf(14, "Other", true, true),
            ])
        ));
    }

    #[test]
    fn refused_remote_reopen_revokes_previous_provider_actions() {
        let mut menu = MenuPopup::default();
        assert!(menu.open(
            "org.test.old",
            "Old owner",
            &root(vec![leaf(2, "Previous action", true, true),])
        ));
        assert_eq!(menu.choice(0), MenuChoice::Click(2));
        // A malformed replacement could be a just-restarted provider.
        // Its failure must not expose the old owner's actionable snapshot.
        assert!(!menu.open(
            "org.test.new",
            "New owner",
            &root(vec![
                leaf(3, "One", true, true),
                leaf(3, "Duplicate", true, true),
            ])
        ));
        assert!(!menu.visible);
        assert!(menu.opened_ids().is_empty());
        assert!(menu.bus_name.is_empty());
        assert_eq!(menu.choice(0), MenuChoice::None);
        assert_eq!(menu.remote_hover_id(0), None);

        assert!(menu.open(
            "org.test.recovered",
            "Recovered",
            &root(vec![leaf(4, "Current action", true, true),])
        ));
        assert_eq!(menu.choice(0), MenuChoice::Click(4));
        assert!(!menu.open("org.test.failed", "Empty", &MenuNode::Empty));
        assert_eq!(menu.choice(0), MenuChoice::None);
        assert!(!menu.visible);
    }

    #[test]
    fn empty_local_reopen_drops_old_keyboard_and_remote_identity() {
        let mut menu = MenuPopup::default();
        assert!(menu.open(
            "org.test.old",
            "Provider",
            &root(vec![leaf(5, "Old", true, true),])
        ));
        assert!(!menu.open_local("Date and Time", Vec::new()));
        assert_eq!(menu.choice(0), MenuChoice::None);
        assert_eq!(menu.remote_hover_id(0), None);
        assert!(!menu.visible);
        assert!(menu.bus_name.is_empty());
        assert!(menu.open_local(
            "Recovered local status",
            vec![MenuRow {
                id: 8,
                label: "Settings".into(),
                enabled: true,
                kind: MenuKind::Action {
                    checked: false,
                    radio: false
                },
            }]
        ));
        assert!(menu.is_local());
        assert_eq!(menu.choice(0), MenuChoice::Click(8));
    }

    #[test]
    fn local_luna_pointer_hover_cannot_emit_provider_owned_dbus_events() {
        let mut menu = MenuPopup::default();
        assert!(menu.open_local(
            "Date and Time",
            vec![MenuRow {
                id: 107,
                label: "Adjust date".into(),
                enabled: true,
                kind: MenuKind::Action {
                    checked: false,
                    radio: false
                }
            },]
        ));
        assert_eq!(menu.remote_hover_id(0), None);
        menu.close();
        assert_eq!(menu.remote_hover_id(0), None);
        assert!(menu.open(
            "org.test.tray",
            "Real SNI",
            &root(vec![
                leaf(5, "Active", true, true),
                leaf(6, "Disabled", false, true),
            ])
        ));
        assert_eq!(menu.remote_hover_id(0), Some(5));
        assert_eq!(menu.remote_hover_id(1), None);
        assert_eq!(menu.remote_hover_id(50), None);
    }

    #[test]
    fn remote_menu_rejects_stale_off_page_accessibility_and_hover_actions() {
        let mut popup = MenuPopup::default();
        assert!(popup.open(
            "org.test.provider",
            "Paged",
            &root(
                (1..=12)
                    .map(|id| leaf(id, &format!("Action {id}"), true, true))
                    .collect()
            )
        ));
        assert_eq!(popup.first, 0);
        // This valid ID is not rendered on the current page. A cached AT-SPI
        // action cannot turn it into an invisible provider click.
        assert_eq!(popup.choice(6), MenuChoice::None);
        assert_eq!(popup.remote_hover_id(6), None);
        assert_eq!(popup.remote_hover_id(0), Some(1));

        popup.page(1);
        assert_eq!(popup.first, POPUP_ROWS);
        assert_eq!(popup.choice(0), MenuChoice::None);
        assert_eq!(popup.remote_hover_id(0), None);
        assert_eq!(popup.choice(5), MenuChoice::Click(6));
        assert_eq!(popup.remote_hover_id(5), Some(6));
        assert_eq!(popup.choice(11), MenuChoice::None);

        popup.page(1);
        assert_eq!(popup.first, 10);
        assert_eq!(popup.choice(9), MenuChoice::None);
        assert_eq!(popup.choice(11), MenuChoice::Click(12));
        popup.page(-1);
        popup.page(-1);
        assert_eq!(popup.choice(0), MenuChoice::Click(1));
        popup.close();
        assert_eq!(popup.choice(0), MenuChoice::None);
        assert_eq!(popup.remote_hover_id(0), None);
    }

    #[test]
    fn local_menu_and_remote_submenus_share_visible_page_action_bounds() {
        let mut popup = MenuPopup::default();
        let rows = (0..10)
            .map(|id| MenuRow {
                id,
                label: format!("Local {id}"),
                enabled: true,
                kind: MenuKind::Action {
                    checked: false,
                    radio: false,
                },
            })
            .collect();
        assert!(popup.open_local("Local", rows));
        assert_eq!(popup.choice(8), MenuChoice::None);
        popup.page(1);
        assert_eq!(popup.choice(0), MenuChoice::None);
        assert_eq!(popup.choice(8), MenuChoice::Click(8));
        assert_eq!(popup.remote_hover_id(8), None);
        popup.close();

        let mut source = (1..=6)
            .map(|id| leaf(id, &format!("Leaf {id}"), true, true))
            .collect::<Vec<_>>();
        source.push(MenuNode::Menu {
            id: 20,
            label: "More".into(),
            enabled: true,
            visible: true,
            children: (30..=36).map(|id| leaf(id, "Nested", true, true)).collect(),
        });
        assert!(popup.open("org.test.provider", "Nested", &root(source)));
        assert_eq!(popup.choice(6), MenuChoice::None);
        popup.page(1);
        assert_eq!(popup.choice(6), MenuChoice::Open(20));
        assert_eq!(popup.first, 0);
        assert_eq!(popup.choice(6), MenuChoice::None);
        popup.page(1);
        assert_eq!(popup.choice(6), MenuChoice::Click(36));
        assert_eq!(popup.back(), Some(20));
        assert_eq!(popup.first, 0);
        assert_eq!(popup.choice(6), MenuChoice::None);
    }

    #[test]
    fn only_primary_wayland_button_may_activate_a_remote_menu_row() {
        assert!(menu_activation_button(0x110)); // BTN_LEFT
        assert!(!menu_activation_button(0x111)); // BTN_RIGHT
        assert!(!menu_activation_button(0x112)); // BTN_MIDDLE
    }

    #[test]
    fn relabelled_live_parent_revokes_open_child_even_with_reused_ids() {
        let parent = |label: &str| {
            root(vec![MenuNode::Menu {
                id: 4,
                label: label.into(),
                enabled: true,
                visible: true,
                children: vec![leaf(5, "Sensitive action", true, true)],
            }])
        };
        let mut menu = MenuPopup::default();
        assert!(menu.open("service", "Live", &parent("Previous account")));
        assert_eq!(menu.choice(0), MenuChoice::Open(4));
        assert_eq!(menu.choice(0), MenuChoice::Click(5));
        assert_eq!(menu.sync(&parent("Different account")), vec![4]);
        assert_eq!(menu.parent_id(), 0, "relabelled parent must be closed");
        assert_eq!(menu.selected, usize::MAX);
        assert_eq!(menu.choice(menu.selected), MenuChoice::None);
        // A new deliberate pointer click may reopen the new menu, not a stale
        // keyboard Enter targeting its previously selected child.
        assert_eq!(menu.choice(0), MenuChoice::Open(4));
    }

    #[test]
    fn promoting_identical_child_out_of_revoked_menu_cannot_inherit_enter() {
        let mut menu = MenuPopup::default();
        assert!(menu.open(
            "service",
            "Live",
            &root(vec![MenuNode::Menu {
                id: 4,
                label: "Old parent".into(),
                enabled: true,
                visible: true,
                children: vec![leaf(9, "Action", true, true)]
            },])
        ));
        assert_eq!(menu.choice(0), MenuChoice::Open(4));
        assert_eq!(menu.choice(0), MenuChoice::Click(9));
        assert_eq!(
            menu.sync(&root(vec![leaf(9, "Action", true, true),])),
            vec![4]
        );
        assert_eq!(menu.selected, usize::MAX);
        assert_eq!(menu.choice(menu.selected), MenuChoice::None);
        menu.select(1);
        assert_eq!(menu.choice(menu.selected), MenuChoice::Click(9));
    }

    #[test]
    fn nested_live_parent_replacement_revokes_only_affected_subtree() {
        let nested = |label: &str| {
            root(vec![MenuNode::Menu {
                id: 4,
                label: "Stable outer".into(),
                enabled: true,
                visible: true,
                children: vec![MenuNode::Menu {
                    id: 8,
                    label: label.into(),
                    enabled: true,
                    visible: true,
                    children: vec![leaf(9, "Reused child", true, true)],
                }],
            }])
        };
        let mut menu = MenuPopup::default();
        assert!(menu.open("service", "Live", &nested("Previous inner")));
        assert_eq!(menu.choice(0), MenuChoice::Open(4));
        assert_eq!(menu.choice(0), MenuChoice::Open(8));
        assert_eq!(menu.choice(0), MenuChoice::Click(9));
        assert_eq!(menu.sync(&nested("Different inner")), vec![8]);
        assert_eq!(menu.parent_id(), 4, "stable outer remains open");
        assert_eq!(menu.selected, usize::MAX);
        assert_eq!(menu.choice(menu.selected), MenuChoice::None);
        menu.select(1);
        assert_eq!(menu.choice(menu.selected), MenuChoice::Open(8));
    }

    #[test]
    fn disabling_open_parent_closes_submenu_and_blocks_stale_child_dispatch() {
        let mut menu = MenuPopup::default();
        assert!(menu.open(
            "service",
            "Live",
            &root(vec![
                MenuNode::Menu {
                    id: 4,
                    label: "Actions".into(),
                    enabled: true,
                    visible: true,
                    children: vec![leaf(5, "Sensitive action", true, true)]
                },
                leaf(7, "Unrelated", true, true),
            ])
        ));
        assert_eq!(menu.choice(0), MenuChoice::Open(4));
        assert_eq!(menu.choice(0), MenuChoice::Click(5));
        assert_eq!(
            menu.sync(&root(vec![
                MenuNode::Menu {
                    id: 4,
                    label: "Actions".into(),
                    enabled: false,
                    visible: true,
                    children: vec![leaf(5, "Sensitive action", true, true)]
                },
                leaf(7, "Unrelated", true, true),
            ])),
            vec![4]
        );
        assert!(menu.path.is_empty());
        assert_eq!(menu.choice(menu.selected), MenuChoice::None);
        assert_eq!(menu.choice(0), MenuChoice::None);
        menu.select(1);
        assert_eq!(menu.choice(menu.selected), MenuChoice::Click(7));
    }
}
