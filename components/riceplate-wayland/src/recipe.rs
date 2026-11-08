//! Bounded, non-executable RicePlate recipes and shared widget geometry.
//! The Waybar adapter and native renderer consume the same bounded panel JSON.

use std::{
    collections::HashSet,
    error::Error,
    fs::OpenOptions,
    io::Read,
    os::unix::fs::{MetadataExt, OpenOptionsExt},
    path::Path,
};

use serde::Deserialize;

pub const LAUNCHER_WIDTH: u32 = 104;
pub const TASK_WIDTH: u32 = 164;
pub const CLOCK_WIDTH: u32 = 96;
const PAGE_BUTTON_WIDTH: u32 = 24;
const MAX_RECIPE_BYTES: usize = 64 * 1024;
pub const MAX_TRACKED_TASKS: usize = 128;
const MAX_LAYOUT_NODES: usize = 24;
const MAX_LAYOUT_LABELS: usize = 8;
const MAX_LAYOUT_ACTIONS: usize = 6;
const MAX_LAYOUT_DEPTH: usize = 3;
pub const ICON_WIDTH: u32 = 104;
pub const ICON_HEIGHT: u32 = 88;
const MAX_DESKTOP_ICONS: usize = 8;

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct DesktopIcon {
    pub label: String,
    pub action: String,
    pub x: u32,
    pub y: u32,
}

#[derive(Debug, Clone)]
pub struct NativeMenu {
    pub title: String,
    pub groups: Vec<NativeMenuGroup>,
    pub presentation: MenuPresentation,
}

/// The same actions/state can be rendered as a horizontal tab strip or as a
/// persistent left navigation rail. Both have explicit hit-test geometry.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum MenuPresentation {
    #[default]
    Tabs,
    Sidebar,
}

#[derive(Debug, Clone)]
pub struct NativeMenuGroup {
    pub title: String,
    pub actions: Vec<String>,
    pub content: Option<Vec<NativeMenuContent>>,
}

/// Bounded data sources, never arbitrary recipe-supplied launch commands.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MenuContentKind {
    Actions,
    Favorites,
    AppsList,
    AppsGrid,
}

