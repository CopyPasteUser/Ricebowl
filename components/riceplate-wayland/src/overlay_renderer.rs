//! Native notifications and calendar rendering shared by all recipes.
//!
//! Pure painters: the event loop owns the state and input, while these
//! routines consume bounded immutable snapshots. No new notification host.

use crate::{
    calendar::{self, CalendarState},
    native_menu,
    raster::{fill_rect, fill_rounded_rect},
    recipe::PanelStyle,
    ricepop::{self, State as NotificationState},
    ricepop_text as text,
    text_render::{draw_auxiliary_text, draw_text, text_pixel_width},
};
use chrono::Datelike;

fn notification_glyphs(value: &str, limit: usize) -> String {
    value
        .chars()
        .map(|c| if c.is_control() { ' ' } else { c })
        .take(limit)
        .collect()
}

/// The notification center uses the same owner-private font as the rest of
/// RicePlate. Only the opt-in font path needs a cell-aware width limit; the
/// default path delegates unchanged to the legacy bitmap painter.
pub(crate) fn draw_notification_text(
    canvas: &mut [u8],
    width: u32,
    height: u32,
    x: u32,
    y: u32,
    label: &str,
    color: u32,
    style: &PanelStyle,
) {
    if style
        .native_art
        .as_ref()
        .and_then(|art| art.font.as_ref())
        .is_none()
    {
        draw_text(canvas, width, height, x, y, label, color);
        return;
    }
    let available = width.saturating_sub(x).saturating_sub(8) / (8 * style.font_scale.max(1));
    if available == 0 {
        return;
    }
    let length = label.chars().count();
    let mut shown: String = if length <= available as usize {
        label.to_owned()
    } else {
        let mut clipped: String = label
            .chars()
            .take(available.saturating_sub(1) as usize)
            .collect();
        clipped.push('…');
        clipped
    };
    // The character budget above assumes one 8px cell per scalar. Wide
    // scripts (CJK) have far larger measured advances and would run off the
    // popup, hiding their tail without any marker, so fit the real painted
    // advance with the same font that draws the text.
    if let Some(font) = style.native_art.as_ref().and_then(|art| art.font.as_ref()) {
        let pixels = width.saturating_sub(x).saturating_sub(8);
        if font.measure_text(&shown) > pixels {
            let source = label.trim_end_matches('…');
            let end = font.fitting_prefix_end(source, pixels, '…');
            shown = format!("{}…", &source[..end]);
        }
    }
    draw_auxiliary_text(canvas, width, height, x, y, &shown, color, style);
}

