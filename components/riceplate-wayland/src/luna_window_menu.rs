//! XP Luna task-button context menu policy.
//! Only real foreign-toplevel windows are exposed. The popup is local to
//! RicePlate and reuses its existing Wayland popup, not application SNI menus.
use crate::{draw_text, fill_rect, tray};

pub const WINDOW_BASE: i32 = 6_000;
pub const SWITCH_NEXT: i32 = 6_100;
pub const RESTORE: i32 = 6_101;
pub const MINIMIZE: i32 = 6_102;
pub const MAXIMIZE: i32 = 6_103;
pub const CLOSE: i32 = 6_104;
pub const RESTORE_ALL: i32 = 6_105;
pub const MINIMIZE_ALL: i32 = 6_106;
pub const CLOSE_ALL: i32 = 6_107;
pub const MAX_WINDOW_ROWS: usize = 20;

#[derive(Clone, Copy)]
pub struct Window<'a> {
    pub title: &'a str,
    pub app_id: &'a str,
    pub active: bool,
    pub minimized: bool,
    pub maximized: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Action {
    Activate(usize),
    NextWindow,
    Restore,
    Minimize,
    Maximize,
    Close,
    RestoreAll,
    MinimizeAll,
    CloseAll,
}

pub fn decode(id: i32, window_count: usize) -> Option<Action> {
    if let Some(index) = id.checked_sub(WINDOW_BASE) {
        if (0..MAX_WINDOW_ROWS as i32).contains(&index)
            && (index as usize) < window_count {
            return Some(Action::Activate(index as usize));
        }
    }
    Some(match id {
        SWITCH_NEXT if window_count > 1 => Action::NextWindow,
        RESTORE if window_count == 1 => Action::Restore,
        MINIMIZE if window_count == 1 => Action::Minimize,
        MAXIMIZE if window_count == 1 => Action::Maximize,
        CLOSE if window_count == 1 => Action::Close,
        RESTORE_ALL if window_count > 1 => Action::RestoreAll,
        MINIMIZE_ALL if window_count > 1 => Action::MinimizeAll,
        CLOSE_ALL if window_count > 1 => Action::CloseAll,
        _ => return None,
    })
}

/// Foreign-toplevel titles are application-controlled. Sanitize before
/// truncating so leading control characters cannot consume the text budget.
/// The popup has more room than a task button; keep distinct document names
/// visible instead of reusing the taskbar's 18-character label limit.
fn title_label(title: &str, app_id: &str) -> String {
    let clean = |value: &str| -> String {
        // Foreign-toplevel titles are owned by applications, not RicePlate.
        // Ignore Unicode bidirectional formatting and invisible direction
        // marks as well as terminal controls, which could spoof menu labels.
        value.chars().filter(|ch| {
            !ch.is_control() && !matches!(*ch,
                '\u{061c}' | '\u{200e}' | '\u{200f}' |
                '\u{202a}'..='\u{202e}' | '\u{2066}'..='\u{2069}')
        }).take(28).collect::<String>().trim().to_owned()
    };
    let name = clean(title);
    if !name.is_empty() { return name; }
    let app = clean(app_id);
    if !app.is_empty() { app } else { "Window".to_owned() }
}

fn separator() -> tray::MenuRow {
    tray::MenuRow { id: 0, label: String::new(), enabled: false, kind: tray::MenuKind::Separator }
}

fn item(id: i32, label: &str, enabled: bool, checked: bool) -> tray::MenuRow {
    tray::MenuRow {
        id,
        label: label.to_owned(),
        enabled,
        kind: tray::MenuKind::Action { checked, radio: false },
    }
}

