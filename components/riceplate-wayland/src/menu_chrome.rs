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
    // Luna's blue bevel needs a top-lit band, not a single flat rectangle.
    for y in 0..38 {
        let color = if y < 19 {
            blend(palette.header, 0xff74_b5fa, 94 - y * 3)
        } else {
            blend(palette.header, 0xff00_1c63, (y - 19) * 4)
        };
        fill_rect(canvas, w, h, 0, y, w, 1, color);
    }
    fill_rect(canvas, w, h, 0, 0, w, 1, 0xff9b_c5ff);
    fill_rect(canvas, w, h, 0, 37, w, 1, 0xffff_cf74);

    // A deliberately original RiceBowl user tile, in the same visual place
    // as the classic account picture. It does not impersonate a real user.
    fill_rounded_rect(canvas, w, h, 7, 4, 29, 30, 5, 0xffff_e7a1);
    fill_rounded_rect(canvas, w, h, 9, 6, 25, 26, 4, 0xffec_f5ff);
    fill_rounded_rect(canvas, w, h, 11, 8, 21, 22, 3, 0xff5d_b9f6);
    fill_rounded_rect(canvas, w, h, 14, 20, 16, 7, 3, 0xff4a_8f39);
    fill_rounded_rect(canvas, w, h, 20, 12, 6, 6, 3, 0xffff_e3a5);
}

pub fn shelf(canvas: &mut [u8], palette: MenuPalette) {
    let (w, h) = (native_menu::WIDTH, native_menu::HEIGHT);
    let split = native_menu::COLUMNS_SPLIT;
    for y in 38..h - 28 {
        // Narrow, bounded gradient. The left pane is ivory; the right is the
        // recognisable pale-blue system shelf with an azure edge.
        let tone = blend(palette.selection, 0xffff_ffff,
                         9 + 24 * (y - 38) / (h - 66));
        fill_rect(canvas, w, h, split, y, w - split, 1, tone);
    }
    fill_rect(canvas, w, h, split, 38, 1, h - 66,
              blend(palette.header, 0xffff_ffff, 75));
    fill_rect(canvas, w, h, split + 1, 38, 1, h - 66, 0xfff2_f8ff);
    fill_rect(canvas, w, h, w - 1, 38, 1, h - 66, 0xff83_a8df);
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
        let shade = blend(palette.header, 0xff00_174e, 20 + (y - (h - 28)) * 3);
        fill_rect(canvas, w, h, 0, y, w, 1, shade);
    }
    fill_rect(canvas, w, h, 0, h - 28, w, 1, 0xff86_b4f3);
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
        "applications" | "settings" => {
            fill_rect(canvas, w, h, x, y + 3, 13, 10, 0xff9e_691d);
            fill_rect(canvas, w, h, x + 2, y + 1, 7, 3, 0xffe4_bc59);
            fill_rect(canvas, w, h, x + 1, y + 5, 11, 6, 0xffff_d268);
        }
        "documents" => {
            // Original yellow tabbed folder and pale paper sheet.
            fill_rect(canvas, w, h, x + 2, y + 1, 8, 10, 0xffe9_f5ff);
            fill_rect(canvas, w, h, x + 4, y + 3, 4, 1, 0xff60_99ce);
            fill_rect(canvas, w, h, x, y + 6, 13, 7, 0xffb7_791e);
            fill_rect(canvas, w, h, x + 1, y + 7, 11, 5, 0xffff_d16d);
            fill_rect(canvas, w, h, x + 2, y + 8, 9, 1, 0xffff_e2a0);
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
        "lock" | "logout" => {
            fill_rounded_rect(canvas, w, h, x + 2, y, 9, 9, 4, ink);
            fill_rounded_rect(canvas, w, h, x + 4, y + 2, 5, 7, 2, light);
            fill_rect(canvas, w, h, x, y + 6, 13, 7, 0xffe9_b447);
            fill_rect(canvas, w, h, x + 6, y + 8, 2, 3, ink);
        }
        "notifications" => {
            fill_rounded_rect(canvas, w, h, x + 2, y + 1, 9, 10, 4, 0xffff_c45b);
            fill_rect(canvas, w, h, x, y + 9, 13, 2, ink);
            fill_rect(canvas, w, h, x + 5, y + 11, 3, 2, 0xffba_7826);
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
}
