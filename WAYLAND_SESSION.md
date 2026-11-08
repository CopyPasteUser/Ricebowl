# RiceBowl (Wayland Preview) — first login-session track

**Experimental / opt-in.** This is an independently selectable labwc session
with an optional native RicePlate panel and a Waybar fallback, not yet a
finished RicePlate/RiceSpice/RicePop desktop. The current XFCE/X11 rice suite
and its backups stay intact.
Mint 22/Ubuntu 24.04's labwc **0.7.1** is supported by using its
`--startup` command and requesting compositor exit when the shell finishes.

## Prerequisites

- Linux display manager that enumerates `/usr/share/wayland-sessions`
  (check your specific login manager on the actual computer).
- User-local RiceBowl already installed with `bash install.sh`.
- `labwc`, `waybar`, `foot`, `fuzzel`, `swaylock`, a proper logind
  `XDG_RUNTIME_DIR` and D-Bus user session.
- `xdg-desktop-portal`, GTK and wlroots portal backends for file pickers
  and screencast; `xwayland` for legacy X11 clients.
- Optional: `swaybg` wallpaper, `swayidle` idle lock, `mako`
  notifications and an installed user polkit agent.

The package only installs the session chooser, a small forwarding wrapper,
RiceBowl-specific portal preferences and a namespaced systemd user target.
It **does not install RiceBowl itself**, overwrite `~/.config/labwc`, edit
global XFCE configuration or set the default session.

The preview `.deb` builder normalizes filesystem/archive timestamps and
supports the standard `SOURCE_DATE_EPOCH` override. Run
`sh scripts/test_wayland_package_reproducibility.sh` to verify that two builds
at different wall-clock times are byte-for-byte identical. This verifies the
small **session-entry package**, not a complete RiceBowl 1.0 application bundle.

## Build and opt in (Debian/Ubuntu/Mint)

From the current RiceBowl checkout:

```bash
bash install.sh --dry-run
bash install.sh
ricebowl de check --json
sh scripts/build_wayland_session_deb.sh
```

Review the package before installing:

```bash
dpkg-deb --contents dist/ricebowl-wayland-session_0.1.0~preview1_all.deb
sudo apt install ./dist/ricebowl-wayland-session_0.1.0~preview1_all.deb
```

Log out. In the login manager's session selector, choose
**RiceBowl (Wayland Preview)**. Your existing XFCE session remains an
independent choice. If the entry is not shown, use the current XFCE session
and inspect the display manager's session-directory support before changing
system settings.

**Nothing in the ordinary `bash install.sh` enables this session.** Do not
install the preview package on a production-only machine without keeping a
working alternative login/session available.

### Nested developer test

From another desktop, `ricebowl de start --nested` explicitly launches a
separate compositor with activation-environment updates disabled, so it
doesn't hijack the current desktop's D-Bus/systemd Wayland variables.
The compositor still requires hardware/driver support for a nested backend.

### RiceSpice settings preview

`ricebowl de settings` opens a **standalone GTK3 window on demand**, with
keyboard-focusable navigation for Network, Sound, Bluetooth, Displays, Input,
Accessibility, Date & Time, Power & Security, and Rice & Appearance. It is
also available as a fixed `settings` action in schema-v4/v5 native menus, e.g.
the bundled `quick-controls` example. It never starts at login by default.

Network, audio and Bluetooth controls query the actual NetworkManager,
PulseAudio-compatible sound server and BlueZ; changes are explicitly selected,
bounded and verified, and may still require authorization. Suspend requests
use logind after confirmation; **nested preview sessions disable suspend**.
The appearance page only selects a rice for the *next* Wayland login. Missing
services and unverified operations show an error. Date/time offers a native,
searchable system-timezone selector and explicit automatic time synchronization
toggle through timedated (system-wide, authorization required). When NTP is off,
the page also offers a confirmed `YYYY-MM-DD HH:MM:SS` local system-clock editor;
incorrect system time can disrupt TLS, login and logging, so test carefully.

**Displays** reads actual active wlroots outputs using `wlr-randr`. It offers
only advertised modes, conservative scale options and bounded X/Y positions. Every trial starts an
independent 18-second rollback helper; click **Keep these display settings**
while the display is usable or the original values are restored even if the
RiceSpice window crashes. An owner-private `ricespice-displays.json` layout
can be saved, forgotten or restored **one display at a time**, each through a
new guarded trial. It is not auto-applied at login to avoid lockout when docks
and displays change. Enabling/disabling outputs is intentionally unsupported;
running from XFCE shows an optional installed external editor instead.

**Input** stores bounded pointer speed, natural scrolling, touchpad tap-to-click
and keyboard-repeat choices in a private `~/.config/ricebowl/ricespice.json`
(`XDG_CONFIG_HOME` respected). The next opt-in labwc session copies its XML
into a private temporary session directory and applies these values; it does
not edit `~/.config/labwc` or XFCE. **Accessibility** offers cursor size and
GTK text scaling or a high-contrast GTK theme at the next RiceBowl login.
Cursor-theme support varies; Qt/Electron applications and RicePlate are not
scaled by GTK settings. You can also request startup of installed **Orca**;
RiceBowl supervises it only in a full, non-nested opt-in session. This does
also enable an **AccessKit/AT-SPI bridge within the native RicePlate panel**:
the visible panel, task groups, menu, desktop shortcuts, calendar,
notifications and system tray expose named nodes, real focus and safe actions.
Actions are handled on RicePlate's existing Wayland event thread. It does
**not** install Orca or provide a magnifier; actual screenreader focus and
multi-monitor assistive-technology behavior still require physical QA.
Legacy private preference JSON migrates to v2.
The X11/XFCE desktop never receives the new display/input preferences.
The network page also provides an enterprise WLAN profile form for
PEAP/MSCHAPv2 and TTLS/PAP or TTLS/MSCHAPv2: enter the real Wi-Fi SSID,
network username and **administrator-confirmed authentication-server domain**.
The system trust store (or an explicit CA certificate) must validate the
server; RiceSpice does not offer an unsafe bypass. Creating the profile does
not activate it. Use **Connect with 802.1X password** to supply a one-time
password to NetworkManager via `passwd-file /dev/stdin`; it is not placed
in process arguments or the RiceSpice configuration. The UI can import an
existing `.ovpn` OpenVPN or `.conf` WireGuard file with autoconnect disabled.
For EAP-TLS client certificates or uncommon provider-specific VPN settings,
use the system NetworkManager connection editor. The sound page exposes active per-application output,
volume and mute with stale-state verification; streams that disappear during
the request must be refreshed.
Hardware and assistive-technology testing is still necessary. Do not change
network, Bluetooth or power settings during an important remote session.

