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
| RicePlate panel | Native Rust layer-shell, per-output panels, window discovery and grouped task activation, launcher, menu with fixed-action search/private per-rice pins, calendar, keyboard task navigation, compact layouts | Native StatusNotifier tray; dynamic installed-app menu search, full accessibility and real-world focus QA |
| Desktop shortcuts | Schema-v5 native shortcut surfaces, drag repositioning, owner-private **per-named-output positions**, independent multi-output reflow, hotplug, Tab/Shift-Tab | Cross-monitor drag semantics, output identity without stable names and mixed-DPI/device tests |
| Wallpaper / appearances | Original bundled wallpapers, composable panel groups, labels, gaps, tokens, original example rices | Full desktop widgets, rich layout primitives, complete cross-app window decorations |
| Hardware indicators | Kernel-backed battery; NetworkManager connectivity and WirePlumber sink status on a bounded worker | Device picker, Bluetooth status, event subscriptions and finer status detail |
| RiceSpice controls | Allowlisted native-menu Wi-Fi/volume/mute; on-demand GTK settings hub with audio sink/source defaults, Wi-Fi scan/visible-network selection plus transient WPA-Personal password entry, BlueZ paired-device and adapter controls, power-profile selection and battery state, lock/confirmed suspend and next-login rice choice | Wi-Fi enterprise/EAP enrollment, VPN/Ethernet editors, fully native display/input/accessibility/timezone editors (presently delegated), per-stream routing and physical hardware/AT QA |
| RicePop notifications | Opt-in native three-row Active/Past tabs in RicePlate, bounded keyboard/pointer selection, on-demand refresh and ID-bound dismissal **only** for active alerts, using Mako as the existing owner | OSD, rich actions, native notification owner and non-Mako backends; physical accessibility QA |
| Session safety | Opt-in session, user polkit agent when installed, optional Mako/swayidle/swaylock, compositor exit cleanup | Complete suspend/resume and hardware recovery acceptance |
| Creator authoring | Schema-v1–v5 validation, offline private draft edits, component catalog and API inventory, nested native render/capture and visual comparisons | Broad desktop composition, complete action/state bindings, high-fidelity mockup conversion |
| RicePack exchange | Deterministic v2 bundled-asset archives or v3 with one SHA-256-addressed private PNG wallpaper; private import/re-export attribution, v1/v2 read compatibility, next-login staging and one-level rollback | Portable icon/font/multi-asset sets, multi-component live apply and transactional active-session rollback |

**Native here means running in the experimental labwc session**, not the
existing Python/GTK XFCE experience. A declarative menu/indicator is not a
working settings page. The network/audio *status labels* are intentionally
non-clickable; the separate validated native-menu actions perform changes.

## Implementation boundaries

- **labwc** owns floating windows and compositing. RiceBowl does not fork it.
- **RicePlate** is the resident native Rust shell renderer; one process renders
  all panels, popups and supported desktop shortcut surfaces.
- **RiceSpice** delegates ordinary controls to NetworkManager and WirePlumber
  through fixed arguments. Its on-demand GTK3 settings window uses the existing
  PulseAudio-compatible server via `pactl` for default sinks/sources and BlueZ
  for Bluetooth, plus the optional `powerprofilesctl` service for energy
  profiles and read-only kernel battery state, with explicit user actions and
  bounded workers. Wi-Fi joins use only the currently visible NetworkManager
  inventory; WPA-Personal entry is masked and sent to NetworkManager via
  the existing stdin-only helper, never shell arguments or stored app secrets.
  Enterprise authentication remains delegated. Missing power-profile services
  are shown as unavailable. Display,
  input, timezone and accessibility pages currently hand off to installed
  system editors, reporting absent editors. No custom recipe commands or
  privileged daemon.
- **RicePop** delegates delivery to the installed Mako host. The optional
  native menu queries active and past notifications only when opened/refreshed,
  displays history read-only and discards both sets of private messages when
  closed. Neither the menu nor CLI owns the notification bus name or replays
  third-party actions.
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

1. Real native SNI tray, correct item ownership/actions and per-output focus;
   complete panel keyboard/accessibility behavior.
2. Complete RiceSpice's remaining delegated system editors as native pages,
   then verify device selectors, permission/error recovery and suspend/lock on
   actual hardware (an on-demand settings hub already exists).
3. RicePop OSD, richer notification presentation and accessibility semantics
   without a duplicate owner or private-message replay; a read-only history
   tab is available already.
4. Complete safe RicePacks with licensed asset manifests, broader composition,
   reproducible visual/functional QA and **explicit transactional live
   apply/restore** across all affected components.
5. Actual multi-monitor/mixed-DPI/input/assistive QA on Linux Mint and
   representative Wayland setups; measure idle PSS/RSS/CPU and launch time.

Detailed tasks and gate conditions live in
[the canonical Wayland DE roadmap](RICEBOWL_DE_ROADMAP.md). Do not call the
desktop 1.0 until those functional and physical gates are met.
