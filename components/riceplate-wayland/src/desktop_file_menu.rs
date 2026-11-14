//! Pure, bounded XP Luna context model for real XDG Desktop items.
//! The model never spawns an opener, issues filesystem writes or trusts a recipe.
use crate::desktop_context::{file_permission, FileAction, FilePermission};
use crate::desktop_layout::inventory::Kind;

pub const WIDTH: u32 = 246;
pub const HEIGHT: u32 = 234;
const FIRST: u32 = 40;
const ROW_HEIGHT: u32 = 29;
pub const BACK_ROW: u32 = 191;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Item { Open, Explorer, Rename, Trash, Properties }

impl Item {
    pub const ALL: [Self; 5] =
        [Self::Open, Self::Explorer, Self::Rename, Self::Trash, Self::Properties];
    pub fn index(self) -> usize {
        match self {
            Self::Open => 0, Self::Explorer => 1, Self::Rename => 2,
            Self::Trash => 3, Self::Properties => 4,
        }
    }
    pub fn label(self) -> &'static str {
        match self {
            Self::Open => "Open",
            Self::Explorer => "Open in RiceField",
            Self::Rename => "Rename  (F2)",
            Self::Trash => "Move to Trash  (Del)",
            Self::Properties => "Properties",
        }
    }
    pub fn permission(self, kind: Kind) -> FilePermission {
        let action = match self {
            Self::Open => FileAction::Open,
            Self::Explorer => FileAction::OpenInExplorer,
            Self::Rename => FileAction::Rename,
            Self::Trash => FileAction::MoveToTrash,
            Self::Properties => FileAction::Properties,
        };
        file_permission(action, kind)
    }
    pub fn enabled(self, kind: Kind) -> bool {
        self.permission(kind) != FilePermission::Disabled
    }
}

pub fn row(item: Item) -> u32 { FIRST + item.index() as u32 * ROW_HEIGHT }

pub fn hit(x: f64, y: f64, kind: Kind) -> Option<Item> {
    if !x.is_finite() || !y.is_finite() || !(5.0..f64::from(WIDTH - 5)).contains(&x)
        || !(f64::from(FIRST)..f64::from(FIRST + ROW_HEIGHT * 5)).contains(&y) {
        return None;
    }
    let item = Item::ALL[((y as u32 - FIRST) / ROW_HEIGHT) as usize];
    item.enabled(kind).then_some(item)
}

pub fn back_hit(x: f64, y: f64) -> bool {
    x.is_finite() && y.is_finite() && (5.0..f64::from(WIDTH - 5)).contains(&x)
        && (f64::from(BACK_ROW)..f64::from(BACK_ROW + ROW_HEIGHT)).contains(&y)
}

pub fn navigate(current: Item, delta: i32, kind: Kind) -> Item {
    let mut index = current.index() as i32;
    for _ in 0..Item::ALL.len() {
        index = (index + delta).rem_euclid(Item::ALL.len() as i32);
        let item = Item::ALL[index as usize];
        if item.enabled(kind) { return item; }
    }
    current
}

pub fn placement(icon: (u32, u32), pointer: (f64, f64), output: (u32, u32),
                 panel: u32, top: bool) -> Option<(u32, u32)> {
    if !pointer.0.is_finite() || !pointer.1.is_finite()
        || !(0.0..f64::from(crate::recipe::ICON_WIDTH)).contains(&pointer.0)
        || !(0.0..f64::from(crate::recipe::ICON_HEIGHT)).contains(&pointer.1) {
        return None;
    }
    let upper = if top { panel } else { 0 };
    let bottom = if top { 0 } else { panel };
    if output.0 < WIDTH || output.1 < HEIGHT + upper + bottom { return None; }
    Some((icon.0.saturating_add(pointer.0.round() as u32).min(output.0 - WIDTH),
          icon.1.saturating_add(pointer.1.round() as u32)
              .clamp(upper, output.1 - HEIGHT - bottom)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn actions_are_bounded_and_untrusted_entries_have_properties_only() {
        for kind in [Kind::File, Kind::Directory] {
            for item in Item::ALL {
                assert_eq!(hit(20.0, f64::from(row(item) + 13), kind), Some(item));
            }
            assert_eq!(navigate(Item::Properties, 1, kind), Item::Open);
        }
        for kind in [Kind::Symlink, Kind::DesktopFile] {
            for item in Item::ALL {
                assert_eq!(item.enabled(kind), item == Item::Properties);
            }
            assert_eq!(navigate(Item::Properties, 1, kind), Item::Properties);
            assert_eq!(hit(20.0, f64::from(row(Item::Trash) + 12), kind), None);
        }
        for (x, y) in [(f64::NAN, 50.0), (0.0, 50.0),
                       (20.0, -1.0), (20.0, 190.0), (246.0, 66.0)] {
            assert_eq!(hit(x, y, Kind::File), None);
        }
        assert!(back_hit(32.0, f64::from(BACK_ROW + 10)));
        assert!(!back_hit(246.0, f64::from(BACK_ROW + 10)));
    }

    #[test]
    fn popup_clamps_on_all_edges_and_never_overlaps_panel() {
        assert_eq!(placement((32, 100), (42.0, 16.0),
            (1366, 768), 40, false), Some((74, 116)));
        assert_eq!(placement((1200, 730), (80.0, 42.0),
            (1366, 768), 40, false), Some((1120, 494)));
        assert_eq!(placement((0, 0), (1.0, 1.0),
            (246, 274), 40, true), Some((0, 40)));
        assert_eq!(placement((0, 0), (1.0, 1.0),
            (245, 768), 40, false), None);
    }
}
