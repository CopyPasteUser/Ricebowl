//! Original, raster-only Luna-inspired chrome for the opt-in two-column menu.
//! Geometry and actions remain owned by `native_menu`, including the footer
//! close target. No Microsoft image, font or executable theme asset is used.

use crate::{fill_rect, fill_rounded_rect, native_menu, recipe::MenuPalette};

fn blend(base: u32, tint: u32, amount: u32) -> u32 {
    let amount = amount.min(255);
    let channel = |shift: u32| {
        let a = (base >> shift) & 255;
        let b = (tint >> shift) & 255;
        (a * (255 - amount) + b * amount + 127) / 255
    };
    0xff00_0000 | (channel(16) << 16) | (channel(8) << 8) | channel(0)
}

pub fn header(canvas: &mut [u8], palette: MenuPalette) {
    let (w, h) = (native_menu::WIDTH, native_menu::HEIGHT);
    // The first 38 logical pixels remain one hit-free title band. A bright
    // rounded-edge-style reflection over cobalt, followed by a dark bottom
    // lip, gives Luna its original visual depth without importing XP assets.
    for y in 0..38 {
        let tone = if y == 0 { 0xffa4_d3ff }
            else if y < 5 {
                blend(palette.header, 0xffa3_d5ff, 144 - y * 13)
            } else if y < 20 {
                blend(palette.header, 0xff52_a2f0, 84 - (y - 5) * 3)
            } else {
                blend(palette.header, 0xff00_205f, (y - 20) * 6)
            };
        fill_rect(canvas, w, h, 0, y, w, 1, tone);
    }
    fill_rect(canvas, w, h, 0, 36, w, 1, 0xff08_357b);
    fill_rect(canvas, w, h, 0, 37, w, 1, 0xffff_c368);

    // Original RiceBowl account artwork in the familiar XP identity square,
    // including a recessed navy rim, pale-gold bevel and inset glossy portrait.
    fill_rounded_rect(canvas, w, h, 6, 3, 32, 32, 5, 0xff0b_387a);
    fill_rounded_rect(canvas, w, h, 7, 4, 30, 30, 4, 0xffff_d88e);
    fill_rounded_rect(canvas, w, h, 9, 6, 26, 26, 3, 0xffee_f7ff);
    fill_rounded_rect(canvas, w, h, 11, 8, 22, 22, 2, 0xff63_b6ef);
    fill_rect(canvas, w, h, 13, 9, 18, 1, 0xffc6_efff);
    fill_rounded_rect(canvas, w, h, 14, 20, 16, 7, 3, 0xff48_963b);
    fill_rounded_rect(canvas, w, h, 20, 12, 6, 6, 3, 0xffff_e4a2);
}

pub fn shelf(canvas: &mut [u8], palette: MenuPalette) {
    let (w, h) = (native_menu::WIDTH, native_menu::HEIGHT);
    let split = native_menu::COLUMNS_SPLIT;
    // Ivory program pane alongside XP's blue system shelf. Both shades stay
    // legible under the actual selected-row highlight and react to recipe
    // colors; the divider is visual, never a new pointer target.
    for y in 38..h - 28 {
        let progress = (y - 38) * 255 / (h - 66);
        let warm = blend(palette.background, 0xfff0_e9d9, progress / 13);
        fill_rect(canvas, w, h, 0, y, split, 1, warm);
        let blue = blend(palette.selection, 0xffff_ffff,
                         5 + 43 * progress / 255);
        fill_rect(canvas, w, h, split, y, w - split, 1, blue);
    }
    fill_rect(canvas, w, h, 0, 38, split, 1, 0xffff_ffff);
    fill_rect(canvas, w, h, split, 38, w - split, 1, 0xff96_b5e7);
    fill_rect(canvas, w, h, split, 39, 1, h - 67, 0xff71_96d0);
    fill_rect(canvas, w, h, split + 1, 39, 1, h - 67, 0xfff4_faff);
    fill_rect(canvas, w, h, w - 1, 38, 1, h - 66, 0xff86_a7d5);
}

