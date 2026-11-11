//! CI-only virtual pointer input against a *disposable* headless Wayland compositor.
//! Not installed with RicePlate and never called by the desktop session.

use std::{error::Error, time::Duration};

use wayland_client::{
    globals::{registry_queue_init, GlobalListContents},
    protocol::{wl_pointer, wl_registry},
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
    ) {}
}

wayland_client::delegate_noop!(Probe: ZwlrVirtualPointerManagerV1);
wayland_client::delegate_noop!(Probe: ZwlrVirtualPointerV1);

fn main() -> Result<(), Box<dyn Error>> {
    let values = std::env::args().skip(1).collect::<Vec<_>>();
    let move_only = values.first().map(String::as_str) == Some("--move-only");
    let scroll = match values.first().map(String::as_str) {
        Some("--scroll-down") => 1.0,
        Some("--scroll-up") => -1.0,
        _ => 0.0,
    };
    let args = if move_only || scroll != 0.0 { &values[1..] } else { &values[..] };
    if args.len() != 4 {
        return Err("Usage: wayland_pointer_click [--move-only|--scroll-down|--scroll-up] X Y OUTPUT_WIDTH OUTPUT_HEIGHT".into());
    }
    let coordinates = args.iter().map(|arg| arg.parse::<u32>())
        .collect::<Result<Vec<_>, _>>()?;
    let [x, y, width, height] = [coordinates[0], coordinates[1], coordinates[2], coordinates[3]];
    if width < 1 || height < 1 || x >= width || y >= height || width > 16384 || height > 16384 {
        return Err("Pointer coordinates must be inside a bounded Wayland output".into());
    }

    let conn = Connection::connect_to_env()?;
    let (globals, mut queue) = registry_queue_init(&conn)?;
    let qh = queue.handle();
    let manager: ZwlrVirtualPointerManagerV1 = globals.bind(&qh, 1..=2, ())?;
    let pointer = manager.create_virtual_pointer(None, &qh, ());
    queue.roundtrip(&mut Probe)?;

    // Let labwc update pointer focus before sending a real press/release pair.
    pointer.motion_absolute(1, x, y, width, height);
    pointer.frame();
    conn.flush()?;
    std::thread::sleep(Duration::from_millis(70));
    if scroll != 0.0 {
        // An actual wl_pointer axis event delivered by labwc to RicePlate.
        // Keep its position identical to the prior hover-only control frame.
        pointer.axis(2, wl_pointer::Axis::VerticalScroll, scroll * 48.0);
        pointer.frame();
    } else if !move_only {
        pointer.button(2, 0x110, wl_pointer::ButtonState::Pressed);
        pointer.frame();
        conn.flush()?;
        std::thread::sleep(Duration::from_millis(70));
        pointer.button(3, 0x110, wl_pointer::ButtonState::Released);
        pointer.frame();
    }
    queue.roundtrip(&mut Probe)?;
    pointer.destroy();
    manager.destroy();
    conn.flush()?;
    println!("Delivered native Wayland {} at {x},{y}",
        if move_only { "pointer motion" }
        else if scroll != 0.0 { "pointer axis" }
        else { "pointer click" });
    Ok(())
}
