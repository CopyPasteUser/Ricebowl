<div align="center">

<img src="assets/ricebowl-symbolic.svg" alt="RiceBowl logo" width="76">

# RiceBowl

**Build a desktop, not just a theme.**

A modular Linux desktop project: polished **XFCE/X11 rices** today, and an
**experimental native Wayland desktop** in development.

[**XFCE/X11 guide**](X11.md) · [**Wayland guide**](WAYLAND.md) ·
[Roadmap](RICEBOWL_DE_ROADMAP.md) · [Releases](https://github.com/CopyPasteUser/Ricebowl/releases)

</div>

## Choose your desktop

| | XFCE / X11 | Wayland / labwc |
| --- | --- | --- |
| **Status** | Supported default | Opt-in preview; **not 1.0** |
| **Desktop** | Existing XFCE + XFWM4 | labwc + native Rust RicePlate |
| **Styles** | Seven OS-inspired families | Recipe-driven shell; XP Luna in active development |
| **Start here** | [Install and restore](X11.md) | [Requirements and safe preview](WAYLAND.md) |

These are **separate implementations**. Installing or changing an XFCE rice
does not switch your login session to Wayland.

## Screenshots

| XFCE/X11 · XP Luna | Native Wayland · XP Luna preview |
| :---: | :---: |
| [![Actual XP Luna-style XFCE Start menu](screenshots/current/winxp-start.webp)](screenshots/current/README.md) | [![Actual Wayland labwc and RicePlate Luna Start menu, November 13](screenshots/wayland/luna-start-20261113.webp)](screenshots/wayland/README.md) |
| [X11 gallery](screenshots/current/README.md) | [Wayland gallery](screenshots/wayland/README.md) |

Both screenshots come from real automated desktop sessions, **not mockups**.
The Wayland image is a headless compositor capture, not evidence of a finished
or hardware-approved desktop. The [nine-view native Wayland gallery](screenshots/wayland/README.md)
also shows **All Programs, the calendar, shortcut context menus, Properties,
Help, Run and the updated labwc titlebar**, with source commit and CI provenance.

## XFCE/X11 · use it now

Choose from **Windows 98, XP Luna, Windows 7 Aero, Windows 10, ChromeOS,
Frutiger Aero and macOS-inspired** styles. RiceBowl Hub provides previews,
explicit apply/restore actions and optional shell components while keeping
XFCE underneath.

**[Installation, daily use and recovery →](X11.md)**

## Wayland · build the next desktop

**labwc** handles windows; **RicePlate** renders native panels, Start menus,
tasks, tray and desktop surfaces. **RiceSpice** provides settings,
**RicePop** handles notifications, and **Rice Creator** edits and previews
validated recipes. XP Luna is an actively developed Wayland rice, not an
exact Windows XP replica.

Use the [Wayland setup guide](WAYLAND.md) to check prerequisites and try a
**nested session** without replacing XFCE. Automated compositor tests cover
many behaviors, but **physical login, suspend/resume, device integration,
mixed-DPI and accessibility acceptance remain open**.

[**See Wayland screenshots**](screenshots/wayland/README.md) ·
[Feature parity](WAYLAND_XP_LUNA_PARITY.md) ·
[Engineering status](DESKTOP_ENVIRONMENT_STATUS.md) ·
[1.0 release gates](RELEASE_1_0_GATES.md)

## Project

[RiceField file manager](https://github.com/CopyPasteUser/Ricefield) ·
[Taskotto task manager](https://github.com/CopyPasteUser/Taskotto) ·
[Contributing](CONTRIBUTING.md) · [License](LICENSE)

RiceBowl is independent of Microsoft, Apple and Google. The Wayland
desktop is **not yet a stable 1.0 release**.
