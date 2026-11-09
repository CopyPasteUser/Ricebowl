//! Optional, event-driven wl_output change stream for the Waybar rescue panel.
//! This mode creates no layer surfaces, polls no display commands and never
//! changes outputs. A dead compositor closes stdout and exits the watcher.

use std::{error::Error, io::{self, Write}};

use smithay_client_toolkit::{
    delegate_registry,
    output::{OutputHandler, OutputState},
    registry::{ProvidesRegistryState, RegistryState},
    registry_handlers,
};
use wayland_client::{
    globals::registry_queue_init,
    protocol::wl_output,
    Connection, QueueHandle,
};

struct Watcher {
    registry: RegistryState,
    outputs: OutputState,
    ready: bool,
}

impl Watcher {
    fn changed(&self) {
        if self.ready {
            // A line means "reinspect outputs", not a command or dimensions.
            // The owner-private supervisor debounces bursts and verifies its
            // fresh wlr-randr inventory before replacing its own Waybar.
            let _ = io::stdout().write_all(b"changed\n");
            let _ = io::stdout().flush();
        }
    }
}

impl OutputHandler for Watcher {
    fn output_state(&mut self) -> &mut OutputState { &mut self.outputs }

    fn new_output(&mut self, _: &Connection, _: &QueueHandle<Self>, _: wl_output::WlOutput) {
        self.changed();
    }

    fn update_output(&mut self, _: &Connection, _: &QueueHandle<Self>, _: wl_output::WlOutput) {
        self.changed();
    }

    fn output_destroyed(&mut self, _: &Connection, _: &QueueHandle<Self>, _: wl_output::WlOutput) {
        self.changed();
    }
}

delegate_registry!(Watcher);
impl ProvidesRegistryState for Watcher {
    fn registry(&mut self) -> &mut RegistryState { &mut self.registry }
    registry_handlers![OutputState];
}
smithay_client_toolkit::delegate_dispatch2!(Watcher);

pub fn run() -> Result<(), Box<dyn Error>> {
    if std::env::var("RICEBOWL_DE_SHELL_CHILD").as_deref() != Ok("1") {
        return Err("Output events require an active opt-in RiceBowl session".into());
    }
    let connection = Connection::connect_to_env()?;
    let (globals, mut queue) = registry_queue_init(&connection)?;
    let qh = queue.handle();
    let mut watcher = Watcher {
        registry: RegistryState::new(&globals),
        outputs: OutputState::new(&globals, &qh),
        ready: false,
    };
    // Consume the initial output inventory without a redundant Waybar restart.
    queue.roundtrip(&mut watcher)?;
    watcher.ready = true;
    loop {
        queue.blocking_dispatch(&mut watcher)?;
    }
}
