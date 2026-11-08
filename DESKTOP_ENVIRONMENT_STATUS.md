# RiceBowl Desktop Environment — implementation status

**As of 8 November 2026 · Experimental, opt-in · Not ready for 1.0**

RiceBowl's target is a lightweight **floating Wayland desktop based on upstream
labwc**, with a reusable recipe engine capable of distinct OS-inspired designs
and AI-assisted original desktop mockups. The proven XFCE/X11 rices remain the
supported default. New Wayland services must not silently replace XFCE or
modify global session settings.

## What really works

| Component | Verified implementation | Important gap |
| --- | --- | --- |
| Session / compositor | Opt-in labwc session, nested preview, Waybar fallback, startup supervision and cleanup; owner-local live profile apply/restore with panel/wallpaper/menu preflight and selection CAS | Physical login/relogin, compositor reconfigure, recovery and power-use acceptance |
| RicePlate panel | Native Rust layer-shell, per-output panels, window discovery and grouped task activation, launcher, schema-v6 tab/sidebar menus and bounded native menu sections; **schema-v6 fixed Apps/Terminal/Settings/Lock buttons** plus **schema-v7 live Wi-Fi/mute/volume controls** with real hardware state, verified writes, unavailable/busy/error feedback and keyboard/AT-SPI labels; calendar, responsive layouts, **experimental SNI tray** and nested DBusMenu context menus | Additional stateful component families, rich layout constraints, native iconography, localized app names, physical installed-app/Orca/screen-reader and third-party focus/tray QA; exact XP/7/10 fidelity deferred |
| Desktop shortcuts | Schema-v5 native shortcut surfaces, drag repositioning, owner-private **per-named-output positions**, independent multi-output reflow, hotplug, Tab/Shift-Tab | Cross-monitor drag semantics, output identity without stable names and mixed-DPI/device tests |
| Wallpaper / appearances | Bundled wallpapers, composable panel/menu layouts and tokens; **schema-v8 native desktop widgets**, **schema-v9 reusable status/action bindings and safe text widgets with pointer-transparent input**, plus **schema-v10 bounded native/Waybar appearance** (bitmap text scale/weight, item gaps, hover/focus/disabled) | Portable native fonts/icons, responsive menu dimensions, interactive desktop actions and complete cross-app window decorations |
| Hardware indicators | Kernel-backed battery; NetworkManager connectivity and WirePlumber sink status on a bounded worker | Device picker, Bluetooth status, event subscriptions and finer status detail |
| RiceSpice controls | Native-menu Wi-Fi/volume/mute; GTK settings hub with audio defaults, MPRIS and verified per-app sink/volume/mute; Wi-Fi scan/WPA-Personal, saved Ethernet/Wi-Fi/VPN profile activation, secure PEAP/TTLS creation/one-time EAP credentials and OpenVPN/WireGuard configuration import; BlueZ/power/timezone/NTP/manual clock, lock/suspend and next-login rice; wlroots mode/scale/X-Y trials with independent rollback and private manually recalled presets; labwc input, GTK cursor/text/high-contrast and supervised optional Orca launch | EAP-TLS client-certificate/manual vendor VPN authoring (delegated editor), automatic monitor preset restore at login and physical network/audio/monitor/AT QA |
| RicePop notifications/OSD | Native Mako-backed Active/Past lists and paged details; verified active-only actions/dismissal, open-only refresh with stale/reused-ID protection, Latin/Greek/Hiragana glyph coverage; input-transparent sink/backlight OSD, private hardware keys and reconnecting `pactl` observer | Real Mako/action/Orca/media-key/backlight/restart and resource QA; universal-script fonts and separate notification owners are post-1.0 options |
| Session safety | Opt-in session, user polkit agent when installed, optional Mako/swayidle/swaylock, compositor exit cleanup | Complete suspend/resume and hardware recovery acceptance |
| Creator authoring | Schema-v1–v10 validation, offline private draft edits, reusable panel/menu/desktop components with bounded status/action bindings, bounded shared visual tokens, **fixed-action and stateful controls**, catalog v11 and API inventory, nested native render/capture and visual comparisons | Portable font-family selection, rich interactive widgets, genuine window-placement controls and high-fidelity mockup conversion |
| RicePack exchange | Deterministic v2 bundled-asset archives or v3 with one SHA-256-addressed private PNG wallpaper; private import/re-export attribution, v1/v2 read compatibility, next-login staging and one-level rollback; guarded live panel/wallpaper/menu apply plus optional RiceProfile v1 RiceField/Taskotto appearance preflight and restore in the opt-in labwc session | Portable icon/font/multi-asset sets, atomic multi-process frame synchronization, real-display acceptance |

**Native here means running in the experimental labwc session**, not the
existing Python/GTK XFCE experience. A declarative menu/indicator is not a
working settings page. The network/audio *status labels* are intentionally
non-clickable; schema-v7 explicitly adds separate, stateful native panel controls
for supported Wi-Fi and audio actions. The Waybar fallback renders those as
disabled `N/A` labels rather than presenting an unverified click target.

## Implementation boundaries

