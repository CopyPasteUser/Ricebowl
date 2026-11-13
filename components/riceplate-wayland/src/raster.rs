//! Shared ARGB8888 raster primitives for native RicePlate surfaces.
//!
//! All callers use tightly packed, little-endian pixels. Clip against both
//! the advertised surface geometry and the number of *complete* buffer rows;
//! malformed or stale buffers must never panic during a compositor redraw.

fn visible_rows(canvas: &[u8], width: u32, height: u32) -> Option<(usize, u32)> {
    let stride = (width as usize).checked_mul(4)?;
    if stride == 0 { return None; }
    let rows = (canvas.len() / stride).min(height as usize);
    Some((stride, rows as u32))
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn fill_rect(
    canvas: &mut [u8], width: u32, height: u32,
    x: u32, y: u32, w: u32, h: u32, color: u32,
) {
    let Some((stride, rows)) = visible_rows(canvas, width, height) else { return; };
    let right = x.saturating_add(w).min(width);
    let bottom = y.saturating_add(h).min(rows);
    if x >= right || y >= bottom { return; }

    let rgba = color.to_le_bytes();
    for row in y as usize..bottom as usize {
        let start = row * stride + x as usize * 4;
        let end = row * stride + right as usize * 4;
        for pixel in canvas[start..end].chunks_exact_mut(4) {
            pixel.copy_from_slice(&rgba);
        }
    }
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn fill_rounded_rect(
    canvas: &mut [u8], width: u32, height: u32,
    x: u32, y: u32, w: u32, h: u32, radius: u32, color: u32,
) {
    let r = radius.min(w / 2).min(h / 2);
    if r == 0 {
        fill_rect(canvas, width, height, x, y, w, h, color);
        return;
    }
    let Some((stride, rows)) = visible_rows(canvas, width, height) else { return; };
    let max_x = w.min(width.saturating_sub(x));
    let max_y = h.min(rows.saturating_sub(y));
    if max_x == 0 || max_y == 0 { return; }

    // Preserve the original integer-circle mask; changing antialiasing here
    // would alter every recipe's screenshot and keyboard focus outlines.
    let corner = (i64::from(r) - 1).pow(2);
    let rgba = color.to_le_bytes();
    for py in 0..max_y {
        let base = (y + py) as usize * stride + x as usize * 4;
        for px in 0..max_x {
            let dx = if px < r { r - 1 - px } else { px.saturating_sub(w - r) };
            let dy = if py < r { r - 1 - py } else { py.saturating_sub(h - r) };
            if i64::from(dx).pow(2) + i64::from(dy).pow(2) <= corner {
                let index = base + px as usize * 4;
                canvas[index..index + 4].copy_from_slice(&rgba);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pixel(frame: &[u8], width: usize, x: usize, y: usize) -> [u8; 4] {
        frame[(y * width + x) * 4..(y * width + x + 1) * 4]
            .try_into().unwrap()
    }

    #[test]
    fn rectangle_clips_to_surface_and_preserves_byte_order() {
        let mut frame = vec![0_u8; 4 * 3 * 4];
        fill_rect(&mut frame, 4, 3, 2, 1, 40, 40, 0x1122_3344);
        assert_eq!(pixel(&frame, 4, 1, 1), [0, 0, 0, 0]);
        assert_eq!(pixel(&frame, 4, 2, 1), [0x44, 0x33, 0x22, 0x11]);
        assert_eq!(pixel(&frame, 4, 3, 2), [0x44, 0x33, 0x22, 0x11]);
        assert_eq!(pixel(&frame, 4, 2, 0), [0, 0, 0, 0]);
    }

    #[test]
    fn truncated_buffers_and_overflowing_coordinates_are_safe() {
        let mut frame = vec![0_u8; 4 * 3]; // one complete row of a 3x3 surface
        fill_rect(&mut frame, 3, 3, 0, 0, 3, 3, 0xffff_ffff);
        assert!(frame.iter().all(|value| *value == 255));
        fill_rounded_rect(&mut frame, 3, 3, 0, 0, 3, 3, 1, 0xff12_3456);
        assert_eq!(pixel(&frame, 3, 1, 0), [0x56, 0x34, 0x12, 0xff]);
        fill_rect(&mut frame, 3, 3, u32::MAX, u32::MAX, 10, 10, 0);
        fill_rounded_rect(&mut frame, 3, 3, u32::MAX, 0, 5, 5, 2, 0);
        fill_rect(&mut [], 0, 0, 0, 0, u32::MAX, u32::MAX, 0);
        fill_rounded_rect(&mut [], 0, 0, 0, 0, 0, 0, 0, 0);
        assert_eq!(pixel(&frame, 3, 1, 0), [0x56, 0x34, 0x12, 0xff]);
    }

    #[test]
    fn rounded_mask_keeps_exact_hard_corners() {
        let mut frame = vec![0_u8; 6 * 6 * 4];
        fill_rounded_rect(&mut frame, 6, 6, 0, 0, 6, 6, 2, 0xff12_3456);
        assert_eq!(pixel(&frame, 6, 0, 0), [0; 4]);
        assert_eq!(pixel(&frame, 6, 1, 0), [0x56, 0x34, 0x12, 0xff]);
        assert_eq!(pixel(&frame, 6, 3, 3), [0x56, 0x34, 0x12, 0xff]);
        assert_eq!(pixel(&frame, 6, 5, 5), [0; 4]);
    }

    #[test]
    fn partial_last_row_remains_untouched() {
        let mut frame = vec![0_u8; 2 * 4 + 3];
        fill_rect(&mut frame, 2, 2, 0, 0, 2, 2, 0xffaa_bbcc);
        assert_eq!(&frame[..8], &[0xcc, 0xbb, 0xaa, 0xff, 0xcc, 0xbb, 0xaa, 0xff]);
        assert_eq!(&frame[8..], &[0, 0, 0]);
    }
}
