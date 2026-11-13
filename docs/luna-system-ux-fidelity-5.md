# XP Luna System UX Fidelity 5 — implementation and acceptance

**Scope:** Control Panel, RiceSpice detail pages, Help/Properties and existing
GTK test capture workflow. The opt-in labwc session, X11/XFCE default,
recipe schemas, native pointer/window engine, Start and taskbar are unchanged.

## Real settings and their effects

The Wayland-facing **`ricebowl de settings --luna`** Control Panel uses exactly
the pre-existing `macrice.de.settings` page dispatcher. Category View and
Classic View differ in navigation structure, **not in the backend**.

| XP category or view | Real Linux settings page(s) | Execution and availability |
|---|---|---|
| Appearance and Themes | appearance, displays, taskbar | On-demand readback; guarded monitor trial/rollback; private next-login settings |
| Network and Internet Connections | network, bluetooth | NetworkManager / BlueZ; explicit operations with expected-state guards |
| Sounds, Speech, and Audio Devices | audio, notifications | PipeWire/PulseAudio + MPRIS; existing RicePop backend |
| Mouse, Keyboard and Other Hardware | input | Validated, owner-private next-login settings |
| Performance and Maintenance | power, timezone | Real power-profile / timedatectl state and permissions |
| Accessibility Options | accessibility | Owner-private next-login settings; Orca availability is clearly stated |

The X11 Luna Control Panel has **nine historical-style categories** with
installed-tool availability checks. An absent utility is disabled and labelled
as such; there is no fabricated Linux applet or shell-based execution.

## Fidelity and UI behavior

- Native window-manager decorations remain authoritative in the **Wayland
  RiceSpice** window. The content header is an XP-era *task banner*, not a
  second draggable titlebar. In the established XFCE/X11 DOCK child variant,
  existing single draggable in-client chrome is retained for compatibility.
- Both Luna Control Panels now implement true **Back / Forward / Home**, with
  maximum 32 bounded local view-history entries. Typing a search refines one
  history entry, not hundreds of entries. Opening a new view discards its
  abandoned Forward branch. Routes never contain executable commands.
- `Alt+Left/Right`, `Ctrl+F`, `Ctrl+1/2` (Wayland RiceSpice) and Escape
  restore navigation. GTK provides focus traversal and accessibility names.
- XP-era pale-blue tasks pane, bevel-edged gray toolbar, cream-white detail
  area, warm-orange focus ring, familiar underlined blue text links and
  original RiceBowl SVG icons replace the contemporary blue dashboard header.
- Help adds Forward, Alt+Arrow, Ctrl+F, Escape and a real, allowlisted
  **Open related Control Panel category** action for topics with a supported
  destination. Topics without one get an explicitly disabled button.
- A late GTK command after worker shutdown releases the semaphore and busy
  state rather than leaving a perpetual spinner.

## Visual and execution evidence

`scripts/capture_luna_control_panel.py` captures **six distinct mapped GTK3
client frames under a real Xvfb GTK session**: category overview, selected
category, Classic View, Input details, Taskbar details, and live Search.
`ci.yml` verifies all six dimensions and unique image hashes; an optional
`/proc` process RSS/PSS snapshot is written beside them in
`luna-control-panel-capture-metrics.json`. These metrics belong to that
**single CI process**, not to labwc or a user's laptop. The pre-existing
XP X11 gallery also covers Help, System Properties, Run, notifications,
and compact 1024×768 screenshots under XFWM4.

The existing **native RicePlate/labwc** smoke covers native Run dialogs and
screen/keyboard interaction, but **does not** demonstrate that the GTK
Control Panel is rendered inside the same compositor. Treat GTK/Xvfb
screenshots as real GTK evidence, not as Wayland screenshots.
A labwc-launched RiceSpice capture and physical keyboard/Orca tests remain
open and must be added to a dedicated integration acceptance gate.

## Gates and known limitations

- [ ] Exact-head full Python/GTK CI is green.
- [ ] Six distinct real GTK screenshot receipts from exact-head CI.
- [ ] Native RicePlate/labwc smoke is green on a compatible compositor.
- [ ] Real labwc GTK Control Panel: categories, Help, System/Properties,
      native window decorations, 640×480 / 1024×768 / 1920×1080 and 1.25× DPI.
- [ ] Physical Linux Mint: pointer/IME, NVDA-equivalent Orca, assistive
      focus/AT-SPI, NetworkManager/BlueZ/Audio/Display trials, suspend/rollback.
- [ ] Performance signoff on representative laptop: startup latency,
      settled PSS/RSS, idle CPU and process count across complete session.
- [ ] No current-main conflicts and no regressions in other rice profiles.

No measured hardware gains, original Microsoft artwork, duplicate daemon, or
completed physical accessibility certification are claimed by this sprint.
