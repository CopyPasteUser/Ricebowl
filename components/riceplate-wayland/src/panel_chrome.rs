//! Rich taskbar treatment for recipes which opt in to a decorated launcher.
//! No special case for XP: undecorated v1–v11 recipes keep their exact pixels.

use crate::{
    fill_rect, fill_rounded_rect,
    recipe::{LauncherDecoration, PanelStyle, PlacedWidget, Widget},
};

/// Native Luna taskbar interaction treatment. The owning RicePlate hit test
/// remains the sole authority: these are paint states, never new commands.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum ButtonVisual {
    #[default]
    Normal,
    Hovered,
    Pressed,
}

fn mix_rgb(base: u32, tint: u32, weight: u32) -> u32 {
    let weight = weight.min(255);
    let channel = |shift: u32| {
        let a = (base >> shift) & 0xff;
        let b = (tint >> shift) & 0xff;
        (a * (255 - weight) + b * weight + 127) / 255
    };
    0xff00_0000 | (channel(16) << 16) | (channel(8) << 8) | channel(0)
}

pub fn background(
    canvas: &mut [u8], width: u32, height: u32,
    style: &PanelStyle, layout: &[PlacedWidget],
) {
    if style.launcher.is_none() {
        // Preserve historical flat-panel output, including all existing rices.
        for pixel in canvas.chunks_exact_mut(4) {
            pixel.copy_from_slice(&style.background.to_le_bytes());
        }
        return;
    }

    if style.id == "xp-luna-columns" {
        // Luna's taskband has three distinct optical zones: a narrow sky-blue
        // rim, a saturated cobalt face, and a deep bottom edge. The gradient
        // is calculated once per scanline and remains entirely opaque.
        for y in 0..height {
            let tone = if y == 0 { 0xff83_b9ff }
                else if y < 3 { 0xff4c_8beb }
                else if y < height / 2 {
                    mix_rgb(0xff1f_58c4, 0xff4f_92ee,
                            95_u32.saturating_sub(y.saturating_mul(3)))
                } else {
                    mix_rgb(0xff25_61ce, 0xff0a_2e87,
                            (y - height / 2) * 85 / (height / 2).max(1))
                };
            fill_rect(canvas, width, height, 0, y, width, 1, tone);
        }
        if height > 3 {
            fill_rect(canvas, width, height, 0, 2, width, 1, 0xff1d_4ea4);
        }
        // The notification area stays part of the same physical panel and
        // starts precisely at the actual right-side status widget geometry.
        let shelf_start = layout.iter()
            .filter(|item| matches!(item.widget,
                Widget::Network | Widget::Audio | Widget::Battery | Widget::Tray | Widget::Clock))
            .filter(|item| item.x >= width / 2)
            .map(|item| item.x).min();
        if let Some(start) = shelf_start {
            let left = start.saturating_sub(4);
            for y in 1..height {
                let tone = if y < height / 2 {
                    mix_rgb(0xff49_b9ee, 0xffd0_faff,
                            60_u32.saturating_sub(y.saturating_mul(3)))
                } else {
                    mix_rgb(0xff2c_98db, 0xff0d_5aab,
                            (y - height / 2) * 84 / (height / 2).max(1))
                };
                fill_rect(canvas, width, height, left, y, width - left, 1, tone);
            }
            fill_rect(canvas, width, height, left, 1, 1,
                      height.saturating_sub(1), 0xff11_448d);
            fill_rect(canvas, width, height, left + 1, 1, 1,
                      height.saturating_sub(1), 0xff98_dfff);
        }
        return;
    }

    // Opaque 40px-classic taskbar: a soft top reflection and darker bottom.
    // Bounded by the compositor-validated panel height; no allocations.
    for y in 0..height {
        let tone = if y * 2 < height {
            mix_rgb(style.background, 0xffff_ffff, 45 - 26 * y / height.max(1))
        } else {
            mix_rgb(style.background, 0xff00_153b,
                    8 + 38 * (y * 2 - height) / height.max(1))
        };
        fill_rect(canvas, width, height, 0, y, width, 1, tone);
    }
    fill_rect(canvas, width, height, 0, 0, width, 1,
              mix_rgb(style.background, 0xffff_ffff, 115));

    // An optical notification shelf, but never a new hit target or process.
    // The shelf starts only when a status widget is in the right-hand half.
    let shelf_start = layout.iter()
        .filter(|item| matches!(item.widget,
            Widget::Network | Widget::Audio | Widget::Battery | Widget::Tray | Widget::Clock))
        .filter(|item| item.x >= width / 2)
        .map(|item| item.x)
        .min();
    if let Some(start) = shelf_start {
        let left = start.saturating_sub(4);
        fill_rect(canvas, width, height, left, 1, width - left,
                  height.saturating_sub(1),
                  mix_rgb(style.background, 0xff39_c2fa, 102));
        fill_rect(canvas, width, height, left, 1, 1,
                  height.saturating_sub(1),
                  mix_rgb(style.background, 0xffff_ffff, 148));
    }
}