#[derive(Debug, Clone)]
pub struct NativeMenuContent {
    pub kind: MenuContentKind,
    pub title: String,
    pub limit: usize,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Widget {
    Launcher,
    Tasks,
    Clock,
    Battery,
    Network,
    Audio,
    Tray,
    Gap(u32),
    Divider(u32),
    Label(u8),
    Action(u8),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PanelAction {
    pub id: String,
    pub label: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PlacedWidget {
    pub widget: Widget,
    pub x: u32,
    pub width: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Hit {
    Launcher,
    Action(u8),
    Clock,
    Task(usize),
    PreviousTasks,
    NextTasks,
    Tray(usize),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TaskViewport {
    pub start: usize,
    pub slots: usize,
    pub cell_width: u32,
    pub content_width: u32,
    pub prev: bool,
    pub next: bool,
}

pub struct PanelStyle {
    pub id: String,
    pub height: u32,
    pub top: bool,
    /// Launcher, per-task and clock logical widths (schema v1 uses defaults).
    pub widths: [u32; 3],
    pub sections: [Vec<Widget>; 3],
    pub labels: Vec<String>,
    pub actions: Vec<PanelAction>,
    pub compact: Option<(u32, [Vec<Widget>; 3])>,
    pub label_padding: u32,
    pub task_radius: u32,
    pub background: u32,
    pub foreground: u32,
    pub active: u32,
    pub desktop_icons: Vec<DesktopIcon>,
    pub menu: Option<NativeMenu>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Recipe {
    schema_version: u32,
    id: String,
    name: String,
    panel: Panel,
    colors: Colors,
    #[serde(default, deserialize_with = "deserialize_present")]
    menu: Option<Menu>,
    #[serde(default, deserialize_with = "deserialize_present")]
    desktop: Option<Desktop>,
    #[serde(default, deserialize_with = "deserialize_present")]
    tokens: Option<Tokens>,
    #[serde(default, deserialize_with = "deserialize_present")]
    responsive: Option<Responsive>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Menu {
    title: String,
    groups: Vec<MenuGroup>,
    #[serde(default, deserialize_with = "deserialize_present")]
    presentation: Option<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct MenuGroup {
    title: String,
    actions: Vec<String>,
    #[serde(default, deserialize_with = "deserialize_present")]
    content: Option<Vec<MenuContentInput>>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct MenuContentInput {
    #[serde(rename = "type")]
    kind: String,
    title: String,
    limit: u8,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Desktop {
    wallpaper: String,
    #[serde(default, deserialize_with = "deserialize_present")]
    icons: Option<Vec<DesktopIconInput>>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct DesktopIconInput {
    label: String,
    action: String,
    x: u32,
    y: u32,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Tokens {
    label_padding: u32,
    task_radius: u32,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Responsive {
    compact_max_width: u32,
    compact_layout: LayoutSections,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Panel {
    position: String,
    height: u32,
    #[serde(default, deserialize_with = "deserialize_present")]
    sections: Option<Sections>,
    #[serde(default, deserialize_with = "deserialize_present")]
    layout: Option<LayoutSections>,
    // Distinguish an absent field from an explicitly supplied JSON null.
    #[serde(default, deserialize_with = "deserialize_present")]
    metrics: Option<PanelMetrics>,
}

fn deserialize_present<'de, D, T>(deserializer: D) -> Result<Option<T>, D::Error>
where
    D: serde::Deserializer<'de>,
    T: Deserialize<'de>,
{
    T::deserialize(deserializer).map(Some)
}

#[derive(Deserialize, Clone, Copy)]
#[serde(deny_unknown_fields)]
struct PanelMetrics {
    launcher_width: u32,
    task_width: u32,
    clock_width: u32,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Sections {
    start: Vec<String>,
    center: Vec<String>,
    end: Vec<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct LayoutSections {
    start: Vec<LayoutNode>,
    center: Vec<LayoutNode>,
    end: Vec<LayoutNode>,
}

#[derive(Deserialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
enum LayoutNode {
    Widget { id: String },
    Gap { width: u32 },
    Divider { width: u32 },
    Label { text: String },
    Action { id: String, label: String },
    Group { gap: u32, children: Vec<LayoutNode> },
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Colors {
    background: String,
    foreground: String,
    active: String,
}

fn color(raw: &str) -> Result<u32, Box<dyn Error>> {
    if raw.len() != 7 || !raw.starts_with('#') || !raw[1..].bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err("RicePlate color must be six hexadecimal RGB digits".into());
    }
    Ok(0xff00_0000 | u32::from_str_radix(&raw[1..], 16)?)
}

fn safe_label(text: &str, max_length: usize) -> bool {
    !text.is_empty()
        && text.len() <= max_length
        && text
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b" ._:+-".contains(&b))
}

fn validate_menu(menu: &Menu, version: u32) -> Result<(), Box<dyn Error>> {
    if !safe_label(&menu.title, 32) || !(1..=4).contains(&menu.groups.len()) {
        return Err("Invalid bounded menu title/groups".into());
    }
    if let Some(presentation) = menu.presentation.as_deref() {
        if version < 6 || !matches!(presentation, "tabs" | "sidebar") {
            return Err("Menu presentation requires schema v6 and tabs/sidebar".into());
        }
    }
    let mut seen = HashSet::new();
    for group in &menu.groups {
        if !safe_label(&group.title, 24) || !(1..=4).contains(&group.actions.len()) {
            return Err("Invalid menu group".into());
        }
        if let Some(content) = &group.content {
            if version < 6 || !(1..=2).contains(&content.len())
                || content.iter().map(|section| section.limit as usize).sum::<usize>() > 4
            {
                return Err("Menu content needs schema v6 and at most four visible items".into());
            }
            let mut sources = HashSet::new();
            for section in content {
                if !matches!(section.kind.as_str(), "actions" | "favorites" | "apps-list" | "apps-grid")
                    || !sources.insert(section.kind.as_str())
                    || !safe_label(&section.title, 24)
                    || !(1..=4).contains(&section.limit)
                {
                    return Err("Invalid or repeated menu content source".into());
                }
            }
        }
        for action in &group.actions {
            if !["applications", "terminal", "lock", "logout",
                 "wifi-toggle", "audio-mute", "audio-up", "audio-down", "notifications", "settings"]
                .contains(&action.as_str())
                || !seen.insert(action.as_str())
            {
                return Err("Menu contains unsupported or duplicate action".into());
            }
        }
    }
    Ok(())
}

fn validate_icons(icons: Vec<DesktopIconInput>) -> Result<Vec<DesktopIcon>, Box<dyn Error>> {
    if !(1..=MAX_DESKTOP_ICONS).contains(&icons.len()) {
        return Err("Desktop must contain 1-8 icons".into());
    }
    let mut result: Vec<DesktopIcon> = Vec::new();
    for icon in icons {
        if !safe_label(&icon.label, 12)
            || !["applications", "terminal", "lock"].contains(&icon.action.as_str())
            || icon.x > 4096
            || !(72..=4096).contains(&icon.y)
            || result.iter().any(|existing| {
                existing.x.abs_diff(icon.x) < ICON_WIDTH
                    && existing.y.abs_diff(icon.y) < ICON_HEIGHT
            })
        {
            return Err("Unsafe, unbounded or overlapping desktop icon".into());
        }
        result.push(DesktopIcon {
            label: icon.label,
            action: icon.action,
            x: icon.x,
            y: icon.y,
        });
    }
    Ok(result)
}

fn expand_layout(
    node: &LayoutNode,
    depth: usize,
    counts: &mut [usize; 2],
    seen: &mut HashSet<String>,
    rendered: &mut Vec<Widget>,
    labels: &mut Vec<String>,
    actions: &mut Vec<PanelAction>,
    version: u32,
) -> Result<(), Box<dyn Error>> {
    counts[0] += 1;
    if depth > MAX_LAYOUT_DEPTH || counts[0] > MAX_LAYOUT_NODES {
        return Err("Panel layout exceeds bounded depth or node count".into());
    }
    match node {
        LayoutNode::Widget { id } => {
            if !seen.insert(id.clone()) {
                return Err("Duplicate panel widget".into());
            }
            match id.as_str() {
                "launcher" => rendered.push(Widget::Launcher),
                "tasks" => rendered.push(Widget::Tasks),
                "clock" => rendered.push(Widget::Clock),
                "battery" => rendered.push(Widget::Battery),
                "network" => rendered.push(Widget::Network),
                "audio" => rendered.push(Widget::Audio),
                // Known but unsupported native controls remain Waybar-only.
                "tray" => rendered.push(Widget::Tray),
                _ => return Err("Unsupported panel widget or action".into()),
            }
        }
        LayoutNode::Gap { width } => {
            if !(4..=64).contains(width) {
                return Err("Panel gap width invalid".into());
            }
            rendered.push(Widget::Gap(*width));
        }
        LayoutNode::Divider { width } => {
            if !(6..=32).contains(width) {
                return Err("Panel divider width invalid".into());
            }
            rendered.push(Widget::Divider(*width));
        }
        LayoutNode::Label { text } => {
            if !safe_label(text, 24) {
                return Err("Panel label is not bounded safe ASCII".into());
            }
            counts[1] += 1;
            if counts[1] > MAX_LAYOUT_LABELS {
                return Err("Too many labels".into());
            }
            let index = labels.len() as u8;
            labels.push(text.clone());
            rendered.push(Widget::Label(index));
        }
        LayoutNode::Action { id, label } => {
            if version < 6
                || !["applications", "terminal", "settings", "lock"].contains(&id.as_str())
                || !safe_label(label, 16)
                || !seen.insert(format!("action:{id}"))
            {
                return Err("Invalid or duplicate native panel action".into());
            }
            let index = if let Some(index) = actions.iter().position(|item| item.id == *id) {
                if actions[index].label != *label {
                    return Err("Responsive panel action label changed".into());
                }
                index
            } else {
                if actions.len() >= MAX_LAYOUT_ACTIONS {
                    return Err("Too many panel actions".into());
                }
                actions.push(PanelAction { id: id.clone(), label: label.clone() });
                actions.len() - 1
            };
            rendered.push(Widget::Action(index as u8));
        }
        LayoutNode::Group { gap, children } => {
            if depth >= MAX_LAYOUT_DEPTH || *gap > 32 || !(1..=6).contains(&children.len()) {
                return Err("Invalid panel group".into());
            }
            for (index, child) in children.iter().enumerate() {
                if index > 0 && *gap > 0 {
                    rendered.push(Widget::Gap(*gap));
                }
                expand_layout(child, depth + 1, counts, seen, rendered, labels, actions, version)?;
            }
        }
    }
    Ok(())
}

pub fn parse(raw: &str, expected_id: Option<&str>) -> Result<PanelStyle, Box<dyn Error>> {
    if raw.len() > MAX_RECIPE_BYTES {
        return Err("RicePlate recipe exceeds 64 KiB".into());
    }
    let recipe: Recipe = serde_json::from_str(raw)?;
    let id = recipe.id.as_bytes();
    if ![1, 2, 3, 4, 5, 6].contains(&recipe.schema_version)
        || id.len() < 2
        || id.len() > 32
        || !id[0].is_ascii_lowercase()
        || !id
            .iter()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || *b == b'-')
        || expected_id.is_some_and(|expected| expected != recipe.id.as_str())
        || recipe.name.is_empty()
        || recipe.name.chars().count() > 60
        || recipe.name.chars().any(char::is_control)
        || !(28..=64).contains(&recipe.panel.height)
        || !["top", "bottom"].contains(&recipe.panel.position.as_str())
    {
        return Err("RicePlate recipe metadata or dimensions are invalid".into());
    }
    let widths = match (recipe.schema_version, recipe.panel.metrics) {
        (1, None) => [LAUNCHER_WIDTH, TASK_WIDTH, CLOCK_WIDTH],
        (2 | 3 | 4 | 5 | 6, Some(metrics))
            if (64..=256).contains(&metrics.launcher_width)
                && (96..=256).contains(&metrics.task_width)
                && (64..=256).contains(&metrics.clock_width) =>
        {
            [
                metrics.launcher_width,
                metrics.task_width,
                metrics.clock_width,
            ]
        }
        _ => return Err("RicePlate v2/v3 requires bounded metrics; v1 forbids them".into()),
    };
    let mut seen: HashSet<String> = HashSet::new();
    let mut sections: [Vec<Widget>; 3] = std::array::from_fn(|_| Vec::new());
    let mut labels = Vec::new();
    let mut actions = Vec::new();
    match (
        recipe.schema_version,
        recipe.panel.sections,
        recipe.panel.layout,
    ) {
        (1 | 2, Some(source), None) => {
            let selected = [source.start, source.center, source.end];
            for (index, widgets) in selected.into_iter().enumerate() {
                if widgets.len() > 7 {
                    return Err("RicePlate section has more than seven widgets".into());
                }
                for widget in widgets {
                    if !seen.insert(widget.clone()) {
                        return Err("RicePlate recipe duplicates a widget".into());
                    }
                    match widget.as_str() {
                        "launcher" => sections[index].push(Widget::Launcher),
                        "tasks" => sections[index].push(Widget::Tasks),
                        "clock" => sections[index].push(Widget::Clock),
                        "battery" => sections[index].push(Widget::Battery),
                        "network" => sections[index].push(Widget::Network),
                        "audio" => sections[index].push(Widget::Audio),
                        "tray" => sections[index].push(Widget::Tray),
                        _ => return Err("Unsupported RicePlate widget or action".into()),
                    }
                }
            }
        }
        (3 | 4 | 5 | 6, None, Some(layout)) => {
            let source = [layout.start, layout.center, layout.end];
            let mut counts = [0_usize, 0_usize];
            for (index, nodes) in source.iter().enumerate() {
                if nodes.len() > 8 {
                    return Err("Too many layout roots".into());
                }
                for node in nodes {
                    expand_layout(
                        node,
                        1,
                        &mut counts,
                        &mut seen,
                        &mut sections[index],
                        &mut labels,
                        &mut actions,
                        recipe.schema_version,
                    )?;
                }
            }
        }
        _ => return Err("Legacy sections and v3 layouts are mutually exclusive".into()),
    }
    if !seen.contains("launcher") && !seen.contains("tasks") {
        return Err("RicePlate requires a launcher or task widget".into());
    }
    let mut compact = None;
    let mut label_padding = 8;
    let mut task_radius = 4;
    let mut desktop_icons = Vec::new();
    let mut native_menu = None;
    match (
        recipe.schema_version,
        recipe.menu,
        recipe.desktop,
        recipe.tokens,
        recipe.responsive,
    ) {
        (version @ (4 | 5 | 6), Some(menu), Some(desktop), Some(tokens), Some(responsive)) => {
            validate_menu(&menu, version)?;
            native_menu = Some(NativeMenu {
                title: menu.title,
                presentation: if menu.presentation.as_deref() == Some("sidebar") {
                    MenuPresentation::Sidebar
                } else {
                    MenuPresentation::Tabs
                },
                groups: menu
                    .groups
                    .into_iter()
                    .map(|group| NativeMenuGroup {
                        title: group.title,
                        actions: group.actions,
                        content: group.content.map(|sections| sections.into_iter().map(|section| {
                            let kind = match section.kind.as_str() {
                                "actions" => MenuContentKind::Actions,
                                "favorites" => MenuContentKind::Favorites,
                                "apps-list" => MenuContentKind::AppsList,
                                "apps-grid" => MenuContentKind::AppsGrid,
                                _ => unreachable!("validated menu content source"),
                            };
                            NativeMenuContent { kind, title: section.title,
                                                limit: section.limit as usize }
                        }).collect()),
                    })
                    .collect(),
            });
            desktop_icons = match (version, desktop.icons) {
                (4, None) => Vec::new(),
                (5 | 6, Some(icons)) => validate_icons(icons)?,
                _ => return Err("Schema v5 requires icons; v4 forbids them".into()),
            };
            let bundled = [
                "aero-seven-blue",
                "aero-seven-night",
                "luna-hills",
                "classic-teal",
                "ten-blue",
                "ten-midnight",
                "chrome-pastel",
                "frutiger-future",
                "aurora-day",
                "aurora-night",
            ].contains(&desktop.wallpaper.as_str());
            let private_asset = version == 6 && desktop.wallpaper.len() == 70
                && desktop.wallpaper.starts_with("asset-")
                && desktop.wallpaper.as_bytes()[6..].iter().all(|c|
                    c.is_ascii_hexdigit() && !c.is_ascii_uppercase());
            if !(bundled || private_asset)
                || tokens.label_padding > 16
                || tokens.task_radius > 12
                || !(480..=1440).contains(&responsive.compact_max_width)
            {
                return Err("Invalid v4 desktop, visual tokens or breakpoint".into());
            }
            label_padding = tokens.label_padding;
            task_radius = tokens.task_radius;
            let mut smaller: [Vec<Widget>; 3] = std::array::from_fn(|_| Vec::new());
            let mut compact_seen = HashSet::new();
            let mut counts = [0_usize, 0_usize];
            for (index, nodes) in [
                responsive.compact_layout.start,
                responsive.compact_layout.center,
                responsive.compact_layout.end,
            ]
            .iter()
            .enumerate()
            {
                if nodes.len() > 8 {
                    return Err("Too many compact panel roots".into());
                }
                for node in nodes {
                    expand_layout(
                        node,
                        1,
                        &mut counts,
                        &mut compact_seen,
                        &mut smaller[index],
                        &mut labels,
                        &mut actions,
                        version,
                    )?;
                }
            }
            if !compact_seen.contains("launcher") && !compact_seen.contains("tasks") {
                return Err("Compact panel lacks launcher or task list".into());
            }
            compact = Some((responsive.compact_max_width, smaller));
        }
        (1 | 2 | 3, None, None, None, None) => {}
        _ => return Err("Shell menu, desktop, tokens and responsive require schema v4".into()),
    }
    Ok(PanelStyle {
        id: recipe.id,
        height: recipe.panel.height,
        top: recipe.panel.position == "top",
        widths,
        sections,
        labels,
        actions,
        compact,
        label_padding,
        task_radius,
        background: color(&recipe.colors.background)?,
        foreground: color(&recipe.colors.foreground)?,
        active: color(&recipe.colors.active)?,
        desktop_icons,
        menu: native_menu,
    })
}

pub fn load(name_or_path: &str) -> Result<PanelStyle, Box<dyn Error>> {
    let (raw, expected): (String, Option<&str>) = match name_or_path {
        "classic" => (
            include_str!("../../../macrice/de/resources/recipes/classic.json").into(),
            Some("classic"),
        ),
        "chrome" => (
            include_str!("../../../macrice/de/resources/recipes/chrome.json").into(),
            Some("chrome"),
        ),
        path => {
            let path = Path::new(path);
            if !path.is_absolute() {
                return Err("Choose classic, chrome or an absolute private JSON path".into());
            }
            let file = OpenOptions::new()
                .read(true)
                .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
                .open(path)?;
            let metadata = file.metadata()?;
            // Verify the opened inode, never just path metadata; no symlinks,
            // world/group-readable recipes, foreign owners, devices or pipes.
            if !metadata.is_file()
                || metadata.uid() != unsafe { libc::geteuid() }
                || metadata.mode() & 0o077 != 0
                || metadata.len() > MAX_RECIPE_BYTES as u64
            {
                return Err("Custom RicePlate recipe must be an owner-private regular file".into());
            }
            let mut data = Vec::new();
            file.take(MAX_RECIPE_BYTES as u64 + 1)
                .read_to_end(&mut data)?;
            if data.len() > MAX_RECIPE_BYTES {
                return Err("Recipe exceeds 64 KiB".into());
            }
            (String::from_utf8(data)?, None)
        }
    };
    parse(&raw, expected)
}

fn width_for(style: &PanelStyle, widget: Widget, tasks: usize) -> u32 {
    match widget {
        Widget::Launcher => style.widths[0],
        Widget::Clock => style.widths[2],
        Widget::Battery | Widget::Network | Widget::Audio => 64,
        Widget::Tray => crate::tray::WIDTH,
        Widget::Tasks => tasks as u32 * style.widths[1],
        Widget::Gap(width) => width,
        Widget::Divider(width) => width,
        Widget::Label(index) => {
            style.labels[index as usize].len() as u32 * 8 + style.label_padding * 2
        }
        Widget::Action(index) => {
            style.actions[index as usize].label.len() as u32 * 8 + style.label_padding * 2 + 8
        }
    }
}

pub fn layout(style: &PanelStyle, screen_width: u32, tasks: usize) -> Vec<PlacedWidget> {
    let sections = match &style.compact {
        Some((threshold, compact)) if screen_width <= *threshold => compact,
        _ => &style.sections,
    };
    // A tray is an interactive region. Do not reserve fake hit targets on
    // narrow displays where it would eliminate the only task slot.
    let tray_enabled = screen_width >= style.widths.iter().sum::<u32>()
        .saturating_add(crate::tray::WIDTH + 8);
    let fixed_width: u32 = sections
        .iter()
        .flatten()
        .filter(|&&w| w != Widget::Tasks && (w != Widget::Tray || tray_enabled))
        .map(|&w| width_for(style, w, 0))
        .sum();
    let optional = [Widget::Battery, Widget::Audio, Widget::Network];
    let enabled = optional.map(|widget| sections.iter().flatten().any(|&w| w == widget));
    let without_status = fixed_width.saturating_sub(
        enabled.iter().filter(|&&present| present).count() as u32 * 64);
    let has_clock = sections.iter().flatten().any(|&w| w == Widget::Clock);
    let show_clock = !has_clock || screen_width >= without_status;
    let mut effective_fixed = without_status.saturating_sub(
        if show_clock || !has_clock { 0 } else { style.widths[2] });
    let baseline_slots = screen_width.saturating_sub(effective_fixed + 8) / style.widths[1];
    let mut show_status = [false; 3];
    // Preserve task capacity, adding lower-priority read-only indicators only
    // when the next one does not cost an existing visible task group.
    for (index, present) in enabled.into_iter().enumerate() {
        if !present { continue; }
        let next_width = effective_fixed + 64;
        let slots = screen_width.saturating_sub(next_width + 8) / style.widths[1];
        if screen_width >= next_width && (slots >= tasks.min(MAX_TRACKED_TASKS) as u32
            || slots == baseline_slots) {
            show_status[index] = true;
            effective_fixed = next_width;
        }
    }
    let visible = tasks
        .min(MAX_TRACKED_TASKS)
        .min((screen_width.saturating_sub(effective_fixed + 8) / style.widths[1]) as usize);
    let is_visible = |widget: Widget| -> bool {
        if widget == Widget::Tray { return tray_enabled; }
        if widget == Widget::Clock { return show_clock; }
        if let Some(index) = optional.iter().position(|&candidate| candidate == widget) {
            return show_status[index];
        }
        true
    };
    let section_width = |widgets: &[Widget]| -> u32 {
        widgets
            .iter()
            .filter(|&&w| is_visible(w))
            .map(|&w| width_for(style, w, visible))
            .sum()
    };
    let widths: [u32; 3] = std::array::from_fn(|i| section_width(&sections[i]));
    let end_x = screen_width.saturating_sub(widths[2]);
    let middle_x = (screen_width.saturating_sub(widths[1]) / 2)
        .max(widths[0])
        .min(end_x.saturating_sub(widths[1]));
    let mut result = Vec::new();
    for (index, begin) in [0, middle_x, end_x].into_iter().enumerate() {
        let mut x = begin;
        for &widget in &sections[index] {
            if !is_visible(widget) {
                continue;
            }
            let width = width_for(style, widget, visible);
            if width > 0 {
                result.push(PlacedWidget { widget, x, width });
                x = x.saturating_add(width);
            }
        }
    }
    result
}

pub fn task_view(
    style: &PanelStyle,
    screen_width: u32,
    tasks: usize,
    offset: usize,
) -> Option<TaskViewport> {
    let item = layout(style, screen_width, tasks)
        .into_iter()
        .find(|placed| placed.widget == Widget::Tasks)?;
    let slots = (item.width / style.widths[1]) as usize;
    if slots == 0 {
        return None;
    }
    let overflowing = tasks > slots;
    let start = if overflowing {
        offset.min(tasks - slots)
    } else {
        0
    };
    let controls = if overflowing {
        PAGE_BUTTON_WIDTH * 2
    } else {
        0
    };
    let content_width = item.width.saturating_sub(controls);
    Some(TaskViewport {
        start,
        slots,
        cell_width: content_width / slots as u32,
        content_width,
        prev: overflowing && start > 0,
        next: overflowing && start + slots < tasks,
    })
}

pub fn hit(
    x: f64,
    screen_width: u32,
    tasks: usize,
    offset: usize,
    style: &PanelStyle,
) -> Option<Hit> {
    if !x.is_finite() || x < 0.0 || x >= f64::from(screen_width) {
        return None;
    }
    for item in layout(style, screen_width, tasks) {
        if x < f64::from(item.x) || x >= f64::from(item.x + item.width) {
            continue;
        }
        return match item.widget {
            Widget::Launcher => Some(Hit::Launcher),
            Widget::Tasks => {
                let view = task_view(style, screen_width, tasks, offset)?;
                let local = x - f64::from(item.x);
                if local >= f64::from(view.content_width) {
                    if local < f64::from(view.content_width + PAGE_BUTTON_WIDTH) && view.prev {
                        Some(Hit::PreviousTasks)
                    } else if local >= f64::from(view.content_width + PAGE_BUTTON_WIDTH)
                        && view.next
                    {
                        Some(Hit::NextTasks)
                    } else {
                        None
                    }
                } else {
                    let index = ((local / f64::from(view.cell_width)) as usize).min(view.slots - 1);
                    Some(Hit::Task(view.start + index))
                }
            }
            Widget::Clock => Some(Hit::Clock),
            Widget::Action(index) => Some(Hit::Action(index)),
            Widget::Tray => Some(Hit::Tray(((x - f64::from(item.x)) /
                f64::from(crate::tray::SLOT_WIDTH)) as usize)),
            Widget::Battery | Widget::Network | Widget::Audio => None,
            Widget::Gap(_) | Widget::Divider(_) | Widget::Label(_) => None,
        };
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    const ACTIONS_V6: &str = include_str!("../../../tests/fixtures/riceplate-actions-v6.json");

    #[test]
    fn v6_action_buttons_have_shared_render_and_hit_geometry() {
        let style = parse(ACTIONS_V6, Some("mockup-actions")).unwrap();
        assert_eq!(style.actions.len(), 2);
        assert_eq!(style.actions[0].id, "terminal");
        assert_eq!(style.actions[1].label, "Settings");
        let wide = layout(&style, 1280, 2);
        for index in [0, 1] {
            let button = wide.iter().find(|placed|
                placed.widget == Widget::Action(index)).unwrap();
            assert_eq!(hit((button.x + 1) as f64, 1280, 2, 0, &style),
                       Some(Hit::Action(index)));
        }
        let compact = layout(&style, 600, 2);
        assert!(!compact.iter().any(|placed| placed.widget == Widget::Action(0)));
        let settings = compact.iter().find(|placed|
            placed.widget == Widget::Action(1)).unwrap();
        assert_eq!(hit((settings.x + 1) as f64, 600, 2, 0, &style), Some(Hit::Action(1)));
    }

    #[test]
    fn v6_action_buttons_reject_unknown_ids_commands_and_label_drift() {
        let source: serde_json::Value = serde_json::from_str(ACTIONS_V6).unwrap();
        for invalid in [
            serde_json::json!({"type":"action","id":"logout","label":"Logout"}),
            serde_json::json!({"type":"action","id":"terminal","label":"<bad>"}),
            serde_json::json!({"type":"action","id":"terminal","label":"Terminal","exec":"sh"}),
            serde_json::json!({"type":"action","id":"terminal","label":"12345678901234567"}),
        ] {
            let mut changed = source.clone();
            changed["panel"]["layout"]["start"][0]["children"][1] = invalid;
            assert!(parse(&changed.to_string(), None).is_err());
        }
        let mut old = source.clone();
        old["schema_version"] = serde_json::json!(5);
        assert!(parse(&old.to_string(), None).is_err());
        let mut repeated = source.clone();
        repeated["panel"]["layout"]["end"].as_array_mut().unwrap().push(
            serde_json::json!({"type":"action","id":"terminal","label":"Terminal"}));
        assert!(parse(&repeated.to_string(), None).is_err());
        let mut changed = source;
        changed["responsive"]["compact_layout"]["end"][0]["label"] =
            serde_json::json!("Prefs");
        assert!(parse(&changed.to_string(), None).is_err());
    }

    #[test]
    fn native_quick_actions_are_recipe_allowlisted() {
        let recipe = parse(include_str!("../../../examples/wayland/quick-controls.json"),
                           Some("quick-controls")).unwrap();
        let menu = recipe.menu.as_ref().unwrap();
        assert_eq!(menu.groups[1].actions,
                   ["wifi-toggle", "audio-mute", "audio-up", "audio-down"]);
        assert_eq!(menu.groups[2].actions,
                   ["notifications", "lock", "logout"]);
    }

    #[test]
    fn schema_v5_icons_are_strict_bounded_and_use_known_actions() {
        let source = include_str!("../../../tests/fixtures/riceplate-desktop-v5.json");
        let style = parse(source, Some("mockup-desktop")).unwrap();
        assert_eq!(style.desktop_icons.len(), 3);
        assert_eq!(style.desktop_icons[0].label, "Applications");
        assert_eq!(style.desktop_icons[1].action, "terminal");
        let mut data: serde_json::Value = serde_json::from_str(source).unwrap();
        data["desktop"]["icons"][0]["action"] = "sh -c whoami".into();
        assert!(parse(&data.to_string(), None).is_err());
        data["desktop"]["icons"][0]["action"] = "applications".into();
        data["desktop"]["icons"][0]["x"] = true.into();
        assert!(parse(&data.to_string(), None).is_err());
        data["desktop"]["icons"][0]["x"] = 32.into();
        data["desktop"]["icons"][1]["x"] = 33.into();
        data["desktop"]["icons"][1]["y"] = 97.into();
        assert!(parse(&data.to_string(), None).is_err());
        data["desktop"]["icons"][1]["x"] = 32.into();
        data["desktop"]["icons"][1]["y"] = 208.into();
        data["desktop"].as_object_mut().unwrap().remove("icons");
        assert!(parse(&data.to_string(), None).is_err());
        data["schema_version"] = 4.into();
        data["desktop"]["icons"] = serde_json::json!([]);
        assert!(parse(&data.to_string(), None).is_err());
    }

    #[test]
    fn schema_v6_menu_presentation_is_bounded_and_backwards_compatible() {
        let source = include_str!("../../../tests/fixtures/riceplate-desktop-v5.json");
        let legacy = parse(source, Some("mockup-desktop")).unwrap();
        assert_eq!(legacy.menu.unwrap().presentation, MenuPresentation::Tabs);

        let mut data: serde_json::Value = serde_json::from_str(source).unwrap();
        data["schema_version"] = serde_json::json!(6);
        data["menu"]["presentation"] = serde_json::json!("sidebar");
        let sidebar = parse(&data.to_string(), Some("mockup-desktop")).unwrap();
        assert_eq!(sidebar.menu.unwrap().presentation, MenuPresentation::Sidebar);
        data["menu"]["presentation"] = serde_json::json!("tabs");
        assert_eq!(parse(&data.to_string(), None).unwrap().menu.unwrap().presentation,
                   MenuPresentation::Tabs);

        data["menu"]["presentation"] = serde_json::json!("not-a-renderer");
        assert!(parse(&data.to_string(), None).is_err());
        data["menu"]["presentation"] = serde_json::Value::Null;
        assert!(parse(&data.to_string(), None).is_err());
        data["menu"]["presentation"] = serde_json::json!("sidebar");
        data["schema_version"] = serde_json::json!(5);
        assert!(parse(&data.to_string(), None).is_err());
    }

    #[test]
    fn schema_v6_menu_content_is_strict_and_non_executable() {
        let source = include_str!("../../../tests/fixtures/riceplate-composed-v6.json");
        let parsed = parse(source, Some("mockup-composed")).unwrap();
        let menu = parsed.menu.unwrap();
        assert_eq!(menu.presentation, MenuPresentation::Sidebar);
        assert_eq!(menu.groups[0].content.as_ref().unwrap().len(), 2);
        assert_eq!(menu.groups[0].content.as_ref().unwrap()[1].kind, MenuContentKind::AppsGrid);
        assert_eq!(menu.groups[1].content.as_ref().unwrap()[0].kind, MenuContentKind::Favorites);
        let mut data: serde_json::Value = serde_json::from_str(source).unwrap();
        data["menu"]["groups"][0]["content"][1]["type"] = serde_json::json!("apps-list");
        assert_eq!(parse(&data.to_string(), None).unwrap().menu.unwrap().groups[0]
                   .content.as_ref().unwrap()[1].kind, MenuContentKind::AppsList);
        data["menu"]["groups"][0]["content"][1]["type"] = serde_json::json!("shell-command");
        assert!(parse(&data.to_string(), None).is_err());
        data["menu"]["groups"][0]["content"][1]["type"] = serde_json::json!("apps-grid");
        data["menu"]["groups"][0]["content"][1]["limit"] = serde_json::json!(5);
        assert!(parse(&data.to_string(), None).is_err());
        data["menu"]["groups"][0]["content"][1]["limit"] = serde_json::json!(2);
        data["menu"]["groups"][0]["content"][0]["command"] = serde_json::json!("sh -c pwd");
        assert!(parse(&data.to_string(), None).is_err());
        data["menu"]["groups"][0]["content"][0].as_object_mut().unwrap().remove("command");
        data["menu"]["groups"][0]["content"][1]["type"] = serde_json::json!("actions");
        assert!(parse(&data.to_string(), None).is_err());
        data["menu"]["groups"][0]["content"][1]["type"] = serde_json::json!("apps-grid");
        data["schema_version"] = serde_json::json!(5);
        data["menu"].as_object_mut().unwrap().remove("presentation");
        assert!(parse(&data.to_string(), None).is_err());
    }

    #[test]
    fn bundled_recipes_are_distinct_and_validated() {
        let a = load("classic").unwrap();
        let b = load("chrome").unwrap();
        assert_eq!((a.height, b.height), (36, 44));
        assert_ne!(a.background, b.background);
        assert_eq!(hit(110.0, 800, 2, 0, &a), Some(Hit::Task(0)));
        assert_eq!(hit(110.0, 800, 2, 0, &b), None);
        assert_eq!(hit(250.0, 800, 2, 0, &b), Some(Hit::Task(0)));
        let clock = layout(&b, 800, 2).into_iter()
            .find(|item| item.widget == Widget::Clock).unwrap();
        assert_eq!(hit(f64::from(clock.x + 6), 800, 2, 0, &b), Some(Hit::Clock));
        assert_eq!(hit(150.0, 180, 20, 0, &b), None);
        assert!(layout(&b, 180, 20)
            .iter()
            .all(|item| item.widget != Widget::Clock));
        assert!(layout(&b, 180, 20).iter().all(|item| item.widget != Widget::Tray));
    }

    #[test]
    fn custom_composition_repositions_all_supported_widgets() {
        let sample = include_str!("../../../macrice/de/resources/recipes/classic.json");
        let reordered = sample
            .replace(
                "\"start\": [\"launcher\", \"tasks\"],",
                "\"start\": [\"clock\"],",
            )
            .replace(
                "\"end\": [\"network\", \"audio\", \"battery\", \"clock\", \"tray\"]",
                "\"end\": [\"network\", \"audio\", \"battery\", \"launcher\", \"tasks\", \"tray\"]",
            );
        let style = parse(&reordered, Some("classic")).unwrap();
        assert_eq!(hit(40.0, 800, 2, 0, &style), Some(Hit::Clock));
        let layout = layout(&style, 800, 2);
        let launcher = layout.iter().find(|item| item.widget == Widget::Launcher).unwrap();
        let tasks = layout.iter().find(|item| item.widget == Widget::Tasks).unwrap();
        assert_eq!(hit(f64::from(launcher.x + 6), 800, 2, 0, &style), Some(Hit::Launcher));
        assert_eq!(hit(f64::from(tasks.x + 6), 800, 2, 0, &style), Some(Hit::Task(0)));
    }

    #[test]
    fn overflow_pages_reach_all_windows_without_overlapping_hit_areas() {
        let style = load("classic").unwrap();
        let view = task_view(&style, 800, 10, 0).unwrap();
        assert_eq!((view.slots, view.start), (2, 0));
        assert!(!view.prev && view.next);
        let start = LAUNCHER_WIDTH as f64;
        let nav = start + f64::from(view.content_width);
        assert_eq!(hit(start + 10.0, 800, 10, 0, &style), Some(Hit::Task(0)));
        assert_eq!(hit(nav + 5.0, 800, 10, 0, &style), None);
        assert_eq!(hit(nav + 30.0, 800, 10, 0, &style), Some(Hit::NextTasks));
        assert_eq!(hit(start + 10.0, 800, 10, view.slots, &style),
                   Some(Hit::Task(view.slots)));
        assert_eq!(hit(nav + 5.0, 800, 10, view.slots, &style), Some(Hit::PreviousTasks));
        let last = task_view(&style, 800, 10, usize::MAX).unwrap();
        assert_eq!(last.start, 8);
        assert!(last.prev && !last.next);
        assert_eq!(
            hit(start + 10.0, 800, 10, usize::MAX, &style),
            Some(Hit::Task(8))
        );
        assert_eq!(hit(nav + 30.0, 800, 10, usize::MAX, &style), None);
    }

    #[test]
    fn small_panels_and_unneeded_paging_do_not_expose_fake_controls() {
        let style = load("chrome").unwrap();
        assert!(task_view(&style, 180, 20, 0).is_none());
        let view = task_view(&style, 800, 2, 99).unwrap();
        assert_eq!((view.start, view.slots), (0, 2));
        assert!(!view.prev && !view.next);
    }

    #[test]
    fn denies_unknown_actions_and_oversized_recipes() {
        let sample = include_str!("../../../macrice/de/resources/recipes/classic.json");
        assert!(parse(&sample.replace("\"launcher\"", "\"exec-shell\""), None).is_err());
        assert!(parse(
            &sample.replace(
                "\"schema_version\": 1",
                "\"schema_version\": 1, \"exec\": \"payload\""
            ),
            None
        )
        .is_err());
        assert!(parse(&"x".repeat(65_537), None).is_err());
        assert!(load("relative.json").is_err());
    }

    #[test]
    fn v2_metrics_resize_real_widget_geometry_and_hit_testing() {
        let original = include_str!("../../../macrice/de/resources/recipes/classic.json");
        let v2 = original.replace("\"schema_version\": 1", "\"schema_version\": 2")
            .replace("\"height\": 36,",
                     "\"height\": 36, \"metrics\": {\"launcher_width\": 120, \"task_width\": 196, \"clock_width\": 80},");
        let style = parse(&v2, Some("classic")).unwrap();
        assert_eq!(style.widths, [120, 196, 80]);
        let placed = layout(&style, 800, 2);
        assert_eq!(
            placed
                .iter()
                .find(|item| item.widget == Widget::Launcher)
                .unwrap()
                .width,
            120
        );
        assert_eq!(
            placed
                .iter()
                .find(|item| item.widget == Widget::Tasks)
                .unwrap()
                .width,
            392
        );
        assert_eq!(hit(119.0, 800, 2, 0, &style), Some(Hit::Launcher));
        assert_eq!(hit(121.0, 800, 2, 0, &style), Some(Hit::Task(0)));
        assert_eq!(hit(320.0, 800, 2, 0, &style), Some(Hit::Task(1)));
        // Native power is a lower-priority indicator and cannot consume
        // another task slot; the newly enabled tray reserves fixed space.
        assert!(layout(&style, 800, 2).iter().any(|item| item.widget == Widget::Battery));
        assert_eq!(task_view(&style, 800, 10, 0).unwrap().slots, 2);
    }

    #[test]
    fn native_statuses_preserve_window_slots_and_have_no_fake_click_targets() {
        let style = load("classic").unwrap();
        let normal = layout(&style, 1024, 2);
        for widget in [Widget::Battery, Widget::Audio, Widget::Network] {
            let indicator = normal.iter().find(|item| item.widget == widget).unwrap();
            assert_eq!(indicator.width, 64);
            assert_eq!(hit(f64::from(indicator.x + 15), 1024, 2, 0, &style), None);
        }
        let overflow = layout(&style, 800, 20);
        let statuses: Vec<_> = overflow.iter().filter(|item| matches!(item.widget,
            Widget::Battery | Widget::Audio | Widget::Network)).collect();
        assert_eq!(statuses.len(), 2);
        assert_eq!(statuses.iter().map(|item| item.widget).collect::<Vec<_>>(),
                   vec![Widget::Audio, Widget::Battery]);
        assert_eq!(task_view(&style, 800, 20, 0).unwrap().slots, 2);
    }

    #[test]
    fn v2_requires_exact_bounded_metrics_and_v1_stays_strict() {
        let original = include_str!("../../../macrice/de/resources/recipes/classic.json");
        let v2_without_metrics = original.replace("\"schema_version\": 1", "\"schema_version\": 2");
        assert!(parse(&v2_without_metrics, None).is_err());
        let with_metrics = original.replace("\"height\": 36,",
            "\"height\": 36, \"metrics\": {\"launcher_width\": 120, \"task_width\": 196, \"clock_width\": 80},");
        assert!(parse(&with_metrics, None).is_err());
        let with_null = original.replace("\"height\": 36,", "\"height\": 36, \"metrics\": null,");
        assert!(parse(&with_null, None).is_err());
        let invalid = with_metrics
            .replace("\"schema_version\": 1", "\"schema_version\": 2")
            .replace("\"task_width\": 196", "\"task_width\": 1");
        assert!(parse(&invalid, None).is_err());
    }

    const NESTED: &str = include_str!("../../../tests/fixtures/riceplate-nested-v3.json");

    #[test]
    fn v3_nested_layout_changes_actual_native_geometry_and_hit_areas() {
        let style = parse(NESTED, Some("my-layout")).unwrap();
        assert!(style.top);
        assert_eq!(style.labels, vec!["Y2K"]);
        let placed = layout(&style, 800, 2);
        assert!(placed
            .iter()
            .any(|node| node.widget == Widget::Label(0) && node.x == 112));
        assert!(placed
            .iter()
            .any(|node| node.widget == Widget::Gap(20) && node.x == 160));
        let task = placed
            .iter()
            .find(|node| node.widget == Widget::Tasks)
            .unwrap();
        assert_eq!(task.x, 188);
        assert_eq!(hit(120.0, 800, 2, 0, &style), None);
        assert_eq!(hit(189.0, 800, 2, 0, &style), Some(Hit::Task(0)));
        assert_eq!(hit(705.0, 800, 2, 0, &style), Some(Hit::Clock));
    }

    #[test]
    fn v3_divider_is_bounded_visible_geometry_without_click_action() {
        let mut data: serde_json::Value = serde_json::from_str(NESTED).unwrap();
        data["panel"]["layout"]["start"].as_array_mut().unwrap()
            .push(serde_json::json!({"type": "divider", "width": 12}));
        let style = parse(&data.to_string(), None).unwrap();
        let divider = layout(&style, 1000, 1).into_iter()
            .find(|node| node.widget == Widget::Divider(12)).unwrap();
        assert_eq!(divider.width, 12);
        assert_eq!(hit(f64::from(divider.x + 5), 1000, 1, 0, &style), None);
        for bad in [serde_json::json!(5), serde_json::json!(33),
                    serde_json::json!(true)] {
            data["panel"]["layout"]["start"].as_array_mut().unwrap().last_mut().unwrap()
                ["width"] = bad;
            assert!(parse(&data.to_string(), None).is_err());
        }
    }

    #[test]
    fn v3_rejects_unknown_properties_executable_nodes_and_deep_groups() {
        let original: serde_json::Value = serde_json::from_str(NESTED).unwrap();
        let mut unsafe_label = original.clone();
        unsafe_label["panel"]["layout"]["start"][0]["children"][1]["text"] =
            serde_json::json!("<script>");
        assert!(parse(&unsafe_label.to_string(), None).is_err());
        let mut executable_gap = original.clone();
        executable_gap["panel"]["layout"]["start"][0]["children"][2]["exec"] =
            serde_json::json!("shell");
        assert!(parse(&executable_gap.to_string(), None).is_err());
        let mut unknown = original.clone();
        unknown["panel"]["layout"]["start"][0]["children"][2]["type"] = serde_json::json!("run");
        assert!(parse(&unknown.to_string(), None).is_err());
        let mut both = original.clone();
        both["panel"]["sections"] = serde_json::json!({"start":[],"center":[],"end":[]});
        assert!(parse(&both.to_string(), None).is_err());
        let child = r#"{"type":"widget","id":"launcher"}"#;
        let group = |inside: String| format!(r#"{{"type":"group","gap":0,"children":[{inside}]}}"#);
        let too_deep = group(group(group(child.to_string())));
        let mut deep = original;
        deep["panel"]["layout"]["start"] =
            serde_json::json!([serde_json::from_str::<serde_json::Value>(&too_deep).unwrap()]);
        assert!(parse(&deep.to_string(), None).is_err());
    }

    const SHELL_V4: &str = include_str!("../../../tests/fixtures/riceplate-shell-v4.json");

    #[test]
    fn v4_applies_live_compact_layout_and_visual_tokens() {
        let style = parse(SHELL_V4, Some("mockup-shell")).unwrap();
        assert_eq!(style.label_padding, 12);
        assert_eq!(style.task_radius, 6);
        let wide = layout(&style, 1200, 2);
        assert!(wide
            .iter()
            .any(|node| node.widget == Widget::Label(0) && node.x == 112));
        assert!(wide
            .iter()
            .any(|node| node.widget == Widget::Tasks && node.x == 196));
        let compact = layout(&style, 600, 2);
        assert!(!compact
            .iter()
            .any(|node| matches!(node.widget, Widget::Label(_))));
        assert!(compact
            .iter()
            .any(|node| node.widget == Widget::Tasks && node.x == 136));
        assert_eq!(hit(140.0, 600, 2, 0, &style), Some(Hit::Task(0)));
        assert_eq!(hit(140.0, 1200, 2, 0, &style), None);
    }

    #[test]
    fn v4_rejects_unknown_menu_actions_wallpaper_and_invalid_compact_nodes() {
        let base: serde_json::Value = serde_json::from_str(SHELL_V4).unwrap();
        let mut action = base.clone();
        action["menu"]["groups"][0]["actions"][0] = serde_json::json!("exec-anything");
        assert!(parse(&action.to_string(), None).is_err());
        let mut wallpaper = base.clone();
        wallpaper["desktop"]["wallpaper"] = serde_json::json!("/etc/passwd");
        assert!(parse(&wallpaper.to_string(), None).is_err());
        let mut compact = base.clone();
        compact["responsive"]["compact_layout"]["start"][0]["id"] =
            serde_json::json!("unknown-action");
        assert!(parse(&compact.to_string(), None).is_err());
        let mut extra = base;
        extra["desktop"]["script"] = serde_json::json!("payload");
        assert!(parse(&extra.to_string(), None).is_err());
    }

    #[test]
    fn v6_accepts_only_bounded_content_addressed_png_ids() {
        let fixture = include_str!("../../../tests/fixtures/riceplate-desktop-v5.json");
        let mut data: serde_json::Value = serde_json::from_str(fixture).unwrap();
        data["schema_version"] = serde_json::json!(6);
        data["desktop"]["wallpaper"] = serde_json::json!(format!("asset-{}", "a".repeat(64)));
        assert!(parse(&data.to_string(), Some("mockup-desktop")).is_ok());
        data["schema_version"] = serde_json::json!(5);
        assert!(parse(&data.to_string(), None).is_err());
        data["schema_version"] = serde_json::json!(6);
        data["desktop"]["wallpaper"] = serde_json::json!("asset-../../secrets.png");
        assert!(parse(&data.to_string(), None).is_err());
        data["desktop"]["wallpaper"] = serde_json::json!(format!("asset-{}", "A".repeat(64)));
        assert!(parse(&data.to_string(), None).is_err());
    }
}
