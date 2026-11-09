//! Opt-in native AT-SPI exposure for RicePlate's hand-painted Wayland shell.
//!
//! AccessKit owns D-Bus/AT-SPI. Only immutable, bounded UI snapshots cross
//! threads; action requests return to the existing Wayland event loop. There
//! is no second renderer, polling service, or command supplied by AT clients.

use std::collections::{HashMap, HashSet};
use std::sync::{Arc, Mutex};

use accesskit::{
    Action, ActionHandler, ActionRequest, ActivationHandler, DeactivationHandler, Node, NodeId,
    Role, TreeId, TreeInfo, TreeUpdate,
};
use accesskit_unix::Adapter;
use chrono::NaiveDate;

pub const ROOT: u64 = 1;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Target {
    Launcher(usize),
    PanelAction(String),
    Task(usize),
    Clock,
    Tray(usize),
    DesktopIcon(usize),
    DesktopWidget(usize),
    MenuGroup(usize),
    MenuAction(String),
    MenuClose,
    MenuSaved,
    CalendarPrevious,
    CalendarNext,
    CalendarToday,
    CalendarDay(NaiveDate),
    NotificationTab(bool),
    NotificationSelect(usize),
    NotificationBodyPage(isize),
    NotificationInvoke(u32, String),
    NotificationRefresh,
    NotificationDismiss(u32),
    NotificationBack,
    TrayPopupItem(usize),
    TrayPopupClose,
    TrayPopupPage(i32),
    TrayMenuRow(usize),
    TrayMenuBack,
    TrayMenuClose,
    TrayMenuPage(i32),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Element {
    pub id: u64,
    pub parent: u64,
    pub role: Role,
    pub label: String,
    pub description: Option<String>,
    pub action: Option<Target>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Model {
    pub elements: Vec<Element>,
    pub focus: u64,
    pub window_focused: bool,
}

impl Model {
    pub fn new() -> Self {
        Self {
            elements: Vec::new(),
            focus: ROOT,
            window_focused: false,
        }
    }

    pub fn add(
        &mut self,
        id: u64,
        parent: u64,
        role: Role,
        label: impl Into<String>,
        action: Option<Target>,
    ) {
        // Recipes can repeat a visual panel widget. A second occurrence must
        // not bring down RicePlate because it shares the semantic node ID.
        if id == ROOT || self.elements.iter().any(|element| element.id == id) {
            return;
        }
        let label: String = label.into();
        self.elements.push(Element {
            id,
            parent,
            role,
            label: label
                .chars()
                .filter(|c| !c.is_control())
                .take(160)
                .collect(),
            description: None,
            action,
        });
    }

    pub fn action_for(&self, request: &ActionRequest) -> Option<Target> {
        if request.target_tree != TreeId::ROOT || request.action != Action::Click {
            return None;
        }
        self.elements
            .iter()
            .find(|element| element.id == request.target_node.0)
            .and_then(|element| element.action.clone())
    }

    pub fn tree(&self) -> TreeUpdate {
        let mut children: HashMap<u64, Vec<NodeId>> = HashMap::new();
        let mut ids = HashSet::new();
        ids.insert(ROOT);
        for element in &self.elements {
            assert_ne!(element.id, ROOT, "accessibility child may not be the root");
            assert!(ids.insert(element.id), "duplicate accessibility node");
            children
                .entry(element.parent)
                .or_default()
                .push(NodeId(element.id));
        }
        // Only the shell's own known node IDs may be parents; reject cycles or
        // accidentally orphaned nodes while building developer-controlled UI.
        assert!(self
            .elements
            .iter()
            .all(|element| ids.contains(&element.parent) && element.parent != element.id));
        let mut root = Node::new(Role::Window);
        root.set_label("RiceBowl desktop");
        root.set_children(children.remove(&ROOT).unwrap_or_default());
        let mut nodes = Vec::with_capacity(self.elements.len() + 1);
        nodes.push((NodeId(ROOT), root));
        for element in &self.elements {
            let mut node = Node::new(element.role);
            node.set_label(element.label.clone());
            if let Some(description) = &element.description {
                node.set_description(description.clone());
            }
            if element.action.is_some() {
                node.add_action(Action::Click);
            }
            node.set_children(children.remove(&element.id).unwrap_or_default());
            nodes.push((NodeId(element.id), node));
        }
        TreeUpdate {
            nodes,
            tree: Some(TreeInfo {
                root: NodeId(ROOT),
                toolkit_name: Some("RicePlate".into()),
                toolkit_version: Some(env!("CARGO_PKG_VERSION").into()),
            }),
            tree_id: TreeId::ROOT,
            focus: NodeId(if ids.contains(&self.focus) {
                self.focus
            } else {
                ROOT
            }),
        }
    }
}

struct Initial(Arc<Mutex<TreeUpdate>>);
impl ActivationHandler for Initial {
    fn request_initial_tree(&mut self) -> Option<TreeUpdate> {
        Some(
            self.0
                .lock()
                .unwrap_or_else(|poison| poison.into_inner())
                .clone(),
        )
    }
}

struct Requests(Box<dyn Fn(ActionRequest) + Send + Sync>);
impl ActionHandler for Requests {
    fn do_action(&mut self, request: ActionRequest) {
        // The adapter invokes this off the Wayland thread. Never mutate UI here.
        (self.0)(request);
    }
}

struct Deactivate;
impl DeactivationHandler for Deactivate {
    fn deactivate_accessibility(&mut self) {}
}

pub struct Bridge {
    adapter: Adapter,
    last: Model,
    latest: Arc<Mutex<TreeUpdate>>,
}

impl Bridge {
    pub fn new(model: Model, requests: impl 'static + Send + Sync + Fn(ActionRequest)) -> Self {
        let latest = Arc::new(Mutex::new(model.tree()));
        let mut adapter = Adapter::new(
            Initial(Arc::clone(&latest)),
            Requests(Box::new(requests)),
            Deactivate,
        );
        adapter.update_window_focus_state(model.window_focused);
        Self {
            adapter,
            last: model,
            latest,
        }
    }

    pub fn sync(&mut self, next: Model) {
        if self.last == next {
            return;
        }
        let update = next.tree();
        *self
            .latest
            .lock()
            .unwrap_or_else(|poison| poison.into_inner()) = update.clone();
        self.adapter.update_if_active(|| update);
        if self.last.window_focused != next.window_focused {
            self.adapter.update_window_focus_state(next.window_focused);
        }
        self.last = next;
    }

    pub fn action_for(&self, request: &ActionRequest) -> Option<Target> {
        self.last.action_for(request)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn panel_button_is_named_clickable_and_focus_is_real() {
        let mut model = Model::new();
        model.add(10, ROOT, Role::Toolbar, "Panel", None);
        model.add(
            11,
            10,
            Role::Button,
            "Open applications",
            Some(Target::Launcher(0)),
        );
        model.focus = 11;
        let update = model.tree();
        assert_eq!(update.nodes.len(), 3);
        assert_eq!(update.focus, NodeId(11));
        let button = &update.nodes[2].1;
        assert_eq!(button.role(), Role::Button);
        assert_eq!(button.label(), Some("Open applications"));
        assert!(button.supports_action(Action::Click));
        let request = ActionRequest {
            action: Action::Click,
            target_tree: TreeId::ROOT,
            target_node: NodeId(11),
            data: None,
        };
        assert_eq!(model.action_for(&request), Some(Target::Launcher(0)));
        assert_eq!(
            model.action_for(&ActionRequest {
                action: Action::Focus,
                ..request
            }),
            None
        );
    }

    #[test]
    fn disappearing_dialog_removes_private_text_and_stale_actions() {
        let mut model = Model::new();
        model.add(20, ROOT, Role::Dialog, "Notifications", None);
        model.add(
            21,
            20,
            Role::Button,
            "Message: sensitive subject",
            Some(Target::NotificationDismiss(12)),
        );
        let request = ActionRequest {
            action: Action::Click,
            target_tree: TreeId::ROOT,
            target_node: NodeId(21),
            data: None,
        };
        assert!(model.action_for(&request).is_some());
        let closed = Model::new();
        assert_eq!(closed.action_for(&request), None);
        assert!(!format!("{:?}", closed.tree()).contains("sensitive"));
    }

    #[test]
    fn unknown_focus_is_root_and_control_codes_are_removed() {
        let mut model = Model::new();
        model.add(2, ROOT, Role::Label, "Line\nOne", None);
        model.focus = 500;
        let tree = model.tree();
        assert_eq!(tree.focus, NodeId(ROOT));
        assert_eq!(tree.nodes[1].1.label(), Some("LineOne"));
    }

    #[test]
    fn repeated_widgets_do_not_crash_or_duplicate_semantic_ids() {
        let mut model = Model::new();
        model.add(3, ROOT, Role::Button, "Clock", Some(Target::Clock));
        model.add(3, ROOT, Role::Button, "Clock", Some(Target::Clock));
        model.add(ROOT, ROOT, Role::Label, "Invalid root", None);
        let update = model.tree();
        assert_eq!(update.nodes.len(), 2);
        assert_eq!(update.nodes[1].1.label(), Some("Clock"));
    }
}