pub fn launcher(
    canvas: &mut [u8], width: u32, height: u32,
    x: u32, span: u32, decoration: &LauncherDecoration,
) {
    if span < 8 || height < 9 { return; }
    // A green raised capsule with inner highlight; the shared hitbox is
    // unchanged, so pointer, keyboard and AT-SPI behavior stays intact.
    fill_rounded_rect(canvas, width, height, x + 1, 2,
                      span - 2, height - 4, decoration.radius,
                      mix_rgb(decoration.background, 0xff00_2000, 100));
    fill_rounded_rect(canvas, width, height, x + 2, 3,
                      span - 4, height - 7,
                      decoration.radius.saturating_sub(1),
                      decoration.background);
    // Bright left shoulder and slightly shaded right flank define the
    // familiar raised green XP silhouette without any imported bitmap.
    for row in 4..height.saturating_sub(6) {
        let tone = if row < height / 2 {
            mix_rgb(decoration.background, 0xffd6_ffb9,
                    100_u32.saturating_sub(row * 3))
        } else {
            mix_rgb(decoration.background, 0xff0d_4818,
                    9 + (row - height / 2) * 3)
        };
        fill_rect(canvas, width, height, x + 12, row,
                  span.saturating_sub(25), 1, tone);
    }
    let inset = decoration.radius.max(5);
    if span > 2 * inset {
        fill_rect(canvas, width, height, x + inset, 4,
                  span - 2 * inset, 1,
                  mix_rgb(decoration.background, 0xffff_ffff, 135));
    }
    // Small original four-tile RiceBowl mark: evokes an early-2000s desktop
    // launcher, but is not a Microsoft Windows trademark/asset copy.
    if span >= 74 && height >= 28 {
        for (dx, dy, color) in [
            (0, 0, 0xffef_8f53), (8, 1, 0xffe6_ce58),
            (0, 8, 0xff75_bbe6), (8, 9, 0xffb3_d973),
        ] {
            fill_rounded_rect(canvas, width, height, x + 11 + dx,
                              height / 2 - 9 + dy, 7, 7, 1,
                              mix_rgb(color, 0xffff_ffff, 25));
        }
    }
}

/// Final optical pass for the opt-in native Luna Start button. It does not
/// alter the launcher geometry or input state of older desktop recipes.
pub fn luna_launcher_finish(canvas: &mut [u8], width: u32, height: u32,
                            x: u32, span: u32, visual: ButtonVisual) {
    if span < 40 || height < 28 { return; }
    let top = if visual == ButtonVisual::Pressed { 5 } else { 4 };
    // An asymmetric raised highlight and a dark-green lower return reproduce
    // the XP taskbar's characteristic chunky, glassy Start silhouette.
    fill_rect(canvas, width, height, x + 15, top, span.saturating_sub(34),
              1, if visual == ButtonVisual::Pressed { 0xff78_bf5a } else { 0xffd9_ffb8 });
    fill_rect(canvas, width, height, x + 9, 7, 1, height.saturating_sub(16),
              0xffa0_ea6d);
    fill_rect(canvas, width, height, x + 13, height.saturating_sub(7),
              span.saturating_sub(27), 1, 0xff1d_5f1b);
    if visual == ButtonVisual::Hovered {
        fill_rect(canvas, width, height, x + 17, top + 1,
                  span.saturating_sub(37), 1, 0xfff2_ffd8);
    }
}

