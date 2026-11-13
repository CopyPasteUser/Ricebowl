//! Native RicePlate experiment: an input-capable, idle event-driven layer surface.
//! No session takeover: launch only inside an already running Wayland session.

use std::{error::Error, os::fd::AsFd, process::Command, sync::mpsc, time::{Duration, Instant}};

use chrono::{Local, Timelike};
use accesskit::{ActionRequest, Role as AccessibleRole};
mod accessibility;
mod brightness;
mod calendar;
mod control_feedback;
mod desktop_context;
mod desktop_files;
mod desktop_layout;
mod desktop_selection;
mod frame_scheduler;
mod input_core;
mod icon_positions;
mod installed_apps;
mod luna_places;
mod luna_dialog;
mod luna_clock;
mod luna_taskbar;
mod luna_desktop_ipc;
mod menu_chrome;
mod menu_pins;
mod menu_recents;
mod native_menu;
mod panel_chrome;
mod osd;
mod overlay_renderer;
mod output_watch;
mod power;
mod raster;
mod recipe;
mod style_art;
mod ricepop;
mod system_status;
mod task_groups;
mod task_navigation;
mod text_render;
mod tray;
use tray::{MenuChoice as TrayMenuChoice, MenuHit as TrayMenuHit, PopupHit as TrayHit};
use native_menu::{Hit as MenuHit, MenuState};
use power::PowerStatus;
use ricepop::{Intent as NotificationIntent, Request as NotificationRequest,
              State as NotificationState};
use system_status::{Audio, ControlAction, SystemStatus};
use control_feedback::ControlFeedback;
use frame_scheduler::FrameGate;
use input_core::{PanelKey, PanelPointerVisual, PointerSignal};
use raster::{fill_rect, fill_rounded_rect};
use overlay_renderer::{paint_calendar, paint_compact_notifications, paint_notifications};
#[cfg(test)]
use overlay_renderer::draw_notification_text;
use text_render::{draw_auxiliary_text, draw_rice_text, draw_text,
                  fit_rice_text, rice_text_width, text_pixel_width};

enum StatusEvent {
    State(SystemStatus),
    Control { action: ControlAction, success: bool, state: SystemStatus },
    ObservedAudio(Audio),
}
use calendar::{CalendarState, Hit as CalendarHit};
use desktop_context::Action as DesktopContextAction;
use recipe::{Hit, PanelStyle, Widget};
use task_navigation::Target as KeyboardTarget;
use smithay_client_toolkit::{
    compositor::{CompositorHandler, CompositorState, FrameCallbackData, Region},
    delegate_registry,
    output::{OutputHandler, OutputState},
    reexports::{calloop::{channel, generic::Generic, EventLoop, Interest, Mode, PostAction},
                calloop_wayland_source::WaylandSource},
    registry::{ProvidesRegistryState, RegistryState},
    registry_handlers,
    seat::{
        keyboard::{KeyEvent, KeyboardHandler, Keysym, Modifiers, RawModifiers},
        pointer::{PointerEvent, PointerEventKind, PointerHandler},
        Capability, SeatHandler, SeatState,
    },
    shell::{
        xdg::{XdgShell, XdgPositioner, popup::{Popup, PopupConfigure, PopupHandler},
              window::{Window, WindowConfigure, WindowHandler}},
        wlr_layer::{
            Anchor, KeyboardInteractivity, Layer, LayerShell, LayerShellHandler, LayerSurface,
            LayerSurfaceConfigure,
        },
        WaylandSurface,
    },
    shm::{slot::SlotPool, Shm, ShmHandler},
};
use task_groups::{TaskGroup, WindowInfo};
use wayland_client::{
    globals::registry_queue_init,
    protocol::{wl_keyboard, wl_output, wl_pointer, wl_seat, wl_shm, wl_surface},
    Connection, Dispatch, QueueHandle,
};
use smithay_client_toolkit::reexports::protocols::xdg::shell::client::xdg_positioner;
use wayland_protocols_wlr::foreign_toplevel::v1::client::{
    zwlr_foreign_toplevel_handle_v1::{self, ZwlrForeignToplevelHandleV1},
    zwlr_foreign_toplevel_manager_v1::{self, ZwlrForeignToplevelManagerV1},
};

const MAX_WIDTH: u32 = 16384;
const MAX_HEIGHT: u32 = 256;
const MAX_OUTPUT_PANELS: usize = 8;
const BTN_LEFT: u32 = 0x110;
const BTN_RIGHT: u32 = 0x111;

fn luna_hover_target(hit: Option<Hit>) -> Option<Hit> {
    hit.filter(|target| matches!(target, Hit::Launcher | Hit::Task(_)))
}


#[derive(Debug, PartialEq, Eq)]
enum MenuSizeDecision {
    Accept,
    AwaitNewConfigure,
    RetryExpectedSize,
}

fn menu_size_decision(expected: (u32, u32), offered: (u32, u32),
                      awaiting_resize: bool) -> MenuSizeDecision {
    if offered == expected { MenuSizeDecision::Accept }
    else if awaiting_resize { MenuSizeDecision::AwaitNewConfigure }
    else { MenuSizeDecision::RetryExpectedSize }
}

fn clock_now(format: luna_clock::ClockFormat) -> String {
    luna_clock::format_time(Local::now().time(), format)
}

fn next_clock_timeout() -> Duration {
    let now = Local::now();
    let milliseconds =
        u64::from(60 - now.second()) * 1000 - u64::from(now.nanosecond() / 1_000_000);
    Duration::from_millis(milliseconds.max(50))
}

fn main() -> Result<(), Box<dyn Error>> {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    // Explicit test entrypoint for CI and packagers; no Wayland connection.
    if matches!(arguments.as_slice(), [arg] if arg == "--version") {
        println!("riceplate-native 0.1.0 (experimental)");
        return Ok(());
    }
    if matches!(arguments.as_slice(), [arg] if arg == "--clear-luna-recents") {
        menu_recents::clear()?;
        println!("XP Luna recent applications cleared");
        return Ok(());
    }
    if let [flag, action] = arguments.as_slice() {
        if flag == "--desktop-command" {
            let request = luna_desktop_ipc::Request::parse(action)
                .ok_or("Unknown or unsafe desktop command")?;
            luna_desktop_ipc::send(request)?;
            return Ok(());
        }
    }
    if matches!(arguments.as_slice(), [arg] if arg == "--watch-outputs") {
        return output_watch::run();
    }
    if matches!(arguments.as_slice(), [arg] if arg == "--help") {
        println!("Usage: riceplate-native [--recipe classic|chrome|/absolute/private.json [--preview-menu|--preview-calendar|--preview-osd|--preview-notifications|--preview-notification-detail|--preview-notifications-scroll]]\n       riceplate-native --watch-outputs (RiceBowl session only)\n       riceplate-native --clear-luna-recents (clear private XP Luna app history)");
        return Ok(());
    }
    let (recipe_name, preview_menu, preview_calendar, preview_osd, preview_notifications,
         preview_notification_detail, preview_notifications_scroll) = match arguments.as_slice() {
        [] => ("classic", false, false, false, false, false, false),
        [flag, recipe] if flag == "--recipe" =>
            (recipe.as_str(), false, false, false, false, false, false),
        [flag, recipe, preview] if flag == "--recipe" && preview == "--preview-menu" =>
            (recipe.as_str(), true, false, false, false, false, false),
        [flag, recipe, preview] if flag == "--recipe" && preview == "--preview-calendar" =>
            (recipe.as_str(), false, true, false, false, false, false),
        [flag, recipe, preview] if flag == "--recipe" && preview == "--preview-osd" =>
            (recipe.as_str(), false, false, true, false, false, false),
        [flag, recipe, preview] if flag == "--recipe" && preview == "--preview-notifications" =>
            (recipe.as_str(), false, false, false, true, false, false),
        [flag, recipe, preview] if flag == "--recipe" && preview == "--preview-notification-detail" =>
            (recipe.as_str(), false, false, false, false, true, false),
        [flag, recipe, preview] if flag == "--recipe" && preview == "--preview-notifications-scroll" =>
            (recipe.as_str(), false, false, false, false, false, true),
        _ => {
            return Err(
                "Usage: riceplate-native [--recipe classic|chrome|/absolute/private.json [--preview-menu|--preview-calendar|--preview-osd|--preview-notifications|--preview-notification-detail|--preview-notifications-scroll]]".into(),
            )
        }
    };
    let mut recipe = recipe::load(recipe_name)?;
    // Reading the owner-private setting is optional and confined to Luna.
    // Other rices always retain the exact existing 24-hour clock behavior.
    let clock_format = if recipe.id == "xp-luna-columns" {
        luna_clock::load()
    } else {
        luna_clock::ClockFormat::Hour24
    };
    let luna_options = if recipe.id == "xp-luna-columns" {
        luna_taskbar::load()
    } else {
        luna_taskbar::Options::default()
    };
    if recipe.id == "xp-luna-columns" && !luna_options.quick_launch {
        // A hidden Quick Launch reserves no space or hit targets. Action
        // indices remain stable for existing menu and Creator contracts.
        let actions = &recipe.actions;
        for section in &mut recipe.sections {
            section.retain(|widget| !matches!(widget, Widget::Action(index)
                if actions.get(*index as usize)
                    .is_some_and(|action| luna_taskbar::is_quick_launch(&action.id))));
        }
        if let Some((_, sections)) = recipe.compact.as_mut() {
            for section in sections {
                section.retain(|widget| !matches!(widget, Widget::Action(index)
                    if actions.get(*index as usize)
                        .is_some_and(|action| luna_taskbar::is_quick_launch(&action.id))));
            }
        }
    }
    if let Some(selection) = recipe.artwork.as_ref() {
        recipe.native_art = Some(style_art::load(selection, recipe.font_scale)?);
    }
    let icon_outputs = icon_positions::restore(&mut recipe).unwrap_or_else(|error| {
        eprintln!("RicePlate: ignored invalid saved desktop icon positions: {error}");
        icon_positions::OutputPositions::default()
    });
    let saved_menu_pins = recipe.menu.as_ref().map_or_else(Vec::new, |menu| {
        menu_pins::restore(&recipe.id, menu).unwrap_or_else(|error| {
            eprintln!("RicePlate: ignored invalid saved menu pins: {error}");
            Vec::new()
        })
    });
    let saved_menu_recents = menu_recents::restore(&recipe.id).unwrap_or_else(|error| {
        eprintln!("RicePlate: ignored invalid XP Luna recent applications: {error}");
        Vec::new()
    });
    if (preview_menu || preview_notifications || preview_notification_detail || preview_notifications_scroll)
        && recipe.menu.is_none() {
        return Err("Native menu preview requires schema v4/v5".into());
    }
    let clock_present = recipe.sections.iter().flatten().any(|widget| *widget == Widget::Clock)
        || recipe.compact.as_ref().is_some_and(|(_, sections)|
            sections.iter().flatten().any(|widget| *widget == Widget::Clock));
    let status_present = |widget| recipe.sections.iter().flatten().any(|&item| item == widget)
        || recipe.compact.as_ref().is_some_and(|(_, sections)|
            sections.iter().flatten().any(|&item| item == widget));
    let menu_controls: Vec<_> = recipe.menu.as_ref().into_iter()
        .flat_map(|menu| menu.groups.iter())
        .flat_map(|group| group.actions.iter())
        .filter_map(|action| ControlAction::from_id(action)).collect();
    let has_notifications = recipe.menu.as_ref().is_some_and(|menu|
        menu.groups.iter().any(|group| group.actions.iter().any(|action| action == "notifications")));
    let panel_controls: Vec<_> = recipe.actions.iter()
        .filter(|action| action.control)
        .filter_map(|action| ControlAction::from_id(&action.id)).collect();
    let desktop_controls: Vec<_> = recipe.composition.as_ref().into_iter()
        .flat_map(|composition| composition.widgets.iter())
        .filter_map(|widget| match &widget.kind {
            recipe::DesktopWidgetKind::Action(action) => ControlAction::from_id(action),
            _ => None,
        }).collect();
    let desktop_network = recipe.composition.as_ref().is_some_and(|composition|
        composition.widgets.iter().any(|widget| matches!(&widget.kind,
            recipe::DesktopWidgetKind::System | recipe::DesktopWidgetKind::Network)));
    let desktop_audio = recipe.composition.as_ref().is_some_and(|composition|
        composition.widgets.iter().any(|widget| matches!(&widget.kind,
            recipe::DesktopWidgetKind::System | recipe::DesktopWidgetKind::Audio)));
    let poll_network = desktop_network || status_present(Widget::Network)
        || menu_controls.contains(&ControlAction::WifiToggle)
        || panel_controls.contains(&ControlAction::WifiToggle)
        || desktop_controls.contains(&ControlAction::WifiToggle);
    // A native full desktop has volume OSD even when a rice omits the audio
    // indicator. Nested design previews retain the old opt-in behavior.
    let full_session = std::env::var("RICEBOWL_DE_NESTED").as_deref() != Ok("1");
    let poll_audio = preview_osd || full_session || desktop_audio || status_present(Widget::Audio)
        || menu_controls.iter().chain(panel_controls.iter()).chain(desktop_controls.iter()).any(|action|
            matches!(action, ControlAction::AudioMute | ControlAction::AudioUp | ControlAction::AudioDown));
    let use_tray = status_present(Widget::Tray);
    if preview_calendar && !clock_present {
        return Err("Calendar preview requires a native clock widget".into());
    }
    let conn = Connection::connect_to_env()?;
    let (globals, event_queue) = registry_queue_init(&conn)?;
    let qh = event_queue.handle();
    let mut event_loop: EventLoop<RicePlate> = EventLoop::try_new()?;
    WaylandSource::new(conn.clone(), event_queue).insert(event_loop.handle())?;
    let compositor = CompositorState::bind(&globals, &qh)?;
    let layer_shell = LayerShell::bind(&globals, &qh)?;
    // Optional XDG shell is used only for the opt-in Luna shortcut menu.
    // Other recipes retain the original layer-shell-only startup behavior.
    let xdg_shell = (recipe.id == "xp-luna-columns")
        .then(|| XdgShell::bind(&globals, &qh).ok()).flatten();
    let shm = Shm::bind(&globals, &qh)?;
    let toplevel_manager: Option<ZwlrForeignToplevelManagerV1> = globals.bind(&qh, 1..=3, ()).ok();
    if toplevel_manager.is_none() {
        eprintln!("RicePlate: compositor lacks wlr-foreign-toplevel-management; taskbar disabled");
    }
    // Honor Auto-hide from the first committed layer-shell frame; do not
    // briefly reserve 40 pixels until the pointer happens to leave.
    let initial_panel_height = luna_taskbar::panel_height(
        luna_options, luna_options.auto_hide, recipe.height);
    let initial_panel_collapsed = initial_panel_height < recipe.height;
    let layer = layer_shell.create_layer_surface(
        &qh,
        compositor.create_surface(&qh),
        Layer::Top,
        Some("riceplate-preview"),
        None,
    );
    let edge = if recipe.top {
        Anchor::TOP
    } else {
        Anchor::BOTTOM
    };
    layer.set_anchor(edge | Anchor::LEFT | Anchor::RIGHT);
    layer.set_size(0, initial_panel_height);
    layer.set_exclusive_zone(initial_panel_height as i32);
    layer.set_keyboard_interactivity(KeyboardInteractivity::OnDemand);
    layer.commit();

    // One small Bottom-layer surface per icon: transparent desktop space is
    // never covered by a full-screen input-catching window.
    let mut icon_layers = Vec::new();
    for (recipe_index, icon) in recipe.desktop_icons.iter().enumerate() {
        let surface = layer_shell.create_layer_surface(
            &qh,
            compositor.create_surface(&qh),
            Layer::Bottom,
            Some("riceplate-desktop-icon"),
            None,
        );
        surface.set_anchor(Anchor::TOP | Anchor::LEFT);
        surface.set_size(recipe::ICON_WIDTH, recipe::ICON_HEIGHT);
        surface.set_margin(icon.y as i32, 0, 0, icon.x as i32);
        surface.set_exclusive_zone(-1);
        surface.set_keyboard_interactivity(KeyboardInteractivity::OnDemand);
        surface.commit();
        icon_layers.push(IconLayer {
            recipe_index,
            surface,
            pool: None,
            configured: false,
            output: None,
            bound_output: None,
            placed: Some((icon.x, icon.y)),
        });
    }
    // Status/text widgets are input-transparent; explicitly action-bound
    // widgets alone own their bounded hit rectangle and on-demand keyboard focus.
    let mut widget_layers = Vec::new();
    if let Some(composition) = recipe.composition.as_ref() {
        let empty_input = Region::new(&compositor)?;
        for (recipe_index, widget) in composition.widgets.iter().enumerate() {
            let surface = layer_shell.create_layer_surface(
                &qh, compositor.create_surface(&qh), Layer::Bottom,
                Some("riceplate-desktop-widget"), None,
            );
            surface.set_anchor(Anchor::TOP | Anchor::LEFT);
            surface.set_size(recipe::DESKTOP_WIDGET_WIDTH, recipe::DESKTOP_WIDGET_HEIGHT);
            surface.set_margin(widget.y as i32, 0, 0, widget.x as i32);
            surface.set_exclusive_zone(-1);
            if matches!(&widget.kind, recipe::DesktopWidgetKind::Action(_)) {
                surface.set_keyboard_interactivity(KeyboardInteractivity::OnDemand);
            } else {
                surface.set_keyboard_interactivity(KeyboardInteractivity::None);
                surface.wl_surface().set_input_region(Some(empty_input.wl_region()));
            }
            surface.commit();
            widget_layers.push(DesktopWidgetLayer {
                recipe_index, surface, pool: None, configured: false,
                output: None, bound_output: None, placed: Some((widget.x, widget.y)),
            });
        }
    }

    // The native start menu shares the validated schema-v4/v5 recipe and the
    // same process as the panel. When closed it is parked beyond the output,
    // not destroyed (a null buffer would invalidate its layer-shell role).
    let menu_layer = recipe.menu.as_ref().map(|_| {
        let surface = layer_shell.create_layer_surface(
            &qh,
            compositor.create_surface(&qh),
            Layer::Top,
            Some("riceplate-native-menu"),
            None,
        );
        surface.set_anchor(
            (if recipe.top {
                Anchor::TOP
            } else {
                Anchor::BOTTOM
            }) | Anchor::LEFT,
        );
        surface.set_size(native_menu::WIDTH, native_menu::HEIGHT);
        surface.set_margin(
            if recipe.top { recipe.height as i32 } else { 0 },
            0,
            if recipe.top { 0 } else { recipe.height as i32 },
            MAX_WIDTH as i32,
        );
        surface.set_exclusive_zone(-1);
        surface.set_keyboard_interactivity(KeyboardInteractivity::None);
        surface.commit();
        MenuLayer { surface, pool: None, configured: false, output: None,
                    size: (native_menu::WIDTH, native_menu::HEIGHT) }
    });
    let preview_secondary_menu = preview_menu
        && std::env::var("RICEBOWL_DE_NESTED").as_deref() == Ok("1")
        && std::env::var("RICEBOWL_DE_MENU_OUTPUT").as_deref() == Ok("secondary");

    // One owner-private calendar popup, idle and parked until the clock is used.
    let calendar_layer = clock_present.then(|| {
        let surface = layer_shell.create_layer_surface(
            &qh, compositor.create_surface(&qh), Layer::Top,
            Some("riceplate-native-calendar"), None,
        );
        surface.set_anchor((if recipe.top { Anchor::TOP } else { Anchor::BOTTOM }) | Anchor::RIGHT);
        surface.set_size(calendar::WIDTH, calendar::HEIGHT);
        surface.set_margin(
            if recipe.top { recipe.height as i32 } else { 0 },
            MAX_WIDTH as i32, // Park beyond the visible output while closed.
            if recipe.top { 0 } else { recipe.height as i32 },
            0,
        );
        surface.set_exclusive_zone(-1);
        surface.set_keyboard_interactivity(KeyboardInteractivity::None);
        surface.commit();
        CalendarLayer { surface, pool: None, configured: false, output: None }
    });
    // A single lazily painted Overlay surface belongs to RicePlate itself.
    // An EMPTY wl_region is essential: unlike a notification, an OSD must not
    // steal pointer/touch input from the window underneath it.
    let osd_layer = poll_audio.then(|| -> Result<OsdLayer, Box<dyn Error>> {
        let surface = layer_shell.create_layer_surface(
            &qh, compositor.create_surface(&qh), Layer::Overlay,
            Some("ricepop-audio-osd"), None,
        );
        surface.set_anchor(Anchor::TOP | Anchor::RIGHT);
        surface.set_size(osd::WIDTH, osd::HEIGHT);
        surface.set_margin(osd_top_margin(&recipe), MAX_WIDTH as i32, 0, 0);
        surface.set_exclusive_zone(-1);
        surface.set_keyboard_interactivity(KeyboardInteractivity::None);
        let empty_input = Region::new(&compositor)?;
        surface.wl_surface().set_input_region(Some(empty_input.wl_region()));
        surface.commit();
        Ok(OsdLayer { surface, pool: None, configured: false })
    }).transpose()?;
    let preview_secondary_calendar = preview_calendar
        && std::env::var("RICEBOWL_DE_NESTED").as_deref() == Ok("1")
        && std::env::var("RICEBOWL_DE_CALENDAR_OUTPUT").as_deref() == Ok("secondary");

    let tray_popup_layer = use_tray.then(|| {
        let surface = layer_shell.create_layer_surface(
            &qh, compositor.create_surface(&qh), Layer::Top,
            Some("riceplate-native-tray-overflow"), None,
        );
        surface.set_anchor((if recipe.top { Anchor::TOP } else { Anchor::BOTTOM }) | Anchor::RIGHT);
        surface.set_size(tray::POPUP_WIDTH, tray::POPUP_HEIGHT);
        surface.set_margin(
            if recipe.top { recipe.height as i32 + 8 } else { 0 },
            MAX_WIDTH as i32,
            if recipe.top { 0 } else { recipe.height as i32 + 8 }, 0,
        );
        surface.set_exclusive_zone(-1);
        surface.set_keyboard_interactivity(KeyboardInteractivity::None);
        surface.commit();
        TrayPopupLayer { surface, pool: None, configured: false, output: None }
    });

    // A real StatusNotifier host/watcher is only connected when a native
    // recipe requests a tray; Waybar continues owning its own fallback tray.
    let tray_host = if use_tray {
        match status_notifier::Host::new() {
            Ok(host) => Some(host),
            Err(error) => {
                eprintln!("RicePlate: native SNI tray unavailable: {error}");
                None
            }
        }
    } else { None };
    let tray_fd = tray_host.as_ref().and_then(|host| {
        host.as_fd().try_clone_to_owned().map_err(|error| {
            eprintln!("RicePlate: cannot observe SNI connection: {error}");
        }).ok()
    });

    let static_icon_count = recipe.desktop_icons.len();
    let mut app = RicePlate {
        compositor,
        layer_shell,
        xdg_shell,
        registry: RegistryState::new(&globals),
        outputs: OutputState::new(&globals, &qh),
        seats: SeatState::new(&globals, &qh),
        shm,
        layer,
        mirrors: Vec::new(),
        icon_layers,
        widget_layers,
        menu_layer,
        menu_mirrors: Vec::new(),
        active_menu: None,
        preview_secondary_menu,
        calendar_layer,
        osd_layer,
        osd_state: osd::State::default(),
        audio_watcher: None,
        calendar_mirrors: Vec::new(),
        active_calendar: None,
        preview_secondary_calendar,
        menu_state: MenuState::with_pins_and_recents(saved_menu_pins, saved_menu_recents),
        notification_state: NotificationState::default(),
        notification_sender: None,
        calendar_state: CalendarState::new(Local::now().date_naive()),
        calendar_focused: false,
        recipe,
        clock: clock_now(clock_format),
        power: PowerStatus::current(),
        system_status: SystemStatus::default(),
        control_pending: None,
        control_result: None,
        tray_host,
        tray_state: tray::State::default(),
        tray_popup_layer,
        tray_popup_mirrors: Vec::new(),
        active_tray_popup: None,
        tray_popup_state: tray::Popup::default(),
        tray_menu_state: tray::MenuPopup::default(),
        tray_popup_focused: false,
        control_sender: None,
        pointer: None,
        pointer_seat: None,
        keyboard: None,
        keyboard_seat: None,
        focused_icon: None,
        keyboard_icon_surface: None,
        desktop_selection: desktop_selection::Selection::default(),
        desktop_files: None,
        static_icon_count,
        desktop_type_select: desktop_selection::TypeSelect::default(),
        selection_modifiers: Modifiers::default(),
        desktop_context: None,
        context_generation: 0,
        context_focused: false,
        luna_dialog: None,
        luna_dialog_focused: false,
        focused_widget: None,
        keyboard_widget_surface: None,
        pressed_widget: None,
        hovered_widget: None,
        focused_panel: None,
        focused_target: None,
        hovered_panel: None,
        pressed_panel: None,
        icon_drag: None,
        icon_position_dirty: false,
        icon_outputs,
        menu_focused: false,
        primary_seat: None,
        primary_output: None,
        primary_output_seen: false,
        toplevel_manager,
        trace_window_events: std::env::var("RICEBOWL_DE_TRACE_WINDOWS").as_deref() == Ok("1"),
        trace_frames: std::env::var("RICEBOWL_DE_TRACE_FRAMES").as_deref() == Ok("1"),
        tasks: Vec::new(),
        show_desktop_restore: Vec::new(),
        luna_options,
        panel_collapsed: initial_panel_collapsed,
        panel_pointer_inside: false,
        task_offset: 0,
        // Refreshed when real task state is painted, not on mouse motion.
        cached_task_group_count: 0,
        pool: None,
        width: 0,
        height: 0,
        configured: false,
        closed: false,
        frame: FrameGate::default(),
        accessibility: None,
    };
    // User-file scan only in opt-in Luna, never in isolated design previews.
    if app.recipe.id == "xp-luna-columns"
        && std::env::var("RICEBOWL_DE_NESTED").as_deref() != Ok("1") {
        match desktop_files::Model::open() {
            Ok(model) => {
                app.desktop_files = Some(model);
                app.rebuild_desktop_file_icons(&qh);
            }
            Err(error) => eprintln!("RicePlate: Desktop directory unavailable: {error}"),
        }
    }
    // Only a real standalone Luna session owns the root-menu command socket.
    // Never let nested design previews steal an active user's socket.
    let desktop_listener = if app.recipe.id == "xp-luna-columns"
        && std::env::var("RICEBOWL_DE_NESTED").as_deref() != Ok("1") {
        match luna_desktop_ipc::bind() {
            Ok(listener) => Some(listener),
            Err(error) => {
                eprintln!("RicePlate: desktop context commands unavailable: {error}");
                None
            }
        }
    } else { None };
    if let Some(listener) = desktop_listener.as_ref() {
        let registered = listener.try_clone()?;
        let reader = listener.try_clone()?;
        let desktop_qh = qh.clone();
        event_loop.handle().insert_source(
            Generic::new(registered, Interest::READ, Mode::Level),
            move |_, _, app: &mut RicePlate| {
                loop {
                    match luna_desktop_ipc::receive(&reader) {
                        Ok(Some(request)) => app.handle_luna_desktop_request(request, &desktop_qh),
                        Ok(None) => break,
                        Err(error) => {
                            eprintln!("RicePlate: desktop context IPC closed: {error}");
                            return Ok(PostAction::Remove);
                        }
                    }
                }
                Ok(PostAction::Continue)
            },
        )?;
    }
    app.notification_state.configure_glyph_scale(
        if app.recipe.native_art.as_ref().and_then(|art| art.font.as_ref()).is_some() {
            app.recipe.font_scale
        } else { 1 });
    if preview_menu && !preview_secondary_menu { app.set_menu_visible(true, &qh); }
    if preview_notifications || preview_notification_detail || preview_notifications_scroll {
        // Real labwc/RicePlate surface with a fixed sample, entirely offline:
        // screenshots must not depend on or mutate the runner's Mako history.
        app.set_menu_visible(true, &qh);
        let sample = ricepop::Notice {
                id: 1, summary: "A message from RicePop".into(),
                app_name: "RiceBowl".into(),
                body: "Portable fonts are now shared by the native notification center, with readable wrapping and paging.".into(),
                urgency: "normal".into(),
                actions: vec![ricepop::Action { key: "open".into(), label: "Open message".into() }],
            };
        app.notification_state.show_preview(ricepop::Snapshot {
            active: if preview_notifications_scroll {
                // Visually distinct across pages: the framebuffer check must
                // detect actual changed rows, not just a trailing ID digit.
                [
                    ("New message from Alex", "Messages"),
                    ("Calendar meeting reminder", "Calendar"),
                    ("Download completed", "RiceField"),
                    ("System temperature warning", "Taskotto"),
                    ("Backup completed successfully", "Satella"),
                    ("Bluetooth headphones paired", "RiceSpice"),
                    ("Updates ready to install", "RiceBowl"),
                ].into_iter().enumerate().map(|(index, (summary, app_name))| ricepop::Notice {
                    id: index as u32 + 1, summary: summary.into(), app_name: app_name.into(),
                    ..sample.clone()
                }).collect()
            } else { vec![sample] },
            history: Vec::new(),
        });
        if preview_notification_detail { app.notification_state.open_detail(0); }
        app.redraw_menu(&qh);
    }
    if preview_calendar && !preview_secondary_calendar {
        app.set_calendar_visible(true, &qh);
    }
    if preview_osd {
        // Deterministic, read-only native compositor proof. A production OSD
        // still comes exclusively from verified audio/brightness events; the
        // preview bypasses the 1.8s expiry only so CI can capture it reliably.
        app.osd_state.current = Some(osd::Notice {
            title: "Volume", value: "68%".into(), fill: Some(68),
        });
        app.redraw_osd();
    }
    // Keep the native AT-SPI bridge entirely opt-in: the normal lightweight
    // panel never starts an accessibility D-Bus client or background executor.
    if std::env::var("RICEBOWL_DE_SCREEN_READER").as_deref() == Ok("1")
        && std::env::var("RICEBOWL_DE_NESTED").as_deref() != Ok("1") {
        let (sender, receiver) = channel::channel::<ActionRequest>();
        app.accessibility = Some(accessibility::Bridge::new(app.accessibility_model(),
            move |request| { let _ = sender.send(request); }));
        let action_qh = qh.clone();
        event_loop.handle().insert_source(receiver, move |event, _, app: &mut RicePlate| {
            if let channel::Event::Msg(request) = event {
                app.handle_accessibility_action(&request, &action_qh);
            }
        })?;
    }
    if let Some(fd) = tray_fd {
        let redraw_qh = qh.clone();
        event_loop.handle().insert_source(
            Generic::new(fd, Interest::READ, Mode::Level),
            move |_, _, app: &mut RicePlate| {
                Ok(if app.refresh_tray(&redraw_qh) {
                    PostAction::Continue
                } else { PostAction::Remove })
            },
        )?;
        app.refresh_tray(&qh);
    }
    let mut audio_observer_sender = None;
    let mut audio_reconnect_after = Instant::now() + Duration::from_secs(5);
    let mut backlight = if full_session { brightness::Watcher::detect() } else { None };
    let mut next_backlight_check = Instant::now() + Duration::from_millis(800);
    let mut next_desktop_scan = Instant::now() + Duration::from_secs(4);
    if poll_network || poll_audio {
        let (sender, receiver) = channel::channel::<StatusEvent>();
        // Zero-capacity rendezvous: repeated clicks cannot queue a burst of
        // Wi-Fi toggles while the hardware service is slow or unavailable.
        let (control_sender, controls) = mpsc::sync_channel::<ControlAction>(0);
        app.control_sender = Some(control_sender);
        let redraw_qh = qh.clone();
        event_loop.handle().insert_source(receiver, move |event, _, app: &mut RicePlate| {
            if let channel::Event::Msg(message) = event {
                let status = match message {
                    StatusEvent::State(status) => status,
                    StatusEvent::ObservedAudio(audio) => {
                        if app.osd_state.show_external(&app.system_status.audio, &audio,
                                                       Instant::now()) {
                            app.redraw_osd();
                        }
                        let mut updated = app.system_status.clone();
                        updated.audio = audio;
                        updated
                    }
                    StatusEvent::Control { action, success, state } => {
                        app.control_pending = None;
                        app.control_result = Some((action, success));
                        app.menu_state.notice = Some(if success {
                            "Action applied"
                        } else { "Unavailable or denied" });
                        if app.menu_state.visible { app.redraw_menu(&redraw_qh); }
                        if app.osd_state.show(action, success, &state, Instant::now()) {
                            app.redraw_osd();
                        }
                        app.request_redraw(&redraw_qh);
                        app.redraw_widgets();
                        state
                    }
                };
                if app.system_status != status {
                    app.system_status = status;
                    app.request_redraw(&redraw_qh);
                    app.redraw_widgets();
                }
            }
        })?;
        if poll_audio && full_session {
            audio_observer_sender = Some(sender.clone());
            let observed = sender.clone();
            app.audio_watcher = system_status::AudioWatcher::start(move |audio| {
                observed.send(StatusEvent::ObservedAudio(audio)).is_ok()
            });
            if app.audio_watcher.is_none() {
                eprintln!("RicePop: pactl subscribe unavailable; external volume OSD disabled");
            }
        }
        // One sleeping worker, enabled only for rices using these widgets;
        // bounded subprocesses never block Wayland input or the frame loop.
        std::thread::spawn(move || {
            if sender.send(StatusEvent::State(SystemStatus::read(poll_network, poll_audio))).is_err() {
                return;
            }
            loop {
                match controls.recv_timeout(Duration::from_secs(30)) {
                    Ok(action) => {
                        let before = SystemStatus::read(poll_network, poll_audio);
                        let applied = action.available(&before) && action.apply();
                        let state = SystemStatus::read(poll_network, poll_audio);
                        let success = action.verified(&before, &state, applied);
                        if sender.send(StatusEvent::Control { action, success, state }).is_err() { break; }
                    }
                    Err(mpsc::RecvTimeoutError::Timeout) => {
                        if sender.send(StatusEvent::State(SystemStatus::read(poll_network, poll_audio)))
                            .is_err() { break; }
                    }
                    Err(mpsc::RecvTimeoutError::Disconnected) => break,
                }
            }
        });
    }
    if has_notifications {
        let (sender, receiver) = channel::channel::<(u64, Result<ricepop::Snapshot, &'static str>)>();
        let (request_sender, requests) = mpsc::sync_channel::<NotificationRequest>(1);
        app.notification_sender = Some(request_sender);
        let redraw_qh = qh.clone();
        event_loop.handle().insert_source(receiver, move |event, _, app: &mut RicePlate| {
            if let channel::Event::Msg((revision, result)) = event {
                if app.notification_state.update(revision, result) {
                    app.redraw_menu(&redraw_qh);
                }
            }
        })?;
        // Only starts for a recipe with the native RicePop action. Sleeps on
        // requests; no background Mako polling or second notification owner.
        std::thread::spawn(move || {
            while let Ok(request) = requests.recv() {
                let revision = request.revision();
                if sender.send((revision, ricepop::run(&request))).is_err() { break; }
            }
        });
    }
    while !app.closed {
        // Calloop sleeps on Wayland's fd and wakes at the next minute,
        // so the clock updates without any resident 1 Hz poll/frame loop.
        // RicePop's short refresh interval exists *only while its UI is open*.
        let osd_timeout = app.osd_state.timeout(Instant::now());
        let reconnect_timeout = (poll_audio && full_session).then(||
            audio_reconnect_after.saturating_duration_since(Instant::now()));
        let backlight_timeout = backlight.as_ref().map(|_| next_backlight_check
            .saturating_duration_since(Instant::now()));
        let timeout = [Some(next_clock_timeout()), osd_timeout, reconnect_timeout, backlight_timeout,
                       app.notification_state.refresh_timeout(Instant::now()),
                       app.desktop_files.as_ref().map(|_| next_desktop_scan.saturating_duration_since(Instant::now()))]
            .into_iter().flatten().min().unwrap_or_else(next_clock_timeout);
        event_loop.dispatch(Some(timeout), &mut app)?;
        if app.desktop_files.is_some() && Instant::now() >= next_desktop_scan {
            app.refresh_desktop_files(&qh);
            next_desktop_scan = Instant::now() + Duration::from_secs(4);
        }
        if backlight.is_some() && Instant::now() >= next_backlight_check {
            if let Some(percent) = backlight.as_mut().and_then(brightness::Watcher::changed) {
                app.osd_state.show_brightness(percent, Instant::now());
                app.redraw_osd();
            }
            next_backlight_check = Instant::now() + Duration::from_millis(800);
        }
        if poll_audio && full_session && Instant::now() >= audio_reconnect_after {
            if !app.audio_watcher.as_mut().is_some_and(system_status::AudioWatcher::running) {
                app.audio_watcher.take();
                if let Some(sender) = audio_observer_sender.as_ref() {
                    let observed = sender.clone();
                    app.audio_watcher = system_status::AudioWatcher::start(move |audio| {
                        observed.send(StatusEvent::ObservedAudio(audio)).is_ok()
                    });
                }
                if app.audio_watcher.is_some() {
                    eprintln!("RicePop: volume observer reconnected");
                }
            }
            // No process spawning on every compositor frame, even when audio
            // has gone away. A silent 5s liveness check is sufficient.
            audio_reconnect_after = Instant::now() + Duration::from_secs(5);
        }
        if let Some(revision) = app.notification_state.begin_background(Instant::now()) {
            let queued = app.notification_sender.as_ref().is_some_and(|sender|
                sender.try_send(NotificationRequest::Refresh(revision)).is_ok());
            if !queued {
                app.notification_state.update(revision, Err("RicePop worker busy"));
            }
        }
        if app.accessibility.is_some() {
            let model = app.accessibility_model();
            if let Some(bridge) = app.accessibility.as_mut() {
                bridge.sync(model);
            }
        }
        if app.osd_state.expire(Instant::now()) { app.hide_osd(); }
        let current = clock_now(clock_format);
        if app.clock != current {
            app.clock = current;
            // The fixed sysfs power supply is read at most once per minute,
            // never on every pointer/frame event or from a resident helper.
            app.power = PowerStatus::current();
            app.request_redraw(&qh);
            app.redraw_widgets();
        }
        let today = Local::now().date_naive();
        if app.calendar_state.today != today {
            app.calendar_state.today = today;
            if app.calendar_state.visible { app.redraw_calendar(&qh); }
        }
    }
    app.save_icon_positions();
    Ok(())
}

struct Task {
    handle: ZwlrForeignToplevelHandleV1,
    title: String,
    app_id: String,
    active: bool,
    minimized: bool,
    ready: bool,
}

struct IconLayer {
    recipe_index: usize,
    surface: LayerSurface,
    pool: Option<SlotPool>,
    configured: bool,
    output: Option<wl_output::WlOutput>,
    bound_output: Option<wl_output::WlOutput>,
    placed: Option<(u32, u32)>,
}

struct DesktopWidgetLayer {
    recipe_index: usize,
    surface: LayerSurface,
    pool: Option<SlotPool>,
    configured: bool,
    output: Option<wl_output::WlOutput>,
    bound_output: Option<wl_output::WlOutput>,
    placed: Option<(u32, u32)>,
}

struct IconDrag {
    index: usize,
    anchor: (f64, f64),
    started: (u32, u32),
    moved: bool,
    original_positions: icon_positions::OutputPositions,
}

struct LunaDialogLayer {
    surface: LayerSurface,
    pool: Option<SlotPool>,
    configured: bool,
    state: luna_dialog::State,
}

struct DesktopContextLayer {
    popup: Popup,
    parent_surface: wl_surface::WlSurface,
    grab_seat: wl_seat::WlSeat,
    pool: Option<SlotPool>,
    configured: bool,
    icon_index: usize,
    selected: DesktopContextAction,
    hovered: Option<DesktopContextAction>,
    pressed: Option<DesktopContextAction>,
    can_move: bool,
    can_reset: bool,
    properties: bool,
    back_hovered: bool,
    back_pressed: bool,
    file_operation: Option<desktop_context::FileOperation>,
}

struct MenuLayer {
    surface: LayerSurface,
    pool: Option<SlotPool>,
    configured: bool,
    output: Option<wl_output::WlOutput>,
    size: (u32, u32),
}

struct CalendarLayer {
    surface: LayerSurface,
    pool: Option<SlotPool>,
    configured: bool,
    output: Option<wl_output::WlOutput>,
}

struct OsdLayer {
    surface: LayerSurface,
    pool: Option<SlotPool>,
    configured: bool,
}

struct TrayPopupLayer {
    surface: LayerSurface,
    pool: Option<SlotPool>,
    configured: bool,
    output: Option<wl_output::WlOutput>,
}

fn osd_top_margin(recipe: &PanelStyle) -> i32 {
    if recipe.top { recipe.height as i32 + 16 } else { 16 }
}

struct PanelMirror {
    output: wl_output::WlOutput,
    surface: LayerSurface,
    pool: Option<SlotPool>,
    width: u32,
    height: u32,
    configured: bool,
    frame: FrameGate,
    task_offset: usize,
}

struct RicePlate {
    compositor: CompositorState,
    layer_shell: LayerShell,
    xdg_shell: Option<XdgShell>,
    registry: RegistryState,
    outputs: OutputState,
    seats: SeatState,
    shm: Shm,
    layer: LayerSurface,
    mirrors: Vec<PanelMirror>,
    icon_layers: Vec<IconLayer>,
    widget_layers: Vec<DesktopWidgetLayer>,
    menu_layer: Option<MenuLayer>,
    menu_mirrors: Vec<MenuLayer>,
    active_menu: Option<wl_surface::WlSurface>,
    preview_secondary_menu: bool,
    calendar_layer: Option<CalendarLayer>,
    osd_layer: Option<OsdLayer>,
    osd_state: osd::State,
    audio_watcher: Option<system_status::AudioWatcher>,
    calendar_mirrors: Vec<CalendarLayer>,
    active_calendar: Option<wl_surface::WlSurface>,
    preview_secondary_calendar: bool,
    menu_state: MenuState,
    notification_state: NotificationState,
    notification_sender: Option<mpsc::SyncSender<NotificationRequest>>,
    calendar_state: CalendarState,
    calendar_focused: bool,
    recipe: PanelStyle,
    clock: String,
    power: PowerStatus,
    system_status: SystemStatus,
    control_pending: Option<ControlAction>,
    control_result: Option<(ControlAction, bool)>,
    tray_host: Option<status_notifier::Host>,
    tray_state: tray::State,
    tray_popup_layer: Option<TrayPopupLayer>,
    tray_popup_mirrors: Vec<TrayPopupLayer>,
    active_tray_popup: Option<wl_surface::WlSurface>,
    tray_popup_state: tray::Popup,
    tray_menu_state: tray::MenuPopup,
    tray_popup_focused: bool,
    control_sender: Option<mpsc::SyncSender<ControlAction>>,
    pointer: Option<wl_pointer::WlPointer>,
    pointer_seat: Option<wl_seat::WlSeat>,
    keyboard: Option<wl_keyboard::WlKeyboard>,
    keyboard_seat: Option<wl_seat::WlSeat>,
    focused_icon: Option<usize>,
    keyboard_icon_surface: Option<wl_surface::WlSurface>,
    desktop_selection: desktop_selection::Selection,
    desktop_files: Option<desktop_files::Model>,
    static_icon_count: usize,
    desktop_type_select: desktop_selection::TypeSelect,
    selection_modifiers: Modifiers,
    desktop_context: Option<DesktopContextLayer>,
    // Invalidates pending AT-SPI actions when menus reopen or change views.
    context_generation: u64,
    context_focused: bool,
    luna_dialog: Option<LunaDialogLayer>,
    luna_dialog_focused: bool,
    focused_widget: Option<usize>,
    keyboard_widget_surface: Option<wl_surface::WlSurface>,
    pressed_widget: Option<usize>,
    hovered_widget: Option<usize>,
    focused_panel: Option<wl_surface::WlSurface>,
    focused_target: Option<KeyboardTarget>,
    // The only interactive taskbar cosmetics, scoped to the originating
    // layer surface so moving between outputs cannot leak hover highlights.
    hovered_panel: Option<(wl_surface::WlSurface, Hit)>,
    pressed_panel: Option<(wl_surface::WlSurface, Hit)>,
    icon_drag: Option<IconDrag>,
    icon_position_dirty: bool,
    icon_outputs: icon_positions::OutputPositions,
    menu_focused: bool,
    primary_seat: Option<wl_seat::WlSeat>,
    primary_output: Option<wl_output::WlOutput>,
    primary_output_seen: bool,
    toplevel_manager: Option<ZwlrForeignToplevelManagerV1>,
    trace_window_events: bool,
    trace_frames: bool,
    tasks: Vec<Task>,
    // Only windows actually minimized by Show Desktop are restored.
    show_desktop_restore: Vec<ZwlrForeignToplevelHandleV1>,
    luna_options: luna_taskbar::Options,
    panel_collapsed: bool,
    // Actual compositor pointer focus, not a timer or guessed screen coordinates.
    panel_pointer_inside: bool,
    task_offset: usize,
    cached_task_group_count: usize,
    pool: Option<SlotPool>,
    width: u32,
    height: u32,
    configured: bool,
    closed: bool,
    frame: FrameGate,
    accessibility: Option<accessibility::Bridge>,
}

impl RicePlate {
    fn maybe_collapse_luna_panel(&mut self, qh: &QueueHandle<Self>) {
        let popup_open = self.menu_state.visible || self.calendar_state.visible
            || self.tray_popup_open() || self.luna_dialog.is_some()
            || self.desktop_context.is_some();
        if std::env::var_os("RICEBOWL_DE_TRACE_MENU").is_some()
            && self.recipe.id == "xp-luna-columns" {
            eprintln!("RicePlate: Luna auto-hide pointer_inside={} popup_open={} collapsed={}",
                      self.panel_pointer_inside, popup_open, self.panel_collapsed);
        }
        if luna_taskbar::should_collapse(
            self.luna_options, self.panel_pointer_inside, popup_open)
        {
            self.set_panel_collapsed(true, qh);
        }
    }

    /// Set the same panel geometry across all active outputs. The compositor
    /// owns window work-area reflow; only the 3px reveal handle remains when
    /// Luna auto-hide is enabled. Hidden canvases never paint interactive rows.
    fn set_panel_collapsed(&mut self, collapsed: bool, qh: &QueueHandle<Self>) {
        if !self.luna_options.auto_hide || self.panel_collapsed == collapsed {
            return;
        }
        self.panel_collapsed = collapsed;
        let height = luna_taskbar::panel_height(
            self.luna_options, collapsed, self.recipe.height);
        self.configured = false;
        self.layer.set_size(0, height);
        self.layer.set_exclusive_zone(height as i32);
        self.layer.commit();
        for mirror in &mut self.mirrors {
            mirror.configured = false;
            mirror.surface.set_size(0, height);
            mirror.surface.set_exclusive_zone(height as i32);
            mirror.surface.commit();
        }
        self.request_redraw(qh);
    }

    /// User file layers are separate runtime state; never rewrite a recipe.
    fn rebuild_desktop_file_icons(&mut self, qh: &QueueHandle<Self>) {
        let Some(files) = self.desktop_files.as_ref() else { return };
        let entries: Vec<_> = files.entries().iter().enumerate().map(|(index, entry)| {
            let slot = index + self.static_icon_count;
            recipe::DesktopIcon {
                label: entry.label(), action: format!("desktop-file:{index}"),
                x: 24 + ((slot / 5) as u32 * 112),
                y: 88 + ((slot % 5) as u32 * 104),
            }
        }).collect();
        self.close_desktop_context();
        self.desktop_selection.clear();
        self.desktop_type_select.reset();
        self.icon_drag = None;
        self.focused_icon = None;
        self.keyboard_icon_surface = None;
        self.icon_layers.retain(|layer| layer.recipe_index < self.static_icon_count);
        self.recipe.desktop_icons.truncate(self.static_icon_count);
        self.recipe.desktop_icons.extend(entries);
        for index in self.static_icon_count..self.recipe.desktop_icons.len() {
            let icon = &self.recipe.desktop_icons[index];
            let surface = self.layer_shell.create_layer_surface(
                qh, self.compositor.create_surface(qh), Layer::Bottom,
                Some("riceplate-desktop-file"), None,
            );
            surface.set_anchor(Anchor::TOP | Anchor::LEFT);
            surface.set_size(recipe::ICON_WIDTH, recipe::ICON_HEIGHT);
            surface.set_margin(icon.y as i32, 0, 0, icon.x as i32);
            surface.set_exclusive_zone(-1);
            surface.set_keyboard_interactivity(KeyboardInteractivity::OnDemand);
            surface.commit();
            self.icon_layers.push(IconLayer {
                recipe_index: index, surface, pool: None, configured: false,
                output: None, bound_output: None, placed: Some((icon.x, icon.y)),
            });
        }
        if self.primary_output_seen { self.sync_mirrors(qh); }
        self.reflow_icons();
        eprintln!("RicePlate: XDG Desktop shows {} bounded file entries",
            self.recipe.desktop_icons.len() - self.static_icon_count);
    }

    fn refresh_desktop_files(&mut self, qh: &QueueHandle<Self>) {
        let Some(files) = self.desktop_files.as_mut() else { return };
        match files.refresh() {
            Ok(true) => self.rebuild_desktop_file_icons(qh),
            Ok(false) => (),
            Err(error) => eprintln!("RicePlate: Desktop refresh retained old icons: {error}"),
        }
    }

    fn open_desktop_file(&self, index: usize) {
        let Some(files) = self.desktop_files.as_ref() else { return };
        let mut command = match files.open_command(index, true) {
            Ok(command) => command,
            Err(error) => {
                eprintln!("RicePlate: Desktop file unavailable: {error}");
                return;
            }
        };
        match command.spawn() {
            Ok(_) => (),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound
                && command.get_program() == "ricefield" => {
                match files.gio_open_command(index).and_then(|mut cmd| cmd.spawn().map(|_| ())) {
                    Ok(()) => (),
                    Err(error) => eprintln!("RicePlate: Gio fallback failed: {error}"),
                }
            }
            Err(error) => eprintln!("RicePlate: Desktop open failed: {error}"),
        }
    }

    /// A real compositor-owned XDG popup provides the focus and the explicit
    /// user decision. No invisible input surface or arbitrary shell commands.
    fn begin_file_rename(&mut self) {
        let Some(menu) = self.desktop_context.as_ref() else { return };
        let Some(recipe_index) = self.icon_layers.get(menu.icon_index).map(|icon| icon.recipe_index)
            else { return };
        let Some(file_index) = recipe_index.checked_sub(self.static_icon_count) else { return };
        let Some(current) = self.desktop_files.as_ref()
            .and_then(|files| files.entry(file_index))
            .and_then(|entry| entry.name.to_str()) else {
            eprintln!("RicePlate: cannot edit an invalid UTF-8 file name in this popup");
            return;
        };
        let Some(input) = desktop_context::RenameInput::new(current) else { return };
        if let Some(menu) = self.desktop_context.as_mut() {
            menu.file_operation = Some(desktop_context::FileOperation::Rename(input));
            menu.properties = false;
        }
        self.redraw_desktop_context();
    }

    fn begin_file_trash(&mut self) {
        let Some(menu) = self.desktop_context.as_ref() else { return };
        if self.icon_layers.get(menu.icon_index)
            .is_none_or(|icon| icon.recipe_index < self.static_icon_count) { return; }
        if let Some(menu) = self.desktop_context.as_mut() {
            menu.file_operation = Some(desktop_context::FileOperation::ConfirmTrash);
            menu.properties = false;
        }
        self.redraw_desktop_context();
    }

    fn commit_file_rename(&mut self, qh: &QueueHandle<Self>) {
        let Some(menu) = self.desktop_context.as_ref() else { return };
        let Some(file_index) = self.icon_layers.get(menu.icon_index)
            .and_then(|icon| icon.recipe_index.checked_sub(self.static_icon_count)) else { return };
        let Some(desktop_context::FileOperation::Rename(input)) = menu.file_operation.as_ref()
            else { return };
        if !input.valid() { return; }
        let proposed = input.value().to_owned();
        let result = self.desktop_files.as_mut().map(|files|
            files.rename(file_index, std::ffi::OsStr::new(&proposed)));
        match result {
            Some(Ok(_)) => {
                self.close_desktop_context();
                self.rebuild_desktop_file_icons(qh);
            }
            Some(Err(error)) => {
                let message = match error.kind() {
                    std::io::ErrorKind::AlreadyExists => "Name already exists",
                    std::io::ErrorKind::PermissionDenied => "Permission denied",
                    std::io::ErrorKind::NotFound => "File disappeared",
                    _ => "Rename failed",
                };
                eprintln!("RicePlate: Desktop rename failed: {error}");
                if let Some(desktop_context::FileOperation::Rename(input)) =
                    self.desktop_context.as_mut().and_then(|menu| menu.file_operation.as_mut()) {
                    input.set_error(message);
                }
                self.redraw_desktop_context();
            }
            None => (),
        }
    }

    fn confirm_file_trash(&mut self, qh: &QueueHandle<Self>) {
        let Some(menu) = self.desktop_context.as_ref() else { return };
        let Some(file_index) = self.icon_layers.get(menu.icon_index)
            .and_then(|icon| icon.recipe_index.checked_sub(self.static_icon_count)) else { return };
        let command = self.desktop_files.as_ref().map(|files| files.trash_command(file_index));
        self.close_desktop_context();
        match command {
            Some(Ok(mut cmd)) => match cmd.spawn() {
                Ok(_) => {
                    // Gio reports completion asynchronously; the bounded
                    // directory scan confirms the actual disappearance.
                    eprintln!("RicePlate: requested Gio Trash move for Desktop file");
                    self.refresh_desktop_files(qh);
                }
                Err(error) => eprintln!("RicePlate: cannot request Gio Trash: {error}"),
            },
            Some(Err(error)) => eprintln!("RicePlate: unsafe Trash request rejected: {error}"),
            None => (),
        }
    }

    fn show_file_in_explorer(&self, file_index: usize) {
        let Some(files) = self.desktop_files.as_ref() else { return };
        let mut command = match files.explorer_command(file_index) {
            Ok(command) => command,
            Err(error) => {
                eprintln!("RicePlate: cannot open file location: {error}");
                return;
            }
        };
        match command.spawn() {
            Ok(_) => (),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                if let Err(error) = files.gio_explorer_command(file_index)
                    .and_then(|mut cmd| cmd.spawn().map(|_| ())) {
                    eprintln!("RicePlate: Gio Explorer fallback unavailable: {error}");
                }
            }
            Err(error) => eprintln!("RicePlate: RiceField Explorer denied: {error}"),
        }
    }

    fn handle_luna_desktop_request(&mut self, request: luna_desktop_ipc::Request,
                                   qh: &QueueHandle<Self>) {
        if self.recipe.id != "xp-luna-columns" { return; }
        if std::env::var("RICEBOWL_DE_TRACE_SHORTCUTS").as_deref() == Ok("1") {
            eprintln!("RicePlate: Luna private IPC {request:?}");
        }
        use luna_desktop_ipc::Request;
        match request {
            Request::Arrange => {
                // Arrange only currently visible shortcuts on each output,
                // preserving the recipe's original order and other displays.
                let mut columns: std::collections::HashMap<Option<String>, usize> =
                    std::collections::HashMap::new();
                let snapshot: Vec<_> = self.icon_layers.iter().enumerate()
                    .filter_map(|(index, layer)| {
                        if layer.placed.is_none() { return None; }
                        let output = layer.bound_output.as_ref()
                            .or(self.primary_output.as_ref()).or(layer.output.as_ref())?;
                        Some((index, self.icon_output_name(index),
                              self.logical_output_size(output)?))
                    }).collect();
                for (index, monitor, (width, height)) in snapshot {
                    let position = columns.entry(monitor).or_default();
                    let rows = (height.saturating_sub(self.recipe.height + 88
                        + recipe::ICON_HEIGHT) / 104 + 1).max(1);
                    let cols = (width.saturating_sub(24 + recipe::ICON_WIDTH) / 112 + 1).max(1);
                    if *position < (rows as usize).saturating_mul(cols as usize) {
                        let x = 24 + (*position as u32 / rows) * 112;
                        let y = 88 + (*position as u32 % rows) * 104;
                        self.move_icon(index, (x, y));
                    }
                    *position += 1;
                }
                self.save_icon_positions();
            }
            Request::NewFolder => match luna_desktop_ipc::new_folder() {
                Ok(path) => {
                    eprintln!("RicePlate: Desktop folder created: {}", path.display());
                    self.refresh_desktop_files(qh);
                },
                Err(error) => eprintln!("RicePlate: cannot create Desktop folder: {error}"),
            },
            Request::Refresh => {
                self.refresh_desktop_files(qh);
                self.menu_state.refresh_apps();
                self.reflow_icons();
                for index in 0..self.icon_layers.len() { self.redraw_icon(index); }
                self.request_redraw(qh);
            }
            Request::Properties => self.launch_luna_settings("appearance"),
            // These three operations are the very same handlers as the real
            // Luna taskbar/menu buttons, never independent compositor state.
            Request::ShowDesktop => self.activate_action("show-desktop", qh),
            Request::Run => self.activate_action("run", qh),
            Request::Explorer => self.activate_action("computer", qh),
        }
    }

    fn luna_icon_peers(&self, index: usize) -> Vec<bool> {
        let Some(source) = self.icon_layers.get(index) else { return Vec::new() };
        // Restrict selection to visible icons on the same logical output.
        self.icon_layers.iter().map(|icon|
            icon.placed.is_some() && icon.bound_output == source.bound_output
        ).collect()
    }

    fn select_luna_icon_mode(&mut self, index: usize, mode: desktop_selection::Mode) {
        if self.recipe.id != "xp-luna-columns" { return; }
        let peers = self.luna_icon_peers(index);
        for changed in self.desktop_selection.choose(index, mode, &peers) {
            self.redraw_icon(changed);
        }
    }

    fn select_luna_icon(&mut self, index: usize) {
        self.select_luna_icon_mode(index, desktop_selection::Mode::Replace);
    }

    fn select_all_luna_icons(&mut self, index: usize) {
        if self.recipe.id != "xp-luna-columns" { return; }
        let peers = self.luna_icon_peers(index);
        for changed in self.desktop_selection.all_on_output(&peers, index) {
            self.redraw_icon(changed);
        }
    }

    fn clear_luna_selection(&mut self) {
        if self.recipe.id != "xp-luna-columns" { return; }
        for changed in self.desktop_selection.clear_all() { self.redraw_icon(changed); }
    }



    fn close_luna_dialog(&mut self) {
        // Drop the real overlay surface on dismissal; no transparent
        // fullscreen input grab, background worker or hidden popup survives.
        self.luna_dialog = None;
        self.luna_dialog_focused = false;
    }

    fn open_luna_dialog(&mut self, kind: luna_dialog::Kind,
                        qh: &QueueHandle<Self>) {
        // The opt-in themed two-column Start is the only source of these
        // actions; non-Luna and X11 profiles retain their original behavior.
        let menu_output = self.active_menu.as_ref().and_then(|surface|
            self.menu_layer.iter().chain(self.menu_mirrors.iter())
                .find(|menu| menu.surface.wl_surface() == surface)
                .and_then(|menu| menu.output.clone()));
        let output = menu_output.or_else(|| self.primary_output.clone())
            .or_else(|| self.outputs.outputs().next());
        let Some(output) = output else {
            self.menu_state.notice = Some("No monitor available");
            self.redraw_menu(qh);
            return;
        };
        let Some(size) = self.logical_output_size(&output) else {
            self.menu_state.notice = Some("Display unavailable");
            self.redraw_menu(qh);
            return;
        };
        let Some((x, y)) = luna_dialog::position(size, self.recipe.height, self.recipe.top) else {
            self.menu_state.notice = Some("Screen too small");
            self.redraw_menu(qh);
            return;
        };
        self.set_menu_visible(false, qh);
        self.close_desktop_context();
        self.close_luna_dialog();
        let surface = self.layer_shell.create_layer_surface(
            qh, self.compositor.create_surface(qh), Layer::Overlay,
            Some("riceplate-luna-run-help"), Some(&output),
        );
        surface.set_anchor(Anchor::TOP | Anchor::LEFT);
        surface.set_size(luna_dialog::WIDTH, luna_dialog::HEIGHT);
        surface.set_margin(y as i32, 0, 0, x as i32);
        surface.set_exclusive_zone(-1);
        // This is an explicit modal dialog; only while open may it own
        // keystrokes. The normal desktop and other rices remain untouched.
        surface.set_keyboard_interactivity(KeyboardInteractivity::Exclusive);
        surface.commit();
        self.luna_dialog = Some(LunaDialogLayer {
            surface, pool: None, configured: false,
            state: luna_dialog::State::new(kind),
        });
    }

    fn execute_luna_dialog(&mut self) {
        let Some(dialog) = self.luna_dialog.as_mut() else { return };
        if dialog.state.kind == luna_dialog::Kind::Help {
            self.close_luna_dialog();
            return;
        }
        let argv = match dialog.state.argv() {
            Ok(argv) => argv,
            Err(notice) => {
                dialog.state.notice = Some(notice);
                self.redraw_luna_dialog();
                return;
            }
        };
        // An explicit local user action, never recipe data. Pass literal argv
        // directly to execve via std::process::Command: no /bin/sh, pipes,
        // wildcard expansion, or potentially injected shell fragments.
        let program = &argv[0];
        match Command::new(program).args(argv.iter().skip(1)).spawn() {
            Ok(_) => self.close_luna_dialog(),
            Err(error) => {
                eprintln!("RicePlate: Run could not start the requested program: {error}");
                if let Some(dialog) = self.luna_dialog.as_mut() {
                    dialog.state.notice = Some("Program missing or denied");
                }
                self.redraw_luna_dialog();
            }
        }
    }

    fn redraw_luna_dialog(&mut self) {
        let Some(dialog) = self.luna_dialog.as_mut() else { return };
        if !dialog.configured { return; }
        let Some(pool) = dialog.pool.as_mut() else { return };
        let (buffer, canvas) = match pool.create_buffer(
            luna_dialog::WIDTH as i32, luna_dialog::HEIGHT as i32,
            (luna_dialog::WIDTH * 4) as i32, wl_shm::Format::Argb8888,
        ) {
            Ok(value) => value,
            Err(error) => {
                eprintln!("RicePlate: Luna dialog buffer unavailable: {error}");
                self.close_luna_dialog();
                return;
            }
        };
        paint_luna_dialog(canvas, &self.recipe, &dialog.state);
        let surface = dialog.surface.wl_surface();
        surface.damage_buffer(0, 0, luna_dialog::WIDTH as i32,
                             luna_dialog::HEIGHT as i32);
        if let Err(error) = buffer.attach_to(surface) {
            eprintln!("RicePlate: Luna dialog attach failed: {error}");
            self.close_luna_dialog();
            return;
        }
        dialog.surface.commit();
    }

    fn close_desktop_context(&mut self) {
        self.context_focused = false;
        self.desktop_type_select.reset();
        // The XDG popup belongs to the original Bottom-layer icon.
        // Never promote a layer permanently or grab keyboard globally.
        self.desktop_context = None;
    }

    fn open_desktop_context(&mut self, index: usize, pointer: (f64, f64),
                            grab: Option<(wl_seat::WlSeat, u32)>, qh: &QueueHandle<Self>) {
        if self.recipe.id != "xp-luna-columns" { return; }
        // An XDG popup grab must use the serial AND seat of its initiating
        // pointer/button or keyboard/key event, never an arbitrary seat.
        let Some((seat, serial)) = grab.filter(|(_, serial)| *serial != 0) else {
            return;
        };
        let Some(icon) = self.icon_layers.get(index) else { return; };
        let Some(position) = icon.placed else { return; };
        let Some(output) = icon.bound_output.as_ref()
            .or(self.primary_output.as_ref()).or(icon.output.as_ref()).cloned()
            else { return };
        let Some(size) = self.logical_output_size(&output) else { return };
        let Some((x, y)) = desktop_context::placement(
            position, pointer, size, self.recipe.height, self.recipe.top)
            else { return };
        let recipe_index = icon.recipe_index;
        let mut output_names: Vec<_> = self.icon_layers.iter()
            .filter(|layer| layer.recipe_index == recipe_index)
            .filter_map(|layer| {
                let output = layer.bound_output.as_ref()
                    .or(self.primary_output.as_ref()).or(layer.output.as_ref())?;
                self.logical_output_size(output)?;
                self.outputs.info(output)?.name
            }).collect();
        output_names.sort();
        output_names.dedup();
        let can_move = recipe_index >= self.static_icon_count || output_names.len() > 1;
        // Only named-output overrides can be reset safely. Never claim to
        // restore source coordinates from an already mutated global recipe.
        let can_reset = recipe_index >= self.static_icon_count
            || (self.icon_output_name(index).is_some_and(|name|
            self.icon_outputs.can_reset_position(
                &name, &self.recipe.desktop_icons[..self.static_icon_count], recipe_index)));        self.icon_drag = None;
        self.desktop_selection.cancel();
        self.select_luna_icon(index);
        if self.menu_state.visible { self.set_menu_visible(false, qh); }
        if self.calendar_state.visible { self.set_calendar_visible(false, qh); }
        if self.tray_popup_open() { self.set_tray_popup_visible(false, qh); }
        self.close_desktop_context();
        self.context_generation = self.context_generation.wrapping_add(1);
        let Some(xdg) = self.xdg_shell.as_ref() else {
            eprintln!("RicePlate: compositor has no XDG popup support");
            return;
        };
        // A genuine child popup receives keyboard focus even when the
        // Bottom-layer icon deliberately cannot claim it. The parent
        // icon is the lifetime/focus owner; no global keyboard grab exists.
        let positioner = match XdgPositioner::new(xdg) {
            Ok(positioner) => positioner,
            Err(error) => {
                eprintln!("RicePlate: cannot create context positioner: {error}");
                return;
            }
        };
        positioner.set_size(desktop_context::WIDTH as i32,
                            desktop_context::HEIGHT as i32);
        positioner.set_anchor_rect(0, 0, 1, 1);
        positioner.set_anchor(xdg_positioner::Anchor::TopLeft);
        positioner.set_gravity(xdg_positioner::Gravity::BottomRight);
        // desired output-local point -> original icon-local coordinates.
        // placement() already clamps against the panel and output bounds.
        positioner.set_offset(x as i32 - position.0 as i32,
                              y as i32 - position.1 as i32);
        let popup = match Popup::from_surface(None, &positioner, qh,
                                             self.compositor.create_surface(qh), xdg) {
            Ok(popup) => popup,
            Err(error) => {
                eprintln!("RicePlate: cannot create context popup: {error}");
                return;
            }
        };
        // The role stays parented to the real Bottom-layer shortcut.
        // labwc 0.7.1 does not grant it keyboard focus (CI blocker);
        // do not silently promote it or request Exclusive keyboard access.
        self.icon_layers[index].surface.get_popup(popup.xdg_popup());
        popup.xdg_popup().grab(&seat, serial);
        popup.wl_surface().commit();
        self.desktop_context = Some(DesktopContextLayer {
            popup, parent_surface: self.icon_layers[index].surface.wl_surface().clone(),
            grab_seat: seat,
            pool: None, configured: false, icon_index: index,
            selected: DesktopContextAction::Open, hovered: None,
            pressed: None, can_move, can_reset,
            properties: false, back_hovered: false, back_pressed: false,
            file_operation: None,
        });
    }

    /// A popup can target another visible icon on the same wl_output while
    /// its Wayland parent remains the right-clicked icon surface.
    fn desktop_context_capabilities(&self, index: usize) -> (bool, bool) {
        let Some(icon) = self.icon_layers.get(index) else { return (false, false) };
        let recipe_index = icon.recipe_index;
        let mut names: Vec<_> = self.icon_layers.iter()
            .filter(|layer| layer.recipe_index == recipe_index)
            .filter_map(|layer| {
                let output = layer.bound_output.as_ref()
                    .or(self.primary_output.as_ref()).or(layer.output.as_ref())?;
                self.logical_output_size(output)?;
                self.outputs.info(output)?.name
            }).collect();
        names.sort();
        names.dedup();
        let can_move = recipe_index >= self.static_icon_count || names.len() > 1;
        let can_reset = recipe_index >= self.static_icon_count
            || (self.icon_output_name(index).is_some_and(|name|
            self.icon_outputs.can_reset_position(
                &name, &self.recipe.desktop_icons[..self.static_icon_count], recipe_index)));        (can_move, can_reset)
    }

    fn type_select_desktop_context(&mut self, typed: &str) -> bool {
        if self.recipe.id != "xp-luna-columns"
            || typed.chars().count() != 1
            || !typed.chars().all(char::is_alphanumeric) {
            return false;
        }
        let Some(current) = self.desktop_context.as_ref()
            .filter(|menu| !menu.properties).map(|menu| menu.icon_index)
            else { return false };
        let Some(source) = self.icon_layers.get(current) else { return false };
        let labels: Vec<Option<&str>> = self.icon_layers.iter().map(|icon| {
            (icon.placed.is_some() && icon.bound_output == source.bound_output)
                .then(|| self.recipe.desktop_icons.get(icon.recipe_index)
                    .map(|entry| entry.label.as_str())).flatten()
        }).collect();
        let Some(next) = self.desktop_type_select.feed(
            &labels, current, typed, Instant::now()) else { return true };
        if next != current {
            let (can_move, can_reset) = self.desktop_context_capabilities(next);
            self.select_luna_icon(next);
            if let Some(menu) = self.desktop_context.as_mut() {
                menu.icon_index = next;
                menu.can_move = can_move;
                menu.can_reset = can_reset;
                menu.selected = DesktopContextAction::Open;
                menu.hovered = None;
                menu.pressed = None;
            }
            self.context_generation = self.context_generation.wrapping_add(1);
            if std::env::var_os("RICEBOWL_DE_TRACE_DESKTOP").is_some() {
                eprintln!("RicePlate desktop type-select from={current} to={next}");
            }
            self.redraw_desktop_context();
        }
        true
    }

    fn choose_desktop_context(&mut self, action: DesktopContextAction,
                               qh: &QueueHandle<Self>) {
        let Some(menu) = self.desktop_context.as_ref() else { return };
        let index = menu.icon_index;
        if !action.enabled(menu.can_move, menu.can_reset) { return; }
        if action == DesktopContextAction::Properties {
            self.context_generation = self.context_generation.wrapping_add(1);
            if let Some(menu) = self.desktop_context.as_mut() {
                menu.properties = true;
                menu.hovered = None;
                menu.pressed = None;
                menu.back_hovered = false;
                menu.back_pressed = false;
            }
            self.redraw_desktop_context();
            return;
        }
        let Some(icon) = self.icon_layers.get(index) else {
            self.close_desktop_context();
            return;
        };
        let icon_action = self.recipe.desktop_icons[icon.recipe_index].action.clone();
        let file_index = icon.recipe_index.checked_sub(self.static_icon_count);
        if let Some(file_index) = file_index {
            match action {
                DesktopContextAction::NextDisplay => self.begin_file_rename(),
                DesktopContextAction::AllDisplays => self.begin_file_trash(),
                DesktopContextAction::ResetPosition => {
                    self.close_desktop_context();
                    self.show_file_in_explorer(file_index);
                }
                DesktopContextAction::Open => {
                    self.close_desktop_context();
                    self.activate_action(&icon_action, qh);
                }
                DesktopContextAction::Properties => unreachable!("handled above"),
            }
            return;
        }
        self.close_desktop_context();
        match action {
            DesktopContextAction::Open => self.activate_action(&icon_action, qh),
            DesktopContextAction::NextDisplay => self.assign_icon_to_next_output(index),
            DesktopContextAction::AllDisplays => self.mirror_icon_on_all_outputs(index),
            DesktopContextAction::ResetPosition => self.reset_icon_position(index),
            DesktopContextAction::Properties => unreachable!("read-only view handled above"),
        }
    }

    fn redraw_desktop_context(&mut self) {
        let Some(menu) = self.desktop_context.as_mut() else { return };
        if !menu.configured { return; }
        let Some(pool) = menu.pool.as_mut() else { return };
        let (buffer, canvas) = match pool.create_buffer(
            desktop_context::WIDTH as i32, desktop_context::HEIGHT as i32,
            (desktop_context::WIDTH * 4) as i32, wl_shm::Format::Argb8888,
        ) {
            Ok(value) => value,
            Err(error) => {
                eprintln!("RicePlate: desktop context buffer unavailable: {error}");
                self.close_desktop_context();
                return;
            }
        };
        let details = self.icon_layers.get(menu.icon_index)
            .and_then(|layer| self.recipe.desktop_icons.get(layer.recipe_index))
            .map(|icon| (icon.label.as_str(), icon.action.as_str()));
        paint_desktop_context(canvas, &self.recipe, menu.selected,
                              menu.hovered, menu.can_move, menu.can_reset,
                              menu.properties, details, menu.back_hovered,
                              menu.file_operation.as_ref());
        let surface = menu.popup.wl_surface();
        surface.damage_buffer(0, 0, desktop_context::WIDTH as i32,
                             desktop_context::HEIGHT as i32);
        if let Err(error) = buffer.attach_to(surface) {
            eprintln!("RicePlate: desktop context attach failed: {error}");
            self.close_desktop_context();
            return;
        }
        menu.popup.wl_surface().commit();
    }

    fn panel_pointer_visual(&self, surface: &wl_surface::WlSurface) -> PanelPointerVisual {
        if self.recipe.id != "xp-luna-columns" {
            return PanelPointerVisual::default();
        }
        let for_surface = |entry: &Option<(wl_surface::WlSurface, Hit)>| {
            entry.as_ref().and_then(|(owner, hit)| (owner == surface).then_some(*hit))
        };
        PanelPointerVisual {
            hovered: for_surface(&self.hovered_panel),
            pressed: for_surface(&self.pressed_panel),
        }
    }

    fn active_menu_size(&self) -> (u32, u32) {
        self.active_menu.as_ref()
            .and_then(|active| self.menu_layer.iter().chain(self.menu_mirrors.iter())
                .find(|layer| layer.surface.wl_surface() == active))
            .map_or((native_menu::WIDTH, native_menu::HEIGHT), |layer| layer.size)
    }

    fn accessibility_model(&self) -> accessibility::Model {
        use accessibility::{Model, Target, ROOT};

        let mut model = Model::new();
        let groups = self.grouped_tasks();
        let panels = std::iter::once((self.width, self.task_offset))
            .chain(self.mirrors.iter().map(|panel| (panel.width, panel.task_offset)));
        for (panel_index, (width, offset)) in panels.enumerate() {
            if width == 0 { continue; }
            let base = 10_000 + panel_index as u64 * 500;
            model.add(base, ROOT, AccessibleRole::Toolbar,
                      format!("RicePlate panel on monitor {}", panel_index + 1), None);
            let widgets = recipe::layout(&self.recipe, width, groups.len());
            for placed in widgets.into_iter().filter(|item| item.x < width) {
                match placed.widget {
                    Widget::Launcher => model.add(base + 1, base, AccessibleRole::Button,
                        "Open applications", Some(Target::Launcher(panel_index))),
                    Widget::Action(index) => {
                        if let Some(action) = self.recipe.actions.get(index as usize) {
                            let control = action.control.then(|| ControlAction::from_id(&action.id)).flatten();
                            let feedback = control.map(|item| ControlFeedback::snapshot(item,
                                &self.system_status, self.control_pending, self.control_result,
                                self.control_sender.is_some()));
                            let name = if let Some((item, state)) = control.zip(feedback) {
                                format!("{}, {}, {}", action.label, item.state_label(&self.system_status),
                                        state.accessibility_label())
                            } else { action.label.clone() };
                            model.add(base + 30 + index as u64, base, AccessibleRole::Button,
                                name, feedback.is_none_or(ControlFeedback::is_actionable)
                                    .then(|| Target::PanelAction(action.id.clone())));
                        }
                    }
                    Widget::Clock => model.add(base + 2, base, AccessibleRole::Button,
                        format!("Clock {}, open calendar", self.clock), Some(Target::Clock)),
                    Widget::Tasks => {
                        if let Some(view) = recipe::task_view(
                            &self.recipe, width, groups.len(), offset) {
                            for index in view.start..(view.start + view.slots).min(groups.len()) {
                                let group = &groups[index];
                                model.add(base + 100 + index as u64, base, AccessibleRole::Button,
                                    format!("{}{}", group.label,
                                            if group.active { ", active" } else { "" }),
                                    Some(Target::Task(index)));
                            }
                        }
                    }
                    Widget::Tray => {
                        for slot in 0..self.tray_keyboard_slots() {
                            let (label, action) = if let Some(item) = self.tray_state.item_at(slot) {
                                (format!("System tray: {}", item.title), Some(Target::Tray(slot)))
                            } else if self.tray_state.overflow_count() > 0 {
                                (format!("{} more tray icons", self.tray_state.overflow_count()),
                                 Some(Target::Tray(slot)))
                            } else { continue };
                            model.add(base + 300 + slot as u64, base,
                                      AccessibleRole::Button, label, action);
                        }
                    }
                    Widget::Network | Widget::Audio | Widget::Battery => {
                        let luna = self.recipe.id == "xp-luna-columns";
                        let (number, label) = match placed.widget {
                            Widget::Network => (5, format!("Network: {}",
                                self.system_status.network.label())),
                            Widget::Audio => (6, format!("Audio: {}",
                                self.system_status.audio.label())),
                            _ => (7, format!("Battery: {}", self.power.label())),
                        };
                        model.add(base + number, base,
                            if luna { AccessibleRole::Button } else { AccessibleRole::Status },
                            label, luna.then_some(Target::Status(placed.widget)));
                    },
                    Widget::Label(index) => {
                        if let Some(label) = self.recipe.labels.get(index as usize) {
                            model.add(base + 20 + index as u64, base,
                                      AccessibleRole::Label, label.clone(), None);
                        }
                    }
                    Widget::Gap(_) | Widget::Divider(_) => {}
                }
            }
        }
        if self.icon_layers.iter().any(|layer| layer.placed.is_some()) {
            model.add(30_000, ROOT, AccessibleRole::Group, "Desktop shortcuts", None);
            for (index, icon) in self.icon_layers.iter().enumerate() {
                if icon.placed.is_none() { continue; }
                if let Some(item) = self.recipe.desktop_icons.get(icon.recipe_index) {
                    let assignment = self.icon_outputs.owner(icon.recipe_index)
                        .map_or("mirrored on all displays", |_| "assigned to one display");
                    let selection_state = if self.recipe.id == "xp-luna-columns" {
                        if self.desktop_selection.is_selected(index) { ", selected" }
                        else { ", not selected" }
                    } else { "" };
                    model.add(30_100 + index as u64, 30_000, AccessibleRole::Button,
                              format!("{}, {}{}; F6 next display, F7 all displays",
                                      item.label, assignment, selection_state),
                              Some(Target::DesktopIcon(index)));
                }
            }
        }
        if let Some(menu) = self.desktop_context.as_ref() {
            if menu.properties {
                model.add(32_000, ROOT, AccessibleRole::Dialog, "Shortcut properties", None);
                if let Some(item) = self.icon_layers.get(menu.icon_index)
                    .and_then(|layer| self.recipe.desktop_icons.get(layer.recipe_index)) {
                    let (kind, destination) = desktop_context::details(&item.action);
                    model.add(32_001, 32_000, AccessibleRole::Label,
                              format!("Name: {}; Type: {}; {}", item.label, kind, destination),
                              None);
                }
                model.add(32_900, 32_000, AccessibleRole::Button,
                          "Back to shortcut actions",
                          Some(Target::DesktopContextBack {
                              icon: menu.icon_index, generation: self.context_generation,
                          }));
                if self.context_focused { model.focus = 32_900; }
            } else {
                model.add(32_000, ROOT, AccessibleRole::Menu, "Shortcut actions", None);
                for action in DesktopContextAction::ALL {
                    model.add(32_100 + action.index() as u64, 32_000,
                              AccessibleRole::MenuItem,
                              action.label(),
                              action.enabled(menu.can_move, menu.can_reset).then_some(
                                  Target::DesktopContextAction {
                                      icon: menu.icon_index, generation: self.context_generation,
                                      action,
                                  }));
                }
                if self.context_focused {
                    model.focus = 32_100 + menu.selected.index() as u64;
                }
            }
        }
        if self.widget_layers.iter().any(|layer| layer.placed.is_some()) {
            model.add(31_000, ROOT, AccessibleRole::Group, "Desktop widgets", None);
            for (index, layer) in self.widget_layers.iter().enumerate() {
                if layer.placed.is_none() { continue; }
                if let Some(widget) = self.recipe.composition.as_ref()
                    .and_then(|composition| composition.widgets.get(layer.recipe_index)) {
                    let description = match &widget.kind {
                        recipe::DesktopWidgetKind::Clock => format!("Time: {}", self.clock),
                        recipe::DesktopWidgetKind::Date =>
                            format!("Date: {}", Local::now().format("%a %d %b %Y")),
                        recipe::DesktopWidgetKind::System =>
                            format!("Network: {}, Audio: {}",
                                    self.system_status.network.label(),
                                    self.system_status.audio.label()),
                        recipe::DesktopWidgetKind::Network =>
                            format!("Network: {}", self.system_status.network.label()),
                        recipe::DesktopWidgetKind::Audio =>
                            format!("Audio: {}", self.system_status.audio.label()),
                        recipe::DesktopWidgetKind::Battery =>
                            format!("Battery: {}", self.power.label()),
                        recipe::DesktopWidgetKind::Text(value) => value.clone(),
                        recipe::DesktopWidgetKind::Action(action) => {
                            format!("{}, {}", widget.title.as_deref().unwrap_or("Action"),
                                    self.desktop_action_state(action))
                        }
                    };
                    let (role, target) = match &widget.kind {
                        recipe::DesktopWidgetKind::Text(_) => (AccessibleRole::Label, None),
                        recipe::DesktopWidgetKind::Action(action) =>
                            (AccessibleRole::Button, self.desktop_action_enabled(action)
                                .then(|| Target::DesktopWidget(index))),
                        _ => (AccessibleRole::Status, None),
                    };
                    model.add(31_100 + index as u64, 31_000, role,
                              description, target);
                }
            }
        }
        if self.menu_state.visible && self.active_menu.is_some() {
            if self.notification_state.open {
                let popup_size = self.active_menu_size();
                let compact = native_menu::compact_layout(popup_size);
                model.add(22_000, ROOT, AccessibleRole::Dialog, "Notifications", None);
                if self.notification_state.detail_id.is_none() {
                    model.add(22_100, 22_000, AccessibleRole::Tab,
                              format!("Active notifications: {}", self.notification_state.notices.len()),
                              Some(Target::NotificationTab(false)));
                    model.add(22_101, 22_000, AccessibleRole::Tab,
                              format!("Past notifications: {}", self.notification_state.history.len()),
                              Some(Target::NotificationTab(true)));
                }
                if self.notification_state.sync_error {
                    model.add(22_151, 22_000, AccessibleRole::Status,
                              "Notification host unavailable; retrying", None);
                }
                if let Some((first, last, total)) = self.notification_state.list_page_status(
                    compact.then_some(popup_size)) {
                    model.add(22_152, 22_000, AccessibleRole::Status,
                              format!("Showing notifications {first} to {last} of {total}"), None);
                }
                if self.notification_state.loading {
                    model.add(22_150, 22_000, AccessibleRole::Status, "Loading notifications", None);
                } else if let Some(error) = self.notification_state.error {
                    model.add(22_150, 22_000, AccessibleRole::Alert, error, None);
                } else if let Some(detail) = self.notification_state.detail_notice() {
                    model.add(22_160, 22_000, AccessibleRole::Group,
                              format!("Notification from {}", detail.app_name), None);
                    model.add(22_161, 22_160, AccessibleRole::Label, detail.summary.clone(), None);
                    model.add(22_162, 22_160, AccessibleRole::Label, detail.body.clone(), None);
                    if (if compact { self.notification_state.compact_body_page_count(popup_size) }
                        else { self.notification_state.body_page_count() }) > 1 {
                        model.add(22_163, 22_160, AccessibleRole::Button,
                                  "Previous message page", Some(Target::NotificationBodyPage(-1)));
                        model.add(22_164, 22_160, AccessibleRole::Button,
                                  "Next message page", Some(Target::NotificationBodyPage(1)));
                    }
                    if !self.notification_state.show_history {
                        let first = if compact {
                            self.notification_state.compact_first_action_row(popup_size)
                        } else { self.notification_state.first_action_row() };
                        let rows = if compact { ricepop::compact_action_rows(popup_size) }
                                   else { ricepop::VISIBLE_ROWS };
                        for (index, action) in detail.actions.iter().enumerate()
                            .skip(first).take(rows) {
                            model.add(22_300 + index as u64, 22_160, AccessibleRole::Button,
                                      action.label.clone(),
                                      Some(Target::NotificationInvoke(detail.id, action.key.clone())));
                        }
                    }
                } else {
                    let first = if compact { self.notification_state.compact_first_row(popup_size) }
                                else { self.notification_state.first_row() };
                    let rows = if compact { ricepop::compact_rows(popup_size) }
                               else { ricepop::VISIBLE_ROWS };
                    for (index, notice) in self.notification_state.visible_notices().iter()
                        .enumerate().skip(first).take(rows) {
                        model.add(22_200 + index as u64, 22_000,
                                  AccessibleRole::Button,
                                  format!("View notification from {}: {}", notice.app_name, notice.summary),
                                  Some(Target::NotificationSelect(index)));
                        if let Some(node) = model.elements.last_mut() {
                            node.description = Some(notice.body.chars()
                                .filter(|character| !character.is_control())
                                .take(512).collect());
                        }
                    }
                }
                model.add(22_900, 22_000, AccessibleRole::Button,
                          if self.notification_state.detail_id.is_some() {
                              "Back to notification list"
                          } else { "Back to menu" }, Some(Target::NotificationBack));
                model.add(22_901, 22_000, AccessibleRole::Button,
                          "Refresh notifications", Some(Target::NotificationRefresh));
                if let Some(id) = self.notification_state.selected_id() {
                    model.add(22_902, 22_000, AccessibleRole::Button,
                              "Dismiss selected notification", Some(Target::NotificationDismiss(id)));
                }
                if self.menu_focused {
                    model.focus = if self.notification_state.detail_id.is_some() {
                        if self.notification_state.selected_action().is_some() {
                            22_300 + self.notification_state.selected_action as u64
                        } else { 22_900 }
                    } else if !self.notification_state.visible_notices().is_empty()
                        && self.notification_state.selected < self.notification_state.visible_notices().len()
                        && !self.notification_state.loading && self.notification_state.error.is_none() {
                        22_200 + self.notification_state.selected as u64
                    } else { 22_900 };
                }
            } else if let Some(menu) = self.recipe.menu.as_ref() {
                model.add(20_000, ROOT, AccessibleRole::Menu, menu.title.clone(), None);
                let active_size = self.active_menu.as_ref()
                    .and_then(|active| self.menu_layer.iter().chain(self.menu_mirrors.iter())
                        .find(|layer| layer.surface.wl_surface() == active))
                    .map(|layer| layer.size)
                    .unwrap_or((native_menu::WIDTH, native_menu::HEIGHT));
                let compact = native_menu::compact_layout(active_size);
                let columns = menu.presentation == recipe::MenuPresentation::Columns
                    && self.menu_state.view == native_menu::View::Groups && !compact;
                let rows = if compact { native_menu::compact_visible_actions(active_size) }
                           else if columns { 8 } else { native_menu::VISIBLE_ACTIONS };
                let group_role = if menu.presentation == recipe::MenuPresentation::Sidebar && !compact {
                    AccessibleRole::Button
                } else {
                    AccessibleRole::Tab
                };
                // Full two-column presentation contains section headings,
                // not interactive group tabs. Do not expose invisible controls.
                if !columns {
                    for (index, group) in menu.groups.iter().enumerate() {
                        model.add(20_100 + index as u64, 20_000, group_role,
                                  group.title.clone(), Some(Target::MenuGroup(index)));
                    }
                }
                if let Some(sections) = self.menu_state.composed_sections(menu).filter(|_| !compact) {
                    for (index, section) in sections.iter().enumerate() {
                        model.add(20_300 + index as u64, 20_000, AccessibleRole::Label,
                                  section.title.to_string(), None);
                    }
                }
                let menu_actions = self.menu_state.actions(menu);
                let selected_action_exists = self.menu_state.selected < menu_actions.len();
                let first = if columns { 0 }
                            else { self.menu_state.first_action_row_for(rows) };
                for (index, action) in menu_actions.into_iter().enumerate()
                    .skip(first).take(rows) {
                    let enabled = action != "logout" || logout_available();
                    model.add(20_500 + index as u64, 20_000, AccessibleRole::Button,
                              self.menu_state.label(action),
                              enabled.then(|| Target::MenuAction(action.to_string())));
                }
                model.add(20_980, 20_000, AccessibleRole::Label,
                          self.menu_state.accessible_summary(menu, rows),
                          None);
                model.add(20_985, 20_000, AccessibleRole::Button,
                          match self.menu_state.search_button_label() {
                              "Find" => "Find applications and actions",
                              "Clear" => "Clear search query",
                              _ => "Back to menu groups",
                          }, Some(Target::MenuSearch));
                model.add(20_990, 20_000, AccessibleRole::Button,
                          if self.menu_state.view == native_menu::View::Saved {
                              "Back to menu groups"
                          } else { "Show saved actions" }, Some(Target::MenuSaved));
                // The opt-in full-size Luna footer contains two additional
                // genuine buttons. Expose their own AT-SPI nodes; compact and
                // palette-free menu trees must not announce invisible controls.
                if menu.presentation == recipe::MenuPresentation::Columns
                    && menu.palette.is_some() && !compact {
                    model.add(20_993, 20_000, AccessibleRole::Button,
                              "Lock screen (Start footer)",
                              Some(Target::MenuAction("lock".to_string())));
                    let can_logout = logout_available();
                    model.add(20_994, 20_000, AccessibleRole::Button,
                              if can_logout { "Log off (Start footer)" }
                              else { "Log off unavailable (Start footer)" },
                              can_logout.then(|| Target::MenuAction("logout".to_string())));
                }
                model.add(20_999, 20_000, AccessibleRole::Button,
                          "Close menu", Some(Target::MenuClose));
                if self.menu_focused {
                    model.focus = if selected_action_exists {
                        20_500 + self.menu_state.selected as u64
                    } else { 20_999 };
                }
            }
        }
        if self.calendar_state.visible && self.active_calendar.is_some() {
            model.add(40_000, ROOT, AccessibleRole::Dialog,
                      format!("Calendar {}", self.calendar_state.month.format("%B %Y")), None);
            model.add(40_100, 40_000, AccessibleRole::Button,
                      "Previous month", Some(Target::CalendarPrevious));
            model.add(40_101, 40_000, AccessibleRole::Button,
                      "Next month", Some(Target::CalendarNext));
            model.add(40_102, 40_000, AccessibleRole::Button,
                      "Go to today", Some(Target::CalendarToday));
            for (index, (day, in_month)) in self.calendar_state.cells().iter().enumerate() {
                let selected = *day == self.calendar_state.selected;
                model.add(40_200 + index as u64, 40_000, AccessibleRole::Button,
                          format!("{}{}{}", day.format("%A %d %B %Y"),
                                  if selected { ", selected" } else { "" },
                                  if !in_month { ", adjacent month" } else { "" }),
                          Some(Target::CalendarDay(*day)));
                if self.calendar_focused && selected {
                    model.focus = 40_200 + index as u64;
                }
            }
        }
        if self.tray_menu_state.visible && self.active_tray_popup.is_some() {
            model.add(51_000, ROOT, AccessibleRole::Menu,
                      self.tray_menu_state.title.clone(), None);
            for (index, row) in self.tray_menu_state.rows().iter().enumerate()
                .skip(self.tray_menu_state.first).take(tray::POPUP_ROWS) {
                model.add(51_100 + index as u64, 51_000,
                          AccessibleRole::MenuItem,
                          if row.label.is_empty() { "Separator".to_string() }
                          else { row.label.clone() },
                          row.selectable().then_some(Target::TrayMenuRow(index)));
            }
            model.add(51_900, 51_000, AccessibleRole::Button,
                      "Back", Some(Target::TrayMenuBack));
            model.add(51_901, 51_000, AccessibleRole::Button,
                      "Previous page", Some(Target::TrayMenuPage(-1)));
            model.add(51_902, 51_000, AccessibleRole::Button,
                      "Next page", Some(Target::TrayMenuPage(1)));
            model.add(51_903, 51_000, AccessibleRole::Button,
                      "Close tray menu", Some(Target::TrayMenuClose));
            if self.tray_popup_focused {
                model.focus = 51_100 + self.tray_menu_state.selected as u64;
            }
        } else if self.tray_popup_state.visible && self.active_tray_popup.is_some() {
            model.add(50_000, ROOT, AccessibleRole::Dialog, "System tray overflow", None);
            for index in self.tray_popup_state.first..
                (self.tray_popup_state.first + tray::POPUP_ROWS).min(self.tray_state.entries.len()) {
                model.add(50_100 + index as u64, 50_000, AccessibleRole::Button,
                          self.tray_state.entries[index].title.clone(),
                          Some(Target::TrayPopupItem(index)));
            }
            model.add(50_900, 50_000, AccessibleRole::Button,
                      "Previous tray page", Some(Target::TrayPopupPage(-1)));
            model.add(50_901, 50_000, AccessibleRole::Button,
                      "Next tray page", Some(Target::TrayPopupPage(1)));
            model.add(50_902, 50_000, AccessibleRole::Button,
                      "Close tray", Some(Target::TrayPopupClose));
            if self.tray_popup_focused {
                model.focus = 50_100 + self.tray_popup_state.selected as u64;
            }
        }
        if model.focus == accessibility::ROOT {
            if let Some(surface) = self.focused_panel.as_ref() {
                if let Some((mirror, _, _)) = self.panel_geometry(surface) {
                    let base = 10_000 + mirror.map_or(0, |index| index + 1) as u64 * 500;
                    model.focus = match self.focused_target {
                        Some(KeyboardTarget::Launcher) => base + 1,
                        Some(KeyboardTarget::Action(index)) => base + 30 + index as u64,
                        Some(KeyboardTarget::Task(index)) => base + 100 + index as u64,
                        Some(KeyboardTarget::Tray(index)) => base + 300 + index as u64,
                        Some(KeyboardTarget::Status(widget)) => base + match widget {
                            Widget::Network => 5, Widget::Audio => 6, _ => 7,
                        },
                        Some(KeyboardTarget::Clock) => base + 2,
                        None => base,
                    };
                }
            } else if let Some(index) = self.focused_icon.filter(|_|
                self.keyboard_icon_surface.is_some()) {
                model.focus = 30_100 + index as u64;
            } else if let Some(index) = self.focused_widget {
                if self.keyboard_widget_surface.is_some() {
                    model.focus = 31_100 + index as u64;
                }
            }
        }
        model.window_focused = self.menu_focused || self.calendar_focused
            || self.tray_popup_focused || self.context_focused || self.focused_panel.is_some()
            || self.keyboard_icon_surface.is_some() || self.keyboard_widget_surface.is_some();
        model
    }

    fn handle_accessibility_action(&mut self, request: &ActionRequest,
                                   qh: &QueueHandle<Self>) {
        use accessibility::Target;
        // An action from an old AT-SPI snapshot must not be rebound to a
        // different window, menu entry or notification after a state change.
        let old = self.accessibility.as_ref().and_then(|bridge| bridge.action_for(request));
        if old.is_none() || old != self.accessibility_model().action_for(request) { return; }
        match old.unwrap() {
            Target::Launcher(panel) => self.activate_launcher(
                if panel == 0 { None } else { Some(panel - 1) }, qh),
            Target::PanelAction(action) => self.activate_action(&action, qh),
            Target::Task(index) => self.activate_group(index),
            Target::Clock => self.toggle_calendar_for_panel(None, qh),
            Target::Status(widget) => {
                let source = self.layer.wl_surface().clone();
                self.open_luna_status_menu(widget, &source, qh);
            }
            Target::DesktopIcon(index) => {
                if let Some(icon) = self.icon_layers.get(index) {
                    if let Some(item) = self.recipe.desktop_icons.get(icon.recipe_index) {
                        let action = item.action.clone();
                        self.activate_action(&action, qh);
                    }
                }
            }
            Target::DesktopContextAction { icon, generation, action } => {
                let valid = self.desktop_context.as_ref().is_some_and(|menu|
                    menu.icon_index == icon && self.context_generation == generation
                    && !menu.properties && action.enabled(menu.can_move, menu.can_reset));
                if valid { self.choose_desktop_context(action, qh); }
            }
            Target::DesktopContextBack { icon, generation } => {
                let valid = self.desktop_context.as_ref().is_some_and(|menu|
                    menu.icon_index == icon && self.context_generation == generation
                    && menu.properties);
                if valid {
                    if let Some(menu) = self.desktop_context.as_mut() {
                        menu.properties = false;
                        menu.back_hovered = false;
                        menu.back_pressed = false;
                    }
                    self.context_generation = self.context_generation.wrapping_add(1);
                    self.redraw_desktop_context();
                }
            }
            Target::DesktopWidget(index) => {
                if let Some(action) = self.widget_action(index).map(str::to_owned) {
                    if self.desktop_action_enabled(&action) {
                        self.activate_action(&action, qh);
                        self.redraw_widgets();
                    }
                }
            }
            Target::Tray(slot) => {
                if slot == tray::VISIBLE_ITEMS - 1 && self.tray_state.overflow_count() > 0 {
                    self.toggle_tray_popup_for_panel(None, qh);
                } else {
                    let surface = self.layer.wl_surface().clone();
                    let position = self.tray_screen_position(&surface, (0.0, 0.0));
                    self.activate_tray_item(slot, BTN_LEFT, position, &surface, qh);
                }
            }
            Target::MenuGroup(index) => {
                if let Some(menu) = self.recipe.menu.as_ref() {
                    self.menu_state.select_group(menu, index);
                }
                self.redraw_menu(qh);
            }
            Target::MenuAction(action) => self.activate_action(&action, qh),
            Target::MenuSearch => {
                self.menu_state.search_button();
                self.redraw_menu(qh);
            }
            Target::MenuClose => self.set_menu_visible(false, qh),
            Target::MenuSaved => {
                self.menu_state.show_saved();
                self.redraw_menu(qh);
            }
            Target::CalendarPrevious => { self.calendar_state.shift(-1); self.redraw_calendar(qh); }
            Target::CalendarNext => { self.calendar_state.shift(1); self.redraw_calendar(qh); }
            Target::CalendarToday => {
                self.calendar_state.go_today(Local::now().date_naive());
                self.redraw_calendar(qh);
            }
            Target::CalendarDay(day) => {
                self.calendar_state.select(day);
                self.redraw_calendar(qh);
            }
            Target::NotificationTab(history) => {
                self.notification_state.select_tab(history);
                self.redraw_menu(qh);
            }
            Target::NotificationSelect(index) => {
                self.notification_state.open_detail(index);
                self.redraw_menu(qh);
            }
            Target::NotificationBodyPage(delta) => {
                let size = self.active_menu_size();
                if native_menu::compact_layout(size) {
                    self.notification_state.change_compact_body_page(delta, size);
                } else { self.notification_state.change_body_page(delta); }
                self.redraw_menu(qh);
            }
            Target::NotificationInvoke(id, key) => {
                let valid = self.notification_state.action_at(0).is_some()
                    && self.notification_state.detail_notice().is_some_and(|notice|
                        notice.id == id && notice.actions.iter().any(|action| action.key == key));
                if valid {
                    self.request_notifications(NotificationIntent::Invoke(id, key), qh);
                }
            }
            Target::NotificationRefresh => self.request_notifications(NotificationIntent::Refresh, qh),
            Target::NotificationDismiss(id) => {
                if self.notification_state.selected_id() == Some(id) {
                    self.request_notifications(NotificationIntent::Dismiss(id), qh);
                }
            }
            Target::NotificationBack => {
                if self.notification_state.detail_id.is_some() {
                    self.notification_state.close_detail();
                } else {
                    self.notification_state.close();
                }
                self.redraw_menu(qh);
            }
            Target::TrayPopupItem(index) => {
                if let Some(surface) = self.active_tray_popup.clone() {
                    let position = self.tray_screen_position(&surface, (44.0, 60.0));
                    self.activate_tray_entry(index, BTN_LEFT, position, &surface, qh);
                }
            }
            Target::TrayPopupClose => self.set_tray_popup_visible(false, qh),
            Target::TrayPopupPage(delta) => {
                self.tray_popup_state.page(delta as isize, self.tray_state.entries.len());
                self.redraw_tray_popup();
            }
            Target::TrayMenuRow(index) => self.choose_tray_menu_row(index, qh),
            Target::TrayMenuBack => self.back_tray_menu(qh),
            Target::TrayMenuClose => self.set_tray_popup_visible(false, qh),
            Target::TrayMenuPage(delta) => {
                self.tray_menu_state.page(delta as isize);
                self.redraw_tray_popup();
            }
        }
    }

    fn tray_keyboard_slots(&self) -> usize {
        self.tray_state.visible_count() + usize::from(self.tray_state.overflow_count() > 0)
    }

    fn panel_geometry(&self, surface: &wl_surface::WlSurface)
        -> Option<(Option<usize>, u32, usize)>
    {
        if surface == self.layer.wl_surface() {
            return Some((None, self.width, self.task_offset));
        }
        self.mirrors.iter().enumerate()
            .find(|(_, mirror)| mirror.surface.wl_surface() == surface)
            .map(|(index, mirror)| (Some(index), mirror.width, mirror.task_offset))
    }

    fn activate_launcher(&mut self, mirror: Option<usize>, qh: &QueueHandle<Self>) {
        if self.menu_layer.is_some() {
            self.toggle_menu_for_panel(mirror, qh);
        } else {
            self.activate_action("applications", qh);
        }
    }

    fn toggle_show_desktop(&mut self, qh: &QueueHandle<Self>) {
        if !self.show_desktop_restore.is_empty() {
            // Do not undo windows the user had already minimized, or newly
            // opened windows. A closed foreign toplevel is ignored safely.
            for task in &self.tasks {
                if self.show_desktop_restore.iter().any(|handle| handle == &task.handle) {
                    // The compositor may still be processing set_minimized
                    // from a rapid double-toggle. Unset is idempotent and
                    // must not depend on an asynchronous state callback.
                    task.handle.unset_minimized();
                }
            }
            self.show_desktop_restore.clear();
        } else {
            self.show_desktop_restore = self.tasks.iter()
                .filter(|task| task.ready && !task.minimized)
                .map(|task| task.handle.clone()).collect();
            for handle in &self.show_desktop_restore { handle.set_minimized(); }
        }
        self.request_redraw(qh);
    }

    fn activate_group(&mut self, index: usize) {
        let groups = self.grouped_tasks();
        if let Some(group) = groups.get(index) {
            let active_index = group.members.iter().copied()
                .find(|&member| self.tasks[member].active);
            let (target, minimize) = task_groups::click_target(group, active_index);
            if self.trace_window_events {
                eprintln!("RicePlate taskbar action={} app_id={:?} seat={} minimized={}",
                    if minimize { "minimize" } else { "restore" },
                    self.tasks[target].app_id,
                    self.primary_seat.is_some(), self.tasks[target].minimized);
            }
            if minimize {
                self.tasks[target].handle.set_minimized();
            } else {
                // Restoring a hidden task must not depend on an activation seat:
                // some nested or remote compositor sessions do not advertise one.
                if self.tasks[target].minimized {
                    self.tasks[target].handle.unset_minimized();
                }
                if let Some(seat) = self.primary_seat.as_ref() {
                    self.tasks[target].handle.activate(seat);
                }
            }
        }
    }

    fn handle_panel_key(&mut self, key: Keysym, qh: &QueueHandle<Self>) -> bool {
        let Some(surface) = self.focused_panel.as_ref() else { return false; };
        let Some((mirror, width, offset)) = self.panel_geometry(surface) else { return false; };
        let groups = self.grouped_tasks();
        let count = groups.len();
        match input_core::panel_key(key) {
            Some(PanelKey::Step(delta)) => {
                self.focused_target = task_navigation::advance(
                    &self.recipe, width, count, self.focused_target, delta,
                    self.tray_keyboard_slots(),
                );
                let next = task_navigation::reveal(
                    &self.recipe, width, count, offset, self.focused_target,
                );
                if let Some(index) = mirror {
                    self.mirrors[index].task_offset = next;
                } else {
                    self.task_offset = next;
                }
                self.request_redraw(qh);
            }
            Some(PanelKey::Invoke) => {
                match self.focused_target {
                    Some(KeyboardTarget::Launcher) if key != Keysym::Menu =>
                        self.activate_launcher(mirror, qh),
                    Some(KeyboardTarget::Action(index)) if key != Keysym::Menu => {
                        if let Some(action) = self.recipe.actions.get(index as usize) {
                            let action_id = action.id.clone();
                            self.activate_action(&action_id, qh);
                        }
                    }
                    Some(KeyboardTarget::Task(index)) if key != Keysym::Menu =>
                        self.activate_group(index),
                    Some(KeyboardTarget::Status(widget)) => {
                        let source = surface.clone();
                        self.open_luna_status_menu(widget, &source, qh);
                    }
                    Some(KeyboardTarget::Clock) => {
                        if key == Keysym::Menu {
                            let source = surface.clone();
                            self.open_luna_status_menu(Widget::Clock, &source, qh);
                        } else {
                            self.toggle_calendar_for_panel(mirror, qh);
                        }
                    }
                    Some(KeyboardTarget::Tray(slot)) => {
                        if slot == tray::VISIBLE_ITEMS - 1 &&
                            self.tray_state.overflow_count() > 0 {
                            self.toggle_tray_popup_for_panel(mirror, qh);
                        } else if let Some(placed) = recipe::layout(&self.recipe, width,
                            count).into_iter().find(|p| p.widget == Widget::Tray) {
                            let local = (f64::from(placed.x + slot as u32 * tray::SLOT_WIDTH + 14),
                                         f64::from(self.recipe.height / 2));
                            let position = self.tray_screen_position(surface, local);
                            let source = surface.clone();
                            let button = if key == Keysym::Menu { BTN_RIGHT } else { BTN_LEFT };
                            self.activate_tray_item(slot, button, position, &source, qh);
                        }
                    }
                    _ => {}
                }
            }
            Some(PanelKey::Dismiss) => {
                self.focused_target = None;
                self.request_redraw(qh);
            }
            None => return false,
        }
        true
    }

    fn save_icon_positions(&mut self) {
        if !self.icon_position_dirty { return; }
        let extras = self.recipe.desktop_icons.split_off(self.static_icon_count);
        let result = icon_positions::save(&self.recipe, &self.icon_outputs);
        self.recipe.desktop_icons.extend(extras);
        if let Err(error) = result {
            eprintln!("RicePlate: cannot persist static icon positions: {error}");
            return;
        }
        self.icon_position_dirty = false;
    }

    fn sync_mirrors(&mut self, qh: &QueueHandle<Self>) {
        // An output can disappear between wl_surface.leave and its eventual
        // enter on another output. Never leave the remaining display blank
        // while the compositor is deciding where the unbound primary goes.
        // Before the very first enter, defer to the compositor's initial
        // placement to avoid redundant startup panels.
        if !self.primary_output_seen { return; }
        let outputs: Vec<_> = self.outputs.outputs()
            .filter(|output| self.primary_output.as_ref() != Some(output))
            .filter(|output| self.logical_output_size(output).is_some())
            .take(MAX_OUTPUT_PANELS).collect();
        let old_count = self.mirrors.len();
        self.mirrors.retain(|mirror| outputs.contains(&mirror.output));
        if old_count != self.mirrors.len() {
            eprintln!("RicePlate: secondary panels removed: {} -> {}", old_count, self.mirrors.len());
        }
        for output in outputs.iter().cloned() {
            if self.mirrors.iter().any(|mirror| mirror.output == output) { continue; }
            eprintln!("RicePlate: creating secondary panel on {output:?}");
            let surface = self.layer_shell.create_layer_surface(
                qh, self.compositor.create_surface(qh), Layer::Top,
                Some("riceplate-output-panel"), Some(&output),
            );
            let edge = if self.recipe.top { Anchor::TOP } else { Anchor::BOTTOM };
            surface.set_anchor(edge | Anchor::LEFT | Anchor::RIGHT);
            let height = luna_taskbar::panel_height(self.luna_options,
                self.panel_collapsed, self.recipe.height);
            surface.set_size(0, height);
            surface.set_exclusive_zone(height as i32);
            surface.set_keyboard_interactivity(KeyboardInteractivity::OnDemand);
            surface.commit();
            self.mirrors.push(PanelMirror {
                output, surface, pool: None, width: 0, height: 0,
                configured: false, frame: FrameGate::default(),
                task_offset: 0,
            });
        }
        // Desktop shortcut surfaces follow the same explicit secondary output
        // ownership as panels. No full-screen input-grabbing wallpaper layer.
        let before = self.icon_layers.len();
        // Tear down the popup before its original icon is removed. This
        // includes hot-unplug AND a former secondary output becoming primary:
        // the icon layer is replaced even when the output stays connected.
        // Search can change the selected action, never the Wayland parent.
        if self.desktop_context.as_ref().is_some_and(|menu|
            self.icon_layers.iter().any(|icon|
                icon.surface.wl_surface() == &menu.parent_surface
                && icon.bound_output.as_ref().is_some_and(|output| !outputs.contains(output)))) {
            self.close_desktop_context();
        }
        self.icon_layers.retain(|icon| icon.bound_output.as_ref()
            .is_none_or(|output| outputs.contains(output)));
        let icons_removed = before != self.icon_layers.len();
        if icons_removed {
            self.desktop_selection.clear();
            // Layer indices can shift after hot-unplug. Never leave an icon
            // keyboard target or drag pointing at a different surface.
            self.focused_icon = None;
            self.keyboard_icon_surface = None;
            self.icon_drag = None;
            self.save_icon_positions();
        }
        for output in &outputs {
            for (recipe_index, icon) in self.recipe.desktop_icons.iter().enumerate() {
                if self.icon_layers.iter().any(|layer|
                    layer.recipe_index == recipe_index && layer.bound_output.as_ref() == Some(output)) {
                    continue;
                }
                let surface = self.layer_shell.create_layer_surface(
                    qh, self.compositor.create_surface(qh), Layer::Bottom,
                    Some("riceplate-output-desktop-icon"), Some(output),
                );
                surface.set_anchor(Anchor::TOP | Anchor::LEFT);
                surface.set_size(recipe::ICON_WIDTH, recipe::ICON_HEIGHT);
                surface.set_margin(icon.y as i32, 0, 0, icon.x as i32);
                surface.set_exclusive_zone(-1);
                surface.set_keyboard_interactivity(KeyboardInteractivity::OnDemand);
                surface.commit();
                self.icon_layers.push(IconLayer {
                    recipe_index, surface, pool: None, configured: false,
                    output: Some(output.clone()), bound_output: Some(output.clone()),
                    placed: Some((icon.x, icon.y)),
                });
            }
        }
        let prior_widgets = self.widget_layers.len();
        self.widget_layers.retain(|widget| widget.bound_output.as_ref()
            .is_none_or(|output| outputs.contains(output)));
        if prior_widgets != self.widget_layers.len() {
            // Indices are unstable after unplug; never retarget focus or an
            // in-flight click to another widget.
            self.focused_widget = None;
            self.keyboard_widget_surface = None;
            self.pressed_widget = None;
            self.hovered_widget = None;
        }
        if let Some(composition) = self.recipe.composition.as_ref() {
            let empty_input = Region::new(&self.compositor);
            for output in &outputs {
                for (recipe_index, widget) in composition.widgets.iter().enumerate() {
                    if self.widget_layers.iter().any(|layer|
                        layer.recipe_index == recipe_index
                        && layer.bound_output.as_ref() == Some(output)) { continue; }
                    let Ok(input) = &empty_input else {
                        eprintln!("RicePlate: cannot make desktop widgets input-transparent");
                        continue;
                    };
                    let surface = self.layer_shell.create_layer_surface(
                        qh, self.compositor.create_surface(qh), Layer::Bottom,
                        Some("riceplate-output-desktop-widget"), Some(output),
                    );
                    surface.set_anchor(Anchor::TOP | Anchor::LEFT);
                    surface.set_size(recipe::DESKTOP_WIDGET_WIDTH, recipe::DESKTOP_WIDGET_HEIGHT);
                    surface.set_margin(widget.y as i32, 0, 0, widget.x as i32);
                    surface.set_exclusive_zone(-1);
                    if matches!(&widget.kind, recipe::DesktopWidgetKind::Action(_)) {
                        surface.set_keyboard_interactivity(KeyboardInteractivity::OnDemand);
                    } else {
                        surface.set_keyboard_interactivity(KeyboardInteractivity::None);
                        surface.wl_surface().set_input_region(Some(input.wl_region()));
                    }
                    surface.commit();
                    self.widget_layers.push(DesktopWidgetLayer {
                        recipe_index, surface, pool: None, configured: false,
                        output: Some(output.clone()), bound_output: Some(output.clone()),
                        placed: Some((widget.x, widget.y)),
                    });
                }
            }
        }
        self.reflow_icons();
        if icons_removed {
            // Existing icon surfaces may keep an old selection highlight even
            // when their placement did not change during unplug. Refresh the
            // survivors once; indices were invalidated by retain().
            for index in 0..self.icon_layers.len() {
                self.redraw_icon(index);
            }
        }
        self.menu_mirrors.retain(|menu|
            menu.output.as_ref().is_some_and(|output| outputs.contains(output)));
        if self.menu_layer.is_some() {
            for output in &outputs {
                if self.menu_mirrors.iter().any(|menu|
                    menu.output.as_ref() == Some(output)) { continue; }
                let surface = self.layer_shell.create_layer_surface(
                    qh, self.compositor.create_surface(qh), Layer::Top,
                    Some("riceplate-output-menu"), Some(output),
                );
                surface.set_anchor((if self.recipe.top { Anchor::TOP } else { Anchor::BOTTOM })
                    | Anchor::LEFT);
                surface.set_size(native_menu::WIDTH, native_menu::HEIGHT);
                surface.set_margin(
                    if self.recipe.top { self.recipe.height as i32 } else { 0 },
                    0,
                    if self.recipe.top { 0 } else { self.recipe.height as i32 },
                    MAX_WIDTH as i32,
                );
                surface.set_exclusive_zone(-1);
                surface.set_keyboard_interactivity(KeyboardInteractivity::None);
                surface.commit();
                self.menu_mirrors.push(MenuLayer {
                    surface, pool: None, configured: false, output: Some(output.clone()),
                    size: (native_menu::WIDTH, native_menu::HEIGHT),
                });
            }
        }
        let default_menu_size = (native_menu::WIDTH, native_menu::HEIGHT);
        let luna_columns = self.recipe.menu.as_ref().is_some_and(|menu|
            menu.presentation == recipe::MenuPresentation::Columns && menu.palette.is_some());
        let panel_height = self.recipe.height;
        let fit = |width, height| if luna_columns {
            native_menu::fitted_luna_size(width, height, panel_height)
        } else {
            native_menu::fitted_size(width, height, panel_height)
        };
        let root_menu_size = self.primary_output.as_ref()
            .and_then(|output| self.logical_output_size(output))
            .map(|(width, height)| fit(width, height))
            .unwrap_or(default_menu_size);
        let mirror_menu_sizes: Vec<_> = outputs.iter().filter_map(|output|
            self.logical_output_size(output).map(|(width, height)|
                (output.clone(), fit(width, height))))
            .collect();
        for menu in self.menu_layer.iter_mut().chain(self.menu_mirrors.iter_mut()) {
            let size = menu.output.as_ref()
                .and_then(|output| mirror_menu_sizes.iter()
                    .find(|(name, _)| name == output).map(|(_, size)| *size))
                .unwrap_or(root_menu_size);
            if menu.size != size {
                if std::env::var_os("RICEBOWL_DE_TRACE_MENU").is_some() {
                    eprintln!("RicePlate: menu trace resize {:?} -> {:?}, active={}",
                              menu.size, size, self.menu_state.visible);
                }
                menu.size = size;
                menu.configured = false;
                menu.pool = None;
                menu.surface.set_size(size.0, size.1);
                menu.surface.commit();
            }
        }
        if self.active_menu.as_ref().is_some_and(|surface|
            self.menu_layer.as_ref().is_none_or(|root| root.surface.wl_surface() != surface)
            && !self.menu_mirrors.iter().any(|menu|
                menu.surface.wl_surface() == surface)) {
            self.active_menu = None;
            self.menu_state.close();
            self.menu_focused = false;
        }
        if self.preview_secondary_menu {
            if let Some(surface) = self.menu_mirrors.first()
                .map(|menu| menu.surface.wl_surface().clone()) {
                self.show_menu_at(surface, qh);
                self.preview_secondary_menu = false;
            }
        }
        self.calendar_mirrors.retain(|calendar|
            calendar.output.as_ref().is_some_and(|output| outputs.contains(output)));
        if self.calendar_layer.is_some() {
            for output in &outputs {
                if self.calendar_mirrors.iter().any(|calendar|
                    calendar.output.as_ref() == Some(output)) { continue; }
                let surface = self.layer_shell.create_layer_surface(
                    qh, self.compositor.create_surface(qh), Layer::Top,
                    Some("riceplate-output-calendar"), Some(output),
                );
                surface.set_anchor((if self.recipe.top { Anchor::TOP } else { Anchor::BOTTOM })
                    | Anchor::RIGHT);
                surface.set_size(calendar::WIDTH, calendar::HEIGHT);
                surface.set_margin(
                    if self.recipe.top { self.recipe.height as i32 } else { 0 },
                    MAX_WIDTH as i32,
                    if self.recipe.top { 0 } else { self.recipe.height as i32 },
                    0,
                );
                surface.set_exclusive_zone(-1);
                surface.set_keyboard_interactivity(KeyboardInteractivity::None);
                surface.commit();
                self.calendar_mirrors.push(CalendarLayer {
                    surface, pool: None, configured: false, output: Some(output.clone()),
                });
            }
        }
        if self.active_calendar.as_ref().is_some_and(|surface|
            self.calendar_layer.as_ref().is_none_or(|root|
                root.surface.wl_surface() != surface)
            && !self.calendar_mirrors.iter().any(|calendar|
                calendar.surface.wl_surface() == surface)) {
            self.active_calendar = None;
            self.calendar_state.visible = false;
            self.calendar_focused = false;
        }
        if self.preview_secondary_calendar {
            if let Some(surface) = self.calendar_mirrors.first()
                .map(|calendar| calendar.surface.wl_surface().clone()) {
                self.show_calendar_at(surface, qh);
                self.preview_secondary_calendar = false;
            }
        }
        self.tray_popup_mirrors.retain(|popup|
            popup.output.as_ref().is_some_and(|output| outputs.contains(output)));
        if self.tray_popup_layer.is_some() {
            for output in &outputs {
                if self.tray_popup_mirrors.iter().any(|popup|
                    popup.output.as_ref() == Some(output)) { continue; }
                let surface = self.layer_shell.create_layer_surface(
                    qh, self.compositor.create_surface(qh), Layer::Top,
                    Some("riceplate-output-tray-overflow"), Some(output),
                );
                surface.set_anchor((if self.recipe.top { Anchor::TOP } else { Anchor::BOTTOM })
                    | Anchor::RIGHT);
                surface.set_size(tray::POPUP_WIDTH, tray::POPUP_HEIGHT);
                surface.set_margin(
                    if self.recipe.top { self.recipe.height as i32 + 8 } else { 0 },
                    MAX_WIDTH as i32,
                    if self.recipe.top { 0 } else { self.recipe.height as i32 + 8 }, 0,
                );
                surface.set_exclusive_zone(-1);
                surface.set_keyboard_interactivity(KeyboardInteractivity::None);
                surface.commit();
                self.tray_popup_mirrors.push(TrayPopupLayer {
                    surface, pool: None, configured: false, output: Some(output.clone()),
                });
            }
        }
        if self.active_tray_popup.as_ref().is_some_and(|surface|
            self.tray_popup_layer.as_ref().is_none_or(|root|
                root.surface.wl_surface() != surface)
            && !self.tray_popup_mirrors.iter().any(|popup|
                popup.surface.wl_surface() == surface)) {
            self.set_tray_popup_visible(false, qh);
        }
        if self.focused_panel.as_ref().is_some_and(|surface|
            self.panel_geometry(surface).is_none()) {
            self.focused_panel = None;
            self.focused_target = None;
        }
        // Hot-unplug must never retain a hover/press owner on a destroyed
        // layer, nor paint that interaction onto a surviving mirror.
        if self.hovered_panel.as_ref().is_some_and(|(surface, _)|
            self.panel_geometry(surface).is_none()) {
            self.hovered_panel = None;
        }
        if self.pressed_panel.as_ref().is_some_and(|(surface, _)|
            self.panel_geometry(surface).is_none()) {
            self.pressed_panel = None;
        }
    }

    fn redraw_mirror(&mut self, index: usize, qh: &QueueHandle<Self>) {
        let paint_started = self.trace_frames.then(Instant::now);
        let groups = self.grouped_tasks();
        self.cached_task_group_count = groups.len();
        let selected = if self.focused_panel.as_ref()
            == self.mirrors.get(index).map(|mirror| mirror.surface.wl_surface()) {
            self.focused_target
        } else { None };
        let visual = self.mirrors.get(index)
            .map(|mirror| self.panel_pointer_visual(mirror.surface.wl_surface()))
            .unwrap_or_default();
        let Some(mirror) = self.mirrors.get_mut(index) else { return };
        if !mirror.configured || mirror.width == 0 || mirror.height == 0 { return; }
        let surface = mirror.surface.wl_surface();
        let Some(pool) = mirror.pool.as_mut() else { return };
        let (buffer, canvas) = match pool.create_buffer(
            mirror.width as i32, mirror.height as i32,
            (mirror.width * 4) as i32, wl_shm::Format::Argb8888,
        ) {
            Ok(value) => value,
            Err(error) => {
                eprintln!("RicePlate: deferring busy output panel buffer: {error}");
                surface.frame(qh, FrameCallbackData(surface.clone()));
                mirror.frame.buffer_busy();
                mirror.surface.commit();
                return;
            }
        };
        paint_panel_pointer(canvas, mirror.width, mirror.height, &self.recipe, &groups,
                    &self.clock, &self.power, &self.system_status, &self.tray_state,
                    mirror.task_offset, selected, self.control_pending, self.control_result,
                    visual);
        surface.damage_buffer(0, 0, mirror.width as i32, mirror.height as i32);
        if let Err(error) = buffer.attach_to(surface) {
            eprintln!("RicePlate: cannot attach output panel: {error}");
            return;
        }
        surface.frame(qh, FrameCallbackData(surface.clone()));
        mirror.frame.submitted();
        mirror.surface.commit();
        if let Some(started) = paint_started {
            let stats = mirror.frame.stats();
            eprintln!("RicePlate frame=mirror output={index} paint_us={} commits={} invalidations={} coalesced={} shm_retries={}",
                started.elapsed().as_micros(), stats.commits, stats.invalidations,
                stats.coalesced, stats.busy_retries);
        }
    }

    fn set_menu_visible(&mut self, visible: bool, qh: &QueueHandle<Self>) {
        if visible {
            if let Some(surface) = self.menu_layer.as_ref()
                .map(|menu| menu.surface.wl_surface().clone()) {
                self.show_menu_at(surface, qh);
            }
            return;
        }
        if std::env::var_os("RICEBOWL_DE_TRACE_MENU").is_some() {
            eprintln!("RicePlate: menu trace hide");
        }
        self.menu_state.close();
        self.notification_state.close();
        self.menu_focused = false;
        self.active_menu = None;
        for layer in self.menu_layer.iter().chain(self.menu_mirrors.iter()) {
            layer.surface.set_keyboard_interactivity(KeyboardInteractivity::None);
            layer.surface.set_margin(
                if self.recipe.top { self.recipe.height as i32 } else { 0 },
                0,
                if self.recipe.top { 0 } else { self.recipe.height as i32 },
                MAX_WIDTH as i32,
            );
            layer.surface.commit();
        }
        // Pointer Leave happened while Start was covering the taskbar.
        // Reconcile now: waiting for another Leave would pin the panel open.
        self.maybe_collapse_luna_panel(qh);
    }

    fn show_menu_at(&mut self, surface: wl_surface::WlSurface, qh: &QueueHandle<Self>) {
        if !self.menu_layer.iter().chain(self.menu_mirrors.iter()).any(|menu|
            menu.surface.wl_surface() == &surface) { return; }
        if std::env::var_os("RICEBOWL_DE_TRACE_MENU").is_some() {
            let geometry = self.menu_layer.iter().chain(self.menu_mirrors.iter())
                .find(|layer| layer.surface.wl_surface() == &surface)
                .map(|layer| (layer.size, layer.configured));
            eprintln!("RicePlate: menu trace show {:?}", geometry);
        }
        if self.calendar_state.visible { self.set_calendar_visible(false, qh); }
        if self.tray_popup_open() { self.set_tray_popup_visible(false, qh); }
        self.menu_state.refresh_apps();
        self.menu_state.open();
        self.notification_state.close();
        self.menu_focused = false;
        self.active_menu = Some(surface.clone());
        for layer in self.menu_layer.iter().chain(self.menu_mirrors.iter()) {
            let active = layer.surface.wl_surface() == &surface;
            layer.surface.set_keyboard_interactivity(if active {
                KeyboardInteractivity::OnDemand
            } else {
                KeyboardInteractivity::None
            });
            layer.surface.set_margin(
                if self.recipe.top { self.recipe.height as i32 } else { 0 },
                0,
                if self.recipe.top { 0 } else { self.recipe.height as i32 },
                if active { 0 } else { MAX_WIDTH as i32 },
            );
            layer.surface.commit();
        }
        self.redraw_menu(qh);
    }

    fn toggle_menu_for_panel(&mut self, mirror: Option<usize>, qh: &QueueHandle<Self>) {
        let target = match mirror {
            Some(index) => self.mirrors.get(index).and_then(|panel|
                self.menu_mirrors.iter().find(|menu|
                    menu.output.as_ref() == Some(&panel.output)))
                .map(|menu| menu.surface.wl_surface().clone()),
            None => self.menu_layer.as_ref()
                .map(|menu| menu.surface.wl_surface().clone()),
        };
        let Some(target) = target else { return; };
        if self.menu_state.visible && self.active_menu.as_ref() == Some(&target) {
            self.set_menu_visible(false, qh);
        } else {
            self.show_menu_at(target, qh);
        }
    }

    fn activate_action(&mut self, action: &str, qh: &QueueHandle<Self>) {
        if let Some(index) = action.strip_prefix("desktop-file:")
            .and_then(|value| value.parse::<usize>().ok()) {
            if self.recipe.id == "xp-luna-columns" { self.open_desktop_file(index); }
            return;
        }
        if action == "show-desktop" {
            if self.menu_state.visible { self.set_menu_visible(false, qh); }
            self.toggle_show_desktop(qh);
            return;
        }
        if matches!(action, "run" | "help") {
            // The schema permits these only in the themed columns profile.
            if self.recipe.menu.as_ref().is_some_and(|menu|
                menu.presentation == recipe::MenuPresentation::Columns
                    && menu.palette.is_some()) {
                self.open_luna_dialog(if action == "run" { luna_dialog::Kind::Run }
                                      else { luna_dialog::Kind::Help }, qh);
            }
            return;
        }
        if action == "notifications" {
            self.request_notifications(NotificationIntent::Refresh, qh);
            return;
        }
        if action == "settings" && self.recipe.id == "xp-luna-columns" {
            if self.menu_state.visible { self.set_menu_visible(false, qh); }
            self.launch_luna_settings("home");
            return;
        }
        if let Some(control) = ControlAction::from_id(action) {
            let supported = control.available(&self.system_status);
            let idle = self.control_pending.is_none();
            let sent = supported && idle && self.control_sender.as_ref()
                .is_some_and(|sender| sender.try_send(control).is_ok());
            if sent {
                self.control_pending = Some(control);
                self.control_result = None;
            } else if supported && idle {
                self.control_result = Some((control, false));
            }
            self.menu_state.notice = Some(if sent { "Applying..." }
                else if !supported { "Hardware unavailable" }
                else if !idle { "Control busy" }
                else { "Unavailable or denied" });
            if self.menu_state.visible { self.redraw_menu(qh); }
            self.request_redraw(qh);
            self.redraw_widgets();
            return;
        }
        if self.menu_state.visible {
            self.set_menu_visible(false, qh);
        }
        if action == "logout" && !logout_available() {
            eprintln!("RicePlate: log out unavailable outside a labwc-managed session");
            return;
        }
        if matches!(action, "documents" | "computer" | "pictures" | "music" | "network" | "trash") {
            luna_places::launch(action, self.recipe.id == "xp-luna-columns");
            return;
        }
        if action.starts_with("desktop:") {
            // Let GLib handle field codes, DBusActivatable, terminal preferences
            // and desktop-file quoting. Never interpret Exec as a shell command.
            if let Some(path) = self.menu_state.app_path(action).map(std::path::Path::to_path_buf) {
                match Command::new("gio").arg("launch").arg(&path).spawn() {
                    Ok(_) => {
                        if self.menu_state.record_app_launch(action)
                            && self.recipe.id == "xp-luna-columns"
                        {
                            if let Err(error) = menu_recents::save(
                                &self.recipe.id, self.menu_state.recent_apps()) {
                                eprintln!("RicePlate: cannot save XP Luna recents: {error}");
                            }
                        }
                    }
                    Err(error) => {
                        eprintln!("RicePlate: cannot launch desktop application: {error}");
                    }
                }
            }
            return;
        }
        let (program, args): (&str, &[&str]) = match action {
            "applications" => ("fuzzel", &[]),
            "terminal" => ("foot", &[]),
            "settings" => ("ricebowl", &["de", "settings"]),
            // Strict, fixed argv: opens only the GTK browser, no watcher.
            "clip-history" => ("ricebowl", &["de", "clip", "--clip-op", "gui"]),
            "lock" => ("ricebowl", &["de", "lock"]),
            "logout" => ("labwc", &["--exit"]),
            _ => return, // Validated recipe contract disallows other IDs.
        };
        if let Err(error) = Command::new(program).args(args).spawn() {
            eprintln!("RicePlate: cannot run {action}: {error}");
        }
    }

    fn activate_menu_action(&mut self, action: &str, qh: &QueueHandle<Self>) {
        // Only the opt-in Luna columns rice replaces the external launcher
        // with an XP-style All Programs page. Desktop shortcuts and every
        // other menu presentation retain their existing fuzzel action.
        if action == "applications" && self.recipe.menu.as_ref().is_some_and(|menu|
            menu.presentation == recipe::MenuPresentation::Columns && menu.palette.is_some()) {
            self.menu_state.show_programs();
            self.redraw_menu(qh);
        } else {
            self.activate_action(action, qh);
        }
    }

    fn request_notifications(&mut self, intent: NotificationIntent, qh: &QueueHandle<Self>) {
        let revision = self.notification_state.begin();
        let request = match intent {
            NotificationIntent::Refresh => NotificationRequest::Refresh(revision),
            NotificationIntent::Dismiss(id) => NotificationRequest::Dismiss(revision, id),
            NotificationIntent::Invoke(id, key) => NotificationRequest::Invoke(revision, id, key),
        };
        if !self.notification_sender.as_ref()
            .is_some_and(|sender| sender.try_send(request).is_ok()) {
            self.notification_state.update(revision, Err("RicePop busy or unavailable"));
        }
        self.redraw_menu(qh);
    }

    fn redraw_menu(&mut self, _qh: &QueueHandle<Self>) {
        let Some(active) = self.active_menu.as_ref() else { return; };
        if self.notification_state.open {
            let size = self.active_menu_size();
            self.notification_state.set_compact_viewport(
                native_menu::compact_layout(size).then_some(size));
        }
        let layer = self.menu_layer.as_mut().filter(|menu|
            menu.surface.wl_surface() == active)
            .or_else(|| self.menu_mirrors.iter_mut().find(|menu|
                menu.surface.wl_surface() == active));
        let (Some(layer), Some(menu)) = (layer, self.recipe.menu.as_ref()) else { return };
        if !layer.configured || !self.menu_state.visible { return; }
        let surface = layer.surface.wl_surface();
        let Some(pool) = layer.pool.as_mut() else {
            return;
        };
        let (width, height) = layer.size;
        let (buffer, canvas) = match pool.create_buffer(
            width as i32,
            height as i32,
            (width * 4) as i32,
            wl_shm::Format::Argb8888,
        ) {
            Ok(result) => result,
            Err(error) => {
                eprintln!("RicePlate: native menu buffer unavailable: {error}");
                return;
            }
        };
        if self.notification_state.open && native_menu::compact_layout(layer.size) {
            paint_compact_notifications(canvas, &self.recipe, &self.notification_state,
                                        layer.size);
        } else if native_menu::compact_layout(layer.size) {
            // Keep the bitmap font at its native pixel size on rotated/small
            // outputs; actions and optional composed sections become a paged
            // list rather than shrinking into unreadable miniature tiles.
            paint_compact_menu(canvas, menu, &self.recipe, &self.menu_state, layer.size);
        } else if layer.size == (native_menu::WIDTH, native_menu::HEIGHT) {
            if self.notification_state.open {
                paint_notifications(canvas, &self.recipe, &self.notification_state);
            } else {
                paint_menu(canvas, menu, &self.recipe, &self.menu_state);
            }
        } else {
            // The menu and RicePop detail states share a 320×304 logical hit
            // vocabulary. Fit that complete surface on small/rotated outputs
            // without silently clipping actions or changing keyboard order.
            let mut original = vec![0_u8;
                (native_menu::WIDTH * native_menu::HEIGHT * 4) as usize];
            if self.notification_state.open {
                paint_notifications(&mut original, &self.recipe, &self.notification_state);
            } else {
                paint_menu(&mut original, menu, &self.recipe, &self.menu_state);
            }
            if self.recipe.id == "xp-luna-columns" && !self.notification_state.open
                && layer.size.0 > native_menu::WIDTH && layer.size.1 > native_menu::HEIGHT {
                // Historical 320px menu logic stays authoritative for input,
                // but enlarged Luna menus no longer use chunky nearest-neighbor
                // stretching of proportional glyphs and thin 1px borders.
                fit_luna_menu_pixels(&original, canvas, layer.size);
            } else {
                fit_menu_pixels(&original, canvas, layer.size);
            }
        }
        surface.damage_buffer(0, 0, width as i32, height as i32);
        if let Err(error) = buffer.attach_to(surface) {
            eprintln!("RicePlate: native menu attach failed: {error}");
            self.closed = true;
            return;
        }
        layer.surface.commit();
    }

    fn set_calendar_visible(&mut self, visible: bool, qh: &QueueHandle<Self>) {
        if visible {
            if let Some(surface) = self.calendar_layer.as_ref()
                .map(|calendar| calendar.surface.wl_surface().clone()) {
                self.show_calendar_at(surface, qh);
            }
            return;
        }
        self.calendar_state.visible = false;
        self.calendar_focused = false;
        self.active_calendar = None;
        for layer in self.calendar_layer.iter().chain(self.calendar_mirrors.iter()) {
            layer.surface.set_keyboard_interactivity(KeyboardInteractivity::None);
            layer.surface.set_margin(
                if self.recipe.top { self.recipe.height as i32 } else { 0 },
                MAX_WIDTH as i32,
                if self.recipe.top { 0 } else { self.recipe.height as i32 }, 0,
            );
            layer.surface.commit();
        }
        self.maybe_collapse_luna_panel(qh);
    }

    fn show_calendar_at(&mut self, surface: wl_surface::WlSurface, qh: &QueueHandle<Self>) {
        if !self.calendar_layer.iter().chain(self.calendar_mirrors.iter()).any(|calendar|
            calendar.surface.wl_surface() == &surface) { return; }
        if self.menu_state.visible { self.set_menu_visible(false, qh); }
        if self.tray_popup_open() { self.set_tray_popup_visible(false, qh); }
        self.calendar_state.open(Local::now().date_naive());
        self.calendar_focused = false;
        self.active_calendar = Some(surface.clone());
        for layer in self.calendar_layer.iter().chain(self.calendar_mirrors.iter()) {
            let active = layer.surface.wl_surface() == &surface;
            layer.surface.set_keyboard_interactivity(if active {
                KeyboardInteractivity::OnDemand
            } else {
                KeyboardInteractivity::None
            });
            layer.surface.set_margin(
                if self.recipe.top { self.recipe.height as i32 } else { 0 },
                if active { 8 } else { MAX_WIDTH as i32 },
                if self.recipe.top { 0 } else { self.recipe.height as i32 }, 0,
            );
            layer.surface.commit();
        }
        self.redraw_calendar(qh);
    }

    fn toggle_calendar_for_panel(&mut self, mirror: Option<usize>, qh: &QueueHandle<Self>) {
        let target = match mirror {
            Some(index) => self.mirrors.get(index).and_then(|panel|
                self.calendar_mirrors.iter().find(|calendar|
                    calendar.output.as_ref() == Some(&panel.output)))
                .map(|calendar| calendar.surface.wl_surface().clone()),
            None => self.calendar_layer.as_ref()
                .map(|calendar| calendar.surface.wl_surface().clone()),
        };
        let Some(target) = target else { return; };
        if self.calendar_state.visible && self.active_calendar.as_ref() == Some(&target) {
            self.set_calendar_visible(false, qh);
        } else {
            self.show_calendar_at(target, qh);
        }
    }

    fn redraw_calendar(&mut self, _qh: &QueueHandle<Self>) {
        let Some(active) = self.active_calendar.as_ref() else { return; };
        let layer = self.calendar_layer.as_mut().filter(|calendar|
            calendar.surface.wl_surface() == active)
            .or_else(|| self.calendar_mirrors.iter_mut().find(|calendar|
                calendar.surface.wl_surface() == active));
        let Some(layer) = layer else { return; };
        if !layer.configured || !self.calendar_state.visible { return; }
        let surface = layer.surface.wl_surface();
        // Keep the popup's shared-memory allocation lazy during idle sessions.
        if layer.pool.is_none() {
            let bytes = (calendar::WIDTH * calendar::HEIGHT * 4 * 3) as usize;
            match SlotPool::new(bytes, &self.shm) {
                Ok(pool) => layer.pool = Some(pool),
                Err(error) => {
                    eprintln!("RicePlate: calendar allocation failed: {error}");
                    self.set_calendar_visible(false, _qh);
                    return;
                }
            }
        }
        let Some(pool) = layer.pool.as_mut() else { return; };
        let (buffer, canvas) = match pool.create_buffer(
            calendar::WIDTH as i32, calendar::HEIGHT as i32,
            (calendar::WIDTH * 4) as i32, wl_shm::Format::Argb8888,
        ) {
            Ok(result) => result,
            Err(error) => {
                eprintln!("RicePlate: calendar buffer unavailable: {error}");
                return;
            }
        };
        paint_calendar(canvas, &self.recipe, &self.calendar_state);
        surface.damage_buffer(0, 0, calendar::WIDTH as i32, calendar::HEIGHT as i32);
        if let Err(error) = buffer.attach_to(surface) {
            eprintln!("RicePlate: calendar attach failed: {error}");
            self.closed = true;
            return;
        }
        layer.surface.commit();
    }

    fn redraw_osd(&mut self) {
        let Some(notice) = self.osd_state.current.as_ref() else { return };
        let Some(layer) = self.osd_layer.as_mut() else { return };
        if !layer.configured { return; }
        if layer.pool.is_none() {
            let bytes = (osd::WIDTH * osd::HEIGHT * 4 * 3) as usize;
            match SlotPool::new(bytes, &self.shm) {
                Ok(pool) => layer.pool = Some(pool),
                Err(error) => {
                    eprintln!("RicePop: OSD allocation failed: {error}");
                    return;
                }
            }
        }
        let Some(pool) = layer.pool.as_mut() else { return };
        let (buffer, canvas) = match pool.create_buffer(
            osd::WIDTH as i32, osd::HEIGHT as i32,
            (osd::WIDTH * 4) as i32, wl_shm::Format::Argb8888,
        ) {
            Ok(result) => result,
            Err(error) => {
                eprintln!("RicePop: deferring busy OSD buffer: {error}");
                return;
            }
        };
        paint_osd(canvas, &self.recipe, notice);
        layer.surface.set_margin(osd_top_margin(&self.recipe), 16, 0, 0);
        let surface = layer.surface.wl_surface();
        surface.damage_buffer(0, 0, osd::WIDTH as i32, osd::HEIGHT as i32);
        if let Err(error) = buffer.attach_to(surface) {
            eprintln!("RicePop: OSD attach failed: {error}");
            self.hide_osd();
            return;
        }
        layer.surface.commit();
    }

    fn hide_osd(&mut self) {
        if let Some(layer) = self.osd_layer.as_mut() {
            layer.surface.set_margin(osd_top_margin(&self.recipe), MAX_WIDTH as i32, 0, 0);
            layer.surface.commit();
        }
    }

    fn redraw_icon(&mut self, index: usize) {
        let Some(layer) = self.icon_layers.get_mut(index) else {
            return;
        };
        if !layer.configured || layer.placed.is_none() {
            return;
        }
        let width = recipe::ICON_WIDTH;
        let height = recipe::ICON_HEIGHT;
        let surface = layer.surface.wl_surface();
        let pool = layer.pool.as_mut().expect("configured icon has pool");
        let (buffer, canvas) = match pool.create_buffer(
            width as i32,
            height as i32,
            (width * 4) as i32,
            wl_shm::Format::Argb8888,
        ) {
            Ok(result) => result,
            Err(error) => {
                eprintln!("RicePlate: desktop icon buffer unavailable: {error}");
                return;
            }
        };
        let icon = &self.recipe.desktop_icons[layer.recipe_index];
        let icon_index = match icon.action.as_str() {
            "applications" => Some(0), "terminal" => Some(1), "lock" => Some(2), _ => None,
        };
        let icon_pixels = icon_index.and_then(|which| self.recipe.native_art.as_ref()
            .and_then(|art| art.icons[which].as_ref()));
        paint_icon(canvas, icon, &self.recipe,
                   self.focused_icon == Some(index)
                       || (self.recipe.id == "xp-luna-columns"
                           && self.desktop_selection.is_selected(index)), icon_pixels);
        surface.damage_buffer(0, 0, width as i32, height as i32);
        if let Err(error) = buffer.attach_to(surface) {
            eprintln!("RicePlate: desktop icon attach failed: {error}");
            self.closed = true;
            return;
        }
        layer.surface.commit();
    }

    fn widget_action(&self, index: usize) -> Option<&str> {
        let layer = self.widget_layers.get(index)?;
        if layer.placed.is_none() { return None; }
        let widget = self.recipe.composition.as_ref()?.widgets.get(layer.recipe_index)?;
        match &widget.kind {
            recipe::DesktopWidgetKind::Action(action) => Some(action),
            _ => None,
        }
    }

    fn desktop_action_enabled(&self, action: &str) -> bool {
        ControlAction::from_id(action).is_none_or(|control|
            ControlFeedback::snapshot(control, &self.system_status,
                self.control_pending, self.control_result, self.control_sender.is_some())
                .is_actionable())
    }

    fn desktop_action_state(&self, action: &str) -> &'static str {
        let Some(control) = ControlAction::from_id(action) else { return "Press Enter or click"; };
        ControlFeedback::snapshot(control, &self.system_status,
            self.control_pending, self.control_result, self.control_sender.is_some())
            .desktop_hint()
    }

    fn redraw_widget(&mut self, index: usize) {
        let Some(widget) = self.recipe.composition.as_ref()
            .and_then(|composition| self.widget_layers.get(index)
                .and_then(|layer| composition.widgets.get(layer.recipe_index))) else { return; };
        let (title, lines) = match &widget.kind {
            recipe::DesktopWidgetKind::Clock =>
                ("Clock", vec![self.clock.clone()]),
            recipe::DesktopWidgetKind::Date =>
                ("Date", vec![Local::now().format("%a %d %b").to_string(),
                              Local::now().format("%Y").to_string()]),
            recipe::DesktopWidgetKind::System =>
                ("System", vec![format!("Network: {}", self.system_status.network.label()),
                                format!("Audio: {}", self.system_status.audio.label())]),
            recipe::DesktopWidgetKind::Network =>
                (widget.title.as_deref().unwrap_or("Network"),
                 vec![self.system_status.network.label().to_string()]),
            recipe::DesktopWidgetKind::Audio =>
                (widget.title.as_deref().unwrap_or("Audio"),
                 vec![self.system_status.audio.label().to_string()]),
            recipe::DesktopWidgetKind::Battery =>
                (widget.title.as_deref().unwrap_or("Battery"),
                 vec![self.power.label().to_string()]),
            recipe::DesktopWidgetKind::Text(value) => ("Text", vec![value.clone()]),
            recipe::DesktopWidgetKind::Action(action) =>
                (widget.title.as_deref().unwrap_or("Action"),
                 vec![action.replace('-', " "), self.desktop_action_state(action).to_string()]),
        };
        let interactive = matches!(&widget.kind, recipe::DesktopWidgetKind::Action(_));
        let disabled = matches!(&widget.kind, recipe::DesktopWidgetKind::Action(action)
            if !self.desktop_action_enabled(action));
        let focused = self.focused_widget == Some(index)
            && self.keyboard_widget_surface.is_some();
        let hovered = self.hovered_widget == Some(index);
        let Some(layer) = self.widget_layers.get_mut(index) else { return; };
        if !layer.configured || layer.placed.is_none() { return; }
        let width = recipe::DESKTOP_WIDGET_WIDTH;
        let height = recipe::DESKTOP_WIDGET_HEIGHT;
        let Some(pool) = layer.pool.as_mut() else { return; };
        let (buffer, canvas) = match pool.create_buffer(
            width as i32, height as i32, (width * 4) as i32, wl_shm::Format::Argb8888,
        ) {
            Ok(result) => result,
            Err(error) => {
                eprintln!("RicePlate: desktop widget buffer unavailable: {error}");
                return;
            }
        };
        paint_desktop_widget(canvas, title, &lines, &self.recipe,
                             interactive, focused, hovered, disabled);
        let surface = layer.surface.wl_surface();
        surface.damage_buffer(0, 0, width as i32, height as i32);
        if let Err(error) = buffer.attach_to(surface) {
            eprintln!("RicePlate: desktop widget attach failed: {error}");
            return;
        }
        layer.surface.commit();
    }

    fn redraw_widgets(&mut self) {
        for index in 0..self.widget_layers.len() {
            self.redraw_widget(index);
        }
    }

    fn logical_output_size(&self, output: &wl_output::WlOutput) -> Option<(u32, u32)> {
        let info = self.outputs.info(output)?;
        // xdg-output logical dimensions include fractional scale and rotation.
        // Old compositors may expose only physical mode and integer scale.
        let (width, height) = info.logical_size.or_else(|| {
            info.modes.iter().find(|mode| mode.current).map(|mode| {
                let scale = info.scale_factor.max(1);
                (mode.dimensions.0 / scale, mode.dimensions.1 / scale)
            })
        })?;
        if width <= 0 || height <= 0 {
            return None;
        }
        Some((width as u32, height as u32))
    }

    fn icon_output_name(&self, layer_index: usize) -> Option<String> {
        let layer = self.icon_layers.get(layer_index)?;
        let output = layer.bound_output.as_ref().or(self.primary_output.as_ref())
            .or(layer.output.as_ref())?;
        self.outputs.info(output)?.name
    }

    fn icon_coordinates(&self, layer_index: usize) -> icon_positions::Coordinates {
        let layer = &self.icon_layers[layer_index];
        let original = &self.recipe.desktop_icons[layer.recipe_index];
        self.icon_output_name(layer_index).as_deref()
            .and_then(|name| self.icon_outputs.for_output(name, self.static_icon_count))
            .and_then(|positions| positions.get(layer.recipe_index)).copied()
            .unwrap_or(icon_positions::Coordinates { x: original.x, y: original.y })
    }

    fn move_icon(&mut self, layer_index: usize, desired: (u32, u32)) {
        let recipe_index = self.icon_layers[layer_index].recipe_index;
        if recipe_index >= self.static_icon_count {
            if let Some(icon) = self.recipe.desktop_icons.get_mut(recipe_index) {
                (icon.x, icon.y) = desired;
            }
            self.reflow_icons();
            return;
        }
        let coords = icon_positions::Coordinates { x: desired.0, y: desired.1 };
        if let Some(output) = self.icon_output_name(layer_index) {
            if let Err(error) = self.icon_outputs.set(&output, &self.recipe.desktop_icons,
                                                       recipe_index, coords) {
                eprintln!("RicePlate: not saving display-specific icon position: {error}");
                return;
            }
        } else {
            // Compositors that hide output names still support legacy global
            // positions; never fabricate a supposedly stable monitor ID.
            let icon = &mut self.recipe.desktop_icons[recipe_index];
            (icon.x, icon.y) = desired;
        }
        self.reflow_icons();
        self.icon_position_dirty = true;
    }

    fn finish_cross_output_drag(&mut self, drag: &IconDrag, pointer: (f64, f64)) -> bool {
        let Some(source_layer) = self.icon_layers.get(drag.index) else { return false };
        let Some(current) = source_layer.placed else { return false };
        let Some(source_output) = source_layer.bound_output.as_ref()
            .or(self.primary_output.as_ref()).or(source_layer.output.as_ref()) else {
            return false;
        };
        let Some(source_origin) = self.outputs.info(source_output)
            .and_then(|info| info.logical_position) else { return false };
        let Some(source_name) = self.icon_output_name(drag.index) else { return false };
        let recipe_index = source_layer.recipe_index;
        if recipe_index >= self.static_icon_count { return false; }
        // Only currently configured, named shell outputs are valid targets.
        // Without xdg-output logical geometry retain the single-display drag.
        let target = self.icon_layers.iter().enumerate().find_map(|(index, layer)| {
            if index == drag.index || layer.recipe_index != recipe_index || !layer.configured {
                return None;
            }
            let output = layer.bound_output.as_ref()
                .or(self.primary_output.as_ref()).or(layer.output.as_ref())?;
            let info = self.outputs.info(output)?;
            let name = info.name.as_ref()?;
            if name == &source_name { return None; }
            let coords = desktop_layout::cross_output_drop(
                source_origin, current, pointer, drag.anchor,
                info.logical_position?, self.logical_output_size(output)?,
            )?;
            Some((index, name.clone(), coords))
        });
        let Some((target_index, name, desired)) = target else { return false };
        // Discard transient moves against the source output. A cross-monitor
        // drop should not rewrite its previous layout or mirrored fallback.
        let mut next = drag.original_positions.clone();
        let transferred = match next.transfer(&self.recipe.desktop_icons[..self.static_icon_count], recipe_index, &name,
            icon_positions::Coordinates { x: desired.0, y: desired.1 }) {
            Ok(()) => { self.icon_outputs = next; true }
            Err(error) => {
                eprintln!("RicePlate: cross-output icon drop refused: {error}");
                self.icon_outputs = drag.original_positions.clone();
                false
            }
        };
        self.focused_icon = None;
        self.keyboard_icon_surface = None;
        self.reflow_icons();
        if transferred && self.icon_layers[target_index].placed.is_none() {
            // A reserved window region or very small display can have no free
            // icon cell. Never save an assignment that hides the shortcut.
            self.icon_outputs = drag.original_positions.clone();
            self.reflow_icons();
            eprintln!("RicePlate: target display has no usable icon position");
        }
        self.icon_position_dirty = true;
        self.save_icon_positions();
        true
    }

    fn assign_icon_to_next_output(&mut self, layer_index: usize) {
        let Some(current) = self.icon_output_name(layer_index) else { return; };
        let recipe_index = self.icon_layers[layer_index].recipe_index;
        // Only offer outputs for which this process actually owns an icon
        // surface. The compositor may advertise more outputs than the bounded
        // secondary layer-shell allocation supports.
        let mut names: Vec<_> = self.icon_layers.iter()
            .filter(|layer| layer.recipe_index == recipe_index)
            .filter_map(|layer| {
                let output = layer.bound_output.as_ref().or(self.primary_output.as_ref())
                    .or(layer.output.as_ref())?;
                self.logical_output_size(output)?;
                self.outputs.info(output)?.name
            })
            .collect();
        names.sort();
        names.dedup();
        if names.len() < 2 { return; }
        let next = names.iter().position(|name| name == &current)
            .map_or(0, |index| (index + 1) % names.len());
        if let Err(error) = self.icon_outputs.assign(
            &self.recipe.desktop_icons[..self.static_icon_count], recipe_index, Some(&names[next]),
        ) {
            eprintln!("RicePlate: cannot assign desktop icon to output: {error}");
            return;
        }
        // The old focused surface becomes invisible. Compositors own actual
        // keyboard focus; do not fake a keyboard enter on the new output.
        self.focused_icon = None;
        self.keyboard_icon_surface = None;
        self.reflow_icons();
        self.icon_position_dirty = true;
        self.save_icon_positions();
    }

    fn reset_icon_position(&mut self, layer_index: usize) {
        let Some(layer) = self.icon_layers.get(layer_index) else { return };
        let recipe_index = layer.recipe_index;
        let Some(name) = self.icon_output_name(layer_index) else { return };
        // The named layout is the only mutable target. Keep the recipe,
        // shortcuts on other displays, and cross-display ownership intact.
        match self.icon_outputs.reset_position(
            &name, &self.recipe.desktop_icons[..self.static_icon_count], recipe_index,
        ) {
            Ok(true) => {
                self.reflow_icons();
                self.icon_position_dirty = true;
                self.save_icon_positions();
            }
            Ok(false) => {}
            Err(error) => eprintln!("RicePlate: cannot reset icon position: {error}"),
        }
    }

    fn mirror_icon_on_all_outputs(&mut self, layer_index: usize) {
        let recipe_index = self.icon_layers[layer_index].recipe_index;
        if let Err(error) = self.icon_outputs.assign(
            &self.recipe.desktop_icons[..self.static_icon_count], recipe_index, None,
        ) {
            eprintln!("RicePlate: cannot restore mirrored desktop icon: {error}");
            return;
        }
        self.reflow_icons();
        self.icon_position_dirty = true;
        self.save_icon_positions();
    }

    fn reflow_icons(&mut self) {
        // A context menu is anchored to one physical output; hotplug and
        // icon position changes invalidate its coordinates and target.
        self.close_desktop_context();
        // Output reflow and icon dragging invalidate pending pointer timing.
        self.desktop_selection.cancel();
        // An advertised output without a shell surface must not swallow
        // shortcuts assigned to it: recover those on the primary instead.
        let connected: Vec<String> = self.icon_layers.iter()
            .filter_map(|layer| {
                let output = layer.bound_output.as_ref().or(self.primary_output.as_ref())
                    .or(layer.output.as_ref())?;
                self.logical_output_size(output)?;
                self.outputs.info(output)?.name
            })
            .collect();
        for index in 0..self.icon_layers.len() {
            let layer = &self.icon_layers[index];
            let output = layer.bound_output.as_ref().or(self.primary_output.as_ref())
                .or(layer.output.as_ref());
            let Some((width, height)) = output.and_then(|o| self.logical_output_size(o)) else {
                continue;
            };
            let name = self.icon_output_name(index);
            let mut local_icons = self.recipe.desktop_icons.clone();
            if let Some(positions) = name.as_deref().and_then(|name|
                self.icon_outputs.for_output(name, self.static_icon_count)) {
                for (icon, position) in local_icons.iter_mut().take(self.static_icon_count).zip(positions) {
                    (icon.x, icon.y) = (position.x, position.y);
                }
            }
            let visible: Vec<_> = (0..local_icons.len())
                .map(|icon| if icon < self.static_icon_count {
                    self.icon_outputs.visible_on(
                        icon, name.as_deref(), layer.bound_output.is_none(), &connected)
                } else {
                    layer.bound_output.is_none()
                }).collect();
            let placement = if let Some(composition) = &self.recipe.composition {
                desktop_layout::compose_visible(&local_icons, &visible, composition, width, height,
                    self.recipe.top, self.recipe.height,
                    self.recipe.compact.as_ref().map_or(720, |(threshold, _)| *threshold))
                    .0[layer.recipe_index]
            } else {
                desktop_layout::place_visible(&local_icons, &visible, width, height,
                    self.recipe.top, self.recipe.height)[layer.recipe_index]
            };
            let restored = {
                let layer = &mut self.icon_layers[index];
                if layer.placed == placement {
                    continue;
                }
                let restored = layer.placed.is_none() && placement.is_some();
                layer.placed = placement;
                if let Some((x, y)) = placement {
                    layer.surface.set_margin(y as i32, 0, 0, x as i32);
                } else {
                    // Keep the layer-shell role mapped: a null-buffer commit
                    // would permanently destroy it under the protocol. Park
                    // the icon beyond the output until room is available.
                    layer.surface.set_margin(
                        height as i32 + recipe::ICON_HEIGHT as i32,
                        0,
                        0,
                        width as i32 + recipe::ICON_WIDTH as i32,
                    );
                }
                layer.surface.commit();
                restored && layer.configured
            };
            if restored {
                self.redraw_icon(index);
            }
        }
        // No stale selection is retained after output loss or a compact
        // layout hides its icon. This also invalidates a pending double click.
        let visible: Vec<bool> = self.icon_layers.iter()
            .map(|layer| layer.placed.is_some()).collect();
        for changed in self.desktop_selection.retain_visible(&visible) {
            self.redraw_icon(changed);
        }
        for index in 0..self.widget_layers.len() {
            let layer = &self.widget_layers[index];
            let output = layer.bound_output.as_ref().or(self.primary_output.as_ref())
                .or(layer.output.as_ref());
            let Some((width, height)) = output.and_then(|o| self.logical_output_size(o)) else {
                continue;
            };
            let Some(composition) = self.recipe.composition.as_ref() else { break; };
            let name = output.and_then(|o| self.outputs.info(o)).and_then(|info| info.name);
            let mut local_icons = self.recipe.desktop_icons.clone();
            if let Some(positions) = name.as_deref().and_then(|name|
                self.icon_outputs.for_output(name, self.static_icon_count)) {
                for (icon, position) in local_icons.iter_mut().take(self.static_icon_count).zip(positions) {
                    (icon.x, icon.y) = (position.x, position.y);
                }
            }
            let visible: Vec<_> = (0..local_icons.len())
                .map(|icon| if icon < self.static_icon_count {
                    self.icon_outputs.visible_on(
                        icon, name.as_deref(), layer.bound_output.is_none(), &connected)
                } else {
                    layer.bound_output.is_none()
                }).collect();
            let placement = desktop_layout::compose_visible(
                &local_icons, &visible, composition, width, height, self.recipe.top, self.recipe.height,
                self.recipe.compact.as_ref().map_or(720, |(threshold, _)| *threshold),
            ).1[layer.recipe_index];
            let restored = {
                let layer = &mut self.widget_layers[index];
                if layer.placed == placement { continue; }
                let restored = layer.placed.is_none() && placement.is_some();
                layer.placed = placement;
                if let Some((x, y)) = placement {
                    layer.surface.set_margin(y as i32, 0, 0, x as i32);
                } else {
                    layer.surface.set_margin(height as i32 + recipe::DESKTOP_WIDGET_HEIGHT as i32,
                                             0, 0, width as i32 + recipe::DESKTOP_WIDGET_WIDTH as i32);
                }
                layer.surface.commit();
                restored && layer.configured
            };
            if restored { self.redraw_widget(index); }
        }
        if self.focused_widget.is_some_and(|index| self.widget_action(index).is_none()) {
            self.focused_widget = None;
            self.keyboard_widget_surface = None;
            self.pressed_widget = None;
            self.hovered_widget = None;
        }
    }

    fn grouped_tasks(&self) -> Vec<TaskGroup> {
        task_groups::group_windows(
            self.tasks
                .iter()
                .enumerate()
                .map(|(index, task)| WindowInfo {
                    index,
                    app_id: &task.app_id,
                    title: &task.title,
                    active: task.active,
                    ready: task.ready,
                }),
        )
    }

    /// The SNI connection is registered with calloop's fd source, never a
    /// polling timer. Fatal bus errors remove the source and leave the shell
    /// usable with a visually empty tray.
    fn refresh_tray(&mut self, qh: &QueueHandle<Self>) -> bool {
        let Some(host) = self.tray_host.as_mut() else { return false };
        if let Err(error) = host.process_events(
            |_, _, _| {},
            |error| eprintln!("RicePlate: SNI item error: {error}"),
            Some(Duration::ZERO),
        ) {
            eprintln!("RicePlate: SNI host disconnected: {error}");
            self.tray_host = None;
            self.tray_state = tray::State::default();
            self.set_tray_popup_visible(false, qh);
            self.request_redraw(qh);
            return false;
        }
        let updated = tray::State::from_items(host.get_all_items());
        if self.tray_menu_state.visible && !self.tray_menu_state.is_local() {
            let bus_name = self.tray_menu_state.bus_name.clone();
            let stale = if let Some(item) = host.get_item(&bus_name) {
                let removed = self.tray_menu_state.sync(&item.menu);
                if !removed.contains(&self.tray_menu_state.root_id) {
                    for id in &removed {
                        if let Err(error) = host.menu_closed(&bus_name, *id) {
                            eprintln!("RicePlate: SNI menu close failed: {error}");
                        }
                    }
                }
                removed.contains(&self.tray_menu_state.root_id)
            } else { true };
            if stale {
                self.set_tray_popup_visible(false, qh);
            } else {
                self.redraw_tray_popup();
            }
        }
        if self.tray_state != updated {
            self.tray_state = updated;
            if self.tray_popup_state.visible {
                if self.tray_state.overflow_count() == 0 {
                    self.set_tray_popup_visible(false, qh);
                } else {
                    self.tray_popup_state.select(0, self.tray_state.entries.len());
                    self.redraw_tray_popup();
                }
            }
            self.request_redraw(qh);
        }
        true
    }

    fn tray_screen_position(&self, surface: &wl_surface::WlSurface,
                            position: (f64, f64)) -> (i32, i32) {
        let popup = self.tray_popup_layer.as_ref().is_some_and(|layer|
            layer.surface.wl_surface() == surface)
            || self.tray_popup_mirrors.iter().any(|layer|
                layer.surface.wl_surface() == surface);
        let output = self.mirrors.iter().find(|panel|
            panel.surface.wl_surface() == surface).map(|panel| &panel.output)
            .or_else(|| self.tray_popup_mirrors.iter().find(|layer|
                layer.surface.wl_surface() == surface).and_then(|layer| layer.output.as_ref()))
            .or(self.primary_output.as_ref());
        let Some(output) = output else { return (0, 0); };
        let Some(info) = self.outputs.info(output) else { return (0, 0); };
        let Some((output_width, output_height)) = self.logical_output_size(output) else {
            return (0, 0);
        };
        tray::screen_coords(info.logical_position.unwrap_or((0, 0)),
                            (output_width, output_height), self.recipe.height,
                            self.recipe.top, popup, position)
    }

    fn tray_popup_open(&self) -> bool {
        self.tray_popup_state.visible || self.tray_menu_state.visible
    }

    /// Open a real native Wayland surface for XP's own status icons. The SNI
    /// host is deliberately not involved: local menu rows never emit D-Bus.
    fn open_luna_status_menu(&mut self, widget: Widget,
                             source: &wl_surface::WlSurface, qh: &QueueHandle<Self>) {
        if self.recipe.id != "xp-luna-columns" { return; }
        let Some(target) = self.tray_popup_target(source) else { return; };
        let Some((title, rows)) = luna_status_rows(widget, &self.system_status, &self.power)
            else { return; };
        let mut popup = tray::MenuPopup::default();
        if !popup.open_local(title, rows) { return; }
        self.set_tray_popup_visible(false, qh);
        self.tray_menu_state = popup;
        self.show_tray_surface_at(target, qh);
    }

    fn launch_luna_settings(&self, page: &str) {
        // Only hard-coded menu actions reach this path. The overview has no
        // --page argument; notification-area shortcuts keep their deep links.
        let mut command = Command::new("ricebowl");
        command.args(["de", "settings", "--luna"]);
        if page != "home" {
            command.args(["--page", page]);
        }
        if let Err(error) = command.spawn() {
            eprintln!("RicePlate: cannot open Luna settings page {page}: {error}");
        }
    }

    fn activate_luna_status_action(&mut self, id: i32, qh: &QueueHandle<Self>) {
        match id {
            101 => self.activate_action("wifi-toggle", qh),
            103 => self.activate_action("audio-mute", qh),
            104 => self.activate_action("audio-down", qh),
            105 => self.activate_action("audio-up", qh),
            100 => self.launch_luna_settings("network"),
            102 => self.launch_luna_settings("audio"),
            106 => self.launch_luna_settings("power"),
            107 => self.launch_luna_settings("timezone"),
            108 => self.launch_luna_settings("taskbar"),
            _ => {}
        }
    }

    fn tray_popup_target(&self, source: &wl_surface::WlSurface)
        -> Option<wl_surface::WlSurface>
    {
        if self.tray_popup_layer.as_ref().is_some_and(|layer|
            layer.surface.wl_surface() == source)
            || self.tray_popup_mirrors.iter().any(|layer|
                layer.surface.wl_surface() == source) {
            return Some(source.clone());
        }
        if self.layer.wl_surface() == source {
            return self.tray_popup_layer.as_ref()
                .map(|layer| layer.surface.wl_surface().clone());
        }
        let output = self.mirrors.iter().find(|panel|
            panel.surface.wl_surface() == source).map(|panel| &panel.output)?;
        self.tray_popup_mirrors.iter().find(|layer|
            layer.output.as_ref() == Some(output))
            .map(|layer| layer.surface.wl_surface().clone())
    }

    fn activate_tray_item(&mut self, slot: usize, button: u32, position: (i32, i32),
                          source: &wl_surface::WlSurface, qh: &QueueHandle<Self>) {
        if self.tray_state.overflow_count() > 0 &&
            slot == tray::VISIBLE_ITEMS - 1 { return; }
        if self.tray_state.item_at(slot).is_none() { return; }
        self.activate_tray_entry(slot, button, position, source, qh);
    }

    fn activate_tray_entry(&mut self, index: usize, button: u32, position: (i32, i32),
                           source: &wl_surface::WlSurface, qh: &QueueHandle<Self>) {
        let Some(entry) = self.tray_state.entries.get(index).cloned() else { return };
        if button == BTN_RIGHT || entry.is_menu {
            let mut popup = tray::MenuPopup::default();
            let has_menu = self.tray_host.as_ref().and_then(|host|
                host.get_item(&entry.bus_name)).is_some_and(|item|
                popup.open(&entry.bus_name, &entry.title, &item.menu));
            if has_menu {
                if let Some(target) = self.tray_popup_target(source) {
                    self.set_tray_popup_visible(false, qh);
                    self.tray_menu_state = popup;
                    self.show_tray_surface_at(target, qh);
                    if let Some(host) = self.tray_host.as_mut() {
                        if let Err(error) = host.menu_opened(&entry.bus_name,
                                                             self.tray_menu_state.root_id) {
                            eprintln!("RicePlate: SNI menu opening failed: {error}");
                        }
                    }
                    return;
                }
            }
        }
        let Some(host) = self.tray_host.as_mut() else { return };
        let result = if button == BTN_RIGHT || entry.is_menu {
            host.item_context_menu(&entry.bus_name, position.0, position.1)
        } else {
            host.item_activate(&entry.bus_name, position.0, position.1)
        };
        if let Err(error) = result {
            eprintln!("RicePlate: SNI item action failed: {error}");
        }
    }

    fn set_tray_popup_visible(&mut self, visible: bool, qh: &QueueHandle<Self>) {
        if !visible {
            if self.tray_menu_state.visible {
                if let Some(host) = self.tray_host.as_mut() {
                    for id in self.tray_menu_state.opened_ids().into_iter().rev() {
                        if let Err(error) = host.menu_closed(&self.tray_menu_state.bus_name, id) {
                            eprintln!("RicePlate: SNI menu close failed: {error}");
                        }
                    }
                }
            }
            self.tray_menu_state.close();
            self.tray_popup_state.close();
            self.tray_popup_focused = false;
            self.active_tray_popup = None;
            for layer in self.tray_popup_layer.iter().chain(self.tray_popup_mirrors.iter()) {
                layer.surface.set_keyboard_interactivity(KeyboardInteractivity::None);
                layer.surface.set_margin(
                    if self.recipe.top { self.recipe.height as i32 + 8 } else { 0 },
                    MAX_WIDTH as i32,
                    if self.recipe.top { 0 } else { self.recipe.height as i32 + 8 }, 0,
                );
                layer.surface.commit();
            }
            self.maybe_collapse_luna_panel(qh);
            return;
        }
        if let Some(surface) = self.tray_popup_layer.as_ref()
            .map(|layer| layer.surface.wl_surface().clone()) {
            self.show_tray_popup_at(surface, qh);
        }
    }

    fn show_tray_popup_at(&mut self, surface: wl_surface::WlSurface,
                          qh: &QueueHandle<Self>) {
        if self.tray_state.overflow_count() == 0 || !self.tray_popup_layer.iter()
            .chain(self.tray_popup_mirrors.iter())
            .any(|layer| layer.surface.wl_surface() == &surface) { return; }
        self.set_tray_popup_visible(false, qh);
        self.tray_popup_state.open(self.tray_state.entries.len());
        self.show_tray_surface_at(surface, qh);
    }

    fn show_tray_surface_at(&mut self, surface: wl_surface::WlSurface,
                            qh: &QueueHandle<Self>) {
        if self.menu_state.visible { self.set_menu_visible(false, qh); }
        if self.calendar_state.visible { self.set_calendar_visible(false, qh); }
        self.tray_popup_focused = false;
        self.active_tray_popup = Some(surface.clone());
        for layer in self.tray_popup_layer.iter().chain(self.tray_popup_mirrors.iter()) {
            let active = layer.surface.wl_surface() == &surface;
            layer.surface.set_keyboard_interactivity(if active {
                KeyboardInteractivity::OnDemand
            } else { KeyboardInteractivity::None });
            layer.surface.set_margin(
                if self.recipe.top { self.recipe.height as i32 + 8 } else { 0 },
                if active { 8 } else { MAX_WIDTH as i32 },
                if self.recipe.top { 0 } else { self.recipe.height as i32 + 8 }, 0,
            );
            layer.surface.commit();
        }
        self.redraw_tray_popup();
    }

    fn toggle_tray_popup_for_panel(&mut self, mirror: Option<usize>,
                                    qh: &QueueHandle<Self>) {
        let target = match mirror {
            Some(index) => self.mirrors.get(index).and_then(|panel|
                self.tray_popup_mirrors.iter().find(|popup|
                    popup.output.as_ref() == Some(&panel.output)))
                .map(|popup| popup.surface.wl_surface().clone()),
            None => self.tray_popup_layer.as_ref()
                .map(|popup| popup.surface.wl_surface().clone()),
        };
        let Some(target) = target else { return; };
        if self.tray_popup_open() && self.active_tray_popup.as_ref() == Some(&target) {
            self.set_tray_popup_visible(false, qh);
        } else {
            self.show_tray_popup_at(target, qh);
        }
    }

    fn choose_tray_menu_row(&mut self, index: usize, qh: &QueueHandle<Self>) {
        let choice = self.tray_menu_state.choice(index);
        if self.tray_menu_state.is_local() {
            if let TrayMenuChoice::Click(id) = choice {
                self.set_tray_popup_visible(false, qh);
                self.activate_luna_status_action(id, qh);
            }
            return;
        }
        match choice {
            TrayMenuChoice::None => return,
            TrayMenuChoice::Open(id) => {
                if let Some(host) = self.tray_host.as_mut() {
                    if let Err(error) = host.menu_opened(&self.tray_menu_state.bus_name, id) {
                        eprintln!("RicePlate: SNI submenu opening failed: {error}");
                        self.set_tray_popup_visible(false, qh);
                        return;
                    }
                }
                self.redraw_tray_popup();
            }
            TrayMenuChoice::Click(id) => {
                if let Some(host) = self.tray_host.as_mut() {
                    if let Err(error) = host.menu_clicked(&self.tray_menu_state.bus_name, id) {
                        eprintln!("RicePlate: SNI menu activation failed: {error}");
                    }
                }
                self.set_tray_popup_visible(false, qh);
            }
        }
    }

    fn back_tray_menu(&mut self, qh: &QueueHandle<Self>) {
        if let Some(closed) = self.tray_menu_state.back() {
            if let Some(host) = self.tray_host.as_mut() {
                if let Err(error) = host.menu_closed(&self.tray_menu_state.bus_name, closed) {
                    eprintln!("RicePlate: SNI submenu close failed: {error}");
                }
            }
            self.redraw_tray_popup();
        } else {
            self.set_tray_popup_visible(false, qh);
        }
    }

    fn redraw_tray_popup(&mut self) {
        if !self.tray_popup_open() { return; }
        let Some(active) = self.active_tray_popup.as_ref() else { return; };
        let layer = self.tray_popup_layer.as_mut().filter(|layer|
            layer.surface.wl_surface() == active)
            .or_else(|| self.tray_popup_mirrors.iter_mut().find(|layer|
                layer.surface.wl_surface() == active));
        let Some(layer) = layer else { return; };
        if !layer.configured { return; }
        if layer.pool.is_none() {
            let bytes = (tray::POPUP_WIDTH * tray::POPUP_HEIGHT * 4 * 3) as usize;
            match SlotPool::new(bytes, &self.shm) {
                Ok(pool) => layer.pool = Some(pool),
                Err(error) => {
                    eprintln!("RicePlate: tray popup allocation failed: {error}");
                    return;
                }
            }
        }
        let Some(pool) = layer.pool.as_mut() else { return; };
        let (buffer, canvas) = match pool.create_buffer(
            tray::POPUP_WIDTH as i32, tray::POPUP_HEIGHT as i32,
            (tray::POPUP_WIDTH * 4) as i32, wl_shm::Format::Argb8888,
        ) {
            Ok(result) => result,
            Err(error) => {
                eprintln!("RicePlate: tray popup buffer unavailable: {error}");
                return;
            }
        };
        if self.tray_menu_state.visible {
            paint_tray_menu(canvas, &self.recipe, &self.tray_menu_state);
        } else {
            paint_tray_popup(canvas, &self.recipe, &self.tray_state, &self.tray_popup_state);
        }
        let surface = layer.surface.wl_surface();
        surface.damage_buffer(0, 0, tray::POPUP_WIDTH as i32, tray::POPUP_HEIGHT as i32);
        if let Err(error) = buffer.attach_to(surface) {
            eprintln!("RicePlate: tray popup attach failed: {error}");
            return;
        }
        layer.surface.commit();
    }

    fn request_redraw(&mut self, qh: &QueueHandle<Self>) {
        if self.frame.invalidate() { self.redraw(qh); }
        for index in 0..self.mirrors.len() {
            if self.mirrors[index].frame.invalidate() {
                self.redraw_mirror(index, qh);
            }
        }
    }

    fn reveal_task(&mut self, index: usize) {
        let groups = self.grouped_tasks();
        let Some(group_index) = groups
            .iter()
            .position(|group| group.members.contains(&index))
        else {
            return;
        };
        let Some(view) =
            recipe::task_view(&self.recipe, self.width, groups.len(), self.task_offset)
        else {
            return;
        };
        if group_index < view.start {
            self.task_offset = group_index;
        } else if group_index >= view.start + view.slots {
            self.task_offset = group_index + 1 - view.slots;
        }
        for mirror in &mut self.mirrors {
            if let Some(view) = recipe::task_view(
                &self.recipe, mirror.width, groups.len(), mirror.task_offset,
            ) {
                if group_index < view.start { mirror.task_offset = group_index; }
                else if group_index >= view.start + view.slots {
                    mirror.task_offset = group_index + 1 - view.slots;
                }
            }
        }
    }

    fn redraw(&mut self, qh: &QueueHandle<Self>) {
        if !self.configured || self.width == 0 || self.height == 0 {
            return;
        }
        let paint_started = self.trace_frames.then(Instant::now);
        let width = self.width;
        let height = self.height;
        let groups = self.grouped_tasks();
        self.cached_task_group_count = groups.len();
        let selected = if self.focused_panel.as_ref() == Some(self.layer.wl_surface()) {
            self.focused_target
        } else { None };
        let surface = self.layer.wl_surface();
        let visual = self.panel_pointer_visual(surface);
        let stride = (width * 4) as i32;
        let pool = self
            .pool
            .as_mut()
            .expect("configured surface has a memory pool");
        let (buffer, canvas) = match pool.create_buffer(
            width as i32,
            height as i32,
            stride,
            wl_shm::Format::Argb8888,
        ) {
            Ok(result) => result,
            Err(error) => {
                // Compositor may still own the last buffer; retry on its next
                // frame instead of killing the shell during a burst of events.
                eprintln!("RicePlate: deferring busy Wayland buffer: {error}");
                surface.frame(qh, FrameCallbackData(surface.clone()));
                self.frame.buffer_busy();
                self.layer.commit();
                return;
            }
        };
        paint_panel_pointer(canvas, width, height, &self.recipe, &groups,
                    &self.clock, &self.power, &self.system_status, &self.tray_state,
                    self.task_offset, selected, self.control_pending, self.control_result,
                    visual);
        surface.damage_buffer(0, 0, width as i32, height as i32);
        if let Err(error) = buffer.attach_to(surface) {
            eprintln!("RicePlate: failed to attach Wayland buffer: {error}");
            self.closed = true;
            return;
        }
        surface.frame(qh, FrameCallbackData(surface.clone()));
        self.frame.submitted();
        self.layer.commit();
        if let Some(started) = paint_started {
            let stats = self.frame.stats();
            eprintln!("RicePlate frame=primary paint_us={} commits={} invalidations={} coalesced={} shm_retries={}",
                started.elapsed().as_micros(), stats.commits, stats.invalidations,
                stats.coalesced, stats.busy_retries);
        }
    }
}

#[cfg(test)]
fn paint_panel(canvas: &mut [u8], width: u32, height: u32,
               style: &PanelStyle, groups: &[TaskGroup], clock: &str,
               power: &PowerStatus, status: &SystemStatus, tray_state: &tray::State, offset: usize,
               selected: Option<KeyboardTarget>, pending: Option<ControlAction>,
               result: Option<(ControlAction, bool)>) {
    paint_panel_pointer(canvas, width, height, style, groups, clock,
                        power, status, tray_state, offset, selected, pending, result,
                        PanelPointerVisual::default());
}

fn paint_panel_pointer(canvas: &mut [u8], width: u32, height: u32,
               style: &PanelStyle, groups: &[TaskGroup], clock: &str,
               power: &PowerStatus, status: &SystemStatus, tray_state: &tray::State, offset: usize,
               selected: Option<KeyboardTarget>, pending: Option<ControlAction>,
               result: Option<(ControlAction, bool)>, visual: PanelPointerVisual) {
    // Unrelated recipes and the original xp-luna preview retain byte-identical
    // historical framebuffers: native pointer effects are strictly opt in.
    let visual = if style.id == "xp-luna-columns" {
        visual
    } else { PanelPointerVisual::default() };
    if style.id == "xp-luna-columns" && height < style.height {
        // The auto-hidden reveal strip deliberately has no controls and
        // cannot run the full taskbar painter at a three-pixel height.
        for pixel in canvas.chunks_exact_mut(4) {
            pixel.copy_from_slice(&0xff4c_8beb_u32.to_le_bytes());
        }
        return;
    }
    let layout = recipe::layout(style, width, groups.len());
    panel_chrome::background(canvas, width, height, style, &layout);
    for placed in layout {
        match placed.widget {
            Widget::Launcher => {
                if let Some(launcher) = style.launcher.as_ref() {
                    panel_chrome::launcher_visual(canvas, width, height, placed.x,
                                                  placed.width, launcher,
                                                  visual.button(Hit::Launcher));
                    if style.id == "xp-luna-columns" {
                        panel_chrome::luna_launcher_finish(
                            canvas, width, height, placed.x, placed.width,
                            visual.button(Hit::Launcher));
                    }
                } else {
                    fill_rect(canvas, width, height, placed.x, 0, placed.width, height,
                              style.active);
                }
                let launcher_label = style.launcher.as_ref().map_or("Apps", |item| item.label.as_str());
                let label_width = rice_text_width(launcher_label, style);
                let label_x = if style.launcher.is_some()
                    && placed.width >= label_width.saturating_add(35) {
                    placed.x + 30 + (placed.width - 30 - label_width) / 2
                } else {
                    placed.x + placed.width.saturating_sub(label_width) / 2
                };
                draw_rice_text(canvas, width, height,
                          label_x,
                          height.saturating_sub(8 * style.font_scale) / 2
                              + u32::from(visual.button(Hit::Launcher)
                                  == panel_chrome::ButtonVisual::Pressed),
                          launcher_label,
                          style.launcher.as_ref().map_or(style.foreground, |item| item.foreground),
                          style);
                if selected == Some(KeyboardTarget::Launcher) {
                    paint_focus_border(canvas, width, height, placed.x, placed.width,
                                       if style.focus != 0 { style.focus } else { style.foreground });
                }
            }
            Widget::Action(index) => {
                if let Some(action) = style.actions.get(index as usize) {
                    if style.id == "xp-luna-columns" && matches!(action.id.as_str(),
                        "applications" | "terminal" | "show-desktop") {
                        // Actual 32px input targets with original lightweight
                        // quick-launch glyphs; no vendor artwork or dummy icon.
                        let left = placed.x + 2;
                        fill_rounded_rect(canvas, width, height, left, 5, 28,
                                          height.saturating_sub(10), 3, 0xff1b_4a9f);
                        fill_rect(canvas, width, height, left + 2, 7, 24, 1, 0xffa4_d7ff);
                        match action.id.as_str() {
                            "applications" => {
                                fill_rect(canvas, width, height, left + 7, 12, 14, 12, 0xfff2_e0a3);
                                fill_rect(canvas, width, height, left + 8, 10, 6, 4, 0xffff_f0bd);
                                fill_rect(canvas, width, height, left + 9, 17, 11, 1, 0xffc7_913a);
                            }
                            "terminal" => {
                                fill_rect(canvas, width, height, left + 6, 11, 17, 15, 0xffd3_e8fa);
                                fill_rect(canvas, width, height, left + 8, 13, 13, 11, 0xff1e_3250);
                                draw_text(canvas, width, height, left + 9, 15, ">", 0xffe5_faff);
                            }
                            _ => {
                                fill_rect(canvas, width, height, left + 6, 12, 17, 12, 0xfff3_faff);
                                fill_rect(canvas, width, height, left + 7, 13, 15, 8, 0xff59_a6e2);
                                fill_rect(canvas, width, height, left + 12, 25, 6, 2, 0xffd6_e7fc);
                                fill_rect(canvas, width, height, left + 9, 27, 12, 1, 0xffb9_cedf);
                            }
                        }
                        if selected == Some(KeyboardTarget::Action(index)) {
                            paint_focus_border(canvas, width, height, placed.x, placed.width,
                                if style.focus != 0 { style.focus } else { style.foreground });
                        }
                        continue;
                    }
                    let control = action.control.then(|| ControlAction::from_id(&action.id)).flatten();
                    let feedback = control.map(|item|
                        ControlFeedback::snapshot(item, status, pending, result, true));
                    let available = feedback.is_none_or(ControlFeedback::is_actionable);
                    if available {
                        fill_rounded_rect(canvas, width, height, placed.x + 2, 3,
                            placed.width.saturating_sub(4), height.saturating_sub(6),
                            style.task_radius, style.active);
                    }
                    let second_line = control.zip(feedback)
                        .map(|(item, state)| state.panel_caption(item, status));
                    draw_rice_text(canvas, width, height, placed.x + style.label_padding + 4,
                        if second_line.is_some() { height.saturating_sub(20 * style.font_scale) / 2 }
                        else { height.saturating_sub(8 * style.font_scale) / 2 },
                        &action.label,
                        if available || style.disabled == 0 { style.foreground } else { style.disabled }, style);
                    if let Some(value) = second_line {
                        draw_rice_text(canvas, width, height, placed.x + style.label_padding + 4,
                                  height / 2 + 2, &value, style.foreground, style);
                    }
                    if selected == Some(KeyboardTarget::Action(index)) {
                        paint_focus_border(canvas, width, height, placed.x, placed.width,
                                           if style.focus != 0 { style.focus } else { style.foreground });
                    }
                }
            }
            Widget::Tasks => {
                let Some(view) = recipe::task_view(style, width, groups.len(), offset) else {
                    continue;
                };
                for (index, group) in groups.iter().skip(view.start).take(view.slots).enumerate() {
                    let consumed = (index as u32) * view.cell_width;
                    let x = placed.x + consumed;
                    let cell_width = if index + 1 == view.slots {
                        view.content_width - consumed
                    } else {
                        view.cell_width
                    };
                    let task_visual = visual.button(Hit::Task(view.start + index));
                    panel_chrome::task_button_visual(canvas, width, height, x, cell_width,
                                                     group.active, style, task_visual);
                    let label = fitted_task_label(group, cell_width, style);
                    draw_rice_text(canvas, width, height, x + 10,
                              height.saturating_sub(8 * style.font_scale) / 2
                                  + u32::from(task_visual
                                      == panel_chrome::ButtonVisual::Pressed),
                              &label, style.foreground, style);
                    if selected == Some(KeyboardTarget::Task(view.start + index)) {
                        paint_focus_border(canvas, width, height, x, cell_width,
                                           if style.focus != 0 { style.focus } else { style.foreground });
                    }
                }
                if view.prev {
                    draw_text(canvas, width, height, placed.x + view.content_width + 8,
                              height / 2 - 4, "<", style.foreground);
                }
                if view.next {
                    draw_text(canvas, width, height, placed.x + view.content_width + 32,
                              height / 2 - 4, ">", style.foreground);
                }
            }
            Widget::Clock => {
                // Center the shorter/longer Luna time inside its reserved slot.
                // The previous 24h 5x8 width remains unchanged for other rices.
                let label_width = if style.id == "xp-luna-columns" {
                    rice_text_width(clock, style)
                } else {
                    40 * style.font_scale
                };
                draw_rice_text(canvas, width, height,
                          placed.x + placed.width.saturating_sub(label_width) / 2,
                          height.saturating_sub(8 * style.font_scale) / 2,
                          clock, style.foreground, style);
            }
            Widget::Battery => {
                let label = power.label();
                if style.id == "xp-luna-columns" {
                    panel_chrome::status_icon(canvas, width, height, placed.x, 28,
                        Widget::Battery, matches!(power, PowerStatus::NotPresent | PowerStatus::Unknown));
                    draw_rice_text(canvas, width, height, placed.x + 30,
                        height.saturating_sub(8 * style.font_scale) / 2,
                        &label, style.foreground, style);
                } else {
                    draw_rice_text(canvas, width, height,
                        placed.x + placed.width.saturating_sub(text_pixel_width(&label, style.font_scale)) / 2,
                        height.saturating_sub(8 * style.font_scale) / 2,
                        &label, style.foreground, style);
                }
            }
            Widget::Network | Widget::Audio => {
                if style.id == "xp-luna-columns" {
                    use system_status::Network;
                    let unavailable = if placed.widget == Widget::Network {
                        matches!(status.network, Network::Offline | Network::Unavailable)
                    } else {
                        matches!(status.audio, Audio::Muted | Audio::Unavailable)
                    };
                    panel_chrome::status_icon(canvas, width, height, placed.x,
                                              placed.width, placed.widget, unavailable);
                    continue;
                }
                let label = if placed.widget == Widget::Network {
                    status.network.label().to_owned()
                } else {
                    status.audio.label()
                };
                draw_rice_text(canvas, width, height,
                          placed.x + placed.width.saturating_sub(text_pixel_width(&label, style.font_scale)) / 2,
                          height.saturating_sub(8 * style.font_scale) / 2,
                          &label, style.foreground, style);
            }
            Widget::Tray => {
                for (index, entry) in tray_state.entries.iter()
                    .take(tray_state.visible_count()).enumerate() {
                    let x = placed.x + index as u32 * tray::SLOT_WIDTH;
                    if entry.needs_attention {
                        fill_rounded_rect(canvas, width, height, x, 3,
                            tray::SLOT_WIDTH, height.saturating_sub(6),
                            style.task_radius, style.active);
                    }
                    if let Some(icon) = &entry.icon {
                        tray::paint_icon(canvas, width, height, x + 4,
                            height.saturating_sub(20) / 2, icon);
                    } else {
                        // Missing pixmap: label fallback is explicit, no
                        // guessed icon assets or untrusted path traversal.
                        let symbol = entry.title.chars().find(|c| c.is_ascii_alphanumeric())
                            .map(|c| c.to_ascii_uppercase()).unwrap_or('?');
                        draw_text(canvas, width, height, x + 10,
                            height.saturating_sub(8) / 2, &symbol.to_string(), style.foreground);
                    }
                }
                let overflow = tray_state.overflow_count();
                if overflow > 0 {
                    if style.id == "xp-luna-columns" {
                        panel_chrome::tray_overflow_chevron(canvas, width, height,
                                                           placed.x + tray::WIDTH - 28);
                    } else {
                        draw_text(canvas, width, height, placed.x + tray::WIDTH - 27,
                            height.saturating_sub(8) / 2, &format!("+{overflow}"),
                            style.foreground);
                    }
                }
                if let Some(KeyboardTarget::Tray(slot)) = selected {
                    let slots = tray_state.visible_count() +
                        usize::from(tray_state.overflow_count() > 0);
                    if slot < slots {
                        paint_focus_border(canvas, width, height,
                            placed.x + slot as u32 * tray::SLOT_WIDTH,
                            tray::SLOT_WIDTH,
                            if style.focus != 0 { style.focus } else { style.foreground });
                    }
                }
            }
            Widget::Gap(_) => {}
            Widget::Divider(_) => {
                let line_height = height.saturating_sub(16);
                fill_rect(canvas, width, height, placed.x + placed.width / 2,
                          (height - line_height) / 2, 1, line_height, style.foreground);
            }
            Widget::Label(index) => {
                if let Some(label) = style.labels.get(index as usize) {
                    draw_rice_text(canvas, width, height, placed.x + style.label_padding,
                              height.saturating_sub(8 * style.font_scale) / 2,
                              label, style.foreground, style);
                }
            }
        }
    }
}

fn paint_osd(canvas: &mut [u8], style: &PanelStyle, notice: &osd::Notice) {
    let width = osd::WIDTH;
    let height = osd::HEIGHT;
    // Opaque, theme-consistent background; no compositor blur dependency.
    for pixel in canvas.chunks_exact_mut(4) {
        pixel.copy_from_slice(&style.background.to_le_bytes());
    }
    fill_rect(canvas, width, height, 0, 0, 4, height, style.active);
    draw_auxiliary_text(canvas, width, height, 16, 10, notice.title, style.foreground, style);
    draw_auxiliary_text(canvas, width, height, 16, 29, &notice.value, style.foreground, style);
    if let Some(percent) = notice.fill {
        fill_rect(canvas, width, height, 16, 54, width - 32, 5, style.active);
        fill_rect(canvas, width, height, 16, 54,
                  (width - 32) * u32::from(percent) / 100, 5, style.foreground);
    }
}

fn paint_tray_popup(canvas: &mut [u8], style: &PanelStyle,
                    tray_state: &tray::State, popup: &tray::Popup) {
    let width = tray::POPUP_WIDTH;
    let height = tray::POPUP_HEIGHT;
    for pixel in canvas.chunks_exact_mut(4) {
        pixel.copy_from_slice(&style.background.to_le_bytes());
    }
    fill_rect(canvas, width, height, 0, 0, width, 36, style.active);
    draw_text(canvas, width, height, 12, 13,
              &format!("Tray icons ({})", tray_state.entries.len()), style.foreground);
    draw_text(canvas, width, height, width - 24, 13, "X", style.foreground);
    for (row, entry) in tray_state.entries.iter().skip(popup.first)
        .take(tray::POPUP_ROWS).enumerate() {
        let top = tray::POPUP_ROW_TOP + row as u32 * tray::POPUP_ROW_HEIGHT;
        if popup.selected == popup.first + row {
            fill_rounded_rect(canvas, width, height, 6, top + 1,
                width - 12, tray::POPUP_ROW_HEIGHT - 2, style.task_radius, style.active);
        }
        if let Some(icon) = &entry.icon {
            tray::paint_icon(canvas, width, height, 12, top + 5, icon);
        } else {
            let initial = entry.title.chars().find(|c| c.is_ascii_alphanumeric())
                .map(|c| c.to_ascii_uppercase()).unwrap_or('?');
            draw_text(canvas, width, height, 18, top + 10,
                      &initial.to_string(), style.foreground);
        }
        let title: String = entry.title.chars().take(26).collect();
        draw_text(canvas, width, height, 42, top + 11, &title, style.foreground);
        if entry.needs_attention {
            fill_rect(canvas, width, height, width - 12, top + 10, 4, 9,
                      style.foreground);
        }
    }
    let footer_top = 201;
    fill_rect(canvas, width, height, 0, footer_top, width, 1, style.active);
    let previous = popup.first > 0;
    let next = popup.first + tray::POPUP_ROWS < tray_state.entries.len();
    draw_text(canvas, width, height, 12, 216,
              if previous { "< Previous" } else { "  First page" }, style.foreground);
    draw_text(canvas, width, height, 169, 216,
              if next { "Next >" } else { "Last page" }, style.foreground);
}

/// XP notification-area menus use the same on-demand native popup as
/// StatusNotifier items, but with strictly local and capability-gated actions.
fn luna_status_rows(widget: Widget, status: &SystemStatus, power: &PowerStatus)
    -> Option<(&'static str, Vec<tray::MenuRow>)>
{
    let row = |id: i32, label: String, enabled: bool, checked: bool| tray::MenuRow {
        id, label, enabled,
        kind: tray::MenuKind::Action { checked, radio: false },
    };
    let available_audio = status.audio != Audio::Unavailable;
    match widget {
        Widget::Network => Some(("Network Connections", vec![
            row(0, format!("Status: {}", status.network.label()), false, false),
            row(101, format!("Turn Wi-Fi {}", if status.wifi == system_status::WifiRadio::Enabled {
                "off" } else { "on" }),
                ControlAction::WifiToggle.available(status),
                status.wifi == system_status::WifiRadio::Enabled),
            row(100, "Network Connections...".into(), true, false),
        ])),
        Widget::Audio => Some(("Volume Control", vec![
            row(0, format!("Volume: {}", status.audio.label()), false, false),
            row(103, "Mute".into(), available_audio, status.audio == Audio::Muted),
            row(104, "Volume Down".into(), available_audio, false),
            row(105, "Volume Up".into(), available_audio, false),
            row(102, "Audio Properties...".into(), true, false),
        ])),
        Widget::Battery => Some(("Power Meter", vec![
            row(0, format!("Battery: {}", power.label()), false, false),
            row(106, "Power Options...".into(), true, false),
        ])),
        Widget::Clock => Some(("Date and Time", vec![
            row(107, "Adjust Date/Time...".into(), true, false),
            row(108, "Taskbar Properties...".into(), true, false),
        ])),
        _ => None,
    }
}

fn paint_tray_menu(canvas: &mut [u8], style: &PanelStyle, popup: &tray::MenuPopup) {
    let (width, height) = (tray::POPUP_WIDTH, tray::POPUP_HEIGHT);
    let luna = style.id == "xp-luna-columns";
    let bg = if luna { 0xfff8_f6ee } else { style.background };
    let fg = if luna { 0xff20_2020 } else { style.foreground };
    let header = if luna { 0xff1a_56b0 } else { style.active };
    let header_fg = if luna { 0xffff_ffff } else { style.foreground };
    for pixel in canvas.chunks_exact_mut(4) {
        pixel.copy_from_slice(&bg.to_le_bytes());
    }
    fill_rect(canvas, width, height, 0, 0, width, 36, header);
    if luna {
        fill_rect(canvas, width, height, 0, 0, 2, height, 0xff0b_387e);
        fill_rect(canvas, width, height, width - 2, 0, 2, height, 0xff0b_387e);
        fill_rect(canvas, width, height, 0, height - 2, width, 2, 0xff0b_387e);
        fill_rect(canvas, width, height, 4, 36, width - 8, 2, 0xffa5_c9f2);
    }
    if popup.parent_id() != popup.root_id {
        draw_text(canvas, width, height, 12, 13, "<", header_fg);
    }
    let header: String = popup.title.chars().take(if popup.parent_id() == popup.root_id {
        24
    } else { 20 }).collect();
    draw_text(canvas, width, height, if popup.parent_id() == popup.root_id { 12 } else { 36 },
              13, &header, header_fg);
    draw_text(canvas, width, height, width - 24, 13, "X", header_fg);
    for (index, row) in popup.rows().iter().enumerate().skip(popup.first)
        .take(tray::POPUP_ROWS) {
        let top = tray::POPUP_ROW_TOP + (index - popup.first) as u32 * tray::POPUP_ROW_HEIGHT;
        if matches!(&row.kind, tray::MenuKind::Separator) {
            fill_rect(canvas, width, height, 12, top + 14, width - 24, 1, style.active);
            continue;
        }
        let selected = index == popup.selected && row.selectable();
        if selected {
            fill_rounded_rect(canvas, width, height, 6, top + 1, width - 12,
                              tray::POPUP_ROW_HEIGHT - 2, if luna { 2 } else { style.task_radius },
                              if luna { 0xff31_6ac5 } else if style.hover != 0 {
                                  style.hover } else { style.active });
        }
        let marker = match &row.kind {
            tray::MenuKind::Action { checked: true, radio: true } => "*",
            tray::MenuKind::Action { checked: true, .. } => "x",
            _ => "",
        };
        draw_text(canvas, width, height, 12, top + 11, marker,
                  if luna && selected { header_fg } else { fg });
        let label: String = row.label.chars().take(25).collect();
        let color = if !row.enabled && luna { 0xff91_9191 }
        else if row.enabled && luna && selected { header_fg }
        else if row.enabled { fg }
        else if style.disabled != 0 { style.disabled } else {
            let fg = fg.to_le_bytes();
            let bg = bg.to_le_bytes();
            u32::from_le_bytes([
                ((u16::from(fg[0]) + u16::from(bg[0])) / 2) as u8,
                ((u16::from(fg[1]) + u16::from(bg[1])) / 2) as u8,
                ((u16::from(fg[2]) + u16::from(bg[2])) / 2) as u8,
                255,
            ])
        };
        draw_text(canvas, width, height, 32, top + 11, &label, color);
        if matches!(&row.kind, tray::MenuKind::Submenu(_)) {
            draw_text(canvas, width, height, width - 20, top + 11, ">", color);
        }
    }
    fill_rect(canvas, width, height, 0, 201, width, 1,
              if luna { 0xffba_cae0 } else { style.active });
    draw_text(canvas, width, height, 12, 216,
              if popup.first > 0 { "< Previous" } else { "First page" }, fg);
    draw_text(canvas, width, height, 169, 216,
              if popup.first + tray::POPUP_ROWS < popup.rows().len() {
                  "Next >"
              } else { "Last page" }, fg);
}

fn paint_focus_border(canvas: &mut [u8], width: u32, height: u32,
                      x: u32, cell_width: u32, color: u32) {
    if cell_width < 6 || height < 6 { return; }
    let inset = x.saturating_add(2);
    let inside = cell_width.saturating_sub(4);
    fill_rect(canvas, width, height, inset, 2, inside, 2, color);
    fill_rect(canvas, width, height, inset, height - 4, inside, 2, color);
    fill_rect(canvas, width, height, inset, 2, 2, height - 4, color);
    fill_rect(canvas, width, height, x.saturating_add(cell_width - 4), 2, 2, height - 4, color);
}

fn logout_available() -> bool {
    // An isolated Creator render can inherit an outer labwc PID. Never let a
    // preview's menu terminate the real logged-in desktop.
    if std::env::var("RICEBOWL_DE_NESTED").as_deref() == Ok("1") {
        return false;
    }
    std::env::var("LABWC_PID")
        .ok()
        .and_then(|value| value.parse::<u32>().ok())
        .is_some_and(|pid| pid > 1)
}

fn fit_menu_pixels(original: &[u8], canvas: &mut [u8], size: (u32, u32)) {
    let (width, height) = size;
    for y in 0..height {
        for x in 0..width {
            let source_x = x * native_menu::WIDTH / width;
            let source_y = y * native_menu::HEIGHT / height;
            let source = ((source_y * native_menu::WIDTH + source_x) * 4) as usize;
            let dest = ((y * width + x) * 4) as usize;
            canvas[dest..dest + 4].copy_from_slice(&original[source..source + 4]);
        }
    }
}

/// Smooth only the *upscaled* Luna menu image. Input coordinates, actions,
/// logical layout and small-output pixel-exact behavior are unchanged. In
/// particular, no extra surface, font atlas or per-frame image cache exists.
fn fit_luna_menu_pixels(original: &[u8], canvas: &mut [u8], size: (u32, u32)) {
    let (width, height) = size;
    debug_assert!(width > native_menu::WIDTH && height > native_menu::HEIGHT);
    let sw = native_menu::WIDTH;
    let sh = native_menu::HEIGHT;
    for y in 0..height {
        let fy = (f64::from(y) + 0.5) * f64::from(sh) / f64::from(height) - 0.5;
        let y0 = fy.floor().clamp(0.0, f64::from(sh - 1)) as u32;
        let y1 = (y0 + 1).min(sh - 1);
        let ty = (fy - f64::from(y0)).clamp(0.0, 1.0);
        for x in 0..width {
            let fx = (f64::from(x) + 0.5) * f64::from(sw) / f64::from(width) - 0.5;
            let x0 = fx.floor().clamp(0.0, f64::from(sw - 1)) as u32;
            let x1 = (x0 + 1).min(sw - 1);
            let tx = (fx - f64::from(x0)).clamp(0.0, 1.0);
            let p00 = ((y0 * sw + x0) * 4) as usize;
            let p10 = ((y0 * sw + x1) * 4) as usize;
            let p01 = ((y1 * sw + x0) * 4) as usize;
            let p11 = ((y1 * sw + x1) * 4) as usize;
            let dst = ((y * width + x) * 4) as usize;
            for channel in 0..4 {
                let upper = f64::from(original[p00 + channel]) * (1.0 - tx)
                    + f64::from(original[p10 + channel]) * tx;
                let lower = f64::from(original[p01 + channel]) * (1.0 - tx)
                    + f64::from(original[p11 + channel]) * tx;
                canvas[dst + channel] =
                    (upper * (1.0 - ty) + lower * ty).round() as u8;
            }
        }
    }
}

/// The header controls are part of RicePlate's shared menu primitive. Their
/// rects come from native_menu, so the compact painter, pointer and AT expose
/// the same real actions across recipes without theme-specific hit regions.
fn paint_menu_header_controls(canvas: &mut [u8], size: (u32, u32),
                              style: &PanelStyle, state: &MenuState,
                              background: u32, foreground: u32, selection: u32,
                              luna_columns: bool) {
    for (hit, text, active) in [
        (MenuHit::Search, state.search_button_label(),
         state.view == native_menu::View::Search ||
             (state.view == native_menu::View::Programs && !state.search.is_empty())),
        (MenuHit::Saved, state.saved_button_label(), state.view == native_menu::View::Saved),
    ] {
        let Some((x, y, width, height)) = native_menu::header_button_rect(size, hit) else {
            continue;
        };
        if luna_columns {
            // Both buttons retain the same native hit rectangles; the two
            // tone treatment is purely visual and carries no fake controls.
            fill_rounded_rect(canvas, size.0, size.1, x, y, width, height,
                              5, 0xff0d_357f);
            fill_rounded_rect(canvas, size.0, size.1, x + 1, y + 1,
                              width - 2, height - 3, 4,
                              if active { 0xff4b_80c8 } else { 0xff2b_67bd });
            fill_rect(canvas, size.0, size.1, x + 6, y + 3,
                      width - 12, 1, 0xff8c_c2f1);
        } else {
            fill_rounded_rect(canvas, size.0, size.1, x, y, width, height,
                              style.task_radius.max(2), if active { selection } else { background });
        }
        let characters = width.saturating_sub(12) / (8 * style.font_scale);
        let caption = if characters < 4 { &text[..1] } else { text };
        draw_rice_text(canvas, size.0, size.1, x + 6,
                       y + height.saturating_sub(8 * style.font_scale) / 2,
                       caption, if luna_columns { 0xffff_ffff } else { foreground }, style);
    }
}

fn paint_compact_menu(canvas: &mut [u8], menu: &recipe::NativeMenu,
                      style: &PanelStyle, state: &MenuState, size: (u32, u32)) {
    let (width, height) = size;
    let rows = native_menu::compact_visible_actions(size);
    let first = state.first_action_row_for(rows);
    let bg = menu.palette.map_or(style.background, |item| item.background);
    let fg = menu.palette.map_or(style.foreground, |item| item.foreground);
    let header = menu.palette.map_or(style.active, |item| item.header);
    let header_fg = menu.palette.map_or(style.foreground, |item| item.header_foreground);
    let selection = menu.palette.map_or(style.active, |item| item.selection);
    for pixel in canvas.chunks_exact_mut(4) {
        pixel.copy_from_slice(&bg.to_le_bytes());
    }
    fill_rect(canvas, width, height, 0, 0, width, 32, header);
    let heading = match state.view {
        native_menu::View::Groups => menu.title.as_str(),
        native_menu::View::Programs => "All Programs",
        native_menu::View::Search => "Find applications & actions",
        native_menu::View::Saved => "Saved actions",
    };
    let heading_limit = width.saturating_sub(native_menu::HEADER_ACTIONS_WIDTH + 8)
        / (8 * style.font_scale);
    draw_rice_text(canvas, width, height, 8, 9,
                   &heading.chars().take(heading_limit as usize).collect::<String>(),
                   header_fg, style);
    paint_menu_header_controls(canvas, size, style, state, bg, fg, selection, false);
    let groups = menu.groups.len().max(1) as u32;
    for (index, group) in menu.groups.iter().enumerate() {
        let x = index as u32 * width / groups;
        let end = (index as u32 + 1) * width / groups;
        let cell_width = end.saturating_sub(x);
        if state.view == native_menu::View::Groups && state.group == index {
            fill_rect(canvas, width, height, x, native_menu::COMPACT_TABS_TOP,
                      cell_width, native_menu::COMPACT_TABS_HEIGHT,
                      selection);
        }
        let limit = cell_width.saturating_sub(12) / (8 * style.font_scale);
        draw_rice_text(canvas, width, height, x + 6,
                       native_menu::COMPACT_TABS_TOP + 10,
                       &group.title.chars().take(limit as usize).collect::<String>(),
                       fg, style);
    }
    let actions = state.actions(menu);
    if actions.is_empty() {
        let label = if state.view == native_menu::View::Programs {
            if state.search.is_empty() { "No installed apps" } else { "No matching apps" }
        } else if state.view == native_menu::View::Saved {
            "No saved actions"
        } else if state.view == native_menu::View::Search {
            "No matching actions"
        } else { "No actions" };
        draw_rice_text(canvas, width, height, 9, native_menu::COMPACT_ACTION_TOP + 14,
                       label, fg, style);
    }
    for (row, action) in actions.iter().skip(first).take(rows).enumerate() {
        let index = first + row;
        let y = native_menu::COMPACT_ACTION_TOP + row as u32 * native_menu::COMPACT_ACTION_HEIGHT;
        if index == state.selected {
            fill_rounded_rect(canvas, width, height, 5, y + 2,
                              width.saturating_sub(10),
                              native_menu::COMPACT_ACTION_HEIGHT - 4,
                              style.task_radius,
                              selection);
        }
        let unavailable = *action == "logout" && !logout_available();
        let label = state.visible_label(menu, action, !unavailable);
        let pinned = state.pins.iter().any(|pin| pin.as_str() == *action);
        let text = format!("{}{}", if pinned { "* " } else { "" }, label);
        let limit = width.saturating_sub(24) / (8 * style.font_scale);
        let color = if unavailable && style.disabled != 0 {
            style.disabled
        } else { fg };
        draw_rice_text(canvas, width, height, 12,
                       y + (native_menu::COMPACT_ACTION_HEIGHT - 8 * style.font_scale) / 2,
                       &text.chars().take(limit as usize).collect::<String>(), color, style);
    }
    // A real footer hit target closes even an empty search or saved view;
    // the counter tells keyboard users when more actions are available.
    let footer_y = height - native_menu::COMPACT_FOOTER_HEIGHT;
    fill_rect(canvas, width, height, 0, footer_y, width, 1, header);
    let footnote = if let Some(notice) = state.notice {
        notice.to_owned()
    } else if state.view == native_menu::View::Search {
        format!("Find: {}", state.search)
    } else if state.view == native_menu::View::Programs && !state.search.is_empty() {
        format!("Filter: {}", state.search)
    } else if state.view == native_menu::View::Programs && actions.is_empty() {
        "Esc: back".to_owned()
    } else if actions.is_empty() {
        "Esc: close".to_owned()
    } else if state.view == native_menu::View::Programs {
        format!("{}-{} / {}  Esc: back", first + 1,
                (first + rows).min(actions.len()), actions.len())
    } else {
        format!("{}-{} / {}  F2 pin  Esc", first + 1,
                (first + rows).min(actions.len()), actions.len())
    };
    draw_rice_text(canvas, width, height, 8, footer_y + 8,
                   &footnote.chars().take((width.saturating_sub(12) /
                       (8 * style.font_scale)) as usize).collect::<String>(), fg, style);
}

/// A single persistence boundary for F2 and menu pointer pin/unpin. Never
/// leave an in-memory favorite that failed owner-private storage validation.
fn toggle_menu_pin(state: &mut MenuState, recipe_id: &str, menu: &recipe::NativeMenu) {
    if state.view == native_menu::View::Programs {
        // Pins are versioned recipe action IDs, never arbitrary desktop files.
        state.notice = Some("App pinning unavailable");
        return;
    }
    let previous = state.pins.clone();
    if !state.toggle_pin(menu) {
        state.notice = Some("No action or saved list full");
        return;
    }
    let pinned = state.pins.len() > previous.len();
    if let Err(error) = menu_pins::save(recipe_id, menu, &state.pins) {
        eprintln!("RicePlate: cannot save native menu pins: {error}");
        state.pins = previous;
        state.notice = Some("Cannot save pins");
    } else {
        state.notice = Some(if pinned { "Action pinned" } else { "Pin removed" });
    }
}

fn paint_menu(canvas: &mut [u8], menu: &recipe::NativeMenu, style: &PanelStyle, state: &MenuState) {
    let width = native_menu::WIDTH;
    let height = native_menu::HEIGHT;
    let bg = menu.palette.map_or(style.background, |item| item.background);
    let fg = menu.palette.map_or(style.foreground, |item| item.foreground);
    let header = menu.palette.map_or(style.active, |item| item.header);
    let header_fg = menu.palette.map_or(style.foreground, |item| item.header_foreground);
    let selection = menu.palette.map_or(style.active, |item| item.selection);
    for pixel in canvas.chunks_exact_mut(4) {
        pixel.copy_from_slice(&bg.to_le_bytes());
    }
    let luna_columns = menu.presentation == recipe::MenuPresentation::Columns
        && menu.palette.is_some();
    if luna_columns {
        menu_chrome::header(canvas, menu.palette.unwrap());
    } else {
        fill_rect(canvas, width, height, 0, 0, width, 38, header);
    }
    draw_rice_text(
        canvas,
        width,
        height,
        if luna_columns { 43 } else { 16 },
        if style.font_scale == 1 { 15 } else { 11 },
        &menu.title.chars().take((width.saturating_sub(native_menu::HEADER_ACTIONS_WIDTH
            + if luna_columns { 43 } else { 16 })
            / (8 * style.font_scale)) as usize)
            .collect::<String>(),
        header_fg,
        style,
    );
    paint_menu_header_controls(canvas, (width, height), style, state,
                               bg, fg, selection, luna_columns);
    let sidebar = menu.presentation == recipe::MenuPresentation::Sidebar;
    let columns = menu.presentation == recipe::MenuPresentation::Columns
        && state.view == native_menu::View::Groups;
    let groups = menu.groups.len().max(1) as u32;
    if columns {
        // Two simultaneous regions: clear, navigable programs on cream and
        // system/session commands on a pale-blue right-hand shelf.
        if luna_columns {
            menu_chrome::shelf(canvas, menu.palette.unwrap());
            menu_chrome::left_all_programs_rule(canvas);
        } else {
            fill_rect(canvas, width, height, native_menu::COLUMNS_SPLIT, 38,
                      width - native_menu::COLUMNS_SPLIT, height - 66, selection);
            fill_rect(canvas, width, height, native_menu::COLUMNS_SPLIT, 38,
                      2, height - 66, header);
        }
    } else {
        if sidebar {
            fill_rect(canvas, width, height, native_menu::SIDEBAR_WIDTH - 2,
                      39, 2, height - 67, selection);
        }
        for (index, group) in menu.groups.iter().enumerate() {
            let (x, y, section_width, section_height) = if sidebar {
                (0, native_menu::TAB_TOP + index as u32 * native_menu::SIDEBAR_ROW_HEIGHT,
                 native_menu::SIDEBAR_WIDTH - 2, native_menu::SIDEBAR_ROW_HEIGHT)
            } else {
                let x = index as u32 * width / groups;
                (x, native_menu::TAB_TOP, (index as u32 + 1) * width / groups - x,
                 native_menu::TAB_HEIGHT)
            };
            if state.view == native_menu::View::Groups && state.group == index {
                fill_rect(canvas, width, height, x, y, section_width, section_height,
                          selection);
            }
            let available = section_width.saturating_sub(16) / (8 * style.font_scale);
            let label: String = group.title.chars().take(available as usize).collect();
            draw_rice_text(canvas, width, height, x + 8,
                      y + section_height.saturating_sub(8 * style.font_scale) / 2,
                      &label, fg, style);
        }
    }
    let content_x = if sidebar { native_menu::SIDEBAR_WIDTH + 8 } else { 12 };
    if state.view == native_menu::View::Search {
        draw_rice_text(canvas, width, height, content_x, 91,
                       &format!("Find: {}", state.search), fg, style);
    } else if state.view == native_menu::View::Programs {
        draw_rice_text(canvas, width, height, content_x, 91,
                       &if state.search.is_empty() {
                           format!("All Programs ({})", state.apps.len())
                       } else {
                           format!("Matches: {}  {}", state.actions(menu).len(),
                                   state.search.chars().take(16).collect::<String>())
                       }, fg, style);
    } else if state.view == native_menu::View::Saved {
        draw_rice_text(canvas, width, height, content_x, 91,
                       &format!("Saved actions: {}", state.actions(menu).len()), fg, style);
    }
    if let Some(sections) = state.composed_sections(menu) {
        let mut right_group_seen = false;
        for section in sections {
            if luna_columns && columns && section.x >= native_menu::COLUMNS_SPLIT {
                if right_group_seen {
                    let dense = section.items.first()
                        .is_some_and(|tile| tile.height <= native_menu::COLUMNS_RIGHT_DENSE_ROW_HEIGHT);
                    menu_chrome::system_group_rule(canvas,
                        section.top.saturating_sub(if dense { 0 } else { 4 }));
                }
                right_group_seen = true;
            }
            // XP's frequent-program pane has no stacked section headings:
            // the white list begins directly below the account banner.
            // Other recipes and the blue system shelf retain their labels.
            if !(luna_columns && columns && section.x < native_menu::COLUMNS_SPLIT) {
                draw_rice_text(canvas, width, height, section.x + 2, section.top + 3,
                               section.title, fg, style);
            }
            if section.items.is_empty() {
                let empty = match section.kind {
                    recipe::MenuContentKind::Favorites => "No favorites yet",
                    recipe::MenuContentKind::AppsList | recipe::MenuContentKind::AppsGrid =>
                        "No installed apps",
                    recipe::MenuContentKind::Actions => "No actions",
                };
                draw_rice_text(canvas, width, height, content_x + 5,
                               section.top + 28, empty, fg, style);
            }
            for tile in section.items {
                if tile.index == state.selected {
                    fill_rounded_rect(canvas, width, height, tile.x + 2, tile.y + 2,
                                      tile.width.saturating_sub(4), tile.height.saturating_sub(4),
                                      style.task_radius, if columns { header } else { selection });
                }
                let tile_fg = if columns && tile.index == state.selected {
                    header_fg
                } else { fg };
                let label = state.visible_label(menu, tile.action, logout_available());
                let pinned = state.pins.iter().any(|pin| pin.as_str() == tile.action);
                if luna_columns && columns && !tile.grid {
                    let icon_y = if tile.height == native_menu::COLUMNS_RIGHT_XP_PARITY_ROW_HEIGHT {
                        tile.y + 2
                    } else if tile.height == native_menu::COLUMNS_RIGHT_DENSE_ROW_HEIGHT {
                        tile.y + 4
                    } else { tile.y + 9 };
                    menu_chrome::action_icon(canvas, tile.x + 6, icon_y,
                                             tile.action, tile.index == state.selected);
                    if tile.action == "applications" {
                        // Green XP-inspired glyph over the *real* All Programs
                        // action, not a duplicate or nonfunctional control.
                        menu_chrome::all_programs_chevron(
                            canvas, tile.x + tile.width - 21, tile.y + 7,
                            tile.index == state.selected);
                    }
                }
                if tile.grid {
                    // A compact letter tile, not a promise of themed app icons.
                    let initial: String = label.chars().next().unwrap_or('?').to_uppercase().collect();
                    draw_rice_text(canvas, width, height, tile.x + 9, tile.y + 9,
                                   &initial, tile_fg, style);
                    let short: String = label.chars().take(9).collect();
                    draw_rice_text(canvas, width, height, tile.x + 9, tile.y + 27,
                                   &short, tile_fg, style);
                } else {
                    let text_inset = if luna_columns && columns { 25 } else { 10 };
                    let cap = (tile.width.saturating_sub(text_inset + 10) /
                               (8 * style.font_scale)) as usize;
                    let prefix = if pinned { "* " } else { "" };
                    let short: String = if luna_columns && columns {
                        fit_rice_text(&format!("{prefix}{label}"),
                            tile.width.saturating_sub(text_inset + 11), style)
                    } else {
                        format!("{prefix}{}", label.chars()
                            .take(cap.saturating_sub(prefix.len())).collect::<String>())
                    };
                    let text_y = if luna_columns && columns
                        && tile.height == native_menu::COLUMNS_RIGHT_XP_PARITY_ROW_HEIGHT {
                        tile.y + (18_u32.saturating_sub(8 * style.font_scale)) / 2
                    } else if luna_columns && columns
                        && tile.height == native_menu::COLUMNS_RIGHT_DENSE_ROW_HEIGHT {
                        tile.y + 8
                    } else { tile.y + 12 };
                    draw_rice_text(canvas, width, height, tile.x + text_inset, text_y,
                                   &short, tile_fg, style);
                }
            }
        }
    } else {
    let actions = state.actions(menu);
    if actions.is_empty() {
        draw_rice_text(canvas, width, height, content_x, 135,
                       if state.view == native_menu::View::Programs {
                           if state.search.is_empty() { "No installed apps" }
                           else { "No matching apps" }
                       } else if state.view == native_menu::View::Saved {
                           "No saved actions"
                       } else { "No matching actions" }, fg, style);
    } else {
        for (row, action) in actions.into_iter().skip(state.first_action_row())
            .take(native_menu::VISIBLE_ACTIONS).enumerate() {
            let action_index = state.first_action_row() + row;
            let top = native_menu::ACTION_TOP + row as u32 * native_menu::ACTION_HEIGHT;
            let action_x = if sidebar { native_menu::SIDEBAR_WIDTH + 4 } else { 8 };
            if action_index == state.selected {
                fill_rounded_rect(
                    canvas,
                    width,
                    height,
                    action_x,
                    top + 2,
                    width - action_x - 8,
                    native_menu::ACTION_HEIGHT - 4,
                    style.task_radius,
                    selection,
                );
            }
            let label = if action == "logout" && !logout_available() {
                "Log out (unavailable)"
            } else { state.label(action) };
            let pinned = state.pins.iter().any(|pin| pin.as_str() == action);
            let max_chars = (if sidebar { if pinned { 19 } else { 21 } }
                             else if pinned { 33 } else { 35 }) / style.font_scale as usize;
            let short_label: String = label.chars().take(max_chars).collect();
            draw_rice_text(canvas, width, height, action_x + 12,
                      top + if style.font_scale == 1 { 16 } else {
                          native_menu::ACTION_HEIGHT.saturating_sub(8 * style.font_scale) / 2 },
                      &format!("{}{}", if pinned { "* " } else { "" }, short_label),
                      if label.contains("(unavailable)") && style.disabled != 0
                          { style.disabled } else { fg }, style);
        }
    }
    }
    if luna_columns {
        menu_chrome::footer(canvas, menu.palette.unwrap(), state.footer_hover,
                            logout_available());
    } else if columns {
        fill_rect(canvas, width, height, 0, height - 28, width, 28, header);
    }
    if luna_columns {
        // Three original XP-style footer buttons, all backed by fixed native
        // actions. Avoid painting the legacy shortcut hint under real controls.
        let caption = |x: u32, value: &str, color: u32, canvas: &mut [u8]| {
            draw_rice_text(canvas, width, height, x, height - 16, value, color, style);
        };
        caption(31, "Lock", header_fg, canvas);
        caption(109, "Log off", if logout_available() { header_fg }
                else { 0xffb9_c9e0 }, canvas);
        caption(261, "Close", header_fg, canvas);
        // Moving real controls into the footer must not silently remove the
        // action feedback / keyboard discovery it previously provided. The
        // left shelf has a free strip above its first action; bound text to
        // the pane so it cannot paint across the system column.
        let status = state.notice.unwrap_or(match state.view {
            native_menu::View::Programs => "Enter open  Esc back",
            native_menu::View::Search => "Find  F2 Pin",
            native_menu::View::Saved => "F2 Remove  F3 Back",
            native_menu::View::Groups => "F2 Pin  F3 Saved",
        });
        if state.view != native_menu::View::Groups || state.notice.is_some() {
            let available_chars = (native_menu::COLUMNS_SPLIT.saturating_sub(20)
                / (8 * style.font_scale.max(1))) as usize;
            draw_rice_text(canvas, width, height, 12, 47,
                           &status.chars().take(available_chars).collect::<String>(),
                           fg, style);
        }
        // Keep the genuine range indicator visible on long search pages.
        if let Some((start, end, total)) = state.page_status(menu, native_menu::VISIBLE_ACTIONS) {
            caption(190, &format!("{start}-{end}/{total}"), header_fg, canvas);
        }
        return;
    }
    // On a long list the visible row range must be discoverable without a
    // keyboard shortcut. Keep the counter right-aligned and bound the hint so
    // it never paints under the counter at either supported font scale.
    let page = state.page_status(menu, native_menu::VISIBLE_ACTIONS)
        .map(|(first, last, total)| format!("{first}-{last}/{total}"));
    let hint = state.notice.unwrap_or(if state.view == native_menu::View::Programs {
        "Enter: open  Esc: back"
    } else if page.is_some() { "Find  Right/F2 Pin" }
    else { "Find  Right/F2 Pin  F3 Saved" });
    let glyph_width = 8 * style.font_scale;
    let hint_limit = if luna_columns {
        (width.saturating_sub(90) / glyph_width).min(28)
    } else if let Some(counter) = page.as_ref() {
        width.saturating_sub(28 + counter.chars().count() as u32 * glyph_width)
            / glyph_width
    } else { width / glyph_width };
    draw_rice_text(
        canvas,
        width,
        height,
        12,
        height - 16,
        &hint.chars().take(hint_limit as usize).collect::<String>(),
        if columns { header_fg } else { fg },
        style,
    );
    if let Some(counter) = page {
        let right = width.saturating_sub(
            (if luna_columns { 83 } else { 12 }) + counter.chars().count() as u32 * glyph_width);
        draw_rice_text(canvas, width, height, right, height - 16, &counter, fg, style);
    }
    if luna_columns {
        draw_rice_text(canvas, width, height, width - 62, height - 16,
                       "Close", header_fg, style);
    }
}

fn paint_luna_dialog(canvas: &mut [u8], style: &PanelStyle, state: &luna_dialog::State) {
    let (w, h) = (luna_dialog::WIDTH, luna_dialog::HEIGHT);
    canvas.fill(0);
    fill_rect(canvas, w, h, 0, 0, w, h, 0xff1a_439c);
    fill_rect(canvas, w, h, 3, 3, w - 6, h - 6, 0xfff6_f3e9);
    fill_rect(canvas, w, h, 4, 4, w - 8, 34, 0xff1c_57c3);
    // Authentic-ish blue caption and a distinct red close glyph, all original.
    draw_rice_text(canvas, w, h, 15, 14, if state.kind == luna_dialog::Kind::Run {
        "Run" } else { "Help and Support" }, 0xffff_ffff, style);
    fill_rounded_rect(canvas, w, h, 414, 9, 24, 23, 3, 0xffd8_4039);
    draw_rice_text(canvas, w, h, 422, 16, "x", 0xffff_ffff, style);

    match state.kind {
        luna_dialog::Kind::Run => {
            fill_rounded_rect(canvas, w, h, 25, 67, 67, 73, 8, 0xff2b_64ae);
            fill_rect(canvas, w, h, 38, 81, 41, 33, 0xffe2_f5ff);
            fill_rect(canvas, w, h, 44, 87, 29, 21, 0xff8a_d6ec);
            fill_rect(canvas, w, h, 50, 116, 17, 7, 0xffab_c6d7);
            draw_rice_text(canvas, w, h, 118, 68, "Type a program name.", 0xff17_315c, style);
            draw_rice_text(canvas, w, h, 118, 87, "No shell expansion.", 0xff4d_6284, style);
            draw_rice_text(canvas, w, h, 118, 104, "Open:", 0xff17_315c, style);
            fill_rect(canvas, w, h, 118, 111, 306, 32, 0xff75_879f);
            fill_rect(canvas, w, h, 120, 113, 302, 28, 0xffff_ffff);
            // Use the same font advances as actual glyph drawing: a
            // proportional selected font must not misplace the caret.
            let (text, cursor_x) = state.input_view(282, |value| {
                style.native_art.as_ref().and_then(|art| art.font.as_ref())
                    .map_or_else(
                        || text_pixel_width(value, style.font_scale.max(1)),
                        |font| font.measure_text(value),
                    )
            });
            draw_rice_text(canvas, w, h, 128, 122, &text, 0xff10_2849, style);
            fill_rect(canvas, w, h, 128 + cursor_x, 120, 2, 16, 0xff10_2849);
            let notice = state.notice.unwrap_or("Executes a command directly as your user.");
            draw_rice_text(canvas, w, h, 22, 163,
                           &notice.chars().take(50).collect::<String>(),
                           if state.notice.is_some() { 0xffb2_302e } else { 0xff4d_6284 }, style);
        }
        luna_dialog::Kind::Help => {
            for (line, text) in [
                "Start menu: All Programs lists installed apps.",
                "Find searches real desktop entries and actions.",
                "F2 pins an action; F3 opens Saved.",
                "Double-click a shortcut to open it.",
                "Right-click a shortcut for display options.",
                "Run starts typed commands without a shell.",
            ].iter().enumerate() {
                draw_rice_text(canvas, w, h, 23, 54 + line as u32 * 22,
                               text, 0xff17_315c, style);
            }
        }
    }
    let primary = if state.kind == luna_dialog::Kind::Run { "OK" } else { "Close" };
    for (x, label, hit) in [(260, primary, luna_dialog::Hit::Accept),
                           (346, "Cancel", luna_dialog::Hit::Cancel)] {
        if state.kind == luna_dialog::Kind::Help && hit == luna_dialog::Hit::Cancel {
            continue;
        }
        let shade = if state.pressed == Some(hit) { 0xff1e_4d9a }
                    else if state.hover == Some(hit) { 0xff4e_8ddd }
                    else { 0xff37_6bbd };
        fill_rounded_rect(canvas, w, h, x, 188, 78, 30, 3, shade);
        fill_rect(canvas, w, h, x + 3, 190, 72, 1, 0xffc3_dffb);
        draw_rice_text(canvas, w, h, x + if label == "Cancel" { 12 }
                       else if label == "Close" { 16 } else { 30 },
                       198, label, 0xffff_ffff, style);
    }
}

fn paint_desktop_context(canvas: &mut [u8], style: &PanelStyle,
                         selected: DesktopContextAction,
                         hovered: Option<DesktopContextAction>,
                         can_move: bool, can_reset: bool, properties: bool,
                         details: Option<(&str, &str)>, back_hovered: bool,
                         file_operation: Option<&desktop_context::FileOperation>) {
    let (w, h) = (desktop_context::WIDTH, desktop_context::HEIGHT);
    canvas.fill(0);
    fill_rect(canvas, w, h, 0, 0, w, h, 0xff20_3f7e);
    fill_rect(canvas, w, h, 2, 2, w - 4, h - 4, 0xfffc_faf2);
    fill_rect(canvas, w, h, 3, 3, w - 6, 29, 0xff24_5ed3);
    draw_rice_text(canvas, w, h, 12, 11,
                   if properties { "Properties" }
                   else if file_operation.is_some() { "File action" }
                   else { "Shortcut" }, 0xffff_ffff, style);
    if let Some(operation) = file_operation {
        match operation {
            desktop_context::FileOperation::Rename(input) => {
                draw_rice_text(canvas, w, h, 12, 48, "New name:", 0xff1d_273d, style);
                fill_rect(canvas, w, h, 12, 68, w - 24, 28, 0xffff_ffff);
                let chars: Vec<_> = input.value().chars().rev().take(19).collect();
                let visible: String = chars.into_iter().rev().collect();
                draw_rice_text(canvas, w, h, 16, 77, &visible, 0xff1d_273d, style);
                draw_rice_text(canvas, w, h, 12, 110,
                    input.error.unwrap_or("Enter: save name"), 0xff9b_2727, style);
            }
            desktop_context::FileOperation::ConfirmTrash => {
                draw_rice_text(canvas, w, h, 12, 48,
                    "Move file to Trash?", 0xff1d_273d, style);
                draw_rice_text(canvas, w, h, 12, 66,
                    "No permanent delete", 0xff1d_273d, style);
                fill_rect(canvas, w, h, 5, 84, w - 10, 27, 0xffe5_e9f2);
                draw_rice_text(canvas, w, h, 15, 93, "Confirm", 0xff1d_273d, style);
            }
        }
        let y = desktop_context::BACK_ROW;
        fill_rect(canvas, w, h, 5, y, w - 10, 27,
                  if back_hovered { 0xff36_6ac9 } else { 0xffe5_e9f2 });
        draw_rice_text(canvas, w, h, 15, y + 8, "Cancel",
                       if back_hovered { 0xffff_ffff } else { 0xff1d_273d }, style);
        return;
    }
    if properties {
        // Bounded, read-only metadata for validated actions; no stat calls,
        // untrusted command strings or guessed file targets.
        let (label, action) = details.unwrap_or(("Unknown", ""));
        let (kind, target) = desktop_context::details(action);
        draw_rice_text(canvas, w, h, 12, 48, "Name:", 0xff1d_273d, style);
        draw_rice_text(canvas, w, h, 68, 48, label, 0xff1d_273d, style);
        draw_rice_text(canvas, w, h, 12, 82, "Type:", 0xff1d_273d, style);
        draw_rice_text(canvas, w, h, 68, 82, kind, 0xff1d_273d, style);
        draw_rice_text(canvas, w, h, 12, 116, target, 0xff1d_273d, style);
        let y = desktop_context::BACK_ROW;
        fill_rect(canvas, w, h, 5, y, w - 10, 27,
                  if back_hovered { 0xff36_6ac9 } else { 0xffe5_e9f2 });
        draw_rice_text(canvas, w, h, 15, y + 8, "Back",
                       if back_hovered { 0xffff_ffff } else { 0xff1d_273d }, style);
        return;
    }
    let is_file = details.is_some_and(|(_, action)| action.starts_with("desktop-file:"));
    for action in DesktopContextAction::ALL {
        let y = desktop_context::row(action);
        if action == selected || hovered == Some(action) {
            fill_rect(canvas, w, h, 5, y, w - 10, 27,
                      if action.enabled(can_move, can_reset) {
                          0xff36_6ac9
                      } else { 0xffdb_dfeb });
        }
        let color = if !action.enabled(can_move, can_reset) { 0xff7c_8291 }
                    else if action == selected || hovered == Some(action) { 0xffff_ffff }
                    else { 0xff1d_273d };
        draw_rice_text(canvas, w, h, 15, y + 8,
                       if is_file { action.label_for_file() } else { action.label() },
                       color, style);
    }
}

fn paint_icon(canvas: &mut [u8], icon: &recipe::DesktopIcon, style: &PanelStyle,
              focused: bool, custom: Option<&style_art::IconPixels>) {
    let width = recipe::ICON_WIDTH;
    let height = recipe::ICON_HEIGHT;
    let active = style.active;
    let foreground = style.foreground;
    canvas.fill(0); // Leave the surrounding desktop visible.
    if focused {
        // Narrow focus frame: keep the rest of the desktop hit area transparent.
        fill_rect(canvas, width, height, 0, 0, width, 2, foreground);
        fill_rect(canvas, width, height, 0, height - 2, width, 2, foreground);
        fill_rect(canvas, width, height, 0, 0, 2, height, foreground);
        fill_rect(canvas, width, height, width - 2, 0, 2, height, foreground);
    }
    let glyph = match icon.action.as_str() {
        "applications" => "Apps",
        "terminal" => ">_",
        "lock" => "Lock",
        "trash" => "Bin",
        "computer" => "PC",
        "documents" => "Docs",
        "network" => "Net",
        other if other.starts_with("desktop-file:") => "File",
        _ => return,
    };
    // The generic default is an original, fully vector-rasterized bin.
    // This still works without host icon themes or proprietary XP artwork.
    let native_bin = icon.action == "trash" && custom.is_none();
    if custom.is_some() {
        // Transparent 48px artwork sits in the existing, keyboard-reachable
        // 104x88 desktop icon surface. Wayland focus/label stay unchanged.
        style_art::paint_icon(canvas, width, custom.unwrap(), 28, 4);
    } else if matches!(icon.action.as_str(), "computer" | "documents" | "network") {
        // Dedicated original pixel-art silhouettes for fixed XP desktop places.
        // No host icon dependency and no proprietary Windows assets.
        match icon.action.as_str() {
            "computer" => {
                fill_rounded_rect(canvas, width, height, 30, 8, 44, 33, 4, 0xff4a_5870);
                fill_rect(canvas, width, height, 34, 11, 36, 25, 0xff8d_c9e3);
                fill_rect(canvas, width, height, 36, 13, 32, 20, 0xffd4_f0fd);
                fill_rect(canvas, width, height, 47, 41, 10, 6, 0xffb3_c4d7);
                fill_rounded_rect(canvas, width, height, 38, 47, 28, 4, 2, 0xff62_7088);
            }
            "documents" => {
                fill_rounded_rect(canvas, width, height, 27, 13, 50, 36, 4, 0xff9f_7c39);
                fill_rect(canvas, width, height, 33, 10, 24, 8, 0xffff_e6a0);
                fill_rounded_rect(canvas, width, height, 30, 20, 44, 27, 2, 0xfff7_cd62);
                fill_rect(canvas, width, height, 36, 27, 33, 3, 0xffff_eaa4);
                fill_rect(canvas, width, height, 36, 34, 26, 3, 0xffde_a644);
            }
            "network" => {
                for x in [30, 55] {
                    fill_rounded_rect(canvas, width, height, x, 8, 21, 21, 3, 0xff50_6784);
                    fill_rect(canvas, width, height, x + 3, 11, 15, 13, 0xff9b_dceb);
                    fill_rect(canvas, width, height, x + 8, 29, 5, 4, 0xffbd_c8d3);
                    fill_rect(canvas, width, height, x + 3, 33, 15, 3, 0xff60_7485);
                }
                fill_rect(canvas, width, height, 49, 22, 8, 4, 0xffe5_c456);
                fill_rect(canvas, width, height, 49, 36, 5, 8, 0xffe5_c456);
                fill_rect(canvas, width, height, 40, 42, 26, 4, 0xffe5_c456);
            }
            _ => unreachable!(),
        }
    } else if native_bin {
        // Original compact trash-can drawing, not a copied XP logo or asset.
        fill_rounded_rect(canvas, width, height, 35, 12, 34, 39, 5, 0xff48_719d);
        fill_rounded_rect(canvas, width, height, 37, 15, 30, 33, 4, 0xffd0_eaf8);
        fill_rect(canvas, width, height, 39, 18, 26, 28, 0xffac_d3e7);
        fill_rect(canvas, width, height, 40, 20, 4, 23, 0xffe6_f5ff);
        fill_rect(canvas, width, height, 48, 20, 3, 23, 0xff79_accf);
        fill_rect(canvas, width, height, 55, 20, 3, 23, 0xffe6_f5ff);
        fill_rect(canvas, width, height, 62, 20, 2, 23, 0xff79_accf);
        fill_rounded_rect(canvas, width, height, 32, 9, 40, 9, 4, 0xff41_6992);
        fill_rect(canvas, width, height, 35, 11, 34, 3, 0xffe7_f9ff);
        fill_rect(canvas, width, height, 47, 6, 11, 4, 0xff90_bdd8);
        fill_rect(canvas, width, height, 43, 46, 18, 2, 0xff76_a5c5);
    } else {
        fill_rounded_rect(canvas, width, height, 24, 4, 56, 48, 10, active);
    }
    // Classic XP desktop labels float directly above the wallpaper, with a
    // small dark text shadow instead of permanent translucent black pills.
    // Selection alone receives a cobalt label background. Other recipes keep
    // their existing contrast backplate, without changing icon hit geometry.
    if style.id == "xp-luna-columns" {
        if focused {
            fill_rounded_rect(canvas, width, height, 2, 58, 100, 26, 4, 0xd025_5ed3);
        }
    } else {
        fill_rounded_rect(canvas, width, height, 2, 58, 100, 26, 6, 0xb020_2c36);
    }
    if custom.is_none() && !native_bin
        && !matches!(icon.action.as_str(), "computer" | "documents" | "network") {
        draw_rice_text(canvas, width, height,
                       52_u32.saturating_sub(rice_text_width(glyph, style) / 2),
                       24, glyph, foreground, style);
    }
    let label_x = width.saturating_sub(rice_text_width(&icon.label, style)) / 2;
    if style.id == "xp-luna-columns" && !focused {
        draw_rice_text(canvas, width, height, label_x.saturating_add(1), 67,
                       &icon.label, 0xcc08_254b, style);
    }
    draw_rice_text(canvas, width, height, label_x, 66,
                   &icon.label, foreground, style);
}

fn paint_desktop_widget(canvas: &mut [u8], title: &str, lines: &[String], style: &PanelStyle,
                        interactive: bool, focused: bool, hovered: bool, disabled: bool) {
    let width = recipe::DESKTOP_WIDGET_WIDTH;
    let height = recipe::DESKTOP_WIDGET_HEIGHT;
    canvas.fill(0);
    fill_rounded_rect(canvas, width, height, 0, 0, width, height, 10, style.background);
    if interactive {
        let outline = if focused { style.focus } else if disabled { style.disabled }
                      else if hovered { style.hover } else { style.active };
        fill_rect(canvas, width, height, 0, 0, width, 2, outline);
        fill_rect(canvas, width, height, 0, height - 2, width, 2, outline);
        fill_rect(canvas, width, height, 0, 0, 2, height, outline);
        fill_rect(canvas, width, height, width - 2, 0, 2, height, outline);
    }
    fill_rect(canvas, width, height, 12, 31, width - 24, 2, style.active);
    draw_rice_text(canvas, width, height, 12,
                   if style.font_scale == 1 { 12 } else { 9 },
                   &title.chars().take((width / (8 * style.font_scale)).saturating_sub(3) as usize)
                       .collect::<String>(), style.foreground, style);
    for (index, line) in lines.iter().take(2).enumerate() {
        // The native 8px font has no word wrap. Keep every line inside the
        // bounded surface even when system providers expose long names.
        let clipped: String = line.chars().take((width.saturating_sub(24) /
            (8 * style.font_scale)) as usize).collect();
        draw_rice_text(canvas, width, height, 12,
                       if style.font_scale == 1 { 43 + index as u32 * 20 }
                       else { 40 + index as u32 * 23 },
                       &clipped, style.foreground, style);
    }
}

/// The XP taskband must preserve a visible grouped-window count even when
/// a proportionally rendered title needs ellipsis inside the button geometry.
fn fitted_task_label(group: &task_groups::TaskGroup, cell: u32,
                     style: &PanelStyle) -> String {
    let label = task_groups::visible_label(group, cell);
    if style.id != "xp-luna-columns" {
        return label;
    }
    let available = cell.saturating_sub(22);
    if group.members.len() <= 1 {
        return fit_rice_text(&label, available, style);
    }
    let suffix = format!(" ({})", group.members.len());
    let suffix_width = rice_text_width(&suffix, style);
    if suffix_width >= available {
        return fit_rice_text(&suffix, available, style);
    }
    let title = label.strip_suffix(&suffix).unwrap_or(&label);
    format!("{}{}", fit_rice_text(title, available - suffix_width, style), suffix)
}

impl CompositorHandler for RicePlate {
    fn scale_factor_changed(
        &mut self,
        _: &Connection,
        _: &QueueHandle<Self>,
        _: &wl_surface::WlSurface,
        _: i32,
    ) {
    }
    fn transform_changed(
        &mut self,
        _: &Connection,
        _: &QueueHandle<Self>,
        _: &wl_surface::WlSurface,
        _: wl_output::Transform,
    ) {
    }
    fn frame(
        &mut self,
        _: &Connection,
        qh: &QueueHandle<Self>,
        surface: &wl_surface::WlSurface,
        _: u32,
    ) {
        if surface != self.layer.wl_surface() {
            if let Some(index) = self.mirrors.iter().position(|mirror|
                    mirror.surface.wl_surface() == surface) {
                if self.mirrors[index].frame.frame_ready() {
                    self.redraw_mirror(index, qh);
                }
            }
            return;
        }
        if self.frame.frame_ready() { self.redraw(qh); }
    }
    fn surface_enter(
        &mut self,
        _: &Connection,
        qh: &QueueHandle<Self>,
        surface: &wl_surface::WlSurface,
        output: &wl_output::WlOutput,
    ) {
        if surface == self.layer.wl_surface() {
            eprintln!("RicePlate: primary panel entered {output:?}");
            self.primary_output = Some(output.clone());
            self.primary_output_seen = true;
            self.reflow_icons();
            self.sync_mirrors(qh);
            return;
        }
        if let Some(layer) = self
            .icon_layers
            .iter_mut()
            .find(|icon| icon.surface.wl_surface() == surface)
        {
            layer.output = Some(output.clone());
            self.reflow_icons();
        }
    }
    fn surface_leave(
        &mut self,
        _: &Connection,
        qh: &QueueHandle<Self>,
        surface: &wl_surface::WlSurface,
        output: &wl_output::WlOutput,
    ) {
        if surface == self.layer.wl_surface() {
            eprintln!("RicePlate: primary panel left {output:?}");
            if self.primary_output.as_ref() == Some(output) {
                self.primary_output = None;
            }
            self.sync_mirrors(qh);
            return;
        }
        if let Some(layer) = self
            .icon_layers
            .iter_mut()
            .find(|icon| icon.surface.wl_surface() == surface)
        {
            if layer.output.as_ref() == Some(output) {
                layer.output = None;
            }
        }
    }
}

impl LayerShellHandler for RicePlate {
    fn closed(&mut self, _: &Connection, qh: &QueueHandle<Self>, layer: &LayerSurface) {
        if self.desktop_context.as_ref().is_some_and(|menu|
            &menu.parent_surface == layer.wl_surface()) {
            self.close_desktop_context();
        }
        if self.focused_panel.as_ref() == Some(layer.wl_surface()) {
            self.focused_panel = None;
            self.focused_target = None;
        }
        if self.luna_dialog.as_ref().is_some_and(|dialog|
            dialog.surface.wl_surface() == layer.wl_surface()) {
            self.close_luna_dialog();
        } else if layer.wl_surface() == self.layer.wl_surface() {
            self.closed = true;
        } else if let Some(index) = self.mirrors.iter().position(|mirror|
                mirror.surface.wl_surface() == layer.wl_surface()) {
            self.mirrors.remove(index);
        } else if self
            .menu_layer
            .as_ref()
            .is_some_and(|menu| menu.surface.wl_surface() == layer.wl_surface())
        {
            self.menu_layer = None;
            if self.active_menu.as_ref() == Some(layer.wl_surface()) {
                self.set_menu_visible(false, qh);
            }
        } else if let Some(index) = self.menu_mirrors.iter().position(|menu|
            menu.surface.wl_surface() == layer.wl_surface()) {
            self.menu_mirrors.remove(index);
            if self.active_menu.as_ref() == Some(layer.wl_surface()) {
                self.set_menu_visible(false, qh);
            }
        } else if self.calendar_layer.as_ref()
            .is_some_and(|calendar| calendar.surface.wl_surface() == layer.wl_surface()) {
            self.calendar_layer = None;
            if self.active_calendar.as_ref() == Some(layer.wl_surface()) {
                self.set_calendar_visible(false, qh);
            }
        } else if let Some(index) = self.calendar_mirrors.iter().position(|calendar|
            calendar.surface.wl_surface() == layer.wl_surface()) {
            self.calendar_mirrors.remove(index);
            if self.active_calendar.as_ref() == Some(layer.wl_surface()) {
                self.set_calendar_visible(false, qh);
            }
        } else if self.osd_layer.as_ref().is_some_and(|osd|
            osd.surface.wl_surface() == layer.wl_surface()) {
            self.osd_layer = None;
        } else if self.tray_popup_layer.as_ref().is_some_and(|popup|
            popup.surface.wl_surface() == layer.wl_surface()) {
            self.tray_popup_layer = None;
            if self.active_tray_popup.as_ref() == Some(layer.wl_surface()) {
                self.set_tray_popup_visible(false, qh);
            }
        } else if let Some(index) = self.tray_popup_mirrors.iter().position(|popup|
            popup.surface.wl_surface() == layer.wl_surface()) {
            self.tray_popup_mirrors.remove(index);
            if self.active_tray_popup.as_ref() == Some(layer.wl_surface()) {
                self.set_tray_popup_visible(false, qh);
            }
        } else if let Some(icon) = self
            .icon_layers
            .iter_mut()
            .find(|icon| icon.surface.wl_surface() == layer.wl_surface())
        {
            icon.configured = false;
        } else if let Some(widget) = self.widget_layers.iter_mut()
            .find(|widget| widget.surface.wl_surface() == layer.wl_surface())
        {
            widget.configured = false;
        }
    }
    fn configure(
        &mut self,
        _: &Connection,
        qh: &QueueHandle<Self>,
        layer: &LayerSurface,
        config: LayerSurfaceConfigure,
        _: u32,
    ) {
        if self.luna_dialog.as_ref().is_some_and(|dialog|
            dialog.surface.wl_surface() == layer.wl_surface()) {
            if config.new_size != (luna_dialog::WIDTH, luna_dialog::HEIGHT) {
                eprintln!("RicePlate: compositor proposed unsupported Luna dialog size");
                self.close_luna_dialog();
                return;
            }
            let dialog = self.luna_dialog.as_mut().expect("matched Luna dialog");
            if dialog.pool.is_none() {
                let bytes = (luna_dialog::WIDTH * luna_dialog::HEIGHT * 4 * 3) as usize;
                match SlotPool::new(bytes, &self.shm) {
                    Ok(pool) => dialog.pool = Some(pool),
                    Err(error) => {
                        eprintln!("RicePlate: cannot allocate Luna dialog: {error}");
                        self.close_luna_dialog();
                        return;
                    }
                }
            }
            dialog.configured = true;
            self.redraw_luna_dialog();
            return;
        }
        if let Some(index) = self.mirrors.iter().position(|mirror|
                mirror.surface.wl_surface() == layer.wl_surface()) {
            let width = config.new_size.0;
            let height = config.new_size.1;
            if width == 0 || width > MAX_WIDTH || height == 0 || height > MAX_HEIGHT {
                eprintln!("RicePlate: invalid extra-output panel geometry");
                self.mirrors.remove(index);
                return;
            }
            let mirror = &mut self.mirrors[index];
            if (width, height) != (mirror.width, mirror.height) {
                let byte_count = width as usize * height as usize * 4 * 3;
                match SlotPool::new(byte_count, &self.shm) {
                    Ok(pool) => mirror.pool = Some(pool),
                    Err(error) => {
                        eprintln!("RicePlate: cannot allocate extra-output panel: {error}");
                        self.mirrors.remove(index);
                        return;
                    }
                }
            }
            mirror.width = width;
            mirror.height = height;
            mirror.configured = true;
            self.redraw_mirror(index, qh);
            return;
        }
        if self.osd_layer.as_ref().is_some_and(|osd|
            osd.surface.wl_surface() == layer.wl_surface()) {
            if config.new_size != (osd::WIDTH, osd::HEIGHT) {
                eprintln!("RicePop: compositor proposed invalid OSD size");
                self.osd_layer = None;
                return;
            }
            if let Some(osd_layer) = self.osd_layer.as_mut() {
                osd_layer.configured = true;
            }
            self.redraw_osd();
            return;
        }
        if self.tray_popup_layer.as_ref().is_some_and(|popup|
            popup.surface.wl_surface() == layer.wl_surface())
            || self.tray_popup_mirrors.iter().any(|popup|
                popup.surface.wl_surface() == layer.wl_surface()) {
            if config.new_size != (tray::POPUP_WIDTH, tray::POPUP_HEIGHT) {
                eprintln!("RicePlate: compositor proposed invalid SNI overflow size");
                if self.tray_popup_layer.as_ref().is_some_and(|popup|
                    popup.surface.wl_surface() == layer.wl_surface()) {
                    self.tray_popup_layer = None;
                } else {
                    self.tray_popup_mirrors.retain(|popup|
                        popup.surface.wl_surface() != layer.wl_surface());
                }
                if self.active_tray_popup.as_ref() == Some(layer.wl_surface()) {
                    self.set_tray_popup_visible(false, qh);
                }
                return;
            }
            if let Some(popup) = self.tray_popup_layer.as_mut().filter(|popup|
                popup.surface.wl_surface() == layer.wl_surface()) {
                popup.configured = true;
            } else if let Some(popup) = self.tray_popup_mirrors.iter_mut().find(|popup|
                popup.surface.wl_surface() == layer.wl_surface()) {
                popup.configured = true;
            }
            self.redraw_tray_popup();
            return;
        }
        if self.calendar_layer.as_ref().is_some_and(|calendar|
            calendar.surface.wl_surface() == layer.wl_surface())
            || self.calendar_mirrors.iter().any(|calendar|
                calendar.surface.wl_surface() == layer.wl_surface()) {
            if config.new_size != (calendar::WIDTH, calendar::HEIGHT) {
                eprintln!("RicePlate: compositor proposed unsupported calendar dimensions");
                if self.calendar_layer.as_ref().is_some_and(|calendar|
                    calendar.surface.wl_surface() == layer.wl_surface()) {
                    self.calendar_layer = None;
                } else {
                    self.calendar_mirrors.retain(|calendar|
                        calendar.surface.wl_surface() != layer.wl_surface());
                }
                if self.active_calendar.as_ref() == Some(layer.wl_surface()) {
                    self.set_calendar_visible(false, qh);
                }
                return;
            }
            if let Some(calendar_layer) = self.calendar_layer.as_mut()
                .filter(|calendar| calendar.surface.wl_surface() == layer.wl_surface()) {
                calendar_layer.configured = true;
            } else if let Some(calendar_layer) = self.calendar_mirrors.iter_mut().find(|calendar|
                calendar.surface.wl_surface() == layer.wl_surface()) {
                calendar_layer.configured = true;
            }
            self.redraw_calendar(qh);
            return;
        }
        if self.menu_layer.as_ref().is_some_and(|menu|
            menu.surface.wl_surface() == layer.wl_surface())
            || self.menu_mirrors.iter().any(|menu|
                menu.surface.wl_surface() == layer.wl_surface()) {
            let (expected_size, awaiting_resize) = self.menu_layer.iter().chain(self.menu_mirrors.iter())
                .find(|menu| menu.surface.wl_surface() == layer.wl_surface())
                .map(|menu| (menu.size, !menu.configured))
                .expect("matched a live native menu layer");
            let disposition = menu_size_decision(expected_size, config.new_size, awaiting_resize);
            if disposition == MenuSizeDecision::AwaitNewConfigure {
                // wl_layer_surface configure is asynchronous. A previous
                // 320×304 configure can arrive *after* output discovery has
                // requested 400×380/480×456. Keep this layer alive until
                // the matching configure arrives; dropping it here makes
                // the native Start menu disappear on the first wide output.
                eprintln!("RicePlate: ignoring superseded native menu configure {:?}; waiting for {:?}",
                          config.new_size, expected_size);
                return;
            }
            if disposition == MenuSizeDecision::RetryExpectedSize {
                // Output mode/scale changes can deliver an older configure
                // even *after* a matching configure was accepted. It is not
                // evidence that the compositor cannot render this surface:
                // destroying the layer would permanently remove Start until
                // the next session. Reassert the current desired geometry.
                eprintln!("RicePlate: retrying native menu geometry {:?} after stale {:?}",
                          expected_size, config.new_size);
                let menu_layer = self.menu_layer.iter_mut().chain(self.menu_mirrors.iter_mut())
                    .find(|menu| menu.surface.wl_surface() == layer.wl_surface())
                    .expect("matched a live native menu layer");
                menu_layer.configured = false;
                menu_layer.surface.set_size(expected_size.0, expected_size.1);
                menu_layer.surface.commit();
                return;
            }
            let menu_layer = self.menu_layer.as_mut().filter(|menu|
                menu.surface.wl_surface() == layer.wl_surface())
                .or_else(|| self.menu_mirrors.iter_mut().find(|menu|
                    menu.surface.wl_surface() == layer.wl_surface()))
                .expect("matched a live native menu layer");
            if menu_layer.pool.is_none() {
                let byte_count = (expected_size.0 * expected_size.1 * 4 * 3) as usize;
                match SlotPool::new(byte_count, &self.shm) {
                    Ok(pool) => menu_layer.pool = Some(pool),
                    Err(error) => {
                        eprintln!("RicePlate: cannot allocate native menu: {error}");
                        self.set_menu_visible(false, qh);
                        return;
                    }
                }
            }
            menu_layer.configured = true;
            self.redraw_menu(qh);
            return;
        }
        if let Some(index) = self
            .icon_layers
            .iter()
            .position(|icon| icon.surface.wl_surface() == layer.wl_surface())
        {
            if config.new_size != (recipe::ICON_WIDTH, recipe::ICON_HEIGHT) {
                eprintln!("RicePlate: compositor proposed unexpected desktop icon size");
                return;
            }
            let icon = &mut self.icon_layers[index];
            if icon.pool.is_none() {
                let bytes = recipe::ICON_WIDTH as usize * recipe::ICON_HEIGHT as usize * 4 * 2;
                match SlotPool::new(bytes, &self.shm) {
                    Ok(pool) => icon.pool = Some(pool),
                    Err(error) => {
                        eprintln!("RicePlate: cannot allocate icon memory: {error}");
                        self.closed = true;
                        return;
                    }
                }
            }
            icon.configured = true;
            self.redraw_icon(index);
            return;
        }
        if let Some(index) = self.widget_layers.iter()
            .position(|widget| widget.surface.wl_surface() == layer.wl_surface())
        {
            if config.new_size != (recipe::DESKTOP_WIDGET_WIDTH, recipe::DESKTOP_WIDGET_HEIGHT) {
                eprintln!("RicePlate: compositor proposed unexpected desktop widget size");
                return;
            }
            let widget = &mut self.widget_layers[index];
            if widget.pool.is_none() {
                let bytes = recipe::DESKTOP_WIDGET_WIDTH as usize
                    * recipe::DESKTOP_WIDGET_HEIGHT as usize * 4 * 2;
                match SlotPool::new(bytes, &self.shm) {
                    Ok(pool) => widget.pool = Some(pool),
                    Err(error) => {
                        eprintln!("RicePlate: desktop widget memory unavailable: {error}");
                        return;
                    }
                }
            }
            widget.configured = true;
            self.redraw_widget(index);
            return;
        }
        if layer.wl_surface() != self.layer.wl_surface() {
            return;
        }
        let width = config.new_size.0;
        let height = config.new_size.1;
        if width == 0 || width > MAX_WIDTH || height == 0 || height > MAX_HEIGHT {
            eprintln!("RicePlate: compositor proposed unsupported surface dimensions");
            self.closed = true;
            return;
        }
        if (width, height) != (self.width, self.height) {
            // Three slots permit updates while the compositor is still
            // reading earlier buffers. Allocation stays bounded to 48 MiB.
            let byte_count = width as usize * height as usize * 4 * 3;
            match SlotPool::new(byte_count, &self.shm) {
                Ok(pool) => self.pool = Some(pool),
                Err(error) => {
                    eprintln!("RicePlate: cannot allocate shared memory: {error}");
                    self.closed = true;
                    return;
                }
            }
        }
        self.width = width;
        self.height = height;
        self.configured = true;
        if let Some(index) = self.tasks.iter().position(|task| task.active && task.ready) {
            self.reveal_task(index);
        }
        self.request_redraw(qh);
    }
}

impl OutputHandler for RicePlate {
    fn output_state(&mut self) -> &mut OutputState {
        &mut self.outputs
    }
    fn new_output(&mut self, _: &Connection, qh: &QueueHandle<Self>, _: wl_output::WlOutput) {
        self.reflow_icons();
        self.sync_mirrors(qh);
    }
    fn update_output(&mut self, _: &Connection, qh: &QueueHandle<Self>, _: wl_output::WlOutput) {
        self.reflow_icons();
        self.sync_mirrors(qh);
    }
    fn output_destroyed(
        &mut self,
        _: &Connection,
        qh: &QueueHandle<Self>,
        output: wl_output::WlOutput,
    ) {
        if self.primary_output.as_ref() == Some(&output) {
            self.primary_output = None;
        }
        for icon in &mut self.icon_layers {
            if icon.output.as_ref() == Some(&output) {
                icon.output = None;
            }
        }
        self.reflow_icons();
        self.sync_mirrors(qh);
    }
}

// XdgShell::bind delegates the optional XDG decoration manager as well.
// RicePlate never creates an XDG toplevel; its only XDG role is the bounded
// icon-parented popup. These no-op WindowHandler callbacks satisfy SCTK's
// binding contract without adding window management or focus stealing.
impl WindowHandler for RicePlate {
    fn request_close(&mut self, _: &Connection, _: &QueueHandle<Self>, _: &Window) {}
    fn configure(&mut self, _: &Connection, _: &QueueHandle<Self>,
                 _: &Window, _: WindowConfigure, _: u32) {}
}

impl PopupHandler for RicePlate {
    fn configure(&mut self, _: &Connection, _: &QueueHandle<Self>,
                 popup: &Popup, config: PopupConfigure) {
        // Keep the original icon as the popup's geometry owner even when
        // searching changes which desktop action is highlighted.
        let within_output = self.desktop_context.as_ref()
            .filter(|menu| &menu.popup == popup)
            .and_then(|menu| {
                let parent = self.icon_layers.iter().find(|icon|
                    icon.surface.wl_surface() == &menu.parent_surface)?;
                let position = parent.placed?;
                let output = parent.bound_output.as_ref()
                    .or(self.primary_output.as_ref()).or(parent.output.as_ref())?;
                let size = self.logical_output_size(output)?;
                Some(desktop_context::configured_inside_output(
                    position, config.position, size, self.recipe.height, self.recipe.top))
            });
        if within_output != Some(true) {
            if within_output == Some(false) {
                eprintln!("RicePlate: shortcut popup configured outside output work area");
            }
            self.close_desktop_context();
            return;
        }
        let Some(menu) = self.desktop_context.as_mut().filter(|menu|
            &menu.popup == popup) else { return };
        if (config.width, config.height) !=
            (desktop_context::WIDTH as i32, desktop_context::HEIGHT as i32) {
            eprintln!("RicePlate: compositor rejected bounded shortcut popup geometry");
            self.close_desktop_context();
            return;
        }
        if menu.pool.is_none() {
            let bytes = (desktop_context::WIDTH * desktop_context::HEIGHT * 4 * 3) as usize;
            match SlotPool::new(bytes, &self.shm) {
                Ok(pool) => menu.pool = Some(pool),
                Err(error) => {
                    eprintln!("RicePlate: cannot allocate shortcut popup buffer: {error}");
                    self.close_desktop_context();
                    return;
                }
            }
        }
        menu.configured = true;
        if std::env::var_os("RICEBOWL_DE_TRACE_DESKTOP").is_some() {
            eprintln!("RicePlate desktop popup configured size={}x{} at={:?}",
                      config.width, config.height, config.position);
        }
        self.redraw_desktop_context();
    }

    fn done(&mut self, _: &Connection, _: &QueueHandle<Self>, popup: &Popup) {
        if self.desktop_context.as_ref().is_some_and(|menu| &menu.popup == popup) {
            if std::env::var_os("RICEBOWL_DE_TRACE_DESKTOP").is_some() {
                eprintln!("RicePlate desktop popup dismissed by compositor");
            }
            self.close_desktop_context();
        }
    }
}

impl SeatHandler for RicePlate {
    fn seat_state(&mut self) -> &mut SeatState {
        &mut self.seats
    }
    fn new_seat(&mut self, _: &Connection, _: &QueueHandle<Self>, seat: wl_seat::WlSeat) {
        if self.primary_seat.is_none() {
            self.primary_seat = Some(seat);
        }
    }
    fn new_capability(
        &mut self,
        _: &Connection,
        qh: &QueueHandle<Self>,
        seat: wl_seat::WlSeat,
        capability: Capability,
    ) {
        if capability == Capability::Keyboard && self.keyboard.is_none() {
            match self.seats.get_keyboard(qh, &seat, None) {
                Ok(keyboard) => {
                    self.keyboard = Some(keyboard);
                    self.keyboard_seat = Some(seat.clone());
                },
                Err(error) => eprintln!("RicePlate: keyboard unavailable: {error}"),
            }
        }
        if capability == Capability::Pointer && self.pointer.is_none() {
            match self.seats.get_pointer(qh, &seat) {
                Ok(pointer) => {
                    self.pointer = Some(pointer);
                    self.pointer_seat = Some(seat.clone());
                },
                Err(error) => eprintln!("RicePlate: pointer unavailable: {error}"),
            }
        }
    }
    fn remove_capability(
        &mut self,
        _: &Connection,
        qh: &QueueHandle<Self>,
        seat: wl_seat::WlSeat,
        capability: Capability,
    ) {
        let owned_device_removed = (capability == Capability::Pointer
                && self.pointer_seat.as_ref() == Some(&seat))
            || (capability == Capability::Keyboard
                && self.keyboard_seat.as_ref() == Some(&seat));
        if owned_device_removed && self.desktop_context.as_ref()
            .is_some_and(|menu| menu.grab_seat == seat) {
            self.close_desktop_context();
        }
        if capability == Capability::Pointer && self.pointer_seat.as_ref() == Some(&seat) {
            self.pointer_seat = None;
            if let Some(pointer) = self.pointer.take() {
                pointer.release();
            }
            self.icon_drag = None;
            self.desktop_selection.cancel();
            self.save_icon_positions();
        } else if capability == Capability::Keyboard
            && self.keyboard_seat.as_ref() == Some(&seat) {
            self.keyboard_seat = None;
            // A removed keyboard never sends release/modifier updates.
            self.selection_modifiers = Modifiers::default();
            self.desktop_selection.cancel();
            if let Some(keyboard) = self.keyboard.take() {
                keyboard.release();
            }
            self.menu_focused = false;
            self.calendar_focused = false;
            self.keyboard_icon_surface = None;
            self.keyboard_widget_surface = None;
            self.pressed_widget = None;
            self.hovered_widget = None;
            if let Some(index) = self.focused_icon.take() {
                self.redraw_icon(index);
                self.save_icon_positions();
            }
            if let Some(index) = self.focused_widget.take() {
                self.redraw_widget(index);
            }
            self.focused_panel = None;
            self.focused_target = None;
            self.request_redraw(qh);
        }
    }
    fn remove_seat(&mut self, _: &Connection, _: &QueueHandle<Self>, seat: wl_seat::WlSeat) {
        if self.desktop_context.as_ref().is_some_and(|menu| menu.grab_seat == seat) {
            self.close_desktop_context();
        }
        if self.pointer_seat.as_ref() == Some(&seat) { self.pointer_seat = None; }
        if self.keyboard_seat.as_ref() == Some(&seat) { self.keyboard_seat = None; }
        if self.primary_seat.as_ref() == Some(&seat) {
            self.primary_seat = None;
        }
    }
}

impl KeyboardHandler for RicePlate {
    fn enter(
        &mut self,
        _: &Connection,
        qh: &QueueHandle<Self>,
        _: &wl_keyboard::WlKeyboard,
        surface: &wl_surface::WlSurface,
        _: u32,
        _: &[u32],
        _: &[Keysym],
    ) {
        self.luna_dialog_focused = self.luna_dialog.as_ref().is_some_and(|dialog|
            dialog.surface.wl_surface() == surface);
        self.context_focused = self.desktop_context.as_ref().is_some_and(|menu|
            menu.popup.wl_surface() == surface);
        if self.context_focused && std::env::var_os("RICEBOWL_DE_TRACE_DESKTOP").is_some() {
            eprintln!("RicePlate desktop context keyboard focused");
        }
        self.menu_focused = self.menu_state.visible
            && self.active_menu.as_ref() == Some(surface);
        self.calendar_focused = self.calendar_state.visible
            && self.active_calendar.as_ref() == Some(surface);
        self.tray_popup_focused = self.tray_popup_open()
            && self.active_tray_popup.as_ref() == Some(surface);
        if let Some((mirror, width, offset)) = self.panel_geometry(surface) {
            let groups = self.grouped_tasks();
            let active = groups.iter().position(|group| group.active);
            self.focused_panel = Some(surface.clone());
            self.focused_target = task_navigation::initial(
                &self.recipe, width, groups.len(), active, self.tray_keyboard_slots(),
            );
            let next = task_navigation::reveal(
                &self.recipe, width, groups.len(), offset, self.focused_target,
            );
            if let Some(index) = mirror {
                self.mirrors[index].task_offset = next;
            } else {
                self.task_offset = next;
            }
            self.request_redraw(qh);
        } else if self.focused_panel.take().is_some() {
            self.focused_target = None;
            self.request_redraw(qh);
        }
        let next = self.icon_layers.iter()
            .position(|icon| icon.surface.wl_surface() == surface && icon.placed.is_some());
        self.keyboard_icon_surface = next.map(|_| surface.clone());
        if self.focused_icon != next {
            self.desktop_type_select.reset();
            let previous = self.focused_icon;
            self.focused_icon = next;
            // The focused surface is not necessarily selected: pointer focus
            // arrives before the Ctrl-click. Selecting on focus-enter would
            // silently invert a fresh Ctrl-toggle. Pointer press and explicit
            // keyboard navigation own selection changes instead.
            if let Some(index) = previous { self.redraw_icon(index); }
            if let Some(index) = next { self.redraw_icon(index); }
            self.save_icon_positions();
        }
        let next_widget = self.widget_layers.iter().position(|layer|
            layer.surface.wl_surface() == surface && layer.placed.is_some()
                && self.recipe.composition.as_ref().and_then(|composition|
                    composition.widgets.get(layer.recipe_index)).is_some_and(|widget|
                    matches!(&widget.kind, recipe::DesktopWidgetKind::Action(_))));
        self.keyboard_widget_surface = next_widget.map(|_| surface.clone());
        if self.focused_widget != next_widget {
            let previous = self.focused_widget;
            self.focused_widget = next_widget;
            if let Some(index) = previous { self.redraw_widget(index); }
            if let Some(index) = next_widget { self.redraw_widget(index); }
        }
    }

    fn leave(
        &mut self,
        _: &Connection,
        qh: &QueueHandle<Self>,
        _: &wl_keyboard::WlKeyboard,
        surface: &wl_surface::WlSurface,
        _: u32,
    ) {
        // Never retain Ctrl/Shift after compositor keyboard focus leaves.
        self.selection_modifiers = Modifiers::default();
        self.desktop_selection.cancel();
        self.desktop_type_select.reset();
        if self.luna_dialog.as_ref().is_some_and(|dialog|
            dialog.surface.wl_surface() == surface) && self.luna_dialog_focused {
            self.close_luna_dialog();
        }
        if self.desktop_context.as_ref().is_some_and(|menu|
            menu.popup.wl_surface() == surface) && self.context_focused {
            self.close_desktop_context();
        }
        if self.active_menu.as_ref() == Some(surface) && self.menu_focused {
            self.set_menu_visible(false, qh);
        }
        if self.active_calendar.as_ref() == Some(surface) && self.calendar_focused {
            self.set_calendar_visible(false, qh);
        }
        if self.active_tray_popup.as_ref() == Some(surface) && self.tray_popup_focused {
            self.set_tray_popup_visible(false, qh);
        }
        if self.keyboard_icon_surface.as_ref() == Some(surface) {
            self.keyboard_icon_surface = None;
            if let Some(index) = self.focused_icon.take() {
                self.redraw_icon(index);
            }
            self.save_icon_positions();
        }
        if self.keyboard_widget_surface.as_ref() == Some(surface) {
            self.keyboard_widget_surface = None;
            if let Some(index) = self.focused_widget.take() {
                self.redraw_widget(index);
            }
        }
        if self.focused_panel.as_ref() == Some(surface) {
            self.focused_panel = None;
            self.focused_target = None;
            self.request_redraw(qh);
        }
    }

    fn press_key(
        &mut self,
        _: &Connection,
        qh: &QueueHandle<Self>,
        _: &wl_keyboard::WlKeyboard,
        serial: u32,
        event: KeyEvent,
    ) {
        if std::env::var_os("RICEBOWL_DE_TRACE_DESKTOP").is_some() && self.context_focused {
            eprintln!("RicePlate desktop context key utf8_len={:?}",
                      event.utf8.as_deref().map(str::len));
        }
        if self.luna_dialog_focused {
            let mut execute = false;
            let mut repaint = false;
            match event.keysym {
                Keysym::Escape => {
                    self.close_luna_dialog();
                    return;
                }
                Keysym::Return | Keysym::KP_Enter => execute = true,
                Keysym::BackSpace => {
                    if let Some(dialog) = self.luna_dialog.as_mut() {
                        repaint = dialog.state.erase();
                    }
                }
                Keysym::Delete => {
                    if let Some(dialog) = self.luna_dialog.as_mut() {
                        repaint = dialog.state.delete();
                    }
                }
                Keysym::Left | Keysym::Right | Keysym::Home | Keysym::End => {
                    if let Some(dialog) = self.luna_dialog.as_mut() {
                        repaint = dialog.state.move_cursor(match event.keysym {
                            Keysym::Left => luna_dialog::CursorMove::Left,
                            Keysym::Right => luna_dialog::CursorMove::Right,
                            Keysym::Home => luna_dialog::CursorMove::Home,
                            _ => luna_dialog::CursorMove::End,
                        });
                    }
                }
                _ => {
                    if let (Some(dialog), Some(text)) =
                        (self.luna_dialog.as_mut(), event.utf8.as_deref()) {
                        repaint = dialog.state.enter(text);
                    }
                }
            }
            if execute { self.execute_luna_dialog(); }
            else if repaint { self.redraw_luna_dialog(); }
            return;
        }
        if self.context_focused {
            if self.desktop_context.as_ref().is_some_and(|menu| menu.file_operation.is_some()) {
                let mut repaint = false;
                let mut commit_rename = false;
                let mut confirm_trash = false;
                if let Some(menu) = self.desktop_context.as_mut() {
                    match menu.file_operation.as_mut() {
                        Some(desktop_context::FileOperation::Rename(input)) => {
                            match event.keysym {
                                Keysym::Escape => { menu.file_operation = None; repaint = true; }
                                Keysym::Return | Keysym::KP_Enter =>
                                    { commit_rename = true; }
                                Keysym::BackSpace => { repaint = input.erase(); }
                                _ if !self.selection_modifiers.ctrl =>
                                    if let Some(typed) = event.utf8.as_deref() {
                                        repaint = input.insert(typed);
                                    },
                                _ => (),
                            }
                        }
                        Some(desktop_context::FileOperation::ConfirmTrash) => {
                            match event.keysym {
                                Keysym::Escape => { menu.file_operation = None; repaint = true; }
                                Keysym::Return | Keysym::KP_Enter | Keysym::space =>
                                    { confirm_trash = true; }
                                _ => (),
                            }
                        }
                        None => (),
                    }
                }
                if commit_rename { self.commit_file_rename(qh); }
                else if confirm_trash { self.confirm_file_trash(qh); }
                else if repaint { self.redraw_desktop_context(); }
                return;
            }
            if !self.selection_modifiers.ctrl {
                if let Some(typed) = event.utf8.as_deref() {
                    if self.type_select_desktop_context(typed) { return; }
                }
            }
            if self.desktop_context.as_ref().is_some_and(|menu| menu.properties) {
                match event.keysym {
                    Keysym::Escape | Keysym::BackSpace |
                    Keysym::Return | Keysym::KP_Enter | Keysym::space => {
                        if let Some(menu) = self.desktop_context.as_mut() {
                            menu.properties = false;
                            menu.back_hovered = false;
                            menu.back_pressed = false;
                        }
                        self.context_generation = self.context_generation.wrapping_add(1);
                        self.redraw_desktop_context();
                    }
                    _ => {}
                }
                return;
            }
            let mut action = None;
            let mut changed = false;
            match event.keysym {
                Keysym::Escape => {
                    self.close_desktop_context();
                    return;
                }
                Keysym::Up | Keysym::ISO_Left_Tab |
                Keysym::Down | Keysym::Tab => {
                    if let Some(menu) = self.desktop_context.as_mut() {
                        let delta = if matches!(event.keysym, Keysym::Up | Keysym::ISO_Left_Tab) {
                            -1
                        } else { 1 };
                        menu.selected = desktop_context::navigate(
                            menu.selected, delta, menu.can_move, menu.can_reset);
                        changed = true;
                    }
                }
                Keysym::Return | Keysym::KP_Enter | Keysym::space => {
                    action = self.desktop_context.as_ref().map(|menu| menu.selected);
                }
                _ => {}
            }
            if let Some(action) = action { self.choose_desktop_context(action, qh); }
            else if changed { self.redraw_desktop_context(); }
            return;
        }
        if self.tray_popup_state.visible && self.tray_popup_focused {
            let count = self.tray_state.entries.len();
            match event.keysym {
                Keysym::Up | Keysym::ISO_Left_Tab => self.tray_popup_state.select(-1, count),
                Keysym::Down | Keysym::Tab => self.tray_popup_state.select(1, count),
                Keysym::Prior => self.tray_popup_state.page(-1, count),
                Keysym::Next => self.tray_popup_state.page(1, count),
                Keysym::Return | Keysym::KP_Enter | Keysym::space
                    | Keysym::Menu | Keysym::Right => {
                    let index = self.tray_popup_state.selected;
                    let position = self.active_tray_popup.as_ref().map(|surface|
                        self.tray_screen_position(surface, (44.0, 60.0)))
                        .unwrap_or((0, 0));
                    if let Some(surface) = self.active_tray_popup.clone() {
                        let button = if matches!(event.keysym, Keysym::Menu | Keysym::Right) {
                            BTN_RIGHT
                        } else { BTN_LEFT };
                        self.activate_tray_entry(index, button, position, &surface, qh);
                        if !self.tray_menu_state.visible {
                            self.set_tray_popup_visible(false, qh);
                        }
                    }
                    return;
                }
                Keysym::Escape => {
                    self.set_tray_popup_visible(false, qh);
                    return;
                }
                _ => return,
            }
            self.redraw_tray_popup();
            return;
        }
        if self.tray_menu_state.visible && self.tray_popup_focused {
            match event.keysym {
                Keysym::Up | Keysym::ISO_Left_Tab => self.tray_menu_state.select(-1),
                Keysym::Down | Keysym::Tab => self.tray_menu_state.select(1),
                Keysym::Prior => self.tray_menu_state.page(-1),
                Keysym::Next => self.tray_menu_state.page(1),
                Keysym::Return | Keysym::KP_Enter | Keysym::space | Keysym::Right => {
                    self.choose_tray_menu_row(self.tray_menu_state.selected, qh);
                    return;
                }
                Keysym::Left | Keysym::BackSpace => {
                    self.back_tray_menu(qh);
                    return;
                }
                Keysym::Escape => {
                    self.set_tray_popup_visible(false, qh);
                    return;
                }
                _ => return,
            }
            self.redraw_tray_popup();
            return;
        }
        if self.calendar_state.visible && self.calendar_focused {
            match event.keysym {
                Keysym::Left => self.calendar_state.move_selection(-1),
                Keysym::Right => self.calendar_state.move_selection(1),
                Keysym::Up => self.calendar_state.move_selection(-7),
                Keysym::Down => self.calendar_state.move_selection(7),
                Keysym::Prior => self.calendar_state.shift(-1),
                Keysym::Next => self.calendar_state.shift(1),
                Keysym::Home => self.calendar_state.go_today(Local::now().date_naive()),
                Keysym::Escape => {
                    self.set_calendar_visible(false, qh);
                    return;
                }
                _ => return,
            }
            self.redraw_calendar(qh);
            return;
        }
        if self.handle_panel_key(event.keysym, qh) {
            return;
        }
        if let Some(index) = self.focused_icon.filter(|_| self.keyboard_icon_surface.is_some()) {
            match event.keysym {
                Keysym::Tab | Keysym::ISO_Left_Tab => {
                    let output = self.icon_layers[index].bound_output.as_ref();
                    let visible: Vec<_> = self.icon_layers.iter()
                        .map(|icon| icon.placed.is_some() && icon.bound_output.as_ref() == output)
                        .collect();
                    let delta = if event.keysym == Keysym::ISO_Left_Tab { -1 } else { 1 };
                    if let Some(next) = desktop_layout::navigate(&visible, index, delta) {
                        self.focused_icon = Some(next);
                        let mode = if self.selection_modifiers.shift
                            && self.recipe.id == "xp-luna-columns" {
                            desktop_selection::Mode::Range
                        } else { desktop_selection::Mode::Replace };
                        self.select_luna_icon_mode(next, mode);
                        self.redraw_icon(index);
                        self.redraw_icon(next);
                    }
                }
                Keysym::a | Keysym::A if self.selection_modifiers.ctrl
                    && self.recipe.id == "xp-luna-columns" => {
                    self.select_all_luna_icons(index);
                }
                Keysym::space if self.selection_modifiers.ctrl
                    && self.recipe.id == "xp-luna-columns" => {
                    self.select_luna_icon_mode(index, desktop_selection::Mode::Toggle);
                }
                Keysym::F2 if self.recipe.id == "xp-luna-columns"
                    && self.icon_layers[index].recipe_index >= self.static_icon_count => {
                    self.open_desktop_context(index, (52.0, 42.0),
                        self.keyboard_seat.clone().map(|seat| (seat, serial)), qh);
                    self.begin_file_rename();
                }
                Keysym::Delete if self.recipe.id == "xp-luna-columns"
                    && self.icon_layers[index].recipe_index >= self.static_icon_count => {
                    self.open_desktop_context(index, (52.0, 42.0),
                        self.keyboard_seat.clone().map(|seat| (seat, serial)), qh);
                    self.begin_file_trash();
                }
                Keysym::Menu if self.recipe.id == "xp-luna-columns" => {
                    self.open_desktop_context(index, (52.0, 42.0),
                        self.keyboard_seat.clone().map(|seat| (seat, serial)), qh);
                }
                Keysym::F10 if self.recipe.id == "xp-luna-columns"
                    && self.selection_modifiers.shift => {
                    // Standard keyboard equivalent of the context-menu key.
                    // The popup still targets just the focused shortcut.
                    self.open_desktop_context(index, (52.0, 42.0),
                        self.keyboard_seat.clone().map(|seat| (seat, serial)), qh);
                }
                Keysym::Return | Keysym::KP_Enter | Keysym::space => {
                    let action = self.recipe.desktop_icons[self.icon_layers[index].recipe_index]
                        .action.clone();
                    self.activate_action(&action, qh);
                }
                Keysym::Left | Keysym::Right | Keysym::Up | Keysym::Down => {
                    let coords = self.icon_coordinates(index);
                    let (mut x, mut y) = (coords.x, coords.y);
                    match event.keysym {
                        Keysym::Left => x = x.saturating_sub(16),
                        Keysym::Right => x = x.saturating_add(16).min(desktop_layout::MAX_SAVED_POSITION),
                        Keysym::Up => y = y.saturating_sub(16),
                        Keysym::Down => y = y.saturating_add(16).min(desktop_layout::MAX_SAVED_POSITION),
                        _ => unreachable!(),
                    }
                    self.move_icon(index, (x, y));
                }
                Keysym::F6 => self.assign_icon_to_next_output(index),
                Keysym::F7 => self.mirror_icon_on_all_outputs(index),
                Keysym::Escape => {
                    self.clear_luna_selection();
                    self.save_icon_positions();
                }
                _ => {}
            }
            return;
        }
        if let Some(index) = self.focused_widget.filter(|_| self.keyboard_widget_surface.is_some()) {
            match event.keysym {
                Keysym::Tab | Keysym::ISO_Left_Tab => {
                    let output = self.widget_layers[index].bound_output.as_ref();
                    let visible: Vec<_> = self.widget_layers.iter().enumerate()
                        .map(|(candidate, layer)| layer.bound_output.as_ref() == output
                            && self.widget_action(candidate).is_some()).collect();
                    let delta = if event.keysym == Keysym::ISO_Left_Tab { -1 } else { 1 };
                    if let Some(next) = desktop_layout::navigate(&visible, index, delta) {
                        self.focused_widget = Some(next);
                        self.redraw_widget(index);
                        self.redraw_widget(next);
                    }
                }
                Keysym::Return | Keysym::KP_Enter | Keysym::space => {
                    if let Some(action) = self.widget_action(index).map(str::to_owned) {
                        if self.desktop_action_enabled(&action) {
                            self.activate_action(&action, qh);
                        }
                    }
                }
                _ => {}
            }
            return;
        }
        if !self.menu_state.visible || !self.menu_focused {
            return;
        }
        if self.notification_state.open {
            let size = self.active_menu_size();
            let compact = native_menu::compact_layout(size);
            let page_rows = if compact { ricepop::compact_rows(size) }
                            else { ricepop::VISIBLE_ROWS };
            let page_actions = if compact { ricepop::compact_action_rows(size) }
                               else { ricepop::VISIBLE_ROWS };
            let detail = self.notification_state.detail_id.is_some();
            match event.keysym {
                Keysym::Escape | Keysym::BackSpace => {
                    if detail { self.notification_state.close_detail(); }
                    else { self.notification_state.close(); }
                }
                Keysym::Left if !detail => self.notification_state.select_tab(false),
                Keysym::Right if !detail => self.notification_state.select_tab(true),
                Keysym::Left if detail => {
                    if compact { self.notification_state.change_compact_body_page(-1, size); }
                    else { self.notification_state.change_body_page(-1); }
                }
                Keysym::Right if detail => {
                    if compact { self.notification_state.change_compact_body_page(1, size); }
                    else { self.notification_state.change_body_page(1); }
                }
                Keysym::Up => {
                    if detail { self.notification_state.select_action(-1); }
                    else { self.notification_state.select(-1); }
                }
                Keysym::Down | Keysym::Tab => {
                    if detail { self.notification_state.select_action(1); }
                    else { self.notification_state.select(1); }
                }
                Keysym::ISO_Left_Tab => {
                    if detail { self.notification_state.select_action(-1); }
                    else { self.notification_state.select(-1); }
                }
                Keysym::Prior => {
                    if detail { self.notification_state.select_action(-(page_actions as isize)); }
                    else { self.notification_state.select(-(page_rows as isize)); }
                }
                Keysym::Next => {
                    if detail { self.notification_state.select_action(page_actions as isize); }
                    else { self.notification_state.select(page_rows as isize); }
                }
                Keysym::r | Keysym::R => {
                    self.request_notifications(NotificationIntent::Refresh, qh);
                    return;
                }
                Keysym::Delete => {
                    if let Some(id) = self.notification_state.selected_id() {
                        self.request_notifications(NotificationIntent::Dismiss(id), qh);
                    }
                    return;
                }
                Keysym::Return | Keysym::KP_Enter => {
                    if detail {
                        if let Some((id, key)) = self.notification_state.selected_action()
                            .map(|(id, action)| (id, action.key.clone())) {
                            self.request_notifications(NotificationIntent::Invoke(id, key), qh);
                        }
                        return;
                    }
                    self.notification_state.open_detail(self.notification_state.selected);
                }
                _ => return,
            }
            self.redraw_menu(qh);
            return;
        }
        let Some(menu) = self.recipe.menu.as_ref() else {
            return;
        };
        let active_compact = self.active_menu.as_ref()
            .and_then(|active| self.menu_layer.iter().chain(self.menu_mirrors.iter())
                .find(|layer| layer.surface.wl_surface() == active))
            .filter(|layer| native_menu::compact_layout(layer.size))
            .map(|layer| native_menu::compact_visible_actions(layer.size));
        let visible_rows = active_compact.unwrap_or(native_menu::VISIBLE_ACTIONS);
        let action = match event.keysym {
            Keysym::Escape => {
                if self.menu_state.back() { None } else {
                    self.set_menu_visible(false, qh);
                    return;
                }
            }
            Keysym::BackSpace => {
                self.menu_state.backspace();
                None
            }
            Keysym::F2 => {
                toggle_menu_pin(&mut self.menu_state, &self.recipe.id, menu);
                None
            }
            Keysym::F3 => {
                self.menu_state.show_saved();
                None
            }
            Keysym::slash => {
                self.menu_state.start_search();
                None
            }
            Keysym::Up => {
                self.menu_state.select_by(menu, -1);
                None
            }
            Keysym::Down | Keysym::Tab => {
                self.menu_state.select_by(menu, 1);
                None
            }
            Keysym::ISO_Left_Tab => {
                self.menu_state.select_by(menu, -1);
                None
            }
            Keysym::Home => {
                self.menu_state.select_edge(menu, false);
                None
            }
            Keysym::End => {
                self.menu_state.select_edge(menu, true);
                None
            }
            Keysym::Prior => {
                self.menu_state.page_by(menu, -(visible_rows as isize));
                None
            }
            Keysym::Next => {
                self.menu_state.page_by(menu, visible_rows as isize);
                None
            }
            Keysym::Left => {
                if active_compact.is_some() { self.menu_state.group_by(menu, -1); }
                else { self.menu_state.horizontal_by(menu, -1); }
                None
            }
            Keysym::Right => {
                if active_compact.is_some() { self.menu_state.group_by(menu, 1); }
                else { self.menu_state.horizontal_by(menu, 1); }
                None
            }
            Keysym::space if matches!(self.menu_state.view,
                    native_menu::View::Search | native_menu::View::Programs) => {
                self.menu_state.search_input(" ");
                None
            }
            Keysym::Return | Keysym::KP_Enter | Keysym::space => {
                self.menu_state.current_action(menu).map(str::to_owned)
            }
            _ => {
                if !event.utf8.as_deref().is_some_and(|input| self.menu_state.search_input(input)) {
                    return;
                }
                None
            }
        };
        if let Some(action) = action {
            self.activate_menu_action(&action, qh);
        } else {
            self.redraw_menu(qh);
        }
    }

    fn repeat_key(
        &mut self,
        conn: &Connection,
        qh: &QueueHandle<Self>,
        keyboard: &wl_keyboard::WlKeyboard,
        serial: u32,
        event: KeyEvent,
    ) {
        // Never repeat Enter/Space: holding a key must not launch multiple apps.
        if matches!(event.keysym, Keysym::Left | Keysym::Right | Keysym::Up
            | Keysym::Down | Keysym::Tab | Keysym::ISO_Left_Tab)
            || (self.luna_dialog_focused
                && matches!(event.keysym, Keysym::BackSpace | Keysym::Delete)) {
            self.press_key(conn, qh, keyboard, serial, event);
        }
    }

    fn release_key(
        &mut self,
        _: &Connection,
        _: &QueueHandle<Self>,
        _: &wl_keyboard::WlKeyboard,
        _: u32,
        event: KeyEvent,
    ) {
        if matches!(event.keysym, Keysym::Left | Keysym::Right | Keysym::Up | Keysym::Down) {
            self.save_icon_positions();
        }
    }

    fn update_modifiers(
        &mut self,
        _: &Connection,
        _: &QueueHandle<Self>,
        _: &wl_keyboard::WlKeyboard,
        _: u32,
        modifiers: Modifiers,
        _: RawModifiers,
        _: u32,
    ) {
        self.selection_modifiers = modifiers;
        // A held Ctrl/Shift modifier invalidates any pending plain double
        // click even if the focus stays on the same shortcut.
        if modifiers.ctrl || modifiers.shift {
            self.desktop_selection.cancel();
        }
    }
}

impl PointerHandler for RicePlate {
    fn pointer_frame(
        &mut self,
        _: &Connection,
        qh: &QueueHandle<Self>,
        _: &wl_pointer::WlPointer,
        events: &[PointerEvent],
    ) {
        for event in events {
            // A popup Enter is authoritative Wayland evidence that the
            // pointer is no longer over the taskbar. Compositors need not
            // deliver the previous panel Leave before transferring focus
            // between separately managed layer-shell surfaces.
            if self.luna_options.auto_hide
                && matches!(event.kind, PointerEventKind::Enter { .. }
                    | PointerEventKind::Motion { .. })
                && (self.active_menu.as_ref() == Some(&event.surface)
                    || self.active_calendar.as_ref() == Some(&event.surface)
                    || self.active_tray_popup.as_ref() == Some(&event.surface)
                    || self.luna_dialog.as_ref().is_some_and(|dialog|
                        dialog.surface.wl_surface() == &event.surface))
            {
                self.panel_pointer_inside = false;
            }
            if self.luna_dialog.as_ref().is_some_and(|dialog|
                dialog.surface.wl_surface() == &event.surface) {
                let mut activate = None;
                let mut repaint = false;
                if let Some(dialog) = self.luna_dialog.as_mut() {
                    let hit = luna_dialog::hit(event.position.0, event.position.1,
                                               dialog.state.kind);
                    match event.kind {
                        PointerEventKind::Enter { .. } | PointerEventKind::Motion { .. } => {
                            if dialog.state.hover != hit {
                                dialog.state.hover = hit;
                                repaint = true;
                            }
                        }
                        PointerEventKind::Leave { .. } => {
                            dialog.state.hover = None;
                            dialog.state.pressed = None;
                            repaint = true;
                        }
                        PointerEventKind::Press { button: BTN_LEFT, .. } => {
                            dialog.state.pressed = hit;
                            repaint = true;
                        }
                        PointerEventKind::Release { button: BTN_LEFT, .. } => {
                            if dialog.state.pressed.take().is_some_and(|start| Some(start) == hit) {
                                activate = hit;
                            } else { repaint = true; }
                        }
                        _ => {}
                    }
                }
                match activate {
                    Some(luna_dialog::Hit::Accept) => self.execute_luna_dialog(),
                    Some(luna_dialog::Hit::Cancel) => self.close_luna_dialog(),
                    Some(luna_dialog::Hit::Input) | None =>
                        if repaint { self.redraw_luna_dialog(); },
                }
                continue;
            }
            if self.desktop_context.as_ref().is_some_and(|menu|
                menu.popup.wl_surface() == &event.surface) {
                let mut activate = None;
                let mut repaint = false;
                if let Some(menu) = self.desktop_context.as_mut() {
                    if menu.properties {
                        let back = desktop_context::back_hit(
                            event.position.0, event.position.1);
                        match event.kind {
                            PointerEventKind::Enter { .. } | PointerEventKind::Motion { .. } => {
                                if menu.back_hovered != back {
                                    menu.back_hovered = back;
                                    repaint = true;
                                }
                            }
                            PointerEventKind::Leave { .. } => {
                                menu.back_hovered = false;
                                menu.back_pressed = false;
                                repaint = true;
                            }
                            PointerEventKind::Press { button: BTN_LEFT, .. } => {
                                menu.back_pressed = back;
                            }
                            PointerEventKind::Release { button: BTN_LEFT, .. } => {
                                if menu.back_pressed && back {
                                    menu.properties = false;
                                    menu.back_hovered = false;
                                    self.context_generation = self.context_generation.wrapping_add(1);
                                    repaint = true;
                                }
                                menu.back_pressed = false;
                            }
                            _ => {}
                        }
                    } else {
                        let hit = desktop_context::hit(event.position.0, event.position.1)
                            .filter(|action| action.enabled(menu.can_move, menu.can_reset));
                        match event.kind {
                            PointerEventKind::Enter { .. } | PointerEventKind::Motion { .. } => {
                                if menu.hovered != hit {
                                    menu.hovered = hit;
                                    repaint = true;
                                }
                            }
                            PointerEventKind::Leave { .. } => {
                                menu.hovered = None;
                                menu.pressed = None;
                                repaint = true;
                            }
                            PointerEventKind::Press { button: BTN_LEFT, .. } => {
                                menu.pressed = hit;
                                if let Some(selected) = hit {
                                    menu.selected = selected;
                                    repaint = true;
                                }
                            }
                            PointerEventKind::Release { button: BTN_LEFT, .. } => {
                                if menu.pressed.take().is_some_and(|pressed| Some(pressed) == hit) {
                                    activate = hit;
                                } else {
                                    repaint = true;
                                }
                            }
                            _ => {}
                        }
                    }
                }
                if let Some(action) = activate {
                    self.choose_desktop_context(action, qh);
                } else if repaint {
                    self.redraw_desktop_context();
                }
                continue;
            }
            if self.active_tray_popup.as_ref() == Some(&event.surface) {
                if self.tray_menu_state.visible {
                    match event.kind {
                        PointerEventKind::Press { button: BTN_LEFT | BTN_RIGHT, .. } => {
                            match self.tray_menu_state.hit(event.position.0, event.position.1) {
                                Some(TrayMenuHit::Row(index)) =>
                                    self.choose_tray_menu_row(index, qh),
                                Some(TrayMenuHit::Back) => self.back_tray_menu(qh),
                                Some(TrayMenuHit::Close) =>
                                    self.set_tray_popup_visible(false, qh),
                                Some(TrayMenuHit::Previous) => {
                                    self.tray_menu_state.page(-1);
                                    self.redraw_tray_popup();
                                }
                                Some(TrayMenuHit::Next) => {
                                    self.tray_menu_state.page(1);
                                    self.redraw_tray_popup();
                                }
                                None => {}
                            }
                        }
                        PointerEventKind::Motion { .. } => {
                            if let Some(TrayMenuHit::Row(index)) =
                                self.tray_menu_state.hit(event.position.0, event.position.1) {
                                if self.tray_menu_state.rows().get(index).is_some_and(|r|
                                    r.selectable()) && self.tray_menu_state.selected != index {
                                    self.tray_menu_state.selected = index;
                                    if let Some(host) = self.tray_host.as_mut() {
                                        let id = self.tray_menu_state.rows()[index].id;
                                        if let Err(error) = host.menu_hovered(
                                            &self.tray_menu_state.bus_name, id) {
                                            eprintln!("RicePlate: SNI menu hover failed: {error}");
                                        }
                                    }
                                    self.redraw_tray_popup();
                                }
                            }
                        }
                        _ => {}
                    }
                    continue;
                }
                if let PointerEventKind::Press { button, .. } = event.kind {
                    if button != BTN_LEFT && button != BTN_RIGHT { continue; }
                    let count = self.tray_state.entries.len();
                    match self.tray_popup_state.hit(event.position.0, event.position.1, count) {
                        Some(TrayHit::Item(index)) => {
                            let coords = self.tray_screen_position(&event.surface, event.position);
                            self.activate_tray_entry(index, button, coords, &event.surface, qh);
                            if !self.tray_menu_state.visible {
                                self.set_tray_popup_visible(false, qh);
                            }
                        }
                        Some(TrayHit::Previous) => {
                            self.tray_popup_state.page(-1, count);
                            self.redraw_tray_popup();
                        }
                        Some(TrayHit::Next) => {
                            self.tray_popup_state.page(1, count);
                            self.redraw_tray_popup();
                        }
                        Some(TrayHit::Close) => self.set_tray_popup_visible(false, qh),
                        None => {}
                    }
                }
                continue;
            }
            if self.active_calendar.as_ref() == Some(&event.surface) {
                if let PointerEventKind::Press { button: BTN_LEFT, .. } = event.kind {
                    match self.calendar_state.hit(event.position.0, event.position.1) {
                        Some(CalendarHit::Previous) => self.calendar_state.shift(-1),
                        Some(CalendarHit::Next) => self.calendar_state.shift(1),
                        Some(CalendarHit::Today) => {
                            self.calendar_state.go_today(Local::now().date_naive());
                        }
                        Some(CalendarHit::Day(day)) => self.calendar_state.select(day),
                        None => continue,
                    }
                    self.redraw_calendar(qh);
                }
                continue;
            }
            if self.active_menu.as_ref() == Some(&event.surface) {
                let menu_size = self.menu_layer.iter().chain(self.menu_mirrors.iter())
                    .find(|layer| layer.surface.wl_surface() == &event.surface)
                    .map_or((native_menu::WIDTH, native_menu::HEIGHT), |layer| layer.size);
                let compact = native_menu::compact_layout(menu_size);
                let pointer = if compact { event.position }
                              else { native_menu::input_coords(event.position, menu_size) };
                if let PointerEventKind::Axis { vertical, .. } = event.kind {
                    if self.notification_state.open {
                        if self.notification_state.scroll_at(pointer.0, pointer.1,
                            vertical.discrete, vertical.absolute,
                            if compact { Some(menu_size) } else { None }) {
                            self.redraw_menu(qh);
                        }
                    } else {
                        let body_top = if compact { native_menu::COMPACT_ACTION_TOP }
                                       else { native_menu::ACTION_TOP };
                        let footer = if compact { native_menu::COMPACT_FOOTER_HEIGHT }
                                     else { 28 };
                        let bottom = (if compact { menu_size.1 } else { native_menu::HEIGHT })
                            .saturating_sub(footer);
                        if pointer.1 >= f64::from(body_top) && pointer.1 < f64::from(bottom) {
                            if let Some(menu) = self.recipe.menu.as_ref() {
                                let rows = if compact {
                                    native_menu::compact_visible_actions(menu_size)
                                } else { native_menu::VISIBLE_ACTIONS };
                                if self.menu_state.scroll_pages(menu, vertical.discrete,
                                                                vertical.absolute, rows) {
                                    self.redraw_menu(qh);
                                }
                            }
                        }
                    }
                    continue;
                }
                // A pointer leaving the menu must not strand a lit footer
                // button when another window or output takes the hover.
                if matches!(event.kind, PointerEventKind::Leave { .. }) {
                    if self.menu_state.footer_hover.take().is_some() {
                        self.redraw_menu(qh);
                    }
                    continue;
                }
                // Hover and keyboard selection share one state. Update only
                // on a changed action to avoid repainting on every motion.
                if matches!(event.kind, PointerEventKind::Motion { .. })
                    && !self.notification_state.open {
                    if let Some(menu) = self.recipe.menu.as_ref() {
                        let hit = if compact {
                            self.menu_state.compact_hit(menu, pointer.0, pointer.1, menu_size)
                        } else { self.menu_state.hit(menu, pointer.0, pointer.1) };
                        let hovered = if !compact && menu.presentation == recipe::MenuPresentation::Columns
                            && menu.palette.is_some() {
                            match hit {
                                Some(MenuHit::FooterLock | MenuHit::FooterLogout | MenuHit::Close)
                                    => hit,
                                _ => None,
                            }
                        } else { None };
                        let mut changed = self.menu_state.footer_hover != hovered;
                        self.menu_state.footer_hover = hovered;
                        if let Some(MenuHit::Action(index)) = hit {
                            if self.menu_state.selected != index {
                                self.menu_state.selected = index;
                                changed = true;
                            }
                        }
                        if changed { self.redraw_menu(qh); }
                    }
                    continue;
                }
                // Right-click pins a real action without executing it, and
                // right-clicking an entry inside Saved removes the pin. Use
                // the same validated, rollback-safe storage path as F2.
                if let PointerEventKind::Press { button: BTN_RIGHT, .. } = event.kind {
                    if !self.notification_state.open {
                        if let Some(menu) = self.recipe.menu.as_ref() {
                            let hit = if compact {
                                self.menu_state.compact_hit(menu, pointer.0, pointer.1, menu_size)
                            } else { self.menu_state.hit(menu, pointer.0, pointer.1) };
                            if let Some(MenuHit::Action(index)) = hit {
                                self.menu_state.selected = index;
                                toggle_menu_pin(&mut self.menu_state, &self.recipe.id, menu);
                                self.redraw_menu(qh);
                            }
                        }
                    }
                    continue;
                }
                if let PointerEventKind::Press {
                    button: BTN_LEFT, ..
                } = event.kind
                {
                    if self.notification_state.open {
                        match if compact { self.notification_state.compact_hit(
                            pointer.0, pointer.1, menu_size) }
                            else { self.notification_state.hit(pointer.0, pointer.1) } {
                            Some(ricepop::Hit::Row(index)) => {
                                self.notification_state.open_detail(index);
                                self.redraw_menu(qh);
                            }
                            Some(ricepop::Hit::Action(index)) => {
                                if let Some((id, key)) = self.notification_state.action_at(index)
                                    .map(|(id, action)| (id, action.key.clone())) {
                                    self.request_notifications(NotificationIntent::Invoke(id, key), qh);
                                }
                            }
                            Some(ricepop::Hit::BodyPage(delta)) => {
                                if compact {
                                    self.notification_state.change_compact_body_page(delta, menu_size);
                                } else { self.notification_state.change_body_page(delta); }
                                self.redraw_menu(qh);
                            }
                            Some(ricepop::Hit::Tab(history)) => {
                                self.notification_state.select_tab(history);
                                self.redraw_menu(qh);
                            }
                            Some(ricepop::Hit::Back) => {
                                if self.notification_state.detail_id.is_some() {
                                    self.notification_state.close_detail();
                                } else {
                                    self.notification_state.close();
                                }
                                self.redraw_menu(qh);
                            }
                            Some(ricepop::Hit::Refresh) => self.request_notifications(NotificationIntent::Refresh, qh),
                            Some(ricepop::Hit::Dismiss) => {
                                if let Some(id) = self.notification_state.selected_id() {
                                    self.request_notifications(NotificationIntent::Dismiss(id), qh);
                                }
                            }
                            None => {}
                        }
                        continue;
                    }
                    if let Some(menu) = self.recipe.menu.as_ref() {
                        match if compact {
                            self.menu_state.compact_hit(menu, pointer.0, pointer.1, menu_size)
                        } else { self.menu_state.hit(menu, pointer.0, pointer.1) } {
                            Some(MenuHit::Search) => {
                                self.menu_state.search_button();
                                self.redraw_menu(qh);
                            }
                            Some(MenuHit::Saved) => {
                                self.menu_state.show_saved();
                                self.redraw_menu(qh);
                            }
                            Some(MenuHit::Group(index)) => {
                                self.menu_state.select_group(menu, index);
                                self.redraw_menu(qh);
                            }
                            Some(MenuHit::Action(index)) => {
                                self.menu_state.selected = index;
                                if let Some(action) = self.menu_state.current_action(menu).map(str::to_owned) {
                                    self.activate_menu_action(&action, qh);
                                }
                            }
                            Some(MenuHit::Close) => self.set_menu_visible(false, qh),
                            Some(MenuHit::FooterLock) if !compact => {
                                self.activate_action("lock", qh);
                            }
                            Some(MenuHit::FooterLogout) if !compact => {
                                if logout_available() {
                                    self.activate_action("logout", qh);
                                }
                            }
                            Some(MenuHit::FooterLock | MenuHit::FooterLogout) => {},
                            None => {}
                        }
                    }
                }
                continue;
            }
            if let Some(index) = self
                .icon_layers
                .iter()
                .position(|icon| &event.surface == icon.surface.wl_surface())
            {
                if self.icon_layers[index].placed.is_none() {
                    continue;
                }
                match event.kind {
                    PointerEventKind::Press { button: BTN_RIGHT, serial, .. } => {
                        self.open_desktop_context(index, event.position,
                            self.pointer_seat.clone().map(|seat| (seat, serial)), qh);
                    }
                    PointerEventKind::Press { button: BTN_LEFT, .. } => {
                        self.close_desktop_context();
                        let mode = if self.recipe.id == "xp-luna-columns" {
                            if self.selection_modifiers.ctrl {
                                desktop_selection::Mode::Toggle
                            } else if self.selection_modifiers.shift {
                                desktop_selection::Mode::Range
                            } else { desktop_selection::Mode::Replace }
                        } else { desktop_selection::Mode::Replace };
                        self.select_luna_icon_mode(index, mode);
                        // Modified selections are not draggable and never
                        // count toward the plain double-click launch sequence.
                        self.icon_drag = None;
                        if mode == desktop_selection::Mode::Replace {
                            if let Some(position) = self.icon_layers[index].placed {
                                self.icon_drag = Some(IconDrag {
                                    index, anchor: event.position, started: position, moved: false,
                                    original_positions: self.icon_outputs.clone(),
                                });
                            }
                        }
                    }
                    PointerEventKind::Motion { .. } => {
                        if let Some(drag) = self.icon_drag.as_mut().filter(|d| d.index == index) {
                            let current = self.icon_layers[index].placed.unwrap();
                            let desired = desktop_layout::dragged_to(
                                current, drag.anchor, event.position,
                            );
                            if desired.0.abs_diff(drag.started.0)
                                + desired.1.abs_diff(drag.started.1) >= 6
                            {
                                drag.moved = true;
                            }
                            if drag.moved && desired != current {
                                self.move_icon(index, desired);
                            }
                        }
                    }
                    PointerEventKind::Release { button: BTN_LEFT, .. } => {
                        if let Some(drag) = self.icon_drag.take() {
                            if drag.index == index && !drag.moved {
                                // XP native-only: a first click selects, a
                                // second short click opens. Keyboard/AT-SPI
                                // activation remains immediate.
                                let open = if self.recipe.id == "xp-luna-columns" {
                                    self.desktop_selection.release(index, event.position, Instant::now())
                                } else { true };
                                if open {
                                    let action = self.recipe.desktop_icons[
                                        self.icon_layers[index].recipe_index].action.clone();
                                    self.activate_action(&action, qh);
                                }
                            } else if drag.index == index {
                                self.desktop_selection.cancel();
                                if !self.finish_cross_output_drag(&drag, event.position) {
                                    self.save_icon_positions();
                                }
                            }
                        }
                    }
                    _ => {}
                }
                continue;
            }
            if let Some(index) = self.widget_layers.iter().position(|layer|
                &event.surface == layer.surface.wl_surface()) {
                // Read-only widget input regions are empty. Only declared
                // actions reach this branch from the compositor.
                let inside = event.position.0 >= 0.0 && event.position.1 >= 0.0
                    && event.position.0 < f64::from(recipe::DESKTOP_WIDGET_WIDTH)
                    && event.position.1 < f64::from(recipe::DESKTOP_WIDGET_HEIGHT);
                match event.kind {
                    PointerEventKind::Enter { .. } | PointerEventKind::Motion { .. } => {
                        let next = inside.then_some(index);
                        if self.hovered_widget != next {
                            let previous = self.hovered_widget;
                            self.hovered_widget = next;
                            if let Some(old) = previous { self.redraw_widget(old); }
                            self.redraw_widget(index);
                        }
                    }
                    PointerEventKind::Leave { .. } => {
                        if self.hovered_widget == Some(index) {
                            self.hovered_widget = None;
                            self.redraw_widget(index);
                        }
                    }
                    PointerEventKind::Press { button: BTN_LEFT, .. } => {
                        self.pressed_widget = self.widget_action(index)
                            .filter(|action| inside && self.desktop_action_enabled(action))
                            .map(|_| index);
                    }
                    PointerEventKind::Release { button: BTN_LEFT, .. } => {
                        if self.pressed_widget.take() == Some(index) && inside {
                            if let Some(action) = self.widget_action(index).map(str::to_owned) {
                                if self.desktop_action_enabled(&action) {
                                    self.activate_action(&action, qh);
                                }
                            }
                        }
                    }
                    _ => {}
                }
                continue;
            }
            let mirror_index = self.mirrors.iter().position(|mirror|
                &event.surface == mirror.surface.wl_surface());
            let (panel_width, panel_height, panel_offset) = if let Some(index) = mirror_index {
                let mirror = &self.mirrors[index];
                (mirror.width, mirror.height, mirror.task_offset)
            } else if &event.surface == self.layer.wl_surface() {
                (self.width, self.height, self.task_offset)
            } else { continue; };
            if self.luna_options.auto_hide && self.recipe.id == "xp-luna-columns" {
                match event.kind {
                    PointerEventKind::Enter { .. } | PointerEventKind::Motion { .. } => {
                        self.panel_pointer_inside = true;
                        if self.panel_collapsed {
                            self.set_panel_collapsed(false, qh);
                            // A 3px reveal handle cannot activate controls.
                            continue;
                        }
                    }
                    PointerEventKind::Leave { .. } => {
                        self.panel_pointer_inside = false;
                        self.maybe_collapse_luna_panel(qh);
                        if self.panel_collapsed { continue; }
                    }
                    _ => {}
                }
                if panel_height < self.recipe.height { continue; }
            }
            // Physical feedback is per surface, while the shared recipe hit
            // geometry stays authoritative for actual activation.
            if self.recipe.id == "xp-luna-columns" {
                let hit = luna_hover_target(input_core::panel_hit(
                    &self.recipe, panel_width, panel_height, event.position,
                    self.cached_task_group_count, panel_offset));
                let signal = match event.kind {
                    PointerEventKind::Enter { .. } | PointerEventKind::Motion { .. } =>
                        Some(PointerSignal::Hover),
                    PointerEventKind::Leave { .. } => Some(PointerSignal::Leave),
                    PointerEventKind::Press { button: BTN_LEFT, .. } =>
                        Some(PointerSignal::Press),
                    PointerEventKind::Release { button: BTN_LEFT, .. } =>
                        Some(PointerSignal::Release),
                    _ => None,
                };
                if signal.is_some_and(|signal| input_core::update_feedback(
                    &mut self.hovered_panel, &mut self.pressed_panel,
                    &event.surface, hit, signal)) {
                    self.request_redraw(qh);
                }
            }
            if let PointerEventKind::Press { button, .. } = event.kind {
                if (button == BTN_LEFT || button == BTN_RIGHT)
                    && event.position.1 >= 0.0
                    && event.position.1 < f64::from(panel_height)
                {
                    if button == BTN_LEFT {
                        self.close_desktop_context();
                        self.clear_luna_selection();
                    }
                    let groups = self.grouped_tasks();
                    match input_core::panel_hit(
                        &self.recipe, panel_width, panel_height, event.position,
                        groups.len(), panel_offset,
                    ) {
                        Some(Hit::Tray(slot)) => {
                            if slot == tray::VISIBLE_ITEMS - 1 &&
                                self.tray_state.overflow_count() > 0 {
                                self.toggle_tray_popup_for_panel(mirror_index, qh);
                            } else {
                                let coords = self.tray_screen_position(&event.surface, event.position);
                                self.activate_tray_item(slot, button, coords, &event.surface, qh);
                            }
                        }
                        Some(Hit::Status(widget)) => {
                            self.open_luna_status_menu(widget, &event.surface, qh);
                        }
                        Some(Hit::Clock) if button == BTN_RIGHT
                            && self.recipe.id == "xp-luna-columns" => {
                            self.open_luna_status_menu(Widget::Clock, &event.surface, qh);
                        }
                        _ if button == BTN_RIGHT => {
                            if self.recipe.id == "xp-luna-columns" {
                                // Right-clicking empty taskbar/task buttons opens
                                // the existing genuine RiceSpice taskbar page.
                                // Provider-owned tray and clock menus win above.
                                self.launch_luna_settings("taskbar");
                            }
                        },
                        Some(Hit::Launcher) => {
                            if self.focused_panel.as_ref() == Some(&event.surface) {
                                self.focused_target = Some(KeyboardTarget::Launcher);
                                self.request_redraw(qh);
                            }
                            self.activate_launcher(mirror_index, qh);
                        }
                        Some(Hit::Action(index)) => {
                            if self.focused_panel.as_ref() == Some(&event.surface) {
                                self.focused_target = Some(KeyboardTarget::Action(index));
                                self.request_redraw(qh);
                            }
                            if let Some(action) = self.recipe.actions.get(index as usize) {
                                let action_id = action.id.clone();
                                self.activate_action(&action_id, qh);
                            }
                        }
                        Some(Hit::Clock) => {
                            if button == BTN_LEFT {
                                self.toggle_calendar_for_panel(mirror_index, qh);
                            }
                        }
                        Some(Hit::Task(index)) => {
                            if self.focused_panel.as_ref() == Some(&event.surface) {
                                self.focused_target = Some(KeyboardTarget::Task(index));
                                self.request_redraw(qh);
                            }
                            self.activate_group(index);
                        }
                        Some(Hit::PreviousTasks) => {
                            if let Some(view) = recipe::task_view(
                                &self.recipe,
                                panel_width,
                                groups.len(),
                                panel_offset,
                            ) {
                                let next = view.start.saturating_sub(view.slots);
                                if let Some(index) = mirror_index {
                                    self.mirrors[index].task_offset = next;
                                } else { self.task_offset = next; }
                                self.request_redraw(qh);
                            }
                        }
                        Some(Hit::NextTasks) => {
                            if let Some(view) = recipe::task_view(
                                &self.recipe,
                                panel_width,
                                groups.len(),
                                panel_offset,
                            ) {
                                let next = (view.start + view.slots)
                                    .min(groups.len().saturating_sub(view.slots));
                                if let Some(index) = mirror_index {
                                    self.mirrors[index].task_offset = next;
                                } else { self.task_offset = next; }
                                self.request_redraw(qh);
                            }
                        }
                        None => {}
                    }
                }
            }
        }
    }
}

impl Dispatch<ZwlrForeignToplevelManagerV1, ()> for RicePlate {
    fn event(
        state: &mut Self,
        _: &ZwlrForeignToplevelManagerV1,
        event: zwlr_foreign_toplevel_manager_v1::Event,
        _: &(),
        _: &Connection,
        qh: &QueueHandle<Self>,
    ) {
        match event {
            zwlr_foreign_toplevel_manager_v1::Event::Toplevel { toplevel } => {
                if state.tasks.len() >= recipe::MAX_TRACKED_TASKS {
                    toplevel.destroy();
                } else {
                    state.tasks.push(Task {
                        handle: toplevel,
                        title: String::new(),
                        app_id: String::new(),
                        active: false,
                        minimized: false,
                        ready: false,
                    });
                }
            }
            zwlr_foreign_toplevel_manager_v1::Event::Finished => {
                if state.trace_window_events {
                    eprintln!("RicePlate window event=manager-finished");
                }
                state.toplevel_manager = None;
                state.tasks.clear();
                state.show_desktop_restore.clear();
                state.task_offset = 0;
                state.request_redraw(qh);
            }
            _ => {}
        }
    }

    // The compositor creates a new handle in the `toplevel` *event*.
    // Without an event-created-child specialization, wayland-client panics
    // before our event handler can add the first real application window.
    wayland_client::event_created_child!(RicePlate, ZwlrForeignToplevelManagerV1, [
        zwlr_foreign_toplevel_manager_v1::EVT_TOPLEVEL_OPCODE => (ZwlrForeignToplevelHandleV1, ()),
    ]);
}

impl Dispatch<ZwlrForeignToplevelHandleV1, ()> for RicePlate {
    fn event(
        state: &mut Self,
        proxy: &ZwlrForeignToplevelHandleV1,
        event: zwlr_foreign_toplevel_handle_v1::Event,
        _: &(),
        _: &Connection,
        qh: &QueueHandle<Self>,
    ) {
        if let zwlr_foreign_toplevel_handle_v1::Event::Closed = event {
            if let Some(index) = state.tasks.iter().position(|task| task.handle == *proxy) {
                if state.trace_window_events {
                    eprintln!("RicePlate window event=closed app_id={:?}", state.tasks[index].app_id);
                }
                state.tasks.remove(index).handle.destroy();
                // The restore transaction must never retain a destroyed
                // compositor proxy after a client exits.
                state.show_desktop_restore.retain(|handle| handle != proxy);
                state.task_offset = state
                    .task_offset
                    .min(state.grouped_tasks().len().saturating_sub(1));
                if let Some(active) = state
                    .tasks
                    .iter()
                    .position(|task| task.active && task.ready)
                {
                    state.reveal_task(active);
                }
                state.request_redraw(qh);
            }
            return;
        }
        if let Some(index) = state.tasks.iter().position(|task| task.handle == *proxy) {
            let task = &mut state.tasks[index];
            let mut refresh = false;
            match event {
                zwlr_foreign_toplevel_handle_v1::Event::Title { title } => {
                    task.title = title.chars().take(256).collect()
                }
                zwlr_foreign_toplevel_handle_v1::Event::AppId { app_id } => {
                    task.app_id = app_id.chars().take(256).collect()
                }
                zwlr_foreign_toplevel_handle_v1::Event::State { state: states } => {
                    let window_state = task_groups::decode_window_state(&states);
                    task.active = window_state.active;
                    task.minimized = window_state.minimized;
                }
                zwlr_foreign_toplevel_handle_v1::Event::Done => {
                    task.ready = true;
                    refresh = true;
                }
                _ => {}
            }
            if refresh {
                if state.trace_window_events {
                    let task = &state.tasks[index];
                    // App IDs are escaped; titles and user content are never traced.
                    eprintln!("RicePlate window event=ready app_id={:?} active={} minimized={}",
                        task.app_id, task.active, task.minimized);
                }
                if state.tasks[index].active {
                    state.reveal_task(index);
                }
                state.request_redraw(qh);
            }
        }
    }
}

impl ShmHandler for RicePlate {
    fn shm_state(&mut self) -> &mut Shm {
        &mut self.shm
    }
}

delegate_registry!(RicePlate);
impl ProvidesRegistryState for RicePlate {
    fn registry(&mut self) -> &mut RegistryState {
        &mut self.registry
    }
    registry_handlers![OutputState, SeatState];
}
smithay_client_toolkit::delegate_dispatch2!(RicePlate);

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn superseded_wayland_menu_configure_waits_instead_of_destroying_the_layer() {
        let old = (native_menu::WIDTH, native_menu::HEIGHT);
        for desired in [(400, 380), (480, 456)] {
            assert_eq!(menu_size_decision(desired, old, true),
                       MenuSizeDecision::AwaitNewConfigure);
            assert_eq!(menu_size_decision(desired, desired, true),
                       MenuSizeDecision::Accept);
            assert_eq!(menu_size_decision(desired, old, false),
                       MenuSizeDecision::RetryExpectedSize);
        }
        // When a fractional-scale output switches from 480 to 320 logical
        // pixels, an old configure must not permanently kill the menu after
        // the new 320 configure was already accepted.
        assert_eq!(menu_size_decision(old, (480, 456), false),
                   MenuSizeDecision::RetryExpectedSize);
        assert_eq!(menu_size_decision(old, old, false), MenuSizeDecision::Accept);
    }

    #[test]
    fn small_menu_raster_keeps_full_source_and_pointer_targets() {
        let width = native_menu::WIDTH;
        let height = native_menu::HEIGHT;
        let size = native_menu::fitted_size(320, 240, 36);
        let mut original = vec![0_u8; (width * height * 4) as usize];
        for y in 0..height {
            for x in 0..width {
                let offset = ((y * width + x) * 4) as usize;
                original[offset] = (x % 256) as u8;
                original[offset + 1] = (y % 256) as u8;
                original[offset + 3] = 255;
            }
        }
        let mut fitted = vec![0_u8; (size.0 * size.1 * 4) as usize];
        fit_menu_pixels(&original, &mut fitted, size);
        for (x, y) in [(0, 0), (size.0 / 2, size.1 / 2),
                       (size.0 - 1, size.1 - 1)] {
            let dst = ((y * size.0 + x) * 4) as usize;
            let src_x = x * width / size.0;
            let src_y = y * height / size.1;
            let src = ((src_y * width + src_x) * 4) as usize;
            assert_eq!(&fitted[dst..dst + 4], &original[src..src + 4]);
        }
    }

    #[test]
    fn enlarged_luna_menu_interpolates_glyph_edges_without_changing_input_space() {
        let (sw, sh) = (native_menu::WIDTH, native_menu::HEIGHT);
        let mut original = vec![0_u8; (sw * sh * 4) as usize];
        for y in 0..sh {
            for x in 0..sw {
                let pos = ((y * sw + x) * 4) as usize;
                let light = if x < sw / 2 { 0 } else { 255 };
                original[pos..pos + 4].copy_from_slice(&[light, light, light, 255]);
            }
        }
        let size = (400, 380);
        let mut smooth = vec![0; (size.0 * size.1 * 4) as usize];
        let mut stepped = smooth.clone();
        fit_luna_menu_pixels(&original, &mut smooth, size);
        fit_menu_pixels(&original, &mut stepped, size);
        assert_ne!(smooth, stepped);
        assert!(smooth.chunks_exact(4).all(|pixel| pixel[3] == 255));
        // Interpolated edge values are new only at actual source transitions.
        assert!(smooth.chunks_exact(4).any(|pixel| pixel[0] > 0 && pixel[0] < 255));
        assert_eq!(&smooth[0..4], &[0, 0, 0, 255]);
        assert_eq!(&smooth[smooth.len() - 4..], &[255, 255, 255, 255]);
        let center = native_menu::input_coords((200.0, 190.0), size);
        assert_eq!(center, (160.0, 152.0));
    }

    #[test]
    fn compact_native_menu_paints_readable_rows_at_output_resolution() {
        let source = include_str!("../../../tests/fixtures/riceplate-desktop-v5.json");
        let style = recipe::parse(source, Some("mockup-desktop")).unwrap();
        let menu = style.menu.as_ref().unwrap();
        let size = native_menu::fitted_size(320, 240, 36);
        assert!(native_menu::compact_layout(size));
        let mut state = native_menu::MenuState::default();
        state.open();
        let mut frame = vec![0_u8; (size.0 * size.1 * 4) as usize];
        paint_compact_menu(&mut frame, menu, &style, &state, size);
        let chosen = ((native_menu::COMPACT_ACTION_TOP + 14) * size.0 + size.0 - 16) as usize * 4;
        assert_eq!(&frame[chosen..chosen + 4],
                   &if style.hover != 0 { style.hover } else { style.active }.to_le_bytes());
        let mut next = frame.clone();
        state.select_by(menu, 1);
        paint_compact_menu(&mut next, menu, &style, &state, size);
        assert_ne!(frame, next);
        assert_eq!(state.compact_hit(menu, 12.0, 77.0, size), Some(MenuHit::Action(0)));
        assert_eq!(state.compact_hit(menu, 12.0, 111.0, size), Some(MenuHit::Action(1)));
    }

    #[test]
    fn native_start_menu_paints_distinct_schema_v6_sidebar_geometry() {
        let source = include_str!("../../../tests/fixtures/riceplate-desktop-v5.json");
        let mut data: serde_json::Value = serde_json::from_str(source).unwrap();
        data["schema_version"] = serde_json::json!(6);
        let tabs = recipe::parse(&data.to_string(), Some("mockup-desktop")).unwrap();
        data["menu"]["presentation"] = serde_json::json!("sidebar");
        let sidebar = recipe::parse(&data.to_string(), Some("mockup-desktop")).unwrap();
        let mut state = native_menu::MenuState::default();
        state.open();
        let mut tabs_frame = vec![0; (native_menu::WIDTH * native_menu::HEIGHT * 4) as usize];
        let mut sidebar_frame = tabs_frame.clone();
        paint_menu(&mut tabs_frame, tabs.menu.as_ref().unwrap(), &tabs, &state);
        paint_menu(&mut sidebar_frame, sidebar.menu.as_ref().unwrap(), &sidebar, &state);
        fn pixel(frame: &[u8], x: usize, y: usize) -> &[u8] {
            let index = (y * native_menu::WIDTH as usize + x) * 4;
            &frame[index..index + 4]
        }
        // The old selected horizontal tab extends across x=140. A left
        // sidebar's group highlight does not paint into the right column.
        assert_eq!(pixel(&tabs_frame, 140, 50), &tabs.active.to_le_bytes());
        assert_eq!(pixel(&sidebar_frame, 140, 50), &sidebar.background.to_le_bytes());
        assert_eq!(pixel(&sidebar_frame, 2, 50), &sidebar.active.to_le_bytes());
        assert_ne!(tabs_frame, sidebar_frame);
    }

    #[test]
    fn composed_menu_paints_headers_and_real_app_grid_tiles() {
        let source = include_str!("../../../tests/fixtures/riceplate-composed-v6.json");
        let style = recipe::parse(source, Some("mockup-composed")).unwrap();
        let mut state = native_menu::MenuState::default();
        state.apps.push(installed_apps::App { action: "desktop:test.desktop".into(),
            name: "Test Editor".into(), search_text: "test editor".into(),
            path: "/usr/share/applications/test.desktop".into() });
        state.open();
        let mut frame = vec![0; (native_menu::WIDTH * native_menu::HEIGHT * 4) as usize];
        paint_menu(&mut frame, style.menu.as_ref().unwrap(), &style, &state);
        let first = (212 * native_menu::WIDTH + 200) as usize * 4;
        assert_eq!(&frame[first..first + 4], &style.background.to_le_bytes());
        state.select_by(style.menu.as_ref().unwrap(), 2);
        let mut selected = frame.clone();
        paint_menu(&mut selected, style.menu.as_ref().unwrap(), &style, &state);
        assert_eq!(&selected[first..first + 4], &style.active.to_le_bytes());
        assert_ne!(frame, selected);
    }

    #[test]
    fn native_tray_paints_live_pixmap_and_reserves_real_hit_regions() {
        let style = recipe::load("classic").unwrap();
        let width = 1024;
        let height = style.height;
        let mut canvas = vec![0; (width * height * 4) as usize];
        let view = tray::State { entries: vec![tray::Entry {
            bus_name: "org.test.SNI".into(), title: "Test".into(),
            icon: Some(tray::Icon { width: 1, height: 1,
                argb: vec![255, 33, 88, 199] }),
            is_menu: false, needs_attention: false,
        }] };
        paint_panel(&mut canvas, width, height, &style, &[], "12:00",
                    &PowerStatus::NotPresent, &SystemStatus::default(), &view, 0, None, None, None);
        let region = recipe::layout(&style, width, 0).into_iter()
            .find(|placed| placed.widget == Widget::Tray).unwrap();
        assert_eq!(region.width, tray::WIDTH);
        assert_eq!(recipe::hit((region.x + 4) as f64, width, 0, 0, &style),
                   Some(Hit::Tray(0)));
        let painted = ((height / 2 * width + region.x + 4) * 4) as usize;
        assert_ne!(&canvas[painted..painted + 4], &style.background.to_le_bytes());
        assert_eq!(recipe::hit((region.x + 4 * tray::SLOT_WIDTH + 1) as f64,
                               width, 0, 0, &style), None);
    }

    #[test]
    fn luna_overflow_chevron_is_backed_by_real_sni_popup_hit() {
        let style = recipe::parse(
            include_str!("../../../examples/wayland/xp-luna-columns.json"),
            Some("xp-luna-columns")).unwrap();
        let view = tray::State { entries: (0..6).map(|index| tray::Entry {
            bus_name: format!("org.example.Test{index}"),
            title: format!("Test {index}"),
            icon: None, is_menu: false, needs_attention: false,
        }).collect() };
        assert_eq!(view.visible_count(), tray::VISIBLE_ITEMS - 1);
        assert_eq!(view.overflow_count(), 3);
        let width = 1366;
        let height = style.height;
        let mut pixels = vec![0; (width * height * 4) as usize];
        paint_panel(&mut pixels, width, height, &style, &[], "12:00",
                    &PowerStatus::NotPresent, &SystemStatus::default(), &view,
                    0, None, None, None);
        let rect = recipe::layout(&style, width, 0).into_iter()
            .find(|placed| placed.widget == Widget::Tray).unwrap();
        let x = rect.x + tray::SLOT_WIDTH * (tray::VISIBLE_ITEMS - 1) as u32;
        assert_eq!(recipe::hit((x + 14) as f64, width, 0, 0, &style),
                   Some(Hit::Tray(tray::VISIBLE_ITEMS - 1)));
        let colored = ((height / 2 * width + x + 14) * 4) as usize;
        assert_ne!(&pixels[colored..colored + 4],
                   &style.background.to_le_bytes());
        let mut empty = vec![0; pixels.len()];
        paint_panel(&mut empty, width, height, &style, &[], "12:00",
                    &PowerStatus::NotPresent, &SystemStatus::default(),
                    &tray::State::default(), 0, None, None, None);
        assert_ne!(pixels, empty);
    }

    #[test]
    fn tray_overflow_popup_draws_distinct_pages_and_selection() {
        let style = recipe::load("classic").unwrap();
        let mut state = tray::State::default();
        for index in 0..12 {
            state.entries.push(tray::Entry {
                bus_name: format!("org.test.Item{index}"), title: format!("App {index}"),
                icon: None, is_menu: false, needs_attention: index == 7,
            });
        }
        let mut popup = tray::Popup::default();
        popup.open(state.entries.len());
        let mut first = vec![0; (tray::POPUP_WIDTH * tray::POPUP_HEIGHT * 4) as usize];
        let mut second = first.clone();
        paint_tray_popup(&mut first, &style, &state, &popup);
        popup.page(1, state.entries.len());
        paint_tray_popup(&mut second, &style, &state, &popup);
        assert_ne!(first, second);
        assert_eq!(popup.hit(16.0, 44.0, state.entries.len()),
                   Some(TrayHit::Item(8)));
        assert_eq!(&second[..4], &style.active.to_le_bytes());
    }

    #[test]
    fn dbusmenu_popup_paints_nested_pages_with_live_checkmark_state() {
        use status_notifier::{MenuNode, ToggleState, ToggleType};
        let style = recipe::load("classic").unwrap();
        let mut popup = tray::MenuPopup::default();
        let model = MenuNode::Menu { id: 0, label: "root".into(), enabled: true,
            visible: true, children: vec![
                MenuNode::Menu { id: 4, label: "Preferences".into(), enabled: true,
                    visible: true, children: vec![
                        MenuNode::Item { id: 7, label: "Enabled".into(), enabled: true,
                            visible: true, icon_name: String::new(),
                            icon_data: status_notifier::IconData(Vec::new()),
                            toggle_type: ToggleType::Checkmark,
                            toggle_state: ToggleState::On },
                    ] },
            ] };
        assert!(popup.open("org.test.menu", "Test application", &model));
        let mut root = vec![0; (tray::POPUP_WIDTH * tray::POPUP_HEIGHT * 4) as usize];
        let mut child = root.clone();
        paint_tray_menu(&mut root, &style, &popup);
        assert_eq!(popup.choice(0), TrayMenuChoice::Open(4));
        paint_tray_menu(&mut child, &style, &popup);
        assert_ne!(root, child, "submenu must render its own controls and back affordance");
        assert_eq!(&child[..4], &style.active.to_le_bytes());
        assert_eq!(popup.hit(8.0, 14.0), Some(TrayMenuHit::Back));
    }

    #[test]
    fn ricepop_osd_renders_readback_volume_and_failure_distinctly() {
        let style = recipe::load("classic").unwrap();
        let mut filled = vec![0; (osd::WIDTH * osd::HEIGHT * 4) as usize];
        let mut error = filled.clone();
        paint_osd(&mut filled, &style, &osd::Notice {
            title: "Volume", value: "58%".into(), fill: Some(58),
        });
        paint_osd(&mut error, &style, &osd::Notice {
            title: "Volume", value: "Change failed".into(), fill: None,
        });
        assert_ne!(filled, error);
        let bar_pixel = |canvas: &[u8], x: u32| {
            let offset = ((54 * osd::WIDTH + x) * 4) as usize;
            u32::from_le_bytes(canvas[offset..offset + 4].try_into().unwrap())
        };
        assert_eq!(bar_pixel(&filled, 18), style.foreground);
        assert_eq!(bar_pixel(&filled, 220), style.active);
        assert_eq!(bar_pixel(&error, 18), style.background);
    }

    #[test]
    fn luna_quick_launch_uses_exact_real_input_slots_and_collapsed_handle_is_inert() {
        let luna = recipe::parse(
            include_str!("../../../examples/wayland/xp-luna-columns.json"),
            Some("xp-luna-columns")).unwrap();
        let width = 1366;
        let placed = recipe::layout(&luna, width, 2);
        let commands: Vec<_> = placed.iter().filter_map(|item| match item.widget {
            Widget::Action(index) =>
                luna.actions.get(index as usize)
                    .map(|action| (action.id.as_str(), item.x, item.width, index)),
            _ => None,
        }).collect();
        assert_eq!(commands.len(), 3);
        assert_eq!(commands.iter().map(|slot| slot.0).collect::<Vec<_>>(),
                   vec!["applications", "terminal", "show-desktop"]);
        for (_, x, span, index) in &commands {
            assert_eq!(*span, 32);
            assert_eq!(recipe::hit(f64::from(*x + 16), width, 2, 0, &luna),
                       Some(Hit::Action(*index)));
        }
        let mut expanded = vec![0; (width * luna.height * 4) as usize];
        paint_panel(&mut expanded, width, luna.height, &luna, &[], "12:00",
                    &PowerStatus::NotPresent, &SystemStatus::default(),
                    &tray::State::default(), 0, None, None, None);
        let mut collapsed = vec![0; (width * luna_taskbar::HANDLE_HEIGHT * 4) as usize];
        paint_panel(&mut collapsed, width, luna_taskbar::HANDLE_HEIGHT, &luna,
                    &[], "12:00", &PowerStatus::NotPresent,
                    &SystemStatus::default(), &tray::State::default(),
                    0, None, None, None);
        assert!(collapsed.chunks_exact(4).all(|pixel| pixel[3] == 255));
        assert_ne!(&collapsed[..4], &expanded[..4]);
        let classic = recipe::load("classic").unwrap();
        assert!(!classic.actions.iter().any(|action| action.id == "show-desktop"));
    }

    #[test]
    fn luna_taskbar_pointer_states_are_real_but_legacy_rices_are_unchanged() {
        let luna = recipe::parse(
            include_str!("../../../examples/wayland/xp-luna-columns.json"),
            Some("xp-luna-columns")).unwrap();
        let classic_luna = recipe::parse(
            include_str!("../../../examples/wayland/xp-luna.json"),
            Some("xp-luna")).unwrap();
        let groups = [TaskGroup {
            members: vec![0], representative: 0, label: "File Manager".into(), active: true,
        }];
        let render = |style: &PanelStyle, visual: PanelPointerVisual| {
            let width = 1366;
            let mut frame = vec![0; (width * style.height * 4) as usize];
            paint_panel_pointer(&mut frame, width, style.height, style, &groups, "12:00",
                                &PowerStatus::NotPresent, &SystemStatus::default(),
                                &tray::State::default(), 0, None, None, None, visual);
            frame
        };
        let idle = render(&luna, PanelPointerVisual::default());
        let launcher_hover = PanelPointerVisual {
            hovered: Some(Hit::Launcher), pressed: None,
        };
        let launcher_press = PanelPointerVisual {
            hovered: Some(Hit::Launcher), pressed: Some(Hit::Launcher),
        };
        let task_hover = PanelPointerVisual {
            hovered: Some(Hit::Task(0)), pressed: None,
        };
        let task_press = PanelPointerVisual {
            hovered: Some(Hit::Task(0)), pressed: Some(Hit::Task(0)),
        };
        assert_eq!(launcher_hover.button(Hit::Launcher),
                   panel_chrome::ButtonVisual::Hovered);
        assert_eq!(launcher_press.button(Hit::Launcher),
                   panel_chrome::ButtonVisual::Pressed);
        assert_eq!(launcher_press.button(Hit::Task(0)),
                   panel_chrome::ButtonVisual::Normal);
        assert_eq!(PanelPointerVisual { pressed: Some(Hit::Launcher), hovered: None }
                   .button(Hit::Launcher), panel_chrome::ButtonVisual::Normal);
        assert_eq!(luna_hover_target(Some(Hit::Task(0))), Some(Hit::Task(0)));
        assert_eq!(luna_hover_target(Some(Hit::Clock)), None);
        assert_eq!(luna_hover_target(Some(Hit::Tray(0))), None);
        let hovered_launcher_frame = render(&luna, launcher_hover);
        let pressed_launcher_frame = render(&luna, launcher_press);
        let hovered_task_frame = render(&luna, task_hover);
        let pressed_task_frame = render(&luna, task_press);
        assert_ne!(idle, hovered_launcher_frame);
        assert_ne!(idle, pressed_launcher_frame);
        assert_ne!(hovered_launcher_frame, pressed_launcher_frame);
        assert_ne!(idle, hovered_task_frame);
        assert_ne!(idle, pressed_task_frame);
        assert_ne!(hovered_task_frame, pressed_task_frame);

        // No hover/press treatment is permitted to alter existing v12 Luna,
        // undecorated classic, or unrelated Creator recipes.
        let baseline = render(&classic_luna, PanelPointerVisual::default());
        assert_eq!(baseline, render(&classic_luna, launcher_press));
        assert_eq!(baseline, render(&classic_luna, task_press));
        let classic = recipe::load("classic").unwrap();
        assert_eq!(render(&classic, PanelPointerVisual::default()),
                   render(&classic, task_press));
    }

    #[test]
    fn luna_native_status_menus_have_real_capability_gates() {
        let unavailable = SystemStatus::default();
        let (_, network) = luna_status_rows(Widget::Network, &unavailable,
                                            &PowerStatus::NotPresent).unwrap();
        assert!(!network[1].enabled);
        assert!(network[2].enabled);
        let (_, audio) = luna_status_rows(Widget::Audio, &unavailable,
                                          &PowerStatus::NotPresent).unwrap();
        assert!(audio[1..4].iter().all(|row| !row.enabled));
        let active = SystemStatus {
            network: system_status::Network::Global,
            audio: Audio::Volume(65),
            wifi: system_status::WifiRadio::Enabled,
        };
        let (_, network) = luna_status_rows(Widget::Network, &active,
                                            &PowerStatus::NotPresent).unwrap();
        assert!(network[1].enabled);
        let (_, volume) = luna_status_rows(Widget::Audio, &active,
                                           &PowerStatus::NotPresent).unwrap();
        assert!(volume[1..4].iter().all(|row| row.enabled));
        assert_eq!(volume[4].id, 102);
        assert!(luna_status_rows(Widget::Tray, &active, &PowerStatus::NotPresent).is_none());
    }

    #[test]
    fn network_and_audio_status_pixels_follow_real_backend_results() {
        let style = recipe::load("classic").unwrap();
        let width = 1024;
        let height = style.height;
        let mut unavailable = vec![0; (width * height * 4) as usize];
        let mut connected = unavailable.clone();
        paint_panel(&mut unavailable, width, height, &style, &[], "12:00",
                    &PowerStatus::NotPresent, &SystemStatus::default(), &tray::State::default(), 0, None, None, None);
        let current = SystemStatus {
            network: system_status::Network::Global,
            audio: system_status::Audio::Volume(58),
            wifi: system_status::WifiRadio::Enabled,
        };
        paint_panel(&mut connected, width, height, &style, &[], "12:00",
                    &PowerStatus::NotPresent, &current, &tray::State::default(), 0, None, None, None);
        for widget in [Widget::Network, Widget::Audio] {
            let region = recipe::layout(&style, width, 0).into_iter()
                .find(|item| item.widget == widget).unwrap();
            assert!((region.x..region.x + region.width).any(|x| {
                (0..height).any(|y| {
                    let offset = ((y * width + x) * 4) as usize;
                    unavailable[offset..offset+4] != connected[offset..offset+4]
                })
            }));
        }
    }

    #[test]
    fn declarative_controls_render_unavailable_live_pending_and_failed_states() {
        let style = recipe::parse(
            include_str!("../../../tests/fixtures/riceplate-controls-v7.json"),
            Some("mockup-controls")).unwrap();
        let width = 1280;
        let size = (width * style.height * 4) as usize;
        let render = |status: &SystemStatus, pending, result| {
            let mut frame = vec![0; size];
            paint_panel(&mut frame, width, style.height, &style, &[], "12:00",
                        &PowerStatus::NotPresent, status, &tray::State::default(), 0,
                        None, pending, result);
            frame
        };
        let unavailable = render(&SystemStatus::default(), None, None);
        let working = SystemStatus {
            network: system_status::Network::Offline,
            wifi: system_status::WifiRadio::Enabled,
            audio: Audio::Volume(42),
        };
        let available = render(&working, None, None);
        assert_ne!(available, unavailable);
        assert_ne!(available, render(&working, Some(ControlAction::WifiToggle), None));
        assert_ne!(available, render(&working, Some(ControlAction::AudioMute), None));
        assert_ne!(available, render(&working, None,
                                    Some((ControlAction::WifiToggle, false))));
        let muted = SystemStatus { audio: Audio::Muted, ..working };
        assert_ne!(available, render(&muted, None, None));
    }

    #[test]
    fn desktop_action_widgets_have_visible_focus_hover_disabled_and_existing_status_parity() {
        let style = recipe::parse(
            include_str!("../../../tests/fixtures/riceplate-desktop-actions-v9.json"),
            Some("desktop-actions")).unwrap();
        let widgets = &style.composition.as_ref().unwrap().widgets;
        assert_eq!(widgets[0].kind, recipe::DesktopWidgetKind::Action("settings".into()));
        assert_eq!(widgets[1].kind, recipe::DesktopWidgetKind::Action("wifi-toggle".into()));
        assert_eq!(widgets[2].kind, recipe::DesktopWidgetKind::Network);
        let len = (recipe::DESKTOP_WIDGET_WIDTH * recipe::DESKTOP_WIDGET_HEIGHT * 4) as usize;
        let render = |interactive, focused, hovered, disabled| {
            let mut canvas = vec![0_u8; len];
            paint_desktop_widget(&mut canvas, "Wi-Fi radio", &["Press Enter".into()], &style,
                                 interactive, focused, hovered, disabled);
            canvas
        };
        let status = render(false, false, false, false);
        let ready = render(true, false, false, false);
        let focused = render(true, true, false, false);
        assert_ne!(status, ready);
        assert_ne!(ready, focused);
        assert_ne!(ready, render(true, false, true, false));
        assert_ne!(ready, render(true, false, false, true));
        assert_eq!(&focused[..4], &style.focus.to_le_bytes());
        assert_eq!(&render(true, false, false, true)[..4], &style.disabled.to_le_bytes());
    }

    #[test]
    fn native_power_indicator_draws_real_state_in_allocated_panel_region() {
        let style = recipe::load("classic").unwrap();
        let width = 800;
        let height = style.height;
        let len = (width * height * 4) as usize;
        let mut without = vec![0; len];
        let mut charging = vec![0; len];
        paint_panel(&mut without, width, height, &style, &[], "12:00",
                    &PowerStatus::NotPresent, &SystemStatus::default(), &tray::State::default(), 0, None, None, None);
        paint_panel(&mut charging, width, height, &style, &[], "12:00",
                    &PowerStatus::Battery { percent: 73, charging: true },
                    &SystemStatus::default(), &tray::State::default(), 0, None, None, None);
        let region = recipe::layout(&style, width, 0).into_iter()
            .find(|item| item.widget == Widget::Battery).unwrap();
        assert_eq!(region.width, 64);
        assert!(charging.chunks_exact(4).enumerate().any(|(index, pixel)| {
            let x = index as u32 % width;
            x >= region.x && x < region.x + region.width
                && pixel == style.foreground.to_le_bytes()
        }));
        assert_ne!(without, charging);
    }

    #[test]
    fn shared_panel_painter_renders_on_independent_output_buffers() {
        let style = recipe::parse(
            include_str!("../../../tests/fixtures/riceplate-desktop-v5.json"),
            Some("mockup-desktop"),
        ).unwrap();
        let width = 800;
        let height = style.height;
        let mut first = vec![0_u8; (width * height * 4) as usize];
        let mut second = vec![0_u8; (width * height * 4) as usize];
        paint_panel(&mut first, width, height, &style, &[], "12:00",
                    &PowerStatus::NotPresent, &SystemStatus::default(), &tray::State::default(), 0, None, None, None);
        paint_panel(&mut second, width, height, &style, &[], "12:00",
                    &PowerStatus::NotPresent, &SystemStatus::default(), &tray::State::default(), 0, None, None, None);
        assert_eq!(first, second);
        assert_eq!(&first[(width * (height / 2) + 400) as usize * 4..][..4],
                   &style.background.to_le_bytes());
        assert!(first.chunks_exact(4).any(|pixel|
            pixel == style.active.to_le_bytes()));
    }

    #[test]
    fn luna_columns_render_separate_visible_panes_with_real_selection() {
        let style = recipe::parse(
            include_str!("../../../examples/wayland/xp-luna-columns.json"),
            Some("xp-luna-columns")).unwrap();
        let menu = style.menu.as_ref().unwrap();
        let mut state = native_menu::MenuState::default();
        state.open();
        let width = native_menu::WIDTH;
        let height = native_menu::HEIGHT;
        let mut canvas = vec![0; (width * height * 4) as usize];
        paint_menu(&mut canvas, menu, &style, &state);
        let pixel = |buffer: &[u8], x: u32, y: u32| {
            let offset = ((y * width + x) * 4) as usize;
            u32::from_le_bytes(buffer[offset..offset+4].try_into().unwrap())
        };
        let palette = menu.palette.unwrap();
        assert_ne!(pixel(&canvas, 120, 70), pixel(&canvas, 260, 70));
        assert_ne!(pixel(&canvas, 260, 70), palette.background);
        assert_ne!(pixel(&canvas, 260, 70), pixel(&canvas, 260, 240));
        assert_ne!(pixel(&canvas, native_menu::COLUMNS_SPLIT, 70), palette.header);
        assert_ne!(pixel(&canvas, 260, height - 10), palette.header);
        assert_eq!(pixel(&canvas, 12, 150), palette.header); // current Terminal row

        state.select_group(menu, 1);
        paint_menu(&mut canvas, menu, &style, &state);
        assert_eq!(pixel(&canvas, 176, 80), palette.header); // current right action
        assert_ne!(pixel(&canvas, 12, 150), palette.header);
    }

    #[test]
    fn luna_footer_keeps_action_feedback_visible_without_repainting_real_buttons() {
        let style = recipe::parse(
            include_str!("../../../examples/wayland/xp-luna-columns.json"),
            Some("xp-luna-columns")).unwrap();
        let menu = style.menu.as_ref().unwrap();
        let frame = || vec![0; (native_menu::WIDTH * native_menu::HEIGHT * 4) as usize];
        let mut state = native_menu::MenuState::default();
        state.open();
        let mut idle = frame();
        paint_menu(&mut idle, menu, &style, &state);
        let mut notice = frame();
        state.notice = Some("Action pinned");
        paint_menu(&mut notice, menu, &style, &state);
        let strip = |pixels: &[u8]| (47_u32..63).flat_map(|y|
            (12_u32..native_menu::COLUMNS_SPLIT).flat_map(move |x| {
                let index = ((y * native_menu::WIDTH + x) * 4) as usize;
                pixels[index..index + 4].to_vec()
            })).collect::<Vec<_>>();
        assert_ne!(strip(&idle), strip(&notice), "Luna must retain menu feedback");
        let footer = (native_menu::LUNA_FOOTER_Y * native_menu::WIDTH * 4) as usize;
        assert_eq!(&idle[footer..], &notice[footer..],
                   "A transient notice must not corrupt real footer buttons");
    }

    #[test]
    fn xp_luna_painter_separates_green_start_and_blue_menu_header() {
        let style = recipe::parse(include_str!("../../../examples/wayland/xp-luna.json"),
                                  Some("xp-luna")).unwrap();
        let width = 1366;
        let height = style.height;
        let mut panel = vec![0; (width * height * 4) as usize];
        paint_panel(&mut panel, width, height, &style, &[], "12:00",
                    &PowerStatus::NotPresent, &SystemStatus::default(),
                    &tray::State::default(), 0, None, None, None);
        let launcher = style.launcher.as_ref().unwrap();
        let green = ((height / 2 * width + 10) * 4) as usize;
        let start_pixel = u32::from_le_bytes(panel[green..green + 4].try_into().unwrap());
        assert_ne!(start_pixel, style.background);
        assert_eq!(launcher.label, "start");
        let blue = ((height / 2 * width + 115) * 4) as usize;
        let upper_blue = ((1 * width + 115) * 4) as usize;
        // Luna uses a graduated blue panel; verify its hue and reflection,
        // not the obsolete flat background pixel.
        assert!(panel[blue] > panel[blue + 1] && panel[blue + 1] > panel[blue + 2]);
        assert_ne!(&panel[blue..blue + 4], &style.background.to_le_bytes());
        assert_ne!(&panel[blue..blue + 4], &panel[upper_blue..upper_blue + 4]);

        let menu = style.menu.as_ref().unwrap();
        let mut state = native_menu::MenuState::default();
        state.open();
        let mut popup = vec![0; (native_menu::WIDTH * native_menu::HEIGHT * 4) as usize];
        paint_menu(&mut popup, menu, &style, &state);
        let palette = menu.palette.unwrap();
        assert_eq!(&popup[..4], &palette.header.to_le_bytes());
        let corner = (((native_menu::HEIGHT - 2) * native_menu::WIDTH +
                       native_menu::WIDTH - 2) * 4) as usize;
        assert_eq!(&popup[corner..corner + 4], &palette.background.to_le_bytes());
    }

    #[test]
    fn keyboard_focus_frame_only_marks_the_selected_panel_widget() {
        let style = recipe::load("classic").unwrap();
        let width = 960;
        let height = style.height;
        let len = (width * height * 4) as usize;
        let mut normal = vec![0; len];
        let mut selected = vec![0; len];
        paint_panel(&mut normal, width, height, &style, &[], "12:00",
                    &PowerStatus::NotPresent, &SystemStatus::default(), &tray::State::default(), 0, None, None, None);
        paint_panel(&mut selected, width, height, &style, &[], "12:00",
                    &PowerStatus::NotPresent, &SystemStatus::default(), &tray::State::default(), 0,
                    Some(KeyboardTarget::Launcher), None, None);
        assert_ne!(normal, selected);
        let launcher = recipe::layout(&style, width, 0).into_iter()
            .find(|item| item.widget == Widget::Launcher).unwrap();
        let pixel = ((2 * width + launcher.x + 10) * 4) as usize;
        assert_eq!(&selected[pixel..pixel + 4], &style.foreground.to_le_bytes());
    }

    #[test]
    fn calendar_painter_renders_actual_month_and_day_states() {
        let style = recipe::load("classic").unwrap();
        let today = chrono::NaiveDate::from_ymd_opt(2024, 2, 29).unwrap();
        let mut state = CalendarState::new(today);
        state.open(today);
        let mut february = vec![0; (calendar::WIDTH * calendar::HEIGHT * 4) as usize];
        let mut march = vec![0; february.len()];
        paint_calendar(&mut february, &style, &state);
        assert_eq!(&february[..4], &style.active.to_le_bytes());
        assert!(february.chunks_exact(4).any(|pixel|
            pixel == style.foreground.to_le_bytes()));
        state.shift(1);
        paint_calendar(&mut march, &style, &state);
        assert_ne!(february, march, "real month names/days must change the pixels");
    }

    #[test]
    fn native_ricepop_painter_distinguishes_loading_empty_and_live_alerts() {
        let style = recipe::load("classic").unwrap();
        let mut state = NotificationState::default();
        let mut loading = vec![0; (native_menu::WIDTH * native_menu::HEIGHT * 4) as usize];
        let mut empty = loading.clone();
        let mut active = loading.clone();
        let mut detail = loading.clone();
        let mut past = loading.clone();
        let revision = state.begin();
        paint_notifications(&mut loading, &style, &state);
        assert!(state.update(revision, Ok(ricepop::Snapshot {
            active: vec![], history: vec![],
        })));
        paint_notifications(&mut empty, &style, &state);
        let revision = state.begin();
        assert!(state.update(revision, Ok(ricepop::Snapshot {
            active: vec![ricepop::Notice {
                id: 1, summary: "New message".into(), body: "Private preview".into(),
                app_name: "Mail".into(), actions: vec![ricepop::Action {
                    key: "default".into(), label: "Open".into(),
                }], ..ricepop::Notice::default()
            }],
            history: vec![ricepop::Notice {
                id: 2, summary: "Older message".into(), body: "Past preview".into(),
                ..ricepop::Notice::default()
            }],
        })));
        paint_notifications(&mut active, &style, &state);
        assert!(state.open_detail(0));
        paint_notifications(&mut detail, &style, &state);
        state.select_tab(true);
        paint_notifications(&mut past, &style, &state);
        assert_ne!(loading, empty);
        assert_ne!(empty, active);
        assert_ne!(active, past);
        assert_ne!(active, detail);
        assert_ne!(past, detail);
        assert_eq!(state.selected_id(), None);
        state.close();
        assert!(state.notices.is_empty());
        assert!(state.history.is_empty());
    }

    #[test]
    fn native_ricepop_range_header_tracks_page_in_full_and_compact_painters() {
        let style = recipe::load("classic").unwrap();
        let mut state = NotificationState::default();
        state.show_preview(ricepop::Snapshot {
            active: (1..=7).map(|id| ricepop::Notice {
                id, summary: format!("Message {id}"), ..ricepop::Notice::default()
            }).collect(), history: vec![],
        });
        let mut first = vec![0; (native_menu::WIDTH * native_menu::HEIGHT * 4) as usize];
        let mut page = first.clone();
        paint_notifications(&mut first, &style, &state);
        state.select(3);
        paint_notifications(&mut page, &style, &state);
        let header_bytes = (native_menu::WIDTH * 38 * 4) as usize;
        assert_ne!(&first[..header_bytes], &page[..header_bytes],
                   "visible range must change in the actual native header");
        state.select(-3);
        let mut restored = first.clone();
        paint_notifications(&mut restored, &style, &state);
        assert_eq!(&first[..header_bytes], &restored[..header_bytes]);

        let size = (168, 144);
        let mut compact_first = vec![0; (size.0 * size.1 * 4) as usize];
        let mut compact_next = compact_first.clone();
        paint_compact_notifications(&mut compact_first, &style, &state, size);
        state.select(1);
        paint_compact_notifications(&mut compact_next, &style, &state, size);
        let compact_header_bytes = (size.0 * 28 * 4) as usize;
        assert_ne!(&compact_first[..compact_header_bytes], &compact_next[..compact_header_bytes]);
    }

    #[test]
    fn compact_ricepop_renders_full_resolution_list_and_detail_without_scaling() {
        let style = recipe::load("classic").unwrap();
        let size = (168, 144);
        let mut state = NotificationState::default();
        let revision = state.begin();
        let len = (size.0 * size.1 * 4) as usize;
        let mut loading = vec![0_u8; len];
        let mut list = vec![0_u8; len];
        let mut detail = vec![0_u8; len];
        paint_compact_notifications(&mut loading, &style, &state, size);
        assert!(state.update(revision, Ok(ricepop::Snapshot {
            active: vec![ricepop::Notice {
                id: 31, summary: "Compact message".into(), app_name: "Messages".into(),
                body: "A longer notification that must remain readable".into(),
                actions: vec![ricepop::Action {
                    key: "open".into(), label: "Open message".into(),
                }], ..ricepop::Notice::default()
            }], history: vec![],
        })));
        paint_compact_notifications(&mut list, &style, &state, size);
        assert!(state.open_detail(0));
        paint_compact_notifications(&mut detail, &style, &state, size);
        assert_ne!(loading, list);
        assert_ne!(list, detail);
        assert_eq!(&detail[..4], &style.active.to_le_bytes());
        assert!(detail.chunks_exact(4).any(|p| p == style.foreground.to_le_bytes()));

        // Reloading a detail must never leak stale cached message text into
        // the compact popup. The original full-size painter masks it.
        state.begin();
        let mut reloading_detail = vec![0_u8; len];
        paint_compact_notifications(&mut reloading_detail, &style, &state, size);
        let mut fresh = NotificationState::default();
        fresh.begin();
        let mut fresh_loading = vec![0_u8; len];
        paint_compact_notifications(&mut fresh_loading, &style, &fresh, size);
        assert_eq!(reloading_detail, fresh_loading);
    }

    #[test]
    fn native_notification_font_is_opt_in_for_list_detail_and_compact_layout() {
        let Some(face) = style_art::fixture_font(2) else { return };
        let bitmap_style = recipe::load("classic").unwrap();
        let mut font_style = recipe::load("classic").unwrap();
        font_style.font_scale = 2;
        font_style.native_art = Some(style_art::LoadedArtwork {
            font: Some(face), icons: [None, None, None],
        });
        let mut state = NotificationState::default();
        state.show_preview(ricepop::Snapshot { active: vec![ricepop::Notice {
            id: 1, app_name: "Mail".into(), summary: "Font comparison".into(),
            body: "Portable Unicode Γραμματοσειρά with detailed message wrapping".into(),
            ..ricepop::Notice::default()
        }], history: vec![] });
        let make_canvas = |size: (u32, u32)| vec![0_u8; (size.0 * size.1 * 4) as usize];
        let full = (native_menu::WIDTH, native_menu::HEIGHT);
        let mut before = make_canvas(full);
        let mut after = make_canvas(full);
        paint_notifications(&mut before, &bitmap_style, &state);
        state.configure_glyph_scale(2);
        paint_notifications(&mut after, &font_style, &state);
        assert_ne!(before, after);
        assert!(state.open_detail(0));
        let mut detail_before = make_canvas(full);
        let mut detail_after = make_canvas(full);
        paint_notifications(&mut detail_before, &bitmap_style, &state);
        paint_notifications(&mut detail_after, &font_style, &state);
        assert_ne!(detail_before, detail_after);
        let compact = (168, 144);
        let mut compact_before = make_canvas(compact);
        let mut compact_after = make_canvas(compact);
        paint_compact_notifications(&mut compact_before, &bitmap_style, &state, compact);
        paint_compact_notifications(&mut compact_after, &font_style, &state, compact);
        assert_ne!(compact_before, compact_after);
        // A painter must not write outside its actual output-sized surface.
        assert_eq!(compact_after.len(), (168 * 144 * 4) as usize);
    }

    #[test]
    fn native_notification_text_without_private_font_is_byte_identical() {
        let style = recipe::load("classic").unwrap();
        let mut bitmap = vec![0_u8; 320 * 20 * 4];
        let mut notification = bitmap.clone();
        draw_text(&mut bitmap, 320, 20, 14, 3, "Alerts & status", style.foreground);
        draw_notification_text(&mut notification, 320, 20, 14, 3,
                               "Alerts & status", style.foreground, &style);
        assert_eq!(bitmap, notification);
    }


    #[test]
    fn xp_run_help_and_error_have_distinct_native_framebuffers() {
        let style = recipe::parse(
            include_str!("../../../examples/wayland/xp-luna-columns.json"),
            Some("xp-luna-columns")).unwrap();
        let size = (luna_dialog::WIDTH * luna_dialog::HEIGHT * 4) as usize;
        let mut run = vec![0_u8; size];
        let mut help = vec![0_u8; size];
        let mut error = vec![0_u8; size];
        paint_luna_dialog(&mut run, &style, &luna_dialog::State::new(luna_dialog::Kind::Run));
        paint_luna_dialog(&mut help, &style, &luna_dialog::State::new(luna_dialog::Kind::Help));
        let mut invalid = luna_dialog::State::new(luna_dialog::Kind::Run);
        invalid.notice = Some("Enter a program name");
        paint_luna_dialog(&mut error, &style, &invalid);
        assert_ne!(run, help);
        assert_ne!(run, error);
        assert_eq!(&run[..4], &0xff1a_439c_u32.to_le_bytes());
        let at = ((luna_dialog::WIDTH * 17 + 418) * 4) as usize;
        assert_eq!(&run[at..at+4], &0xffd8_4039_u32.to_le_bytes());
        let mut text = luna_dialog::State::new(luna_dialog::Kind::Run);
        for ch in "foot -e true".chars() { assert!(text.enter(&ch.to_string())); }
        let mut typed = vec![0_u8; size];
        paint_luna_dialog(&mut typed, &style, &text);
        assert_ne!(typed, run);
    }

    #[test]
    fn luna_context_paint_marks_real_selected_and_disabled_rows() {
        let style = recipe::parse(
            include_str!("../../../examples/wayland/xp-luna-columns.json"),
            Some("xp-luna-columns")).unwrap();
        let bytes = (desktop_context::WIDTH * desktop_context::HEIGHT * 4) as usize;
        let mut before = vec![0; bytes];
        let mut selected = vec![0; bytes];
        paint_desktop_context(&mut before, &style, DesktopContextAction::Open, None,
                              false, false, false, None, false, None);
        paint_desktop_context(&mut selected, &style, DesktopContextAction::AllDisplays,
                              Some(DesktopContextAction::AllDisplays),
                              false, false, false, None, false, None);
        let pixel = |buffer: &[u8], x: u32, y: u32| -> u32 {
            let at = ((y * desktop_context::WIDTH + x) * 4) as usize;
            u32::from_le_bytes(buffer[at..at+4].try_into().unwrap())
        };
        assert_eq!(pixel(&before, 12, desktop_context::row(DesktopContextAction::Open)),
                   0xff36_6ac9);
        assert_eq!(pixel(&selected, 12, desktop_context::row(DesktopContextAction::AllDisplays)),
                   0xff36_6ac9);
        assert_eq!(pixel(&before, 12, desktop_context::row(DesktopContextAction::NextDisplay)),
                   0xfffc_faf2);
        assert_ne!(before, selected);
        let mut enabled = vec![0; bytes];
        paint_desktop_context(&mut enabled, &style, DesktopContextAction::NextDisplay,
                              None, true, false, false, None, false, None);
        assert_eq!(pixel(&enabled, 12, desktop_context::row(DesktopContextAction::NextDisplay)),
                   0xff36_6ac9);
        let mut info = vec![0; bytes];
        paint_desktop_context(&mut info, &style, DesktopContextAction::Properties,
                              None, false, false, true,
                              Some(("Recycle Bin", "trash")), true, None);
        assert_ne!(info, before);
        assert_eq!(pixel(&info, 10, desktop_context::BACK_ROW), 0xff36_6ac9);
        let mut reset = vec![0; bytes];
        paint_desktop_context(&mut reset, &style, DesktopContextAction::ResetPosition,
                              None, false, true, false, None, false, None);
        assert_eq!(pixel(&reset, 12, desktop_context::row(DesktopContextAction::ResetPosition)),
                   0xff36_6ac9);
    }

    #[test]
    fn xp_icon_selection_changes_label_pixels_only_for_luna() {
        let style = recipe::parse(
            include_str!("../../../examples/wayland/xp-luna-columns.json"),
            Some("xp-luna-columns")).unwrap();
        let icon = &style.desktop_icons[0];
        let mut plain = vec![0; (recipe::ICON_WIDTH * recipe::ICON_HEIGHT * 4) as usize];
        let mut highlighted = plain.clone();
        paint_icon(&mut plain, icon, &style, false, None);
        paint_icon(&mut highlighted, icon, &style, true, None);
        let at = ((64 * recipe::ICON_WIDTH + 10) * 4) as usize;
        assert_eq!(&plain[at..at+4], &0_u32.to_le_bytes());
        assert_eq!(&highlighted[at..at+4], &0xd025_5ed3_u32.to_le_bytes());
        let classic = recipe::parse(
            include_str!("../../../tests/fixtures/riceplate-desktop-v5.json"),
            Some("mockup-desktop")).unwrap();
        paint_icon(&mut highlighted, &classic.desktop_icons[0], &classic, true, None);
        assert_eq!(&highlighted[at..at+4], &0xb020_2c36_u32.to_le_bytes());
    }

    #[test]
    fn recycle_bin_uses_real_validated_desktop_icon_and_original_raster() {
        let style = recipe::parse(
            include_str!("../../../examples/wayland/xp-luna-columns.json"),
            Some("xp-luna-columns")).unwrap();
        let icon = style.desktop_icons.iter()
            .find(|icon| icon.action == "trash").unwrap();
        assert_eq!(icon.label, "Recycle Bin");
        let mut pixels = vec![0; (recipe::ICON_WIDTH * recipe::ICON_HEIGHT * 4) as usize];
        paint_icon(&mut pixels, icon, &style, false, None);
        assert_eq!(&pixels[..4], &[0, 0, 0, 0]);
        let pixel = |x: u32, y: u32| -> u32 {
            let index = ((y * recipe::ICON_WIDTH + x) * 4) as usize;
            u32::from_le_bytes(pixels[index..index+4].try_into().unwrap())
        };
        assert_eq!(pixel(45, 35), 0xffac_d3e7);
        assert_ne!(pixel(45, 35), style.active);
        assert_ne!(pixel(40, 28), pixel(50, 28)); // Original bin vertical ribs
        assert!(pixels.chunks_exact(4).skip((60 * recipe::ICON_WIDTH) as usize)
            .any(|pixel| pixel != [0, 0, 0, 0]),
            "accessible shortcut label must still be rendered");
        let mut focused = vec![0; pixels.len()];
        paint_icon(&mut focused, icon, &style, true, None);
        assert_eq!(&focused[..4], &style.foreground.to_le_bytes());
    }

    #[test]
    fn desktop_icon_paint_preserves_transparent_background() {
        let style = recipe::parse(
            include_str!("../../../tests/fixtures/riceplate-desktop-v5.json"),
            Some("mockup-desktop"),
        ).unwrap();
        let icon = recipe::DesktopIcon {
            label: "Terminal".into(),
            action: "terminal".into(),
            x: 32,
            y: 112,
        };
        let mut pixels = vec![255; (recipe::ICON_WIDTH * recipe::ICON_HEIGHT * 4) as usize];
        paint_icon(&mut pixels, &icon, &style, false, None);
        assert_eq!(&pixels[0..4], &[0, 0, 0, 0]);
        assert!(pixels
            .chunks_exact(4)
            .any(|pixel| pixel == 0xff4179aa_u32.to_le_bytes()));
        assert!(pixels
            .chunks_exact(4)
            .any(|pixel| pixel == 0xfff3f7fa_u32.to_le_bytes()));
        paint_icon(&mut pixels, &icon, &style, true, None);
        assert_eq!(&pixels[0..4], &0xfff3f7fa_u32.to_le_bytes());
        assert_eq!(
            &pixels[((recipe::ICON_HEIGHT - 1) * recipe::ICON_WIDTH * 4) as usize..][..4],
            &0xfff3f7fa_u32.to_le_bytes(),
        );
    }

    #[test]
    fn draw_clips_to_surface_bounds() {
        let mut pixels = vec![0_u8; 4 * 3 * 4];
        fill_rect(&mut pixels, 4, 3, 2, 1, 20, 20, 0xff4179aa);
        assert_eq!(&pixels[0..4], &[0, 0, 0, 0]);
        assert_eq!(
            &pixels[(2 * 4 + 3) * 4..(2 * 4 + 4) * 4],
            &0xff4179aa_u32.to_le_bytes()
        );
    }


    #[test]
    fn luna_grouped_task_badge_survives_visual_ellipsis() {
        let mut luna = recipe::parse(
            include_str!("../../../examples/wayland/xp-luna-columns.json"),
            Some("xp-luna-columns")).unwrap();
        luna.native_art = Some(style_art::load(
            luna.artwork.as_ref().unwrap(), luna.font_scale).unwrap());
        let group = task_groups::TaskGroup {
            members: vec![0, 1, 2], representative: 0,
            label: "An application title with a long name".into(), active: false,
        };
        for width in [90, 100, 124, 156] {
            let short = fitted_task_label(&group, width, &luna);
            assert!(short.ends_with(" (3)"), "lost group count at {width}: {short}");
            assert!(rice_text_width(&short, &luna) <= width - 22);
        }
        let legacy = recipe::load("classic").unwrap();
        assert_eq!(fitted_task_label(&group, 156, &legacy),
                   task_groups::visible_label(&group, 156));
    }

    #[test]
    fn luna_font_metrics_clip_at_actual_pixel_width_and_keep_legacy_cells() {
        let mut luna = recipe::parse(
            include_str!("../../../examples/wayland/xp-luna-columns.json"),
            Some("xp-luna-columns")).unwrap();
        let art = style_art::load(luna.artwork.as_ref().unwrap(), luna.font_scale)
            .expect("embedded Luna artwork");
        luna.native_art = Some(art);
        assert!(rice_text_width("WWW", &luna) > rice_text_width("iii", &luna));
        let long = "Mein sehr langes Fenster – Übung";
        for allowed in [0_u32, 8, 24, 40, 65, 100] {
            let clipped = fit_rice_text(long, allowed, &luna);
            assert!(rice_text_width(&clipped, &luna) <= allowed,
                    "long text must never overpaint the neighbour at {allowed}px");
            assert!(clipped.is_char_boundary(clipped.len()));
        }
        assert_eq!(fit_rice_text("OK", 100, &luna), "OK");
        let legacy = recipe::load("classic").unwrap();
        assert_eq!(rice_text_width("WWW", &legacy), text_pixel_width("WWW", legacy.font_scale));
        assert_eq!(rice_text_width("WWW", &legacy), rice_text_width("iii", &legacy));
    }

    #[test]
    fn label_pixels_come_from_font_glyphs() {
        let mut pixels = vec![0_u8; 20 * 12 * 4];
        draw_text(&mut pixels, 20, 12, 0, 0, "A", 0xfff3f7fa);
        assert!(pixels
            .chunks_exact(4)
            .any(|color| color == 0xfff3f7fa_u32.to_le_bytes()));
    }

    #[test]
    fn auxiliary_text_keeps_legacy_pixels_when_no_private_font_is_selected() {
        let style = recipe::load("classic").unwrap();
        let mut original = vec![0_u8; 150 * 24 * 4];
        let mut auxiliary = original.clone();
        draw_text(&mut original, 150, 24, 6, 8, "November 2026", style.foreground);
        draw_auxiliary_text(&mut auxiliary, 150, 24, 6, 8,
                            "November 2026", style.foreground, &style);
        assert_eq!(auxiliary, original);
    }

    #[test]
    fn unicode_text_is_measured_in_rendered_cells_not_utf8_bytes() {
        assert_eq!(text_pixel_width("Äpfel", 1), 5 * 8);
        assert_eq!(text_pixel_width("Γεια", 2), 4 * 16);
        assert_eq!(text_pixel_width("", 2), 0);
    }

    #[test]
    fn labels_are_bounded_and_have_fallbacks() {
        assert_eq!(
            task_groups::task_label("", "org.example.Terminal"),
            "org.example.Termin"
        );
        assert_eq!(task_groups::task_label("", ""), "Window");
        assert_eq!(task_groups::task_label("Readme", "org.example"), "Readme");
    }

    #[test]
    fn clock_format_is_fixed_width_and_minute_sized() {
        let time = chrono::NaiveTime::from_hms_opt(2, 3, 59).unwrap();
        assert_eq!(time.format("%H:%M").to_string(), "02:03");
        assert!(next_clock_timeout() <= Duration::from_secs(60));
        assert!(!clock_now(luna_clock::ClockFormat::Hour24).is_empty());
        assert!(text_pixel_width("9:07 PM", 1) <= 80);
    }

    #[test]
    fn native_menu_draws_real_recipe_groups_without_opaque_overlay_elsewhere() {
        let style = recipe::parse(
            include_str!("../../../tests/fixtures/riceplate-desktop-v5.json"),
            Some("mockup-desktop"),
        ).unwrap();
        let menu = style.menu.as_ref().unwrap();
        let mut state = MenuState::default();
        state.open();
        let mut canvas = vec![0; (native_menu::WIDTH * native_menu::HEIGHT * 4) as usize];
        paint_menu(&mut canvas, menu, &style, &state);
        assert_eq!(&canvas[0..4], &style.active.to_le_bytes());
        assert_eq!(&canvas[(100 * native_menu::WIDTH * 4) as usize..][..4],
                   &style.background.to_le_bytes());
        assert_eq!(state.current_action(menu), Some("applications"));
        state.group_by(menu, 1);
        assert_eq!(state.current_action(menu), Some("lock"));
    }
}
