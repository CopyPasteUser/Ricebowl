//! Bounded, unprivileged NetworkManager/WirePlumber status sampling.
//! These commands run only in an opt-in native session's worker thread.
//! Missing services report unavailable; a recipe never controls arguments.

use std::{
    io::{BufRead, BufReader, ErrorKind, Read},
    os::fd::AsRawFd,
    process::{Child, Command, Stdio},
    sync::mpsc::{self, TrySendError},
    thread,
    time::{Duration, Instant},
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ControlAction {
    WifiToggle,
    BluetoothToggle,
    AudioMute,
    AudioUp,
    AudioDown,
}

impl ControlAction {
    pub fn from_id(id: &str) -> Option<Self> {
        match id {
            "wifi-toggle" => Some(Self::WifiToggle),
            "bluetooth-toggle" => Some(Self::BluetoothToggle),
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
            Self::BluetoothToggle => {
                let Some(state) = command_output("bluetoothctl", &["show"]) else {
                    return false;
                };
                match BluetoothRadio::parse(&state) {
                    BluetoothRadio::Enabled => ("bluetoothctl", vec!["power", "off"]),
                    BluetoothRadio::Disabled => ("bluetoothctl", vec!["power", "on"]),
                    BluetoothRadio::Unavailable => return false,
                }
            }
            Self::AudioMute => ("wpctl", vec!["set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"]),
            Self::AudioUp => ("wpctl", vec!["set-volume", "@DEFAULT_AUDIO_SINK@", "5%+",
                                             "--limit", "1.0"]),
            Self::AudioDown => ("wpctl", vec!["set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"]),
        };
        command_status(command.0, &command.1)
    }

    /// Hardware-owned capability, never inferred from network connectivity.
    pub fn available(self, status: &SystemStatus) -> bool {
        match self {
            Self::WifiToggle => status.wifi != WifiRadio::Unavailable,
            Self::BluetoothToggle => status.bluetooth != BluetoothRadio::Unavailable,
            Self::AudioMute | Self::AudioUp | Self::AudioDown =>
                status.audio != Audio::Unavailable,
        }
    }

    pub fn state_label(self, status: &SystemStatus) -> String {
        match self {
            Self::WifiToggle => status.wifi.label().into(),
            Self::BluetoothToggle => status.bluetooth.label().into(),
            Self::AudioMute => match status.audio {
                Audio::Muted => "Muted".into(),
                Audio::Unavailable => "N/A".into(),
                Audio::Volume(_) => "On".into(),
            },
            Self::AudioUp | Self::AudioDown => status.audio.label(),
        }
    }

    /// A successful subprocess exit alone is not proof of a state transition.
    pub fn verified(self, before: &SystemStatus, after: &SystemStatus, exit_ok: bool) -> bool {
        if !exit_ok || !self.available(before) || !self.available(after) { return false; }
        match self {
            Self::WifiToggle => before.wifi != after.wifi,
            Self::BluetoothToggle => before.bluetooth != after.bluetooth,
            // A successful mute command must actually toggle the mute bit.
            // A concurrent volume adjustment is not evidence that the mute
            // request took effect, even if the command exited successfully.
            Self::AudioMute => matches!(
                (&before.audio, &after.audio),
                (Audio::Muted, Audio::Volume(_)) | (Audio::Volume(_), Audio::Muted)
            ),
            Self::AudioUp | Self::AudioDown => match (&before.audio, &after.audio) {
                (Audio::Volume(first), Audio::Volume(second)) =>
                    if self == Self::AudioUp { second > first } else { second < first },
                _ => false,
            },
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WifiRadio { Enabled, Disabled, Unavailable }

impl WifiRadio {
    fn parse(value: &str) -> Self {
        match value.trim() {
            "enabled" => Self::Enabled,
            "disabled" => Self::Disabled,
            _ => Self::Unavailable,
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Self::Enabled => "On",
            Self::Disabled => "Off",
            Self::Unavailable => "N/A",
        }
    }
}

/// Default controller radio power, never the state of a paired device.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BluetoothRadio { Enabled, Disabled, Unavailable }

impl BluetoothRadio {
    fn parse(output: &str) -> Self {
        let mut observed = None;
        for line in output.lines().take(64) {
            let Some(value) = line.trim().strip_prefix("Powered:") else { continue; };
            let state = match value.trim() {
                "yes" => Self::Enabled,
                "no" => Self::Disabled,
                _ => return Self::Unavailable,
            };
            if observed.replace(state).is_some() { return Self::Unavailable; }
        }
        observed.unwrap_or(Self::Unavailable)
    }

    pub fn label(self) -> &'static str {
        match self {
            Self::Enabled => "On",
            Self::Disabled => "Off",
            Self::Unavailable => "N/A",
        }
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
    pub wifi: WifiRadio,
    pub bluetooth: BluetoothRadio,
}

impl Default for SystemStatus {
    fn default() -> Self {
        Self { network: Network::Unavailable, audio: Audio::Unavailable,
               wifi: WifiRadio::Unavailable, bluetooth: BluetoothRadio::Unavailable }
    }
}

impl SystemStatus {
    pub fn read(include_network: bool, include_audio: bool, include_bluetooth: bool) -> Self {
        Self {
            network: if include_network {
                command_output("nmcli", &["--wait", "1", "-t", "-f", "STATE", "general"])
                    .map(|output| Network::parse(&output)).unwrap_or(Network::Unavailable)
            } else { Network::Unavailable },
            audio: if include_audio {
                command_output("wpctl", &["get-volume", "@DEFAULT_AUDIO_SINK@"])
                    .map(|output| Audio::parse(&output)).unwrap_or(Audio::Unavailable)
            } else { Audio::Unavailable },
            wifi: if include_network {
                command_output("nmcli", &["--wait", "1", "radio", "wifi"])
                    .map(|output| WifiRadio::parse(&output)).unwrap_or(WifiRadio::Unavailable)
            } else { WifiRadio::Unavailable },
            bluetooth: if include_bluetooth {
                command_output("bluetoothctl", &["show"])
                    .map(|output| BluetoothRadio::parse(&output))
                    .unwrap_or(BluetoothRadio::Unavailable)
            } else { BluetoothRadio::Unavailable },
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
    /// A disconnected Pulse server can terminate `pactl subscribe` without
    /// bringing down the panel. The owner may start a fresh observer later.
    pub fn running(&mut self) -> bool {
        matches!(self.child.try_wait(), Ok(None))
    }

    pub fn start(callback: impl Fn(Audio) -> bool + Send + 'static) -> Option<Self> {
        let mut child = Command::new("pactl").arg("subscribe").env("LC_ALL", "C")
            .stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::null())
            .spawn().ok()?;
        let output = child.stdout.take()?;
        let (events, pending) = mpsc::sync_channel::<()>(1);
        thread::spawn(move || {
            while pending.recv().is_ok() {
                thread::sleep(Duration::from_millis(80));
                if !callback(SystemStatus::read(false, true, false).audio) {
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
    // Use an O_NONBLOCK pipe rather than a joined reader thread. A command
    // may exit while a descendant still holds its stdout FD; waiting for
    // EOF in a reader.join() can then hang forever despite killing/reaping
    // the original child. The timeout bounds BOTH the child and pipe.
    let mut pipe = child.stdout.take();
    if output && pipe.is_none() {
        let _ = child.kill();
        let _ = child.wait();
        return None;
    }
    if let Some(stdout) = pipe.as_ref() {
        // SAFETY: the descriptor is owned by ChildStdout and stays open
        // until pipe is dropped. F_GETFL/F_SETFL change only its file flags.
        let flags = unsafe { libc::fcntl(stdout.as_raw_fd(), libc::F_GETFL) };
        if flags < 0 || unsafe {
            libc::fcntl(stdout.as_raw_fd(), libc::F_SETFL, flags | libc::O_NONBLOCK)
        } < 0 {
            let _ = child.kill();
            let _ = child.wait();
            return None;
        }
    }
    let started = Instant::now();
    let mut bytes = Vec::new();
    let mut status = None;
    let mut eof = !output;
    loop {
        let mut chunk = [0_u8; 1025];
        let read = pipe.as_mut().map(|stdout| stdout.read(&mut chunk));
        match read {
            Some(Ok(0)) => {
                pipe = None;
                eof = true;
            }
            Some(Ok(len)) => {
                if bytes.len().saturating_add(len) > 1024 {
                    let _ = child.kill();
                    let _ = child.wait();
                    return None; // Reject oversized state, never truncate it.
                }
                bytes.extend_from_slice(&chunk[..len]);
            }
            Some(Err(error)) if error.kind() == ErrorKind::WouldBlock => {}
            Some(Err(error)) if error.kind() == ErrorKind::Interrupted => continue,
            Some(Err(_)) => {
                let _ = child.kill();
                let _ = child.wait();
                return None;
            }
            None => {}
        }
        if status.is_none() {
            match child.try_wait() {
                Ok(Some(exit)) => status = Some(exit.success()),
                Ok(None) => {}
                Err(_) => {
                    let _ = child.kill();
                    let _ = child.wait();
                    return None;
                }
            }
        }
        if let Some(success) = status {
            if eof {
                return Some((success, String::from_utf8(bytes).ok()?));
            }
        }
        if started.elapsed() >= Duration::from_millis(4000) {
            if status.is_none() {
                let _ = child.kill();
                let _ = child.wait();
            }
            // Do not wait for pipe EOF from descendants after parent exit.
            return None;
        }
        thread::sleep(Duration::from_millis(15));
    }
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
        assert_eq!(ControlAction::from_id("bluetooth-toggle"), Some(ControlAction::BluetoothToggle));
        assert_eq!(ControlAction::from_id("audio-mute"), Some(ControlAction::AudioMute));
        assert_eq!(ControlAction::from_id("audio-up"), Some(ControlAction::AudioUp));
        assert_eq!(ControlAction::from_id("audio-down"), Some(ControlAction::AudioDown));
        for invalid in ["", "terminal", "wifi off", "../../nmcli", "audio-volume 100"] {
            assert_eq!(ControlAction::from_id(invalid), None);
        }
    }

    #[test]
    fn radio_capability_is_independent_from_connectivity_and_readback_is_verified() {
        assert_eq!(WifiRadio::parse("enabled\n"), WifiRadio::Enabled);
        assert_eq!(WifiRadio::parse("disabled\n"), WifiRadio::Disabled);
        assert_eq!(WifiRadio::parse("permission denied"), WifiRadio::Unavailable);
        let mut before = SystemStatus::default();
        before.network = Network::Offline;
        before.wifi = WifiRadio::Enabled;
        assert!(ControlAction::WifiToggle.available(&before));
        assert!(!ControlAction::AudioUp.available(&before));
        let mut after = before.clone();
        after.wifi = WifiRadio::Disabled;
        assert!(ControlAction::WifiToggle.verified(&before, &after, true));
        assert!(!ControlAction::WifiToggle.verified(&before, &before, true));
        assert!(!ControlAction::WifiToggle.verified(&before, &after, false));
        before.audio = Audio::Volume(55);
        after.audio = Audio::Volume(60);
        assert!(ControlAction::AudioUp.verified(&before, &after, true));
        assert!(!ControlAction::AudioDown.verified(&before, &after, true));
        after.audio = Audio::Muted;
        assert!(ControlAction::AudioMute.verified(&before, &after, true));
        assert!(!ControlAction::AudioUp.verified(&before, &after, true));
        assert_eq!(ControlAction::AudioMute.state_label(&after), "Muted");
        assert!(!ControlAction::AudioMute.verified(
            &SystemStatus { audio: Audio::Volume(40), ..before.clone() },
            &SystemStatus { audio: Audio::Volume(55), ..after.clone() }, true),
            "a concurrent volume-only change must never confirm a mute");
        assert!(!ControlAction::AudioMute.verified(
            &SystemStatus { audio: Audio::Volume(40), ..before.clone() },
            &SystemStatus { audio: Audio::Volume(40), ..after.clone() }, true));
        assert!(ControlAction::AudioMute.verified(
            &SystemStatus { audio: Audio::Muted, ..before.clone() },
            &SystemStatus { audio: Audio::Volume(40), ..after.clone() }, true),
            "unmute must be accepted when a real sink becomes audible");
        assert!(!ControlAction::AudioMute.verified(
            &SystemStatus { audio: Audio::Muted, ..before.clone() },
            &SystemStatus { audio: Audio::Muted, ..after.clone() }, true),
            "two muted readings must not confirm a change");
    }

    #[test]
    fn bluetooth_requires_explicit_controller_readback_and_verified_transition() {
        assert_eq!(BluetoothRadio::parse("Controller AB:CD\n\tPowered: yes\n"), BluetoothRadio::Enabled);
        assert_eq!(BluetoothRadio::parse("Controller AB:CD\n\tPowered: no\n"), BluetoothRadio::Disabled);
        for value in ["", "No default controller available", "Powered: maybe",
                      "Powered: yes\nPowered: no", "Powered: yes extra"] {
            assert_eq!(BluetoothRadio::parse(value), BluetoothRadio::Unavailable);
        }
        let mut before = SystemStatus::default();
        before.bluetooth = BluetoothRadio::Enabled;
        assert!(ControlAction::BluetoothToggle.available(&before));
        assert_eq!(ControlAction::BluetoothToggle.state_label(&before), "On");
        let mut after = before.clone();
        after.bluetooth = BluetoothRadio::Disabled;
        assert!(ControlAction::BluetoothToggle.verified(&before, &after, true));
        assert!(!ControlAction::BluetoothToggle.verified(&before, &before, true));
        assert!(!ControlAction::BluetoothToggle.verified(&before, &after, false));
        after.bluetooth = BluetoothRadio::Unavailable;
        assert!(!ControlAction::BluetoothToggle.verified(&before, &after, true));
    }

    #[test]
    fn bounded_worker_drains_pipe_and_rejects_oversized_or_invalid_responses() {
        // Coreutils seq is available on supported Ubuntu/Mint systems. The
        // 10,000-line process writes far more than the pipe and 1 KiB limit:
        // neither partial successful output nor a four-second deadlock is OK.
        assert_eq!(spawn_bounded("seq", &["1", "3"], true),
                   Some((true, "1\n2\n3\n".into())));
        assert_eq!(spawn_bounded("seq", &["1", "10000"], true), None);
        assert_eq!(spawn_bounded("nonexistent-ricebowl-qa-provider",
                                 &[], true), None);
        assert_eq!(spawn_bounded("true", &[], false),
                   Some((true, String::new())));
    }

    #[test]
    fn bounded_worker_does_not_wait_for_inherited_stdout_after_parent_exits() {
        // A short-lived shell can leave a child with the same pipe open.
        // The former reader.join() waited for that unrelated process to
        // close stdout AFTER the original command had exited.
        // This test-only shell never enters a production command allowlist.
        let started = Instant::now();
        let result = spawn_bounded("sh", &["-c",
            "printf 'enabled\\n'; sleep 6 & exit 0"], true);
        assert_eq!(result, None, "unclosed inherited stdout must fail closed");
        assert!(started.elapsed() < Duration::from_secs(6),
                "an inherited pipe must never bypass the four-second bound");
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