/// No user-supplied command strings are ever placed in local popup actions.
/// Long groups retain access to every window through "Next window" and group
/// operations, while menu painting remains bounded.
pub fn entries(windows: &[Window<'_>]) -> Option<(String, Vec<tray::MenuRow>)> {
    let first = windows.first()?;
    let title = if windows.len() == 1 {
        title_label(first.title, first.app_id)
    } else {
        format!("{} windows", windows.len())
    };
    let mut rows = Vec::with_capacity(MAX_WINDOW_ROWS + 6);
    if windows.len() == 1 {
        rows.push(item(RESTORE, "Restore", first.minimized || first.maximized, false));
        rows.push(item(MINIMIZE, "Minimize", !first.minimized, false));
        rows.push(item(MAXIMIZE, "Maximize", !first.maximized, false));
        rows.push(separator());
        rows.push(item(CLOSE, "Close", true, false));
    } else {
        for (index, window) in windows.iter().take(MAX_WINDOW_ROWS).enumerate() {
            let label = title_label(window.title, window.app_id);
            rows.push(item(WINDOW_BASE + index as i32, &label, true, window.active));
        }
        if windows.len() > MAX_WINDOW_ROWS {
            rows.push(item(0, "More: use Next window", false, false));
        }
        rows.push(separator());
        rows.push(item(SWITCH_NEXT, "Next window", true, false));
        rows.push(item(RESTORE_ALL, "Restore all",
                       windows.iter().any(|w| w.minimized || w.maximized), false));
        rows.push(item(MINIMIZE_ALL, "Minimize all", windows.iter().any(|w| !w.minimized), false));
        rows.push(item(CLOSE_ALL, "Close group", true, false));
    }
    Some((title, rows))
}

// The shared SNI surface remains 288x240; only task-owned menu pixels and
// input are compact. No extra Wayland surface, worker, or status-notifier hook.
pub const ROW_HEIGHT: u32 = 24;
pub const PADDING: u32 = 6;
pub const FOOTER_HEIGHT: u32 = 25;
const GUTTER: u32 = 31;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Bounds {
    pub top: u32,
    pub height: u32,
}

/// The bottom taskbar's menu hugs its upper edge; top panels grow downward.
pub fn bounds(total: usize, first: usize, top_panel: bool) -> Bounds {
    // Keep a fixed frame while paging a group. Otherwise the bottom-aligned
    // painted rows move underneath the compositor's already-installed input
    // region whenever the last page contains fewer windows.
    let paged = total > tray::POPUP_ROWS;
    let visible = if paged { tray::POPUP_ROWS as u32 }
                  else { total.saturating_sub(first) as u32 };
    let footer = if paged { FOOTER_HEIGHT } else { 0 };
    let height = (2 * PADDING + visible * ROW_HEIGHT + footer)
        .min(tray::POPUP_HEIGHT);
    Bounds { top: if top_panel { 0 } else { tray::POPUP_HEIGHT - height }, height }
}

pub fn menu_hit(popup: &tray::MenuPopup, x: f64, y: f64, top_panel: bool)
    -> Option<tray::MenuHit>
{
    let region = bounds(popup.rows().len(), popup.first, top_panel);
    if !x.is_finite() || !y.is_finite() || x < 0.0 || y < f64::from(region.top)
        || x >= f64::from(tray::POPUP_WIDTH)
        || y >= f64::from(region.top + region.height) { return None; }
    let local_y = y as u32 - region.top;
    if local_y < PADDING { return None; }
    let total = popup.rows().len();
    let visible = if total > tray::POPUP_ROWS { tray::POPUP_ROWS }
                  else { total.saturating_sub(popup.first) };
    let row_end = PADDING + visible as u32 * ROW_HEIGHT;
    if local_y < row_end {
        let index = popup.first + ((local_y - PADDING) / ROW_HEIGHT) as usize;
        return popup.rows().get(index)
            .filter(|row| row.selectable()).map(|_| tray::MenuHit::Row(index));
    }
    if popup.rows().len() > tray::POPUP_ROWS && local_y < row_end + FOOTER_HEIGHT {
        return if x < f64::from(tray::POPUP_WIDTH / 2) {
            (popup.first > 0).then_some(tray::MenuHit::Previous)
        } else {
            (popup.first + tray::POPUP_ROWS < popup.rows().len())
                .then_some(tray::MenuHit::Next)
        };
    }
    None
}

/// Compact XP-like bevel, shaded icon gutter, navy keyboard selection and
/// explicit disabled/separator states. Outside pixels are transparent rather
/// than a misleading, full-size SNI window with a blue title bar.
pub fn paint(canvas: &mut [u8], popup: &tray::MenuPopup, top_panel: bool) {
    let width = tray::POPUP_WIDTH;
    let height = tray::POPUP_HEIGHT;
    canvas.fill(0);
    let rect = bounds(popup.rows().len(), popup.first, top_panel);
    if rect.height == 0 { return; }
    let y = rect.top;
    // 2 px ambient shadow stays inside the fixed surface.
    fill_rect(canvas, width, height, 2, y + 2,
              width - 2, rect.height.saturating_sub(2), 0xff85_8790);
    fill_rect(canvas, width, height, 0, y,
              width - 3, rect.height.saturating_sub(3), 0xff42_4250);
    fill_rect(canvas, width, height, 1, y + 1,
              width - 5, rect.height.saturating_sub(5), 0xfffc_fbf6);
    fill_rect(canvas, width, height, 2, y + 2,
              GUTTER - 2, rect.height.saturating_sub(7), 0xffed_eae0);
    fill_rect(canvas, width, height, 1, y + 1, width - 5, 1, 0xffff_ffff);
    fill_rect(canvas, width, height, GUTTER, y + 2, 1,
              rect.height.saturating_sub(7), 0xffd1_cfc7);
    let rows = popup.rows();
    for (offset, row) in rows.iter().enumerate().skip(popup.first).take(tray::POPUP_ROWS) {
        let local = offset - popup.first;
        let row_y = y + PADDING + local as u32 * ROW_HEIGHT;
        if matches!(&row.kind, tray::MenuKind::Separator) {
            fill_rect(canvas, width, height, GUTTER + 3, row_y + ROW_HEIGHT / 2,
                      width - GUTTER - 12, 1, 0xffbb_b9b5);
            fill_rect(canvas, width, height, GUTTER + 3, row_y + ROW_HEIGHT / 2 + 1,
                      width - GUTTER - 12, 1, 0xffff_ffff);
            continue;
        }
        let selected = offset == popup.selected && row.selectable();
        if selected {
            fill_rect(canvas, width, height, GUTTER + 2, row_y + 1,
                      width - GUTTER - 8, ROW_HEIGHT - 2, 0xff18_3a94);
        }
        // Small original native window icon, not an imported XP system asset.
        if row.id >= WINDOW_BASE && row.id < SWITCH_NEXT {
            fill_rect(canvas, width, height, 9, row_y + 6, 13, 11, 0xff28_4c96);
            fill_rect(canvas, width, height, 10, row_y + 7, 11, 2, 0xff8b_c8ef);
            fill_rect(canvas, width, height, 11, row_y + 10, 9, 5, 0xfffc_fbf6);
            if matches!(&row.kind, tray::MenuKind::Action { checked: true, .. }) {
                // Active member is visible even when keyboard focus is on
                // a different row in this group.
                fill_rect(canvas, width, height, 23, row_y + 10, 4, 5, 0xff25_8f36);
            }
        } else if row.id == CLOSE || row.id == CLOSE_ALL {
            draw_text(canvas, width, height, 12, row_y + 8, "x", 0xffab_3636);
        } else if row.id == MINIMIZE || row.id == MINIMIZE_ALL {
            fill_rect(canvas, width, height, 11, row_y + 15, 10, 2, 0xff47_6080);
        } else if row.id == RESTORE || row.id == MAXIMIZE ||
                  row.id == RESTORE_ALL {
            fill_rect(canvas, width, height, 11, row_y + 7, 11, 10, 0xff36_5184);
            fill_rect(canvas, width, height, 12, row_y + 9, 9, 7, 0xfff7_f7ee);
        }
        let color = if !row.enabled { 0xff99_9894 }
            else if selected { 0xffff_ffff } else { 0xff1c_1c1c };
        // Titles are already bounded by task_groups::task_label, and actions
        // are fixed English strings; never render controls from raw app text.
        draw_text(canvas, width, height, GUTTER + 9, row_y + 8,
                  &row.label.chars().take(30).collect::<String>(), color);
    }
    if rows.len() > tray::POPUP_ROWS {
        let footer_y = y + PADDING + ROW_HEIGHT * tray::POPUP_ROWS as u32;
        fill_rect(canvas, width, height, GUTTER + 2, footer_y,
                  width - GUTTER - 8, 1, 0xffbb_b9b5);
        draw_text(canvas, width, height, 40, footer_y + 9, "< Previous",
                  if popup.first > 0 { 0xff18_3a94 } else { 0xff99_9894 });
        draw_text(canvas, width, height, width - 89, footer_y + 9, "Next >",
                  if popup.first + tray::POPUP_ROWS < rows.len() {
                      0xff18_3a94
                  } else { 0xff99_9894 });
    }
}

/// A right-anchored layer-shell popup is positioned alongside the clicked
/// task, clamped to the visible panel; it never crosses to another output.
pub fn right_margin(panel_width: u32, click_x: f64) -> i32 {
    const EDGE: u32 = 8;
    let desired = if click_x.is_finite() {
        click_x.max(0.0).min(f64::from(panel_width)) as u32
    } else {
        EDGE
    };
    let max_left = panel_width.saturating_sub(tray::POPUP_WIDTH + EDGE).max(EDGE);
    let left = desired.clamp(EDGE, max_left);
    panel_width.saturating_sub(left + tray::POPUP_WIDTH).max(EDGE) as i32
}

#[cfg(test)]
mod tests {
    use super::*;
    fn w(title: &'static str, active: bool, minimized: bool) -> Window<'static> {
        Window { title, app_id: "org.example.Editor", active, minimized, maximized: false }
    }

    #[test]
    fn singleton_menu_has_live_window_actions_and_no_fake_sni_commands() {
        let (title, rows) = entries(&[w("Document", true, false)]).unwrap();
        assert_eq!(title, "Document");
        assert_eq!(rows.iter().map(|row| row.id).collect::<Vec<_>>(),
                   [RESTORE, MINIMIZE, MAXIMIZE, 0, CLOSE]);
        assert!(!rows[0].enabled);
        assert!(matches!(&rows[3].kind, tray::MenuKind::Separator));
        assert!(rows[1].enabled);
        assert_eq!(decode(CLOSE, 1), Some(Action::Close));
        assert_eq!(decode(CLOSE_ALL, 1), None);
        let (_, minimized) = entries(&[w("Draft", false, true)]).unwrap();
        assert!(minimized[0].enabled);
        assert!(!minimized[1].enabled);
        assert!(entries(&[]).is_none());
        let maximized = [Window { maximized: true, ..w("Full screen", true, false) }];
        let (_, rows) = entries(&maximized).unwrap();
        assert!(rows[0].enabled, "maximized windows must offer Restore");
        assert!(!rows[2].enabled, "already-maximized windows cannot Maximize again");
    }

    #[test]
    fn groups_include_real_titles_count_and_bounded_fallback_navigation() {
        let windows = [w("First", false, false), w("Second", true, true)];
        let (title, rows) = entries(&windows).unwrap();
        assert_eq!(title, "2 windows");
        assert_eq!(rows[0].label, "First");
        assert_eq!(rows[1].label, "Second");
        assert!(matches!(&rows[1].kind, tray::MenuKind::Action { checked: true, .. }));
        assert_eq!(decode(rows[1].id, 2), Some(Action::Activate(1)));
        assert_eq!(decode(SWITCH_NEXT, 2), Some(Action::NextWindow));
        assert_eq!(decode(RESTORE_ALL, 2), Some(Action::RestoreAll));
        assert_eq!(decode(MINIMIZE_ALL, 2), Some(Action::MinimizeAll));
        assert_eq!(decode(CLOSE_ALL, 2), Some(Action::CloseAll));
        assert_eq!(decode(WINDOW_BASE + 5, 2), None);
        assert_eq!(title_label("A\nB\rC", ""), "ABC");

        let many = vec![w("Window", false, false); 128];
        let (_, rows) = entries(&many).unwrap();
        assert_eq!(rows.len(), MAX_WINDOW_ROWS + 6);
        assert!(!rows[MAX_WINDOW_ROWS].enabled, "More hint must be disabled");
        assert!(matches!(&rows[MAX_WINDOW_ROWS + 1].kind, tray::MenuKind::Separator));
        assert_eq!(decode(WINDOW_BASE + 21, 128), None);
        assert_eq!(decode(SWITCH_NEXT, 128), Some(Action::NextWindow));
    }

    #[test]
    fn untrusted_window_titles_preserve_distinct_names_without_controls() {
        assert_eq!(title_label("\n\r\tA long document title · Draft 2", ""),
                   "A long document title · Draf");
        assert_eq!(title_label("\u{0001}\u{0002}Hello", "fallback"), "Hello");
        assert_eq!(title_label("\n\r", "org.example.Editor"), "org.example.Editor");
        assert_eq!(title_label("", ""), "Window");
        assert_eq!(title_label("One", "ignored"), "One");
        // Directional isolates/overrides are formatting controls, even
        // though Rust char::is_control() does not classify them as such.
        assert_eq!(title_label("invoice\u{202e}cod.exe\u{202c}", ""), "invoicecod.exe");
        assert_eq!(title_label("\u{2066}Report\u{2069}", ""), "Report");
        assert_eq!(title_label("\u{200e}\u{061c}", "org.example.Editor"),
                   "org.example.Editor");
    }

    #[test]
    fn compact_menu_hit_testing_ignores_separators_and_blank_surface() {
        let (_, rows) = entries(&[w("Document", true, false)]).unwrap();
        let mut popup = tray::MenuPopup::default();
        assert!(popup.open_local("Document", rows));
        let b = bounds(popup.rows().len(), popup.first, false);
        assert_eq!(b.height, 132);
        assert_eq!(b.top, 108);
        assert_eq!(menu_hit(&popup, 48.0, f64::from(b.top + PADDING + ROW_HEIGHT + 4), false),
                   Some(tray::MenuHit::Row(1)));
        assert_eq!(menu_hit(&popup, 48.0, f64::from(b.top + PADDING + ROW_HEIGHT * 3 + 3), false),
                   None);
        assert_eq!(menu_hit(&popup, 48.0, 70.0, false), None);
        assert_eq!(menu_hit(&popup, f64::NAN, 130.0, false), None);
        assert_eq!(bounds(5, 0, true).top, 0);
    }

    #[test]
    fn compact_menu_raster_is_transparent_above_the_bottom_panel_menu() {
        let (_, rows) = entries(&[w("Document", true, false)]).unwrap();
        let mut popup = tray::MenuPopup::default();
        popup.open_local("Document", rows);
        let mut pixels = vec![0u8; (tray::POPUP_WIDTH * tray::POPUP_HEIGHT * 4) as usize];
        paint(&mut pixels, &popup, false);
        assert_eq!(&pixels[..4], &[0, 0, 0, 0]);
        let position = (((tray::POPUP_HEIGHT - 12) * tray::POPUP_WIDTH + 20) * 4) as usize;
        assert_ne!(&pixels[position..position + 4], &[0, 0, 0, 0]);
        let before = pixels.clone();
        popup.select(1);
        paint(&mut pixels, &popup, false);
        assert_ne!(before, pixels, "keyboard selection must visibly move");
    }

    #[test]
    fn active_group_member_has_a_visual_marker_independent_of_keyboard_focus() {
        let windows = [w("First", false, false), w("Second", true, false)];
        let (_, checked) = entries(&windows).unwrap();
        let mut popup = tray::MenuPopup::default();
        assert!(popup.open_local("2 windows", checked));
        let mut selected_frame = vec![0; (tray::POPUP_WIDTH * tray::POPUP_HEIGHT * 4) as usize];
        paint(&mut selected_frame, &popup, true);
        let y = PADDING + ROW_HEIGHT + 12;
        let index = ((y * tray::POPUP_WIDTH + 25) * 4) as usize;
        assert_eq!(&selected_frame[index..index + 4], &0xff25_8f36_u32.to_le_bytes());
        let mut unchecked = windows;
        unchecked[1].active = false;
        let (_, rows) = entries(&unchecked).unwrap();
        assert!(popup.open_local("2 windows", rows));
        let mut idle_frame = selected_frame.clone();
        paint(&mut idle_frame, &popup, true);
        assert_ne!(selected_frame, idle_frame);
    }

    #[test]
    fn grouped_window_paging_only_hits_real_enabled_rows() {
        let windows = vec![w("Example", false, false); 15];
        let (_, rows) = entries(&windows).unwrap();
        let mut popup = tray::MenuPopup::default();
        assert!(popup.open_local("15 windows", rows));
        let b = bounds(popup.rows().len(), popup.first, true);
        assert_eq!(b.height, 157);
        assert_eq!(menu_hit(&popup, 258.0, f64::from(b.top + PADDING +
                   tray::POPUP_ROWS as u32 * ROW_HEIGHT + 9), true), Some(tray::MenuHit::Next));
        assert_eq!(menu_hit(&popup, 24.0, f64::from(b.top + PADDING +
                   tray::POPUP_ROWS as u32 * ROW_HEIGHT + 9), true), None);
        popup.page(1);
        assert_eq!(bounds(popup.rows().len(), popup.first, true), b,
                   "page transitions must retain the same input geometry");
        assert_eq!(menu_hit(&popup, 24.0, f64::from(b.top + PADDING +
                   tray::POPUP_ROWS as u32 * ROW_HEIGHT + 9), true),
                   Some(tray::MenuHit::Previous));
    }

    #[test]
    fn right_anchored_popup_tracks_pointer_and_clamps_on_both_edges() {
        assert_eq!(right_margin(1024, 100.0), 636);
        assert_eq!(right_margin(1024, 999.0), 8);
        assert_eq!(right_margin(1024, -40.0), 728);
        assert_eq!(right_margin(320, f64::NAN), 24);
        assert_eq!(right_margin(320, f64::INFINITY), 24);
    }
}
