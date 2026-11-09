<div align="center">

<img src="assets/ricebowl-symbolic.svg" alt="RiceBowl" width="80">

# RiceBowl

**Build a desktop, not just a theme.**

A modular Linux desktop project with seven OS-inspired styles, an experimental Wayland environment and tools for building your own rices.

[Gallery](screenshots/current/README.md) · [Desktop status](DESKTOP_ENVIRONMENT_STATUS.md) · [Wayland guide](WAYLAND_SESSION.md) · [Roadmap](RICEBOWL_DE_ROADMAP.md)

</div>

![RiceBowl XP Luna desktop](screenshots/current/winxp-start.webp)

## What it includes

- **Seven XFCE/X11 styles:** Windows 98, XP Luna, Windows 7, Windows 10, Frutiger Aero, ChromeOS and macOS-inspired desktops.
- **Opt-in Wayland preview:** labwc with the native Rust RicePlate panel, menus, desktop shortcuts, live status controls and reversible rice switching.
- **RiceSpice and RicePop:** desktop settings, network/audio controls, notifications and on-screen displays.
- **Rice Creator 0.9 (experimental):** GTK recipe editor, reusable components, isolated previews and reference-image comparison with region-level feedback.
- **Rice ecosystem:** optional, validated appearance integration with [RiceField](https://github.com/CopyPasteUser/Ricefield) and [Taskotto](https://github.com/CopyPasteUser/Taskotto).

XFCE/X11 remains the default. The Wayland session and Creator are **previews**, not a finished replacement desktop or automatic screenshot-to-desktop converter. Hardware, accessibility and multi-monitor acceptance are still in progress.

## Try it

For Linux Mint XFCE or a compatible XFCE/X11 session:

```bash
sudo apt install -y git python3-gi python3-cairo python3-gi-cairo python3-pil gir1.2-gtk-3.0 gir1.2-wnck-3.0
git clone https://github.com/CopyPasteUser/Ricebowl.git "$HOME/RiceBowl"
cd "$HOME/RiceBowl"
bash install.sh --dry-run
bash install.sh
"$HOME/.local/bin/ricebowl"
```

Choose a style in the Hub; installation alone does not change your desktop. Run `ricebowl creator` for the experimental editor. `ricebowl update` checks for updates, and `macrice rice restore` undoes a rice switch.

## Documentation

[Wayland installation, Creator and safety](WAYLAND_SESSION.md) · [Feature and release status](DESKTOP_ENVIRONMENT_STATUS.md) · [Screenshots](screenshots/current/README.md) · [Example recipes](examples/wayland/README.md) · [Ecosystem roadmap](RICE_ECOSYSTEM_ROADMAP.md) · [Contributing](CONTRIBUTING.md) · [License](LICENSE) · [Releases](https://github.com/CopyPasteUser/Ricebowl/releases)

RiceBowl is independent of Microsoft, Apple and Google. Included artwork is original; a stable release still requires real-device acceptance.
