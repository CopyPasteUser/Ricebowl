# Contributing

Thank you for helping improve RiceBowl. The project has two separate targets:
the [current XFCE/X11 desktop](X11.md) and the [opt-in Wayland preview](WAYLAND.md).

1. Open an issue for observable bugs or compatibility concerns.
2. Make focused changes; avoid replacing the tested component installers.
3. Run `/usr/bin/python3 -m unittest discover -s tests -v` from the root.
4. For native Wayland/RicePlate changes, run
   `cargo test --manifest-path components/riceplate-wayland/Cargo.toml` and
   the relevant headless Wayland CI; for X11 changes, run the component's
   Python/XFCE checks.
5. Keep screenshots free of usernames, SSIDs, IP addresses, private notes and desktop notifications.

For bug reports, identify **X11 or Wayland**, the Linux distribution, session
type, compositor/window manager and relevant Python/Rust versions. Changes to
default XFCE panel behavior must remain opt-in and have a documented rollback.
Never claim physical Wayland acceptance from headless CI alone.
