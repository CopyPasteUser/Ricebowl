//! Opt-in native AT-SPI exposure for RicePlate's hand-painted Wayland shell.
//!
//! AccessKit owns D-Bus/AT-SPI. Only immutable, bounded UI snapshots cross
//! threads; action requests return to the existing Wayland event loop. There
//! is no second renderer, polling service, or command supplied by AT clients.

use std::collections::{HashMap, HashSet};
use std::sync::{Arc, Mutex};

use crate::desktop_context::Action as ShortcutAction;
use accesskit::{
    Action, ActionHandler, ActionRequest, ActivationHandler, DeactivationHandler, Node, NodeId,
    Role, TextPosition, TextSelection, TreeId, TreeInfo, TreeUpdate,
};
use accesskit_unix::Adapter;
use chrono::NaiveDate;
use unicode_segmentation::UnicodeSegmentation;

pub const ROOT: u64 = 1;

fn access_character_lengths(text: &str) -> Vec<u8> {
    let mut lengths = Vec::new();
    for grapheme in text.graphemes(true) {
        if let Ok(size) = u8::try_from(grapheme.len()) {
            lengths.push(size);
        } else {
            // Oversized ZWJ sequences cannot fit AccessKit's u8 encoding.
            // Keep the value whole, expressing multiple scalar positions.
            lengths.extend(grapheme.chars().map(|c| c.len_utf8() as u8));
        }
    }
    lengths
}

/// Keep accessibility strings complete at extended-grapheme boundaries.
/// AccessKit's character table is built from the same filtered string used
/// for caret projection; it must not expose a half-emoji or isolated mark.
fn bounded_accessible_text(text: &str, limit: usize) -> String {
    let mut cleaned = String::new();
    let mut used = 0_usize;
    for grapheme in text.graphemes(true) {
        if grapheme.chars().any(char::is_control) {
            continue;
        }
        let scalars = grapheme.chars().count();
        if scalars > limit.saturating_sub(used) {
            break;
        }
        cleaned.push_str(grapheme);
        used += scalars;
    }
    cleaned
}

