# RiceBowl Desktop Environment — implementation status

**As of 7 November 2026 · Experimental, opt-in · Not ready for 1.0**

RiceBowl's target is a lightweight **floating Wayland desktop based on upstream
labwc**, with a reusable recipe engine capable of distinct OS-inspired designs
and AI-assisted original desktop mockups. The proven XFCE/X11 rices remain the
supported default. New Wayland services must not silently replace XFCE or
modify global session settings.

## What really works

| Component | Verified implementation | Important gap |
| --- | --- | --- |
| Session / compositor | Opt-in labwc session, nested preview, Waybar fallback, startup supervision and cleanup | Physical login/relogin, recovery and power-use acceptance |
| RicePlate panel | Native Rust layer-shell, per-output panels, window discovery and grouped task activation, launcher, menu with fixed-action search/private per-rice pins, calendar, keyboard task navigation, compact layouts and **experimental SNI tray** with live pixmaps and direct clicks | Native tray overflow navigation/DBusMenu presentation, dynamic installed-app menu search, full accessibility and real-world focus QA |
| Desktop shortcuts | Schema-v5 native shortcut surfaces, drag repositioning, owner-private **per-named-output positions**, independent multi-output reflow, hotplug, Tab/Shift-Tab | Cross-monitor drag semantics, output identity without stable names and mixed-DPI/device tests |
| Wallpaper / appearances | Original bundled wallpapers, composable panel groups, labels, gaps, tokens, original example rices | Full desktop widgets, rich layout primitives, complete cross-app window decorations |
| Hardware indicators | Kernel-backed battery; NetworkManager connectivity and WirePlumber sink status on a bounded worker | Device picker, Bluetooth status, event subscriptions and finer status detail |
| RiceSpice controls | Allowlisted native-menu Wi-Fi/volume/mute; on-demand GTK settings hub with audio sink/source defaults, MPRIS media transport controls, Wi-Fi scan/visible-network selection plus transient WPA-Personal password entry, BlueZ paired-device and adapter controls, power-profile selection/battery state, polkit-gated system timezone selection, lock/confirmed suspend and next-login rice choice | Wi-Fi enterprise/EAP enrollment, VPN/Ethernet editors, fully native display/input/accessibility editors (presently delegated), NTP/clock editing, per-stream routing and physical hardware/AT QA |
| RicePop notifications/OSD | Opt-in native three-row Active/Past tabs in RicePlate, bounded keyboard/pointer selection, on-demand refresh and ID-bound dismissal **only** for active alerts, using Mako as the existing owner; transient input-transparent native volume OSD after explicitly selected RicePlate audio actions | External multimedia-key/volume-change OSD triggers, rich actions, native notification owner and non-Mako backends; physical accessibility QA |
| Session safety | Opt-in session, user polkit agent when installed, optional Mako/swayidle/swaylock, compositor exit cleanup | Complete suspend/resume and hardware recovery acceptance |
| Creator authoring | Schema-v1–v6 validation, offline private draft edits, reusable panel groups/labels/gaps/dividers, component catalog and API inventory, nested native render/capture and visual comparisons | Broad desktop composition, complete action/state bindings, high-fidelity mockup conversion |
| RicePack exchange | Deterministic v2 bundled-asset archives or v3 with one SHA-256-addressed private PNG wallpaper; private import/re-export attribution, v1/v2 read compatibility, next-login staging and one-level rollback | Portable icon/font/multi-asset sets, multi-component live apply and transactional active-session rollback |

**Native here means running in the experimental labwc session**, not the
existing Python/GTK XFCE experience. A declarative menu/indicator is not a
working settings page. The network/audio *status labels* are intentionally
non-clickable; the separate validated native-menu actions perform changes.

## Implementation boundaries

- **labwc** owns floating windows and compositing. RiceBowl does not fork it.
- **RicePlate** is the resident native Rust shell renderer; one process renders
  all panels, popups and supported desktop shortcut surfaces. Its optional
  native tray connects directly to the D-Bus StatusNotifierHost/Watcher
  protocol when a recipe includes `tray`, listens on the bus fd (no polling
  thread), draws size-checked SNI pixmaps, ignores Passive items and dispatches
  direct item Activate/ContextMenu calls. Missing pixmaps use an initial-letter
  placeholder. Four slots are reserved, with overflow indicated but navigation
  of overflow items and rich DBusMenu rendering not yet implemented. Native
  tray needs Rust 1.88 and `libdbus-1` at build/run time; a failed bus
  connection leaves the rest of the panel usable.
