//! Bounded, unprivileged NetworkManager/WirePlumber status sampling.
//! These commands run only in an opt-in native session's worker thread.
//! Missing services report unavailable; a recipe never controls arguments.

use std::{
    io::{BufRead, BufReader, Read},
    process::{Child, Command, Stdio},
    sync::mpsc::{self, TrySendError},
    thread,
    time::{Duration, Instant},
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ControlAction {
    WifiToggle,
    AudioMute,
    AudioUp,
    AudioDown,
}

impl ControlAction {
    pub fn from_id(id: &str) -> Option<Self> {
        match id {
            "wifi-toggle" => Some(Self::WifiToggle),
            "audio-mute" => Some(Self::AudioMute),
            "audio-up" => Some(Self::AudioUp),
            "audio-down" => Some(Self::AudioDown),
            _ => None,
        }
    }

    pub fn apply(self) -> bool {
        let command = match self {
            Self::WifiToggle => {
                let Some(state) = command_output("nmcli", &["--wait", "1", "radio", "wifi"])
                else { return false; };
                match state.trim() {
                    "enabled" => ("nmcli", vec!["--wait", "3", "radio", "wifi", "off"]),
                    "disabled" => ("nmcli", vec!["--wait", "3", "radio", "wifi", "on"]),
                    _ => return false,
                }
            }
            Self::AudioMute => ("wpctl", vec!["set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"]),
            Self::AudioUp => ("wpctl", vec!["set-volume", "@DEFAULT_AUDIO_SINK@", "5%+",
                                             "--limit", "1.0"]),
            Self::AudioDown => ("wpctl", vec!["set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"]),
        };
        command_status(command.0, &command.1)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Network {
    Global,
    Local,
    Connecting,
    Offline,
    Unavailable,
}

impl Network {
    pub fn label(&self) -> &'static str {
        match self {
            Self::Global => "Net",
            Self::Local => "Local",
            Self::Connecting => "Wait",
            Self::Offline => "Off",
            Self::Unavailable => "N/A",
        }
    }

    fn parse(output: &str) -> Self {
        let output = output.trim().to_ascii_lowercase();
        match output.as_str() {
            "connected" | "connected (global)" => Self::Global,
            "connected (site only)" | "connected (local only)" => Self::Local,
            "connecting" => Self::Connecting,
            "disconnected" | "disconnecting" | "asleep" => Self::Offline,
            _ => Self::Unavailable,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Audio {
    Volume(u16),
    Muted,
    Unavailable,
}

impl Audio {
    pub fn label(&self) -> String {
        match self {
            Self::Volume(value) => format!("{value}%"),
            Self::Muted => "Mute".into(),
            Self::Unavailable => "N/A".into(),
        }
    }

    fn parse(output: &str) -> Self {
        let Some(value) = output.trim().strip_prefix("Volume: ") else {
            return Self::Unavailable;
        };
        let Some(number) = value.split_whitespace().next()
            .and_then(|value| value.parse::<f64>().ok()) else {
            return Self::Unavailable;
        };
        if !number.is_finite() || !(0.0..=1.5).contains(&number) {
            return Self::Unavailable;
        }
        if value.contains("[MUTED]") { return Self::Muted; }
        Self::Volume((number * 100.0).round() as u16)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SystemStatus {
    pub network: Network,
    pub audio: Audio,
}

impl Default for SystemStatus {
    fn default() -> Self {
        Self { network: Network::Unavailable, audio: Audio::Unavailable }
    }
}

impl SystemStatus {
    pub fn read(include_network: bool, include_audio: bool) -> Self {
        Self {
            network: if include_network {
                command_output("nmcli", &["--wait", "1", "-t", "-f", "STATE", "general"])
                    .map(|output| Network::parse(&output)).unwrap_or(Network::Unavailable)
            } else { Network::Unavailable },
            audio: if include_audio {
                command_output("wpctl", &["get-volume", "@DEFAULT_AUDIO_SINK@"])
                    .map(|output| Audio::parse(&output)).unwrap_or(Audio::Unavailable)
            } else { Audio::Unavailable },
        }
    }
}

/// Only default-output changes can affect the RicePop volume OSD. Ignore
/// sink-input/player chatter, microphone changes and unrelated D-Bus traffic.
fn is_audio_event(line: &str) -> bool {
    let event = line.trim();
    ["Event 'change' on sink #", "Event 'new' on sink #",
     "Event 'remove' on sink #", "Event 'change' on server #"]
        .iter().any(|prefix| event.starts_with(prefix))
}

/// One event-driven PulseAudio-compatibility observer for the native session.
/// The child is killed when RicePlate exits; a bounded one-slot mailbox
/// coalesces rapid slider changes before the real WirePlumber readback.
pub struct AudioWatcher {
    child: Child,
}

impl AudioWatcher {
    pub fn start(callback: impl Fn(Audio) -> bool + Send + 'static) -> Option<Self> {
        let mut child = Command::new("pactl").arg("subscribe").env("LC_ALL", "C")
            .stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::null())
            .spawn().ok()?;
        let output = child.stdout.take()?;
        let (events, pending) = mpsc::sync_channel::<()>(1);
        thread::spawn(move || {
            while pending.recv().is_ok() {
                thread::sleep(Duration::from_millis(80));
                if !callback(SystemStatus::read(false, true).audio) {
                    break;
                }
            }
        });
        thread::spawn(move || {
            for line in BufReader::new(output).lines() {
                let Ok(line) = line else { break; };
                if !is_audio_event(&line) { continue; }
                match events.try_send(()) {
                    Ok(()) | Err(TrySendError::Full(())) => {}
                    Err(TrySendError::Disconnected(())) => break,
                }
            }
        });
        Some(Self { child })
    }
}

impl Drop for AudioWatcher {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn spawn_bounded(program: &str, args: &[&str], output: bool) -> Option<(bool, String)> {
    let mut child = Command::new(program).args(args).env("LC_ALL", "C")
        .stdin(Stdio::null())
        .stdout(if output { Stdio::piped() } else { Stdio::null() })
        .stderr(Stdio::null())
        .spawn().ok()?;
    let started = Instant::now();
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if started.elapsed() < Duration::from_millis(4000) => {
                thread::sleep(Duration::from_millis(15));
            }
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                return None;
            }
        }
    };
    let mut output = String::new();
    if let Some(stdout) = child.stdout.take() {
        stdout.take(1024).read_to_string(&mut output).ok()?;
    }
    Some((status.success(), output))
}

fn command_output(program: &str, args: &[&str]) -> Option<String> {
    spawn_bounded(program, args, true)
        .and_then(|(success, value)| success.then_some(value))
}

fn command_status(program: &str, args: &[&str]) -> bool {
    spawn_bounded(program, args, false).is_some_and(|(success, _)| success)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn network_cli_states_do_not_fabricate_internet_connectivity() {
        assert_eq!(Network::parse("connected\n"), Network::Global);
        assert_eq!(Network::parse("connected (site only)"), Network::Local);
        assert_eq!(Network::parse("connecting\n"), Network::Connecting);
        assert_eq!(Network::parse("disconnected\n"), Network::Offline);
        assert_eq!(Network::parse("garbage"), Network::Unavailable);
        assert_eq!(Network::Unavailable.label(), "N/A");
    }

    #[test]
    fn pipewire_volume_parsing_bounds_and_mute_are_explicit() {
        assert_eq!(Audio::parse("Volume: 0.58\n"), Audio::Volume(58));
        assert_eq!(Audio::parse("Volume: 0.20 [MUTED]\n"), Audio::Muted);
        assert_eq!(Audio::parse("Volume: 1.15"), Audio::Volume(115));
        for invalid in ["", "Volume: nan", "Volume: -2", "Volume: 12", "garbage"] {
            assert_eq!(Audio::parse(invalid), Audio::Unavailable);
        }
    }

    #[test]
    fn quick_actions_are_fixed_allowlisted_ids() {
        assert_eq!(ControlAction::from_id("wifi-toggle"), Some(ControlAction::WifiToggle));
        assert_eq!(ControlAction::from_id("audio-mute"), Some(ControlAction::AudioMute));
        assert_eq!(ControlAction::from_id("audio-up"), Some(ControlAction::AudioUp));
        assert_eq!(ControlAction::from_id("audio-down"), Some(ControlAction::AudioDown));
        for invalid in ["", "terminal", "wifi off", "../../nmcli", "audio-volume 100"] {
            assert_eq!(ControlAction::from_id(invalid), None);
        }
    }

    #[test]
    fn pulse_events_filter_sinks_not_per_application_streams() {
        assert!(is_audio_event("Event 'change' on sink #3"));
        assert!(is_audio_event("Event 'new' on sink #2"));
        assert!(is_audio_event("Event 'change' on server #0"));
        assert!(!is_audio_event("Event 'change' on sink-input #13"));
        assert!(!is_audio_event("Event 'change' on source #2"));
        assert!(!is_audio_event("Event 'change' on client #4"));
        assert!(!is_audio_event("malicious output"));
    }
}
