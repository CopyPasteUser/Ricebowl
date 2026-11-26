//! CI-only genuine input-method-v2 producer for RicePlate text-input-v3.
//! A separate client, communicating *only through labwc*, confirms that
//! compositor-mediated preedit, commit and UTF-8 byte deletion reach a native editor.
//! No test-only backdoors in RicePlate or input-method background services.
//!
//! Usage: `wayland_ime_v2_client [preedit-observed-file] [--base TEXT]
//! [--focus-cycle DIR]`. `--base` is the text already in the editor (Rename
//! file name); the focus cycle appends a second, uncommitted preedit, waits
//! for the compositor to take and later return text-input focus, and then
//! requires the preedit to have been dropped (never committed) and the
//! surrounding text to be intact. Progress is reported to the driving
//! script through marker files in DIR; the script gates each step.

use std::{
    error::Error,
    path::PathBuf,
    time::{Duration, Instant},
};

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
    surrounding: Option<String>,
    unavailable: bool,
    activations: u32,
    deactivations: u32,
    /// A `done` has been received since the latest activate.
    fresh: bool,
}

impl Dispatch<wl_registry::WlRegistry, GlobalListContents> for Probe {
    fn event(
        _: &mut Self,
        _: &wl_registry::WlRegistry,
        _: wl_registry::Event,
        _: &GlobalListContents,
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
    }
}

impl Dispatch<wl_seat::WlSeat, ()> for Probe {
    fn event(
        _: &mut Self,
        _: &wl_seat::WlSeat,
        _: wl_seat::Event,
        _: &(),
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
    }
}

wayland_client::delegate_noop!(Probe: ZwpInputMethodManagerV2);

impl Dispatch<ZwpInputMethodV2, ()> for Probe {
    fn event(
        state: &mut Self,
        _: &ZwpInputMethodV2,
        event: zwp_input_method_v2::Event,
        _: &(),
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        // Failure diagnostics only: event kinds and sizes, never editor text.
        eprintln!("ime-v2 event: {}", event_kind(&event));
        match event {
            zwp_input_method_v2::Event::Activate => {
                state.active = true;
                state.activations += 1;
                state.fresh = false;
                state.surrounding = None;
            }
            zwp_input_method_v2::Event::Deactivate => {
                state.active = false;
                state.deactivations += 1;
            }
            zwp_input_method_v2::Event::SurroundingText { text, .. } => {
                state.surrounding = Some(text);
            }
            zwp_input_method_v2::Event::Done => {
                state.serial = state.serial.wrapping_add(1);
                state.fresh = true;
            }
            zwp_input_method_v2::Event::Unavailable => {
                state.unavailable = true;
            }
            _ => {}
        }
    }
}

fn event_kind(event: &zwp_input_method_v2::Event) -> String {
    match event {
        zwp_input_method_v2::Event::Activate => "activate".into(),
        zwp_input_method_v2::Event::Deactivate => "deactivate".into(),
        zwp_input_method_v2::Event::SurroundingText { text, .. } => {
            format!("surrounding bytes={}", text.len())
        }
        zwp_input_method_v2::Event::Done => "done".into(),
        zwp_input_method_v2::Event::Unavailable => "unavailable".into(),
        _ => "other".into(),
    }
}

#[derive(Clone, Copy)]
enum Phase {
    Waiting,
    Preediting { serial: u32, since: Instant },
    Committed { serial: u32 },
    Replaced { serial: u32 },
    CyclePreediting { serial: u32 },
    AwaitLeave { deactivations: u32 },
    AwaitReenter { activations: u32 },
    AwaitVerified,
    CycleCommitted { serial: u32 },
}

struct Options {
    preedit_observed: Option<PathBuf>,
    base: String,
    cycle_dir: Option<PathBuf>,
}

fn parse_options() -> Result<Options, Box<dyn Error>> {
    let mut options = Options {
        preedit_observed: None,
        base: String::new(),
        cycle_dir: None,
    };
    let mut args = std::env::args_os().skip(1);
    while let Some(arg) = args.next() {
        match arg.to_str() {
            Some("--base") => {
                options.base = args
                    .next()
                    .and_then(|value| value.into_string().ok())
                    .ok_or("--base needs UTF-8 text")?;
            }
            Some("--focus-cycle") => {
                options.cycle_dir =
                    Some(PathBuf::from(args.next().ok_or("--focus-cycle needs DIR")?));
            }
            _ if options.preedit_observed.is_none() => {
                options.preedit_observed = Some(PathBuf::from(arg))
            }
            _ => return Err("unexpected argument".into()),
        }
    }
    Ok(options)
}

fn marker(dir: &Option<PathBuf>, name: &str) -> Result<(), Box<dyn Error>> {
    if let Some(dir) = dir {
        std::fs::write(dir.join(name), b"")?;
    }
    Ok(())
}