- **RiceSpice** delegates ordinary controls to NetworkManager and WirePlumber
  through fixed arguments. Its on-demand GTK3 settings window uses the existing
  PulseAudio-compatible server via `pactl` for default sinks/sources, the
  existing session MPRIS adapter for explicit media transport controls and BlueZ
  for Bluetooth, plus the optional `powerprofilesctl` service for energy
  profiles and read-only kernel battery state, with explicit user actions and
  bounded workers. Wi-Fi joins use only the currently visible NetworkManager
  inventory; WPA-Personal entry is masked and sent to NetworkManager via
  the existing stdin-only helper, never shell arguments or stored app secrets.
  Enterprise authentication remains delegated. Missing power-profile services
  are shown as unavailable. Audio-device and media-player discovery fail
  independently; absent media players never cause invented playback state. The
  date/time page selects only timezones returned by timedated, verifies the
  polkit-gated change and retains an optional installed editor fallback. Display,
  input and accessibility pages currently hand off to installed
  system editors, reporting absent editors. No custom recipe commands or
  privileged daemon.
- **RicePop** delegates delivery to the installed Mako host. The optional
  native menu queries active and past notifications only when opened/refreshed,
  displays history read-only and discards both sets of private messages when
  closed. Neither the menu nor CLI owns the notification bus name or replays
  third-party actions. Independently, RicePlate owns a single transient
  layer-shell volume OSD: it appears only after its own explicit volume/mute
  menu actions, uses actual WirePlumber readback and an 1.8-second event-loop
  deadline, and has an empty pointer/touch input region. Hardware multimedia
  keys and external volume changes do not yet trigger this OSD.
- **Creator** is optional, on demand and offline. It never needs a model at
  runtime and must require an explicit user choice before an active desktop
  change. Current stage/rollback affects the *next* opt-in login only.
- **Waybar** remains an intentionally supported recovery/fallback panel.

## Inspect or try without replacing XFCE

```bash
ricebowl de check --json
ricebowl de catalog --json
ricebowl de creator-api --json

# Explicit nested preview; native binary and labwc prerequisites required:
ricebowl de start --nested --panel native

# Optional example with real Wi-Fi/audio quick actions and native RicePop;
# import never applies it:
ricebowl de recipe-import --recipe "$PWD/examples/wayland/quick-controls.json"
ricebowl de start --nested --panel native --recipe quick-controls
# Open menu → Session → Notifications. Left/Right switches Active/Past;
# Enter/Delete dismisses a selected ACTIVE item only. R refreshes, Esc returns.
# A running Mako host is required.
# Select Quick actions → Volume +5%, Volume -5% or Mute for the native RicePop OSD.

# Only inside a Wayland session with the Mako notification host:
ricebowl de notifications --json
# Only when intentionally closing one active notification returned above:
ricebowl de notification-dismiss --notification-id 12 --json

# Real audio devices (never invent sink/source names):
ricebowl de audio-devices --json
# After reviewing a returned device name, explicitly choose it:
ricebowl de audio-default --device-kind sink --device-name "$DEVICE_NAME" --json

# On-demand RiceSpice settings (not a background service):
ricebowl de settings
```

Wi-Fi toggling can disconnect the current session. Notification JSON may
contain private messages; dismissal actually closes an alert in the current
Mako session. The nested preview does not change your current
desktop. See [Wayland preview instructions](WAYLAND_SESSION.md) for detailed
dependencies, screen captures and rollback behavior.

Changing an audio default affects future streams and may affect the active
audio session even outside the experimental RiceBowl login. Running streams
can continue on their previous outputs. If selection verification fails,
the CLI reports that the state may already have changed; inspect again.

## Verification and 1.0 gates

Implementation evidence includes [native icons PR #143](https://github.com/CopyPasteUser/Ricebowl/pull/143)
and [Mako bridge PR #141](https://github.com/CopyPasteUser/Ricebowl/pull/141).
Local automated suites most recently passed **915 Python tests** (16 skipped
for session/hardware constraints) and **53 native Rust tests**. GitHub's
`Tests`, `Native RicePlate prototype` and `Wayland session preview` workflows
have passed on the corresponding merged milestones. Native CI renders actual screenshots under headless labwc, including
two-output icon/menu/calendar hotplug coverage; this is *not* physical device
signoff, a performance benchmark or proof of historical-OS visual fidelity.

The next substantial release gates, in recommended order:

1. Finish native SNI overflow navigation, real item-owned DBusMenu presentation,
   output-relative activation coordinates and tray keyboard/accessibility
   focus; a live host and basic mouse actions now exist.
2. Complete RiceSpice's remaining delegated system editors as native pages,
   then verify device selectors, permission/error recovery and suspend/lock on
   actual hardware (an on-demand settings hub already exists).
3. Hook the native RicePop volume OSD into hardware multimedia-key/external
   volume events; enrich notification presentation and accessibility semantics
   without a duplicate owner or private-message replay. The on-demand
   Active/Past view and explicit RicePlate-action OSD are implemented.
4. Complete safe RicePacks with licensed asset manifests, broader composition,
   reproducible visual/functional QA and **explicit transactional live
   apply/restore** across all affected components.
5. Actual multi-monitor/mixed-DPI/input/assistive QA on Linux Mint and
   representative Wayland setups; measure idle PSS/RSS/CPU and launch time.

Detailed tasks and gate conditions live in
[the canonical Wayland DE roadmap](RICEBOWL_DE_ROADMAP.md). Do not call the
desktop 1.0 until those functional and physical gates are met.
