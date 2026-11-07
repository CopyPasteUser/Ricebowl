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

It is also becoming an independent, floating **Wayland desktop environment based on labwc**. Its long-term goal is a *desktop construction kit*: give an AI a reference screenshot or an original mockup, and use validated layout recipes and shared functional components to build a usable rice—without writing a new desktop shell for each design.

The **opt-in Wayland preview** already runs with labwc and a native Rust RicePlate panel: real window/task groups, keyboard-accessible menus with fixed-action search and private per-rice favorites, calendar, responsive layouts, movable desktop shortcuts on multiple outputs, battery/network/audio status, limited Wi-Fi/audio controls and an experimental event-driven StatusNotifier tray with icon clicks and navigable overflow. RiceSpice opens a real on-demand settings window with audio device selection and MPRIS media playback controls, Wi-Fi scan/connection to visible networks with saved credentials or a masked WPA-Personal password, Bluetooth, optional power profiles, battery status, polkit-gated timezone selection and lock/suspend actions; display, input and accessibility settings still delegate to installed system tools. RicePop offers opt-in native active/history tabs through the existing Mako host, single-alert dismissal limited to active items, and a transient input-transparent volume OSD after native volume/mute actions. An offline Creator CLI validates and edits reusable panel layout groups, labels, gaps and dividers, renders the real shell in isolated labwc, compares captures and exports **RicePack v2** bundles or **v3** archives with one verified content-addressed PNG wallpaper.

**It is not yet a complete replacement desktop.** Native tray DBusMenu presentation and first-class keyboard accessibility, complete built-in RiceSpice editors, external multimedia-key OSD triggers and richer notifications, portable icon/font/multi-asset packs, live rice switching with rollback and real-device QA are still missing. The existing seven-style XFCE/X11 environment remains the default. See the [honest feature and release-gate matrix](DESKTOP_ENVIRONMENT_STATUS.md).

## Try it

On Linux Mint XFCE or a compatible XFCE/X11 session:

```bash
sudo apt install -y git python3-gi python3-cairo python3-gi-cairo gir1.2-gtk-3.0 gir1.2-wnck-3.0
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
- [Two real Wayland Creator example rices and reproducible captures](examples/wayland/README.md)
- [Desktop environment development roadmap](RICEBOWL_DE_ROADMAP.md)
- [Rice ecosystem (RiceField, Taskotto and more)](RICE_ECOSYSTEM_ROADMAP.md)
- [Contributing](CONTRIBUTING.md) · [License](LICENSE) · [Releases](https://github.com/CopyPasteUser/Ricebowl/releases)

RiceBowl is independent of Microsoft, Apple and Google; no proprietary operating-system artwork is included. Real-hardware acceptance is required before a stable release.