/// Horizontal separator above the *real* All Programs tile. The tile's
/// geometry is defined exclusively in native_menu; this line is inert art.
pub fn left_all_programs_rule(canvas: &mut [u8]) {
    let (w, h) = (native_menu::WIDTH, native_menu::HEIGHT);
    let span = native_menu::COLUMNS_SPLIT.saturating_sub(20);
    fill_rect(canvas, w, h, 10, 232, span, 1, 0xffbd_bab0);
    fill_rect(canvas, w, h, 10, 233, span, 1, 0xffff_ffff);
}

/// Original bevelled footer buttons, using shared native_menu hit rectangles.
/// Lock and Log off are actual session actions; Log off looks disabled when the
/// compositor's supervised logout is unavailable (e.g. Creator preview).
fn footer_button(canvas: &mut [u8], left: u32, right: u32, hovered: bool,
                 disabled: bool, warm: bool) {
    let (w, h) = (native_menu::WIDTH, native_menu::HEIGHT);
    let y = native_menu::LUNA_FOOTER_Y + 3;
    let span = right.saturating_sub(left);
    let base = if disabled { 0xff64_7895 } else if warm { 0xffa8_5829 }
               else { 0xff3d_70be };
    let face = if hovered && !disabled { blend(base, 0xffff_ffff, 75) }
               else { blend(base, 0xffff_ffff, 18) };
    fill_rounded_rect(canvas, w, h, left, y, span, 22, 4,
                      blend(base, 0xff00_1039, 94));
    fill_rounded_rect(canvas, w, h, left + 1, y + 1, span.saturating_sub(2),
                      19, 3, face);
    fill_rect(canvas, w, h, left + 5, y + 2, span.saturating_sub(10), 1,
              if disabled { 0xff91_a3bd } else { 0xffb9_d9ff });
    // Small hand-painted lock/power glyph, not a Windows icon asset.
    if warm {
        fill_rounded_rect(canvas, w, h, left + 8, y + 6, 11, 11, 5,
                          if disabled { 0xffa5_b5c9 } else { 0xffff_e6b2 });
        fill_rect(canvas, w, h, left + 12, y + 4, 3, 8, face);
    } else {
        fill_rounded_rect(canvas, w, h, left + 9, y + 4, 10, 11, 5,
                          0xffde_ecff);
        fill_rect(canvas, w, h, left + 8, y + 10, 13, 8, 0xffff_cb68);
        fill_rect(canvas, w, h, left + 14, y + 13, 2, 4, 0xff43_6191);
    }
}

pub fn footer(canvas: &mut [u8], palette: MenuPalette,
              hovered: Option<native_menu::Hit>, logout_enabled: bool) {
    let (w, h) = (native_menu::WIDTH, native_menu::HEIGHT);
    for y in h - 28..h {
        let local = y - (h - 28);
        let shade = if local < 3 {
            blend(palette.header, 0xffa3_cfff, 115 - local * 20)
        } else if local < 17 {
            blend(palette.header, 0xff2e_73d1, 46)
        } else {
            blend(palette.header, 0xff00_174e, 40 + (local - 17) * 5)
        };
        fill_rect(canvas, w, h, 0, y, w, 1, shade);
    }
    fill_rect(canvas, w, h, 0, h - 28, w, 1, 0xffac_d5ff);
    fill_rect(canvas, w, h, 0, h - 1, w, 1, 0xff0b_317a);
    let lock = native_menu::LUNA_LOCK_RECT;
    let logout = native_menu::LUNA_LOGOUT_RECT;
    let close = native_menu::LUNA_CLOSE_RECT;
    footer_button(canvas, lock.0, lock.1,
                  hovered == Some(native_menu::Hit::FooterLock), false, false);
    footer_button(canvas, logout.0, logout.1,
                  hovered == Some(native_menu::Hit::FooterLogout), !logout_enabled, true);
    // Close stays in its previous 64px region, with an independent hit target.
    fill_rounded_rect(canvas, w, h, close.0, h - 24, close.1 - close.0,
                      20, 5, 0xff0c_327d);
    fill_rounded_rect(canvas, w, h, close.0 + 2, h - 23, close.1 - close.0 - 4,
                      17, 4, if hovered == Some(native_menu::Hit::Close) {
                          0xff66_9be0
                      } else { 0xff38_73c6 });
    fill_rect(canvas, w, h, close.0 + 10, h - 21, 44, 1, 0xffa7_d8ff);
}

