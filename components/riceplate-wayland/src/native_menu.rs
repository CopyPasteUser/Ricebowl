//! Bounded, input-independent navigation for a real native RicePlate menu.
//! Every row maps to a validated recipe action; labels never become commands.

use std::time::{Duration, Instant};

use crate::{installed_apps::{self, App}, recipe::{MenuContentKind, MenuPresentation, NativeMenu}};

pub const WIDTH: u32 = 320;
pub const HEIGHT: u32 = 304;

/// Keep the entire native menu reachable on a small or rotated logical output.
/// A fixed-ratio fit is used only when the original dimensions cannot fit;
/// the painter and pointer coordinate transform share this geometry.
pub fn fitted_size(output_width: u32, output_height: u32, panel_height: u32) -> (u32, u32) {
    let available_width = output_width.saturating_sub(8).max(1);
    let available_height = output_height.saturating_sub(panel_height.saturating_add(8)).max(1);
    let scale = (available_width as f64 / WIDTH as f64)
        .min(available_height as f64 / HEIGHT as f64)
        .min(1.0);
    ((WIDTH as f64 * scale).floor().max(1.0) as u32,
     (HEIGHT as f64 * scale).floor().max(1.0) as u32)
}

pub fn input_coords(position: (f64, f64), size: (u32, u32)) -> (f64, f64) {
    (position.0 * f64::from(WIDTH) / f64::from(size.0.max(1)),
     position.1 * f64::from(HEIGHT) / f64::from(size.1.max(1)))
}
pub const TAB_TOP: u32 = 46;
pub const TAB_HEIGHT: u32 = 40;
pub const SIDEBAR_WIDTH: u32 = 112;
pub const COLUMNS_SPLIT: u32 = 164;
const COLUMNS_LEFT: u32 = 8;
const COLUMNS_RIGHT: u32 = 172;
const COLUMNS_TOP: u32 = 92;
pub const SIDEBAR_ROW_HEIGHT: u32 = 44;
pub const ACTION_TOP: u32 = 108;
pub const ACTION_HEIGHT: u32 = 42;
pub const VISIBLE_ACTIONS: usize = 4;
pub const MAX_PINS: usize = 8;
// A small output gets a real, full-resolution list instead of a downscaled
// 320x304 bitmap. The smallest outputs still use the existing proportional
// fit: below this bound even a single readable row cannot be guaranteed.
pub const COMPACT_MIN_WIDTH: u32 = 168;
pub const COMPACT_MIN_HEIGHT: u32 = 144;
pub const COMPACT_TABS_TOP: u32 = 34;
pub const COMPACT_TABS_HEIGHT: u32 = 34;
pub const COMPACT_ACTION_TOP: u32 = 75;
pub const COMPACT_ACTION_HEIGHT: u32 = 34;
pub const COMPACT_FOOTER_HEIGHT: u32 = 25;

pub fn compact_layout(size: (u32, u32)) -> bool {
    size != (WIDTH, HEIGHT) && size.0 >= COMPACT_MIN_WIDTH
        && size.1 >= COMPACT_MIN_HEIGHT
}

pub fn compact_visible_actions(size: (u32, u32)) -> usize {
    ((size.1.saturating_sub(COMPACT_ACTION_TOP + COMPACT_FOOTER_HEIGHT)
        / COMPACT_ACTION_HEIGHT) as usize).clamp(1, VISIBLE_ACTIONS)
}
const APP_REFRESH_INTERVAL: Duration = Duration::from_secs(30);
const CONTENT_HEADER_HEIGHT: u32 = 14;
const CONTENT_LIST_HEIGHT: u32 = 30;
const CONTENT_GRID_HEIGHT: u32 = 46;

/// Pixel geometry shared by painting and pointer/keyboard navigation.
/// The index always refers to the flattened, currently available action list.
pub struct MenuTile<'a> {
    pub action: &'a str,
    pub index: usize,
    pub x: u32,
    pub y: u32,
    pub width: u32,
    pub height: u32,
    pub grid: bool,
}

pub struct MenuSection<'a> {
    pub title: &'a str,
    pub x: u32,
    pub kind: MenuContentKind,
    pub top: u32,
    pub items: Vec<MenuTile<'a>>,
}