fn main() -> Result<(), Box<dyn Error>> {
    let Options {
        preedit_observed,
        base,
        cycle_dir,
    } = parse_options()?;
    let base = base.as_str();
    let conn = Connection::connect_to_env()?;
    let (globals, mut queue) = registry_queue_init(&conn)?;
    let qh = queue.handle();
    // A missing protocol is a real feature failure, never a skipped smoke.
    let manager: ZwpInputMethodManagerV2 = globals.bind(&qh, 1..=1, ())?;
    let seat: wl_seat::WlSeat = globals.bind(&qh, 1..=9, ())?;
    let input = manager.get_input_method(&seat, &qh, ());
    let mut probe = Probe::default();
    let mut phase = Phase::Waiting;
    let deadline = Instant::now() + Duration::from_secs(if cycle_dir.is_some() { 40 } else { 12 });

    while Instant::now() < deadline {
        queue.roundtrip(&mut probe)?;
        if probe.unavailable {
            return Err("labwc rejected external input method".into());
        }
        if matches!(phase, Phase::AwaitLeave { .. } | Phase::AwaitReenter { .. }) {
            // The compositor, not this client, moves text-input focus. A
            // real leave must deactivate this input method; a real return
            // must activate it with fresh surrounding text (preedit state is
            // never replayed, and no request is sent while inactive).
            if let Phase::AwaitLeave { deactivations } = phase {
                if probe.deactivations > deactivations {
                    marker(&cycle_dir, "left")?;
                    phase = Phase::AwaitReenter {
                        activations: probe.activations,
                    };
                }
            }
            if matches!(phase, Phase::AwaitReenter { activations } if probe.activations > activations)
                && probe.active
                && probe.fresh
                && probe.surrounding.is_some()
            {
                if probe.surrounding.as_deref() != Some(&format!("{base}日本界")) {
                    return Err("preedit or stale text reached the editor across focus loss".into());
                }
                marker(&cycle_dir, "reentered")?;
                phase = Phase::AwaitVerified;
            }
            std::thread::sleep(Duration::from_millis(20));
            continue;
        }
        if !probe.active {
            if !matches!(phase, Phase::Waiting) {
                return Err("input method lost focus before committed text was confirmed".into());
            }
        } else {
            phase = match phase {
                Phase::Waiting if probe.serial > 0 && probe.surrounding.is_some() => {
                    // Real IME-visible, uncommitted Japanese candidate. The
                    // full UTF-8 cursor is supplied in bytes, not scalars.
                    let preedit = "にほんご";
                    input.set_preedit_string(
                        preedit.to_owned(),
                        preedit.len() as i32,
                        preedit.len() as i32,
                    );
                    input.commit(probe.serial);
                    conn.flush()?;
                    eprintln!("ime-v2 request sent at serial {}", probe.serial);
                    Phase::Preediting {
                        serial: probe.serial,
                        since: Instant::now(),
                    }
                }
                Phase::Preediting { serial, since }
                    if probe.serial > serial
                        && since.elapsed() >= Duration::from_millis(250)
                        && preedit_observed.as_ref().is_none_or(|file| file.is_file()) =>
                {
                    // A second compositor-confirmed transaction ends preedit
                    // and commits native CJK Unicode; keyboard events alone
                    // cannot produce this proof.
                    input.set_preedit_string(String::new(), 0, 0);
                    input.commit_string("日本語".to_owned());
                    input.commit(probe.serial);
                    conn.flush()?;
                    eprintln!("ime-v2 request sent at serial {}", probe.serial);
                    Phase::Committed {
                        serial: probe.serial,
                    }
                }
                Phase::Committed { serial }
                    if probe.serial > serial
                        && probe.surrounding.as_deref() == Some(&format!("{base}日本語")) =>
                {
                    // Delete one complete 3-byte CJK grapheme before caret,
                    // replace with another, then require real surrounding
                    // text to be returned through the compositor.
                    input.delete_surrounding_text("語".len() as u32, 0);
                    input.commit_string("界".to_owned());
                    input.commit(probe.serial);
                    conn.flush()?;
                    eprintln!("ime-v2 request sent at serial {}", probe.serial);
                    Phase::Replaced {
                        serial: probe.serial,
                    }
                }
                Phase::Replaced { serial }
                    if probe.serial > serial
                        && probe.surrounding.as_deref() == Some(&format!("{base}日本界")) =>
                {
                    println!("PASS: real IME v2 -> labwc -> text-input-v3 preedit/commit/delete");
                    if cycle_dir.is_none() {
                        input.destroy();
                        manager.destroy();
                        conn.flush()?;
                        return Ok(());
                    }
                    // Leave a second candidate uncommitted so a focus loss
                    // has something that must never be committed anywhere.
                    let pending = "かんじ";
                    input.set_preedit_string(
                        pending.to_owned(),
                        pending.len() as i32,
                        pending.len() as i32,
                    );
                    input.commit(probe.serial);
                    conn.flush()?;
                    eprintln!("ime-v2 request sent at serial {}", probe.serial);
                    Phase::CyclePreediting {
                        serial: probe.serial,
                    }
                }
                Phase::CyclePreediting { serial } if probe.serial > serial => {
                    marker(&cycle_dir, "preedit-active")?;
                    Phase::AwaitLeave {
                        deactivations: probe.deactivations,
                    }
                }
                Phase::AwaitVerified
                    if cycle_dir
                        .as_ref()
                        .is_some_and(|dir| dir.join("verified").is_file()) =>
                {
                    // The driving script has independently verified the
                    // editor over AT-SPI; prove input still reaches it.
                    input.commit_string("文".to_owned());
                    input.commit(probe.serial);
                    conn.flush()?;
                    eprintln!("ime-v2 request sent at serial {}", probe.serial);
                    Phase::CycleCommitted {
                        serial: probe.serial,
                    }
                }
                Phase::CycleCommitted { serial }
                    if probe.serial > serial
                        && probe.surrounding.as_deref() == Some(&format!("{base}日本界文")) =>
                {
                    println!(
                        "PASS: real IME v2 focus leave/re-enter dropped preedit, kept text, re-committed"
                    );
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