pub(crate) fn paint_compact_notifications(
    canvas: &mut [u8],
    style: &PanelStyle,
    state: &NotificationState,
    size: (u32, u32),
) {
    let (width, height) = size;
    let language = state.language;
    let text_width = state.compact_text_width(width);
    // All existing coordinates, colors and font pixels remain identical for
    // bundled rices. Only opted-in private fonts use the bounded glyph path.
    let draw_text =
        |canvas: &mut [u8], width: u32, height: u32, x: u32, y: u32, label: &str, color: u32| {
            draw_notification_text(canvas, width, height, x, y, label, color, style);
        };
    let large_font = style
        .native_art
        .as_ref()
        .and_then(|art| art.font.as_ref())
        .is_some()
        && style.font_scale > 1;
    for pixel in canvas.chunks_exact_mut(4) {
        pixel.copy_from_slice(&style.background.to_le_bytes());
    }
    fill_rect(canvas, width, height, 0, 0, width, 28, style.active);
    draw_text(
        canvas,
        width,
        height,
        8,
        10,
        text::title(language, large_font),
        style.foreground,
    );
    if !state.sync_error {
        if let Some((first, last, total)) = state.list_page_status(Some(size)) {
            let rows = ricepop::compact_rows(size);
            let label = if large_font {
                format!("{}/{}", (first - 1) / rows + 1, total.div_ceil(rows))
            } else {
                format!("{first}-{last}/{total}")
            };
            let cell = if large_font { 8 * style.font_scale } else { 8 };
            let x = width.saturating_sub(label.len() as u32 * cell + 8);
            draw_text(canvas, width, height, x, 10, &label, style.foreground);
        }
    }
    if state.sync_error {
        let status = text::offline(language, large_font || width < 232);
        let cell = if large_font { 8 * style.font_scale } else { 8 };
        draw_text(
            canvas,
            width,
            height,
            width.saturating_sub(status.len() as u32 * cell + 4),
            10,
            status,
            style.foreground,
        );
    }
    let footer = height - ricepop::COMPACT_FOOTER_HEIGHT;
    fill_rect(canvas, width, height, 0, footer, width, 1, style.foreground);
    draw_text(
        canvas,
        width,
        height,
        8,
        footer + 9,
        text::compact_footer_back(language, large_font, width),
        style.foreground,
    );
    draw_text(
        canvas,
        width,
        height,
        width / 3 + 4,
        footer + 9,
        text::compact_footer_retry(language, large_font),
        style.foreground,
    );
    if state.selected_id().is_some() {
        draw_text(
            canvas,
            width,
            height,
            width * 2 / 3 + 4,
            footer + 9,
            text::compact_footer_dismiss(language),
            style.foreground,
        );
    }
    if state.loading || state.error.is_some() {
        draw_text(
            canvas,
            width,
            height,
            8,
            76,
            state.error.map_or(text::loading(language), |error| {
                text::error(language, error)
            }),
            style.foreground,
        );
        return;
    }
    if state.detail_id.is_none() {
        fill_rounded_rect(
            canvas,
            width,
            height,
            if state.show_history { width / 2 } else { 0 },
            30,
            width / 2,
            34,
            style.task_radius,
            style.active,
        );
        draw_text(
            canvas,
            width,
            height,
            8,
            43,
            &text::compact_tab_active(language, large_font, state.notices.len()),
            style.foreground,
        );
        draw_text(
            canvas,
            width,
            height,
            width / 2 + 8,
            43,
            &text::compact_tab_past(language, large_font, state.history.len()),
            style.foreground,
        );
        if state.visible_notices().is_empty() {
            draw_text(
                canvas,
                width,
                height,
                8,
                76,
                text::empty(language, state.show_history),
                style.foreground,
            );
        } else {
            for (row, notice) in state
                .visible_notices()
                .iter()
                .skip(state.compact_first_row(size))
                .take(ricepop::compact_rows(size))
                .enumerate()
            {
                let index = state.compact_first_row(size) + row;
                let y = ricepop::COMPACT_ROW_TOP + row as u32 * ricepop::COMPACT_ROW_HEIGHT;
                if index == state.selected {
                    fill_rounded_rect(
                        canvas,
                        width,
                        height,
                        4,
                        y,
                        width - 8,
                        ricepop::COMPACT_ROW_HEIGHT - 2,
                        style.task_radius,
                        style.active,
                    );
                }
                let summary = if notice.summary.is_empty() {
                    text::untitled(language)
                } else {
                    &notice.summary
                };
                draw_text(
                    canvas,
                    width,
                    height,
                    10,
                    y + 5,
                    &notification_glyphs(summary, text_width.saturating_sub(1)),
                    style.foreground,
                );
                draw_text(
                    canvas,
                    width,
                    height,
                    10,
                    y + 19,
                    &notification_glyphs(&notice.app_name, text_width.saturating_sub(1)),
                    style.foreground,
                );
            }
        }
    } else if let Some(notice) = state.detail_notice() {
        draw_text(
            canvas,
            width,
            height,
            8,
            36,
            &notification_glyphs(&notice.summary, text_width),
            style.foreground,
        );
        let pages = state.compact_body_page_count(size);
        let page_label = format!("{}/{}", state.body_page + 1, pages);
        let source_width = if pages <= 1 {
            text_width
        } else if large_font {
            text_width.saturating_sub(page_label.chars().count() + 1)
        } else {
            text_width.saturating_sub(8)
        };
        draw_text(
            canvas,
            width,
            height,
            8,
            53,
            &notification_glyphs(&notice.app_name, source_width),
            style.foreground,
        );
        if pages > 1 {
            if large_font {
                let digits = page_label.chars().count() as u32;
                let x = width.saturating_sub(digits.saturating_mul(8 * style.font_scale) + 8);
                draw_text(canvas, width, height, x, 53, &page_label, style.foreground);
            } else {
                draw_text(
                    canvas,
                    width,
                    height,
                    width.saturating_sub(68),
                    53,
                    &format!("{}/{} < >", state.body_page + 1, pages),
                    style.foreground,
                );
            }
        }
        let body = ricepop::body_lines_with_width(&notice.body, text_width);
        for (row, line) in body
            .iter()
            .skip(state.body_page * ricepop::compact_body_rows(height))
            .take(ricepop::compact_body_rows(height))
            .enumerate()
        {
            draw_text(
                canvas,
                width,
                height,
                8,
                73 + row as u32 * 15,
                line,
                style.foreground,
            );
        }
        if !state.show_history && !notice.actions.is_empty() {
            let top = ricepop::compact_action_top(height);
            for (row, action) in notice
                .actions
                .iter()
                .skip(state.compact_first_action_row(size))
                .take(ricepop::compact_action_rows(size))
                .enumerate()
            {
                let index = state.compact_first_action_row(size) + row;
                let y = top + row as u32 * ricepop::COMPACT_ACTION_HEIGHT;
                if index == state.selected_action {
                    fill_rounded_rect(
                        canvas,
                        width,
                        height,
                        4,
                        y,
                        width - 8,
                        ricepop::COMPACT_ACTION_HEIGHT - 2,
                        style.task_radius,
                        style.active,
                    );
                }
                draw_text(
                    canvas,
                    width,
                    height,
                    10,
                    y + 9,
                    &notification_glyphs(&action.label, text_width.saturating_sub(1)),
                    style.foreground,
                );
            }
        }
    }
}

