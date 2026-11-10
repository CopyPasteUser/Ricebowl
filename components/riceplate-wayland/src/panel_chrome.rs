//! Rich taskbar treatment for recipes which opt in to a decorated launcher.
//! No special case for XP: undecorated v1–v11 recipes keep their exact pixels.

use crate::{
    fill_rect, fill_rounded_rect,
    recipe::{LauncherDecoration, PanelStyle, PlacedWidget, Widget},
};

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
    let inset = decoration.radius.max(5);
    if span > 2 * inset {
        fill_rect(canvas, width, height, x + inset, 4,
                  span - 2 * inset, 1,
                  mix_rgb(decoration.background, 0xffff_ffff, 135));
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
              span - 12, 1, mix_rgb(base, 0xffff_ffff, 85));
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
        assert_eq!(px(&pixels, 400, 45, 20), decor.background);
        task_button(&mut pixels, 400, 40, 100, 130, false, &style);
        let inactive = px(&pixels, 400, 110, 20);
        task_button(&mut pixels, 400, 40, 100, 130, true, &style);
        assert_ne!(inactive, px(&pixels, 400, 110, 20));
    }

    #[test]
    fn tiny_surfaces_do_not_panic() {
        let style = luna();
        let mut pixels = vec![0_u8; 12 * 8 * 4];
        background(&mut pixels, 12, 8, &style, &[]);
        task_button(&mut pixels, 12, 8, 0, 4, true, &style);
        launcher(&mut pixels, 12, 8, 0, 4, style.launcher.as_ref().unwrap());
    }
}