/// Native XP-style green All Programs chevron. Its entire row remains the
/// real menu::Hit::Action; the glyph does not create a second fake target.
pub fn all_programs_chevron(canvas: &mut [u8], x: u32, y: u32, selected: bool) {
    let (w, h) = (native_menu::WIDTH, native_menu::HEIGHT);
    fill_rounded_rect(canvas, w, h, x, y, 17, 17, 7, 0xff1d_702c);
    fill_rounded_rect(canvas, w, h, x + 1, y + 1, 15, 14, 6,
                      if selected { 0xff5c_c547 } else { 0xff46_a833 });
    fill_rect(canvas, w, h, x + 5, y + 2, 7, 1, 0xffad_f49e);
    // White east-facing arrow: unlike the previous thin triangle, it retains
    // its silhouette against both the ivory and selected cobalt backgrounds.
    fill_rect(canvas, w, h, x + 4, y + 7, 8, 3, 0xffff_ffff);
    for step in 0..5 {
        fill_rect(canvas, w, h, x + 9 + step, y + 4 + step,
                  1, 9 - 2 * step, 0xffff_ffff);
    }
}

/// XP pale shelf separators, constrained to the real right-hand group edges.
pub fn system_group_rule(canvas: &mut [u8], y: u32) {
    let (w, h) = (native_menu::WIDTH, native_menu::HEIGHT);
    if y <= 39 || y >= h - 28 { return; }
    fill_rect(canvas, w, h, native_menu::COLUMNS_SPLIT + 8, y,
              w - native_menu::COLUMNS_SPLIT - 18, 1, 0xffa7_c5e8);
    fill_rect(canvas, w, h, native_menu::COLUMNS_SPLIT + 8, y + 1,
              w - native_menu::COLUMNS_SPLIT - 18, 1, 0xfff7_ffff);
}

