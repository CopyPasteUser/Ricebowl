//! Optional, owner-private coordinates for the currently selected rice.
//! Source recipes remain immutable; Creator/headless previews ignore overrides.

use std::{
    collections::BTreeMap,
    env,
    error::Error,
    fs::{self, DirBuilder, OpenOptions},
    io::{Read, Write},
    os::unix::fs::{DirBuilderExt, MetadataExt, OpenOptionsExt},
    path::PathBuf,
    time::{SystemTime, UNIX_EPOCH},
};

use serde::{Deserialize, Serialize};

use crate::{desktop_layout::MAX_SAVED_POSITION, recipe::{DesktopIcon, PanelStyle}};

const MAX_BYTES: u64 = 4096;
const MAX_OUTPUTS: usize = 8;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Coordinates {
    pub x: u32,
    pub y: u32,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct OutputPositions {
    positions: BTreeMap<String, Vec<Coordinates>>,
    // Empty means the historical mirrored-desktop behavior on every output.
    // An explicit owner exists only after the user moves an icon to a display.
    owners: Vec<Option<String>>,
}

impl OutputPositions {
    pub fn for_output(&self, name: &str, icon_count: usize) -> Option<&[Coordinates]> {
        self.positions.get(name).filter(|items| items.len() == icon_count)
            .map(Vec::as_slice)
    }

    pub fn set(&mut self, name: &str, icons: &[DesktopIcon], index: usize,
               coords: Coordinates) -> Result<(), Box<dyn Error>> {
        if !safe_output_name(name) || index >= icons.len()
            || coords.x > MAX_SAVED_POSITION || coords.y > MAX_SAVED_POSITION
        {
            return Err("Invalid output name or icon position".into());
        }
        if !self.positions.contains_key(name) && self.positions.len() >= MAX_OUTPUTS {
            return Err("Too many saved display layouts".into());
        }
        let values = self.positions.entry(name.to_owned()).or_insert_with(|| icons.iter()
            .map(|icon| Coordinates { x: icon.x, y: icon.y }).collect());
        if values.len() != icons.len() {
            return Err("Icon layout is incompatible with this rice".into());
        }
        values[index] = coords;
        Ok(())
    }

    /// Only a per-output override different from the immutable recipe
    /// position is resettable. Unknown and malformed displays are not
    /// silently initialized by a Reset click.
    pub fn can_reset_position(&self, name: &str, icons: &[DesktopIcon],
                              index: usize) -> bool {
        safe_output_name(name) && self.for_output(name, icons.len())
            .and_then(|positions| positions.get(index))
            .zip(icons.get(index))
            .is_some_and(|(position, icon)|
                position.x != icon.x || position.y != icon.y)
    }

    /// Restore just one shortcut on one named monitor. Never change the
    /// source recipe, other monitors, desktop ownership, or unrelated icons.
    /// Returns false without writing when already at default.
    pub fn reset_position(&mut self, name: &str, icons: &[DesktopIcon],
                          index: usize) -> Result<bool, Box<dyn Error>> {
        if !safe_output_name(name) || index >= icons.len() {
            return Err("Invalid display or icon index".into());
        }
        let Some(positions) = self.positions.get_mut(name) else {
            return Ok(false);
        };
        if positions.len() != icons.len() {
            return Err("Icon layout is incompatible with this rice".into());
        }
        let expected = Coordinates { x: icons[index].x, y: icons[index].y };
        if positions[index] == expected { return Ok(false); }
        positions[index] = expected;
        Ok(true)
    }

    pub fn owner(&self, index: usize) -> Option<&str> {
        self.owners.get(index).and_then(Option::as_deref)
    }

    /// A missing assigned monitor must not strand its shortcut off-screen.
    /// The primary unbound layer is the temporary recovery surface until the
    /// saved monitor is reconnected; unassigned icons remain mirrored.
    pub fn visible_on(&self, index: usize, name: Option<&str>, is_primary: bool,
                      connected: &[String]) -> bool {
        match self.owner(index) {
            None => true,
            Some(owner) if connected.iter().any(|available| available == owner) =>
                name == Some(owner),
            Some(_) => is_primary,
        }
    }

    pub fn assign(&mut self, icons: &[DesktopIcon], index: usize,
                  owner: Option<&str>) -> Result<(), Box<dyn Error>> {
        if index >= icons.len() || owner.is_some_and(|name| !safe_output_name(name)) {
            return Err("Invalid display assignment".into());
        }
        if self.owners.is_empty() {
            self.owners.resize(icons.len(), None);
        }
        if self.owners.len() != icons.len() {
            return Err("Icon ownership is incompatible with this rice".into());
        }
        self.owners[index] = owner.map(str::to_owned);
        Ok(())
    }

    /// Commit a cross-display drop together with its ownership, or nothing.
    /// A failed target layout must not leave the icon assigned off-screen.
    pub fn transfer(&mut self, icons: &[DesktopIcon], index: usize,
                    target: &str, coords: Coordinates) -> Result<(), Box<dyn Error>> {
        let mut next = self.clone();
        next.set(target, icons, index, coords)?;
        next.assign(icons, index, Some(target))?;
        *self = next;
        Ok(())
    }
}

fn safe_output_name(name: &str) -> bool {
    !name.is_empty() && name.len() <= 64
        && name.bytes().all(|byte| byte.is_ascii_alphanumeric()
            || matches!(byte, b'-' | b'_' | b'.'))
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Positions {
    schema_version: u32,
    recipe: String,
    icons: Vec<DesktopIcon>,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    outputs: BTreeMap<String, Vec<Coordinates>>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    owners: Vec<Option<String>>,
}

fn path(id: &str) -> Option<PathBuf> {
    if env::var("RICEBOWL_DE_NESTED").ok().as_deref() == Some("1") {
        return None;
    }
    let base = match env::var_os("XDG_CONFIG_HOME") {
        Some(dir) => PathBuf::from(dir),
        None => PathBuf::from(env::var_os("HOME")?).join(".config"),
    };
    base.is_absolute().then(|| base.join("ricebowl/native-icon-positions").join(format!("{id}.json")))
}

fn apply(raw: &[u8], recipe: &mut PanelStyle) -> Result<OutputPositions, Box<dyn Error>> {
    let saved: Positions = serde_json::from_slice(raw)?;
    if !matches!(saved.schema_version, 1 | 2 | 3) || saved.recipe != recipe.id
        || saved.icons.len() != recipe.desktop_icons.len()
        || saved.icons.iter().zip(&recipe.desktop_icons).any(|(stored, original)| {
            stored.action != original.action || stored.label != original.label
                || stored.x > MAX_SAVED_POSITION || stored.y > MAX_SAVED_POSITION
        })
    {
        return Err("Native icon positions do not match the selected rice".into());
    }
    if (saved.schema_version == 1 && !saved.outputs.is_empty())
        || (saved.schema_version < 3 && !saved.owners.is_empty())
        || (!saved.owners.is_empty() && saved.owners.len() != saved.icons.len())
        || saved.owners.iter().flatten().any(|name| !safe_output_name(name))
        || saved.outputs.len() > MAX_OUTPUTS
        || saved.outputs.iter().any(|(name, icons)| {
            !safe_output_name(name) || icons.len() != saved.icons.len()
                || icons.iter().any(|item| {
                    item.x > MAX_SAVED_POSITION || item.y > MAX_SAVED_POSITION
                })
        })
    {
        return Err("Invalid per-output native icon layout".into());
    }
    for (icon, stored) in recipe.desktop_icons.iter_mut().zip(saved.icons) {
        (icon.x, icon.y) = (stored.x, stored.y);
    }
    Ok(OutputPositions { positions: saved.outputs, owners: saved.owners })
}

pub fn restore(recipe: &mut PanelStyle) -> Result<OutputPositions, Box<dyn Error>> {
    let Some(location) = path(&recipe.id) else { return Ok(OutputPositions::default()); };
    restore_at(&location, recipe)
}

fn restore_at(location: &PathBuf, recipe: &mut PanelStyle) -> Result<OutputPositions, Box<dyn Error>> {
    if !location.exists() { return Ok(OutputPositions::default()); }
    let file = OpenOptions::new().read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC).open(location)?;
    let meta = file.metadata()?;
    if !meta.is_file() || meta.uid() != unsafe { libc::geteuid() }
        || meta.mode() & 0o077 != 0 || meta.len() > MAX_BYTES
    {
        return Err("Native icon positions must be a private regular file".into());
    }
    let mut data = Vec::new();
    file.take(MAX_BYTES + 1).read_to_end(&mut data)?;
    if data.len() as u64 > MAX_BYTES { return Err("Icon position file is oversized".into()); }
    apply(&data, recipe)
}

pub fn save(recipe: &PanelStyle, outputs: &OutputPositions) -> Result<(), Box<dyn Error>> {
    let Some(location) = path(&recipe.id) else { return Ok(()); };
    save_at(&location, recipe, outputs)
}

fn save_at(location: &PathBuf, recipe: &PanelStyle,
           outputs: &OutputPositions) -> Result<(), Box<dyn Error>> {
    let directory = location.parent().ok_or("Missing icon position directory")?;
    let root = directory.parent().ok_or("Missing RiceBowl config directory")?;
    fs::create_dir_all(root)?;
    if fs::symlink_metadata(root)?.file_type().is_symlink() {
        return Err("RiceBowl config directory is a symlink".into());
    }
    if !directory.exists() { DirBuilder::new().mode(0o700).create(directory)?; }
    let meta = fs::symlink_metadata(directory)?;
    if !meta.is_dir() || meta.file_type().is_symlink()
        || meta.uid() != unsafe { libc::geteuid() } || meta.mode() & 0o077 != 0
    {
        return Err("Native icon position directory must be owner-private".into());
    }
    if let Ok(meta) = fs::symlink_metadata(location) {
        if !meta.is_file() || meta.file_type().is_symlink()
            || meta.uid() != unsafe { libc::geteuid() } || meta.mode() & 0o077 != 0
        {
            return Err("Refusing to replace an unmanaged icon position file".into());
        }
    }
    let encoded = serde_json::to_vec(&Positions {
        schema_version: 3, recipe: recipe.id.clone(), icons: recipe.desktop_icons.clone(),
        outputs: outputs.positions.clone(),
        owners: outputs.owners.clone(),
    })?;
    if encoded.len() as u64 > MAX_BYTES { return Err("Too many icon position bytes".into()); }
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    let temporary = directory.join(format!(".{}-{}-{nonce}.tmp", recipe.id, std::process::id()));
    let result = (|| -> Result<(), Box<dyn Error>> {
        let mut file = OpenOptions::new().write(true).create_new(true).mode(0o600).open(&temporary)?;
        file.write_all(&encoded)?;
        file.sync_all()?;
        fs::rename(&temporary, location)?;
        Ok(())
    })();
    if result.is_err() { let _ = fs::remove_file(temporary); }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::symlink;

    fn disposable() -> PathBuf {
        let nonce = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let path = env::temp_dir().join(format!("riceplate-icons-{}-{nonce}", std::process::id()));
        fs::create_dir(&path).unwrap();
        path
    }

    #[test]
    fn rejects_stale_or_cross_rice_positions_without_mutating_recipe() {
        let mut recipe = crate::recipe::load("classic").unwrap();
        let original = recipe.desktop_icons.clone();
        let wrong = Positions {
            schema_version: 1, recipe: "different-rice".into(), icons: original.clone(),
            outputs: BTreeMap::new(), owners: vec![],
        };
        assert!(apply(&serde_json::to_vec(&wrong).unwrap(), &mut recipe).is_err());
        assert_eq!(recipe.desktop_icons.len(), original.len());
        assert!(recipe.desktop_icons.iter().zip(&original).all(|(a, b)|
            a.x == b.x && a.y == b.y));
    }

    #[test]
    fn valid_positions_restore_only_coordinates() {
        let source = include_str!("../../../tests/fixtures/riceplate-desktop-v5.json");
        let mut recipe = crate::recipe::parse(source, Some("mockup-desktop")).unwrap();
        let mut moved = recipe.desktop_icons.clone();
        moved[0].x += 32;
        let state = Positions { schema_version: 1, recipe: recipe.id.clone(), icons: moved,
                                outputs: BTreeMap::new(), owners: vec![] };
        apply(&serde_json::to_vec(&state).unwrap(), &mut recipe).unwrap();
        assert_eq!(recipe.desktop_icons[0].x, state.icons[0].x);
        assert_eq!(recipe.desktop_icons[0].action, state.icons[0].action);
        assert_eq!(recipe.desktop_icons[0].label, state.icons[0].label);
    }

    #[test]
    fn refuses_modified_actions_and_oversized_coordinates() {
        let source = include_str!("../../../tests/fixtures/riceplate-desktop-v5.json");
        let mut recipe = crate::recipe::parse(source, Some("mockup-desktop")).unwrap();
        let original_x = recipe.desktop_icons[0].x;
        let mut state = Positions {
            schema_version: 1, recipe: recipe.id.clone(), icons: recipe.desktop_icons.clone(),
            outputs: BTreeMap::new(), owners: vec![],
        };
        state.icons[0].action = "logout".into();
        assert!(apply(&serde_json::to_vec(&state).unwrap(), &mut recipe).is_err());
        state.icons[0].action = recipe.desktop_icons[0].action.clone();
        state.icons[0].x = MAX_SAVED_POSITION + 1;
        assert!(apply(&serde_json::to_vec(&state).unwrap(), &mut recipe).is_err());
        assert_eq!(recipe.desktop_icons[0].x, original_x);
    }

    #[test]
    fn stores_private_coordinates_and_rejects_symlink_replacement() {
        let base = disposable();
        let file = base.join("ricebowl/native-icon-positions/mockup-desktop.json");
        let source = include_str!("../../../tests/fixtures/riceplate-desktop-v5.json");
        let mut recipe = crate::recipe::parse(source, Some("mockup-desktop")).unwrap();
        recipe.desktop_icons[0].x += 32;
        save_at(&file, &recipe, &OutputPositions::default()).unwrap();
        assert_eq!(fs::symlink_metadata(&file).unwrap().mode() & 0o077, 0);
        assert_eq!(fs::symlink_metadata(file.parent().unwrap()).unwrap().mode() & 0o077, 0);
        let mut restored = crate::recipe::parse(source, Some("mockup-desktop")).unwrap();
        restore_at(&file, &mut restored).unwrap();
        assert_eq!(restored.desktop_icons[0].x, recipe.desktop_icons[0].x);

        fs::remove_file(&file).unwrap();
        let protected = base.join("unrelated.txt");
        fs::write(&protected, b"KEEP").unwrap();
        symlink(&protected, &file).unwrap();
        assert!(save_at(&file, &recipe, &OutputPositions::default()).is_err());
        assert_eq!(fs::read(&protected).unwrap(), b"KEEP");
        fs::remove_dir_all(base).unwrap();
    }

    #[test]
    fn output_layout_is_independent_and_survives_reconnect() {
        let source = include_str!("../../../tests/fixtures/riceplate-desktop-v5.json");
        let recipe = crate::recipe::parse(source, Some("mockup-desktop")).unwrap();
        let base_x = recipe.desktop_icons[0].x;
        let mut state = OutputPositions::default();
        state.set("HDMI-A-1", &recipe.desktop_icons, 0,
                  Coordinates { x: 416, y: 192 }).unwrap();
        state.set("DP-1", &recipe.desktop_icons, 0,
                  Coordinates { x: 128, y: 240 }).unwrap();
        assert_eq!(state.for_output("HDMI-A-1", recipe.desktop_icons.len()).unwrap()[0].x, 416);
        assert_eq!(state.for_output("DP-1", recipe.desktop_icons.len()).unwrap()[0].x, 128);
        assert_eq!(recipe.desktop_icons[0].x, base_x);
        let base = disposable();
        let file = base.join("ricebowl/native-icon-positions/mockup-desktop.json");
        save_at(&file, &recipe, &state).unwrap();
        let mut fresh = crate::recipe::parse(source, Some("mockup-desktop")).unwrap();
        let restored = restore_at(&file, &mut fresh).unwrap();
        assert_eq!(restored, state);
        assert_eq!(fresh.desktop_icons[0].x, base_x);
        fs::remove_dir_all(base).unwrap();
    }

    #[test]
    fn owner_assignment_survives_reconnect_and_can_restore_mirrored_layout() {
        let source = include_str!("../../../tests/fixtures/riceplate-desktop-v5.json");
        let recipe = crate::recipe::parse(source, Some("mockup-desktop")).unwrap();
        let mut state = OutputPositions::default();
        assert_eq!(state.owner(0), None); // All connected displays as before.
        state.assign(&recipe.desktop_icons, 0, Some("DP-1")).unwrap();
        assert_eq!(state.owner(0), Some("DP-1"));
        let connected = vec!["DP-1".to_owned(), "HDMI-A-1".to_owned()];
        assert!(state.visible_on(0, Some("DP-1"), false, &connected));
        assert!(!state.visible_on(0, Some("HDMI-A-1"), true, &connected));
        let unplugged = vec!["HDMI-A-1".to_owned()];
        assert!(state.visible_on(0, Some("HDMI-A-1"), true, &unplugged));
        assert!(!state.visible_on(0, Some("OTHER"), false, &unplugged));
        state.set("DP-1", &recipe.desktop_icons, 0, Coordinates { x: 120, y: 80 }).unwrap();
        let base = disposable();
        let file = base.join("ricebowl/native-icon-positions/mockup-desktop.json");
        save_at(&file, &recipe, &state).unwrap();
        let mut restored_recipe = crate::recipe::parse(source, Some("mockup-desktop")).unwrap();
        let mut restored = restore_at(&file, &mut restored_recipe).unwrap();
        assert_eq!(restored.owner(0), Some("DP-1"));
        assert_eq!(restored.for_output("DP-1", recipe.desktop_icons.len()).unwrap()[0].x, 120);
        restored.assign(&recipe.desktop_icons, 0, None).unwrap();
        assert_eq!(restored.owner(0), None);
        assert!(restored.visible_on(0, Some("HDMI-A-1"), true, &connected));
        save_at(&file, &recipe, &restored).unwrap();
        let mut fresh = crate::recipe::parse(source, Some("mockup-desktop")).unwrap();
        assert_eq!(restore_at(&file, &mut fresh).unwrap().owner(0), None);
        fs::remove_dir_all(base).unwrap();
    }

    #[test]
    fn cross_output_transfer_preserves_source_and_rejects_partial_updates() {
        let source = include_str!("../../../tests/fixtures/riceplate-desktop-v5.json");
        let recipe = crate::recipe::parse(source, Some("mockup-desktop")).unwrap();
        let icons = &recipe.desktop_icons;
        let mut state = OutputPositions::default();
        state.set("DP-1", icons, 0, Coordinates { x: 150, y: 70 }).unwrap();
        state.transfer(icons, 0, "HDMI-A-1", Coordinates { x: 30, y: 90 }).unwrap();
        assert_eq!(state.owner(0), Some("HDMI-A-1"));
        assert_eq!(state.for_output("DP-1", icons.len()).unwrap()[0].x, 150);
        assert_eq!(state.for_output("HDMI-A-1", icons.len()).unwrap()[0].x, 30);
        let before = state.clone();
        assert!(state.transfer(icons, 0, "../../invalid", Coordinates { x: 1, y: 1 }).is_err());
        assert!(state.transfer(icons, 0, "DP-1", Coordinates {
            x: MAX_SAVED_POSITION + 1, y: 2,
        }).is_err());
        assert_eq!(state, before);
        state.owners = vec![None; icons.len() + 1]; // Fail after target layout preflight.
        let incompatible = state.clone();
        assert!(state.transfer(icons, 0, "DP-2", Coordinates { x: 10, y: 20 }).is_err());
        assert_eq!(state, incompatible);
    }

    #[test]
    fn reset_one_monitor_position_preserves_other_layouts_and_ownership() {
        let source = include_str!("../../../tests/fixtures/riceplate-desktop-v5.json");
        let recipe = crate::recipe::parse(source, Some("mockup-desktop")).unwrap();
        let icons = &recipe.desktop_icons;
        let mut state = OutputPositions::default();
        let changed = Coordinates { x: 386, y: 216 };
        state.set("DP-1", icons, 0, changed).unwrap();
        state.set("HDMI-A-1", icons, 0, Coordinates { x: 524, y: 320 }).unwrap();
        state.assign(icons, 0, Some("DP-1")).unwrap();
        let untouched = state.for_output("HDMI-A-1", icons.len()).unwrap()[0];
        assert!(state.can_reset_position("DP-1", icons, 0));
        assert!(!state.can_reset_position("DP-1", icons, icons.len()));
        assert!(!state.can_reset_position("NONEXISTENT", icons, 0));
        assert!(state.reset_position("DP-1", icons, 0).unwrap());
        assert!(!state.can_reset_position("DP-1", icons, 0));
        assert!(!state.reset_position("DP-1", icons, 0).unwrap());
        assert!(!state.reset_position("DP-2", icons, 0).unwrap());
        assert_eq!(state.for_output("DP-1", icons.len()).unwrap()[0],
                   Coordinates { x: icons[0].x, y: icons[0].y });
        assert_eq!(state.for_output("HDMI-A-1", icons.len()).unwrap()[0], untouched);
        assert_eq!(state.owner(0), Some("DP-1"));
        let before = state.clone();
        assert!(state.reset_position("../../oops", icons, 0).is_err());
        assert!(state.reset_position("DP-1", icons, icons.len()).is_err());
        assert_eq!(state, before);
    }

    #[test]
    fn rejects_invalid_owner_and_unsupported_migration_without_partial_apply() {
        let source = include_str!("../../../tests/fixtures/riceplate-desktop-v5.json");
        let mut recipe = crate::recipe::parse(source, Some("mockup-desktop")).unwrap();
        let mut state = OutputPositions::default();
        assert!(state.assign(&recipe.desktop_icons, 0, Some("../../escape")).is_err());
        assert_eq!(state.owner(0), None);
        assert!(state.assign(&recipe.desktop_icons, recipe.desktop_icons.len(), Some("DP-1")).is_err());
        let mut invalid = Positions { schema_version: 2, recipe: recipe.id.clone(),
            icons: recipe.desktop_icons.clone(), outputs: BTreeMap::new(),
            owners: vec![Some("DP-1".into()); recipe.desktop_icons.len()] };
        let prior = recipe.desktop_icons[0].x;
        assert!(apply(&serde_json::to_vec(&invalid).unwrap(), &mut recipe).is_err());
        assert_eq!(recipe.desktop_icons[0].x, prior);
        invalid.schema_version = 3;
        invalid.owners[0] = Some("..//bad".into());
        assert!(apply(&serde_json::to_vec(&invalid).unwrap(), &mut recipe).is_err());
        invalid.owners = vec![None];
        assert!(apply(&serde_json::to_vec(&invalid).unwrap(), &mut recipe).is_err());
    }

    #[test]
    fn rejects_invalid_output_name_and_layout_without_partial_restore() {
        let source = include_str!("../../../tests/fixtures/riceplate-desktop-v5.json");
        let mut recipe = crate::recipe::parse(source, Some("mockup-desktop")).unwrap();
        let mut state = OutputPositions::default();
        assert!(state.set("../../escape", &recipe.desktop_icons, 0,
                          Coordinates { x: 8, y: 8 }).is_err());
        state.set("DP-1", &recipe.desktop_icons, 0,
                  Coordinates { x: 16, y: 32 }).unwrap();
        let mut invalid = Positions {
            schema_version: 2, recipe: recipe.id.clone(), icons: recipe.desktop_icons.clone(),
            outputs: state.positions, owners: vec![],
        };
        invalid.outputs.get_mut("DP-1").unwrap()[0].x = MAX_SAVED_POSITION + 1;
        let before = recipe.desktop_icons[0].x;
        assert!(apply(&serde_json::to_vec(&invalid).unwrap(), &mut recipe).is_err());
        assert_eq!(recipe.desktop_icons[0].x, before);
    }
}
