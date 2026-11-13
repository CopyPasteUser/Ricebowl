//! Shared presentation state for verified Linux hardware controls.
//!
//! Panel buttons, action widgets and AT-SPI nodes must describe the same
//! operation, including a busy worker and a failed readback. The actual
//! permission/availability checks and action dispatch remain in the owner.

use crate::system_status::{ControlAction, SystemStatus};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ControlFeedback {
    Ready,
    Applying,
    Busy,
    Unavailable,
    Failed,
}

impl ControlFeedback {
    pub(crate) fn snapshot(
        action: ControlAction,
        status: &SystemStatus,
        pending: Option<ControlAction>,
        result: Option<(ControlAction, bool)>,
        worker_ready: bool,
    ) -> Self {
        if pending == Some(action) { Self::Applying }
        else if pending.is_some() { Self::Busy }
        else if !action.available(status) || !worker_ready { Self::Unavailable }
        else if result == Some((action, false)) { Self::Failed }
        else { Self::Ready }
    }

    /// Failure feedback is visible but does not permanently disable retries.
    pub(crate) fn is_actionable(self) -> bool {
        matches!(self, Self::Ready | Self::Failed)
    }

    pub(crate) fn accessibility_label(self) -> &'static str {
        match self {
            Self::Ready => "ready",
            Self::Applying => "applying",
            Self::Busy => "busy",
            Self::Unavailable => "unavailable",
            Self::Failed => "failed",
        }
    }

    pub(crate) fn desktop_hint(self) -> &'static str {
        match self {
            Self::Ready => "Press Enter or click",
            Self::Applying => "Applying...",
            Self::Busy => "Busy",
            Self::Unavailable => "Unavailable",
            Self::Failed => "Action failed",
        }
    }

    pub(crate) fn panel_caption(self, action: ControlAction, status: &SystemStatus) -> String {
        match self {
            Self::Applying => "Wait".into(),
            Self::Busy => "Busy".into(),
            Self::Failed => "Failed".into(),
            Self::Ready | Self::Unavailable => action.state_label(status),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::system_status::{Audio, Network, WifiRadio};

    fn connected() -> SystemStatus {
        SystemStatus {
            network: Network::Global,
            audio: Audio::Volume(45),
            wifi: WifiRadio::Enabled,
        }
    }

    #[test]
    fn one_snapshot_defines_accessibility_panel_and_desktop_semantics() {
        let status = connected();
        let action = ControlAction::WifiToggle;
        let ready = ControlFeedback::snapshot(action, &status, None, None, true);
        assert!(ready.is_actionable());
        assert_eq!(ready.accessibility_label(), "ready");
        assert_eq!(ready.desktop_hint(), "Press Enter or click");
        assert_eq!(ready.panel_caption(action, &status), "On");

        let applying = ControlFeedback::snapshot(action, &status, Some(action), None, true);
        assert!(!applying.is_actionable());
        assert_eq!(applying.accessibility_label(), "applying");
        assert_eq!(applying.desktop_hint(), "Applying...");
        assert_eq!(applying.panel_caption(action, &status), "Wait");

        let busy = ControlFeedback::snapshot(action, &status,
                                             Some(ControlAction::AudioDown), None, true);
        assert!(!busy.is_actionable());
        assert_eq!(busy.accessibility_label(), "busy");
        assert_eq!(busy.panel_caption(action, &status), "Busy");

        let failed = ControlFeedback::snapshot(action, &status,
                                               None, Some((action, false)), true);
        assert!(failed.is_actionable()); // retry is permitted
        assert_eq!(failed.accessibility_label(), "failed");
        assert_eq!(failed.desktop_hint(), "Action failed");
        assert_eq!(failed.panel_caption(action, &status), "Failed");
    }

    #[test]
    fn missing_worker_or_hardware_is_not_presented_as_clickable() {
        let status = connected();
        let action = ControlAction::AudioMute;
        let no_worker = ControlFeedback::snapshot(action, &status, None, None, false);
        assert_eq!(no_worker, ControlFeedback::Unavailable);
        assert!(!no_worker.is_actionable());
        assert_eq!(no_worker.desktop_hint(), "Unavailable");

        let no_hardware = ControlFeedback::snapshot(
            action, &SystemStatus::default(), None, Some((action, false)), true);
        assert_eq!(no_hardware, ControlFeedback::Unavailable);
        assert!(!no_hardware.is_actionable());

        // Failure of a different control never contaminates this control.
        assert_eq!(ControlFeedback::snapshot(action, &status, None,
                   Some((ControlAction::WifiToggle, false)), true),
                   ControlFeedback::Ready);
        assert_eq!(ControlFeedback::snapshot(action, &status, None,
                   Some((action, true)), true), ControlFeedback::Ready);
    }
}
