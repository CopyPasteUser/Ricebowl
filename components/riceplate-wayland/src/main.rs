//! Native RicePlate experiment: an input-capable, idle event-driven layer surface.
//! No session takeover: launch only inside an already running Wayland session.

use std::{error::Error, os::fd::AsFd, process::Command, sync::mpsc, time::{Duration, Instant}};

use chrono::{Datelike, Local, Timelike};
use accesskit::{ActionRequest, Role as AccessibleRole};
use font8x8::{UnicodeFonts, BASIC_FONTS, LATIN_FONTS, GREEK_FONTS, HIRAGANA_FONTS, MISC_FONTS};
mod accessibility;
mod brightness;
mod calendar;
mod desktop_layout;
mod icon_positions;
mod installed_apps;
mod menu_pins;
mod native_menu;
mod osd;
mod power;
mod recipe;
mod style_art;
mod ricepop;
mod system_status;
mod task_groups;
mod task_navigation;
mod tray;
use tray::{MenuChoice as TrayMenuChoice, MenuHit as TrayMenuHit, PopupHit as TrayHit};
use native_menu::{Hit as MenuHit, MenuState};
use power::PowerStatus;
use ricepop::{Intent as NotificationIntent, Request as NotificationRequest,
              State as NotificationState};
use system_status::{Audio, ControlAction, SystemStatus};

enum StatusEvent {
    State(SystemStatus),
    Control { action: ControlAction, success: bool, state: SystemStatus },
    ObservedAudio(Audio),
}
use calendar::{CalendarState, Hit as CalendarHit};
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
use wayland_protocols_wlr::foreign_toplevel::v1::client::{
    zwlr_foreign_toplevel_handle_v1::{self, ZwlrForeignToplevelHandleV1},
    zwlr_foreign_toplevel_manager_v1::{self, ZwlrForeignToplevelManagerV1},
};

const MAX_WIDTH: u32 = 16384;
const MAX_HEIGHT: u32 = 256;
const MAX_OUTPUT_PANELS: usize = 8;
const BTN_LEFT: u32 = 0x110;
const BTN_RIGHT: u32 = 0x111;

