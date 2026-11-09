//! Deterministic icon placement in the logical dimensions of one Wayland output.
//! No file access, timers or per-frame work: recompute only on output changes.

use crate::recipe::{DesktopComposition, DesktopIcon, WindowRegion,
                    DESKTOP_WIDGET_HEIGHT, DESKTOP_WIDGET_WIDTH, ICON_HEIGHT, ICON_WIDTH};

const GAP: u32 = 8;
pub const MAX_SAVED_POSITION: u32 = 16_384;

/// Cycle a keyboard selection through visible icon surfaces only. A hidden
/// icon must never receive Enter or keyboard-movement actions.
pub fn navigate(visible: &[bool], current: usize, delta: isize) -> Option<usize> {
    if visible.is_empty() || !visible.iter().any(|&item| item) { return None; }
    let mut next = current % visible.len();
    for _ in 0..visible.len() {
        next = (next as isize + delta).rem_euclid(visible.len() as isize) as usize;
        if visible[next] { return Some(next); }
    }
    None
}

/// Wayland pointer coordinates are surface-relative, including during a grab.
/// Use the current surface placement to prevent jumps as its margin moves.
pub fn dragged_to(current: (u32, u32), anchor: (f64, f64), pointer: (f64, f64)) -> (u32, u32) {
    let moved = |origin: u32, delta: f64| {
        (f64::from(origin) + delta).round().clamp(0.0, f64::from(MAX_SAVED_POSITION)) as u32
    };
    (moved(current.0, pointer.0 - anchor.0),
     moved(current.1, pointer.1 - anchor.1))
}

/// Resolve a drop on a different logical output from the grabbed icon surface.
/// The implicit Wayland pointer grab continues delivering surface-relative
/// motion even after the cursor crosses the source output boundary.
pub fn cross_output_drop(
    source_origin: (i32, i32), current: (u32, u32),
    pointer: (f64, f64), anchor: (f64, f64),
    target_origin: (i32, i32), target_size: (u32, u32),
) -> Option<(u32, u32)> {
    if ![pointer.0, pointer.1, anchor.0, anchor.1].iter().all(|v| v.is_finite())
        || target_size.0 < ICON_WIDTH || target_size.1 < ICON_HEIGHT
    {
        return None;
    }
    let global = (f64::from(source_origin.0) + f64::from(current.0) + pointer.0,
                  f64::from(source_origin.1) + f64::from(current.1) + pointer.1);
    let local = (global.0 - f64::from(target_origin.0),
                 global.1 - f64::from(target_origin.1));
    if !(0.0..f64::from(target_size.0)).contains(&local.0)
        || !(0.0..f64::from(target_size.1)).contains(&local.1)
    {
        return None;
    }
    Some(((local.0 - anchor.0).round().clamp(0.0, f64::from(MAX_SAVED_POSITION)) as u32,
          (local.1 - anchor.1).round().clamp(0.0, f64::from(MAX_SAVED_POSITION)) as u32))
}