/// 12px original RiceBowl command symbols. They use the same safe action IDs
/// that supply the hit-test grid; unknown installed applications get a dot.
pub fn action_icon(canvas: &mut [u8], x: u32, y: u32, action: &str, selected: bool) {
    let (w, h) = (native_menu::WIDTH, native_menu::HEIGHT);
    let ink = if selected { 0xffff_ffff } else { 0xff1a_4d84 };
    let light = if selected { 0xffca_e3ff } else { 0xff86_c2ec };
    match action {
        "applications" => {
            // Programs: a yellow XP-style folder, distinct from system setup.
            fill_rect(canvas, w, h, x, y + 3, 13, 10, 0xff9e_691d);
            fill_rect(canvas, w, h, x + 2, y + 1, 7, 3, 0xffe4_bc59);
            fill_rect(canvas, w, h, x + 1, y + 5, 11, 6, 0xffff_d268);
        }
        "settings" => {
            // Control Panel: copper gear surrounding a separate blue dial.
            // This symbol is original pixel art, not proprietary XP artwork.
            let rim = 0xff7d_571d;
            for (dx, dy) in [(5, 0), (6, 0), (0, 5), (0, 6),
                             (11, 5), (11, 6), (5, 11), (6, 11)] {
                fill_rect(canvas, w, h, x + dx, y + dy, 2, 2, rim);
            }
            fill_rounded_rect(canvas, w, h, x + 2, y + 2, 10, 10, 4, rim);
            fill_rounded_rect(canvas, w, h, x + 3, y + 3, 8, 8, 3, 0xffff_cf69);
            fill_rounded_rect(canvas, w, h, x + 5, y + 5, 4, 4, 2, 0xff46_96ce);
        }
        "documents" => {
            // Original yellow tabbed folder and pale paper sheet.
            fill_rect(canvas, w, h, x + 2, y + 1, 8, 10, 0xffe9_f5ff);
            fill_rect(canvas, w, h, x + 4, y + 3, 4, 1, 0xff60_99ce);
            fill_rect(canvas, w, h, x, y + 6, 13, 7, 0xffb7_791e);
            fill_rect(canvas, w, h, x + 1, y + 7, 11, 5, 0xffff_d16d);
            fill_rect(canvas, w, h, x + 2, y + 8, 9, 1, 0xffff_e2a0);
        }
        "pictures" => {
            // RiceBowl's own blue picture frame with a green landscape.
            fill_rect(canvas, w, h, x, y + 1, 13, 12, 0xff4c_71b7);
            fill_rect(canvas, w, h, x + 2, y + 3, 9, 8, 0xffa8_dcf5);
            fill_rect(canvas, w, h, x + 3, y + 8, 7, 3, 0xff61_a94f);
            fill_rounded_rect(canvas, w, h, x + 7, y + 4, 2, 2, 1, 0xffff_ee97);
        }
        "music" => {
            // Twin musical notes, drawn from primitives rather than host art.
            fill_rect(canvas, w, h, x + 5, y + 1, 7, 2, ink);
            fill_rect(canvas, w, h, x + 5, y + 3, 2, 8, ink);
            fill_rect(canvas, w, h, x + 10, y + 3, 2, 6, ink);
            fill_rounded_rect(canvas, w, h, x + 1, y + 9, 6, 4, 2, light);
            fill_rounded_rect(canvas, w, h, x + 7, y + 8, 6, 4, 2, light);
        }
        "computer" => {
            // Cobalt desktop monitor and original turquoise screen glint.
            fill_rect(canvas, w, h, x, y + 1, 13, 10, 0xff1e_436c);
            fill_rect(canvas, w, h, x + 1, y + 2, 11, 7, 0xff75_c2ee);
            fill_rect(canvas, w, h, x + 2, y + 3, 9, 2, 0xffc7_f6fa);
            fill_rect(canvas, w, h, x + 5, y + 11, 3, 2, ink);
            fill_rect(canvas, w, h, x + 2, y + 13, 9, 1, ink);
        }
        "terminal" => {
            fill_rect(canvas, w, h, x, y, 13, 11, ink);
            fill_rect(canvas, w, h, x + 2, y + 2, 9, 7, 0xff11_3444);
            fill_rect(canvas, w, h, x + 3, y + 5, 5, 1, 0xff8d_e5da);
            fill_rect(canvas, w, h, x + 4, y + 11, 5, 2, ink);
        }
        "lock" => {
            fill_rounded_rect(canvas, w, h, x + 2, y, 9, 9, 4, ink);
            fill_rounded_rect(canvas, w, h, x + 4, y + 2, 5, 7, 2, light);
            fill_rect(canvas, w, h, x, y + 6, 13, 7, 0xffe9_b447);
            fill_rect(canvas, w, h, x + 6, y + 8, 2, 3, ink);
        }
        "logout" => {
            // Log off: distinct orange doorway with an outward white arrow.
            fill_rect(canvas, w, h, x + 1, y + 1, 9, 12, 0xff8b_471d);
            fill_rect(canvas, w, h, x + 3, y + 2, 6, 10, 0xffed_a14c);
            fill_rect(canvas, w, h, x + 5, y + 4, 2, 2, 0xffff_e9a5);
            fill_rect(canvas, w, h, x + 5, y + 7, 8, 2, 0xffff_ffff);
            fill_rect(canvas, w, h, x + 10, y + 5, 2, 6, 0xffff_ffff);
        }
        "help" => {
            // Original blue assistance tile with a bright question-mark stem.
            fill_rounded_rect(canvas, w, h, x, y, 13, 13, 2, 0xff33_79cf);
            fill_rect(canvas, w, h, x + 4, y + 3, 5, 2, 0xffff_ffdc);
            fill_rect(canvas, w, h, x + 8, y + 5, 2, 3, 0xffff_ffdc);
            fill_rect(canvas, w, h, x + 5, y + 8, 3, 2, 0xffff_ffdc);
            fill_rect(canvas, w, h, x + 5, y + 11, 3, 2, 0xffff_ffdc);
        }
        "run" => {
            // Original terminal-window glyph. No shell command is inferred.
            fill_rounded_rect(canvas, w, h, x, y, 13, 12, 2, ink);
            fill_rect(canvas, w, h, x + 1, y + 2, 11, 9, 0xffd3_edf8);
            fill_rect(canvas, w, h, x + 3, y + 5, 3, 1, 0xff25_64ac);
            fill_rect(canvas, w, h, x + 6, y + 6, 2, 1, 0xff25_64ac);
        }
        "notifications" => {
            fill_rounded_rect(canvas, w, h, x + 2, y + 1, 9, 10, 4, 0xffff_c45b);
            fill_rect(canvas, w, h, x, y + 9, 13, 2, ink);
            fill_rect(canvas, w, h, x + 5, y + 11, 3, 2, 0xffba_7826);
        }
        app if app.starts_with("desktop:") => {
            // Missing vendor icon artwork is not replaced with a fake app
            // logo. An original framed application-window symbol communicates
            // an installed XDG program without relying on host icon paths.
            let tint = match app.bytes().fold(0_u8, |acc, b| acc.wrapping_add(b)) % 3 {
                0 => 0xff59_9ad5,
                1 => 0xff64_a755,
                _ => 0xffba_8a42,
            };
            fill_rect(canvas, w, h, x, y + 1, 14, 13, ink);
            fill_rect(canvas, w, h, x + 1, y + 2, 12, 11, 0xfff5_f9fd);
            fill_rect(canvas, w, h, x + 2, y + 3, 10, 3, tint);
            fill_rect(canvas, w, h, x + 3, y + 8, 7, 1, 0xff70_9ec7);
            fill_rect(canvas, w, h, x + 3, y + 10, 5, 1, 0xffa5_bac8);
        }
        _ => fill_rounded_rect(canvas, w, h, x + 3, y + 3, 7, 7, 3, light),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::recipe;

    fn at(pixels: &[u8], x: u32, y: u32) -> u32 {
        u32::from_le_bytes(pixels[((y * native_menu::WIDTH + x) * 4) as usize..]
            [..4].try_into().unwrap())
    }

    #[test]
    fn luna_chrome_has_distinct_header_programs_and_system_panes() {
        let style = recipe::parse(
            include_str!("../../../examples/wayland/xp-luna-columns.json"),
            Some("xp-luna-columns")).unwrap();
        let palette = style.menu.unwrap().palette.unwrap();
        let mut pixels = vec![0; (native_menu::WIDTH * native_menu::HEIGHT * 4) as usize];
        header(&mut pixels, palette);
        shelf(&mut pixels, palette);
        footer(&mut pixels, palette, None, false);
        assert_ne!(at(&pixels, 100, 0), at(&pixels, 100, 20));
        assert_ne!(at(&pixels, 100, 20), at(&pixels, 100, 36));
        assert_ne!(at(&pixels, 50, 150), at(&pixels, 250, 150));
        assert_ne!(at(&pixels, 250, 48), at(&pixels, 250, 250));
        assert_ne!(at(&pixels, 100, 289), at(&pixels, 100, 303));
        // At no point does a visual edge introduce transparency into the menu.
        for &(x, y) in &[(10, 10), (50, 150), (250, 150), (319, 200), (200, 303)] {
            assert_eq!(at(&pixels, x, y) >> 24, 0xff);
        }
    }

    #[test]
    fn green_all_programs_arrow_and_right_shelf_separator_have_bounded_pixels() {
        let mut pixels = vec![0; (native_menu::WIDTH * native_menu::HEIGHT * 4) as usize];
        all_programs_chevron(&mut pixels, 130, 115, false);
        assert_ne!(at(&pixels, 137, 121), 0); // Rounded corners are transparent
        assert_eq!(at(&pixels, 138, 123), 0xffff_ffff);
        let normal = pixels.clone();
        all_programs_chevron(&mut pixels, 130, 115, true);
        assert_ne!(normal, pixels); // Selected row has a brighter green face.
        system_group_rule(&mut pixels, 218);
        assert_ne!(at(&pixels, native_menu::COLUMNS_SPLIT + 9, 218), 0);
        assert_eq!(at(&pixels, 10, 218), 0); // No left pane bleed.
        assert_eq!(at(&pixels, 10, 275), 0); // Footer remains unmodified.
    }

    #[test]
    fn luna_bottom_program_separator_and_generic_xdg_icons_are_real_pixels() {
        let mut pixels = vec![0; (native_menu::WIDTH * native_menu::HEIGHT * 4) as usize];
        left_all_programs_rule(&mut pixels);
        assert_ne!(at(&pixels, 20, 232), 0);
        assert_eq!(at(&pixels, 200, 232), 0);
        let before = pixels.clone();
        action_icon(&mut pixels, 14, 80, "desktop:firefox.desktop", false);
        assert_ne!(pixels, before);
        assert_ne!(at(&pixels, 14, 81), 0);
        assert_eq!(at(&pixels, 14, 100), 0);
    }

    #[test]
    fn luna_footer_hover_and_logout_unavailability_are_painted_not_faked() {
        let style = recipe::parse(include_str!("../../../examples/wayland/xp-luna-columns.json"),
                                  Some("xp-luna-columns")).unwrap();
        let palette = style.menu.unwrap().palette.unwrap();
        let frame = || vec![0; (native_menu::WIDTH * native_menu::HEIGHT * 4) as usize];
        let mut idle = frame();
        footer(&mut idle, palette, None, true);
        let mut locked = frame();
        footer(&mut locked, palette, Some(native_menu::Hit::FooterLock), true);
        let mut logged_out = frame();
        footer(&mut logged_out, palette, Some(native_menu::Hit::FooterLogout), true);
        let mut unavailable = frame();
        footer(&mut unavailable, palette, Some(native_menu::Hit::FooterLogout), false);
        // Distinct live hover states for only the actual button surfaces.
        assert_ne!(at(&idle, 45, 287), at(&locked, 45, 287));
        assert_eq!(at(&idle, 140, 287), at(&locked, 140, 287));
        assert_ne!(at(&idle, 140, 287), at(&logged_out, 140, 287));
        // Hovering an unavailable logout does not light up a fake action.
        let mut disabled_idle = frame();
        footer(&mut disabled_idle, palette, None, false);
        assert_eq!(at(&disabled_idle, 140, 287), at(&unavailable, 140, 287));
        assert_ne!(at(&idle, 140, 287), at(&unavailable, 140, 287));
        assert_eq!(at(&idle, 217, 287), at(&locked, 217, 287));
    }

    #[test]
    fn menu_chrome_has_bevel_shelf_and_actionable_footer() {
        let style = recipe::parse(include_str!("../../../examples/wayland/xp-luna-columns.json"),
                                  Some("xp-luna-columns")).unwrap();
        let menu = style.menu.unwrap();
        let palette = menu.palette.unwrap();
        let mut pixels = vec![0; (native_menu::WIDTH * native_menu::HEIGHT * 4) as usize];
        header(&mut pixels, palette);
        shelf(&mut pixels, palette);
        footer(&mut pixels, palette, None, false);
        assert_ne!(at(&pixels, 100, 0), at(&pixels, 100, 29));
        assert_ne!(at(&pixels, 240, 48), at(&pixels, 240, 240));
        assert_ne!(at(&pixels, 280, native_menu::HEIGHT - 16),
                   at(&pixels, 200, native_menu::HEIGHT - 16));
        action_icon(&mut pixels, 14, 110, "terminal", false);
        assert_ne!(at(&pixels, 14, 110), 0);
        action_icon(&mut pixels, 14, 132, "documents", false);
        action_icon(&mut pixels, 14, 155, "computer", false);
        assert_ne!(at(&pixels, 14, 138), at(&pixels, 14, 156));
        let mut state = native_menu::MenuState::default();
        state.open();
        assert_eq!(state.hit(&menu, 280.0, f64::from(native_menu::HEIGHT - 16)),
                   Some(native_menu::Hit::Close));
    }

    #[test]
    fn luna_start_menu_control_panel_and_logoff_have_distinct_real_icons() {
        let render = |action: &str| {
            let mut pixels = vec![0_u8; (native_menu::WIDTH * native_menu::HEIGHT * 4) as usize];
            action_icon(&mut pixels, 32, 100, action, false);
            pixels
        };
        let programs = render("applications");
        let settings = render("settings");
        let lock = render("lock");
        let logout = render("logout");
        assert_ne!(programs, settings, "Control Panel must not reuse the Programs folder");
        assert_ne!(lock, logout, "Log off must not reuse the lock glyph");
        for pixels in [&programs, &settings, &lock, &logout] {
            assert_eq!(at(pixels, 30, 107), 0, "glyph may not paint outside its tile");
            assert_eq!(at(pixels, 46, 113), 0, "glyph may not paint into neighbouring text");
            assert_ne!(at(pixels, 37, 108), 0, "glyph is visible on actual menu pixels");
        }
    }
}