- **labwc** owns floating windows and compositing. RiceBowl does not fork it.
- **RicePlate** is the resident native Rust shell renderer; one process renders
  all panels, popups and supported desktop shortcut surfaces. Its optional
  native tray connects directly to the D-Bus StatusNotifierHost/Watcher
  protocol when a recipe includes `tray`, listens on the bus fd (no polling
  thread), draws size-checked SNI pixmaps, ignores Passive items and dispatches
  direct item Activate/ContextMenu calls. Missing pixmaps use an initial-letter
  placeholder. Four slots are reserved; when needed, the fourth opens an
  output-local overflow popup with keyboard/pointer paging and activation.
  Right-click and menu-only SNI entries now show an output-local native
  DBusMenu popup when the item exposes a menu tree: nested pages, real
  enabled/visible flags, separators, checkmarks/radio state, bounded
  pagination, arrow/Tab/Enter/Escape/Back navigation and actual `menu_clicked`,
  `menu_opened` and `menu_closed` dispatch. Changes from the item are refreshed
  while the popup is open, with strict node/depth and label bounds. The panel
  keyboard focus cycle includes visible tray slots and the overflow entry;
  the keyboard Context Menu key (or Right from the overflow list) opens an
  application's SNI context menu even when its left-click activates a window.
  Items without a retrieved DBusMenu still receive their own `ContextMenu`
  call; this cannot guarantee every third-party app provides a usable menu.
  Very narrow panel layouts suppress the tray rather than cover task controls.
  Native
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
  Existing NetworkManager Ethernet, VPN and Wi-Fi profiles are displayed with
  real UUID-based activation, stale-state protection and explicit confirmation.
  New PEAP/TTLS password profiles require a RADIUS domain and system or custom
  CA trust; an ephemeral stdin-only password activates a reviewed, supported
  profile without persisting secrets. OpenVPN `.ovpn` and WireGuard `.conf`
  files can be imported into inactive NetworkManager profiles. Complex EAP-TLS
  client certificate and manual provider-specific VPN editing remains with the
  installed system editor.
  Missing power-profile services are shown as unavailable. Audio-device,
  active application playback stream and media-player discovery fail
  independently; each stream supports verified output, volume and mute controls.
  The
  date/time page selects only timezones returned by timedated, exposes verified
  system-wide NTP state/actions and a confirmed manual local clock editor
  when synchronization is off; polkit-gated changes are checked. Displays
  now read real active outputs from `wlr-randr`;
  their advertised mode, bounded scale and X/Y position can be tried with a
  detached 18-second rollback guard. Private saved layouts are manually
  recalled under the same guard, never forced at login. Enabling/disabling
  monitors and automatic persistence are not claimed. Input and limited accessibility
  settings are validated and saved in an owner-private file, then added to a
  private labwc config at the next opt-in session start (pointer/touchpad,
  keyboard repeat, cursor size, GTK text scale and optional high-contrast theme).
  The full RiceBowl session can optionally supervise an installed Orca reader;
  missing Orca is reported. The same opt-in flag activates RicePlate's native
  AccessKit/AT-SPI tree for its layer-shell controls with actionable elements,
  actual keyboard-focus reporting, menu and calendar, notices and live tray.
  AT clients never supply commands and requests run in the Wayland event loop.
  Physical Orca testing is still required before claiming screenreader signoff.
  No global XFCE or labwc user configuration is changed; neither complete
  assistive technology nor cross-toolkit scaling is claimed. No custom recipe commands or
  privileged daemon.
- **RicePop** leaves notification delivery to the installed Mako host. Its
  native inbox reads active/past alerts on open and refreshes only while open,
  retries with stale actions disabled and clears private bodies on close.
  Single-ID dismissals and application actions are verified against the host.
  Paged text uses built-in Latin/Greek/Hiragana 8×8 fonts, with visible fallback
  for unsupported scripts. One 1.8-second input-transparent OSD handles
  verified audio and hardware-backlight changes. The optional `pactl subscribe`
  observer restarts after exiting. Private labwc multimedia bindings never
  alter XFCE or the user's global configuration.
- **Creator** is optional, on demand and offline. It never needs a model at
  runtime and requires an explicit user choice before an active desktop
  change. Stage/rollback affect the next login; separate `creator-live-*`
  commands use a private supervisor socket for the current opt-in labwc shell;
  nested previews change appearance only until they exit.
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
The last previously merged native tray baseline passed **937 Python tests**
(21 skipped for session/hardware constraints) and **74 native Rust tests**.
GitHub's
`Tests`, `Native RicePlate prototype` and `Wayland session preview` workflows
have passed on the corresponding merged milestones. Native CI renders actual screenshots under headless labwc, including
two-output icon/menu/calendar hotplug coverage; this is *not* physical device
signoff, a performance benchmark or proof of historical-OS visual fidelity.

The next substantial release gates, in recommended order:

1. Validate native SNI/DBusMenu rendering, focus and third-party menu semantics
   on real multi-monitor hardware, then add any missing screen-reader/AT
   support. Host-rendered nested menus and panel tray keyboard focus now exist.
2. Expand RiceSpice's limited new display and assistive controls to monitor
   arrangement/persistence, genuinely usable screen-reader flows and missing
   system editors; then verify devices, rollback, permission/error recovery,
   and suspend/lock on physical hardware (the on-demand hub already exists).
3. Hook the native RicePop volume OSD into hardware multimedia-key/external
   volume events; enrich notification presentation and accessibility semantics
   without a duplicate owner or private-message replay. The on-demand
   Active/Past view and explicit RicePlate-action OSD are implemented.
4. Complete safe RicePacks with licensed asset manifests, broader composition,
   reproducible visual/functional QA and **session-wide transactional live
   apply/restore** across independent applications. Panel/wallpaper/labwc menu
   have a supervised opt-in live transaction. Approved recipe/reference
   SHA-256 baselines and a bounded rasterization-tolerant screenshot regression
   gate now exist; human baseline review, visual fidelity and input QA remain
   necessary.
5. Actual multi-monitor/mixed-DPI/input/assistive QA on Linux Mint and
   representative Wayland setups; measure idle PSS/RSS/CPU and launch time.

Detailed tasks and gate conditions live in
[the canonical Wayland DE roadmap](RICEBOWL_DE_ROADMAP.md). Do not call the
desktop 1.0 until those functional and physical gates are met.