/// Layer input feedback over the existing native green Start capsule.
pub fn launcher_visual(
    canvas: &mut [u8], width: u32, height: u32, x: u32,
    span: u32, decoration: &LauncherDecoration, visual: ButtonVisual,
) {
    launcher(canvas, width, height, x, span, decoration);
    if span < 32 || height < 16 { return; }
    match visual {
        ButtonVisual::Normal => {}
        ButtonVisual::Hovered => {
            // XP-like illuminated top/left edge with the existing green body.
            fill_rect(canvas, width, height, x + 15, 4,
                      span.saturating_sub(32), 2, 0xffc2_f9a6);
            fill_rect(canvas, width, height, x + 5, 11, 1,
                      height.saturating_sub(22), 0xff83_dc62);
        }
        ButtonVisual::Pressed => {
            // Depressed optical edge, visually distinct from hover.
            fill_rect(canvas, width, height, x + 15, 4,
                      span.saturating_sub(32), 2, 0xff20_5719);
            fill_rect(canvas, width, height, x + 6, height - 6,
                      span.saturating_sub(15), 1, 0xffb6_ec98);
        }
    }
}

pub fn task_button(
    canvas: &mut [u8], width: u32, height: u32,
    x: u32, span: u32, active: bool, style: &PanelStyle,
) {
    if style.launcher.is_none() {
        if active {
            fill_rounded_rect(canvas, width, height, x, 0,
                              span.saturating_sub(2), height,
                              style.task_radius, style.active);
        }
        return;
    }
    if span < 8 || height < 10 { return; }

    if style.id == "xp-luna-columns" {
        // Inactive task buttons are raised and luminous; active windows sit
        // slightly recessed with the unmistakable deeper cobalt-blue face.
        let edge = if active { 0xff0c_327b } else { 0xff1c_479f };
        let face = if active { 0xff174a9e } else { 0xff397cda };
        fill_rounded_rect(canvas, width, height, x + 1, 3,
                          span - 3, height - 6, 4, edge);
        fill_rounded_rect(canvas, width, height, x + 2, 4,
                          span - 5, height - 8, 3, face);
        fill_rect(canvas, width, height, x + 6, 4,
                  span.saturating_sub(13), 1,
                  if active { 0xff2e_69bf } else { 0xffa2_d5ff });
        fill_rect(canvas, width, height, x + 6, height - 6,
                  span.saturating_sub(13), 1,
                  if active { 0xff0c_306e } else { 0xff1b_4ba5 });
        return;
    }

    let base = if active {
        style.active
    } else {
        mix_rgb(style.background, 0xffff_ffff, 38)
    };
    fill_rounded_rect(canvas, width, height, x + 1, 3,
                      span - 4, height - 6, style.task_radius,
                      mix_rgb(base, 0xff00_1738, 38));
    fill_rounded_rect(canvas, width, height, x + 2, 4,
                      span - 6, height - 9, style.task_radius, base);
    fill_rect(canvas, width, height, x + 5, 4,
              span.saturating_sub(12), 1, mix_rgb(base, 0xffff_ffff, 85));
}

