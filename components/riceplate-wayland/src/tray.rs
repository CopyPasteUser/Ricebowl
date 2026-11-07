//! Small, bounded view of live StatusNotifier items for a native RicePlate.
//! The D-Bus host is handled by `status-notifier`; no arbitrary recipe paths
//! or commands can reach the bus. Pixmaps are untrusted and size checked.

use status_notifier::{Item, Pixmap};

pub const WIDTH: u32 = 112;
pub const SLOT_WIDTH: u32 = 28;
pub const VISIBLE_ITEMS: usize = 4;
pub const MAX_ITEMS: usize = 32;
pub const POPUP_WIDTH: u32 = 288;
pub const POPUP_HEIGHT: u32 = 240;
pub const POPUP_ROWS: usize = 5;
pub const POPUP_ROW_TOP: u32 = 44;
pub const POPUP_ROW_HEIGHT: u32 = 30;

pub fn screen_coords(output_origin: (i32, i32), output_size: (u32, u32),
                     panel_height: u32, top_panel: bool, popup: bool,
                     local: (f64, f64)) -> (i32, i32) {
    let left = if popup { output_size.0.saturating_sub(POPUP_WIDTH + 8) } else { 0 };
    let top = if popup {
        if top_panel { panel_height + 8 }
        else { output_size.1.saturating_sub(panel_height + 8 + POPUP_HEIGHT) }
    } else if top_panel { 0 }
    else { output_size.1.saturating_sub(panel_height) };
    (output_origin.0.saturating_add(left as i32).saturating_add(local.0 as i32),
     output_origin.1.saturating_add(top as i32).saturating_add(local.1 as i32))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PopupHit {
    Item(usize),
    Previous,
    Next,
    Close,
}

#[derive(Debug, Default)]
pub struct Popup {
    pub visible: bool,
    pub first: usize,
    pub selected: usize,
}

impl Popup {
    pub fn open(&mut self, entries: usize) {
        self.visible = true;
        self.first = (VISIBLE_ITEMS - 1).min(entries.saturating_sub(1));
        self.selected = self.first;
    }

    pub fn close(&mut self) {
        self.visible = false;
        self.first = 0;
        self.selected = 0;
    }

    pub fn select(&mut self, delta: isize, count: usize) {
        if count == 0 { return; }
        self.selected = self.selected.saturating_add_signed(delta).min(count - 1);
        if self.selected < self.first { self.first = self.selected; }
        if self.selected >= self.first + POPUP_ROWS {
            self.first = self.selected + 1 - POPUP_ROWS;
        }
    }

    pub fn page(&mut self, delta: isize, count: usize) {
        if count == 0 { return; }
        if (delta > 0 && self.first + POPUP_ROWS >= count) ||
            (delta < 0 && self.first == 0) { return; }
        let last = count - 1;
        self.first = self.first.saturating_add_signed(delta.saturating_mul(POPUP_ROWS as isize))
            .min(last);
        self.selected = self.first;
    }

    pub fn hit(&self, x: f64, y: f64, count: usize) -> Option<PopupHit> {
        if !x.is_finite() || !y.is_finite() || x < 0.0 || y < 0.0 ||
            x >= f64::from(POPUP_WIDTH) || y >= f64::from(POPUP_HEIGHT) { return None; }
        if y < 36.0 && x >= f64::from(POPUP_WIDTH - 44) {
            return Some(PopupHit::Close);
        }
        if y >= f64::from(POPUP_ROW_TOP) &&
            y < f64::from(POPUP_ROW_TOP + POPUP_ROWS as u32 * POPUP_ROW_HEIGHT) {
            let index = self.first + ((y as u32 - POPUP_ROW_TOP) / POPUP_ROW_HEIGHT) as usize;
            return (index < count).then_some(PopupHit::Item(index));
        }
        if y >= 202.0 {
            return Some(if x < f64::from(POPUP_WIDTH / 2) {
                PopupHit::Previous
            } else { PopupHit::Next });
        }
        None
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Icon {
    pub width: u32,
    pub height: u32,
    pub argb: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Entry {
    pub bus_name: String,
    pub title: String,
    pub icon: Option<Icon>,
    pub is_menu: bool,
    pub needs_attention: bool,
}

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct State {
    pub entries: Vec<Entry>,
}

impl State {
    pub fn from_items<'a>(items: impl Iterator<Item = (&'a String, &'a Item)>) -> Self {
        let mut entries: Vec<Entry> = items.filter_map(|(name, item)| {
            if !matches!(item.status.as_str(), "Active" | "NeedsAttention") ||
                name.len() > 255 || item.title.len() > 512 {
                return None;
            }
            let pixmaps = if item.status == "NeedsAttention" && !item.attention_icon_pixmap.is_empty() {
                &item.attention_icon_pixmap
            } else { &item.icon_pixmap };
            Some(Entry {
                bus_name: name.clone(),
                title: item.title.chars().take(48).collect(),
                icon: choose_pixmap(pixmaps),
                is_menu: item.item_is_menu,
                needs_attention: item.status == "NeedsAttention",
            })
        }).take(MAX_ITEMS).collect();
        // A stable order avoids focus jumping when D-Bus sends a property update.
        entries.sort_by(|a, b| b.needs_attention.cmp(&a.needs_attention)
            .then_with(|| a.bus_name.cmp(&b.bus_name)));
        Self { entries }
    }

    pub fn visible_count(&self) -> usize {
        if self.entries.len() > VISIBLE_ITEMS { VISIBLE_ITEMS - 1 }
        else { self.entries.len() }
    }

    pub fn overflow_count(&self) -> usize {
        self.entries.len().saturating_sub(self.visible_count())
    }

    pub fn item_at(&self, slot: usize) -> Option<&Entry> {
        if slot >= self.visible_count() { return None; }
        self.entries.get(slot)
    }
}

fn choose_pixmap(pixmaps: &[Pixmap]) -> Option<Icon> {
    pixmaps.iter().filter_map(|pixmap| {
        let [w, h] = pixmap.dimensions;
        if !(1..=64).contains(&w) || !(1..=64).contains(&h) ||
           pixmap.image_data.len() != (w * h * 4) as usize { return None; }
        Some(Icon { width: w as u32, height: h as u32, argb: pixmap.image_data.clone() })
    }).min_by_key(|icon| (icon.width.abs_diff(20) + icon.height.abs_diff(20),
                          icon.width * icon.height))
}

/// Copy a bounded ARGB32 (network-order) icon into an opaque 20x20 tile.
/// Sampling is nearest-neighbour. Alpha is explicitly blended into the theme.
pub fn paint_icon(canvas: &mut [u8], canvas_width: u32, canvas_height: u32,
                  x: u32, y: u32, icon: &Icon) {
    for dy in 0..20 {
        for dx in 0..20 {
            let tx = x + dx;
            let ty = y + dy;
            if tx >= canvas_width || ty >= canvas_height { continue; }
            let sx = dx * icon.width / 20;
            let sy = dy * icon.height / 20;
            let src = ((sy * icon.width + sx) * 4) as usize;
            let dst = ((ty * canvas_width + tx) * 4) as usize;
            let a = u32::from(icon.argb[src]);
            // Wayland's Argb8888 shared memory is BGRA in little-endian memory.
            for (channel, rgb_index) in [(0, 3), (1, 2), (2, 1)] {
                let foreground = u32::from(icon.argb[src + rgb_index]);
                let background = u32::from(canvas[dst + channel]);
                canvas[dst + channel] = ((foreground * a + background * (255 - a) + 127)
                    / 255) as u8;
            }
            canvas[dst + 3] = 255;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn item(status: &str, title: &str) -> Item {
        Item { status: status.into(), title: title.into(), ..Item::default() }
    }

    #[test]
    fn picks_valid_small_pixmap_and_blends_network_argb() {
        let valid = Pixmap { dimensions: [1, 1], image_data: vec![128, 200, 60, 20] };
        assert!(choose_pixmap(&[Pixmap { dimensions: [10000, 10000],
            image_data: vec![0] }, Pixmap { dimensions: [2, 2],
            image_data: vec![0; 3] }]).is_none());
        let icon = choose_pixmap(&[valid]).unwrap();
        let mut canvas = vec![255_u8; 20 * 20 * 4];
        paint_icon(&mut canvas, 20, 20, 0, 0, &icon);
        assert_eq!(canvas[3], 255);
        // BGR order: blue is the last RGB byte in protocol ARGB.
        assert!((137..=139).contains(&canvas[0]));
        assert!((156..=158).contains(&canvas[1]));
        assert!((227..=229).contains(&canvas[2]));
    }

    #[test]
    fn popup_coordinates_are_output_local_even_on_second_monitor() {
        assert_eq!(screen_coords((1920, 0), (1920, 1080), 36, false, false,
                                 (50.0, 18.0)), (1970, 1062));
        assert_eq!(screen_coords((1920, 0), (1920, 1080), 36, false, true,
                                 (10.0, 20.0)), (3554, 816));
        assert_eq!(screen_coords((-1280, 0), (1280, 800), 44, true, true,
                                 (10.0, 20.0)), (-286, 72));
    }

    #[test]
    fn ignores_passive_prioritizes_attention_and_bounds_visible_slots() {
        let mut raw = Vec::new();
        for idx in 0..6 {
            raw.push((format!("org.test.Item{idx}"), item("Active", "App")));
        }
        raw[5].1.status = "NeedsAttention".into();
        raw[1].1.status = "Passive".into();
        let state = State::from_items(raw.iter().map(|(name, item)| (name, item)));
        assert_eq!(state.entries.len(), 5);
        assert_eq!(state.entries[0].bus_name, "org.test.Item5");
        assert_eq!(state.visible_count(), 3);
        assert_eq!(state.overflow_count(), 2);
        assert_eq!(state.item_at(0).unwrap().bus_name, "org.test.Item5");
        assert!(state.item_at(3).is_none());
    }

    #[test]
    fn overflow_popup_paginates_and_rejects_out_of_bounds_actions() {
        let mut popup = Popup::default();
        popup.open(17);
        assert!(popup.visible);
        assert_eq!(popup.first, 3);
        assert_eq!(popup.hit(18.0, 44.0, 17), Some(PopupHit::Item(3)));
        popup.page(1, 17);
        assert_eq!(popup.first, 8);
        assert_eq!(popup.hit(18.0, 44.0, 17), Some(PopupHit::Item(8)));
        popup.page(100, 17);
        assert_eq!(popup.first, 16);
        popup.select(-99, 17);
        assert_eq!(popup.selected, 0);
        assert_eq!(popup.first, 0);
        assert_eq!(popup.hit(18.0, 44.0, 0), None);
        assert_eq!(popup.hit(f64::NAN, 20.0, 17), None);
        assert_eq!(popup.hit(260.0, 8.0, 17), Some(PopupHit::Close));
        popup.close();
        assert!(!popup.visible);

        popup.open(4);
        popup.page(1, 4);
        assert_eq!(popup.first, 3, "no phantom next page past a short final page");
    }
}
