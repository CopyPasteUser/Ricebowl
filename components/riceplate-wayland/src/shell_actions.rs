//! Typed shell action vocabulary. Backends remain in the existing runtime.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Surface { Panel, Menu, Desktop }
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Kind { Launch, Place, Settings, Session, Window, Control, Notification, Dialog }
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct ShellAction {
    pub(crate) id: &'static str,
    pub(crate) kind: Kind,
    surfaces: &'static [Surface],
}
use self::Surface::{Panel as P, Menu as M, Desktop as D};
pub(crate) const ACTIONS: &[ShellAction] = &[
    ShellAction { id: "applications", kind: Kind::Launch, surfaces: &[P,M,D] },
    ShellAction { id: "terminal", kind: Kind::Launch, surfaces: &[P,M,D] },
    ShellAction { id: "settings", kind: Kind::Settings, surfaces: &[P,M,D] },
    ShellAction { id: "lock", kind: Kind::Session, surfaces: &[P,M,D] },
    ShellAction { id: "clip-history", kind: Kind::Launch, surfaces: &[P,M,D] },
    ShellAction { id: "show-desktop", kind: Kind::Window, surfaces: &[P,D] },
    ShellAction { id: "wifi-toggle", kind: Kind::Control, surfaces: &[P,M,D] },
    ShellAction { id: "audio-mute", kind: Kind::Control, surfaces: &[P,M,D] },
    ShellAction { id: "audio-up", kind: Kind::Control, surfaces: &[P,M,D] },
    ShellAction { id: "audio-down", kind: Kind::Control, surfaces: &[P,M,D] },
    ShellAction { id: "logout", kind: Kind::Session, surfaces: &[M] },
    ShellAction { id: "documents", kind: Kind::Place, surfaces: &[M,D] },
    ShellAction { id: "computer", kind: Kind::Place, surfaces: &[M,D] },
    ShellAction { id: "pictures", kind: Kind::Place, surfaces: &[M] },
    ShellAction { id: "music", kind: Kind::Place, surfaces: &[M] },
    ShellAction { id: "network", kind: Kind::Place, surfaces: &[D] },
    ShellAction { id: "trash", kind: Kind::Place, surfaces: &[D] },
    ShellAction { id: "notifications", kind: Kind::Notification, surfaces: &[M] },
    ShellAction { id: "help", kind: Kind::Dialog, surfaces: &[M] },
    ShellAction { id: "run", kind: Kind::Dialog, surfaces: &[M] },
];
impl ShellAction {
    pub(crate) fn from_id(id: &str) -> Option<Self> {
        ACTIONS.iter().copied().find(|item| item.id == id)
    }
    pub(crate) fn supports(self, surface: Surface) -> bool {
        self.surfaces.contains(&surface)
    }
    pub(crate) fn supported(id: &str, surface: Surface) -> bool {
        Self::from_id(id).is_some_and(|item| item.supports(surface))
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use crate::{control_feedback::ControlFeedback, recipe, system_status::{ControlAction,SystemStatus}};
    use std::collections::HashSet;

    #[test]
    fn allowlists_and_fail_closed() {
        let ids = |surface| ACTIONS.iter().filter(|x| x.supports(surface))
            .map(|x| x.id).collect::<HashSet<_>>();
        assert_eq!(ids(P), HashSet::from(["applications","terminal","settings","lock",
            "clip-history","show-desktop","wifi-toggle","audio-mute","audio-up","audio-down"]));
        assert_eq!(ids(M), HashSet::from(["applications","terminal","settings","lock","clip-history",
            "wifi-toggle","audio-mute","audio-up","audio-down","logout","documents","computer",
            "pictures","music","notifications","help","run"]));
        assert_eq!(ids(D), HashSet::from(["applications","terminal","settings","lock","clip-history",
            "show-desktop","wifi-toggle","audio-mute","audio-up","audio-down","documents",
            "computer","network","trash"]));
        assert_eq!(ACTIONS.len(), ACTIONS.iter().map(|a| a.id).collect::<HashSet<_>>().len());
        for id in ["", "exec:sh", "desktop:fake.desktop", "wifi-on", "quit", "run;sh"] {
            assert!(ShellAction::from_id(id).is_none());
        }
    }

    #[test]
    fn shared_hardware_controls_are_not_new_backends() {
        for id in ["wifi-toggle","audio-mute","audio-up","audio-down"] {
            assert_eq!(ShellAction::from_id(id).unwrap().kind, Kind::Control);
            let backend = ControlAction::from_id(id).unwrap();
            assert_eq!(ControlFeedback::snapshot(backend, &SystemStatus::default(),
                None, None, false), ControlFeedback::Unavailable);
        }
    }

    #[test]
    fn two_reusable_recipe_layouts_parse_in_native_engine() {
        let a = recipe::parse(include_str!("../../../examples/wayland/test-taskbar-shell.json"),
            Some("test-taskbar-shell")).unwrap();
        let b = recipe::parse(include_str!("../../../examples/wayland/test-dock-shell.json"),
            Some("test-dock-shell")).unwrap();
        assert_ne!(a.sections, b.sections);
        assert_ne!(a.background, b.background);
        assert_ne!(a.menu.as_ref().unwrap().presentation, b.menu.as_ref().unwrap().presentation);
        for item in [&a, &b] {
            for width in [800, 1366] {
                let layout = recipe::layout(item, width, 3);
                assert!(layout.iter().any(|w| w.widget == recipe::Widget::Launcher));
                assert!(layout.iter().any(|w| w.widget == recipe::Widget::Tasks));
                assert!(layout.iter().any(|w| w.widget == recipe::Widget::Clock));
            }
        }
    }

    #[test]
    fn component_binding_accepts_shared_show_desktop_but_no_commands() {
        let mut data: serde_json::Value = serde_json::from_str(
            include_str!("../../../examples/wayland/test-taskbar-shell.json")).unwrap();
        data["components"].as_array_mut().unwrap().push(serde_json::json!({
            "id":"desktop-switch","role":"action","binding":"show-desktop","label":"Desktop"
        }));
        data["panel"]["layout"]["start"].as_array_mut().unwrap().push(
            serde_json::json!({"type":"component","ref":"desktop-switch"}));
        assert!(recipe::parse(&data.to_string(), None).unwrap().actions.iter()
            .any(|a| a.id == "show-desktop"));
        data["components"][2]["binding"] = serde_json::json!("exec:unsafe");
        assert!(recipe::parse(&data.to_string(), None).is_err());
    }
}
