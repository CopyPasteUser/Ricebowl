//! Opt-in compositor focus experiment, not part of the RicePlate session.
//! Run only in an isolated headless labwc with the companion smoke script.
//! A bounded 256x128 wl_shm surface paints BLUE initially, AMBER on a real
//! pointer press and GREEN on compositor wl_keyboard.enter. It never records
//! keysyms, keyboard text, or any user input contents.
//!
//! Build: cargo build --manifest-path components/riceplate-wayland/Cargo.toml
//! Run:   riceplate_focus_probe bottom|top|overlay
//! The Bottom/OnDemand comparison is intentionally not treated as acceptance
//! that the real RicePlate desktop acquired focus.

use std::io::{self, Write};

use smithay_client_toolkit::{
    compositor::{CompositorHandler, CompositorState},
    delegate_registry,
    output::{OutputHandler, OutputState},
    registry::{ProvidesRegistryState, RegistryState},
    registry_handlers,
    seat::{
        keyboard::{KeyEvent, KeyboardHandler, Keysym, Modifiers, RawModifiers},
        pointer::{PointerEvent, PointerEventKind, PointerHandler, BTN_LEFT},
        Capability, SeatHandler, SeatState,
    },
    shell::{
        wlr_layer::{
            Anchor, KeyboardInteractivity, Layer, LayerShell, LayerShellHandler,
            LayerSurface, LayerSurfaceConfigure,
        },
        WaylandSurface,
    },
    shm::{slot::SlotPool, Shm, ShmHandler},
};
use wayland_client::{
    globals::registry_queue_init,
    protocol::{wl_keyboard, wl_output, wl_pointer, wl_seat, wl_shm, wl_surface},
    Connection, QueueHandle,
};

const WIDTH: i32 = 256;
const HEIGHT: i32 = 128;
const STRIDE: i32 = WIDTH * 4;
const POOL_BYTES: usize = (STRIDE * HEIGHT * 16) as usize;

fn log(message: &str) {
    println!("FOCUS_PROBE {message}");
    let _ = io::stdout().flush();
}

fn main() {
    let mode = std::env::args().nth(1).unwrap_or_default();
    let layer_kind = match mode.as_str() {
        "bottom" => Layer::Bottom,
        "top" => Layer::Top,
        "overlay" => Layer::Overlay,
        _ => {
            eprintln!("Usage: riceplate_focus_probe bottom|top|overlay");
            std::process::exit(2);
        }
    };
    let conn = Connection::connect_to_env().expect("private Wayland session required");
    let (globals, mut queue) = registry_queue_init(&conn).expect("Wayland registry");
    let qh = queue.handle();
    let compositor = CompositorState::bind(&globals, &qh).expect("wl_compositor");
    let shell = LayerShell::bind(&globals, &qh).expect("wlr-layer-shell");
    let shm = Shm::bind(&globals, &qh).expect("wl_shm");
    let layer = shell.create_layer_surface(
        &qh, compositor.create_surface(&qh), layer_kind, Some("riceplate-focus-probe"), None,
    );
    layer.set_anchor(Anchor::TOP | Anchor::LEFT);
    layer.set_size(WIDTH as u32, HEIGHT as u32);
    layer.set_margin(220, 0, 0, 220);
    layer.set_exclusive_zone(-1);
    layer.set_keyboard_interactivity(KeyboardInteractivity::OnDemand);
    layer.commit();

    let pool = SlotPool::new(POOL_BYTES, &shm).expect("private wl_shm pool");
    let mut state = Probe {
        registry: RegistryState::new(&globals),
        seats: SeatState::new(&globals, &qh),
        outputs: OutputState::new(&globals, &qh),
        shm,
        pool,
        layer,
        owner: None,
        keyboard: None,
        pointer: None,
        configured: false,
        focused: false,
        clicked: false,
        presses: 0,
        exit: false,
    };
    log(&format!("event=started layer={mode} interactivity=ondemand"));
    while !state.exit {
        queue.blocking_dispatch(&mut state).expect("Wayland event dispatch");
    }
    log("event=stopped");
}

struct Probe {
    registry: RegistryState,
    seats: SeatState,
    outputs: OutputState,
    shm: Shm,
    pool: SlotPool,
    layer: LayerSurface,
    owner: Option<wl_seat::WlSeat>,
    keyboard: Option<wl_keyboard::WlKeyboard>,
    pointer: Option<wl_pointer::WlPointer>,
    configured: bool,
    focused: bool,
    clicked: bool,
    presses: u32,
    exit: bool,
}

