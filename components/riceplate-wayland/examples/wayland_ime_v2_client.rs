//! CI-only genuine input-method-v2 producer for RicePlate text-input-v3.
//! A separate client, communicating *only through labwc*, confirms that
//! compositor-mediated preedit, commit and UTF-8 byte deletion reach Run.
//! No test-only backdoors in RicePlate or input-method background services.

use std::{error::Error, time::{Duration, Instant}};

use wayland_client::{
    globals::{registry_queue_init, GlobalListContents},
    protocol::{wl_registry, wl_seat},
    Connection, Dispatch, QueueHandle,
};
use wayland_protocols_misc::zwp_input_method_v2::client::{
    zwp_input_method_manager_v2::ZwpInputMethodManagerV2,
    zwp_input_method_v2::{self, ZwpInputMethodV2},
};

#[derive(Default)]
struct Probe {
    active: bool,
    serial: u32,
    surrounding: String,
    unavailable: bool,
}

impl Dispatch<wl_registry::WlRegistry, GlobalListContents> for Probe {
    fn event(
        _: &mut Self, _: &wl_registry::WlRegistry, _: wl_registry::Event,
        _: &GlobalListContents, _: &Connection, _: &QueueHandle<Self>,
    ) {}
}

impl Dispatch<wl_seat::WlSeat, ()> for Probe {
    fn event(
        _: &mut Self, _: &wl_seat::WlSeat, _: wl_seat::Event,
        _: &(), _: &Connection, _: &QueueHandle<Self>,
    ) {}
}

wayland_client::delegate_noop!(Probe: ZwpInputMethodManagerV2);

impl Dispatch<ZwpInputMethodV2, ()> for Probe {
    fn event(
        state: &mut Self, _: &ZwpInputMethodV2,
        event: zwp_input_method_v2::Event, _: &(),
        _: &Connection, _: &QueueHandle<Self>,
    ) {
        match event {
            zwp_input_method_v2::Event::Activate => {
                state.active = true;
                state.surrounding.clear();
            }
            zwp_input_method_v2::Event::Deactivate => {
                state.active = false;
            }
            zwp_input_method_v2::Event::SurroundingText { text, .. } => {
                state.surrounding = text;
            }
            zwp_input_method_v2::Event::Done => {
                state.serial = state.serial.wrapping_add(1);
            }
            zwp_input_method_v2::Event::Unavailable => {
                state.unavailable = true;
            }
            _ => {}
        }
    }
}

#[derive(Clone, Copy)]
enum Phase {
    Waiting,
    Preediting { serial: u32, since: Instant },
    Committed { serial: u32 },
    Replaced { serial: u32 },
}

fn main() -> Result<(), Box<dyn Error>> {
    let conn = Connection::connect_to_env()?;
    let (globals, mut queue) = registry_queue_init(&conn)?;
    let qh = queue.handle();
    // A missing protocol is a real feature failure, never a skipped smoke.
    let manager: ZwpInputMethodManagerV2 = globals.bind(&qh, 1..=1, ())?;
    let seat: wl_seat::WlSeat = globals.bind(&qh, 1..=9, ())?;
    let input = manager.get_input_method(&seat, &qh, ());
    let mut probe = Probe::default();
    let mut phase = Phase::Waiting;
    let deadline = Instant::now() + Duration::from_secs(12);

    while Instant::now() < deadline {
        queue.roundtrip(&mut probe)?;
        if probe.unavailable { return Err("labwc rejected external input method".into()); }
        if !probe.active {
            if !matches!(phase, Phase::Waiting) {
                return Err("input method lost focus before committed text was confirmed".into());
            }
        } else {
            phase = match phase {
                Phase::Waiting if probe.serial > 0 => {
                    // Real IME-visible, uncommitted Japanese candidate. The
                    // full UTF-8 cursor is supplied in bytes, not scalars.
                    let preedit = "にほんご";
                    input.set_preedit_string(preedit.to_owned(), preedit.len() as i32,
                                              preedit.len() as i32);
                    input.commit(probe.serial);
                    conn.flush()?;
                    Phase::Preediting { serial: probe.serial, since: Instant::now() }
                }
                Phase::Preediting { serial, since }
                    if probe.serial > serial
                        && since.elapsed() >= Duration::from_millis(250) =>
                {
                    // A second compositor-confirmed transaction ends preedit
                    // and commits native CJK Unicode; keyboard events alone
                    // cannot produce this proof.
                    input.set_preedit_string(String::new(), 0, 0);
                    input.commit_string("日本語".to_owned());
                    input.commit(probe.serial);
                    conn.flush()?;
                    Phase::Committed { serial: probe.serial }
                }
                Phase::Committed { serial }
                    if probe.serial > serial && probe.surrounding == "日本語" =>
                {
                    // Delete one complete 3-byte CJK grapheme before caret,
                    // replace with another, then require real surrounding
                    // text to be returned through the compositor.
                    input.delete_surrounding_text("語".len() as u32, 0);
                    input.commit_string("界".to_owned());
                    input.commit(probe.serial);
                    conn.flush()?;
                    Phase::Replaced { serial: probe.serial }
                }
                Phase::Replaced { serial }
                    if probe.serial > serial && probe.surrounding == "日本界" =>
                {
                    println!("PASS: real IME v2 -> labwc -> text-input-v3 preedit/commit/delete");
                    input.destroy();
                    manager.destroy();
                    conn.flush()?;
                    return Ok(());
                }
                current => current,
            };
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    Err("No complete external IME preedit/commit/delete and UTF-8 roundtrip".into())
}
