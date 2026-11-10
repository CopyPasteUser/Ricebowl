<div align="center">

<img src="assets/ricebowl-symbolic.svg" alt="RiceBowl" width="80">

# RiceBowl

**Build a desktop, not just a theme.**

A modular Linux desktop project with two distinct paths: **ready-to-use
XFCE/X11 rices** and an **experimental native Wayland desktop**.

**[XFCE/X11 guide](X11.md)** · **[Wayland guide](WAYLAND.md)** · [Roadmap](RICEBOWL_DE_ROADMAP.md) · [Releases](https://github.com/CopyPasteUser/Ricebowl/releases)

</div>

## Choose your desktop

| | XFCE / X11 | Wayland / labwc |
| --- | --- | --- |
| **Status** | **Current supported default** | **Opt-in preview — not 1.0** |
| **Foundation** | XFCE, XFWM4 and existing GTK/Python components | Upstream labwc and native Rust RicePlate |
| **Customize** | Seven OS-inspired desktop families | Validated RicePlate recipes and Rice Creator 0.9 |
| **Switching** | Plan/apply/restore XFCE rices | Separate session, nested preview and guarded recipe switching |
| **Read first** | **[X11 installation and usage](X11.md)** | **[Wayland setup and limitations](WAYLAND.md)** |

These are **different implementations**. Installing the XFCE version never
automatically replaces your login session with Wayland.

## XFCE / X11 · current default

[![RiceBowl XP Luna running on XFCE/X11](screenshots/current/winxp-start.webp)](screenshots/current/README.md)

Seven desktop families: **Windows 98, XP, Windows 7, Windows 10, ChromeOS,
Frutiger Aero and macOS-inspired** styles. Includes the RiceBowl Hub,
reversible rice switching and optional desktop components.

**[Install and use XFCE/X11](X11.md)** · [Real X11 screenshots](screenshots/current/README.md)

## Wayland · experimental preview

[![Orbit Studio running native RicePlate in headless labwc](screenshots/wayland/orbit.webp)](screenshots/wayland/README.md)

The next-generation desktop combines **labwc + Rust RicePlate**, RiceSpice
settings, RicePop notifications and the experimental **Rice Creator 0.9**.
Menus, desktop shortcuts, live controls, recipes and safe recovery paths are
implemented; **physical login, suspend/resume, devices, mixed-DPI and
accessibility still need acceptance**. The image is a real *headless CI*
capture, not proof of a tested laptop installation.

**[Wayland overview and safe first steps](WAYLAND.md)** · [Progress and screenshots](WAYLAND_PROGRESS.md)

## Project links

- [RiceField file manager](https://github.com/CopyPasteUser/Ricefield) and [Taskotto task manager](https://github.com/CopyPasteUser/Taskotto): optional, validated appearance integration.
- [Wayland engineering status](DESKTOP_ENVIRONMENT_STATUS.md) · [1.0 release gates](RELEASE_1_0_GATES.md) · [Full roadmap](RICEBOWL_DE_ROADMAP.md)
- [Contributing](CONTRIBUTING.md) · [License](LICENSE)

RiceBowl is independent of Microsoft, Apple and Google. Included artwork is
original. The Wayland desktop is **not yet a stable 1.0 release**.
