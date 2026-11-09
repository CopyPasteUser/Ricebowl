# RiceBowl Wayland — progress, screenshots and release readiness

**Snapshot: 9 November 2026 · Experimental, opt-in labwc/RicePlate desktop · Not a stable 1.0 release**

RiceBowl is transitioning from an XFCE/X11 ricing suite to a lightweight, modular, floating **Wayland desktop built on upstream [labwc](https://labwc.github.io/)**. This is more than a Waybar theme: the experimental session has a native Rust shell, configurable menus and desktop surfaces, settings, notifications, and a visual recipe editor.

**XFCE/X11 is still the supported default.** The Wayland session does not silently replace the login session, the existing panel, the user's global labwc configuration, or personal XFCE settings. Implemented code, successful headless CI and physical hardware acceptance are *different* levels of evidence.

[Try the preview](#try-it-safely) · [Screenshot evidence](#real-wayland-screenshots) · [Detailed feature matrix](DESKTOP_ENVIRONMENT_STATUS.md) · [Full development roadmap](RICEBOWL_DE_ROADMAP.md) · [Implementation guide](WAYLAND_SESSION.md)

## Architecture at a glance

| Layer | Responsibility | State |
| --- | --- | --- |
| **labwc** | Floating window placement, compositor and XWayland clients | Integrated into the optional login/nested session; upstream compositor, not a fork |
| **RicePlate** | Native Rust layer-shell panels, task groups, launcher/menus, desktop shortcuts, tray, calendar, widgets | Implemented as an experimental shell; headless native CI, real-device input/focus QA outstanding |
| **RiceSpice** | On-demand GTK settings for network, sound, Bluetooth, displays, input, accessibility, power and appearance | Functional guarded controls and explicit readback; hardware/permission and accessibility QA outstanding |
| **RicePop** | Native notification inbox and volume/brightness OSD | Uses Mako as notification owner; real device/media-key/action and Orca QA outstanding |
| **Rice Creator** | Offline recipe authoring, isolated native render, reference comparison and safe RicePack exports | **0.9 experimental**; human-guided regions/corrections, not automatic screenshot-to-desktop conversion |
| **Waybar fallback** | Minimal usable panel if RicePlate cannot run | Deliberately retained for recovery, not visual or feature parity |

The compositor retains ownership of ordinary application windows and their decorations. A rice can restyle and rearrange RiceBowl-owned components; it cannot guarantee a pixel-perfect Windows/macOS desktop or restyle arbitrary third-party app chrome.

## Implementation status

| Area | Available today | Still outstanding before 1.0 |
| --- | --- | --- |
| **Session and recovery** | Separate opt-in Wayland login entry, nested session, startup supervision, private labwc configuration, cleaned-up exit, guarded live recipe selection, rollback and bounded Waybar rescue | Physical login/logout/relogin, suspend/lock, crash/display recovery, install/upgrade/uninstall checks |
| **Native panel and app menu** | Per-output layer-shell panels, real window discovery/grouping, launcher, keyboard navigation, tab/sidebar menus, fixed allowlisted actions, calendar, search, responsive layouts | Third-party app/focus QA, full localization/icon system, long-run performance, final small-screen accessibility |
| **Desktop / layout** | Movable shortcut icons, named-output positions, tested cross-output drops, hotplug reflow, schema-v8 read-only widgets and schema-v9 shared status/action components | Real mouse grab and mixed-DPI/multi-monitor validation, richer layout primitives, dependable output identity |
| **Hardware state and quick actions** | NetworkManager/WirePlumber state, real bounded Wi-Fi/mute/volume actions with disabled/busy/error feedback; battery readout | Physical networking/audio edge cases and device-specific interoperability |
| **RiceSpice** | Audio device/stream and MPRIS controls; Wi-Fi/NetworkManager profiles, selected VPN import, Bluetooth/power/date-time; guarded wlroots display mode/scale/position trials and manually recalled layouts; next-login input/accessibility preferences | Real hardware regressions, auto monitor layout restore, advanced EAP-TLS/vendor VPN editing, broad accessibility/Orca signoff |
| **RicePop** | Mako-backed Active/Past lists, verified actions/dismissal, event-driven sink OSD and supported brightness keys/backlight OSD | Actual Mako/keyboard/notification-owner/restart behavior on devices; broader scripts and screen-reader UX |
| **Creator / formats** | Schema-v1–v11 validated recipes; reusable components, editable nested layout, private PNG/icon/font assets, isolated real RicePlate renders, source-region selection and repeatable visual comparison; guarded RicePack v4 export and compatibility checks | Semantic screenshot-to-rice generation, layout fidelity across disparate designs, human baseline review, real-screen acceptance |
| **App ecosystem** | Optional data-only RiceProfile v1 integration with compatible RiceField and Taskotto, validation and best-effort revert | Guaranteed synchronized multi-process frame update is **not** claimed |

**Terminology matters:** A working *native component* is not automatically a working desktop-wide feature. Native status text does not mean every control is interactive. The fallback Waybar panel deliberately shows unsupported interactive state as unavailable instead of pretending to control hardware.

## Real Wayland screenshots

There are **real compositor framebuffer captures**, not just mockups. They were produced in an isolated headless **labwc + native RicePlate** run and archived by GitHub Actions.

**Evidence:** [Successful Native RicePlate CI run #42625109733](https://github.com/CopyPasteUser/Ricebowl/actions/runs/42625109733) on source commit [`8001a0a`](https://github.com/CopyPasteUser/Ricebowl/commit/8001a0a24db469358f420cc82a8ccaf4522b26c6) (9 November 2026). Open that run's **Artifacts → `riceplate-native-preview-8001a0a...`**, then browse the PNGs below.

| Capture inside the CI artifact | What it shows | What it does **not** prove |
| --- | --- | --- |
| `isolated-v5.png` | Real isolated 1024×768 native shell, classic-style panel/shortcuts and wallpaper | Full installed-login integration or actual desktop usage |
| `creator-examples/orbit-studio-v10-1366x768-scale-1-0.png` | Original orbit-themed composition with top panel, live-data slots and visual tokens | Final artistic polish or working Wi-Fi in CI |
| `creator-examples/heritage-modern-v10-1366x768-scale-1-0.png` | Structurally distinct classic layout, bottom panel and read-only desktop widgets | Pixel-perfect historical fidelity |
| `menu-sidebar-v6.png` | Native sidebar menu rendered as a real Wayland layer surface | Physical mouse/keyboard focus and third-party app compatibility |
| `calendar-v5.png` / `components-v9.png` | Calendar and shared status/widget surfaces | Complete localization or live hardware values |
| `desktop-v5-1024x768.png`, `desktop-v5-1920x1080.png`, `desktop-v5-scale-125.png` | Actual native geometry captures at multiple sizes/scales | Mixed-DPI monitor/device acceptance |
| `multioutput/*` | Separate panel/menu/calendar/shortcut captures before and after simulated output changes | Real dock, GPU, monitor hotplug or sleep behavior |

The artifact includes `capture-manifest.json` and `creator-examples/manifest.json` with source revision, environment, capture dimensions and SHA-256 hashes. The screenshot bytes and these manifests were checked for consistency when preparing this page. They are **CI screenshots with synthetic/headless device state**; labels such as `N/A` are expected and should not be misrepresented as a functional network connection.

**Retention warning:** GitHub Actions artifacts are temporary (this run's archive expires on **23 November 2026**). This document links to the reproducible workflow and source rather than embedding images that would silently disappear. The canonical XFCE/X11 [screenshot gallery](screenshots/current/README.md) is **not** a Wayland gallery. To create fresh Wayland evidence after expiry, rerun [the native workflow](.github/workflows/riceplate-native.yml) on the intended revision, or follow the [capture commands](WAYLAND_SESSION.md) in an isolated preview. Do not substitute stylized concept art for a screenshot.

### Reproduce the headless capture tests

The [native CI job](.github/workflows/riceplate-native.yml) builds RicePlate, runs its Rust tests, starts labwc on a headless wlroots backend with pixman, renders actual screenshots using `grim` and validates pixel/geometry/capture receipts. The [Creator demonstrator test](scripts/verify_wayland_creator_examples.py) exercises distinct recipes at 1024×768, 1366×768, 1920×1080 and scale 1.25.

Download the workflow artifact from GitHub to inspect the exact PNGs; it is not a proof of a physical monitor, XWayland app, or screen-reader session.

## Try it safely

The normal RiceBowl install stays on XFCE/X11. Before entering a separate preview, use:

```bash
ricebowl de check --json
ricebowl de catalog --json
# Explicit nested compositor: check prerequisites and keep XFCE available.
ricebowl de start --nested --panel native
```

For a native preview with supported quick controls, first review/import the bundled recipe and then start the nested session:

```bash
ricebowl de recipe-import --recipe "$PWD/examples/wayland/quick-controls.json"
ricebowl de start --nested --panel native --recipe quick-controls
```

For an independent login session, follow [the package review and opt-in instructions](WAYLAND_SESSION.md#build-and-opt-in-debianubuntumint). That package only adds a *selectable* session entry; it does not make Wayland the default.

**Safety:** Wi-Fi, sound, date/time and display settings are real system operations even when the settings UI is opened as a preview. Avoid disrupting your only network connection or a remote session. Display trials have a bounded rollback, but hardware validation is still required. Keep an independently working XFCE login available.

## Remaining release gates, in order

1. **Physical session:** login/logout, repeated sessions, compositor recovery, XWayland and portals, clipboard, polkit, lock/suspend and clean return to XFCE.
2. **Real input and displays:** one/two monitors, mixed DPI, hotplug, menus/tray/DBusMenu focus, pointer cross-output drag, keyboard navigation and Orca/AT-SPI.
3. **System controls:** network/audio/Bluetooth/display actions, failure states, backlight/media keys and notification actions across missing/restarting services.
4. **Creator and ecosystem:** verify two genuinely different designs, local reference comparison, import/export, explicit live apply/revert and real RiceField/Taskotto integration.
5. **Release quality:** current-HEAD CI, installer and rollback checks, performance baselines for cold start/settled PSS/CPU, sustained memory behavior, owner hardware signoff and reviewed release metadata.

**No percentage-complete claim:** Passing component tests cannot be converted honestly into a percentage of complete desktop functionality. Track explicit gates rather than guessing a release date.

[Feature-by-feature matrix](DESKTOP_ENVIRONMENT_STATUS.md) · [Detailed Wayland/Creator guide](WAYLAND_SESSION.md) · [Roadmap and evidence](RICEBOWL_DE_ROADMAP.md) · [1.0 release gates](RELEASE_1_0_GATES.md) · [Example rice recipes](examples/wayland/README.md)