On the dedicated Wayland/Orca acceptance run: enable Screen reader in
RiceSpice Accessibility, log out/in to the *native* RicePlate session and
verify Orca announces the launcher, task buttons, tray/overflow context
menus, grouped menu actions, calendar days and notifications. Check Tab,
Arrow, Return, Escape, selected/focus changes, closing/reopening dialogs,
and moving between two outputs without duplicate/stale announcements.
Check that disabling the preference or starting a nested preview does not
start a background AT-SPI bridge. For Enterprise Wi-Fi, test valid CA/server
names, rejected fake certificates, incorrect passwords, network loss,
profile reactivation after relogin and VPN import on supported NetworkManager
plugins; do not run network-disruption tests over the only remote connection.

RicePop audio OSD: in a **full native RicePlate/labwc** login, press the
keyboard's volume-up, volume-down and mute keys. The *private* labwc `rc.xml`
binds them to `wpctl` and, when `pactl subscribe` is available, RicePop observes
the changed default sink from PulseAudio/PipeWire compatibility notifications.
The existing transient OSD uses an actual post-event `wpctl` readback and
does not consume pointer input. Also change the default sink through pavucontrol
or another mixer and confirm that the OSD updates, repeated unchanged states
do not flash, and per-application stream-volume changes do not trigger it.
Repeat with no `pactl`, unavailable default sink, suspend/resume and a restarted
Pulse/PipeWire service; the monitor currently requires relogin after its
subscriber process exits. XFCE/X11 and global labwc keybindings must remain
unchanged. Nested previews intentionally do not spawn the event subscriber.

Manual RiceSpice acceptance before 1.0:

1. In XFCE, open `ricebowl de settings`: Displays must not attempt any
   `wlr-randr` write. Verify that saving Input does not modify XFCE or
   `~/.config/labwc` and that Accessibility alone does not override input.
2. In a nested RiceBowl Wayland preview, inspect an active output. Try a
   different advertised mode/scale/position; **do not confirm** and verify the original
   state returns after 18 seconds. Repeat while closing RiceSpice during the
   trial, then test explicit confirmation. Save a layout preset and try to
   restore it; each output must require a new confirmation. Verify unavailable/
   disconnected outputs cannot be selected, and try real mixed-DPI/hotplug hardware.
3. Set touchpad speed/tap and keyboard repeat, log out and back into the
   opt-in RiceBowl session, verify the real device behavior, then use the
   **Restore inherited settings** button and re-test. Compare with XFCE.
4. Verify cursor size/text scaling/high contrast with installed GTK themes.
   Enable Orca only in a full RiceBowl session; verify reader launch, clean
   shutdown, native RicePlate gaps and keyboard navigation separately.
5. Check that NTP reflects timedated's actual state. With authorization,
   toggle it and verify the readback; test denial and unavailable-service
   states without claiming success. Only after saving/restoring correct time,
   test the manual clock editor with NTP disabled, including invalid dates.
   **These changes affect the whole system.**
6. Connect/disconnect a saved Ethernet, VPN and enterprise Wi-Fi profile only
   from a safe physical console; verify readback, timeout and permission denial.
   Confirm the external editor handles credentials without leaking them.
7. Start audio in two programs and move/mute/change volume on one stream;
   verify the other is unaffected. Unplug an audio sink while RiceSpice is open,
   then verify stale operations report errors and the active session survives.

### RicePlate layout recipes (first data-only contract)

The experimental Waybar adapter can render two structurally different,
declarative RicePlate panel layouts without starting a second panel or
modifying your live desktop configuration:

```bash
ricebowl de recipes
ricebowl de start --nested --recipe classic
ricebowl de start --nested --recipe chrome
```

For offline authoring agents and mockup-to-rice experiments, the **read-only,
versioned shell component catalog** describes what the current native and
Waybar backends actually implement:

```bash
ricebowl de catalog --json
```

The versioned `catalog_version` (currently **6**) identifies the response format, while
`recipe.schema_versions` (currently **1, 2, 3, 4, 5**) identifies supported recipe versions. Each
panel widget has a known ID, real backend support level, fixed behavior and
keyboard-availability flag. The `shell_components` collection separately
describes native menu, output-bound calendar and desktop shortcut actions,
pointer/keyboard support, output ownership and known limitations. It does not
claim that the clock can be opened from a keyboard-only panel focus or that
desktop icons migrate between outputs. Unsupported functionality is reported explicitly
instead of presenting an imaginary action or widget. This catalog never reads
private desktop state, invokes a model or changes a rice. The cross-command
Creator inventory is available through `ricebowl de creator-api --json`.

The next read-only Creator building block validates one recipe and optionally
compares it with a bundled, imported or owner-private base recipe:

```bash
ricebowl de review --recipe classic --json
ricebowl de review --recipe /absolute/path/to/my-rice.json --compare chrome --json
```