pub(crate) fn paint_notifications(
    canvas: &mut [u8],
    style: &PanelStyle,
    state: &NotificationState,
) {
    let width = native_menu::WIDTH;
    let height = native_menu::HEIGHT;
    let language = state.language;
    let draw_text =
        |canvas: &mut [u8], width: u32, height: u32, x: u32, y: u32, label: &str, color: u32| {
            draw_notification_text(canvas, width, height, x, y, label, color, style);
        };
    let large_font = style
        .native_art
        .as_ref()
        .and_then(|art| art.font.as_ref())
        .is_some()
        && style.font_scale > 1;
    for pixel in canvas.chunks_exact_mut(4) {
        pixel.copy_from_slice(&style.background.to_le_bytes());
    }
    fill_rect(canvas, width, height, 0, 0, width, 38, style.active);
    draw_text(
        canvas,
        width,
        height,
        14,
        15,
        text::title(language, false),
        style.foreground,
    );
    if !state.sync_error {
        if let Some((first, last, total)) = state.list_page_status(None) {
            let label = if large_font {
                format!(
                    "{}/{}",
                    (first - 1) / ricepop::VISIBLE_ROWS + 1,
                    total.div_ceil(ricepop::VISIBLE_ROWS)
                )
            } else {
                format!("{first}-{last}/{total}")
            };
            let cell = if large_font { 8 * style.font_scale } else { 8 };
            let x = width.saturating_sub(label.len() as u32 * cell + 8);
            draw_text(canvas, width, height, x, 15, &label, style.foreground);
        }
    }
    if state.sync_error {
        draw_text(
            canvas,
            width,
            height,
            if large_font { 264 } else { 250 },
            15,
            text::offline(language, large_font),
            style.foreground,
        );
    }
    if state.detail_id.is_none() {
        let selected_tab_x = if state.show_history { 164 } else { 4 };
        fill_rounded_rect(
            canvas,
            width,
            height,
            selected_tab_x,
            41,
            152,
            42,
            style.task_radius,
            style.active,
        );
        draw_text(
            canvas,
            width,
            height,
            14,
            54,
            &text::tab_active(language, state.notices.len()),
            style.foreground,
        );
        draw_text(
            canvas,
            width,
            height,
            174,
            54,
            &text::tab_past(language, state.history.len()),
            style.foreground,
        );
    }
    if state.loading {
        draw_text(
            canvas,
            width,
            height,
            14,
            120,
            text::loading(language),
            style.foreground,
        );
    } else if let Some(error) = state.error {
        draw_text(
            canvas,
            width,
            height,
            14,
            120,
            text::error(language, error),
            style.foreground,
        );
        draw_text(
            canvas,
            width,
            height,
            14,
            145,
            text::retry_hint(language),
            style.foreground,
        );
    } else if let Some(notice) = state.detail_notice() {
        let source = if notice.app_name.is_empty() {
            text::unknown_app(language)
        } else {
            &notice.app_name
        };
        draw_text(
            canvas,
            width,
            height,
            14,
            49,
            &notification_glyphs(&format!("{source} / {}", notice.urgency), 37),
            style.foreground,
        );
        draw_text(
            canvas,
            width,
            height,
            14,
            72,
            &notification_glyphs(&notice.summary, 36),
            style.foreground,
        );
        let lines = state.body_text_lines(&notice.body);
        let pages = state.body_page_count();
        if pages > 1 {
            draw_text(
                canvas,
                width,
                height,
                195,
                87,
                &if large_font {
                    format!("{}/{}", state.body_page + 1, pages)
                } else {
                    text::text_pages(state.body_page + 1, pages)
                },
                style.foreground,
            );
        }
        for (row, line) in lines
            .iter()
            .skip(state.body_page * ricepop::BODY_LINES_PER_PAGE)
            .take(ricepop::BODY_LINES_PER_PAGE)
            .enumerate()
        {
            draw_text(
                canvas,
                width,
                height,
                14,
                103 + row as u32 * 16,
                &notification_glyphs(line, ricepop::BODY_WIDTH),
                style.foreground,
            );
        }
        if notice.actions.is_empty() || state.show_history {
            draw_text(
                canvas,
                width,
                height,
                14,
                180,
                text::no_actions(language),
                style.foreground,
            );
        } else {
            draw_text(
                canvas,
                width,
                height,
                14,
                138,
                &text::actions_header(language, large_font, notice.actions.len()),
                style.foreground,
            );
            for (position, action) in notice
                .actions
                .iter()
                .skip(state.first_action_row())
                .take(ricepop::VISIBLE_ROWS)
                .enumerate()
            {
                let row_index = state.first_action_row() + position;
                let y = ricepop::ACTION_TOP + position as u32 * ricepop::ACTION_HEIGHT;
                if row_index == state.selected_action {
                    fill_rounded_rect(
                        canvas,
                        width,
                        height,
                        8,
                        y,
                        width - 16,
                        29,
                        style.task_radius,
                        style.active,
                    );
                }
                draw_text(
                    canvas,
                    width,
                    height,
                    18,
                    y + 9,
                    &notification_glyphs(&action.label, 33),
                    style.foreground,
                );
            }
        }
    } else if state.visible_notices().is_empty() {
        draw_text(
            canvas,
            width,
            height,
            14,
            120,
            text::empty(language, state.show_history),
            style.foreground,
        );
    } else {
        for (position, notice) in state
            .visible_notices()
            .iter()
            .skip(state.first_row())
            .take(ricepop::VISIBLE_ROWS)
            .enumerate()
        {
            let row_index = state.first_row() + position;
            let y = ricepop::ROW_TOP + position as u32 * ricepop::ROW_HEIGHT;
            if row_index == state.selected {
                fill_rounded_rect(
                    canvas,
                    width,
                    height,
                    8,
                    y,
                    width - 16,
                    50,
                    style.task_radius,
                    style.active,
                );
            }
            let summary = notification_glyphs(&notice.summary, 35);
            let app = notification_glyphs(&notice.app_name, 35);
            draw_text(
                canvas,
                width,
                height,
                18,
                y + 10,
                if summary.is_empty() {
                    text::untitled(language)
                } else {
                    &summary
                },
                style.foreground,
            );
            draw_text(canvas, width, height, 18, y + 28, &app, style.foreground);
        }
    }
    fill_rect(canvas, width, height, 0, 261, width, 1, style.foreground);
    draw_text(
        canvas,
        width,
        height,
        14,
        279,
        text::footer_back(language, large_font, state.detail_id.is_some()),
        style.foreground,
    );
    draw_text(
        canvas,
        width,
        height,
        98,
        279,
        text::footer_refresh(language, large_font),
        style.foreground,
    );
    draw_text(
        canvas,
        width,
        height,
        193,
        279,
        text::footer_dismiss(language, large_font, state.selected_id().is_some()),
        style.foreground,
    );
}