/// Luna task entries have distinct hover and depressed faces without
/// changing the original hit rectangles, window activation or task grouping.
pub fn task_button_visual(
    canvas: &mut [u8], width: u32, height: u32,
    x: u32, span: u32, active: bool, style: &PanelStyle, visual: ButtonVisual,
) {
    task_button(canvas, width, height, x, span, active, style);
    // Keep the existing interactive states for other decorated rices.
    // XP-specific colors are selected below without changing their pixels.
    if style.launcher.is_none() || span < 18 || height < 16 { return; }
    match visual {
        ButtonVisual::Normal => {}
        ButtonVisual::Hovered => {
            let top = if style.id == "xp-luna-columns" {
                0xffe0_f2ff
            } else { 0xffb8_e5ff };
            fill_rect(canvas, width, height, x + 6, 5,
                      span.saturating_sub(14), 2, top);
            fill_rect(canvas, width, height, x + 4, 10,
                      1, height.saturating_sub(20), 0xff8d_bfff);
        }
        ButtonVisual::Pressed => {
            fill_rect(canvas, width, height, x + 6, 5,
                      span.saturating_sub(14), 2, 0xff0c_2e75);
            fill_rect(canvas, width, height, x + 5, height - 6,
                      span.saturating_sub(13), 1, 0xff94_bbf2);
        }
    }
}

/// Highlight minimized groups without inventing a task or altering its hit
/// region. Other rices retain byte-identical rendering.
pub fn task_button_state_visual(
    canvas: &mut [u8], width: u32, height: u32,
    x: u32, span: u32, active: bool, minimized: bool,
    style: &PanelStyle, visual: ButtonVisual,
) {
    task_button_visual(canvas, width, height, x, span, active, style, visual);
    if style.id == "xp-luna-columns" && minimized && !active
        && span >= 20 && height >= 18 {
        // Muted lower inset distinguishes a minimized task from a window
        // simply behind another window; keep hover/pressed state intact.
        fill_rect(canvas, width, height, x + 7, height - 9,
                  span.saturating_sub(16), 1, 0xff98_b2d8);
    }
}

/// Original 16px tray art for the Luna recipe. The native widget keeps its
/// existing pointer and accessible status value; only the painted pixels are
/// changed. Other rices keep their plain, informative status text.
pub fn status_icon(canvas: &mut [u8], width: u32, height: u32,
                   x: u32, span: u32, widget: Widget, unavailable: bool) {
    if span < 18 || height < 18 { return; }
    let left = x + (span - 18) / 2;
    let top = (height - 16) / 2;
    let outline = 0xff19_3157;
    let shine = 0xffec_f7ff;
    match widget {
        Widget::Network => {
            // Two small connected desktop monitors, with a bright glass edge.
            fill_rect(canvas, width, height, left + 2, top + 5, 10, 8, outline);
            fill_rect(canvas, width, height, left + 3, top + 6, 8, 5, 0xff7f_c6fa);
            fill_rect(canvas, width, height, left + 4, top + 6, 6, 1, shine);
            fill_rect(canvas, width, height, left + 6, top + 13, 3, 1, shine);
            fill_rect(canvas, width, height, left + 10, top + 1, 7, 7, outline);
            fill_rect(canvas, width, height, left + 11, top + 2, 5, 4, 0xff49_9edf);
            fill_rect(canvas, width, height, left + 12, top + 2, 3, 1, shine);
            fill_rect(canvas, width, height, left + 12, top + 8, 3, 1, shine);
        }
        Widget::Audio => {
            // Silver speaker with two blue sound-wave strokes.
            fill_rect(canvas, width, height, left + 2, top + 6, 4, 5, outline);
            fill_rect(canvas, width, height, left + 3, top + 7, 3, 3, shine);
            fill_rect(canvas, width, height, left + 6, top + 4, 2, 9, outline);
            fill_rect(canvas, width, height, left + 8, top + 2, 2, 13, 0xffb8_dced);
            fill_rect(canvas, width, height, left + 11, top + 5, 1, 7, 0xfff2_ffff);
            fill_rect(canvas, width, height, left + 13, top + 3, 1, 11, 0xff9b_e9ff);
        }
        Widget::Battery => {
            // Original 16px silver battery silhouette with green charge fill.
            fill_rect(canvas, width, height, left + 2, top + 4, 13, 10, outline);
            fill_rect(canvas, width, height, left + 3, top + 5, 11, 8, shine);
            fill_rect(canvas, width, height, left + 5, top + 7, 7, 4,
                      if unavailable { 0xffa4_b1be } else { 0xff69_bf44 });
            fill_rect(canvas, width, height, left + 15, top + 7, 2, 4, outline);
            fill_rect(canvas, width, height, left + 3, top + 5, 11, 1, 0xff9e_c6e1);
        }
        _ => return,
    }
    if unavailable {
        // XP-style red disconnected/muted badge, visible on dark taskbars.
        fill_rect(canvas, width, height, left + 12, top + 10, 5, 5, shine);
        for offset in 0..5 {
            fill_rect(canvas, width, height, left + 12 + offset, top + 10 + offset,
                      1, 1, 0xffe6_3428);
            fill_rect(canvas, width, height, left + 16 - offset, top + 10 + offset,
                      1, 1, 0xffe6_3428);
        }
    }
}