pub fn action_label(action: &str) -> &'static str {
    match action {
        "applications" => "Applications",
        "terminal" => "Terminal",
        "settings" => "RiceSpice settings",
        "lock" => "Lock screen",
        "logout" => "Log out of RiceBowl",
        "wifi-toggle" => "Toggle Wi-Fi radio",
        "audio-mute" => "Toggle speaker mute",
        "audio-up" => "Volume +5%",
        "audio-down" => "Volume -5%",
        "notifications" => "Notifications",
        _ => "Unsupported",
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum View {
    #[default]
    Groups,
    Search,
    Saved,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Hit {
    Group(usize),
    Action(usize),
    Close,
}

#[derive(Debug, Default)]
pub struct MenuState {
    pub visible: bool,
    pub group: usize,
    pub selected: usize,
    pub notice: Option<&'static str>,
    pub view: View,
    pub search: String,
    pub pins: Vec<String>,
    pub apps: Vec<App>,
    last_app_refresh: Option<Instant>,
}

impl MenuState {
    pub fn with_pins(pins: Vec<String>) -> Self {
        Self { pins, ..Self::default() }
    }

    /// Refresh the bounded application index when the menu is opened, never on
    /// keypress or during rendering. Changes are picked up on the next opening.
    pub fn refresh_apps(&mut self) {
        if self.last_app_refresh.is_some_and(|last| last.elapsed() < APP_REFRESH_INTERVAL) {
            return;
        }
        self.apps = installed_apps::discover();
        self.last_app_refresh = Some(Instant::now());
    }

    pub fn label<'a>(&'a self, action: &'a str) -> &'a str {
        self.apps.iter().find(|app| app.action == action)
            .map_or_else(|| action_label(action), |app| app.name.as_str())
    }

    pub fn app_path(&self, action: &str) -> Option<&std::path::Path> {
        self.apps.iter().find(|app| app.action == action).map(|app| app.path.as_path())
    }

    pub fn open(&mut self) {
        self.visible = true;
        self.group = 0;
        self.selected = 0;
        self.notice = None;
        self.view = View::Groups;
        self.search.clear();
    }

    pub fn close(&mut self) {
        self.visible = false;
    }

    pub fn group_by(&mut self, menu: &NativeMenu, delta: isize) {
        let count = menu.groups.len();
        if count == 0 {
            return;
        }
        let target = (self.group as isize + delta).rem_euclid(count as isize) as usize;
        self.select_group(menu, target);
    }

    /// Select a visible section in columns mode, or switch ordinary menus.
    pub fn select_group(&mut self, menu: &NativeMenu, index: usize) {
        if index >= menu.groups.len() { return; }
        self.open_group(index);
        if menu.presentation == MenuPresentation::Columns && index > 0 {
            self.selected = self.composed_sections(menu)
                .and_then(|sections| sections.into_iter()
                    .find(|section| section.title == menu.groups[index].title)
                    .and_then(|section| section.items.first().map(|tile| tile.index)))
                .unwrap_or(0);
        }
    }

    /// Left/right traverse the two-column grid when a neighbouring tile
    /// exists on the same row; otherwise they retain group switching.
    pub fn horizontal_by(&mut self, menu: &NativeMenu, delta: isize) {
        if menu.presentation == MenuPresentation::Columns && self.view == View::Groups {
            if let Some(sections) = self.composed_sections(menu) {
                let tiles: Vec<_> = sections.iter().flat_map(|section| section.items.iter())
                    .collect();
                if let Some(current) = tiles.iter().find(|tile| tile.index == self.selected) {
                    let target_right = delta > 0;
                    if (current.x >= COLUMNS_SPLIT) != target_right {
                        if let Some(target) = tiles.iter()
                            .filter(|tile| (tile.x >= COLUMNS_SPLIT) == target_right)
                            .min_by_key(|tile| (tile.y.abs_diff(current.y), tile.index)) {
                            self.selected = target.index;
                        }
                    }
                }
            }
            return;
        }
        let neighbour = self.composed_sections(menu).and_then(|sections| {
            let tiles: Vec<_> = sections.iter().flat_map(|section| section.items.iter()).collect();
            let current = tiles.iter().find(|tile| tile.index == self.selected && tile.grid)?;
            let target_x = current.x as isize + delta * current.width as isize;
            tiles.iter().find(|tile| tile.grid && tile.y == current.y &&
                tile.x as isize == target_x).map(|tile| tile.index)
        });
        if let Some(index) = neighbour {
            self.selected = index;
            return;
        }
        self.group_by(menu, delta);
    }

    pub fn open_group(&mut self, index: usize) {
        self.group = index;
        self.selected = 0;
        self.view = View::Groups;
        self.search.clear();
    }

    pub fn actions<'a>(&'a self, menu: &'a NativeMenu) -> Vec<&'a str> {
        let all = || menu.groups.iter().flat_map(|group|
            group.actions.iter().map(String::as_str));
        match self.view {
            View::Groups => {
                if let Some(sections) = self.composed_sections(menu) {
                    sections.into_iter().flat_map(|section| section.items.into_iter()
                        .map(|tile| tile.action)).collect()
                } else {
                    menu.groups.get(self.group).into_iter()
                        .flat_map(|group| group.actions.iter().map(String::as_str)).collect()
                }
            }
            View::Search => {
                let query = self.search.trim().to_lowercase();
                let mut result: Vec<_> = all().filter(|action| action_label(action)
                    .to_lowercase().contains(&query)).collect();
                // Empty search retains the old action list and does not dump
                // every installed application into the four-row menu.
                if !query.is_empty() {
                    // Exact/prefix name matches should not disappear behind
                    // generic keyword hits from alphabetically earlier apps.
                    // The original catalogue order breaks ties predictably.
                    let mut apps: Vec<_> = self.apps.iter().enumerate()
                        .filter_map(|(index, app)| app.match_score(&query)
                            .map(|score| (score, index, app.action.as_str())))
                        .collect();
                    apps.sort_by_key(|(score, index, _)| (*score, *index));
                    result.extend(apps.into_iter().map(|(_, _, action)| action));
                }
                result
            }
            View::Saved => all().filter(|action|
                self.pins.iter().any(|pin| pin.as_str() == *action)).collect(),
        }
    }

    /// Two genuinely simultaneous columns. Both painter and pointer hit
    /// testing consume the same tiles, so no decorative dead menu entries.
    fn column_sections<'a>(&'a self, menu: &'a NativeMenu) -> Option<Vec<MenuSection<'a>>> {
        let programs = menu.groups.first()?;
        let sources = programs.content.as_ref()?;
        let mut result = Vec::with_capacity(sources.len() + menu.groups.len() - 1);
        let mut index = 0;
        let mut top = COLUMNS_TOP;
        let left_width = COLUMNS_SPLIT - COLUMNS_LEFT - 8;
        for source in sources {
            let actions: Vec<&str> = match source.kind {
                MenuContentKind::Actions => programs.actions.iter().map(String::as_str)
                    .take(source.limit).collect(),
                MenuContentKind::Favorites => self.pins.iter().filter(|pin|
                    menu.groups.iter().any(|group| group.actions.contains(pin)))
                    .map(String::as_str).take(source.limit).collect(),
                MenuContentKind::AppsList | MenuContentKind::AppsGrid => self.apps.iter()
                    .map(|app| app.action.as_str()).take(source.limit).collect(),
            };
            let grid = source.kind == MenuContentKind::AppsGrid;
            let row_height = if grid { CONTENT_GRID_HEIGHT } else { CONTENT_LIST_HEIGHT };
            let mut items = Vec::with_capacity(actions.len());
            for (position, action) in actions.into_iter().enumerate() {
                let col = if grid { position % 2 } else { 0 };
                let row = if grid { position / 2 } else { position };
                let tile_width = if grid { left_width / 2 } else { left_width };
                items.push(MenuTile {
                    action, index, x: COLUMNS_LEFT + col as u32 * tile_width,
                    y: top + CONTENT_HEADER_HEIGHT + row as u32 * row_height,
                    width: tile_width, height: row_height, grid,
                });
                index += 1;
            }
            result.push(MenuSection { title: &source.title, x: COLUMNS_LEFT,
                                      kind: source.kind, top, items });
            let rows = if grid { source.limit.div_ceil(2) } else { source.limit };
            top += CONTENT_HEADER_HEIGHT + rows as u32 * row_height;
        }

        top = COLUMNS_TOP;
        let right_width = WIDTH - COLUMNS_RIGHT - 8;
        for group in menu.groups.iter().skip(1) {
            let mut items = Vec::with_capacity(group.actions.len());
            for (row, action) in group.actions.iter().enumerate() {
                items.push(MenuTile {
                    action, index, x: COLUMNS_RIGHT,
                    y: top + CONTENT_HEADER_HEIGHT + row as u32 * CONTENT_LIST_HEIGHT,
                    width: right_width, height: CONTENT_LIST_HEIGHT, grid: false,
                });
                index += 1;
            }
            result.push(MenuSection { title: &group.title, x: COLUMNS_RIGHT,
                kind: MenuContentKind::Actions, top, items });
            top += CONTENT_HEADER_HEIGHT + group.actions.len() as u32 * CONTENT_LIST_HEIGHT;
        }
        Some(result)
    }

    /// Compose only validated sources. Reserving each section's declared
    /// capacity keeps the popup geometry stable when favorites change.
    pub fn composed_sections<'a>(&'a self, menu: &'a NativeMenu) -> Option<Vec<MenuSection<'a>>> {
        if self.view != View::Groups { return None; }
        if menu.presentation == MenuPresentation::Columns {
            return self.column_sections(menu);
        }
        let group = menu.groups.get(self.group)?;
        let composition = group.content.as_ref()?;
        let sidebar = menu.presentation == MenuPresentation::Sidebar;
        let left = if sidebar { SIDEBAR_WIDTH + 4 } else { 8 };
        let width = WIDTH - left - 8;
        let mut top = ACTION_TOP;
        let mut index = 0;
        let mut sections = Vec::with_capacity(composition.len());
        for source in composition {
            let actions: Vec<&str> = match source.kind {
                MenuContentKind::Actions => group.actions.iter().map(String::as_str)
                    .take(source.limit).collect(),
                MenuContentKind::Favorites => self.pins.iter().filter(|pin|
                    menu.groups.iter().any(|group| group.actions.contains(pin)))
                    .map(String::as_str).take(source.limit).collect(),
                MenuContentKind::AppsList | MenuContentKind::AppsGrid => self.apps.iter()
                    .map(|app| app.action.as_str()).take(source.limit).collect(),
            };
            let grid = source.kind == MenuContentKind::AppsGrid;
            let row_height = if grid { CONTENT_GRID_HEIGHT } else { CONTENT_LIST_HEIGHT };
            let mut items = Vec::with_capacity(actions.len());
            for (position, action) in actions.into_iter().enumerate() {
                let column = if grid { position % 2 } else { 0 };
                let row = if grid { position / 2 } else { position };
                let tile_width = if grid { width / 2 } else { width };
                items.push(MenuTile { action, index, x: left + column as u32 * tile_width,
                    y: top + CONTENT_HEADER_HEIGHT + row as u32 * row_height,
                    width: tile_width, height: row_height, grid });
                index += 1;
            }
            sections.push(MenuSection { title: &source.title, x: left,
                kind: source.kind, top, items });
            let rows = if grid { source.limit.div_ceil(2) } else { source.limit };
            top += CONTENT_HEADER_HEIGHT + rows as u32 * row_height;
        }
        Some(sections)
    }

    pub fn first_action_row(&self) -> usize {
        self.first_action_row_for(VISIBLE_ACTIONS)
    }

    pub fn first_action_row_for(&self, rows: usize) -> usize {
        let rows = rows.clamp(1, VISIBLE_ACTIONS);
        (self.selected / rows) * rows
    }

    pub fn start_search(&mut self) {
        self.view = View::Search;
        self.search.clear();
        self.selected = 0;
    }

    pub fn search_input(&mut self, text: &str) -> bool {
        if text.chars().count() != 1 || self.search.chars().count() >= 32
            || self.search.len() + text.len() > 96
            || !text.chars().all(|c| c.is_alphanumeric() || c == ' ' || c == '-') {
            return false;
        }
        if self.view != View::Search { self.start_search(); }
        self.search.push_str(text);
        self.selected = 0;
        true
    }

    pub fn backspace(&mut self) -> bool {
        if self.view != View::Search { return false; }
        self.search.pop();
        self.selected = 0;
        true
    }

    pub fn show_saved(&mut self) {
        self.view = if self.view == View::Saved { View::Groups } else { View::Saved };
        self.search.clear();
        self.selected = 0;
    }

    pub fn back(&mut self) -> bool {
        if self.view == View::Groups { return false; }
        self.view = View::Groups;
        self.search.clear();
        self.selected = 0;
        true
    }

    pub fn toggle_pin(&mut self, menu: &NativeMenu) -> bool {
        let Some(action) = self.current_action(menu).map(str::to_owned) else { return false; };
        // A pin is a validated recipe action. Installed apps are searchable,
        // but are not persisted in the recipe-action pin format.
        if !menu.groups.iter().any(|group| group.actions.contains(&action)) { return false; }
        if let Some(index) = self.pins.iter().position(|item| *item == action) {
            self.pins.remove(index);
        } else if self.pins.len() < MAX_PINS {
            self.pins.push(action);
        } else {
            return false;
        }
        self.selected = self.selected.min(self.actions(menu).len().saturating_sub(1));
        true
    }

    pub fn select_by(&mut self, menu: &NativeMenu, delta: isize) {
        let count = self.actions(menu).len();
        if count == 0 {
            return;
        }
        self.selected = (self.selected as isize + delta).rem_euclid(count as isize) as usize;
    }

    /// Home/End jump to the real first/last action in the current group,
    /// saved view or search results; no invisible recipe actions are invented.
    pub fn select_edge(&mut self, menu: &NativeMenu, last: bool) {
        let count = self.actions(menu).len();
        self.selected = if last { count.saturating_sub(1) } else { 0 };
    }

    /// PageUp/PageDown advance the visible viewport without wrapping around
    /// a long search result. Arrow keys retain their existing cyclic behavior.
    pub fn page_by(&mut self, menu: &NativeMenu, delta: isize) {
        let count = self.actions(menu).len();
        if count == 0 { self.selected = 0; return; }
        self.selected = self.selected.saturating_add_signed(delta)
            .min(count - 1);
    }

    pub fn current_action<'a>(&'a self, menu: &'a NativeMenu) -> Option<&'a str> {
        self.actions(menu).get(self.selected).copied()
    }

    pub fn hit(&self, menu: &NativeMenu, x: f64, y: f64) -> Option<Hit> {
        if !self.visible
            || !x.is_finite()
            || !y.is_finite()
            || x < 0.0
            || x >= f64::from(WIDTH)
            || y < 0.0
            || y >= f64::from(HEIGHT)
        {
            return None;
        }
        match menu.presentation {
            MenuPresentation::Tabs if (f64::from(TAB_TOP)..f64::from(TAB_TOP + TAB_HEIGHT)).contains(&y) => {
                let index = (x as usize * menu.groups.len()) / WIDTH as usize;
                return (index < menu.groups.len()).then_some(Hit::Group(index));
            }
            MenuPresentation::Sidebar if x < f64::from(SIDEBAR_WIDTH)
                && (f64::from(TAB_TOP)..f64::from(TAB_TOP + menu.groups.len() as u32 * SIDEBAR_ROW_HEIGHT)).contains(&y) => {
                return Some(Hit::Group((y as u32 - TAB_TOP) as usize / SIDEBAR_ROW_HEIGHT as usize));
            }
            _ => {}
        }
        if let Some(sections) = self.composed_sections(menu) {
            return sections.iter().flat_map(|section| section.items.iter())
                .find(|tile| x >= f64::from(tile.x) && x < f64::from(tile.x + tile.width)
                    && y >= f64::from(tile.y) && y < f64::from(tile.y + tile.height))
                .map(|tile| Hit::Action(tile.index))
                .or_else(|| (y >= f64::from(HEIGHT - 28)).then_some(Hit::Close));
        }
        if (f64::from(ACTION_TOP)..f64::from(ACTION_TOP + VISIBLE_ACTIONS as u32 * ACTION_HEIGHT)).contains(&y) {
            if menu.presentation == MenuPresentation::Sidebar && x < f64::from(SIDEBAR_WIDTH) {
                return None;
            }
            let index = self.first_action_row() +
                ((y as u32 - ACTION_TOP) / ACTION_HEIGHT) as usize;
            return self.actions(menu).get(index).map(|_| Hit::Action(index));
        }
        (y >= f64::from(HEIGHT - 28)).then_some(Hit::Close)
    }

    /// Compact rendering flattens optional recipe sections into a readable,
    /// paged action list. Both pointer hits and painting use this viewport.
    pub fn compact_hit(&self, menu: &NativeMenu, x: f64, y: f64,
                       size: (u32, u32)) -> Option<Hit> {
        if !self.visible || !compact_layout(size) || !x.is_finite() || !y.is_finite()
            || x < 0.0 || y < 0.0 || x >= f64::from(size.0)
            || y >= f64::from(size.1) {
            return None;
        }
        if (f64::from(COMPACT_TABS_TOP)..f64::from(COMPACT_TABS_TOP + COMPACT_TABS_HEIGHT))
            .contains(&y) && !menu.groups.is_empty() {
            let index = x as usize * menu.groups.len() / size.0 as usize;
            return (index < menu.groups.len()).then_some(Hit::Group(index));
        }
        let rows = compact_visible_actions(size);
        if (f64::from(COMPACT_ACTION_TOP)..f64::from(COMPACT_ACTION_TOP +
            rows as u32 * COMPACT_ACTION_HEIGHT)).contains(&y) {
            let index = self.first_action_row_for(rows) +
                (y as u32 - COMPACT_ACTION_TOP) as usize / COMPACT_ACTION_HEIGHT as usize;
            return self.actions(menu).get(index).map(|_| Hit::Action(index));
        }
        (y >= f64::from(size.1 - COMPACT_FOOTER_HEIGHT)).then_some(Hit::Close)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::recipe::NativeMenuGroup;

    fn menu() -> NativeMenu {
        NativeMenu {
            title: "Desktop".into(),
            presentation: MenuPresentation::Tabs,
            palette: None,
            groups: vec![
                NativeMenuGroup {
                    title: "Programs".into(),
                    actions: vec!["applications".into(), "terminal".into()],
                    content: None,
                },
                NativeMenuGroup {
                    title: "Session".into(),
                    actions: vec!["lock".into(), "logout".into()],
                    content: None,
                },
            ],
        }
    }

    #[test]
    fn columns_show_real_programs_and_system_actions_simultaneously() {
        let recipe = crate::recipe::parse(
            include_str!("../../../examples/wayland/xp-luna-columns.json"),
            Some("xp-luna-columns")).unwrap();
        let menu = recipe.menu.as_ref().unwrap();
        assert_eq!(menu.presentation, MenuPresentation::Columns);
        let mut state = MenuState::default();
        state.open();
        // No installed-app fixtures: all real fixed actions remain present.
        assert_eq!(state.actions(menu), vec![
            "applications", "terminal", "settings", "notifications", "lock", "logout"
        ]);
        assert_eq!(state.hit(menu, 20.0, 116.0), Some(Hit::Action(0)));
        assert_eq!(state.hit(menu, 200.0, 116.0), Some(Hit::Action(2)));
        assert_eq!(state.hit(menu, 200.0, 188.0), Some(Hit::Action(4)));
        assert_eq!(state.hit(menu, 200.0, 218.0), Some(Hit::Action(5)));
        assert_eq!(state.hit(menu, 164.0, 120.0), None);
        assert_eq!(state.hit(menu, 200.0, 290.0), Some(Hit::Close));

        state.horizontal_by(menu, 1);
        assert_eq!(state.current_action(menu), Some("settings"));
        state.horizontal_by(menu, -1);
        assert_eq!(state.current_action(menu), Some("applications"));
        state.select_group(menu, 2);
        assert_eq!(state.current_action(menu), Some("lock"));
        state.start_search();
        assert!(state.search_input("term"));
        // Search and saving use the real shared actions, not fake column labels.
        assert!(state.actions(menu).contains(&"terminal"));
    }

    #[test]
    fn columns_remain_scrollable_on_compact_outputs() {
        let recipe = crate::recipe::parse(
            include_str!("../../../examples/wayland/xp-luna-columns.json"),
            Some("xp-luna-columns")).unwrap();
        let menu = recipe.menu.as_ref().unwrap();
        let mut state = MenuState::default();
        state.open();
        let size = fitted_size(320, 240, 40);
        assert!(compact_layout(size));
        assert_eq!(state.compact_hit(menu, 8.0, 50.0, size), Some(Hit::Group(0)));
        state.select_group(menu, 1);
        assert_eq!(state.current_action(menu), Some("settings"));
        state.select_group(menu, 2);
        assert_eq!(state.current_action(menu), Some("lock"));
        let action_count = state.actions(menu).len();
        assert!(action_count >= 6);
        state.select_edge(menu, true);
        assert_eq!(state.current_action(menu), Some("logout"));
    }

    #[test]
    fn keyboard_cycles_real_actions_and_groups() {
        let data = menu();
        let mut state = MenuState::default();
        state.open();
        assert_eq!(state.current_action(&data), Some("applications"));
        state.select_by(&data, -1);
        assert_eq!(state.current_action(&data), Some("terminal"));
        state.group_by(&data, 1);
        assert_eq!(state.current_action(&data), Some("lock"));
        state.group_by(&data, 1);
        assert_eq!(state.current_action(&data), Some("applications"));
        state.close();
        assert_eq!(state.hit(&data, 15.0, 120.0), None);
    }

    #[test]
    fn native_popup_fits_rotated_small_outputs_and_maps_pointer_back() {
        assert_eq!(fitted_size(1920, 1080, 40), (WIDTH, HEIGHT));
        let tiny = fitted_size(320, 240, 36);
        assert!(tiny.0 <= 320 && tiny.1 <= 196);
        assert!(tiny.0 > 0 && tiny.1 > 0);
        let origin = input_coords((0.0, 0.0), tiny);
        assert_eq!(origin, (0.0, 0.0));
        let center = input_coords((f64::from(tiny.0) / 2.0,
                                   f64::from(tiny.1) / 2.0), tiny);
        assert_eq!(center, (f64::from(WIDTH) / 2.0, f64::from(HEIGHT) / 2.0));
        assert!(compact_layout(tiny));
        assert_eq!(compact_visible_actions(tiny), 2);
        assert!(!compact_layout(fitted_size(100, 100, 36)));
    }

    #[test]
    fn compact_menu_reflows_both_presentations_without_losing_actions() {
        let mut data = menu();
        data.groups[0].actions = vec!["applications".into(), "terminal".into(),
            "audio-up".into(), "audio-down".into(), "wifi-toggle".into()];
        let mut state = MenuState::default();
        state.open();
        let size = fitted_size(320, 240, 36);
        assert_eq!(compact_visible_actions(size), 2);
        state.select_by(&data, 4);
        assert_eq!(state.first_action_row_for(2), 4);
        assert_eq!(state.compact_hit(&data, 22.0, 78.0, size), Some(Hit::Action(4)));
        assert_eq!(state.compact_hit(&data, 22.0, 112.0, size), None);
        assert_eq!(state.compact_hit(&data, 22.0, 50.0, size), Some(Hit::Group(0)));
        assert_eq!(state.compact_hit(&data, 22.0, f64::from(size.1 - 5), size), Some(Hit::Close));
        data.presentation = MenuPresentation::Sidebar;
        assert_eq!(state.compact_hit(&data, f64::from(size.0 - 2), 50.0, size),
                   Some(Hit::Group(1)));
        state.start_search();
        assert!(state.search_input("v"));
        assert_eq!(state.actions(&data), vec!["audio-up", "audio-down"]);
        assert_eq!(state.compact_hit(&data, 20.0, 78.0, size), Some(Hit::Action(0)));
        assert_eq!(state.compact_hit(&data, f64::NAN, 78.0, size), None);
        assert_eq!(state.compact_hit(&data, -1.0, 78.0, size), None);
    }

    #[test]
    fn pointer_hit_testing_never_invents_actions() {
        let data = menu();
        let mut state = MenuState::default();
        state.open();
        assert_eq!(state.hit(&data, 300.0, 50.0), Some(Hit::Group(1)));
        assert_eq!(state.hit(&data, 20.0, 108.0), Some(Hit::Action(0)));
        assert_eq!(state.hit(&data, 20.0, 200.0), None);
        assert_eq!(state.hit(&data, 20.0, 290.0), Some(Hit::Close));
        assert_eq!(state.hit(&data, f64::NAN, 120.0), None);
        assert_eq!(state.hit(&data, -1.0, 120.0), None);
    }

    #[test]
    fn search_is_bounded_and_finds_labels_across_groups() {
        let data = NativeMenu {
            title: "Demo".into(),
            presentation: MenuPresentation::Tabs,
            palette: None,
            groups: vec![NativeMenuGroup { title: "Tools".into(), actions: vec![
                "terminal".into(), "audio-up".into(), "audio-down".into(),
                "wifi-toggle".into(), "notifications".into(),
            ], content: None }],
        };
        let mut state = MenuState::default();
        state.open();
        assert!(state.search_input("v"));
        assert!(state.search_input("o"));
        assert!(state.search_input("l"));
        assert_eq!(state.actions(&data), vec!["audio-up", "audio-down"]);
        assert_eq!(state.current_action(&data), Some("audio-up"));
        assert!(!state.search_input("☃"));
        assert!(!state.search_input("invalid"));
        assert_eq!(state.search, "vol");
        assert!(state.backspace());
        assert_eq!(state.search, "vo");
        assert!(state.back());
        assert_eq!(state.view, View::Groups);
        state.open();
        assert_eq!(state.view, View::Groups);
        assert!(state.search.is_empty());
    }

    #[test]
    fn pins_and_paged_search_keep_pointer_and_selection_consistent() {
        let data = NativeMenu {
            title: "Demo".into(),
            presentation: MenuPresentation::Tabs,
            palette: None,
            groups: vec![NativeMenuGroup { title: "Tools".into(), actions: vec![
                "applications".into(), "terminal".into(), "lock".into(),
                "logout".into(), "wifi-toggle".into(), "audio-up".into(),
            ], content: None }],
        };
        let mut state = MenuState::default();
        state.open();
        state.start_search();
        state.select_by(&data, 5);
        assert_eq!(state.current_action(&data), Some("audio-up"));
        assert_eq!(state.first_action_row(), 4);
        assert_eq!(state.hit(&data, 20.0, 111.0), Some(Hit::Action(4)));
        assert_eq!(state.hit(&data, 20.0, 155.0), Some(Hit::Action(5)));
        assert_eq!(state.hit(&data, 20.0, 206.0), None);
        assert!(state.toggle_pin(&data));
        assert_eq!(state.pins, vec!["audio-up"]);
        state.show_saved();
        assert_eq!(state.actions(&data), vec!["audio-up"]);
        assert!(state.toggle_pin(&data));
        assert!(state.actions(&data).is_empty());
        assert_eq!(state.current_action(&data), None);
        state.close();
        state.open();
        assert!(state.pins.is_empty());
    }

    #[test]
    fn installed_apps_are_searchable_and_never_masquerade_as_recipe_actions() {
        let data = menu();
        let mut state = MenuState::default();
        state.apps = vec![App {
            action: "desktop:org.example.Editor.desktop".into(),
            name: "Example Editor".into(),
            search_text: "example editor writing".into(),
            path: "/usr/share/applications/org.example.Editor.desktop".into(),
        }];
        state.open();
        state.start_search();
        assert_eq!(state.actions(&data), vec!["applications", "terminal", "lock", "logout"]);
        for character in ["w", "r", "i"] { assert!(state.search_input(character)); }
        assert_eq!(state.current_action(&data), Some("desktop:org.example.Editor.desktop"));
        assert_eq!(state.label("desktop:org.example.Editor.desktop"), "Example Editor");
        assert!(state.app_path("desktop:org.example.Editor.desktop").is_some());
        assert!(!state.toggle_pin(&data));
        assert!(state.pins.is_empty());
        state.back();
        assert_eq!(state.current_action(&data), Some("applications"));
    }

    #[test]
    fn search_supports_international_app_names_without_unbounded_input() {
        let data = menu();
        let mut state = MenuState::default();
        state.apps.push(App {
            action: "desktop:schreibwerk.desktop".into(),
            name: "Schreibwerk".into(),
            search_text: "schreibwerk büro".into(),
            path: "/usr/share/applications/schreibwerk.desktop".into(),
        });
        state.open();
        assert!(state.search_input("ü"));
        assert_eq!(state.current_action(&data), Some("desktop:schreibwerk.desktop"));
        for _ in 0..31 { assert!(state.search_input("a")); }
        assert!(!state.search_input("a"));
        assert!(state.backspace());
    }

    #[test]
    fn search_orders_multiword_app_results_by_relevance_not_catalog_position() {
        let data = menu();
        let mut state = MenuState::default();
        let app = |id: &str, name: &str, search: &str| App {
            action: format!("desktop:{id}.desktop"), name: name.into(),
            search_text: search.into(), path: format!("/usr/share/applications/{id}.desktop").into(),
        };
        state.apps = vec![
            app("a", "Archive", "archive file manager utility"),
            app("b", "Manager File", "manager file"),
            app("c", "File Manager", "file manager"),
            app("d", "File Manager Plus", "file manager plus"),
            app("e", "File Manager", "file manager"),
            app("f", "Audio", "audio music"),
        ];
        state.open();
        state.start_search();
        for ch in "file manager".chars() {
            assert!(state.search_input(&ch.to_string()));
        }
        assert_eq!(state.actions(&data), vec![
            "desktop:c.desktop", "desktop:e.desktop", "desktop:d.desktop",
            "desktop:b.desktop", "desktop:a.desktop",
        ]);
        assert_eq!(state.current_action(&data), Some("desktop:c.desktop"));
        state.select_by(&data, 4);
        assert_eq!(state.current_action(&data), Some("desktop:a.desktop"));
        assert!(!state.toggle_pin(&data));
    }

    #[test]
    fn sidebar_navigation_and_action_hits_are_independent() {
        let mut data = menu();
        data.presentation = MenuPresentation::Sidebar;
        let mut state = MenuState::default();
        state.open();
        assert_eq!(state.hit(&data, 24.0, 58.0), Some(Hit::Group(0)));
        assert_eq!(state.hit(&data, 24.0, 102.0), Some(Hit::Group(1)));
        assert_eq!(state.hit(&data, 24.0, 130.0), Some(Hit::Group(1)));
        assert_eq!(state.hit(&data, 130.0, 130.0), Some(Hit::Action(0)));
        assert_eq!(state.hit(&data, 24.0, 262.0), None);
        assert_eq!(state.hit(&data, 130.0, 286.0), Some(Hit::Close));
        state.open_group(1);
        assert_eq!(state.current_action(&data), Some("lock"));
        state.start_search();
        assert_eq!(state.hit(&data, 130.0, 130.0), Some(Hit::Action(0)));
        assert_eq!(state.hit(&data, 24.0, 102.0), Some(Hit::Group(1)));
    }

    #[test]
    fn composed_sections_share_action_indices_with_pointer_and_keyboard() {
        use crate::recipe::NativeMenuContent;
        let mut data = menu();
        data.presentation = MenuPresentation::Sidebar;
        data.groups[0].content = Some(vec![
            NativeMenuContent { kind: MenuContentKind::Actions, title: "Quick Links".into(), limit: 2 },
            NativeMenuContent { kind: MenuContentKind::AppsGrid, title: "Apps".into(), limit: 2 },
        ]);
        let mut state = MenuState::default();
        state.apps = vec![App { action: "desktop:a.desktop".into(), name: "Editor".into(),
            search_text: "editor".into(), path: "/usr/share/applications/a.desktop".into() },
            App { action: "desktop:b.desktop".into(), name: "Browser".into(),
            search_text: "browser".into(), path: "/usr/share/applications/b.desktop".into() }];
        state.open();
        assert_eq!(state.actions(&data), vec!["applications", "terminal", "desktop:a.desktop", "desktop:b.desktop"]);
        let sections = state.composed_sections(&data).unwrap();
        assert_eq!(sections.len(), 2);
        assert_eq!(sections[1].items[0].index, 2);
        assert_eq!(sections[1].items[0].y, sections[1].items[1].y);
        assert_eq!(state.hit(&data, 130.0, 196.0), Some(Hit::Action(2)));
        assert_eq!(state.hit(&data, 232.0, 196.0), Some(Hit::Action(3)));
        assert_eq!(state.hit(&data, 130.0, 184.0), None);
        state.select_by(&data, 2);
        assert_eq!(state.current_action(&data), Some("desktop:a.desktop"));
        state.horizontal_by(&data, 1);
        assert_eq!(state.current_action(&data), Some("desktop:b.desktop"));
        assert!(!state.toggle_pin(&data));
        state.horizontal_by(&data, -1);
        assert_eq!(state.current_action(&data), Some("desktop:a.desktop"));
        state.group_by(&data, 1);
        assert_eq!(state.current_action(&data), Some("lock"));
    }

    #[test]
    fn favorites_and_apps_list_are_bounded_and_do_not_launch_unknown_actions() {
        use crate::recipe::NativeMenuContent;
        let mut data = menu();
        data.groups[0].content = Some(vec![
            NativeMenuContent { kind: MenuContentKind::Favorites, title: "Pinned".into(), limit: 2 },
            NativeMenuContent { kind: MenuContentKind::AppsList, title: "Installed".into(), limit: 2 },
        ]);
        let mut state = MenuState::with_pins(vec!["terminal".into(), "not-in-recipe".into()]);
        state.apps = vec![App { action: "desktop:a.desktop".into(), name: "Editor".into(),
            search_text: "editor".into(), path: "/usr/share/applications/a.desktop".into() }];
        state.open();
        assert_eq!(state.actions(&data), vec!["terminal", "desktop:a.desktop"]);
        assert_eq!(state.hit(&data, 20.0, 124.0), Some(Hit::Action(0)));
        assert_eq!(state.hit(&data, 20.0, 198.0), Some(Hit::Action(1)));
        assert!(state.toggle_pin(&data));
        assert_eq!(state.actions(&data), vec!["desktop:a.desktop"]);
    }

    #[test]
    fn keyboard_page_and_edge_navigation_remain_in_visible_action_bounds() {
        let mut data = menu();
        data.groups[0].actions = vec!["terminal".into(), "audio-up".into(),
            "audio-down".into(), "lock".into(), "wifi-toggle".into(),
            "notifications".into(), "logout".into()];
        let mut state = MenuState::default();
        state.open();
        state.select_edge(&data, true);
        assert_eq!(state.current_action(&data), Some("logout"));
        assert_eq!(state.first_action_row(), 4);
        assert_eq!(state.hit(&data, 15.0, 108.0), Some(Hit::Action(4)));
        state.page_by(&data, -(VISIBLE_ACTIONS as isize));
        assert_eq!(state.current_action(&data), Some("audio-down"));
        state.page_by(&data, -(VISIBLE_ACTIONS as isize));
        assert_eq!(state.current_action(&data), Some("terminal"));
        state.page_by(&data, 100);
        assert_eq!(state.current_action(&data), Some("logout"));
        state.select_edge(&data, false);
        assert_eq!(state.current_action(&data), Some("terminal"));
        state.open_group(1);
        state.select_edge(&data, true);
        assert_eq!(state.current_action(&data), Some("logout"));
    }

    #[test]
    fn keyboard_navigation_safely_handles_empty_saved_view() {
        let data = menu();
        let mut state = MenuState::default();
        state.open();
        state.show_saved();
        state.select_edge(&data, true);
        state.page_by(&data, VISIBLE_ACTIONS as isize);
        state.select_by(&data, -1);
        assert_eq!(state.selected, 0);
        assert_eq!(state.current_action(&data), None);
    }
}
