# RiceBowl on Wayland

**Experimental, opt-in preview — not a finished 1.0 desktop.** The native
Wayland environment uses upstream **labwc** for window management and
**RicePlate (Rust)** for the panel, launchers and desktop surfaces. Your
[existing XFCE/X11 desktop](X11.md) remains the supported default.

## What already works in source and headless CI

- **RicePlate:** multiple outputs, taskbar/window groups, native tab/sidebar
  menus, localized and relevance-ranked XDG application search, keyboard
  navigation, tray/DBusMenu, desktop shortcuts and widgets.
- **RiceSpice:** real NetworkManager, WirePlumber, BlueZ, display, power and
  accessibility settings with explicit actions and bounded rollback where
  supported.
- **RicePop:** notification inbox and on-screen volume/backlight feedback.
- **Recipes:** validated compositions, selected-rice previews, separate
  Wayland session entry, reversible selection and supervised fallback.

These features have **automated coverage**, including headless labwc and
XWayland interaction tests. They have not all been signed off on a real laptop.

[**See current progress and genuine Wayland screenshots**](WAYLAND_PROGRESS.md) ·
[Engineering status](DESKTOP_ENVIRONMENT_STATUS.md)

## Inspect before switching

Install the regular RiceBowl application first using the [X11 instructions](X11.md#install-on-linux-mint-xfce-or-compatible-xfcex11), or use the standalone
Wayland preview package described in the [complete installation guide](WAYLAND_SESSION.md).

From your existing desktop, check the environment **without changing it**:

```bash
ricebowl de check --json
ricebowl de catalog --json
```

Once the [Wayland prerequisites](WAYLAND_SESSION.md#prerequisites) and the
native RicePlate binary are available, an **explicit nested preview** avoids
logging out of XFCE:

```bash
ricebowl de start --nested --panel native
```

For a separate **Wayland login-session choice**, follow the
[reviewed Debian/Ubuntu/Mint installation procedure](WAYLAND_SESSION.md#build-and-opt-in-debianubuntumint).
It is not created by ordinary `bash install.sh`. Keep XFCE selectable at the
login screen; never remove the only working desktop for a preview.

## Rice Creator

`ricebowl creator` opens the experimental GTK editor. **Creator 0.9** can edit
validated RicePlate recipes, preview in isolation, compare reference images,
export RicePacks and explicitly stage/apply/restore supported Wayland changes.
It does **not** automatically convert an arbitrary screenshot into a complete
functioning desktop. [Creator and recipe workflows](WAYLAND_SESSION.md#riceplate-layout-recipes-first-data-only-contract).

## What's still required for 1.0

The remaining sign-off is primarily **on real hardware**: login/logout,
suspend and resume, device/network/audio controls, GPU/display hotplug,
mixed-DPI, input/focus, accessibility and measured idle resource use.
Inside the opt-in session, the read-only report
`ricebowl de acceptance --json` (or
`ricebowl-wayland-app de acceptance --json` with the standalone package)
helps collect evidence; it is **not** an automatic certification.

- [Full hardware acceptance checklist](WAYLAND_SESSION.md#physical-acceptance-checklist-not-yet-signed-off)
- [Release gates](RELEASE_1_0_GATES.md) · [Development roadmap](RICEBOWL_DE_ROADMAP.md)

**Real hardware or network settings can change state when you deliberately use
controls inside a preview.** Only the inspection commands above are read-only.

[**Back to project overview**](README.md) · [**XFCE/X11 instead?**](X11.md)