#[cfg(test)]
fn overlaps(x: u32, y: u32, other_x: u32, other_y: u32) -> bool {
    x.abs_diff(other_x) < ICON_WIDTH && y.abs_diff(other_y) < ICON_HEIGHT
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct Rect {
    x: u32,
    y: u32,
    w: u32,
    h: u32,
}

impl Rect {
    fn intersects(self, other: Rect) -> bool {
        self.x < other.x + other.w && other.x < self.x + self.w
            && self.y < other.y + other.h && other.y < self.y + self.h
    }
}

fn reserved_region(region: WindowRegion, width: u32, height: u32) -> Rect {
    Rect { x: width * region.x / 100, y: height * region.y / 100,
           w: width * region.width / 100, h: height * region.height / 100 }
}

fn place_rects(
    requested: &[(u32, u32)], item_w: u32, item_h: u32,
    width: u32, height: u32, panel_top: bool, panel_height: u32,
    reserved: &[Rect],
) -> Vec<Option<(u32, u32)>> {
    let upper = if panel_top { panel_height.saturating_add(GAP) } else { GAP };
    let lower = if panel_top { GAP } else { panel_height.saturating_add(GAP) };
    let Some(max_y) = height.checked_sub(lower.saturating_add(item_h)) else {
        return vec![None; requested.len()];
    };
    let Some(max_x) = width.checked_sub(item_w) else {
        return vec![None; requested.len()];
    };
    if max_y < upper { return vec![None; requested.len()]; }
    let mut placed = Vec::new();
    let mut result = Vec::with_capacity(requested.len());
    for &(x, y) in requested {
        let desired = (x.min(max_x), y.clamp(upper, max_y));
        let free = |(x, y): (u32, u32)| {
            let candidate = Rect { x, y, w: item_w, h: item_h };
            reserved.iter().chain(placed.iter()).all(|other| !candidate.intersects(*other))
        };
        let selected = if free(desired) { Some(desired) } else {
            // Search the full supported logical coordinate range, not just
            // the first N columns. On wide displays a reserved window region
            // can occupy that prefix, hiding icons despite free space on the
            // right. Cap compositor-reported dimensions to the same bounded
            // coordinate range as saved positions; malformed giant modes
            // must not cause millions of geometry checks or UI stalls.
            let step_x = item_w.saturating_add(GAP).max(1);
            let step_y = item_h.saturating_add(GAP).max(1);
            let search_max_x = max_x.min(MAX_SAVED_POSITION);
            let search_max_y = max_y.min(upper.saturating_add(MAX_SAVED_POSITION));
            let cols = search_max_x / step_x;
            let rows = (search_max_y - upper) / step_y;
            let mut best: Option<((u32, u32, u32), (u32, u32))> = None;
            for row in 0..=rows.saturating_add(1) {
                let y = if row > rows { search_max_y } else { upper + row * step_y };
                for col in 0..=cols.saturating_add(1) {
                    let x = if col > cols { search_max_x } else { col * step_x };
                    let candidate = (x, y);
                    if !free(candidate) { continue; }
                    let key = (x.abs_diff(desired.0) + y.abs_diff(desired.1), y, x);
                    if best.as_ref().is_none_or(|(current, _)| key < *current) {
                        best = Some((key, candidate));
                    }
                }
            }
            best.map(|(_, candidate)| candidate)
        };
        if let Some((x, y)) = selected {
            placed.push(Rect { x, y, w: item_w, h: item_h });
        }
        result.push(selected);
    }
    result
}

/// Preserve each requested position if possible. Displaced icons use the
/// nearest free bounded grid cell; None means there is no safe hit area.
pub fn place(
    icons: &[DesktopIcon], width: u32, height: u32, panel_top: bool, panel_height: u32,
) -> Vec<Option<(u32, u32)>> {
    place_visible(icons, &vec![true; icons.len()], width, height, panel_top, panel_height)
}

/// Hidden shortcuts must not occupy layout cells or prevent widgets from
/// using the freed space. Keep the returned indices aligned with the recipe.
pub fn place_visible(
    icons: &[DesktopIcon], visible: &[bool], width: u32, height: u32,
    panel_top: bool, panel_height: u32,
) -> Vec<Option<(u32, u32)>> {
    let active: Vec<_> = icons.iter().enumerate()
        .filter(|(index, _)| visible.get(*index).copied().unwrap_or(false))
        .map(|(index, icon)| (index, (icon.x, icon.y))).collect();
    let requests: Vec<_> = active.iter().map(|(_, pos)| *pos).collect();
    let placed = place_rects(&requests, ICON_WIDTH, ICON_HEIGHT,
                             width, height, panel_top, panel_height, &[]);
    let mut result = vec![None; icons.len()];
    for ((index, _), position) in active.into_iter().zip(placed) {
        result[index] = position;
    }
    result
}

/// One deterministic cross-region plan. Client windows are not moved; the
/// declared region stays free of desktop items so labwc can place them there.
pub fn compose(
    icons: &[DesktopIcon], composition: &DesktopComposition, width: u32, height: u32,
    panel_top: bool, panel_height: u32, compact_max_width: u32,
) -> (Vec<Option<(u32, u32)>>, Vec<Option<(u32, u32)>>) {
    compose_visible(icons, &vec![true; icons.len()], composition, width, height,
                    panel_top, panel_height, compact_max_width)
}

pub fn compose_visible(
    icons: &[DesktopIcon], visible: &[bool], composition: &DesktopComposition,
    width: u32, height: u32, panel_top: bool, panel_height: u32,
    compact_max_width: u32,
) -> (Vec<Option<(u32, u32)>>, Vec<Option<(u32, u32)>>) {
    let region = reserved_region(composition.window_region, width, height);
    let active_icons: Vec<_> = icons.iter().enumerate()
        .filter(|(index, _)| visible.get(*index).copied().unwrap_or(false))
        .map(|(index, icon)| (index, (icon.x, icon.y))).collect();
    let icon_requests: Vec<_> = active_icons.iter().map(|(_, pos)| *pos).collect();
    let placed_icons = place_rects(&icon_requests, ICON_WIDTH, ICON_HEIGHT,
                                   width, height, panel_top, panel_height, &[region]);
    let mut icon_positions = vec![None; icons.len()];
    for ((index, _), position) in active_icons.into_iter().zip(placed_icons) {
        icon_positions[index] = position;
    }
    let mut reserved = vec![region];
    for &(x, y) in icon_positions.iter().flatten() {
        reserved.push(Rect { x, y, w: ICON_WIDTH, h: ICON_HEIGHT });
    }
    let active: Vec<_> = composition.widgets.iter().enumerate()
        .filter(|(_, widget)| width > compact_max_width
            || !composition.compact_hide_widgets.contains(&widget.id))
        .map(|(index, widget)| (index, (widget.x, widget.y))).collect();
    let requests: Vec<_> = active.iter().map(|(_, position)| *position).collect();
    let placed = place_rects(&requests, DESKTOP_WIDGET_WIDTH, DESKTOP_WIDGET_HEIGHT,
                             width, height, panel_top, panel_height, &reserved);
    let mut widgets = vec![None; composition.widgets.len()];
    for ((index, _), position) in active.into_iter().zip(placed) {
        widgets[index] = position;
    }
    (icon_positions, widgets)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::recipe::{DesktopWidget, DesktopWidgetKind};

    fn icon(x: u32, y: u32) -> DesktopIcon {
        DesktopIcon { label: "Apps".into(), action: "applications".into(), x, y }
    }

    fn composition() -> DesktopComposition {
        DesktopComposition {
            widgets: vec![
                DesktopWidget { id: "desk-clock".into(), kind: DesktopWidgetKind::Clock,
                                x: 32, y: 320, title: None },
                DesktopWidget { id: "desk-system".into(), kind: DesktopWidgetKind::System,
                                x: 32, y: 432, title: None },
            ],
            window_region: WindowRegion { x: 30, y: 8, width: 66, height: 84 },
            compact_hide_widgets: vec!["desk-system".into()],
        }
    }

    #[test]
    fn v8_avoids_window_workarea_and_cross_region_widget_collisions() {
        let icons = [icon(32, 96), icon(32, 208)];
        for (width, height) in [(1920, 1080), (1366, 768), (1093, 614), (640, 480)] {
            let (icon_placements, widget_placements) = compose(
                &icons, &composition(), width, height, true, 44, 840);
            assert_eq!(icon_placements.len(), icons.len());
            assert_eq!(widget_placements.len(), 2);
            let window = reserved_region(composition().window_region, width, height);
            let mut covered = Vec::new();
            for (x, y) in icon_placements.iter().flatten() {
                covered.push(Rect { x: *x, y: *y, w: ICON_WIDTH, h: ICON_HEIGHT });
            }
            for (x, y) in widget_placements.iter().flatten() {
                covered.push(Rect { x: *x, y: *y,
                                    w: DESKTOP_WIDGET_WIDTH, h: DESKTOP_WIDGET_HEIGHT });
            }
            for (index, region) in covered.iter().enumerate() {
                assert!(!region.intersects(window));
                assert!(region.x + region.w <= width);
                assert!(region.y + region.h <= height);
                assert!(covered.iter().skip(index + 1).all(|other|
                    !region.intersects(*other)));
            }
            if width <= 840 { assert!(widget_placements[1].is_none()); }
        }
    }

    #[test]
    fn filtered_icons_free_space_for_visible_icons_and_widgets() {
        let icons = [icon(32, 96), icon(32, 96)];
        let standalone = place_visible(&icons, &[false, true], 800, 600, true, 44);
        assert_eq!(standalone, vec![None, Some((32, 96))]);
        let with_widgets = compose_visible(&icons, &[false, true], &composition(),
                                           800, 600, true, 44, 640);
        assert_eq!(with_widgets.0[0], None);
        assert_eq!(with_widgets.0[1], Some((32, 96)));
        assert!(with_widgets.1.iter().flatten().all(|(x, y)|
            !overlaps(*x, *y, 32, 96)));
        assert_eq!(place_visible(&icons, &[], 800, 600, true, 44), vec![None, None]);
    }

    #[test]
    fn keyboard_navigation_skips_hidden_icons_and_wraps() {
        let visible = [true, false, true, false];
        assert_eq!(navigate(&visible, 0, 1), Some(2));
        assert_eq!(navigate(&visible, 2, 1), Some(0));
        assert_eq!(navigate(&visible, 0, -1), Some(2));
        assert_eq!(navigate(&[false, false], 0, 1), None);
        assert_eq!(navigate(&[], 0, 1), None);
    }

    #[test]
    fn preserves_positions_on_large_output_without_hidden_overlaps() {
        let originals = [icon(32, 96), icon(32, 208), icon(152, 96)];
        assert_eq!(place(&originals, 1920, 1080, true, 40),
                   vec![Some((32, 96)), Some((32, 208)), Some((152, 96))]);
    }

    #[test]
    fn clamps_at_small_and_fractionally_scaled_logical_output_boundaries() {
        let originals = [icon(990, 700), icon(4000, 4000), icon(32, 96)];
        for (width, height) in [(1024, 768), (1093, 614)] {
            let positions = place(&originals, width, height, true, 40);
            assert!(positions.iter().all(Option::is_some));
            for (index, position) in positions.iter().enumerate() {
                let (x, y) = position.unwrap();
                assert!(x + ICON_WIDTH <= width, "icon {index} exceeds width");
                assert!(y >= 48 && y + ICON_HEIGHT <= height - GAP);
            }
            for left in 0..positions.len() {
                for right in (left + 1)..positions.len() {
                    let (x, y) = positions[left].unwrap();
                    let (other_x, other_y) = positions[right].unwrap();
                    assert!(!overlaps(x, y, other_x, other_y));
                }
            }
        }
    }

    #[test]
    fn reserves_bottom_panel_and_hides_icons_if_no_safe_hit_area() {
        let original = [icon(32, 700), icon(32, 700)];
        let placed = place(&original, 640, 480, false, 48);
        assert!(placed.iter().all(Option::is_some));
        assert!(placed.iter().all(|p| p.unwrap().1 + ICON_HEIGHT <= 424));
        assert_eq!(place(&original, 90, 300, true, 40), vec![None, None]);
        assert_eq!(place(&original, 640, 120, false, 48), vec![None, None]);
    }

    #[test]
    fn bounded_search_never_maps_multiple_icons_onto_one_pixel_region() {
        let eight: Vec<_> = (0..8).map(|i| icon(i * 104, 96)).collect();
        let placed = place(&eight, 104, 480, true, 40);
        assert!(placed.iter().any(Option::is_none));
        let visible: Vec<_> = placed.into_iter().flatten().collect();
        for (index, &(x, y)) in visible.iter().enumerate() {
            assert!(visible.iter().skip(index + 1).all(|&(ox, oy)|
                    !overlaps(x, y, ox, oy)));
        }
    }

    #[test]
    fn wide_output_reaches_free_cells_beyond_the_first_icon_columns() {
        let icons = [(64, 96), (64, 96)];
        let region = Rect { x: 0, y: 0, w: 3000, h: 2160 };
        let result = place_rects(&icons, ICON_WIDTH, ICON_HEIGHT, 3840, 2160,
                                 true, 44, &[region]);
        let first = result[0].expect("free right-hand output area must stay reachable");
        let second = result[1].expect("second icon must also be placeable");
        assert!(first.0 >= 3000 && second.0 >= 3000);
        assert!(!overlaps(first.0, first.1, second.0, second.1));
        assert_eq!(result, place_rects(&icons, ICON_WIDTH, ICON_HEIGHT, 3840, 2160,
                                       true, 44, &[region]), "reflow must be deterministic");
    }

    #[test]
    fn layout_reflow_recovers_after_output_mode_changes() {
        let icons = [(32, 96), (32, 96), (32, 96)];
        let region = Rect { x: 0, y: 0, w: 1500, h: 900 };
        let wide = place_rects(&icons, ICON_WIDTH, ICON_HEIGHT, 1920, 900,
                               false, 40, &[region]);
        assert!(wide.iter().all(Option::is_some));
        let small = place_rects(&icons, ICON_WIDTH, ICON_HEIGHT, 640, 480,
                                false, 40, &[]);
        assert!(small.iter().all(Option::is_some));
        assert_eq!(wide, place_rects(&icons, ICON_WIDTH, ICON_HEIGHT, 1920, 900,
                                      false, 40, &[region]));
    }

    #[test]
    fn malformed_giant_output_does_not_expand_the_collision_search() {
        let region = Rect { x: 0, y: 0, w: 2048, h: 2048 };
        let icon = [(32, 96)];
        let result = place_rects(&icon, ICON_WIDTH, ICON_HEIGHT, 1_000_000, 1_000_000,
                                 true, 44, &[region]);
        let (x, y) = result[0].expect("bounded coordinates still offer free space");
        assert!(x <= MAX_SAVED_POSITION && y <= MAX_SAVED_POSITION + 52);
        assert!(x >= 2048 || y >= 2048);
    }

    #[test]
    fn pointer_motion_translates_positions_without_underflow_or_jumps() {
        assert_eq!(dragged_to((32, 96), (20.0, 10.0), (60.0, 30.0)), (72, 116));
        assert_eq!(dragged_to((72, 116), (20.0, 10.0), (20.0, 10.0)), (72, 116));
        assert_eq!(dragged_to((32, 96), (20.0, 10.0), (-200.0, -200.0)), (0, 0));
        assert_eq!(dragged_to((16_380, 16_380), (0.0, 0.0), (100.0, 100.0)),
                   (MAX_SAVED_POSITION, MAX_SAVED_POSITION));
    }

    #[test]
    fn cross_monitor_drop_uses_logical_geometry_and_pointer_grab() {
        assert_eq!(cross_output_drop((0, 0), (1880, 220), (190.0, 20.0),
                                     (20.0, 10.0), (1920, 0), (1280, 1024)), Some((130, 230)));
        // A monitor left of the primary has a negative global origin.
        assert_eq!(cross_output_drop((0, 0), (10, 30), (-40.0, 15.0),
                                     (15.0, 10.0), (-1280, 0), (1280, 800)), Some((1235, 35)));
        // A cursor in the output gap is not a drop on either display.
        assert_eq!(cross_output_drop((0, 0), (1880, 220), (190.0, 20.0),
                                     (20.0, 10.0), (2200, 0), (1280, 1024)), None);
        assert_eq!(cross_output_drop((0, 0), (1800, 220), (f64::NAN, 10.0),
                                     (20.0, 10.0), (1920, 0), (1280, 1024)), None);
        assert_eq!(cross_output_drop((0, 0), (1800, 220), (200.0, 10.0),
                                     (20.0, 10.0), (1920, 0), (40, 30)), None);
    }
}