`review_version: 1` describes a versioned JSON response (panel-only for v1–v3,
initial shell components for v4 and opt-in desktop icons for v5) with `ok`,
`applied: false`, a normalized `recipe`, a `summary`, and an optional
`comparison`. The summary includes an SHA-256 of the **normalized recipe
semantics** (not of the source file's bytes), native-unavailable widgets and
whether full widget support still requires Waybar. The comparison reports a
stable list of JSON Pointer paths and old/new values, including absent v1
metrics versus v2 metric defaults. Source file locations are not echoed.
Whitespace/key ordering changes do not affect the semantic fingerprint.

Exit status is `0` for a valid review, `2` for an invalid/inaccessible recipe
when `--json` is requested (a fixed, path-free `invalid_recipe` JSON response),
and `1` for rejected command flags or ordinary human-readable recipe errors.
The review never launches labwc, probes live hardware, writes a draft or
changes an active/next-login rice. It is **not** a rendered preview, image
comparison, complete RicePack validator or guarantee of functional parity.

#### Offline Creator component edits (experimental)

Agents can now read `ricebowl de catalog --json` and use the
`authoring.draft_edit` contract to build a **new panel draft** from actual
supported components. The contract publishes editable JSON Pointer paths,
limits, an explicit `set` operation and an example against `classic`.

For example, save this data as `/absolute/path/panel-edits.json` (an
owner-controlled regular `.json` file, not group/world writable):

```json
{
  "edit_version": 1,
  "operations": [
    {"op": "set", "path": "/panel/height", "value": 44},
    {"op": "set", "path": "/panel/sections/start", "value": ["launcher"]},
    {"op": "set", "path": "/panel/sections/center", "value": ["tasks"]}
  ]
}
```

Then validate and create a **new** private runtime-compatible JSON recipe:

```bash
ricebowl de recipe-init --base classic --id my-panel --name "My Panel" \
  --output /absolute/path/my-panel-base.json
ricebowl de draft-edit --recipe /absolute/path/my-panel-base.json \
  --edit /absolute/path/panel-edits.json \
  --output /absolute/path/my-panel-draft.json --json
ricebowl de review --recipe /absolute/path/my-panel-draft.json \
  --compare /absolute/path/my-panel-base.json --json
ricebowl de start --nested --recipe /absolute/path/my-panel-draft.json
```

The editor supports only validated panel property changes: name, panel edge,
height, schema-v1/v2 `start`/`center`/`end` widget lists, schema-v3 typed
`panel.layout` regions, hex colors and schema-v2/v3/v4 widget widths. Schema
v4 additionally offers explicit menu, wallpaper, design-token and responsive
editing paths.
IDs/schema versions are immutable; use `recipe-init` to create
a fresh identity or v2/v3/v4 template. A draft made directly from `classic` remains
identified as `classic` and can be previewed by absolute path, but cannot be
imported over the reserved built-in ID. At most 16 `set` operations and 16 KiB of
edit data are accepted; duplicate paths, unknown components, scripts, external
assets, unsupported actions and no-op edits are rejected. The destination
must not exist; the new file is created with mode `0600` without overwriting
the source. `--json` uses exit `0` for success, `2` for validation/creation
failure with a structured error code and (only for allowlisted properties)
a JSON Pointer diagnostic, and `1` for invalid flags. Errors never echo
private source/output paths, arbitrary edit values or executable content.

Neither the active session nor its next-login selection changes; actual visual
inspection is still a separate nested labwc step. These are reusable **panel
components only**. Menu, desktop, notification, settings and full RicePack
composition still need their respective native components and schemas.

#### Nested panel layouts (schema v3)

For AI-assisted building from an OS screenshot or generated mockup, schema v3
adds genuine **horizontal nested composition** to the panel recipe instead of
only rearranging a flat widget list. It is opt-in; existing v1/v2 recipes are
still accepted unchanged. Start with a private template:

```bash
ricebowl de recipe-init --schema-version 3 --base classic \
  --id y2k-panel --name "Y2K panel" --output "$HOME/y2k-panel.json"
ricebowl de catalog --json
```

Replace `panel.layout` in the new JSON with the example below (preserve the
generated `id`, `name`, `colors` and `panel.metrics`):

```json
"layout": {
  "start": [{"type": "group", "gap": 8, "children": [
    {"type": "widget", "id": "launcher"},
    {"type": "label", "text": "Y2K"},
    {"type": "gap", "width": 20},
    {"type": "widget", "id": "tasks"}
  ]}],
  "center": [],
  "end": [{"type": "widget", "id": "clock"}]
}
```

Run `ricebowl de review --recipe "$HOME/y2k-panel.json" --json` to validate
and inspect its normalized structure, then `ricebowl de start --nested
--recipe "$HOME/y2k-panel.json"` for Waybar or add `--panel native` for the
experimental native Rust panel. For agent edits, the `draft-edit` operation
`set /panel/layout/start` (or `center`/`end`) accepts a replacement list of
typed nodes; edits are validated, saved to a **new private file** and never
automatically applied.

Every node has an exact type and fields, with no CSS, commands, action strings
or remote assets. `widget` uses a unique existing ID from the catalog. `group`
has 1–6 children, gap 0–32 logical pixels and can nest at most three levels
total. A `gap` has width 4–64; a noninteractive `label` allows 1–24 safe ASCII
characters (`A–Z`, `a–z`, digits, spaces, `._:+-`). Limits are 24 typed nodes,
8 labels and 8 root nodes per panel region. Widget IDs cannot be duplicated,
and either a launcher or task list is required. The native panel currently
renders launcher, tasks, clock, read-only battery/network/audio labels, and
static labels/spacing; the system tray remains **Waybar-only**. NetworkManager
(`nmcli`) and WirePlumber (`wpctl`) are sampled by one bounded worker thread
only when the active recipe includes their widgets. Unavailable services are
shown as `N/A`, not as connected or working. Their refresh interval is 30
seconds, without a second background service or blocking Wayland input.
Native battery state comes from
Linux sysfs once per minute, displays `N/A` when absent and yields space to
overflowed task groups. No power control or UPower subscription is implied.
Waybar uses GTK/CSS minimum widths,
so the visual pixel result can differ from Rust's fixed geometry. Grouping is
horizontal and panel-only, without flex/grid, responsiveness, generic content
containers, custom actions or AI running inside the desktop.

The shared real-backend example is
[`tests/fixtures/riceplate-nested-v3.json`](tests/fixtures/riceplate-nested-v3.json).
The native Rust tests assert geometry and click behavior for it, and the native
CI exercises its start inside headless labwc. A physical GPU/display and
multi-resolution visual QA still require separate acceptance.

#### Schema-v4 shell composition preview

For the first **multi-region** mockup-to-desktop authoring slice, use the v4
template rather than writing scripts or altering labwc/Waybar files yourself:

```bash
ricebowl de recipe-init --schema-version 4 --base classic \
  --id my-shell --name "My Shell" --output "$HOME/my-shell.json"
ricebowl de review --recipe "$HOME/my-shell.json" --json
ricebowl de start --nested --recipe "$HOME/my-shell.json"
```

Schema v4 retains v3 `panel.layout`, widths and colors, and adds four strictly
required, typed objects:

| Section | Runtime behavior | Bounds / limits |
| --- | --- | --- |
| `menu` | Generates a genuine **labwc root context menu** in an isolated private per-session config; action IDs map to fixed `fuzzel`, `foot`, `swaylock -f` or labwc Exit | 1–4 groups, 1–4 unique actions each, short ASCII labels; no commands in recipes |
| `desktop.wallpaper` | Selects bundled artwork, or in schema v6 a previously imported private PNG for `swaybg` | Bundled IDs or `asset-<sha256>`; never a recipe-supplied path or URL |
| `tokens` | `label_padding` changes native text geometry / Waybar CSS; `task_radius` changes native active task backgrounds / Waybar CSS | Integer 0–16 and 0–12 logical px respectively |
| `responsive` | `compact_layout` replaces the full panel layout at or below `compact_max_width` **live in native Rust** | Breakpoint 480–1440, same strict nested node limits; Waybar only supports explicit width-dependent offline generation |

All fields can be edited through the existing safe `de draft-edit` workflow,
with `/menu/title`, `/menu/groups`, `/desktop/wallpaper`, `/tokens/...` and
`/responsive/...` JSON Pointer paths. `de catalog --json` advertises exact
supported actions, wallpapers and backend limitations. The canonical example
[`tests/fixtures/riceplate-shell-v4.json`](tests/fixtures/riceplate-shell-v4.json)
is consumed by Python and the native Rust renderer's geometry tests and is
started in headless labwc CI. The existing login and XFCE defaults are never
replaced; temporary compositor menu files are removed on normal shutdown.

**Honest boundary:** This is a functional context menu and background, not
yet a visually configurable Windows-style Start menu. Original mockups cannot
be automatically converted into working control backends. Waybar does not
currently recompile its compact variant when the display is resized; the
native panel selects it during layout.

#### Schema-v5 native desktop icons preview

Schema v5 adds an optional *preview feature*, required when using that schema:
`desktop.icons`. Each entry contains only `label`, `action`, `x` and `y`.
There are 1–8 icons, labels contain 1–12 safe ASCII characters, coordinates
are bounded (`x`: 0–4096, `y`: 72–4096), and their 104×88 logical-pixel hit
areas must not overlap. Actions are fixed IDs: `applications`, `terminal`,
`lock` (mapped respectively to `fuzzel`, `foot`, `swaylock -f`). No arbitrary
commands or filesystem links are accepted.

```bash
ricebowl de recipe-init --schema-version 5 --base classic \
  --id my-desktop --name "My Desktop" --output "$HOME/my-desktop.json"
ricebowl de review --recipe "$HOME/my-desktop.json" --json
ricebowl de start --nested --panel native --recipe "$HOME/my-desktop.json"
```

The [shared fixture](tests/fixtures/riceplate-desktop-v5.json) shows the exact
JSON shape. `/desktop/icons` is available for `de draft-edit` and visible in
semantic `de review` comparisons. RicePlate draws each icon as a small
transparent Wayland Bottom-layer surface in its **existing process**; it does
not cover the desktop with a giant input window. The ordinary Waybar fallback
still renders the panel, menu and wallpaper but **does not show icons**. This
preview supports click-to-launch, dragging a shortcut with the left button,
and an on-demand keyboard focus frame: click to focus, use arrow keys to move
in 16-pixel steps, or Enter/Space to launch. RicePlate stores positions per
rice in `$XDG_CONFIG_HOME/ricebowl/native-icon-positions/<rice-id>.json`
(typically `~/.config/ricebowl/native-icon-positions/`) without altering the
original recipe. Saved coordinates are private and never honored by nested
Creator/headless sessions, so screenshots remain reproducible. Desktop widgets,
independent multi-output ownership and real-GPU/input acceptance remain open.
Native RicePlate **reflows shortcuts within its selected logical
output** on mode/scale changes, preserving valid positions and parking icons
outside the output when no safe, non-overlapping hit area exists. This placement is not persisted;
fractional-scale visual quality and multi-monitor hotplug still need device
acceptance. Do not treat it as a finished desktop.

The default **Waybar-backed** Wayland session is separately checked in CI
with two genuine labwc headless outputs. The smoke captures the bar on each,
turns one output off, checks the remaining bar and reconnects the second.
This verifies fallback display/hotplug behavior, **not** multi-monitor native
RicePlate parity or physical mixed-DPI hardware acceptance.

An additional experimental native RicePlate track now draws a
separate taskbar layer on each connected output **inside the same process**,
while sharing window discovery and the event-driven clock. Secondary panels
use independent task paging. Click a panel to give it keyboard focus, then
use Left/Right or Tab to move between its launcher and window groups, Enter
or Space to activate, and Escape to clear its focus selection. The focused
group is visibly outlined and automatically paged into view on that output;
this is a first keyboard pathway, not screen-reader or device signoff.
Native desktop icons still belong to the primary output. For schema-v4/v5
recipes each secondary launcher now opens its own native menu on that output;
recipes without a native menu keep the accessible fuzzel picker. Only one
menu is visible at a time, and unplugging the owning output closes it instead
of teleporting it to another screen.
Every **native panel clock now opens a functional calendar on its own output**.
Only one popup is visible at a time; the other outputs remain unobstructed.
Choose months
with the previous/next controls, select a date or return with **Today**;
arrow keys move between days, PageUp/PageDown switch months and Escape closes
the popup. Dates come from the local system clock (no extra daemon).
Calendars on secondary outputs are separate Wayland layers in the existing
RicePlate process; losing an output closes its calendar without moving it to
the surviving display. The `--preview-calendar` native flag is intended for
headless labwc CI (the shown dates follow its local clock), not for a full
desktop release. CI sets `RICEBOWL_DE_CALENDAR_OUTPUT=secondary` inside an
isolated nested session to exercise the secondary-calendar preview.
The `smoke_riceplate_multioutput.sh` CI test verifies two native panel frames
and a secondary disconnect/reconnect, plus output-bound calendar screenshot
proof, a secondary native-menu screenshot and popup cleanup after hotplug.
Genuine compositor screenshots are
included in the `riceplate-native-preview` workflow artifact. Actual mixed-DPI,
primary-output removal, and keyboard/menu parity on secondary screens remain
open acceptance items.

#### Native start menu and keyboard preview

For schema-v4/v5 recipes the experimental native panel now draws its **own
start menu in the same Rust process**, using the recipe's actual grouped menu
title and validated action IDs. Click the panel's `Apps` button to toggle it.
Use **Left/Right** to switch groups, **Up/Down/Tab** to select an action,
**Enter** to activate, **type** to search the validated action labels across
groups, **Backspace** to edit the search, **F2** to save/remove the selected
action, **F3** to toggle the saved-action view, and **Escape** to return to
groups or dismiss. Search input is restricted to 24 ASCII characters and the
four visible action rows scroll to follow keyboard selection. Mouse tabs, rows and close
control have the same action mapping. The menu requests Wayland keyboard focus
only while open; it is parked outside the output and noninteractive while
closed. The legacy labwc root menu remains a recovery path.

Actions are strictly the existing known Linux bindings: fuzzel applications,
foot terminal, swaylock lock, and labwc's own `--exit` for logout **only when
the compositor supplied a valid `LABWC_PID`**. Otherwise the logout row shows
`unavailable` and cannot terminate an unrelated desktop session. Missing
optional programs emit an error rather than inventing a working control.
Logout is also disabled inside nested Creator previews, even if the caller
inherited an outer compositor's `LABWC_PID`.

The visual QA flag `riceplate-native --recipe /absolute/private.json
--preview-menu` opens the menu on startup; normal use never does. CI captures
an actual `menu-v5.png` from headless labwc and verifies it differs from the
closed-menu framebuffer. Favorites are limited to eight prevalidated fixed
actions, stored atomically in an owner-private
`$XDG_CONFIG_HOME/ricebowl/native-menu-pins/<rice-id>.json` (or
`~/.config/ricebowl/native-menu-pins/`), never added to recipes or used to
execute arbitrary commands. Nested Creator previews neither load nor write
these overrides. Unsafe, symlinked, stale or malformed files are ignored with
a diagnostic. These capabilities apply to the **native RicePlate menu only**;
the labwc/Waybar fallback does not offer the same search/pins UI. Dynamic
installed-app search, arbitrary layout composition, rich app icons, custom
typography, assistive-technology validation and physical multi-monitor
keyboard/navigation acceptance remain open.

For **real** Wayland screenshots, install `grim` and explicitly invoke the
Creator capture command **inside the Wayland compositor you want to inspect**:

```bash
ricebowl de capture --output "$HOME/riceplate-actual.png" --json
ricebowl de visual-compare \
  --reference "$HOME/reference.png" --actual "$HOME/riceplate-actual.png" --json
```

`de capture` is a versioned, on-demand Creator endpoint (discoverable via
`de catalog --json`) which captures the **current** Wayland desktop, not a
newly launched or automatically isolated preview. Its screenshot can include
private windows; never share captures without reviewing them. It writes a
new owner-private PNG, refuses to overwrite files or symlinks and reports
actual dimensions and SHA-256. The legacy manual helper
`scripts/capture_wayland_panel.sh` also remains available. Comparison requires Pillow and
outputs JSON dimensions, mean RGB pixel error and the fraction of changed
pixels, not a made-up fidelity percentage. The native CI also captures a
**genuine headless labwc screenshot** in its downloadable preview artifact.
For reproducible screenshots **without an active Wayland login** (and without
touching any current desktop), install `labwc`, `wlr-randr`, `grim`, `swaybg`
and the experimental `riceplate-native` binary, then run as a normal user:

```bash
ricebowl de render --recipe classic \
  --output "$HOME/riceplate-isolated.png" \
  --width 1024 --height 768 --scale 1.0 --json
```

This starts a temporary headless compositor (Pixman), renders the requested
validated rice with native RicePlate and a bundled wallpaper, captures it,
and stops the session automatically. A new private PNG is published only on
success. `--scale` accepts 1, 1.25, 1.5 or 2. This is a rendering aid, **not**
proof of interactive correctness, visual similarity or real-GPU compatibility.
For schema-v5 rices the **optional region inspection** also locates the real
panel, remaining desktop and individual icon hit areas. It identifies clipped
icons or icons colliding with the panel; this describes geometry, not whether
the compositor successfully drew or activated each control. To obtain private
no-overwrite visual diagnostics:

```bash
ricebowl de visual-compare \
  --reference "$HOME/reference.png" \
  --actual "$HOME/riceplate-actual.png" \
  --recipe "$HOME/my-desktop.json" \
  --overlay "$HOME/compare-overlay.png" \
  --heatmap "$HOME/compare-heatmap.png" --json
```

The on-demand Creator CLI emits a versioned machine-readable result with
overall and per-region RGB errors plus a recipe fingerprint. The legacy
`scripts/compare_wayland_captures.py` standalone command remains available
and uses **the same comparison engine**. The overlay blends the original captures; the red
heatmap amplifies changed pixels. Both outputs are new, private `0600` files,
and the source images and recipe are never modified. Reference and actual
must have the same dimensions, be PNG and fit the 16-megapixel safety bound.

For font and antialiasing jitter, `--tolerance-radius 1` (or at most `2`)
adds **separate** metrics that ignore bounded local RGB shifts *in both
directions*; the original raw pixel score is always preserved. A tolerance
radius is not a perceptual score and does not certify functional fidelity.
`--tolerant-heatmap /absolute/new.png` saves only the remaining differences.
After reviewing a known-good real screenshot, you can explicitly create a
private, versioned QA baseline pinned to its PNG SHA-256, recipe semantic
fingerprint and exact image size:

```bash
ricebowl de visual-baseline \
  --reference "$HOME/reference.png" --recipe "$HOME/my-desktop.json" \
  --output "$HOME/my-desktop-baseline.json" \
  --tolerance-radius 1 --threshold 24 --max-changed-ratio 0.01 \
  --approve-reference --json
ricebowl de visual-compare \
  --reference "$HOME/reference.png" --actual "$HOME/riceplate-actual.png" \
  --recipe "$HOME/my-desktop.json" --baseline "$HOME/my-desktop-baseline.json" \
  --tolerant-heatmap "$HOME/remaining-differences.png" --json
```

The second command exits `0` on a passing image-and-layout gate, `3` when
the captured image exceeds the approved difference limit or icons collide
with a panel, and `2` on malformed, changed, wrong-size or mismatched inputs.
The baseline's tolerance overrides normal comparison defaults; it cannot be
overridden while gating. A reference or recipe change requires a **new human
approval**, not silent baseline updates. These gates should run at every
target resolution/scale with a separately approved reference. They cannot
replace keyboard, live-action, assistive-technology or actual-device tests.

Native CI now captures the *same running shell* at 1024×768, 1366×768 and
1920×1080 plus a 1.25-scale case. The downloadable build artifact includes
the actual compositor PNGs and a `capture-manifest.json` with hashes, recipe,
scale and inspected geometry. A self-comparison in CI checks only geometry;
it is **not** a similarity score or a replacement for a manually approved
reference. A user-approved baseline gate is now available separately; no
golden screenshots have been automatically approved. Real-hardware mixed-DPI,
multi-output, visual fidelity and functional keyboard QA remain open.

#### Portable Wayland RicePacks and Creator API (experimental)

For experimental **Wayland RicePop diagnostics**, run
`ricebowl de notifications --json` explicitly inside the opt-in labwc session.
It queries the existing optional Mako host for current notifications and its
history. The JSON can contain private message bodies: handle it like a
personal screenshot, and do not paste it publicly. If Mako is absent or not
running, the command returns an explicit unavailable error. It never starts a
notification daemon, invokes saved notification actions or modifies history.
This is a read-only Creator integration, not a finished on-screen center.

Discover the implemented authoring operations, required flags, safe effects,
versioned output and their limits without launching a model or a daemon:

```bash
ricebowl de creator-api --json
ricebowl de catalog --json
```

The **Wayland RicePack v2** is a reproducible, local `.ricepack` ZIP with exactly
`ricepack.json` (format version, recipe identity, SHA-256 checksums and declared
provenance) and `recipe.json` (canonical schema-v1–v5 recipe). There is no
unpacking arbitrary archive paths or executing commands. Existing *bundled*
wallpapers are referenced by known IDs only. V2 records their exact SHA-256.
**V3** additionally carries one locally imported PNG wallpaper as the exact
third entry `assets/wallpaper.png` for a schema-v6 recipe. Its SHA-256-derived
`asset-…` ID is verified on import and runtime resolution, and the image is
stored separately as a private `0600` file. Other artwork, fonts, icons,
commands and scripts are not supported. Older v1/v2 packs remain readable;
exports with only bundled artwork retain deterministic v2 bytes.

To create a portable rice with an **original or properly licensed PNG**:

```bash
ricebowl de asset-import --asset /absolute/path/my-wallpaper.png --json
# Copy asset_id from the output into desktop.wallpaper in the new JSON.
ricebowl de recipe-init --base classic --schema-version 6 \
  --id my-rice --name "My Rice" --output "$HOME/my-rice.json"
ricebowl de review --recipe "$HOME/my-rice.json" --json
ricebowl de pack-export --recipe "$HOME/my-rice.json" \
  --output "$HOME/my-rice.ricepack" --json
```

Only owner-controlled regular PNG files up to 2 MiB, with verified checksums
and bounded dimensions, are accepted. Private storage is
`$XDG_CONFIG_HOME/ricebowl/wallpapers/` (or `~/.config/ricebowl/wallpapers/`).
Importing never selects or applies a rice.

```bash
ricebowl de pack-export --recipe /absolute/path/my-rice.json \
  --output /absolute/path/my-rice.ricepack --json
ricebowl de pack-inspect --package /absolute/path/my-rice.ricepack --json
ricebowl de pack-import --package /absolute/path/my-rice.ricepack --json
ricebowl de review --recipe my-rice --json
```

Export optionally accepts `--metadata /absolute/path/provenance.json` with
this exact, owner-controlled JSON object:

```json
{
  "author": "Your name",
  "license": "CC0-1.0",
  "origin": "ai-assisted",
  "source_reference": "My original local design",
  "wallpaper_provenance": {
    "author": "Wallpaper artist", "license": "CC-BY-4.0",
    "origin": "original", "source_reference": "My own painting"
  }
}
```

Accepted licenses are `unspecified`, `CC0-1.0`, `CC-BY-4.0`, `MIT` and
`custom`; origins are `unspecified`, `original`, `ai-assisted` and `adapted`.
The optional `wallpaper_provenance` has those same four bounded fields. These
are declarations by the exporter, not externally verified license evidence. Without
explicit metadata, the package says `unspecified`; it never fabricates a
license or creator. V3 supports one user-declared PNG, but no third-party icons/fonts or rendered
preview yet, and is distinct from the earlier **XFCE Riceware v2 `.zip`**
format documented in [RICEPACK_SPEC.md](RICEPACK_SPEC.md).

The archive limit is 3 MiB including a possible PNG, recipes stay within 64 KiB and JSON is strictly
validated. Import refuses unknown archive entries, symlinks, compression,
corruption, duplicate names, hash mismatches, executable fields, reserved IDs
and collisions with previously imported recipes. It installs **only** an
owner-private `0600` JSON recipe and optional content-addressed PNG, without selecting it for the next login or
changing the active desktop. Export never overwrites files; the archive bytes
are deterministic for the same recipe and metadata. Invalid pack input returns
JSON with `ok: false`, a path-free error code and exit status `2` when
`--json` is supplied; invalid flags exit `1`. All commands work offline.

#### Reviewed next-login staging (no live switch)

After importing and previewing a recipe, Creator can require a semantic
fingerprint match before staging it for the **next** opt-in Wayland login:

```bash
ricebowl de creator-status --json
ricebowl de review --recipe my-rice --json
# Copy summary.semantic_sha256 from the review JSON into the command below:
ricebowl de creator-stage --recipe my-rice \
  --expect-sha256 64_LOWERCASE_HEX_CHARACTERS --expect-active classic --json
ricebowl de creator-status --json
# To undo that future-login preference (without starting a session):
ricebowl de creator-rollback --expect-active my-rice --json
```

`--expect-active` is an optional concurrency guard: if the next-login
selection has changed since review, no new preference is committed. The
required `--expect-sha256` is checked against the actual validated recipe
**under the selection lock**. Creator saves that fingerprint in a compatible
selection-state v2 record; at Wayland login, a changed recipe fails the
fingerprint check and RiceBowl falls back to `classic`. Old v1 selections
continue to work, and the previous next-login selection can be restored once.
The recipe file itself is not made immutable, and this is *not* live apply,
full multi-component transaction/rollback or protection against a malicious
process with the same user's permissions. These commands never switch the
current Wayland or XFCE desktop, nor launch a Creator daemon.

`de creator-status`, `de creator-stage` and `de creator-rollback` support
stable JSON responses (`stage_version: 1`), exit `0` for success, `2` for
failed safe operations, and `1` for invalid command flags. Error responses
do not expose private file paths or recipe contents.

#### Existing recipe creation, import/export and selection

Custom recipes use the strict JSON schema illustrated in
`macrice/de/resources/recipes/`. Supply an **absolute path** to an owner-only,
regular JSON file (`chmod 600 YOUR_FILE.json`). Recipes are limited to 64 KiB,
known panel widgets and six-digit colors. They cannot run commands, import CSS,
load assets or define new system actions. Temporary Waybar configurations are
created under the private `XDG_RUNTIME_DIR` and removed at session exit.

To create a rice without editing an installed/bundled recipe, choose your own
absolute JSON location (in an existing directory):

```bash
ricebowl de recipe-init --base chrome --id my-rice --name "My Rice" \
  --output "$HOME/my-rice.json"
ricebowl de recipes --recipe "$HOME/my-rice.json" --json
ricebowl de start --nested --recipe "$HOME/my-rice.json"
```

To exchange this **panel-only** recipe offline, import its JSON into the
user-private collection (without changing your active desktop), then use its
ID in either panel preview mode:

```bash
ricebowl de recipe-import --recipe "$HOME/my-rice.json"
ricebowl de recipes --json
ricebowl de start --nested --panel native --recipe my-rice
ricebowl de recipe-export --recipe my-rice --output "$HOME/my-rice-share.json"
```

Choose which validated panel recipe the **next opt-in Wayland login** uses,
without restarting or changing the current desktop:

```bash
ricebowl de recipe-select --recipe my-rice
ricebowl de recipe-current --json
ricebowl de recipe-restore   # One-level undo for the next login
```

To share the *appearance* of a validated RicePlate panel recipe with the
independently installed Taskotto process monitor, export its separate,
versioned and non-executable TOML contract:

```bash
ricebowl de taskotto-export --recipe classic --output "$HOME/taskotto-rice.toml"
RICEBOWL_TASKOTTO_RICEPACK="$HOME/taskotto-rice.toml" taskotto
```

This does not apply a desktop rice or require Taskotto to be installed for
export. Taskotto checks the file itself and allows a reversible in-app
preview. The v1 handoff carries only RicePlate's validated foreground,
background and active colors plus a supported base family when a known
wallpaper identifier exists; no arbitrary launcher, scripts, icons or
window-decorator settings are handed over. Existing destination files are
never overwritten, and exports are owner-only `0600`. Use a new filename for
each revision. This is a **manual opt-in bridge**, not automatic session-wide
application styling or a complete cross-app RicePack transaction.

The selection is an atomic `0600` preference inside the owner-private recipe
directory. Repeating the same selection preserves the last undo target; the
selection lock serializes parallel updates. The default is `classic`. A
corrupted selection or subsequently deleted recipe is reported and ignored
at login so the built-in classic panel can start. An **explicitly** requested
invalid recipe still fails before launching labwc. This selects only the
Wayland panel layout; full live desktop rice switching is not implemented.

Imports accept owner-controlled `0600` or `0644` regular `.json` files,
reject symlinks, unsafe directories, invalid schemas, reserved IDs and
duplicate names, and store the result privately in
`$XDG_CONFIG_HOME/ricebowl/recipes/` (or `~/.config/ricebowl/recipes/`).
Exported files are `0600` and existing files are never overwritten. Share
the exported JSON using your normal file-transfer tool; it contains no
executables or assets. The experimental Wayland `.ricepack` above adds portable
integrity/provenance metadata and one bounded PNG, **not** full cross-component
composition, a complete asset suite or live transaction/rollback.

The initializer creates a fully validated `0600` file through an atomic,
no-overwrite operation. Edit its `panel.sections`, `position`, `height` and
`colors` to map a reference/mockup to known widgets; validate again before
preview. No shell code from the recipe is executed. This is **manual assisted
authoring**, not automatic screenshot conversion or a full layout editor.

For mockup layouts that need different panel button widths, explicitly create
a **panel-only schema v2** recipe (v1 remains the default and is unchanged):

```bash
ricebowl de recipe-init --schema-version 2 --base classic \
  --id custom-widths --name "Custom widths" --output "$HOME/custom-widths.json"
```

Edit `panel.metrics` in that JSON file, for example:

```json
"metrics": {"launcher_width": 120, "task_width": 196, "clock_width": 80}
```

The required integer dimensions are in logical pixels: launcher **64–256**,
per-task **96–256**, clock **64–256**. Unknown fields, missing dimensions,
booleans and out-of-range values are rejected. Native RicePlate uses these
widths for actual drawing and click areas; the Waybar preview translates them
to CSS minimum widths, so long text/font metrics can yield a wider fallback
widget. RicePack v3 can embed one PNG, but does not automate mockup conversion.

This demonstrates structural composition through a shared recipe contract;
it does **not** mean RicePlate's Rust layer-shell renderer, arbitrary mockup
conversion or all seven native profiles are implemented yet.

### Native RicePlate layer-shell experiment (developers only)

The GitHub Actions **Native RicePlate prototype** workflow now attaches a
14-day downloadable `riceplate-native-preview-<commit>` build artifact for
each Rust/workflow change. Its folder contains the Ubuntu 24.04 x86_64
experimental binary, the exact Cargo dependency resolution used by CI,
`BUILDINFO.txt` and `SHA256SUMS`. Verify after downloading:

```bash
cd riceplate-native-preview
sha256sum -c SHA256SUMS
chmod +x riceplate-native  # GitHub ZIP download may discard executable bits
./riceplate-native --version
```

This is a short-lived **QA artifact**, not a signed release, portable Linux
installer, or complete RiceBowl session. Use the existing `--nested` preview
instructions and do not replace your login desktop with the binary.

The repository additionally includes `components/riceplate-wayland`, an
event-driven Rust/Smithay Client Toolkit layer-shell prototype. It paints a
simple labelled surface with a fixed `Apps` button that launches the installed
Fuzzel command without passing any recipe data to a shell. When labwc offers
`wlr-foreign-toplevel-management`, the prototype also displays live window
titles and supports click-to-activate via the Wayland seat; clicking an active
single-window task requests minimization. Windows with the same nonempty
Wayland app ID share a labelled task group with a visible count; clicking the
active group cycles through its windows. Windows with unknown IDs remain
separate. The window list is deliberately bounded; when there are more groups
than can fit, the native taskbar exposes previous/next page controls to reach
remaining groups, automatically reveals the active group, and keeps input hit
areas aligned with the visible labels. Only visible entries accept clicks; if the
protocol is missing the panel keeps its launcher and reports the limitation.
It is **not** a replacement taskbar: despite later additions of calendar,
keyboard task navigation and multi-output panels, it still lacks a native tray,
network/audio quick actions and notification handling. Do not start it automatically
alongside Waybar.

The native prototype understands two *bundled* schema-v1 RicePlate recipes:
`classic` (left-aligned bottom taskbar) and `chrome` (centered task list and
taller shelf). Both are parsed from the same recipe JSON files as the
temporary Waybar adapter, with strict schema/widget/color checks. It also
accepts owner-private absolute JSON recipe files (regular files, permissions
`0600`, no final symlinks, maximum 64 KiB). The first implemented widgets
(launcher, tasks and local-time clock), plus the read-only battery label,
may be arranged in the start, center or
end section in any order, including custom top panels; their hit areas follow
the rendered geometry and shrink on narrow displays. The clock is updated
on minute boundaries through the Wayland event loop without a 1 Hz timer.
Custom schema-v2/v3 panel recipes additionally support strict per-widget widths;
schema-v3 adds validated nested groups, static text and spacers with real native
geometry/hit areas; schema-v1 recipes retain their original native dimensions.
Network/audio interactions and the tray still need functional Rust backends. The native
renderer deliberately omits unavailable widgets without displaying pretend
buttons. Custom recipes cannot contain commands or arbitrary executable code.

In a *disposable/nested* labwc session, developers with Rust 1.86+ can try:

```bash
cargo run --manifest-path components/riceplate-wayland/Cargo.toml -- --recipe chrome
```

To exercise RicePlate as the **only** panel within RiceBowl's isolated labwc
session, first install the experimental binary into your user-local PATH:

```bash
cargo install --path components/riceplate-wayland
command -v riceplate-native
ricebowl de start --nested --panel native --recipe chrome
```

The experimental Rust crate does not yet ship a committed `Cargo.lock`; a
reproducible locked native-binary package remains a 1.0 release gate.

This is an explicit developer opt-in, **not** the login-manager default. The
temporary Waybar dependency remains installed and available for recovery: if
RicePlate crashes or cannot start after session preflight, the session logs
the problem and restores Waybar automatically. A deliberate clean panel exit
or an external session shutdown does not restart Waybar. If the native binary
is absent before startup, the CLI refuses the request without touching the
current desktop. The native panel deliberately omits system widgets not yet
implemented; use ordinary `ricebowl de start --nested` for a fuller preview.

To preview a private recipe without changing any desktop settings:

```bash
recipe_copy=$(mktemp --suffix=.json)
cp macrice/de/resources/recipes/classic.json "$recipe_copy"
chmod 600 "$recipe_copy"
cargo run --manifest-path components/riceplate-wayland/Cargo.toml -- --recipe "$recipe_copy"
rm -- "$recipe_copy"
```

The dedicated CI workflow compiles it and checks that both bundled recipes and
a private custom recipe remain alive on a real headless labwc compositor.
The Python session tests additionally verify native launch, crash fallback,
D-Bus restart argument preservation and intentional shutdown behavior.
Nothing changes the XFCE path, Waybar default or the optional session package.

## First-session controls

| Key | Action |
| --- | --- |
| Super + Return | Open Foot terminal |
| Super + Space | Open Fuzzel launcher |
| Super + L | Lock with Swaylock |
| Alt + F4 | Close the focused window (labwc default) |
| Desktop right-click | labwc root menu, including Exit |

Until RicePlate is native, Waybar provides the taskbar, clock, tray and
available system indicators. Only one panel is started. A terminated panel
requests a clean labwc exit instead of leaving the user on an empty desktop.
The temporary shell does not use XFCE's panel or XFDesktop.

## Session boundaries and recovery

An on-demand, read-only process snapshot can now include recognized labwc,
Waybar, native RicePlate and associated upstream services alongside XFCE:

```bash
ricebowl performance desktop --samples 3 --json
```

The report distinguishes XFCE and Wayland PSS totals, marks unreadable
measurements unknown and warns if both Waybar and native RicePlate are seen.
It includes **all matching user-owned processes**, potentially across nested
sessions, so it is not by itself evidence of one session's idle RAM or CPU.
Use isolated login/hardware acceptance for the 1.0 benchmark.

- Labwc reads **only** the bundled `macrice/de/resources/labwc` configuration
  through `--config-dir`. The user's own labwc setup is left untouched.
- The session launcher rejects root execution, missing core dependencies,
  unsafe runtime-directory permissions and an accidental non-nested launch
  inside a desktop.
- labwc 0.7.1 needs an explicit D-Bus activation-environment import; the
  session's autostart performs it for primary sessions. Nested instances
  never import shared activation variables.
- The preview starts/stops its own `ricebowl-session.target`; it does not
  stop `graphical-session.target` used by other sessions.
- The temporary shell supervises its Waybar and optional helper processes.
  Its exit requests termination only of the labwc instance it belongs to.
- The login package can be uninstalled with
  `sudo apt remove ricebowl-wayland-session`. Your user-local RiceBowl
  installation, XFCE session and personal files remain.

If the Wayland session fails to start, the display manager should return to
its greeter. Select XFCE. If the greeter itself is unavailable, use a text
console (`Ctrl+Alt+F3`) to remove the optional session package, **not** the
XFCE desktop packages. Review the user's journal and display-manager logs.

## Physical acceptance checklist (not yet signed off)

- [ ] Login manager lists both RiceBowl Wayland and XFCE.
- [ ] Login, logout, repeated login and crash recovery work.
- [ ] Waybar taskbar, launchers, focus/Alt-Tab, multi-monitor and hotplug.
- [ ] Clipboard between native Wayland and XWayland apps.
- [ ] Flatpak/portal file picker, screenshot, OBS/PipeWire screencast.
- [ ] Polkit authentication (with and without an installed agent).
- [ ] Swaylock, idle lock, suspend/resume, lid and power-button behavior.
- [ ] Input layout/IME, touchpad/tablet, HiDPI scaling and accessibility.
- [ ] Systemd and D-Bus activation variables remain correct across logout
      and returning to XFCE.
- [ ] Real baseline PSS/RSS, idle CPU and login duration recorded on Mint.

These are genuine device acceptance gates; CI cannot replace them. If they
fail, the XFCE session stays the supported default.

[Main DE roadmap](RICEBOWL_DE_ROADMAP.md) · [Current XFCE boundaries](XFCE_RESOURCE_BOUNDARIES.md)