impl Probe {
    fn paint(&mut self) {
        if !self.configured { return; }
        let (buffer, canvas) = self.pool.create_buffer(
            WIDTH, HEIGHT, STRIDE, wl_shm::Format::Argb8888,
        ).expect("focus probe buffer");
        // Little-endian ARGB8888: visible, nontransparent colors.
        let base = if self.focused { 0xff22_aa55_u32 }
                   else if self.clicked { 0xffee_a122_u32 }
                   else { 0xff33_6699_u32 };
        for (i, pixel) in canvas.chunks_exact_mut(4).enumerate() {
            let x = (i % WIDTH as usize) as i32;
            let y = (i / WIDTH as usize) as i32;
            let color = if x < 3 || y < 3 || x >= WIDTH - 3 || y >= HEIGHT - 3 {
                0xffee_eeee_u32
            } else { base };
            pixel.copy_from_slice(&color.to_le_bytes());
        }
        self.layer.wl_surface().damage_buffer(0, 0, WIDTH, HEIGHT);
        buffer.attach_to(self.layer.wl_surface()).expect("attach probe buffer");
        self.layer.commit();
    }
}

impl CompositorHandler for Probe {
    fn scale_factor_changed(
        &mut self, _: &Connection, _: &QueueHandle<Self>,
        _: &wl_surface::WlSurface, _: i32,
    ) {}
    fn transform_changed(
        &mut self, _: &Connection, _: &QueueHandle<Self>,
        _: &wl_surface::WlSurface, _: wl_output::Transform,
    ) {}
    fn frame(
        &mut self, _: &Connection, _: &QueueHandle<Self>,
        _: &wl_surface::WlSurface, _: u32,
    ) {}
    fn surface_enter(
        &mut self, _: &Connection, _: &QueueHandle<Self>,
        surface: &wl_surface::WlSurface, _: &wl_output::WlOutput,
    ) {
        if self.layer.wl_surface() == surface { log("event=output_enter"); }
    }
    fn surface_leave(
        &mut self, _: &Connection, _: &QueueHandle<Self>,
        surface: &wl_surface::WlSurface, _: &wl_output::WlOutput,
    ) {
        if self.layer.wl_surface() == surface { log("event=output_leave"); }
    }
}

impl OutputHandler for Probe {
    fn output_state(&mut self) -> &mut OutputState { &mut self.outputs }
    fn new_output(&mut self, _: &Connection, _: &QueueHandle<Self>, _: wl_output::WlOutput) {}
    fn update_output(&mut self, _: &Connection, _: &QueueHandle<Self>, _: wl_output::WlOutput) {}
    fn output_destroyed(
        &mut self, _: &Connection, _: &QueueHandle<Self>, _: wl_output::WlOutput,
    ) { log("event=output_removed"); }
}

impl LayerShellHandler for Probe {
    fn closed(&mut self, _: &Connection, _: &QueueHandle<Self>, _: &LayerSurface) {
        log("event=surface_closed");
        self.focused = false;
        self.exit = true;
    }
    fn configure(
        &mut self, _: &Connection, _: &QueueHandle<Self>,
        _: &LayerSurface, _: LayerSurfaceConfigure, _: u32,
    ) {
        if !self.configured {
            self.configured = true;
            self.paint();
            log("event=mapped");
        }
    }
}

