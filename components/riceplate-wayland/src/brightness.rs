//! Backlight readback for RicePop. Optional full-session hardware support:
//! read two kernel-provided sysfs integers, never write them or spawn a daemon.

use std::{fs, path::PathBuf};

pub struct Watcher {
    brightness: PathBuf,
    maximum: u64,
    last: Option<u16>,
}

fn percentage(current: &str, maximum: u64) -> Option<u16> {
    let value: u64 = current.trim().parse().ok()?;
    (maximum > 0 && value <= maximum).then(||
        ((value.saturating_mul(100).saturating_add(maximum / 2)) / maximum).min(100) as u16)
}

impl Watcher {
    pub fn detect() -> Option<Self> {
        let mut devices = Vec::new();
        for device in fs::read_dir("/sys/class/backlight").ok()?.take(16).flatten() {
            let path = device.path();
            let Ok(raw_maximum) = fs::read_to_string(path.join("max_brightness")) else {
                continue;
            };
            let Ok(maximum) = raw_maximum.trim().parse::<u64>() else { continue; };
            if maximum == 0 { continue; }
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
        Some(Self { brightness, maximum, last: Some(last) })
    }

    pub fn changed(&mut self) -> Option<u16> {
        let now = fs::read_to_string(&self.brightness).ok()
            .and_then(|current| percentage(&current, self.maximum));
        let changed = match (self.last, now) {
            (Some(previous), Some(value)) if previous != value => Some(value),
            _ => None,
        };
        self.last = now;
        changed
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