pub(crate) fn paint_calendar(canvas: &mut [u8], style: &PanelStyle, state: &CalendarState) {
    let width = calendar::WIDTH;
    let height = calendar::HEIGHT;
    let glyph_scale = if style
        .native_art
        .as_ref()
        .and_then(|art| art.font.as_ref())
        .is_some()
    {
        style.font_scale
    } else {
        1
    };
    let large_custom_font = glyph_scale > 1;
    for pixel in canvas.chunks_exact_mut(4) {
        pixel.copy_from_slice(&style.background.to_le_bytes());
    }
    fill_rect(canvas, width, height, 0, 0, width, 56, style.active);
    let month_label = state
        .month
        .format(if large_custom_font { "%b %Y" } else { "%B %Y" })
        .to_string();
    draw_auxiliary_text(
        canvas,
        width,
        height,
        12,
        22,
        &month_label,
        style.foreground,
        style,
    );
    draw_auxiliary_text(canvas, width, height, 262, 22, "<", style.foreground, style);
    draw_auxiliary_text(canvas, width, height, 306, 22, ">", style.foreground, style);
    for (index, weekday) in ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
        .iter()
        .enumerate()
    {
        draw_auxiliary_text(
            canvas,
            width,
            height,
            calendar::GRID_X + index as u32 * calendar::CELL_WIDTH + 12,
            82,
            weekday,
            style.foreground,
            style,
        );
    }
    let muted = {
        let foreground = style.foreground;
        let background = style.background;
        let channel = |shift| {
            (((foreground >> shift) & 0xff_u32) + 2_u32 * ((background >> shift) & 0xff_u32))
                / 3_u32
        };
        0xff00_0000_u32 | (channel(16) << 16) | (channel(8) << 8) | channel(0)
    };
    for (index, (day, this_month)) in state.cells().into_iter().enumerate() {
        let x = calendar::GRID_X + (index % 7) as u32 * calendar::CELL_WIDTH;
        let y = calendar::GRID_Y + (index / 7) as u32 * calendar::CELL_HEIGHT;
        if day == state.today {
            fill_rounded_rect(
                canvas,
                width,
                height,
                x + 4,
                y + 2,
                calendar::CELL_WIDTH - 8,
                calendar::CELL_HEIGHT - 4,
                7,
                style.active,
            );
        }
        if day == state.selected {
            fill_rect(
                canvas,
                width,
                height,
                x + 4,
                y + 1,
                calendar::CELL_WIDTH - 8,
                2,
                style.foreground,
            );
            fill_rect(
                canvas,
                width,
                height,
                x + 4,
                y + calendar::CELL_HEIGHT - 3,
                calendar::CELL_WIDTH - 8,
                2,
                style.foreground,
            );
        }
        let label = day.day().to_string();
        let label_width = text_pixel_width(&label, glyph_scale);
        draw_auxiliary_text(
            canvas,
            width,
            height,
            x + calendar::CELL_WIDTH.saturating_sub(label_width) / 2,
            y + 13,
            &label,
            if this_month { style.foreground } else { muted },
            style,
        );
    }
    fill_rounded_rect(canvas, width, height, 12, 322, 92, 28, 4, style.active);
    draw_auxiliary_text(
        canvas,
        width,
        height,
        if large_custom_font { 14 } else { 31 },
        332,
        "Today",
        style.foreground,
        style,
    );
    draw_auxiliary_text(
        canvas,
        width,
        height,
        183,
        332,
        if large_custom_font {
            "Esc"
        } else {
            "Esc to close"
        },
        style.foreground,
        style,
    );
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wide_script_labels_are_fitted_to_the_popup_not_cut_by_its_edge() {
        // Real XP Luna face (embedded Liberation Sans; CJK through the
        // trusted system fallback when installed, else visible '?' cells).
        let mut style = crate::recipe::parse(
            include_str!("../../../examples/wayland/xp-luna-columns.json"),
            Some("xp-luna-columns"),
        )
        .unwrap();
        let art = crate::style_art::load(style.artwork.as_ref().unwrap(), style.font_scale)
            .expect("embedded Luna artwork");
        style.native_art = Some(art);
        let (width, height) = (320_u32, 40_u32);
        let mut canvas = vec![0_u8; (width * height * 4) as usize];
        // 30 scalars fit the character budget, but their measured advance
        // (system CJK fallback) is far wider than the popup.
        let label = "日本語のテキストです。".repeat(3);
        draw_notification_text(
            &mut canvas,
            width,
            height,
            14,
            8,
            &label,
            0xffff_ffff,
            &style,
        );
        let painted = |from: u32| {
            canvas
                .chunks_exact(4)
                .enumerate()
                .any(|(index, pixel)| index as u32 % width >= from && pixel != [0, 0, 0, 0])
        };
        assert!(painted(14), "label must be visible");
        assert!(
            !painted(width - 8),
            "wide text painted into the right margin: it overflowed and was cut"
        );
    }

    #[test]
    fn notification_labels_replace_controls_and_limit_unicode_scalars() {
        assert_eq!(notification_glyphs("alpha\nbeta", 20), "alpha beta");
        assert_eq!(notification_glyphs("αβγδε", 3), "αβγ");
        assert_eq!(notification_glyphs("test", 0), "");
    }
}