/// An original XP-like "show hidden icons" chevron. The existing fourth
/// SNI tray slot remains its only hit target and still opens the real popup.
pub fn tray_overflow_chevron(canvas: &mut [u8], width: u32, height: u32, x: u32) {
    if height < 22 { return; }
    let top = (height - 24) / 2;
    fill_rounded_rect(canvas, width, height, x + 2, top, 24, 24, 6, 0xff15_598f);
    fill_rounded_rect(canvas, width, height, x + 3, top + 1, 22, 21, 5, 0xff53_b6ed);
    fill_rect(canvas, width, height, x + 5, top + 2, 18, 1, 0xffc5_f2ff);
    // White facing-left double chevron, not a static count masquerading as
    // an interactive control.
    for origin in [8_u32, 15] {
        for step in 0..4 {
            fill_rect(canvas, width, height, x + origin + step,
                      top + 8 + step, 1, 7 - step * 2, 0xffff_ffff);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::recipe;

    fn px(buffer: &[u8], width: u32, x: u32, y: u32) -> u32 {
        let index = ((y * width + x) * 4) as usize;
        u32::from_le_bytes(buffer[index..index + 4].try_into().unwrap())
    }

    fn luna() -> PanelStyle {
        recipe::parse(include_str!("../../../examples/wayland/xp-luna.json"),
                      Some("xp-luna")).unwrap()
    }

    #[test]
    fn legacy_panel_stays_pixel_identical() {
        let style = recipe::parse(
            include_str!("../../../macrice/de/resources/recipes/classic.json"),
            Some("classic")).unwrap();
        let mut pixels = vec![0_u8; 400 * 36 * 4];
        background(&mut pixels, 400, 36, &style, &[]);
        assert!(pixels.chunks_exact(4).all(|pixel|
            pixel == style.background.to_le_bytes().as_slice()));
    }

    #[test]
    fn battery_status_glyph_is_bounded_and_reflects_absence() {
        let (width, height) = (80, 40);
        let mut available = vec![0_u8; (width * height * 4) as usize];
        let mut absent = available.clone();
        status_icon(&mut available, width, height, 0, 28, Widget::Battery, false);
        status_icon(&mut absent, width, height, 0, 28, Widget::Battery, true);
        assert_ne!(available, absent);
        assert!(available.iter().any(|byte| *byte != 0));
        assert!(available.chunks_exact(4).skip((width * 2) as usize)
            .any(|pixel| pixel != [0, 0, 0, 0]));
    }

    #[test]
    fn decorated_panel_has_top_glint_and_separate_status_shelf() {
        let style = luna();
        let (width, height) = (1366, style.height);
        let mut pixels = vec![0_u8; (width * height * 4) as usize];
        let layout = recipe::layout(&style, width, 3);
        background(&mut pixels, width, height, &style, &layout);
        assert_ne!(px(&pixels, width, 200, 0), px(&pixels, width, 200, height - 1));
        assert_ne!(px(&pixels, width, width - 4, 18), px(&pixels, width, width / 2, 18));
    }

    #[test]
    fn decorated_buttons_are_distinct_and_bounded() {
        let style = luna();
        let mut pixels = vec![0_u8; 400 * 40 * 4];
        let decor = style.launcher.as_ref().unwrap();
        launcher(&mut pixels, 400, 40, 0, 94, decor);
        let green = px(&pixels, 400, 45, 20);
        assert!((green >> 8 & 255) > (green >> 16 & 255));
        assert_ne!(px(&pixels, 400, 45, 9), green);
        assert_ne!(px(&pixels, 400, 14, 14), green); // Original tile mark
        task_button(&mut pixels, 400, 40, 100, 130, false, &style);
        let inactive = px(&pixels, 400, 110, 20);
        task_button(&mut pixels, 400, 40, 100, 130, true, &style);
        assert_ne!(inactive, px(&pixels, 400, 110, 20));
    }

    #[test]
    fn luna_hover_and_pressed_states_have_distinct_pixels_without_changing_geometry() {
        let style = recipe::parse(
            include_str!("../../../examples/wayland/xp-luna-columns.json"),
            Some("xp-luna-columns")).unwrap();
        let (width, height) = (420, style.height);
        let decor = style.launcher.as_ref().unwrap();
        let render = |visual| {
            let mut pixels = vec![0; (width * height * 4) as usize];
            background(&mut pixels, width, height, &style, &[]);
            launcher_visual(&mut pixels, width, height, 0, 96, decor, visual);
            task_button_visual(&mut pixels, width, height, 110, 150, false,
                               &style, visual);
            pixels
        };
        let idle = render(ButtonVisual::Normal);
        let hover = render(ButtonVisual::Hovered);
        let press = render(ButtonVisual::Pressed);
        assert_ne!(idle, hover);
        assert_ne!(idle, press);
        assert_ne!(hover, press);
        for frame in [&idle, &hover, &press] {
            assert_eq!(px(frame, width, width - 1, 0), px(&idle, width, width - 1, 0));
            assert_eq!(px(frame, width, 330, height - 2), px(&idle, width, 330, height - 2));
        }
    }

    #[test]
    fn decorated_non_luna_task_buttons_keep_existing_hover_and_pressed_states() {
        let mut other = recipe::parse(
            include_str!("../../../examples/wayland/xp-luna-columns.json"),
            Some("xp-luna-columns")).unwrap();
        other.id = "other-decorated-rice".into();
        let (width, height) = (420, other.height);
        let image = |visual| {
            let mut pixels = vec![0_u8; (width * height * 4) as usize];
            background(&mut pixels, width, height, &other, &[]);
            task_button_visual(&mut pixels, width, height, 110, 150, false,
                               &other, visual);
            pixels
        };
        assert_ne!(image(ButtonVisual::Normal), image(ButtonVisual::Hovered));
        assert_ne!(image(ButtonVisual::Normal), image(ButtonVisual::Pressed));
    }

    #[test]
    fn luna_taskband_palette_is_layered_and_legacy_is_not_affected() {
        let style = recipe::parse(
            include_str!("../../../examples/wayland/xp-luna-columns.json"),
            Some("xp-luna-columns")).unwrap();
        let width = 600;
        let mut pixels = vec![0_u8; (width * style.height * 4) as usize];
        let layout = recipe::layout(&style, width, 2);
        background(&mut pixels, width, style.height, &style, &layout);
        // Distinct sky-blue rim, cobalt task face and lower navy finish.
        assert_ne!(px(&pixels, width, 250, 0), px(&pixels, width, 250, 15));
        assert_ne!(px(&pixels, width, 250, 15),
                   px(&pixels, width, 250, style.height - 2));
        let original = pixels.clone();
        task_button(&mut pixels, width, style.height, 105, 150, false, &style);
        let inactive = px(&pixels, width, 125, 18);
        task_button(&mut pixels, width, style.height, 105, 150, true, &style);
        assert_ne!(inactive, px(&pixels, width, 125, 18));
        assert_eq!(px(&pixels, width, 450, 15), px(&original, width, 450, 15));
        let decor = style.launcher.as_ref().unwrap();
        launcher_visual(&mut pixels, width, style.height, 0, 94, decor, ButtonVisual::Hovered);
        let hovered = pixels.clone();
        luna_launcher_finish(&mut pixels, width, style.height, 0, 94, ButtonVisual::Hovered);
        assert_ne!(hovered, pixels);
        assert_eq!(px(&pixels, width, 450, 15), px(&original, width, 450, 15));
    }

    #[test]
    fn tiny_surfaces_do_not_panic() {
        let style = luna();
        let mut pixels = vec![0_u8; 12 * 8 * 4];
        background(&mut pixels, 12, 8, &style, &[]);
        task_button(&mut pixels, 12, 8, 0, 4, true, &style);
        launcher(&mut pixels, 12, 8, 0, 4, style.launcher.as_ref().unwrap());
        status_icon(&mut pixels, 12, 8, 0, 4, Widget::Audio, true);
    }

    #[test]
    fn luna_tray_overflow_chevron_is_original_and_clipped() {
        let (width, height) = (112, 40);
        let mut pixels = vec![0_u8; (width * height * 4) as usize];
        tray_overflow_chevron(&mut pixels, width, height, width - 28);
        assert_eq!(px(&pixels, width, 0, 0), 0);
        assert_ne!(px(&pixels, width, width - 21, height / 2), 0);
        assert_eq!(px(&pixels, width, 45, height / 2), 0);
        // Small/rotated logical panels remain safely paintable.
        let mut tiny = vec![0_u8; 8 * 8 * 4];
        tray_overflow_chevron(&mut tiny, 8, 8, 0);
        assert!(tiny.iter().all(|&value| value == 0));
    }

    #[test]
    fn minimized_luna_tasks_have_distinct_pixels_without_other_rice_regression() {
        let style = recipe::parse(
            include_str!("../../../examples/wayland/xp-luna-columns.json"),
            Some("xp-luna-columns"),
        ).unwrap();
        let mut normal = vec![0; (300 * 40 * 4) as usize];
        task_button_state_visual(&mut normal, 300, 40, 10, 125,
                                 false, false, &style, ButtonVisual::Normal);
        let mut minimized = vec![0; normal.len()];
        task_button_state_visual(&mut minimized, 300, 40, 10, 125,
                                 false, true, &style, ButtonVisual::Normal);
        assert_ne!(normal, minimized);
        assert_eq!(px(&minimized, 300, 17, 31), 0xff98_b2d8);
        let mut hovered = vec![0; normal.len()];
        task_button_state_visual(&mut hovered, 300, 40, 10, 125,
                                 false, true, &style, ButtonVisual::Hovered);
        assert_ne!(hovered, minimized);
        let mut legacy = crate::recipe::load("classic").unwrap();
        legacy.launcher = style.launcher;
        let mut a = vec![0; normal.len()];
        let mut b = vec![0; normal.len()];
        task_button_state_visual(&mut a, 300, 40, 10, 125,
                                 false, false, &legacy, ButtonVisual::Hovered);
        task_button_state_visual(&mut b, 300, 40, 10, 125,
                                 false, true, &legacy, ButtonVisual::Hovered);
        assert_eq!(a, b);
    }

    #[test]
    fn luna_tray_icons_are_distinct_and_expose_a_disconnected_badge() {
        let (width, height) = (90, 40);
        let mut pixels = vec![0_u8; (width * height * 4) as usize];
        status_icon(&mut pixels, width, height, 0, 28, Widget::Network, false);
        status_icon(&mut pixels, width, height, 29, 28, Widget::Audio, false);
        assert_ne!(px(&pixels, width, 9, 21), 0);
        assert_ne!(px(&pixels, width, 41, 21), 0);
        let before = px(&pixels, width, 46, 23);
        status_icon(&mut pixels, width, height, 29, 28, Widget::Audio, true);
        assert_ne!(before, px(&pixels, width, 46, 23));
    }
}
