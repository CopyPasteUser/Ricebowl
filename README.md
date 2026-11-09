<div align="center">

<img src="assets/ricebowl-symbolic.svg" alt="RiceBowl" width="80">

# RiceBowl

**Build a desktop, not just a theme.**

A lightweight, modular Linux desktop project for recreating classic OS experiences and building original **AI-assisted rices** from reusable components.

[Desktop gallery](screenshots/current/README.md) · [Desktop status](DESKTOP_ENVIRONMENT_STATUS.md) · [Wayland roadmap](RICEBOWL_DE_ROADMAP.md) · [Get started](#try-it)

</div>

![RiceBowl XP Luna desktop](screenshots/current/winxp-start.webp)

## What is RiceBowl?

Today, RiceBowl is a **seven-style XFCE/X11 ricing suite**: Windows 98, XP Luna, Windows 7, Windows 10, Frutiger Aero, ChromeOS and macOS-inspired experiences. Each has its own menus, panels and controls, using original artwork and real Linux integrations.

It is also becoming an independent, floating **Wayland desktop environment based on labwc**. Its long-term goal is a *desktop construction kit*: give an AI a reference screenshot or an original mockup, and use validated layout recipes and shared functional components to build a usable rice—without writing a new desktop shell for each design. **Framework-first:** safe reusable controls, session switching and creator contracts take priority over pixel-perfect historical OS themes.

**Experimental Rice Creator 0.9:** run `ricebowl creator` (also installed as a desktop entry). The GTK editor creates immutable schema-v11 drafts from four templates, edits reusable components, nested panel groups and desktop geometry, and imports private wallpaper/icon/TrueType assets. Its private PNG workflow compares an isolated *real* native RicePlate capture against a reference with split/overlay/tolerance heatmaps. Version 0.7 added conservative offline panel/color hints and individually approved external AI/human JSON proposals; 0.8 added bounded region-based diagnostics. **New in 0.9:** click-drag to select source-pixel regions in the reference viewer, inspect a numbered overlay, then follow a repeatable *measure → edit → save → render → re-measure* cycle with SHA-bound, per-region error deltas across up to 12 captures. Manual coordinate input remains available. No image upload, AI service, generated scripts or desktop activation occurs. RicePack v4 never includes private references, proposals or region reports. Automatic semantic screenshot-to-rice conversion and real hardware acceptance remain future work. [Creator 0.9 guide](WAYLAND_SESSION.md#rice-creator-09--interactive-region-correction-cycle)

The **opt-in Wayland preview** already runs with labwc and a native Rust RicePlate panel: real window/task groups, keyboard-accessible menus with schema-v6 horizontal-tab or left-sidebar layouts and **optional bounded action/favorite/installed-app list or two-column grid sections**, fixed-action and installed-XDG-app search (via `gio launch`) and private per-rice action favorites, calendar, responsive layouts, movable desktop shortcuts on multiple outputs (including private `F6` per-monitor assignment, `F7` unmirroring reversal and hotplug fallback; cross-monitor release-to-drop has software coverage; physical pointer-grab QA is still pending), battery/network/audio status, **schema-v7 declarative live Wi-Fi/mute/volume panel controls with verified readback, disabled/pending/failure states and AT-SPI labels**, and an experimental event-driven StatusNotifier tray with icon clicks, keyboard-accessible slots and overflow, plus bounded native DBusMenu context menus with submenus and live toggle indicators. The opt-in **schema-v8 Layout Engine** additionally composes read-only clock/date/system desktop widgets with desktop shortcuts around a reserved percentage-based window region, with live logical-output reflow and compact-screen hiding; it does **not** control labwc client placement, and Waybar does not render these desktop widgets. RiceSpice opens a real on-demand settings window with audio device selection and MPRIS media playback controls, Wi-Fi scan/connection to visible networks with saved credentials or a masked WPA-Personal password, Bluetooth, optional power profiles, battery status, polkit-gated timezone selection and lock/suspend actions. Its native monitor page supports temporary mode/scale trials with automatic rollback, while input and limited cursor/GTK accessibility preferences are stored for the next opt-in labwc login. RicePop offers native active/history tabs with details, active-only explicit dismissal and freshly verified app actions through the existing Mako host; external default-sink changes also update its input-transparent volume OSD. An offline Creator CLI validates and edits reusable panel layout groups, labels, gaps, dividers and fixed Linux controls, renders the real shell in isolated labwc, compares captures and exports **RicePack v2** bundles or **v3** archives with one verified content-addressed PNG wallpaper. The Waybar fallback exposes v7 controls as *noninteractive N/A labels* rather than simulating the native worker.

Creator visual QA now supports manually approved, SHA-256-pinned screenshot baselines with 1–2 px rasterization tolerance and a machine-readable regression result. It does not automatically judge OS fidelity. **Explicit live switching** in the opt-in labwc session changes the RicePlate/Waybar panel, swaybg wallpaper, private labwc menu and next-login selection, recovering previous components on activation failure. **RiceProfile v1** additionally discovers compatible independent RiceField/Taskotto installations, prevalidates their data-only appearance files and includes them in the session's guarded apply/restore. Installed apps started inside this session can follow the generated private TOML files; existing windows refresh asynchronously (RiceField ~3 s, Taskotto ~2 s). Missing/older clients are safely skipped; `de creator-live-status --json` reports managed apps. No system default app, saved preference or XFCE configuration is changed. These are file-level reversible transactions, **not** a guarantee that every client renders the same frame simultaneously. `de creator-live-apply` requires a reviewed recipe; physical multi-app acceptance is still pending.

Live recovery now also compensates a late selection-write error without losing the previous login/undo state, refuses to clobber concurrent Creator stages, rolls back partial multi-app profile restores, and attempts the menu/selection recoveries even if one client fails. A crashed live panel triggers at most one prior-rice restore followed by one verified Waybar rescue; session shutdown cancels an in-progress switch. This is tested software fault handling, **not** a claim of crash-proof display-frame atomicity or physical suspend/power-loss acceptance.

The first **shared component library (schema v9)** lets one validated status/action definition be reused in native panel, compact layout and read-only desktop widgets; the desktop can also display bounded static text labels without intercepting pointer input. Buttons reuse RicePlate's existing verified worker and focus handling; no per-rice scripts, new daemons or XFCE defaults are introduced. [Component contract and example](WAYLAND_SESSION.md#schema-v9-shared-component-bindings-native-riceplate)

**Schema v10 appearance tokens** add validated bitmap text scaling/weight, panel-item spacing and shared hover/focus/disabled colors for native surfaces and Waybar. **Schema v11** adds native-only private TrueType glyphs and desktop shortcut artwork; the Waybar rescue path retains built-in fonts/icons and compiles compact/full bars for each detected logical monitor at startup, with a compact catch-all for later hotplug outputs. Confirmed RiceSpice display changes refresh only the supervised Waybar; an optional event-driven native watcher also detects external mode changes without polling, with `ricebowl de display-refresh` remaining available as recovery. Native menus and RicePop notifications now display full-resolution, keyboard/pointer/AT-SPI-aware paged layouts on supported small outputs. Extreme-size reflow and physical usability QA remain open. [Appearance contract](WAYLAND_SESSION.md#schema-v10-appearance-and-output-aware-fallback)

Advanced RiceSpice now also handles active application playback streams (output,
volume and mute), saved Ethernet/Wi-Fi/VPN NetworkManager connections, guarded
monitor X/Y positioning and owner-private manually recalled layouts. It can
create verified PEAP/TTLS enterprise Wi-Fi profiles, supply one-shot passwords
through NetworkManager's stdin credential channel and import OpenVPN/WireGuard
configuration files. It can request a high-contrast GTK theme and start an
installed Orca screen reader in the full RiceBowl session. When enabled,
RicePlate exports a real AccessKit/AT-SPI tree for native panel, menu, task,
calendar, shortcut, notification and tray controls, with event-loop-routed
actions and focus. These capabilities still require physical Orca and device QA.

The native RicePop volume OSD also reacts to real default-sink volume/mute
changes from other audio controls. In a full labwc session, private XF86Audio
shortcuts drive WirePlumber; an optional reconnecting Pulse-compatible monitor
feeds the existing input-transparent OSD. An exposed kernel backlight also
enables a brightness OSD with optional private `brightnessctl` keybindings.
The Mako inbox refreshes only while it is open, and long messages are paged.
Neither path changes XFCE shortcuts.

**It is not yet a complete replacement desktop.** Physical Orca/AT-SPI and tray/focus validation, automatic/safe monitor layout restoration, certificate-based EAP-TLS and manual provider-specific VPN authoring, RicePop Mako/action/hardware-key/backlight acceptance, broad international font coverage, complete system icon themes, cross-application transactional switching and real-device QA remain open. Mako intentionally remains the notification owner for RicePop 1.0. The existing seven-style XFCE/X11 environment remains the default. See the [honest feature and release-gate matrix](DESKTOP_ENVIRONMENT_STATUS.md).

## Try it

On Linux Mint XFCE or a compatible XFCE/X11 session:

```bash
sudo apt install -y git python3-gi python3-cairo python3-gi-cairo python3-pil gir1.2-gtk-3.0 gir1.2-wnck-3.0
git clone https://github.com/CopyPasteUser/Ricebowl.git "$HOME/RiceBowl"
cd "$HOME/RiceBowl"
bash install.sh --dry-run
bash install.sh
"$HOME/.local/bin/ricebowl"
```

Select a rice in the Hub; installation alone does not change your desktop. Use `ricebowl update` to check for updates or `macrice rice restore` to undo a rice switch.

## Explore

- [Wayland preview, installation and safety](WAYLAND_SESSION.md)
- [Current desktop environment implementation status](DESKTOP_ENVIRONMENT_STATUS.md)
- [AI-friendly shell recipes and components](WAYLAND_SESSION.md#schema-v5-native-desktop-icons-preview)
- [Schema-v8 Layout Engine and responsive desktop widgets](WAYLAND_SESSION.md#schema-v8-layout-engine-native-riceplate)
- [Two real Wayland Creator example rices and reproducible captures](examples/wayland/README.md)
- [Desktop environment development roadmap](RICEBOWL_DE_ROADMAP.md)
- [Rice ecosystem (RiceField, Taskotto and more)](RICE_ECOSYSTEM_ROADMAP.md)
- [Contributing](CONTRIBUTING.md) · [License](LICENSE) · [Releases](https://github.com/CopyPasteUser/Ricebowl/releases)

RiceBowl is independent of Microsoft, Apple and Google; no proprietary operating-system artwork is included. Real-hardware acceptance is required before a stable release.
