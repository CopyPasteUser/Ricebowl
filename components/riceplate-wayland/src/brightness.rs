//! Backlight readback for RicePop. Optional full-session hardware support:
//! read two kernel-provided sysfs integers, never write them or spawn a daemon.

use std::{fs, path::PathBuf};

const SYSFS_CLASS: &str = "/sys/class/backlight";

/// Directory holding one sub-directory per backlight device. Always the
/// kernel's `/sys/class/backlight`, unless `RICEBOWL_BACKLIGHT_DIR` names an
/// absolute directory: a disposable test session has no panel backlight, so
/// the SG3 smoke points this at a private fixture tree. Only the two integer
/// files below it are ever read; nothing is written or executed.
fn class_dir() -> PathBuf {
    match std::env::var_os("RICEBOWL_BACKLIGHT_DIR") {
        Some(value) if PathBuf::from(&value).is_absolute() => PathBuf::from(value),
        _ => PathBuf::from(SYSFS_CLASS),
    }
}

pub struct Watcher {
    brightness: PathBuf,
    maximum: u64,
    last: Option<u16>,
}

fn percentage(current: &str, maximum: u64) -> Option<u16> {
    let value: u64 = current.trim().parse().ok()?;
    (maximum > 0 && value <= maximum).then(|| {
        ((value.saturating_mul(100).saturating_add(maximum / 2)) / maximum).min(100) as u16
    })
}

impl Watcher {
    pub fn detect() -> Option<Self> {
        let mut devices = Vec::new();
        for device in fs::read_dir(class_dir()).ok()?.take(16).flatten() {
            let path = device.path();
            let Ok(raw_maximum) = fs::read_to_string(path.join("max_brightness")) else {
                continue;
            };
            let Ok(maximum) = raw_maximum.trim().parse::<u64>() else {
                continue;
            };
            if maximum == 0 {
                continue;
            }
            let brightness = path.join("brightness");
            if let Ok(current) = fs::read_to_string(&brightness) {
                if let Some(value) = percentage(&current, maximum) {
                    devices.push((maximum, brightness, value));
                }
            }
        }
        // Prefer the actual hardware backlight over legacy ACPI shim devices.
        devices.sort_by_key(|(maximum, _, _)| std::cmp::Reverse(*maximum));
        let (maximum, brightness, last) = devices.into_iter().next()?;
        Some(Self {
            brightness,
            maximum,
            last: Some(last),
        })
    }

    pub fn changed(&mut self) -> Option<u16> {
        let now = fs::read_to_string(&self.brightness)
            .ok()
            .and_then(|current| percentage(&current, self.maximum));
        let changed = match (self.last, now) {
            (Some(previous), Some(value)) if previous != value => Some(value),
            _ => None,
        };
        // An unreadable or out-of-range sample says nothing about the level:
        // keep the last VALID reading so the next real change is still shown
        // (and an identical one is not).
        self.last = now.or(self.last);
        changed
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn detect_and_change_read_only_the_two_sysfs_integers_of_the_best_device() {
        let root = std::env::temp_dir().join(format!("rb-backlight-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        for (name, maximum, current) in [("acpi_video0", "10", "9"), ("panel", "1000", "250")] {
            let device = root.join(name);
            fs::create_dir_all(&device).unwrap();
            fs::write(device.join("max_brightness"), format!("{maximum}\n")).unwrap();
            fs::write(device.join("brightness"), format!("{current}\n")).unwrap();
        }
        std::env::set_var("RICEBOWL_BACKLIGHT_DIR", &root);
        let mut watcher = Watcher::detect().expect("fixture backlight");
        // The real hardware panel (largest range) wins over the ACPI shim.
        assert_eq!(watcher.last, Some(25));
        assert_eq!(watcher.changed(), None, "no change yet");
        fs::write(root.join("panel/brightness"), "500\n").unwrap();
        assert_eq!(watcher.changed(), Some(50));
        assert_eq!(watcher.changed(), None, "an unchanged level shows nothing");
        fs::write(root.join("panel/brightness"), "junk").unwrap();
        assert_eq!(
            watcher.changed(),
            None,
            "unreadable values never flash an OSD"
        );
        fs::write(root.join("panel/brightness"), "500\n").unwrap();
        assert_eq!(
            watcher.changed(),
            None,
            "the same level after a bad sample is not a change"
        );
        fs::write(root.join("panel/brightness"), "junk").unwrap();
        assert_eq!(watcher.changed(), None);
        fs::write(root.join("panel/brightness"), "600\n").unwrap();
        assert_eq!(
            watcher.changed(),
            Some(60),
            "a real change after a bad sample is still shown"
        );
        std::env::set_var("RICEBOWL_BACKLIGHT_DIR", root.join("missing"));
        assert!(
            Watcher::detect().is_none(),
            "no backlight device means no OSD and no invented level"
        );
        std::env::set_var("RICEBOWL_BACKLIGHT_DIR", "relative/path");
        assert_eq!(class_dir(), PathBuf::from(SYSFS_CLASS));
        std::env::remove_var("RICEBOWL_BACKLIGHT_DIR");
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn sysfs_brightness_is_validated_and_rounded_without_division_by_zero() {
        assert_eq!(percentage("50\n", 100), Some(50));
        assert_eq!(percentage("5\n", 10), Some(50));
        assert_eq!(percentage("1", 3), Some(33));
        assert_eq!(percentage("0", 100), Some(0));
        for (input, maximum) in [("1", 0), ("6", 5), ("-1", 100), ("a", 100)] {
            assert_eq!(percentage(input, maximum), None);
        }
    }
}