fn clock_now() -> String {
    Local::now().format("%H:%M").to_string()
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
    if matches!(arguments.as_slice(), [arg] if arg == "--help") {
        println!("Usage: riceplate-native [--recipe classic|chrome|/absolute/private.json [--preview-menu|--preview-calendar]]");
        return Ok(());
    }
    let (recipe_name, preview_menu, preview_calendar) = match arguments.as_slice() {
        [] => ("classic", false, false),
        [flag, recipe] if flag == "--recipe" => (recipe.as_str(), false, false),
        [flag, recipe, preview] if flag == "--recipe" && preview == "--preview-menu" =>
            (recipe.as_str(), true, false),
        [flag, recipe, preview] if flag == "--recipe" && preview == "--preview-calendar" =>
            (recipe.as_str(), false, true),
        _ => {
            return Err(
                "Usage: riceplate-native [--recipe classic|chrome|/absolute/private.json [--preview-menu|--preview-calendar]]".into(),
            )
        }
    };
    let mut recipe = recipe::load(recipe_name)?;
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
    if preview_menu && recipe.menu.is_none() {
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
    let desktop_network = recipe.composition.as_ref().is_some_and(|composition|
        composition.widgets.iter().any(|widget| matches!(&widget.kind,
            recipe::DesktopWidgetKind::System | recipe::DesktopWidgetKind::Network)));
    let desktop_audio = recipe.composition.as_ref().is_some_and(|composition|
        composition.widgets.iter().any(|widget| matches!(&widget.kind,
            recipe::DesktopWidgetKind::System | recipe::DesktopWidgetKind::Audio)));
    let poll_network = desktop_network || status_present(Widget::Network)
        || menu_controls.contains(&ControlAction::WifiToggle)
        || panel_controls.contains(&ControlAction::WifiToggle);
    // A native full desktop has volume OSD even when a rice omits the audio
    // indicator. Nested design previews retain the old opt-in behavior.
    let full_session = std::env::var("RICEBOWL_DE_NESTED").as_deref() != Ok("1");
    let poll_audio = full_session || desktop_audio || status_present(Widget::Audio)
        || menu_controls.iter().chain(panel_controls.iter()).any(|action|
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
    let shm = Shm::bind(&globals, &qh)?;
    let toplevel_manager: Option<ZwlrForeignToplevelManagerV1> = globals.bind(&qh, 1..=3, ()).ok();
    if toplevel_manager.is_none() {
        eprintln!("RicePlate: compositor lacks wlr-foreign-toplevel-management; taskbar disabled");
    }
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
    layer.set_size(0, recipe.height);
    layer.set_exclusive_zone(recipe.height as i32);
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
    // Read-only widgets must not intercept pointer input from client windows.
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
            surface.set_keyboard_interactivity(KeyboardInteractivity::None);
            surface.wl_surface().set_input_region(Some(empty_input.wl_region()));
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
        MenuLayer { surface, pool: None, configured: false, output: None }
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

    let mut app = RicePlate {
        compositor,
        layer_shell,
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
        menu_state: MenuState::with_pins(saved_menu_pins),
        notification_state: NotificationState::default(),
        notification_sender: None,
        calendar_state: CalendarState::new(Local::now().date_naive()),
        calendar_focused: false,
        recipe,
        clock: clock_now(),
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
        keyboard: None,
        focused_icon: None,
        keyboard_icon_surface: None,
        focused_panel: None,
        focused_target: None,
        icon_drag: None,
        icon_position_dirty: false,
        icon_outputs,
        menu_focused: false,
        primary_seat: None,
        primary_output: None,
        primary_output_seen: false,
        toplevel_manager,
        tasks: Vec::new(),
        task_offset: 0,
        pool: None,
        width: 0,
        height: 0,
        configured: false,
        closed: false,
        frame_pending: false,
        needs_redraw: false,
        accessibility: None,
    };
    if preview_menu && !preview_secondary_menu { app.set_menu_visible(true, &qh); }
    if preview_calendar && !preview_secondary_calendar {
        app.set_calendar_visible(true, &qh);
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
                       app.notification_state.refresh_timeout(Instant::now())]
            .into_iter().flatten().min().unwrap_or_else(next_clock_timeout);
        event_loop.dispatch(Some(timeout), &mut app)?;
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
        let current = clock_now();
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
}

struct MenuLayer {
    surface: LayerSurface,
    pool: Option<SlotPool>,
    configured: bool,
    output: Option<wl_output::WlOutput>,
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
    frame_pending: bool,
    needs_redraw: bool,
    task_offset: usize,
}

struct RicePlate {
    compositor: CompositorState,
    layer_shell: LayerShell,
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
    keyboard: Option<wl_keyboard::WlKeyboard>,
    focused_icon: Option<usize>,
    keyboard_icon_surface: Option<wl_surface::WlSurface>,
    focused_panel: Option<wl_surface::WlSurface>,
    focused_target: Option<KeyboardTarget>,
    icon_drag: Option<IconDrag>,
    icon_position_dirty: bool,
    icon_outputs: icon_positions::OutputPositions,
    menu_focused: bool,
    primary_seat: Option<wl_seat::WlSeat>,
    primary_output: Option<wl_output::WlOutput>,
    primary_output_seen: bool,
    toplevel_manager: Option<ZwlrForeignToplevelManagerV1>,
    tasks: Vec<Task>,
    task_offset: usize,
    pool: Option<SlotPool>,
    width: u32,
    height: u32,
    configured: bool,
    closed: bool,
    frame_pending: bool,
    needs_redraw: bool,
    accessibility: Option<accessibility::Bridge>,
}

impl RicePlate {
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
                            let available = control.is_none_or(|item|
                                item.available(&self.system_status) && self.control_pending.is_none());
                            let name = if let Some(item) = control {
                                format!("{}, {}, {}", action.label, item.state_label(&self.system_status),
                                    if self.control_pending == Some(item) { "applying" }
                                    else if self.control_pending.is_some() { "busy" }
                                    else if self.control_result == Some((item, false)) { "failed" }
                                    else if !item.available(&self.system_status) { "unavailable" }
                                    else { "ready" })
                            } else { action.label.clone() };
                            model.add(base + 30 + index as u64, base, AccessibleRole::Button,
                                name, available.then(|| Target::PanelAction(action.id.clone())));
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
                    Widget::Network => model.add(base + 5, base, AccessibleRole::Status,
                        format!("Network: {}", self.system_status.network.label()), None),
                    Widget::Audio => model.add(base + 6, base, AccessibleRole::Status,
                        format!("Audio: {}", self.system_status.audio.label()), None),
                    Widget::Battery => model.add(base + 7, base, AccessibleRole::Status,
                        format!("Battery: {}", self.power.label()), None),
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
                    model.add(30_100 + index as u64, 30_000, AccessibleRole::Button,
                              item.label.clone(), Some(Target::DesktopIcon(index)));
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
                    };
                    let role = if matches!(&widget.kind, recipe::DesktopWidgetKind::Text(_)) {
                        AccessibleRole::Label
                    } else { AccessibleRole::Status };
                    model.add(31_100 + index as u64, 31_000, role,
                              description, None);
                }
            }
        }
        if self.menu_state.visible && self.active_menu.is_some() {
            if self.notification_state.open {
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
                if self.notification_state.loading {
                    model.add(22_150, 22_000, AccessibleRole::Status, "Loading notifications", None);
                } else if let Some(error) = self.notification_state.error {
                    model.add(22_150, 22_000, AccessibleRole::Alert, error, None);
                } else if let Some(detail) = self.notification_state.detail_notice() {
                    model.add(22_160, 22_000, AccessibleRole::Group,
                              format!("Notification from {}", detail.app_name), None);
                    model.add(22_161, 22_160, AccessibleRole::Label, detail.summary.clone(), None);
                    model.add(22_162, 22_160, AccessibleRole::Label, detail.body.clone(), None);
                    if self.notification_state.body_page_count() > 1 {
                        model.add(22_163, 22_160, AccessibleRole::Button,
                                  "Previous message page", Some(Target::NotificationBodyPage(-1)));
                        model.add(22_164, 22_160, AccessibleRole::Button,
                                  "Next message page", Some(Target::NotificationBodyPage(1)));
                    }
                    if !self.notification_state.show_history {
                        for (index, action) in detail.actions.iter().enumerate()
                            .skip(self.notification_state.first_action_row())
                            .take(ricepop::VISIBLE_ROWS) {
                            model.add(22_300 + index as u64, 22_160, AccessibleRole::Button,
                                      action.label.clone(),
                                      Some(Target::NotificationInvoke(detail.id, action.key.clone())));
                        }
                    }
                } else {
                    for (index, notice) in self.notification_state.visible_notices().iter()
                        .enumerate().skip(self.notification_state.first_row())
                        .take(ricepop::VISIBLE_ROWS) {
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
                let group_role = if menu.presentation == recipe::MenuPresentation::Sidebar {
                    AccessibleRole::Button
                } else {
                    AccessibleRole::Tab
                };
                for (index, group) in menu.groups.iter().enumerate() {
                    model.add(20_100 + index as u64, 20_000, group_role,
                              group.title.clone(), Some(Target::MenuGroup(index)));
                }
                if let Some(sections) = self.menu_state.composed_sections(menu) {
                    for (index, section) in sections.iter().enumerate() {
                        model.add(20_300 + index as u64, 20_000, AccessibleRole::Label,
                                  section.title.to_string(), None);
                    }
                }
                for (index, action) in self.menu_state.actions(menu).into_iter().enumerate()
                    .skip(self.menu_state.first_action_row()).take(native_menu::VISIBLE_ACTIONS) {
                    let enabled = action != "logout" || logout_available();
                    model.add(20_500 + index as u64, 20_000, AccessibleRole::Button,
                              self.menu_state.label(action),
                              enabled.then(|| Target::MenuAction(action.to_string())));
                }
                model.add(20_980, 20_000, AccessibleRole::Label,
                          if self.menu_state.view == native_menu::View::Search {
                              format!("Searching for {}. Type to refine; Backspace removes a letter",
                                      self.menu_state.search)
                          } else { "Type to search; F2 pins; F3 shows saved actions".to_string() },
                          None);
                model.add(20_990, 20_000, AccessibleRole::Button,
                          "Show saved actions", Some(Target::MenuSaved));
                model.add(20_999, 20_000, AccessibleRole::Button,
                          "Close menu", Some(Target::MenuClose));
                if self.menu_focused { model.focus = 20_500 + self.menu_state.selected as u64; }
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
                        None => base,
                    };
                }
            } else if let Some(index) = self.focused_icon {
                if self.keyboard_icon_surface.is_some() {
                    model.focus = 30_100 + index as u64;
                }
            }
        }
        model.window_focused = self.menu_focused || self.calendar_focused
            || self.tray_popup_focused || self.focused_panel.is_some()
            || self.keyboard_icon_surface.is_some();
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
            Target::DesktopIcon(index) => {
                if let Some(icon) = self.icon_layers.get(index) {
                    if let Some(item) = self.recipe.desktop_icons.get(icon.recipe_index) {
                        let action = item.action.clone();
                        self.activate_action(&action, qh);
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
                self.menu_state.open_group(index);
                self.redraw_menu(qh);
            }
            Target::MenuAction(action) => self.activate_action(&action, qh),
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
                self.notification_state.change_body_page(delta);
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

    fn activate_group(&mut self, index: usize) {
        let groups = self.grouped_tasks();
        if let Some(group) = groups.get(index) {
            let active_index = group.members.iter().copied()
                .find(|&member| self.tasks[member].active);
            let (target, minimize) = task_groups::click_target(group, active_index);
            if minimize {
                self.tasks[target].handle.set_minimized();
            } else if let Some(seat) = self.primary_seat.as_ref() {
                self.tasks[target].handle.activate(seat);
            }
        }
    }

    fn handle_panel_key(&mut self, key: Keysym, qh: &QueueHandle<Self>) -> bool {
        let Some(surface) = self.focused_panel.as_ref() else { return false; };
        let Some((mirror, width, offset)) = self.panel_geometry(surface) else { return false; };
        let groups = self.grouped_tasks();
        let count = groups.len();
        match key {
            Keysym::Right | Keysym::Tab | Keysym::Down
            | Keysym::Left | Keysym::ISO_Left_Tab | Keysym::Up => {
                let delta = if matches!(key, Keysym::Left | Keysym::ISO_Left_Tab | Keysym::Up) {
                    -1
                } else { 1 };
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
            Keysym::Return | Keysym::KP_Enter | Keysym::space | Keysym::Menu => {
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
            Keysym::Escape => {
                self.focused_target = None;
                self.request_redraw(qh);
            }
            _ => return false,
        }
        true
    }

    fn save_icon_positions(&mut self) {
        if !self.icon_position_dirty {
            return;
        }
        if let Err(error) = icon_positions::save(&self.recipe, &self.icon_outputs) {
            eprintln!("RicePlate: cannot persist desktop icon positions: {error}");
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
            surface.set_size(0, self.recipe.height);
            surface.set_exclusive_zone(self.recipe.height as i32);
            surface.set_keyboard_interactivity(KeyboardInteractivity::OnDemand);
            surface.commit();
            self.mirrors.push(PanelMirror {
                output, surface, pool: None, width: 0, height: 0,
                configured: false, frame_pending: false, needs_redraw: false,
                task_offset: 0,
            });
        }
        // Desktop shortcut surfaces follow the same explicit secondary output
        // ownership as panels. No full-screen input-grabbing wallpaper layer.
        let before = self.icon_layers.len();
        self.icon_layers.retain(|icon| icon.bound_output.as_ref()
            .is_none_or(|output| outputs.contains(output)));
        if before != self.icon_layers.len() {
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
        self.widget_layers.retain(|widget| widget.bound_output.as_ref()
            .is_none_or(|output| outputs.contains(output)));
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
                    surface.set_keyboard_interactivity(KeyboardInteractivity::None);
                    surface.wl_surface().set_input_region(Some(input.wl_region()));
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
                });
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
    }

    fn redraw_mirror(&mut self, index: usize, qh: &QueueHandle<Self>) {
        let groups = self.grouped_tasks();
        let selected = if self.focused_panel.as_ref()
            == self.mirrors.get(index).map(|mirror| mirror.surface.wl_surface()) {
            self.focused_target
        } else { None };
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
                mirror.frame_pending = true;
                mirror.surface.commit();
                return;
            }
        };
        paint_panel(canvas, mirror.width, mirror.height, &self.recipe, &groups,
                    &self.clock, &self.power, &self.system_status, &self.tray_state,
                    mirror.task_offset, selected, self.control_pending, self.control_result);
        surface.damage_buffer(0, 0, mirror.width as i32, mirror.height as i32);
        if let Err(error) = buffer.attach_to(surface) {
            eprintln!("RicePlate: cannot attach output panel: {error}");
            return;
        }
        surface.frame(qh, FrameCallbackData(surface.clone()));
        mirror.frame_pending = true;
        mirror.needs_redraw = false;
        mirror.surface.commit();
    }

    fn set_menu_visible(&mut self, visible: bool, qh: &QueueHandle<Self>) {
        if visible {
            if let Some(surface) = self.menu_layer.as_ref()
                .map(|menu| menu.surface.wl_surface().clone()) {
                self.show_menu_at(surface, qh);
            }
            return;
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
    }

    fn show_menu_at(&mut self, surface: wl_surface::WlSurface, qh: &QueueHandle<Self>) {
        if !self.menu_layer.iter().chain(self.menu_mirrors.iter()).any(|menu|
            menu.surface.wl_surface() == &surface) { return; }
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
        if action == "notifications" {
            self.request_notifications(NotificationIntent::Refresh, qh);
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
            return;
        }
        if self.menu_state.visible {
            self.set_menu_visible(false, qh);
        }
        if action == "logout" && !logout_available() {
            eprintln!("RicePlate: log out unavailable outside a labwc-managed session");
            return;
        }
        if action.starts_with("desktop:") {
            // Let GLib handle field codes, DBusActivatable, terminal preferences
            // and desktop-file quoting. Never interpret Exec as a shell command.
            if let Some(path) = self.menu_state.app_path(action) {
                if let Err(error) = Command::new("gio").arg("launch").arg(path).spawn() {
                    eprintln!("RicePlate: cannot launch desktop application: {error}");
                }
            }
            return;
        }
        let (program, args): (&str, &[&str]) = match action {
            "applications" => ("fuzzel", &[]),
            "terminal" => ("foot", &[]),
            "settings" => ("ricebowl", &["de", "settings"]),
            "lock" => ("swaylock", &["-f"]),
            "logout" => ("labwc", &["--exit"]),
            _ => return, // Validated recipe contract disallows other IDs.
        };
        if let Err(error) = Command::new(program).args(args).spawn() {
            eprintln!("RicePlate: cannot run {action}: {error}");
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
        let (buffer, canvas) = match pool.create_buffer(
            native_menu::WIDTH as i32,
            native_menu::HEIGHT as i32,
            (native_menu::WIDTH * 4) as i32,
            wl_shm::Format::Argb8888,
        ) {
            Ok(result) => result,
            Err(error) => {
                eprintln!("RicePlate: native menu buffer unavailable: {error}");
                return;
            }
        };
        if self.notification_state.open {
            paint_notifications(canvas, &self.recipe, &self.notification_state);
        } else {
            paint_menu(canvas, menu, &self.recipe, &self.menu_state);
        }
        surface.damage_buffer(0, 0, native_menu::WIDTH as i32, native_menu::HEIGHT as i32);
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
        paint_icon(canvas, icon, self.recipe.active, self.recipe.foreground,
                   self.focused_icon == Some(index), icon_pixels);
        surface.damage_buffer(0, 0, width as i32, height as i32);
        if let Err(error) = buffer.attach_to(surface) {
            eprintln!("RicePlate: desktop icon attach failed: {error}");
            self.closed = true;
            return;
        }
        layer.surface.commit();
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
        };
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
        paint_desktop_widget(canvas, title, &lines, &self.recipe);
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
            .and_then(|name| self.icon_outputs.for_output(name, self.recipe.desktop_icons.len()))
            .and_then(|positions| positions.get(layer.recipe_index)).copied()
            .unwrap_or(icon_positions::Coordinates { x: original.x, y: original.y })
    }

    fn move_icon(&mut self, layer_index: usize, desired: (u32, u32)) {
        let recipe_index = self.icon_layers[layer_index].recipe_index;
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

    fn reflow_icons(&mut self) {
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
                self.icon_outputs.for_output(name, local_icons.len())) {
                for (icon, position) in local_icons.iter_mut().zip(positions) {
                    (icon.x, icon.y) = (position.x, position.y);
                }
            }
            let placement = if let Some(composition) = &self.recipe.composition {
                desktop_layout::compose(&local_icons, composition, width, height,
                    self.recipe.top, self.recipe.height,
                    self.recipe.compact.as_ref().map_or(720, |(threshold, _)| *threshold))
                    .0[layer.recipe_index]
            } else {
                desktop_layout::place(&local_icons, width, height,
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
                self.icon_outputs.for_output(name, local_icons.len())) {
                for (icon, position) in local_icons.iter_mut().zip(positions) {
                    (icon.x, icon.y) = (position.x, position.y);
                }
            }
            let placement = desktop_layout::compose(
                &local_icons, composition, width, height, self.recipe.top, self.recipe.height,
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
        if self.tray_menu_state.visible {
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
        self.needs_redraw = true;
        if !self.frame_pending {
            self.redraw(qh);
        }
        for index in 0..self.mirrors.len() {
            self.mirrors[index].needs_redraw = true;
            if !self.mirrors[index].frame_pending { self.redraw_mirror(index, qh); }
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
        let width = self.width;
        let height = self.height;
        let groups = self.grouped_tasks();
        let selected = if self.focused_panel.as_ref() == Some(self.layer.wl_surface()) {
            self.focused_target
        } else { None };
        let surface = self.layer.wl_surface();
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
                self.frame_pending = true;
                self.layer.commit();
                return;
            }
        };
        paint_panel(canvas, width, height, &self.recipe, &groups,
                    &self.clock, &self.power, &self.system_status, &self.tray_state,
                    self.task_offset, selected, self.control_pending, self.control_result);
        surface.damage_buffer(0, 0, width as i32, height as i32);
        if let Err(error) = buffer.attach_to(surface) {
            eprintln!("RicePlate: failed to attach Wayland buffer: {error}");
            self.closed = true;
            return;
        }
        surface.frame(qh, FrameCallbackData(surface.clone()));
        self.frame_pending = true;
        self.needs_redraw = false;
        self.layer.commit();
    }
}

fn paint_panel(canvas: &mut [u8], width: u32, height: u32,
               style: &PanelStyle, groups: &[TaskGroup], clock: &str,
               power: &PowerStatus, status: &SystemStatus, tray_state: &tray::State, offset: usize,
               selected: Option<KeyboardTarget>, pending: Option<ControlAction>,
               result: Option<(ControlAction, bool)>) {
    for pixel in canvas.chunks_exact_mut(4) {
        pixel.copy_from_slice(&style.background.to_le_bytes());
    }
    for placed in recipe::layout(style, width, groups.len()) {
        match placed.widget {
            Widget::Launcher => {
                fill_rect(canvas, width, height, placed.x, 0, placed.width, height,
                          style.active);
                draw_rice_text(canvas, width, height,
                          placed.x + placed.width.saturating_sub(32 * style.font_scale) / 2,
                          height.saturating_sub(8 * style.font_scale) / 2,
                          "Apps", style.foreground, style);
                if selected == Some(KeyboardTarget::Launcher) {
                    paint_focus_border(canvas, width, height, placed.x, placed.width,
                                       if style.focus != 0 { style.focus } else { style.foreground });
                }
            }
            Widget::Action(index) => {
                if let Some(action) = style.actions.get(index as usize) {
                    let control = action.control.then(|| ControlAction::from_id(&action.id)).flatten();
                    let available = control.is_none_or(|item|
                        item.available(status) && pending.is_none());
                    if available {
                        fill_rounded_rect(canvas, width, height, placed.x + 2, 3,
                            placed.width.saturating_sub(4), height.saturating_sub(6),
                            style.task_radius, style.active);
                    }
                    let second_line = control.map(|item| {
                        if pending == Some(item) { "Wait".to_string() }
                        else if pending.is_some() { "Busy".to_string() }
                        else if result == Some((item, false)) { "Failed".to_string() }
                        else { item.state_label(status) }
                    });
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
                    if group.active {
                        fill_rounded_rect(canvas, width, height, x, 0,
                                          cell_width.saturating_sub(2), height,
                                          style.task_radius, style.active);
                    }
                    let label = task_groups::visible_label(group, cell_width);
                    draw_rice_text(canvas, width, height, x + 10,
                              height.saturating_sub(8 * style.font_scale) / 2,
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
                draw_rice_text(canvas, width, height,
                          placed.x + placed.width.saturating_sub(40 * style.font_scale) / 2,
                          height.saturating_sub(8 * style.font_scale) / 2,
                          clock, style.foreground, style);
            }
            Widget::Battery => {
                let label = power.label();
                draw_rice_text(canvas, width, height,
                          placed.x + placed.width.saturating_sub(label.len() as u32 * 8 * style.font_scale) / 2,
                          height.saturating_sub(8 * style.font_scale) / 2,
                          &label, style.foreground, style);
            }
            Widget::Network | Widget::Audio => {
                let label = if placed.widget == Widget::Network {
                    status.network.label().to_owned()
                } else {
                    status.audio.label()
                };
                draw_rice_text(canvas, width, height,
                          placed.x + placed.width.saturating_sub(label.len() as u32 * 8 * style.font_scale) / 2,
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
                    draw_text(canvas, width, height, placed.x + tray::WIDTH - 27,
                        height.saturating_sub(8) / 2, &format!("+{overflow}"), style.foreground);
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
    draw_text(canvas, width, height, 16, 10, notice.title, style.foreground);
    draw_text(canvas, width, height, 16, 29, &notice.value, style.foreground);
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

fn paint_tray_menu(canvas: &mut [u8], style: &PanelStyle, popup: &tray::MenuPopup) {
    let (width, height) = (tray::POPUP_WIDTH, tray::POPUP_HEIGHT);
    for pixel in canvas.chunks_exact_mut(4) {
        pixel.copy_from_slice(&style.background.to_le_bytes());
    }
    fill_rect(canvas, width, height, 0, 0, width, 36, style.active);
    if popup.parent_id() != popup.root_id {
        draw_text(canvas, width, height, 12, 13, "<", style.foreground);
    }
    let header: String = popup.title.chars().take(if popup.parent_id() == popup.root_id {
        24
    } else { 20 }).collect();
    draw_text(canvas, width, height, if popup.parent_id() == popup.root_id { 12 } else { 36 },
              13, &header, style.foreground);
    draw_text(canvas, width, height, width - 24, 13, "X", style.foreground);
    for (index, row) in popup.rows().iter().enumerate().skip(popup.first)
        .take(tray::POPUP_ROWS) {
        let top = tray::POPUP_ROW_TOP + (index - popup.first) as u32 * tray::POPUP_ROW_HEIGHT;
        if matches!(&row.kind, tray::MenuKind::Separator) {
            fill_rect(canvas, width, height, 12, top + 14, width - 24, 1, style.active);
            continue;
        }
        if index == popup.selected && row.selectable() {
            fill_rounded_rect(canvas, width, height, 6, top + 1, width - 12,
                              tray::POPUP_ROW_HEIGHT - 2, style.task_radius,
                              if style.hover != 0 { style.hover } else { style.active });
        }
        let marker = match &row.kind {
            tray::MenuKind::Action { checked: true, radio: true } => "*",
            tray::MenuKind::Action { checked: true, .. } => "x",
            _ => "",
        };
        draw_text(canvas, width, height, 12, top + 11, marker, style.foreground);
        let label: String = row.label.chars().take(25).collect();
        let color = if row.enabled { style.foreground }
        else if style.disabled != 0 { style.disabled } else {
            let fg = style.foreground.to_le_bytes();
            let bg = style.background.to_le_bytes();
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
    fill_rect(canvas, width, height, 0, 201, width, 1, style.active);
    draw_text(canvas, width, height, 12, 216,
              if popup.first > 0 { "< Previous" } else { "First page" }, style.foreground);
    draw_text(canvas, width, height, 169, 216,
              if popup.first + tray::POPUP_ROWS < popup.rows().len() {
                  "Next >"
              } else { "Last page" }, style.foreground);
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

fn paint_menu(canvas: &mut [u8], menu: &recipe::NativeMenu, style: &PanelStyle, state: &MenuState) {
    let width = native_menu::WIDTH;
    let height = native_menu::HEIGHT;
    for pixel in canvas.chunks_exact_mut(4) {
        pixel.copy_from_slice(&style.background.to_le_bytes());
    }
    fill_rect(canvas, width, height, 0, 0, width, 38, style.active);
    draw_rice_text(
        canvas,
        width,
        height,
        16,
        if style.font_scale == 1 { 15 } else { 11 },
        &menu.title.chars().take((width.saturating_sub(32) / (8 * style.font_scale)) as usize)
            .collect::<String>(),
        style.foreground,
        style,
    );
    let sidebar = menu.presentation == recipe::MenuPresentation::Sidebar;
    let groups = menu.groups.len().max(1) as u32;
    if sidebar {
        // Structural variant: a persistent navigation rail, with actions and
        // search in an independent content column. All colors are rice tokens.
        fill_rect(canvas, width, height, native_menu::SIDEBAR_WIDTH - 2,
                  39, 2, height - 67, style.active);
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
                      if style.hover != 0 { style.hover } else { style.active });
        }
        let available = section_width.saturating_sub(16) / (8 * style.font_scale);
        let label: String = group.title.chars().take(available as usize).collect();
        draw_rice_text(canvas, width, height, x + 8,
                  y + section_height.saturating_sub(8 * style.font_scale) / 2,
                  &label, style.foreground, style);
    }
    let content_x = if sidebar { native_menu::SIDEBAR_WIDTH + 8 } else { 12 };
    if state.view == native_menu::View::Search {
        draw_text(canvas, width, height, content_x, 91,
                  &format!("Find: {}", state.search), style.foreground);
    } else if state.view == native_menu::View::Saved {
        draw_text(canvas, width, height, content_x, 91,
                  &format!("Saved actions: {}", state.actions(menu).len()), style.foreground);
    }
    if let Some(sections) = state.composed_sections(menu) {
        for section in sections {
            draw_text(canvas, width, height, content_x, section.top + 3,
                      section.title, style.foreground);
            if section.items.is_empty() {
                let empty = match section.kind {
                    recipe::MenuContentKind::Favorites => "No favorites yet",
                    recipe::MenuContentKind::AppsList | recipe::MenuContentKind::AppsGrid =>
                        "No installed apps",
                    recipe::MenuContentKind::Actions => "No actions",
                };
                draw_text(canvas, width, height, content_x + 5,
                          section.top + 28, empty, style.foreground);
            }
            for tile in section.items {
                if tile.index == state.selected {
                    fill_rounded_rect(canvas, width, height, tile.x + 2, tile.y + 2,
                                      tile.width.saturating_sub(4), tile.height.saturating_sub(4),
                                      style.task_radius, style.active);
                }
                let label = if tile.action == "logout" && !logout_available() {
                    "Log out (unavailable)"
                } else { state.label(tile.action) };
                let pinned = state.pins.iter().any(|pin| pin.as_str() == tile.action);
                if tile.grid {
                    // A compact letter tile, not a promise of themed app icons.
                    let initial: String = label.chars().next().unwrap_or('?').to_uppercase().collect();
                    draw_text(canvas, width, height, tile.x + 9, tile.y + 9,
                              &initial, style.foreground);
                    let short: String = label.chars().take(9).collect();
                    draw_text(canvas, width, height, tile.x + 9, tile.y + 27,
                              &short, style.foreground);
                } else {
                    let cap = if sidebar { if pinned { 18 } else { 20 } }
                              else if pinned { 32 } else { 34 };
                    let short: String = label.chars().take(cap).collect();
                    draw_text(canvas, width, height, tile.x + 10, tile.y + 12,
                              &format!("{}{}", if pinned { "* " } else { "" }, short),
                              style.foreground);
                }
            }
        }
    } else {
    let actions = state.actions(menu);
    if actions.is_empty() {
        draw_text(canvas, width, height, content_x, 135,
                  if state.view == native_menu::View::Saved {
                      "No saved actions"
                  } else { "No matching actions" }, style.foreground);
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
                    if style.hover != 0 { style.hover } else { style.active },
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
                          { style.disabled } else { style.foreground }, style);
        }
    }
    }
    draw_text(
        canvas,
        width,
        height,
        12,
        height - 16,
        state.notice.unwrap_or("Type to find  F2 Pin  F3 Saved"),
        style.foreground,
    );
}

fn notification_glyphs(value: &str, limit: usize) -> String {
    value.chars().map(|c| if c.is_control() { ' ' } else { c })
        .take(limit).collect()
}

fn paint_notifications(canvas: &mut [u8], style: &PanelStyle, state: &NotificationState) {
    let width = native_menu::WIDTH;
    let height = native_menu::HEIGHT;
    for pixel in canvas.chunks_exact_mut(4) {
        pixel.copy_from_slice(&style.background.to_le_bytes());
    }
    fill_rect(canvas, width, height, 0, 0, width, 38, style.active);
    draw_text(canvas, width, height, 14, 15, "Notifications", style.foreground);
    if state.sync_error {
        draw_text(canvas, width, height, 250, 15, "Offline", style.foreground);
    }
    if state.detail_id.is_none() {
        let selected_tab_x = if state.show_history { 164 } else { 4 };
        fill_rounded_rect(canvas, width, height, selected_tab_x, 41, 152, 42,
                          style.task_radius, style.active);
        draw_text(canvas, width, height, 14, 54,
                  &format!("Active ({})", state.notices.len()), style.foreground);
        draw_text(canvas, width, height, 174, 54,
                  &format!("Past ({})", state.history.len()), style.foreground);
    }
    if state.loading {
        draw_text(canvas, width, height, 14, 120, "Loading alerts...", style.foreground);
    } else if let Some(error) = state.error {
        draw_text(canvas, width, height, 14, 120, error, style.foreground);
        draw_text(canvas, width, height, 14, 145, "Refresh to try again", style.foreground);
    } else if let Some(notice) = state.detail_notice() {
        let source = if notice.app_name.is_empty() { "Unknown app" } else { &notice.app_name };
        draw_text(canvas, width, height, 14, 49,
                  &notification_glyphs(&format!("{source} / {}", notice.urgency), 37),
                  style.foreground);
        draw_text(canvas, width, height, 14, 72,
                  &notification_glyphs(&notice.summary, 36), style.foreground);
        let lines = ricepop::body_lines(&notice.body);
        let pages = state.body_page_count();
        if pages > 1 {
            draw_text(canvas, width, height, 195, 87,
                      &format!("Text {}/{} < >", state.body_page + 1, pages), style.foreground);
        }
        for (row, line) in lines.iter().skip(state.body_page * ricepop::BODY_LINES_PER_PAGE)
            .take(ricepop::BODY_LINES_PER_PAGE).enumerate() {
            draw_text(canvas, width, height, 14, 103 + row as u32 * 16,
                      &notification_glyphs(line, ricepop::BODY_WIDTH), style.foreground);
        }
        if notice.actions.is_empty() || state.show_history {
            draw_text(canvas, width, height, 14, 180, "No available actions", style.foreground);
        } else {
            draw_text(canvas, width, height, 14, 138,
                      &format!("Actions ({}) - Enter to use", notice.actions.len()),
                      style.foreground);
            for (position, action) in notice.actions.iter()
                .skip(state.first_action_row()).take(ricepop::VISIBLE_ROWS).enumerate() {
                let row_index = state.first_action_row() + position;
                let y = ricepop::ACTION_TOP + position as u32 * ricepop::ACTION_HEIGHT;
                if row_index == state.selected_action {
                    fill_rounded_rect(canvas, width, height, 8, y, width - 16, 29,
                                      style.task_radius, style.active);
                }
                draw_text(canvas, width, height, 18, y + 9,
                          &notification_glyphs(&action.label, 33), style.foreground);
            }
        }
    } else if state.visible_notices().is_empty() {
        draw_text(canvas, width, height, 14, 120,
                  if state.show_history { "No past alerts" } else { "No active alerts" },
                  style.foreground);
    } else {
        for (position, notice) in state.visible_notices().iter().skip(state.first_row())
            .take(ricepop::VISIBLE_ROWS).enumerate() {
            let row_index = state.first_row() + position;
            let y = ricepop::ROW_TOP + position as u32 * ricepop::ROW_HEIGHT;
            if row_index == state.selected {
                fill_rounded_rect(canvas, width, height, 8, y, width - 16, 50,
                                  style.task_radius, style.active);
            }
            let summary = notification_glyphs(&notice.summary, 35);
            let app = notification_glyphs(&notice.app_name, 35);
            draw_text(canvas, width, height, 18, y + 10,
                      if summary.is_empty() { "(No title)" } else { &summary },
                      style.foreground);
            draw_text(canvas, width, height, 18, y + 28, &app, style.foreground);
        }
    }
    fill_rect(canvas, width, height, 0, 261, width, 1, style.foreground);
    draw_text(canvas, width, height, 14, 279,
              if state.detail_id.is_some() { "Esc List" } else { "Esc Back" }, style.foreground);
    draw_text(canvas, width, height, 98, 279, "R Refresh", style.foreground);
    draw_text(canvas, width, height, 193, 279,
              if state.selected_id().is_some() { "Del Dismiss" } else { "Unavailable" },
              style.foreground);
}

fn paint_calendar(canvas: &mut [u8], style: &PanelStyle, state: &CalendarState) {
    let width = calendar::WIDTH;
    let height = calendar::HEIGHT;
    for pixel in canvas.chunks_exact_mut(4) {
        pixel.copy_from_slice(&style.background.to_le_bytes());
    }
    fill_rect(canvas, width, height, 0, 0, width, 56, style.active);
    draw_text(canvas, width, height, 12, 22,
              &state.month.format("%B %Y").to_string(), style.foreground);
    draw_text(canvas, width, height, 262, 22, "<", style.foreground);
    draw_text(canvas, width, height, 306, 22, ">", style.foreground);
    for (index, weekday) in ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"].iter().enumerate() {
        draw_text(canvas, width, height,
                  calendar::GRID_X + index as u32 * calendar::CELL_WIDTH + 12,
                  82, weekday, style.foreground);
    }
    let muted = {
        let foreground = style.foreground;
        let background = style.background;
        let channel = |shift| {
            (((foreground >> shift) & 0xff_u32) + 2_u32 * ((background >> shift) & 0xff_u32)) / 3_u32
        };
        0xff00_0000_u32 | (channel(16) << 16) | (channel(8) << 8) | channel(0)
    };
    for (index, (day, this_month)) in state.cells().into_iter().enumerate() {
        let x = calendar::GRID_X + (index % 7) as u32 * calendar::CELL_WIDTH;
        let y = calendar::GRID_Y + (index / 7) as u32 * calendar::CELL_HEIGHT;
        if day == state.today {
            fill_rounded_rect(canvas, width, height, x + 4, y + 2,
                              calendar::CELL_WIDTH - 8, calendar::CELL_HEIGHT - 4,
                              7, style.active);
        }
        if day == state.selected {
            fill_rect(canvas, width, height, x + 4, y + 1,
                      calendar::CELL_WIDTH - 8, 2, style.foreground);
            fill_rect(canvas, width, height, x + 4, y + calendar::CELL_HEIGHT - 3,
                      calendar::CELL_WIDTH - 8, 2, style.foreground);
        }
        let label = day.day().to_string();
        draw_text(canvas, width, height,
                  x + (calendar::CELL_WIDTH - label.len() as u32 * 8) / 2,
                  y + 13, &label, if this_month { style.foreground } else { muted });
    }
    fill_rounded_rect(canvas, width, height, 12, 322, 92, 28, 4, style.active);
    draw_text(canvas, width, height, 31, 332, "Today", style.foreground);
    draw_text(canvas, width, height, 183, 332, "Esc to close", style.foreground);
}

fn paint_icon(canvas: &mut [u8], icon: &recipe::DesktopIcon, active: u32,
              foreground: u32, focused: bool, custom: Option<&style_art::IconPixels>) {
    let width = recipe::ICON_WIDTH;
    let height = recipe::ICON_HEIGHT;
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
        _ => return,
    };
    if custom.is_some() {
        // Transparent 48px artwork sits in the existing, keyboard-reachable
        // 104x88 desktop icon surface. Wayland focus/label stay unchanged.
        style_art::paint_icon(canvas, width, custom.unwrap(), 28, 4);
    } else {
        fill_rounded_rect(canvas, width, height, 24, 4, 56, 48, 10, active);
    }
    // Contrast backplate prevents white labels from vanishing on bright rices.
    fill_rounded_rect(canvas, width, height, 2, 58, 100, 26, 6, 0xb020_2c36);
    if custom.is_none() {
        draw_text(canvas, width, height, 52 - (glyph.len() as u32 * 4),
                  24, glyph, foreground);
    }
    draw_text(
        canvas,
        width,
        height,
        (width - icon.label.len() as u32 * 8) / 2,
        66,
        &icon.label,
        foreground,
    );
}

fn paint_desktop_widget(canvas: &mut [u8], title: &str, lines: &[String], style: &PanelStyle) {
    let width = recipe::DESKTOP_WIDGET_WIDTH;
    let height = recipe::DESKTOP_WIDGET_HEIGHT;
    canvas.fill(0);
    fill_rounded_rect(canvas, width, height, 0, 0, width, height, 10, style.background);
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

fn fill_rect(
    canvas: &mut [u8],
    width: u32,
    height: u32,
    x: u32,
    y: u32,
    w: u32,
    h: u32,
    color: u32,
) {
    for row in y..y.saturating_add(h).min(height) {
        for column in x..x.saturating_add(w).min(width) {
            let index = ((row * width + column) * 4) as usize;
            canvas[index..index + 4].copy_from_slice(&color.to_le_bytes());
        }
    }
}

fn fill_rounded_rect(
    canvas: &mut [u8],
    width: u32,
    height: u32,
    x: u32,
    y: u32,
    w: u32,
    h: u32,
    radius: u32,
    color: u32,
) {
    let r = radius.min(w / 2).min(h / 2);
    if r == 0 {
        fill_rect(canvas, width, height, x, y, w, h, color);
        return;
    }
    let corner = (r as i64 - 1).pow(2);
    for py in 0..h.min(height.saturating_sub(y)) {
        for px in 0..w.min(width.saturating_sub(x)) {
            let dx = if px < r {
                r - 1 - px
            } else {
                px.saturating_sub(w - r)
            };
            let dy = if py < r {
                r - 1 - py
            } else {
                py.saturating_sub(h - r)
            };
            if (dx as i64).pow(2) + (dy as i64).pow(2) <= corner {
                let index = (((y + py) * width + x + px) * 4) as usize;
                canvas[index..index + 4].copy_from_slice(&color.to_le_bytes());
            }
        }
    }
}

fn draw_text(canvas: &mut [u8], width: u32, height: u32, x: u32, y: u32, text: &str, color: u32) {
    draw_bitmap_text(canvas, width, height, x, y, text, color, 1, false);
}

fn draw_rice_text(canvas: &mut [u8], width: u32, height: u32, x: u32, y: u32,
                  text: &str, color: u32, style: &PanelStyle) {
    if let Some(font) = style.native_art.as_ref().and_then(|art| art.font.as_ref()) {
        font.draw(canvas, width, height, x, y, text, color);
        return;
    }
    draw_bitmap_text(canvas, width, height, x, y, text, color,
                     style.font_scale, style.font_bold);
}

fn draw_bitmap_text(canvas: &mut [u8], width: u32, height: u32, x: u32, y: u32,
                    text: &str, color: u32, scale: u32, bold: bool) {
    for (offset, character) in text.chars().enumerate() {
        if character.is_control() { continue; }
        // The existing 8x8 renderer is intentionally allocation-free: support
        // the crate's non-ASCII tables and show a visible replacement glyph
        // instead of silently erasing unsupported scripts.
        let bitmap = BASIC_FONTS.get(character)
            .or_else(|| LATIN_FONTS.get(character))
            .or_else(|| GREEK_FONTS.get(character))
            .or_else(|| HIRAGANA_FONTS.get(character))
            .or_else(|| MISC_FONTS.get(character))
            .or_else(|| BASIC_FONTS.get('?'));
        let Some(bitmap) = bitmap else { continue; };
        let origin = x.saturating_add((offset as u32).saturating_mul(8 * scale));
        for (row, bits) in bitmap.iter().enumerate() {
            for column in 0..8_u32 {
                if *bits & (1_u8 << column) != 0 {
                    fill_rect(
                        canvas,
                        width,
                        height,
                        origin.saturating_add(column * scale),
                        y.saturating_add(row as u32 * scale),
                        scale + u32::from(bold && column < 7),
                        scale,
                        color,
                    );
                }
            }
        }
    }
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
                self.mirrors[index].frame_pending = false;
                if self.mirrors[index].needs_redraw { self.redraw_mirror(index, qh); }
            }
            return;
        }
        self.frame_pending = false;
        if self.needs_redraw {
            self.redraw(qh);
        }
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
        if self.focused_panel.as_ref() == Some(layer.wl_surface()) {
            self.focused_panel = None;
            self.focused_target = None;
        }
        if layer.wl_surface() == self.layer.wl_surface() {
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
            if config.new_size != (native_menu::WIDTH, native_menu::HEIGHT) {
                eprintln!("RicePlate: compositor proposed unsupported native menu geometry");
                if self.menu_layer.as_ref().is_some_and(|menu|
                    menu.surface.wl_surface() == layer.wl_surface()) {
                    self.menu_layer = None;
                } else {
                    self.menu_mirrors.retain(|menu|
                        menu.surface.wl_surface() != layer.wl_surface());
                }
                if self.active_menu.as_ref() == Some(layer.wl_surface()) {
                    self.set_menu_visible(false, qh);
                }
                return;
            }
            let menu_layer = self.menu_layer.as_mut().filter(|menu|
                menu.surface.wl_surface() == layer.wl_surface())
                .or_else(|| self.menu_mirrors.iter_mut().find(|menu|
                    menu.surface.wl_surface() == layer.wl_surface()))
                .expect("matched a live native menu layer");
            if menu_layer.pool.is_none() {
                let byte_count = (native_menu::WIDTH * native_menu::HEIGHT * 4 * 3) as usize;
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
                Ok(keyboard) => self.keyboard = Some(keyboard),
                Err(error) => eprintln!("RicePlate: keyboard unavailable: {error}"),
            }
        }
        if capability == Capability::Pointer && self.pointer.is_none() {
            match self.seats.get_pointer(qh, &seat) {
                Ok(pointer) => self.pointer = Some(pointer),
                Err(error) => eprintln!("RicePlate: pointer unavailable: {error}"),
            }
        }
    }
    fn remove_capability(
        &mut self,
        _: &Connection,
        qh: &QueueHandle<Self>,
        _: wl_seat::WlSeat,
        capability: Capability,
    ) {
        if capability == Capability::Pointer {
            if let Some(pointer) = self.pointer.take() {
                pointer.release();
            }
            self.icon_drag = None;
            self.save_icon_positions();
        } else if capability == Capability::Keyboard {
            if let Some(keyboard) = self.keyboard.take() {
                keyboard.release();
            }
            self.menu_focused = false;
            self.calendar_focused = false;
            self.keyboard_icon_surface = None;
            if let Some(index) = self.focused_icon.take() {
                self.redraw_icon(index);
                self.save_icon_positions();
            }
            self.focused_panel = None;
            self.focused_target = None;
            self.request_redraw(qh);
        }
    }
    fn remove_seat(&mut self, _: &Connection, _: &QueueHandle<Self>, seat: wl_seat::WlSeat) {
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
            let previous = self.focused_icon;
            self.focused_icon = next;
            if let Some(index) = previous { self.redraw_icon(index); }
            if let Some(index) = next { self.redraw_icon(index); }
            self.save_icon_positions();
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
        _: u32,
        event: KeyEvent,
    ) {
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
                        self.redraw_icon(index);
                        self.redraw_icon(next);
                    }
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
                Keysym::Escape => {
                    self.save_icon_positions();
                }
                _ => {}
            }
            return;
        }
        if !self.menu_state.visible || !self.menu_focused {
            return;
        }
        if self.notification_state.open {
            let detail = self.notification_state.detail_id.is_some();
            match event.keysym {
                Keysym::Escape | Keysym::BackSpace => {
                    if detail { self.notification_state.close_detail(); }
                    else { self.notification_state.close(); }
                }
                Keysym::Left if !detail => self.notification_state.select_tab(false),
                Keysym::Right if !detail => self.notification_state.select_tab(true),
                Keysym::Left if detail => self.notification_state.change_body_page(-1),
                Keysym::Right if detail => self.notification_state.change_body_page(1),
                Keysym::Up => {
                    if detail { self.notification_state.select_action(-1); }
                    else { self.notification_state.select(-1); }
                }
                Keysym::Down | Keysym::Tab => {
                    if detail { self.notification_state.select_action(1); }
                    else { self.notification_state.select(1); }
                }
                Keysym::Prior => {
                    if detail { self.notification_state.select_action(-(ricepop::VISIBLE_ROWS as isize)); }
                    else { self.notification_state.select(-(ricepop::VISIBLE_ROWS as isize)); }
                }
                Keysym::Next => {
                    if detail { self.notification_state.select_action(ricepop::VISIBLE_ROWS as isize); }
                    else { self.notification_state.select(ricepop::VISIBLE_ROWS as isize); }
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
                let previous = self.menu_state.pins.clone();
                if self.menu_state.toggle_pin(menu) {
                    let now_pinned = self.menu_state.pins.len() > previous.len();
                    if let Err(error) = menu_pins::save(&self.recipe.id, menu, &self.menu_state.pins) {
                        eprintln!("RicePlate: cannot save native menu pins: {error}");
                        self.menu_state.pins = previous;
                        self.menu_state.notice = Some("Cannot save pins");
                    } else {
                        self.menu_state.notice = Some(if now_pinned { "Action pinned" } else { "Pin removed" });
                    }
                } else {
                    self.menu_state.notice = Some("No action or saved list full");
                }
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
            Keysym::Left => {
                self.menu_state.horizontal_by(menu, -1);
                None
            }
            Keysym::Right => {
                self.menu_state.horizontal_by(menu, 1);
                None
            }
            Keysym::space if self.menu_state.view == native_menu::View::Search => {
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
            self.activate_action(&action, qh);
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
            | Keysym::Down | Keysym::Tab | Keysym::ISO_Left_Tab) {
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
        _: Modifiers,
        _: RawModifiers,
        _: u32,
    ) {
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
                if let PointerEventKind::Press {
                    button: BTN_LEFT, ..
                } = event.kind
                {
                    if self.notification_state.open {
                        match self.notification_state.hit(event.position.0, event.position.1) {
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
                                self.notification_state.change_body_page(delta);
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
                        match self
                            .menu_state
                            .hit(menu, event.position.0, event.position.1)
                        {
                            Some(MenuHit::Group(index)) => {
                                self.menu_state.open_group(index);
                                self.redraw_menu(qh);
                            }
                            Some(MenuHit::Action(index)) => {
                                self.menu_state.selected = index;
                                if let Some(action) = self.menu_state.current_action(menu).map(str::to_owned) {
                                    self.activate_action(&action, qh);
                                }
                            }
                            Some(MenuHit::Close) => self.set_menu_visible(false, qh),
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
                    PointerEventKind::Press { button: BTN_LEFT, .. } => {
                        if let Some(position) = self.icon_layers[index].placed {
                            self.icon_drag = Some(IconDrag {
                                index, anchor: event.position, started: position, moved: false,
                            });
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
                                let action = self.recipe.desktop_icons[
                                    self.icon_layers[index].recipe_index].action.clone();
                                self.activate_action(&action, qh);
                            } else if drag.index == index {
                                self.save_icon_positions();
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
            if let PointerEventKind::Press { button, .. } = event.kind {
                if (button == BTN_LEFT || button == BTN_RIGHT)
                    && event.position.1 >= 0.0
                    && event.position.1 < f64::from(panel_height)
                {
                    let groups = self.grouped_tasks();
                    match recipe::hit(
                        event.position.0,
                        panel_width,
                        groups.len(),
                        panel_offset,
                        &self.recipe,
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
                        _ if button == BTN_RIGHT => {},
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
                        ready: false,
                    });
                }
            }
            zwlr_foreign_toplevel_manager_v1::Event::Finished => {
                state.toplevel_manager = None;
                state.tasks.clear();
                state.task_offset = 0;
                state.request_redraw(qh);
            }
            _ => {}
        }
    }
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
                state.tasks.remove(index).handle.destroy();
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
                    task.active = states
                        .chunks_exact(4)
                        .any(|raw| u32::from_ne_bytes(raw.try_into().unwrap_or_default()) == 2)
                }
                zwlr_foreign_toplevel_handle_v1::Event::Done => {
                    task.ready = true;
                    refresh = true;
                }
                _ => {}
            }
            if refresh {
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
    fn desktop_icon_paint_preserves_transparent_background() {
        let icon = recipe::DesktopIcon {
            label: "Terminal".into(),
            action: "terminal".into(),
            x: 32,
            y: 112,
        };
        let mut pixels = vec![255; (recipe::ICON_WIDTH * recipe::ICON_HEIGHT * 4) as usize];
        paint_icon(&mut pixels, &icon, 0xff4179aa, 0xfff3f7fa, false, None);
        assert_eq!(&pixels[0..4], &[0, 0, 0, 0]);
        assert!(pixels
            .chunks_exact(4)
            .any(|pixel| pixel == 0xff4179aa_u32.to_le_bytes()));
        assert!(pixels
            .chunks_exact(4)
            .any(|pixel| pixel == 0xfff3f7fa_u32.to_le_bytes()));
        paint_icon(&mut pixels, &icon, 0xff4179aa, 0xfff3f7fa, true, None);
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
    fn label_pixels_come_from_font_glyphs() {
        let mut pixels = vec![0_u8; 20 * 12 * 4];
        draw_text(&mut pixels, 20, 12, 0, 0, "A", 0xfff3f7fa);
        assert!(pixels
            .chunks_exact(4)
            .any(|color| color == 0xfff3f7fa_u32.to_le_bytes()));
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
        assert!(!clock_now().is_empty());
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
