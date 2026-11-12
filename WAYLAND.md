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

## RiceShot (early on-demand CLI)

Inside a running Wayland session, RiceShot can save a private PNG of the whole
desktop, one named output, or an interactively selected region:

```bash
ricebowl de shot --output "$HOME/Pictures/desktop.png"
ricebowl de shot --shot-mode output --monitor eDP-1 --output "$HOME/Pictures/laptop.png"
ricebowl de shot --shot-mode region --output "$HOME/Pictures/selection.png"
ricebowl de shot --shot-mode region --clipboard
```

`grim` is required for capture; interactive region selection additionally needs
`slurp`, and clipboard copy needs `wl-copy`. `--clipboard` and `--output` are
mutually exclusive: copying uses a temporary private PNG that is removed after
the clipboard owner accepts it. Use a **new absolute filename** when saving:
existing files and symlinks are not overwritten. `--json` returns structured
success/failure information.
Only an explicit command can capture; no background capture service or global XFCE
shortcut is installed. Clipboard content is held by the normal Wayland
selection owner until replaced. Screenshots can reveal private information.
Annotations, configurable shortcuts, portal fallback and real-device
capture acceptance are still outstanding.

In the optional RiceBowl labwc login/preview session, **Print** copies the
desktop to the clipboard and **Shift+Print** selects a region first. These
bindings use the exact same guarded CLI, require the optional tools above and
are private to that labwc configuration; other desktop sessions remain intact.
Real keyboard, clipboard and focus behavior on the ThinkPad is not yet accepted.

## RiceClip (opt-in text-history foundation)

RiceClip 0.1 offers an **explicit, foreground-only** event-driven text clipboard
watcher for the current Wayland display. It does not start with Luna or any
other rice; clipboard history is held only in the watcher's process memory.
Open a terminal inside the optional labwc session:

```bash
ricebowl de clip --clip-op watch
```

In another terminal, inspect and manage that same session's bounded history:

```bash
ricebowl de clip --clip-op status --json
ricebowl de clip --clip-op list
ricebowl de clip --clip-op gui  # GTK browser; manual refresh and preview search
ricebowl de clip --clip-op copy --clip-index 0
ricebowl de clip --clip-op pause
ricebowl de clip --clip-op resume
ricebowl de clip --clip-op clear
```

RiceClip's optional **on-demand GTK3 browser** displays only 80-character
previews (not full clipboard contents), filters those previews locally,
supports keyboard/row activation, explicit copy-back, pause/resume, manual
refresh and confirmed clearing. It **never starts the watcher implicitly**,
writes history to disk, polls in the background or claims to detect passwords.
If the watcher is not active, the window explains how to enable it. List/copy
requests carry a revision and random per-watcher identity: if new clipboard
content moves an index **or the watcher restarts**, copy-back is rejected
and the user must refresh, preventing wrong-item copies.
The older CLI `--clip-index` behavior is unchanged. Validated Wayland rice
menus and panel action components may now expose `clip-history`: a fixed
`ricebowl de clip --clip-op gui` launch with no recipe-defined commands.
The opt-in original XP-Luna sidebar and Heritage example show it, including
their labwc and Waybar fallbacks; the six-slot Luna-Columns right shelf is
deliberately unaffected. This opens the shared on-demand GTK window, **not**
a separate native RicePlate inbox. Up to **five session-only pins** can
now be marked/unmarked in the same GTK browser; pinned entries stay at the
front even as the ordinary 20-entry history rolls over. Pin mutations require
the same current watcher identity and revision as guarded copy-back; a stale
selection is refused. Pins are cleared with history and on watcher exit, never
persisted or auto-restored. Configurable retention, physical hardware input,
and a composited in-panel history view remain open.

The watcher requires `wl-paste --watch` **and** compositor support for
wlroots data-control; copy-back requires `wl-copy`. It saves at most 20 text
entries of 64 KiB each, deduplicates them, refuses non-UTF-8/oversized data,
and owns no clipboard selection until explicit copy-back. The private Unix
socket lives in the current 0700 XDG runtime directory, with owner-only
permissions; it is removed when the watcher exits. `Ctrl+C` stops collection
and drops all history. No configuration, history file, X11 settings or XFCE
shortcuts are changed.

This is **not** a sensitive-data detector or a password-manager-safe clipboard:
Wayland clipboard metadata cannot reliably identify secrets. Pause before
copying sensitive values; lock-screen clearing, image/URI capture, native
search/pin UI and per-application exclusions remain future work. Do not enable
the watcher on a shared or security-sensitive session without understanding
that it temporarily retains copied text.

## What's still required for 1.0

The remaining sign-off is primarily **on real hardware**: login/logout,
suspend and resume, device/network/audio controls, GPU/display hotplug,
mixed-DPI, input/focus, accessibility and measured idle resource use.
From a full (non-nested) RiceBowl Wayland login, use
`ricebowl performance desktop --wayland-session --samples 3 --json` for a
read-only PSS/CPU snapshot of recognized processes in that login. The default
`performance desktop` still counts all matching processes owned by your user.
The scoped report excludes missing/unreadable process environments, so it is
not a complete desktop-memory benchmark or hardware acceptance by itself.
Inside the opt-in session, the read-only report
`ricebowl de acceptance --json` (or
`ricebowl-wayland-app de acceptance --json` with the standalone package)
helps collect evidence; it is **not** an automatic certification.

RiceSpice's saved monitor arrangement can be tried as a single guarded change.
An **optional, disabled-by-default next-login trial** is also available for
full RiceBowl Wayland sessions. You must approve it in the visible confirmation
window within 18 seconds, or the prior monitor layout is restored. XFCE and
nested previews are excluded; monitor hardware still needs real-device QA.

RiceSpice also offers **next-login RicePop banner fonts and behavior**:
installed TrueType font families, bounded text size, default duration and
visible notification count. These apply only to RiceBowl's own Mako instance
in a full Wayland login, without touching your XFCE notification preferences.

- [Full hardware acceptance checklist](WAYLAND_SESSION.md#physical-acceptance-checklist-not-yet-signed-off)
- [Release gates](RELEASE_1_0_GATES.md) · [Development roadmap](RICEBOWL_DE_ROADMAP.md)

**Real hardware or network settings can change state when you deliberately use
controls inside a preview.** Only the inspection commands above are read-only.

[**Back to project overview**](README.md) · [**XFCE/X11 instead?**](X11.md)
