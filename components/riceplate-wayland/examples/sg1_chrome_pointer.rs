//! CI-only compositor-backed Chrome launcher pointer with explicit release.
//!
//! The parent smoke owns a private FIFO and sends "release" only after the
//! *actual* Fuzzel layer has received compositor keyboard focus. This makes
//! device teardown event-driven rather than a guessed number of milliseconds.
//! Never installed as a production RicePlate executable.

use std::{
    error::Error,
    io::{self, Write},
    time::Duration,
};

use wayland_client::{
    globals::{registry_queue_init, GlobalListContents},
    protocol::{wl_pointer, wl_registry, wl_seat},
    Connection, Dispatch, QueueHandle,
};
use wayland_protocols_wlr::virtual_pointer::v1::client::{
    zwlr_virtual_pointer_manager_v1::ZwlrVirtualPointerManagerV1,
    zwlr_virtual_pointer_v1::ZwlrVirtualPointerV1,
};

struct Probe;

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

wayland_client::delegate_noop!(Probe: ZwlrVirtualPointerManagerV1);
wayland_client::delegate_noop!(Probe: ZwlrVirtualPointerV1);

fn coordinates() -> Result<[u32; 4], Box<dyn Error>> {
    let values = std::env::args().skip(1)
        .map(|value| value.parse::<u32>())
        .collect::<Result<Vec<_>, _>>()?;
    let [x, y, width, height]: [u32; 4] = values.try_into()
        .map_err(|_| "Usage: sg1_chrome_pointer X Y OUTPUT_WIDTH OUTPUT_HEIGHT")?;
    if width == 0 || height == 0 || width > 16384 || height > 16384
        || x >= width || y >= height {
        return Err("Pointer coordinates are outside the bounded output".into());
    }
    Ok([x, y, width, height])
}

fn release_command() -> Result<(), Box<dyn Error>> {
    // Poll only the test's explicit FIFO. Never wait indefinitely if the
    // compositor, parent shell, or Fuzzel process has failed.
    let mut input = libc::pollfd {
        fd: 0,
        events: libc::POLLIN,
        revents: 0,
    };
    let polled = unsafe { libc::poll(&mut input, 1, 15_000) };
    if polled != 1 || (input.revents & libc::POLLIN) == 0 {
        return Err("Chrome pointer release handshake timed out or disconnected".into());
    }
    let mut command = String::new();
    io::stdin().read_line(&mut command)?;
    if command != "release\n" {
        return Err("Chrome pointer refused unrecognized release command".into());
    }
    Ok(())
}

fn main() -> Result<(), Box<dyn Error>> {
    let [x, y, width, height] = coordinates()?;
    let connection = Connection::connect_to_env()?;
    let (globals, mut queue) = registry_queue_init(&connection)?;
    let qh = queue.handle();
    let manager: ZwlrVirtualPointerManagerV1 = globals.bind(&qh, 1..=2, ())?;
    let seat: wl_seat::WlSeat = globals.bind(&qh, 1..=9, ())?;
    let pointer = manager.create_virtual_pointer(Some(&seat), &qh, ());
    queue.roundtrip(&mut Probe)?;

    pointer.motion_absolute(1, x, y, width, height);
    pointer.frame();
    connection.flush()?;
    std::thread::sleep(Duration::from_millis(70));
    pointer.button(2, 0x110, wl_pointer::ButtonState::Pressed);
    pointer.frame();
    connection.flush()?;
    std::thread::sleep(Duration::from_millis(70));
    pointer.button(25, 0x110, wl_pointer::ButtonState::Released);
    pointer.frame();
    queue.roundtrip(&mut Probe)?;
    println!("Chrome real pointer click delivered at {x},{y}; awaiting focus receipt");
    io::stdout().flush()?;

    // A valid release explicitly destroys the virtual pointer instead of
    // terminating the client with SIGTERM and dropping compositor seat state.
    release_command()?;
    pointer.destroy();
    manager.destroy();
    connection.flush()?;
    println!("Chrome real pointer disconnected after Fuzzel focus receipt");
    Ok(())
}
