//! Read-only UPower-compatible kernel supply fallback for native panel power.
//! Only the fixed Linux sysfs root is opened at runtime; no new daemon, D-Bus
//! watcher, arbitrary recipe paths, or privileged operation is introduced.

use std::{fs, path::Path};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PowerStatus {
    NotPresent,
    Unknown,
    Battery { percent: u8, charging: bool },
}

impl PowerStatus {
    pub fn current() -> Self {
        Self::read(Path::new("/sys/class/power_supply"))
    }

    pub fn label(&self) -> String {
        match self {
            Self::NotPresent => "N/A".into(),
            Self::Unknown => "BAT ?".into(),
            Self::Battery { percent, charging } if *charging => format!("{percent}%+"),
            Self::Battery { percent, .. } => format!("{percent}%"),
        }
    }

    fn read(root: &Path) -> Self {
        let Ok(entries) = fs::read_dir(root) else {
            return Self::Unknown;
        };
        let mut count = 0_u64;
        let mut total = 0_u64;
        let mut charging = false;
        let mut invalid = false;
        for entry in entries.flatten() {
            let path = entry.path();
            if read_trimmed(&path.join("type")).as_deref() != Some("Battery")
                || read_trimmed(&path.join("present")).as_deref() == Some("0")
            {
                continue;
            }
            count += 1;
            charging |= matches!(
                read_trimmed(&path.join("status")).as_deref(),
                Some("Charging")
            );
            match read_trimmed(&path.join("capacity")).and_then(|data| data.parse::<u8>().ok()) {
                Some(value) if value <= 100 => total += u64::from(value),
                _ => invalid = true,
            }
        }
        if count == 0 {
            return Self::NotPresent;
        }
        if invalid {
            return Self::Unknown;
        }
        Self::Battery {
            percent: ((total + count / 2) / count) as u8,
            charging,
        }
    }
}

fn read_trimmed(path: &Path) -> Option<String> {
    let content = fs::read_to_string(path).ok()?;
    (content.len() <= 80).then(|| content.trim().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn temp_supply() -> PathBuf {
        let root = std::env::temp_dir().join(format!(
            "riceplate-power-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir(&root).unwrap();
        root
    }

    fn add(root: &Path, id: &str, kind: &str, capacity: &str, status: &str) {
        let directory = root.join(id);
        fs::create_dir(&directory).unwrap();
        fs::write(directory.join("type"), kind).unwrap();
        fs::write(directory.join("capacity"), capacity).unwrap();
        fs::write(directory.join("status"), status).unwrap();
    }

    #[test]
    fn reads_real_kernel_contract_without_assuming_battery_exists() {
        let root = temp_supply();
        assert_eq!(PowerStatus::read(&root), PowerStatus::NotPresent);
        add(&root, "AC", "Mains", "100", "Charging");
        assert_eq!(PowerStatus::read(&root), PowerStatus::NotPresent);
        add(&root, "BAT0", "Battery", "59", "Discharging");
        assert_eq!(PowerStatus::read(&root).label(), "59%");
        add(&root, "BAT1", "Battery", "81", "Charging");
        assert_eq!(PowerStatus::read(&root).label(), "70%+");
        fs::write(root.join("BAT1/capacity"), "999").unwrap();
        assert_eq!(PowerStatus::read(&root), PowerStatus::Unknown);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn disconnected_supply_and_invalid_root_do_not_fabricate_charge() {
        let root = temp_supply();
        add(&root, "BAT0", "Battery", "55", "Charging");
        fs::write(root.join("BAT0/present"), "0").unwrap();
        assert_eq!(PowerStatus::read(&root), PowerStatus::NotPresent);
        fs::remove_dir_all(&root).unwrap();
        assert_eq!(PowerStatus::read(&root), PowerStatus::Unknown);
    }
}