impl SeatHandler for Probe {
    fn seat_state(&mut self) -> &mut SeatState { &mut self.seats }
    fn new_seat(&mut self, _: &Connection, _: &QueueHandle<Self>, seat: wl_seat::WlSeat) {
        if self.owner.is_none() { self.owner = Some(seat); }
        log("event=seat_announced");
    }
    fn new_capability(
        &mut self, _: &Connection, qh: &QueueHandle<Self>,
        seat: wl_seat::WlSeat, capability: Capability,
    ) {
        if self.owner.as_ref() != Some(&seat) { return; }
        if capability == Capability::Keyboard && self.keyboard.is_none() {
            if let Ok(keyboard) = self.seats.get_keyboard(qh, &seat, None) {
                self.keyboard = Some(keyboard);
                log("event=keyboard_capability");
            }
        }
        if capability == Capability::Pointer && self.pointer.is_none() {
            if let Ok(pointer) = self.seats.get_pointer(qh, &seat) {
                self.pointer = Some(pointer);
                log("event=pointer_capability");
            }
        }
    }
    fn remove_capability(
        &mut self, _: &Connection, _: &QueueHandle<Self>,
        seat: wl_seat::WlSeat, capability: Capability,
    ) {
        if self.owner.as_ref() != Some(&seat) { return; }
        if capability == Capability::Keyboard {
            if let Some(keyboard) = self.keyboard.take() { keyboard.release(); }
            self.focused = false;
            self.paint();
            log("event=keyboard_removed");
        }
        if capability == Capability::Pointer {
            if let Some(pointer) = self.pointer.take() { pointer.release(); }
            log("event=pointer_removed");
        }
    }
    fn remove_seat(&mut self, _: &Connection, _: &QueueHandle<Self>, seat: wl_seat::WlSeat) {
        if self.owner.as_ref() == Some(&seat) {
            if let Some(keyboard) = self.keyboard.take() { keyboard.release(); }
            if let Some(pointer) = self.pointer.take() { pointer.release(); }
            self.owner = None;
            self.focused = false;
            self.paint();
            log("event=seat_removed");
        }
    }
}

impl KeyboardHandler for Probe {
    fn enter(
        &mut self, _: &Connection, _: &QueueHandle<Self>,
        keyboard: &wl_keyboard::WlKeyboard, surface: &wl_surface::WlSurface,
        _: u32, _: &[u32], _: &[Keysym],
    ) {
        if self.keyboard.as_ref() == Some(keyboard) && self.layer.wl_surface() == surface {
            self.focused = true;
            self.paint();
            log("event=keyboard_enter");
        }
    }
    fn leave(
        &mut self, _: &Connection, _: &QueueHandle<Self>,
        keyboard: &wl_keyboard::WlKeyboard, surface: &wl_surface::WlSurface, _: u32,
    ) {
        if self.keyboard.as_ref() == Some(keyboard) && self.layer.wl_surface() == surface {
            self.focused = false;
            self.paint();
            log("event=keyboard_leave");
        }
    }
    fn press_key(
        &mut self, _: &Connection, _: &QueueHandle<Self>,
        keyboard: &wl_keyboard::WlKeyboard, _: u32, _: KeyEvent,
    ) {
        if self.keyboard.as_ref() == Some(keyboard) && self.focused {
            self.presses = self.presses.saturating_add(1);
            log(&format!("event=keyboard_press count={}", self.presses));
        }
    }
    fn repeat_key(
        &mut self, _: &Connection, _: &QueueHandle<Self>,
        _: &wl_keyboard::WlKeyboard, _: u32, _: KeyEvent,
    ) {}
    fn release_key(
        &mut self, _: &Connection, _: &QueueHandle<Self>,
        _: &wl_keyboard::WlKeyboard, _: u32, _: KeyEvent,
    ) {}
    fn update_modifiers(
        &mut self, _: &Connection, _: &QueueHandle<Self>,
        _: &wl_keyboard::WlKeyboard, _: u32, _: Modifiers, _: RawModifiers, _: u32,
    ) {}
}

impl PointerHandler for Probe {
    fn pointer_frame(
        &mut self, _: &Connection, _: &QueueHandle<Self>,
        pointer: &wl_pointer::WlPointer, events: &[PointerEvent],
    ) {
        if self.pointer.as_ref() != Some(pointer) { return; }
        for event in events {
            if &event.surface != self.layer.wl_surface() { continue; }
            match event.kind {
                PointerEventKind::Enter { .. } => log("event=pointer_enter"),
                PointerEventKind::Press { button, .. } if button == BTN_LEFT => {
                    self.clicked = true;
                    self.paint();
                    log("event=pointer_press");
                }
                PointerEventKind::Leave { .. } => log("event=pointer_leave"),
                _ => {}
            }
        }
    }
}

impl ShmHandler for Probe {
    fn shm_state(&mut self) -> &mut Shm { &mut self.shm }
}

delegate_registry!(Probe);
impl ProvidesRegistryState for Probe {
    fn registry(&mut self) -> &mut RegistryState { &mut self.registry }
    registry_handlers![OutputState, SeatState];
}
smithay_client_toolkit::delegate_dispatch2!(Probe);