/// Project editor caret/selection through the same control-stripping and
/// grapheme-preserving truncation as the exposed text. The normal editor
/// cannot contain controls, but an invalid external snapshot must still be
/// internally coherent and never point into a discarded cluster.
fn bounded_editor_text(
    text: &str,
    caret: usize,
    anchor: Option<usize>,
) -> (String, usize, Option<usize>) {
    let mut cleaned = String::new();
    let mut used = 0_usize;
    // Track offsets in the *filtered bytes*, not the original grapheme count:
    // removing a control can join formerly separate graphemes (e.g. "e\\n◌́").
    // The old count then placed AT-SPI carets past the last visible character.
    let mut caret_byte = 0_usize;
    let mut anchor_byte = 0_usize;
    for (index, grapheme) in text.graphemes(true).enumerate() {
        if grapheme.chars().any(char::is_control) {
            continue;
        }
        let scalars = grapheme.chars().count();
        if scalars > crate::luna_dialog::MAX_INPUT.saturating_sub(used) {
            break;
        }
        cleaned.push_str(grapheme);
        used += scalars;
        if index < caret {
            caret_byte = cleaned.len();
        }
        if anchor.is_some_and(|a| index < a) {
            anchor_byte = cleaned.len();
        }
    }
    // Re-segment the final exposed text; a previously valid boundary may
    // now lie inside a combined cluster. Round forward to the first complete
    // visible grapheme so neither caret nor selection splits a Unicode glyph.
    let boundaries: Vec<usize> = cleaned
        .grapheme_indices(true)
        .map(|(offset, _)| offset)
        .chain(std::iter::once(cleaned.len()))
        .collect();
    let project = |byte: usize| boundaries.partition_point(|&offset| offset < byte);
    (
        cleaned,
        project(caret_byte),
        anchor.map(|_| project(anchor_byte)),
    )
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Target {
    Launcher(usize),
    PanelAction(String),
    Task(usize),
    Clock,
    Tray(usize),
    Status(crate::recipe::Widget),
    DesktopIcon(usize),
    DesktopContextAction {
        icon: usize,
        generation: u64,
        action: ShortcutAction,
    },
    DesktopContextBack {
        icon: usize,
        generation: u64,
    },
    DesktopWidget(usize),
    MenuGroup(usize),
    MenuAction(String),
    MenuSearch,
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
    /// Present only while the real editable modal is open. Never persisted.
    pub value: Option<String>,
    /// A logical extended-grapheme caret (TextInput nodes only).
    pub caret: Option<usize>,
    /// Logical selection anchor, separate from the focused caret.
    pub selection_anchor: Option<usize>,
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
            label: bounded_accessible_text(&label, 160),
            description: None,
            action,
            value: None,
            caret: None,
            selection_anchor: None,
        });
    }

    /// One real accessible text editor plus a TextRun child. AccessKit
    /// requires the child's UTF-8-length table and a selection on that child
    /// for screen-reader caret/character reporting, including empty fields.
    /// User text is copied into the transient AT-SPI snapshot *only* while
    /// the modal is active; it is never added to labels, logs or saved state.
    pub fn add_text_input(
        &mut self,
        id: u64,
        parent: u64,
        label: &str,
        value: &str,
        caret: usize,
        anchor: Option<usize>,
    ) {
        // One text input owns exactly two sibling IDs (input + text run).
        // Reject overflow, the reserved root and collisions *before* adding
        // either node; otherwise debug builds can panic and release builds can
        // wrap a child ID to 0 or silently create a run without its parent.
        let Some(run_id) = id.checked_add(1) else {
            return;
        };
        if id <= ROOT
            || run_id == ROOT
            || self
                .elements
                .iter()
                .any(|element| element.id == id || element.id == run_id)
        {
            return;
        }
        // The native editor already restricts length, but isolate external
        // accessibility consumers from unbounded/invalid snapshot content.
        let (value, safe_caret, safe_anchor) = bounded_editor_text(value, caret, anchor);
        self.add(id, parent, Role::TextInput, label, None);
        self.add(run_id, id, Role::TextRun, "", None);
        if let Some(input) = self.elements.iter_mut().find(|item| item.id == id) {
            input.value = Some(value.clone());
            input.caret = Some(safe_caret);
            input.selection_anchor = safe_anchor;
        }
        if let Some(run) = self.elements.iter_mut().find(|item| item.id == run_id) {
            run.value = Some(value);
        }
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
            // AccessKit's AT-SPI adapter derives a static Label's accessible
            // name from its *value*, never its label: a Label that only
            // carries a label reaches screen readers as an empty name. Mirror
            // the text unless the element provides an explicit value.
            let value = element.value.as_ref().or_else(|| {
                (element.role == Role::Label && !element.label.is_empty()).then_some(&element.label)
            });
            if let Some(value) = value {
                node.set_value(value.clone());
                if element.role == Role::TextRun {
                    // AccessKit character lengths are UTF-8 byte lengths in
                    // u8. Preserve full graphemes whenever representable;
                    // split exceptionally long clusters by scalar otherwise.
                    node.set_character_lengths(access_character_lengths(value));
                } else if element.role == Role::TextInput {
                    let to_position = |graphemes: usize| {
                        let offset = value
                            .grapheme_indices(true)
                            .nth(graphemes)
                            .map_or(value.len(), |(index, _)| index);
                        TextPosition {
                            node: NodeId(element.id + 1),
                            character_index: access_character_lengths(&value[..offset]).len(),
                        }
                    };
                    let caret = element.caret.unwrap_or(0);
                    node.set_text_selection(TextSelection {
                        anchor: to_position(element.selection_anchor.unwrap_or(caret)),
                        focus: to_position(caret),
                    });
                }
            }
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
    fn native_menu_search_has_transient_text_run_with_exact_unicode_caret() {
        let mut model = Model::new();
        model.add(20_000, ROOT, Role::Menu, "Start", None);
        let query = "👩‍💻e\u{301}/";
        model.add_text_input(
            20_950,
            20_000,
            "Search applications and actions",
            query,
            3,
            None,
        );
        model.focus = 20_950;
        model.window_focused = true;
        let tree = model.tree();
        let input = &tree
            .nodes
            .iter()
            .find(|(id, _)| *id == NodeId(20_950))
            .expect("accessible search input")
            .1;
        let run = &tree
            .nodes
            .iter()
            .find(|(id, _)| *id == NodeId(20_951))
            .expect("accessible query text run")
            .1;
        assert_eq!(input.role(), Role::TextInput);
        assert_eq!(input.label(), Some("Search applications and actions"));
        assert_eq!(run.value(), Some(query));
        assert_eq!(run.character_lengths(), [11, 3, 1]);
        assert_eq!(input.text_selection().unwrap().focus.character_index, 3);
        assert_eq!(tree.focus, NodeId(20_950));
        // Hidden Start menus must not retain query data in published AT-SPI.
        let closed = Model::new().tree();
        assert!(!format!("{closed:?}").contains(query));
    }

    #[test]
    fn unicode_editor_exposes_text_run_and_grapheme_caret_only_while_live() {
        let mut model = Model::new();
        model.add(60_000, ROOT, Role::Dialog, "Rename File", None);
        let secret = "a\u{301}👩‍💻🇩🇪.txt";
        model.add_text_input(60_100, 60_000, "File name", secret, 2, None);
        model.focus = 60_100;
        model.window_focused = true;
        let tree = model.tree();
        let editor = &tree
            .nodes
            .iter()
            .find(|(id, _)| *id == NodeId(60_100))
            .unwrap()
            .1;
        let run = &tree
            .nodes
            .iter()
            .find(|(id, _)| *id == NodeId(60_101))
            .unwrap()
            .1;
        assert_eq!(editor.role(), Role::TextInput);
        assert_eq!(editor.label(), Some("File name"));
        assert_eq!(run.role(), Role::TextRun);
        assert_eq!(run.value(), Some(secret));
        assert_eq!(run.character_lengths(), [3, 11, 8, 1, 1, 1, 1]);
        assert_eq!(
            run.character_lengths()
                .iter()
                .map(|n| *n as usize)
                .sum::<usize>(),
            secret.len()
        );
        let selection = editor.text_selection().unwrap();
        assert_eq!(selection.focus.node, NodeId(60_101));
        assert_eq!(selection.focus.character_index, 2);
        assert_eq!(tree.focus, NodeId(60_100));
        assert!(format!("{tree:?}").contains("👩"));

        // Destroying a dialog removes all command and filename text from
        // the published model, not merely a stale focused element.
        let closed = Model::new();
        let next = closed.tree();
        assert!(!format!("{next:?}").contains(secret));
        assert_eq!(next.nodes.len(), 1);
    }

    #[test]
    fn selected_unicode_text_reports_distinct_accesskit_anchor_and_focus() {
        let mut model = Model::new();
        model.add(60_000, ROOT, Role::Dialog, "Rename File", None);
        model.add_text_input(60_100, 60_000, "File name", "a\u{301}👩‍💻Z.txt", 3, Some(1));
        let tree = model.tree();
        let editor = &tree
            .nodes
            .iter()
            .find(|(id, _)| *id == NodeId(60_100))
            .unwrap()
            .1;
        let selection = editor.text_selection().unwrap();
        assert_eq!(selection.anchor.node, NodeId(60_101));
        assert_eq!(selection.anchor.character_index, 1);
        assert_eq!(selection.focus.character_index, 3);
        // Bounds belong to the *transient* accessibility model; stale
        // file names and Run argv are not present after modal teardown.
        assert!(!format!("{:?}", Model::new().tree()).contains("Z.txt"));
    }

    #[test]
    fn invalid_text_node_ids_never_overflow_or_leave_orphan_run_children() {
        let mut model = Model::new();
        for id in [0, ROOT, u64::MAX] {
            model.add_text_input(id, ROOT, "Invalid", "private", 1, None);
            assert!(
                model.elements.is_empty(),
                "reserved/overflow ID inserted: {id}"
            );
        }

        // A child's ID may already belong to another accessible widget.
        // Reject the pair atomically without overwriting that live widget.
        model.add(10, ROOT, Role::Button, "Existing", None);
        model.add_text_input(9, ROOT, "Unsafe", "secret", 1, None);
        assert_eq!(model.elements.len(), 1);
        assert_eq!(model.elements[0].label, "Existing");

        model.add_text_input(20, ROOT, "File name", "a\u{301}.txt", 1, Some(0));
        assert_eq!(model.elements.len(), 3);
        let tree = model.tree();
        assert!(tree.nodes.iter().any(|(node, _)| *node == NodeId(20)));
        assert!(tree.nodes.iter().any(|(node, _)| *node == NodeId(21)));
        assert!(!format!("{tree:?}").contains("secret"));
    }

    #[test]
    fn accessibility_editor_handles_long_clusters_and_empty_input() {
        let mut model = Model::new();
        model.add(60_000, ROOT, Role::Dialog, "Run", None);
        model.add_text_input(60_100, 60_000, "Command", "", 0, None);
        let tree = model.tree();
        let empty = &tree
            .nodes
            .iter()
            .find(|(id, _)| *id == NodeId(60_101))
            .unwrap()
            .1;
        assert!(empty.character_lengths().is_empty());
        assert_eq!(empty.value(), Some(""));
        let huge = format!("a{}z", "\u{301}".repeat(150));
        assert_eq!(
            huge.graphemes(true).count(),
            2,
            "test must include one cluster larger than u8::MAX"
        );
        // A synthetic oversized grapheme is only for the AccessKit data
        // contract; the production Luna editor caps 192 Unicode scalars.
        let lengths = access_character_lengths(&huge);
        assert!(lengths.iter().all(|n| *n > 0));
        assert_eq!(
            lengths.iter().map(|n| *n as usize).sum::<usize>(),
            huge.len()
        );
    }

    #[test]
    fn accesskit_editor_caret_and_selection_follow_sanitized_clusters() {
        let mut model = Model::new();
        model.add(60_000, ROOT, Role::Dialog, "Rename File", None);
        // Raw caret=3 follows A + newline + the emoji. Newline is invalid
        // editor text: AT-SPI must place the caret after A + emoji (index 2).
        model.add_text_input(60_100, 60_000, "File name", "A\n👩‍💻B", 3, Some(2));
        let tree = model.tree();
        let editor = &tree
            .nodes
            .iter()
            .find(|(id, _)| *id == NodeId(60_100))
            .unwrap()
            .1;
        let run = &tree
            .nodes
            .iter()
            .find(|(id, _)| *id == NodeId(60_101))
            .unwrap()
            .1;
        assert_eq!(run.value(), Some("A👩‍💻B"));
        assert_eq!(run.character_lengths(), [1, 11, 1]);
        let selection = editor.text_selection().unwrap();
        assert_eq!(selection.anchor.character_index, 1);
        assert_eq!(selection.focus.character_index, 2);
        assert_eq!(selection.focus.node, NodeId(60_101));
    }

    #[test]
    fn sanitized_editor_resegments_joined_graphemes_before_publishing_caret() {
        // Stripping a control can join a base and combining mark into ONE
        // exposed character. The old projection reported a phantom caret=2.
        let (text, caret, anchor) = bounded_editor_text("e\n\u{301}Z", 2, Some(1));
        assert_eq!(text, "e\u{301}Z");
        assert_eq!(text.graphemes(true).count(), 2);
        assert_eq!((caret, anchor), (1, Some(1)));
        let mut model = Model::new();
        model.add_text_input(60_100, ROOT, "Command", "e\n\u{301}Z", 2, Some(1));
        let tree = model.tree();
        let editor = &tree
            .nodes
            .iter()
            .find(|(id, _)| *id == NodeId(60_100))
            .expect("TextInput node")
            .1;
        let run = &tree
            .nodes
            .iter()
            .find(|(id, _)| *id == NodeId(60_101))
            .expect("TextRun node")
            .1;
        assert_eq!(run.value(), Some("e\u{301}Z"));
        assert_eq!(run.character_lengths(), [3, 1]);
        let selection = editor.text_selection().expect("exposed caret");
        assert_eq!(selection.anchor.character_index, 1);
        assert_eq!(selection.focus.character_index, 1);
    }

    #[test]
    fn accessibility_projection_clamps_after_truncation_and_control_removal() {
        let oversize = format!("{}\n\u{301}🇩🇪", "x".repeat(crate::luna_dialog::MAX_INPUT));
        let (text, caret, anchor) = bounded_editor_text(&oversize, usize::MAX, Some(0));
        assert_eq!(text, "x".repeat(crate::luna_dialog::MAX_INPUT));
        assert_eq!(caret, crate::luna_dialog::MAX_INPUT);
        assert_eq!(anchor, Some(0));
        let (text, caret, anchor) = bounded_editor_text("\n", 1, Some(0));
        assert!(text.is_empty());
        assert_eq!((caret, anchor), (0, Some(0)));
    }

    #[test]
    fn accessible_names_and_text_never_truncate_inside_graphemes() {
        let mut model = Model::new();
        let label = format!("{}a\u{301}", "x".repeat(159));
        model.add(8, ROOT, Role::Label, label, None);
        assert_eq!(model.elements[0].label, "x".repeat(159));
        model.add_text_input(
            60_100,
            ROOT,
            "Command",
            &format!("{}👩‍💻", "x".repeat(190)),
            999,
            Some(999),
        );
        let tree = model.tree();
        let run = &tree
            .nodes
            .iter()
            .find(|(id, _)| *id == NodeId(60_101))
            .unwrap()
            .1;
        let editor = &tree
            .nodes
            .iter()
            .find(|(id, _)| *id == NodeId(60_100))
            .unwrap()
            .1;
        assert_eq!(run.value(), Some("x".repeat(190).as_str()));
        assert_eq!(run.character_lengths().len(), 190);
        let sel = editor.text_selection().unwrap();
        assert_eq!(sel.focus.character_index, 190);
        assert_eq!(sel.anchor.character_index, 190);
        // The original renderer value is never put into the node label.
        assert_eq!(editor.label(), Some("Command"));
    }

    #[test]
    fn context_actions_include_a_revision_to_reject_stale_popup_reuse() {
        let mut before = Model::new();
        before.add(32_000, ROOT, Role::Menu, "Shortcut", None);
        before.add(
            32_100,
            32_000,
            Role::MenuItem,
            "Open",
            Some(Target::DesktopContextAction {
                icon: 0,
                generation: 4,
                action: ShortcutAction::Open,
            }),
        );
        let request = ActionRequest {
            action: Action::Click,
            target_tree: TreeId::ROOT,
            target_node: NodeId(32_100),
            data: None,
        };
        let old = before.action_for(&request);
        assert!(old.is_some());
        let mut next = before.clone();
        next.elements[1].action = Some(Target::DesktopContextAction {
            icon: 0,
            generation: 5,
            action: ShortcutAction::Open,
        });
        assert_ne!(old, next.action_for(&request));
        let mut properties = Model::new();
        properties.add(32_000, ROOT, Role::Dialog, "Properties", None);
        properties.add(
            32_900,
            32_000,
            Role::Button,
            "Back",
            Some(Target::DesktopContextBack {
                icon: 0,
                generation: 6,
            }),
        );
        assert_eq!(properties.action_for(&request), None);
    }

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
    fn static_label_text_is_exposed_as_the_value_atspi_reads() {
        // AccessKit's AT-SPI adapter names a Label from its value. A label
        // given only a label (the RicePop detail summary/body) was an empty
        // accessible name for screen readers.
        let mut model = Model::new();
        model.add(2, ROOT, Role::Label, "Subject", None);
        model.add(3, ROOT, Role::Button, "Dismiss", Some(Target::Clock));
        let tree = model.tree();
        let (label, button) = (&tree.nodes[1].1, &tree.nodes[2].1);
        assert_eq!(label.label(), Some("Subject"));
        assert_eq!(label.value(), Some("Subject"));
        // Only static text mirrors its label; controls keep their own name.
        assert_eq!(button.value(), None);
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
