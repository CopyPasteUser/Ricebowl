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

pub fn footer(canvas: &mut [u8], palette: MenuPalette) {
    let (w, h) = (native_menu::WIDTH, native_menu::HEIGHT);
    for y in h - 28..h {
        let shade = blend(palette.header, 0xff00_174e, 20 + (y - (h - 28)) * 3);
        fill_rect(canvas, w, h, 0, y, w, 1, shade);
    }
    fill_rect(canvas, w, h, 0, h - 28, w, 1, 0xff86_b4f3);
    // The entire footer is an existing Close hit target; this is the visible,
    // accurately positioned affordance for that working action.
    fill_rounded_rect(canvas, w, h, w - 69, h - 24, 64, 20, 5, 0xff0c_327d);
    fill_rounded_rect(canvas, w, h, w - 67, h - 23, 60, 17, 4, 0xff38_73c6);
    fill_rect(canvas, w, h, w - 59, h - 21, 44, 1, 0xffa7_d8ff);
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
    fn menu_chrome_has_bevel_shelf_and_actionable_footer() {
        let style = recipe::parse(include_str!("../../../examples/wayland/xp-luna-columns.json"),
                                  Some("xp-luna-columns")).unwrap();
        let menu = style.menu.unwrap();
        let palette = menu.palette.unwrap();
        let mut pixels = vec![0; (native_menu::WIDTH * native_menu::HEIGHT * 4) as usize];
        header(&mut pixels, palette);
        shelf(&mut pixels, palette);
        footer(&mut pixels, palette);
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
