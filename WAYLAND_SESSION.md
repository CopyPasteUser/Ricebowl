# RiceBowl (Wayland Preview) — first login-session track

**Experimental / opt-in.** This is an independently selectable labwc session
with an optional native RicePlate panel and a Waybar fallback, not yet a
finished RicePlate/RiceSpice/RicePop desktop. The current XFCE/X11 rice suite
and its backups stay intact.
Mint 22/Ubuntu 24.04's labwc **0.7.1** is supported by using its
`--startup` command and requesting compositor exit when the shell finishes.

## Portal integration acceptance (isolated CI)

The session package routes FileChooser through GTK and Screenshot/ScreenCast
through the wlroots backend. The dedicated CI smoke launches a **real headless
labwc** with a private D-Bus and PipeWire runtime. It checks the FileChooser,
Screenshot and ScreenCast interfaces, then requests a **real PNG screenshot**
and validates its size/dimensions. It also creates a ScreenCast session and
selects its sole headless monitor, then **attempts** `Start`. A successful
`Start` must return PipeWire node IDs and a valid remote socket FD. On this
CI runner the **pixman software renderer** instead produces portal response
code 2 at `Start`, a known wlroots ScreenCast limitation
([upstream issue](https://github.com/emersion/xdg-desktop-portal-wlr/issues/289)).
Only the explicitly isolated headless pixman lane reports this as
`PORTAL_CAPTURE_LIMIT`, **never** as a verified ScreenCast stream. All other
method failures, missing screenshot, malformed PNG or bad FD remain fatal.

Only the disposable CI `XDG_CONFIG_HOME` sets wlroots
`[screencast] chooser_type=none` for unattended headless selection; the
installed portal configuration **never** disables the user's output chooser.
The capture client also requires a private marker, runtime mode 0700, nested
headless compositor socket and explicit CI flag. It cannot silently capture
the user's XFCE/Wayland desktop. No interactive consent is exercised here.

Run acceptance on a system with labwc, PipeWire, PyGObject (`python3-gi`),
xdg-desktop-portal, both GTK and wlroots portal backends, gdbus and
dbus-run-session:

```bash
timeout -k 5s 80s sh scripts/smoke_wayland_portals.sh
```

**This verifies an actual headless Screenshot and ScreenCast negotiation,
not a completed PipeWire remote handshake, Flatpak or streamed-frame
certification.** Before 1.0, log into the
physical RiceBowl Wayland session
and verify: (1) a real sandboxed Flatpak file-open and file-save dialog
with consent and cancellation; (2) a real PipeWire ScreenCast sharing flow
in a browser or conferencing client, with visible consent, output selection,
frame delivery and clean stop/revoke; (3) screenshot consent and rejection;
(4) denied requests and missing-backend behavior; (5) dual-display selection,
hotplug and suspend/resume. Verify the same on both Waybar and native
RicePlate sessions without altering XFCE. ScreenCast may need a working
PipeWire user session and compositor-specific chooser configuration that a
single headless screen with automatic output selection cannot certify.

## Prerequisites

Run `ricebowl de check --json` (or `ricebowl-wayland-app de check --json`
when using the standalone package) from your normal desktop first. The
read-only preflight now checks the same required executables as the session
launcher, including the Waybar recovery path, and reports three distinct
booleans: `nested_prerequisites_ready`, `login_prerequisites_ready`, and
`native_login_prerequisites_ready`. A full login requires `swayidle` in
addition to the nested-preview requirements; a native login also needs
`riceplate-native`. The command exits nonzero when full-login prerequisites
are missing and lists each missing program. It does not start a compositor,
inspect user files, or change the current session.

These booleans check **executable availability only**. They do not prove
that the login entry is installed, the D-Bus bus is responsive, the runtime
directory is valid, portal backends work, or the GPU, devices, lock and
screen reader pass physical acceptance. `standalone_de_ready` intentionally
remains `false` until the complete 1.0 release gates are met.

- Linux display manager that enumerates `/usr/share/wayland-sessions`
  (check your specific login manager on the actual computer).
- Either the standalone `ricebowl-wayland-core` package or the legacy
  user-local RiceBowl installed with `bash install.sh`.
- `labwc`, `waybar`, `foot`, `fuzzel`, `swaylock`, a proper logind
  `XDG_RUNTIME_DIR` and D-Bus user session.
- `xdg-desktop-portal`, GTK and wlroots portal backends for file pickers
  and screencast; `xwayland` for legacy X11 clients.
- Full login sessions require **both** `swaylock` and `swayidle`:
  `swayidle -w` requests a lock after ten idle minutes and before sleep.
  The native panel supervisor ends the opt-in session if this essential
  idle/sleep guard exits unexpectedly, rather than continuing unprotected.
  Nested compositor previews intentionally do not start the idle guard.
- Optional: `swaybg` wallpaper, `mako` notifications and an installed
  user polkit agent.

The package only installs the session chooser, a small forwarding wrapper,
RiceBowl-specific portal preferences and a namespaced systemd user target.
It **does not install RiceBowl itself**, overwrite `~/.config/labwc`, edit
global XFCE configuration or set the default session.

The preview `.deb` builder normalizes filesystem/archive timestamps and
supports the standard `SOURCE_DATE_EPOCH` override. Run
`sh scripts/test_wayland_package_reproducibility.sh` to verify that two builds
at different wall-clock times are byte-for-byte identical. This verifies the
small **session-entry package**, not a complete RiceBowl 1.0 application bundle.

## Complete standalone Wayland Debian preview (amd64)

**New:** The four-package bundle no longer needs a prior user-local RiceBowl
installation. It provides a tracked-source application tree under
`/usr/lib/ricebowl-wayland`, an independent `/usr/bin/ricebowl-wayland-app`
command, the login session, and the native Rust panel. Its aggregate package
`ricebowl-wayland-desktop` is dependency-only; no maintainer scripts enable
the desktop, select a login session, migrate user files, or change XFCE.

From a clean Git checkout on an Ubuntu 24.04/Mint 22 **amd64 build machine**:

```bash
bash scripts/build_wayland_core_deb.sh
sh scripts/build_wayland_session_deb.sh
cargo build --release --manifest-path components/riceplate-wayland/Cargo.toml
sh scripts/build_riceplate_native_deb.sh \
    "$PWD/components/riceplate-wayland/target/release/riceplate-native" \
    "$PWD/dist/ricebowl-riceplate-native_0.1.0~preview1_amd64.deb"
sh scripts/build_wayland_desktop_deb.sh

# Inspect the packages before any host installation.
dpkg-deb -I dist/ricebowl-wayland-desktop_0.1.0~preview2_amd64.deb
sudo apt install \
    ./dist/ricebowl-wayland-core_0.1.0~preview2_all.deb \
    ./dist/ricebowl-wayland-session_0.1.0~preview3_all.deb \
    ./dist/ricebowl-riceplate-native_0.1.0~preview1_amd64.deb \
    ./dist/ricebowl-wayland-desktop_0.1.0~preview2_amd64.deb

ricebowl-wayland-app de check --json
```

Log out and **manually** select either RiceBowl Wayland Preview (Waybar) or
Native Wayland Preview (RicePlate) in your login manager. The existing XFCE
selection stays available; neither package changes the default session.
The login wrapper **prefers** the versioned packaged application and only
falls back to `~/.local/bin/ricebowl` if that package is absent, for users
of the original session-only preview. No global `ricebowl` command replaces
the existing user-local XFCE installation.

To remove the four preview packages:

```bash
sudo apt purge ricebowl-wayland-desktop ricebowl-wayland-core \
    ricebowl-wayland-session ricebowl-riceplate-native
```

This removes package-owned binaries and session entries, **not** owner-local
`~/.config/ricebowl`, recipe drafts or appearance choices. Make a backup of
those separately if needed. Only sign out of the Wayland session before
uninstalling; never remove running executable files to test rollback.

GitHub CI builds all four packages reproducibly and checks clean install,
same-version reinstall and purge inside disposable Ubuntu 24.04. A second
CI test checks **real cross-version package lifecycle** against the pinned
source commit `b3d615a7cc508049050eb06c7952ef5a8d26e598` (PR #214):
old Core/Meta `0.1.0~preview1` → new Core/Meta `0.1.0~preview2`,
a rejected corrupt upgrade, an explicit downgrade to saved `preview1`,
then re-upgrade and purge. The session `preview3` and native RicePlate
`preview1` packages are intentionally unchanged in that matrix.

The new Core package includes an immutable
`/usr/lib/ricebowl-wayland/BUILDINFO` containing its Debian version, exact
Git source commit and reproducible-build epoch; the previous package did not.
It is deliberately outside `/usr/share/doc`, which Ubuntu's minimal container
images may exclude during package installation. CI verifies this file appears after upgrade and disappears
after rollback. Test-user recipes, the test XFCE panel configuration and a
user-local `ricebowl` command are checksum-checked after **every** operation.

To reproduce on an isolated Ubuntu 24.04 machine **with Docker** and the
four built current packages (no host package changes):

```bash
git fetch --no-tags --depth=1 origin b3d615a7cc508049050eb06c7952ef5a8d26e598
bash scripts/smoke_wayland_upgrade_rollback.sh "$PWD/dist/riceplate-native-preview"
```

For manual rollback on a real Debian/Mint system, **first log out of the
Wayland session**, back up your XDG recipe/draft state, retain trusted
checksummed `preview1` Core/Meta `.deb` files and use an explicit
`apt install --allow-downgrades ./old-core.deb ./old-desktop.deb`.
Inspect the proposed apt transaction before confirming, especially if other
RiceBowl package revisions or dependencies have since changed. Never run the
automated Docker test against your host package database.

These tests **do not** certify Mint-specific package versions, upgrades of
the unchanged Rust/Session packages, login manager selection, boot recovery,
or suspend/monitor behavior on your ThinkPad. Real old-to-new migration with
user recipes and a reversible physical rollout remain release gates.

### Legacy user-local setup

The session-only package still supports the established user-local
`bash install.sh` deployment, so machines using it are not forced to
migrate. That older flow follows below.

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
dpkg-deb --contents dist/ricebowl-wayland-session_0.1.0~preview3_all.deb
sudo apt install ./dist/ricebowl-wayland-session_0.1.0~preview3_all.deb
```

Log out. In the login manager's session selector, choose
**RiceBowl (Wayland Preview)**. Your existing XFCE session remains an
independent choice. If the entry is not shown, use the current XFCE session
and inspect the display manager's session-directory support before changing
system settings.

The same package now also provides **RiceBowl (Native Wayland Preview)**.
This second entry starts native Rust RicePlate as the sole panel (`--panel
native`); if it crashes during startup, the existing supervisor can recover
with Waybar. The native entry uses `TryExec=/usr/bin/riceplate-native`, so it
is normally hidden until the *separate, optional* native RicePlate preview
package is installed in `/usr/bin`. A user-local Cargo binary on its own does
not make this login-manager choice visible. The ordinary Wayland Preview
continues to start Waybar by default, and neither choice touches XFCE.

Both entries require a working user-local RiceBowl installation. If native
RicePlate is missing, the native launcher fails before entering a compositor;
select the normal Wayland Preview or XFCE and install the optional binary
separately. No RiceBowl session is selected automatically.

### Wake and lost-lock-watcher recovery

In a full RiceBowl Wayland login, the supervisor now compares Linux
`CLOCK_BOOTTIME` with `CLOCK_MONOTONIC`. A difference jump of at least
1.5 seconds indicates suspend/resume; ordinary idle time or system clock
adjustments do not. After a 1.5-second compositor/output-settle window,
Waybar's output-specific recipe is compared with its last known version and
refreshed **only if the effective configuration changed**. Native RicePlate
continues listening to `wl_output` directly. Detection adds no daemon,
network traffic or standalone polling timer, and is disabled in nested
previews and on kernels without `CLOCK_BOOTTIME`.

An unexpectedly dead `swayidle` listener now ends **both live and
non-live** full sessions, including the native panel, rather than entering
an unprotected Waybar recovery loop. A session with a healthy lock watcher
but a failed panel still uses the existing bounded previous-rice/Waybar
fallback. The launcher's return to the login manager is intentional on
security-guard failure; XFCE and the global labwc configuration are not
modified.

This is **not** physical suspend testing. Check on real hardware: suspend
via RiceSpice, physical lid close, power button, wake-to-locked state,
prompt/unlock, USB-C dock reconnect, output layout/different scaling,
repeated sleep cycles, and whether PipeWire/audio and portals recover.
Also check that killing the session's `swayidle` exits RiceBowl without
starting another panel. Save logs before restarting if that fails.

In preview3, **Lock screen** waits for `swaylock -f` to return after
obtaining the lock surface, rather than declaring success merely because a
locker process was launched. **Suspend** first completes the same lock
handshake and refuses to invoke `loginctl suspend` if lock acquisition fails
or times out. Neither behavior verifies power-button/lid-triggered suspend
on physical hardware: check those separately, including resume with a
password-protected lock, missing swayidle, disconnected external displays,
and a crashed idle watcher. For this security boundary, do not treat a
headless unit test as a completed physical security acceptance.

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
For schema-v9 **desktop action widgets**, render
`tests/fixtures/riceplate-desktop-actions-v9.json` in an opt-in nested session.
Click Settings and verify the real settings hub opens; the Wi-Fi widget must
show unavailable when no radio is reported and only toggle through its
verified backend when a device exists. Within a focused output, check
Tab/Shift-Tab, Enter/Space, pointer press-drag-out/release cancellation,
AT-SPI action/focus announcements, then disconnect/reconnect an output while
a widget is focused. Status and text widgets must not intercept app clicks.
Do not test Wi-Fi disruption over the only remote connection. A headless
capture proves pixels, not these human input or assistive behaviors.
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
Pulse/PipeWire service. RicePlate checks a dead subscriber every five seconds
and attempts to reattach without a relogin; verify this really works on the
target device. XFCE/X11 and global labwc keybindings must remain unchanged.
Nested previews intentionally do not spawn the event subscriber.

RicePop brightness OSD: if `/sys/class/backlight/` contains a real backlight,
press brightness up/down in a **full native session** with `brightnessctl`
installed. The private labwc bindings update the hardware, and RicePlate reads
actual kernel brightness (approximately 800 ms response interval) before
showing the existing input-transparent overlay. Confirm that neither an
unavailable backlight nor a missing `brightnessctl` creates a false OSD;
an external brightness change should appear too. No backlight means this
optional feature is unsupported, not a fake 0% display.

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
`recipe.schema_versions` (currently **1, 2, 3, 4, 5, 6, 7**) identifies supported recipe versions. Each
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
`authoring.draft_edit` contract to build a **new Wayland draft** from actual
supported components. The contract publishes editable JSON Pointer paths,
limits, an explicit `set` operation and an example against `classic`.
`ricebowl de creator-schema --recipe ID --json` additionally returns a
standalone JSON Schema 2020-12 for that recipe's actual schema version,
including value types, enum/range limits and nested data structures.
It includes a deterministic schema SHA-256 alongside the reviewed source
SHA-256. This is suitable for IDEs and agent-side early validation without
adding dependencies to the runtime; the full parser remains mandatory for
cross-component and complete recipe checks.

For a repeatable starting point, run
`ricebowl de creator-snapshot --recipe ID --json`. It publishes a canonical
recipe copy under `XDG_STATE_HOME/ricebowl/creator/snapshots/` (or the default
user state directory), with a `snapshot-<content-sha256>.json` filename and
`0400` permissions. The returned absolute `path` can be used as `--recipe`
for `draft-check`, `draft-edit`, `review` or an isolated preview. Every recipe
load checks the exact byte hash against the filename, even if someone changes
only whitespace. Repeated calls reuse an already verified copy without
overwriting it. Referenced visual assets retain their separate content IDs;
the snapshot does not duplicate or back up those assets. The owner can still
change file permissions or delete files, so this is not a privileged immutable
backup or a replacement for an off-machine backup.

The GTK Creator workspace also keeps a durable `.history` intent beside each
new private draft. It publishes that intent before the recipe: an interrupted
save can leave a `.history` without its `.json`, but never exposes that failed
version as a finished draft. To inspect or recover the last **verified** parent
of a missing, corrupted or merely unwanted newer version:

```bash
ricebowl de creator-recovery --json
# Lists missing/unverified workspace versions (up to 128 intents).
ricebowl de creator-recovery --recipe /absolute/path/draft-newer.json --json
# Review parent_semantic_sha256 and the parent path before continuing.
ricebowl de creator-recover --recipe /absolute/path/draft-newer.json \
  --expect-sha256 PARENT_HASH_FROM_INSPECTION --json
```

The second command creates a **new**, reviewable private draft linked to the
verified parent. It does not fix/delete the damaged file, choose the next-login
rice, or change the running desktop. If the parent or its receipt is missing or
has changed, recovery is refused; legacy receiptless drafts have no claimed
ancestry. This offline Creator recovery does not replace the live Wayland
supervisor's separate restore mechanism or hardware crash tests.

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

First check the exact semantic diff **without creating a file**. Review its
`changes`, `source_semantic_sha256` and `draft_semantic_sha256`, then use both
fingerprints to publish only that reviewed proposal:

```bash
ricebowl de recipe-init --base classic --id my-panel --name "My Panel" \
  --output /absolute/path/my-panel-base.json
ricebowl de creator-schema --recipe /absolute/path/my-panel-base.json --json
ricebowl de creator-snapshot --recipe /absolute/path/my-panel-base.json --json
# To pin the source bytes, use the returned snapshot path as --recipe below.
ricebowl de draft-check --recipe /absolute/path/my-panel-base.json \
  --edit /absolute/path/panel-edits.json --json
ricebowl de draft-edit --recipe /absolute/path/my-panel-base.json \
  --edit /absolute/path/panel-edits.json \
  --expect-sha256 SOURCE_HASH_FROM_CHECK \
  --expect-draft-sha256 DRAFT_HASH_FROM_CHECK \
  --output /absolute/path/my-panel-draft.json --json
ricebowl de review --recipe /absolute/path/my-panel-draft.json \
  --compare /absolute/path/my-panel-base.json --json
ricebowl de start --nested --recipe /absolute/path/my-panel-draft.json
```

The editor supports only validated, non-executable recipe properties: name, panel edge,
height, schema-v1/v2 `start`/`center`/`end` widget lists, schema-v3 typed
`panel.layout` regions, hex colors and schema-v2/v3/v4 widget widths. Schema
v4 additionally offers explicit menu, wallpaper, design-token and responsive
editing paths.
IDs/schema versions are immutable; use `recipe-init` to create
a fresh identity or v2/v3/v4 template. A draft made directly from `classic` remains
identified as `classic` and can be previewed by absolute path, but cannot be
imported over the reserved built-in ID. At most 16 `set` operations and 16 KiB of
edit data are accepted; duplicate paths, unknown components, scripts, external
assets, unsupported actions and no-op edits are rejected. Stale source or
changed proposal fingerprints fail before file creation. The destination
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
in 16-pixel steps, or Enter/Space to launch. On multiple named monitors, press
`F6` while a desktop icon is focused to assign it to the next connected
display (cycling alphabetically), or `F7` to show it on every display again.
Unassigned icons keep their original mirrored behavior. Assigned icons
disappear from non-owner displays and no longer reserve collision space there;
if their saved display is unplugged, they appear temporarily on the primary
desktop and return to their assigned output when it reconnects. A missing or
unsafe compositor output name cannot be assigned. Keyboard focus is **not**
automatically transferred to the new display; use the pointer to focus there.
The native shell also accepts a left-button drag **released on a different
named display** when the compositor reports both outputs' logical positions.
The shortcut snaps to the target after release (no cross-screen drag ghost);
the former display's saved positions are preserved. A missing output name,
unconfigured destination, absent geometry or no free icon space rejects the
transfer. `F6` / `F7` remain the keyboard alternative; physical Wayland
pointer-grab and mixed-DPI acceptance is still required. RicePlate stores positions per
rice in `$XDG_CONFIG_HOME/ricebowl/native-icon-positions/<rice-id>.json`
(typically `~/.config/ricebowl/native-icon-positions/`) without altering the
original recipe. Saved coordinates and optional output assignments use a
private, backward-compatible v3 file (v1/v2 still load), and are never
honored by nested Creator/headless sessions, so screenshots remain
reproducible. Desktop widgets are available in schema v8; real-GPU/input
acceptance remains open.
Native RicePlate **reflows shortcuts within its selected logical
output** on mode/scale changes, preserving valid positions and parking icons
outside the output when no safe, non-overlapping hit area exists. This placement is not persisted;
fractional-scale visual quality and multi-monitor hotplug still need device
acceptance. Do not treat it as a finished desktop.

#### Schema-v6 native menu presentation (experimental)

Native RicePlate supports two real menu geometries using the **same fixed
Linux actions, installed-application search and saved pins**. The original
horizontal group tabs remain the default for every earlier schema. A v6
recipe may opt into a persistent left navigation rail:

```json
"menu": {
  "title": "Y2K Desktop",
  "presentation": "sidebar",
  "groups": [
    {"title": "Programs", "actions": ["applications", "terminal"]},
    {"title": "Session", "actions": ["lock", "logout"]}
  ]
}
```

Use [`tests/fixtures/riceplate-sidebar-v6.json`](tests/fixtures/riceplate-sidebar-v6.json)
as a complete working example. From schema v6 onward, `presentation` is
optional and may only be `tabs` or `sidebar`. Unknown fields, null, scripts,
unsupported values and an explicit presentation in v4/v5 are rejected. The
vertical variant reserves 112 logical pixels on the left for up to four
group buttons; the selected group's actions, search results and favorites
remain in the right column. Keyboard group changes and action activation
reuse the existing logic; assistive roles identify sidebar groups as buttons.

`de draft-edit` accepts `/menu/presentation` on v6+ recipes, `de catalog --json`
advertises both variants, and `de review` reports the semantic change. The
Waybar fallback continues to compile the same grouped labwc root context
menu, **not** the native sidebar visual. The headless native smoke generates
`menu-v5.png` and `menu-sidebar-v6.png` for comparison. This is a first
structural option, **not** a Windows XP/7 one-to-one menu clone, dynamic
grid engine, or fully themeable shell.

#### Schema-v6 composed menu sections (native RicePlate)

Optional `content` on each menu group composes the same **one real native
menu** from at most two validated sections and four total visible items:

```json
{"title": "Programs", "actions": ["applications", "terminal"], "content": [
  {"type": "actions", "title": "Quick Links", "limit": 2},
  {"type": "apps-grid", "title": "Installed Apps", "limit": 2}
]}
```

- `actions` displays the group's existing fixed, allowlisted actions.
- `favorites` displays privately saved F2 fixed-action pins, never arbitrary
  commands or unverified desktop files.
- `apps-list` lists installed XDG launchers from the already verified native
  application index; `apps-grid` displays two-column initial-letter tiles.
  These **are not** desktop-specific themed application icons.
- Section titles use the same safe ASCII label rules as group titles. Each
  `limit` is an integer 1–4; section kinds cannot repeat, and the sum of
  section limits must be at most four. The recipe cannot choose a launch path.
- Without `content`, older group layouts are unchanged. Schema v4/v5 reject
  `content`, as do `null`, unknown fields, duplicate sources and excess limits.

`tests/fixtures/riceplate-composed-v6.json` is a complete native example.
The **320×304** popup keeps a stable footprint: optional headings and rows
fit inside its existing content area. Grid cells use pointer and keyboard
navigation (Left/Right within a populated row, otherwise switch groups);
accessible labels use the same action targets as tab/sidebar menus. F2 pinning
continues to support fixed recipe actions only. Search and Saved views retain
their earlier list layout. The Creator catalog, `/menu/groups` draft edits,
semantic review and native screenshot smoke now understand compositions.
The Waybar/labwc fallback keeps its flat action groups and does not imitate
the native grid. Headless screenshot: `menu-composed-v6.png`. Visual fidelity,
localized icon sets and physical input/Orca testing remain open.

#### Schema-v7 declarative system controls (native RicePlate)

Schema v7 adds a bounded `control` node to `panel.layout` and
`responsive.compact_layout`. Only these four IDs are allowed; each takes one
safe 1–16-character static label and **never** a shell command:

```json
{"type": "control", "id": "wifi-toggle", "label": "Wi-Fi"}
{"type": "control", "id": "audio-mute", "label": "Mute"}
{"type": "control", "id": "audio-down", "label": "Vol -"}
{"type": "control", "id": "audio-up", "label": "Vol +"}
```

See the complete, native-testable
[`riceplate-controls-v7.json`](tests/fixtures/riceplate-controls-v7.json) recipe.
Start a new private template with `ricebowl de recipe-init --schema-version 7`
plus the ordinary `--base`, `--id`, `--name` and `--output` options; add these
nodes using `de draft-edit`, review them with `de review` and preview the
result with `de start --nested --panel native --recipe /absolute/path/to/rice.json`.
The Creator catalog v11 advertises the exact contract. Existing schemas v1–v6
are still accepted, but reject `control` nodes.

The native RicePlate panel and its menu share **one bounded asynchronous
NetworkManager/WirePlumber worker**. It samples WLAN radio state separately
from general connectivity, reads actual default-sink mute/volume and verifies
the state after a write. A control with no provider shows `N/A`, a pending
operation shows `Wait` (`Busy` on other controls), and unsuccessful readback
shows `Failed`. Multiple
simultaneous writes are not queued; pointer, keyboard and AT-SPI activation
use the same dispatcher. The geometry never moves when the status changes.
The **Waybar fallback displays noninteractive `N/A` labels** with a native-only
tooltip: it cannot verify those state changes and must not pretend to. Real
GPU, hardware toggles and Orca interaction still need local acceptance.

#### Schema-v8 Layout Engine (native RicePlate)

Schema v8 keeps the versioned v7 panel, compact layout, native menu, wallpaper,
and validated desktop shortcuts. It adds one **opt-in desktop composition**:

```json
"composition": {
  "widgets": [
    {"id": "desk-clock", "kind": "clock", "x": 32, "y": 320},
    {"id": "desk-system", "kind": "system", "x": 32, "y": 432},
    {"id": "desk-date", "kind": "date", "x": 32, "y": 544}
  ],
  "window_region": {"x": 30, "y": 8, "width": 66, "height": 84},
  "compact_hide_widgets": ["desk-system", "desk-date"]
}
```

`window_region` is a rectangle in **percent of output logical dimensions**:
in this example, the shell keeps the right-hand 66% of each output free of
desktop shortcuts/widgets, starting at 30% of its width and 8% of its height.
Labwc remains the window manager: this is a *desktop-item exclusion zone*,
not a command to tile, resize, or position client windows. A bounded placement
planner keeps 1–8 existing shortcuts and up to 4 fixed 200×96 desktop widgets
from overlapping the exclusion zone or each other, respecting panel height.
If there is no safe room, the surface is parked off-screen, not squeezed onto
another widget. The existing panel `responsive.compact_max_width` also hides
any widget IDs listed under `compact_hide_widgets` on narrow outputs.

Widgets are native, read-only clock, date and live network/audio system status
surfaces, rendered by the existing RicePlate process on the bottom layer. They
use the compositor's logical output geometry, reflow on output changes and
expose read-only accessibility status. No custom scripts, network endpoints,
arbitrary widget types, background daemon, or compositor window-control API
are admitted. The Waybar fallback still renders **only the panel**; its desktop
widget support is explicitly unavailable. Recipe schemas v1–v7 and XFCE/X11
continue unchanged.

```sh
ricebowl de recipe-init --schema-version 8 --base classic --id workstation-layout \
  --name "Workstation Layout" --output "$HOME/workstation-layout.json"
ricebowl de review --recipe "$HOME/workstation-layout.json" --json
ricebowl de catalog --json
ricebowl de render --recipe "$PWD/tests/fixtures/riceplate-layout-v8.json" \
  --output "$HOME/layout-preview.png" --width 1366 --height 768 --json
```

The full [schema-v8 fixture](tests/fixtures/riceplate-layout-v8.json) combines
sidebar menu, hierarchical panel controls, wallpaper, shortcuts, widgets and
a compact breakpoint. The isolated `de render` command requires labwc, grim,
swaybg and `riceplate-native`; it does not mutate the active desktop.
Actual multi-monitor placement, fractional scaling, device input and Orca
require real-hardware acceptance before a stable release.

#### Schema-v9 shared component bindings (native RicePlate)

The opt-in v9 component registry defines at most **eight reusable instances**
using only existing Linux capabilities. A `status` binding is one of `clock`,
`network`, `audio`, `battery`; an `action` binds only the same four fixed panel
actions (`applications`, `terminal`, `settings`, `lock`) or four verified native
controls (`wifi-toggle`, `audio-mute`, `audio-up`, `audio-down`). No external
command or user-provided executable is allowed.

```json
"components": [
  {"id":"net-status","role":"status","binding":"network","label":"Network"},
  {"id":"wifi-switch","role":"action","binding":"wifi-toggle","label":"Wi-Fi"}
]
```

Use `{ "type":"component", "ref":"net-status" }` in either a full panel
region or the compact panel layout; use `{ "type":"component",
"ref":"wifi-switch" }` for a real native Wi-Fi control with the existing
verified state/disabled/error presentation and keyboard/AT-SPI activation.
The Waybar fallback renders the status with its usual module and the
unverified Wi-Fi control as **noninteractive N/A**, never a fake toggle.

Native desktop widgets may reference a **status** component with
`{"id":"desk-net","kind":"component","ref":"net-status","x":32,"y":432}`.
That widget displays the same live NetworkManager-derived status as the panel
and uses the existing output-aware widget layer; action components are rejected
on desktop widgets because a safe pointer/keyboard action surface has not yet
been implemented there. The same binding is read once by the existing native
status provider, not by an additional polling daemon.

Schema v9 also permits a standalone read-only text widget without a binding:

```json
{"id":"desk-title","kind":"text","text":"Welcome to RiceBowl","x":32,"y":656}
```

The text is limited to **1–22 safe ASCII characters**, without markup,
commands or script evaluation. All desktop widget surfaces use an **empty
Wayland input region** (including newly attached outputs), so a clock, status
or text label does not steal pointer clicks from underlying windows. Desktop
widget actions and editing via direct manipulation remain future work; the
Waybar fallback still has no desktop widget layer.

Generate a private example with `ricebowl de recipe-init --schema-version 9
--base classic --id my-components --name "My Components" --output
"$HOME/my-components.json"`. Inspect the complete
[v9 component fixture](tests/fixtures/riceplate-components-v9.json), which
demonstrates reuse in full/compact panel regions and desktop status widgets;
review with `de review`, edit with `de draft-edit` (`/components` and the
existing layout paths), or render with isolated `de render`. Schemas v1–v8
remain valid. This is a first, bounded common component system, not a generic
extension/plugin runtime or an arbitrary visual widget framework.

#### Schema-v10 appearance and output-aware fallback

Create an owner-private recipe with `ricebowl de recipe-init --schema-version 10
--base classic --id my-style --name "My Style" --output "$HOME/my-style.json"`.
The strict v10 contract adds exactly one `appearance` object:

```json
"appearance": {
  "font_scale": 2,
  "font_weight": "bold",
  "item_spacing": 6,
  "hover": "#336699",
  "focus": "#ffffff",
  "disabled": "#7a7a7a"
}
```

`font_scale` is bounded to 1 or 2; `font_weight` to `regular`/`bold`;
`item_spacing` to 0–16 logical pixels, and state colors to six-digit hex.
Native RicePlate uses its existing bundled 8×8 glyphs (no external font
dependency) and scales pixel cells consistently in the panel and selected
native menu/desktop surfaces. Waybar uses the matching CSS size, weight and
state colors. This does **not** supply selectable TTF/OTF families or complete
resizable menu layouts. The Creator accepts `/appearance/font_scale`,
`/appearance/font_weight`, `/appearance/item_spacing` and the three colors as
safe offline draft edits; `de review` and RicePack preserve them exactly.
Recipes v1–v9 retain their original rendering defaults.

On a logical output too small for the 320×304 native start menu plus panel,
RicePlate fits the popup within available width/height. At popup sizes of at
least 168×144 logical pixels, the **native menu** draws readable full-resolution
bitmap text in a compact, paged action list (including composed menu actions),
with matched pointer hit targets, PageUp/PageDown and AT-SPI visible rows.
Narrow sidebar menus switch to top group tabs; typing searches as before.
RicePop notifications use the same full-resolution compact strategy for active/
history rows and detail actions; body text wraps to the compact width and
remains page-reachable using the keyboard, pointer and accessibility actions.
Outputs smaller than 168×144 still use a proportional clipping-safety fit
with inverse-mapped pointer hits. Normal-sized menus and notifications retain
their established layouts. Real physical-device/Orca usability and extreme-size
readability remain outstanding.

If `wlr-randr --json` provides an enabled-output inventory, the supervised
Waybar startup/live-apply/rescue path compiles each output's actual logical
width into a separate named bar with its own compact/full layout and scoped
CSS. One extra compact bar excludes all known names and catches a *new*
hotplug output without duplicating the others. If the utility fails, the
unchanged generic fallback is used. After a user **confirms** a mode or scale
change in RiceSpice's guarded monitor editor, its detached rollback worker
asks the owner-private live shell supervisor to refresh only that session's
Waybar, keeping the current panel when the replacement fails. **External**
mode/scale changes are also detected without polling when both `riceplate-native`
and `wlr-randr` are installed. An additional **surface-free, event-driven**
Rust watcher runs only in the opt-in Waybar fallback session; it observes
compositor `wl_output` events and sends a private notification pipe to the
existing shell supervisor. After a short burst debounce, the supervisor
compares the fresh validated configuration and replaces **only its own**
Waybar when needed. The watcher never modifies displays. If the optional
watcher is absent or crashes, `ricebowl de display-refresh --json` remains
available, or a fresh login regenerates the layout. No display polling,
system-wide signals or recipe-supplied commands are added; the small watcher
process adds some resident memory while enabled. Physical hotplug QA remains
outstanding.

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
notification daemon, invokes an action or modifies history by reading the list.

In RicePlate's opt-in **Notifications** menu, Enter or pointer selection opens
a detail page; Up/Down select the exact action advertised by the original app,
and Enter (or a pointer click) explicitly invokes it. The service re-reads the
bounded active inventory and checks the ID and action key before calling Mako;
expired notifications, changed actions, duplicate IDs and invalid data are
rejected. Delete is a separate active-only dismissal, never an Enter shortcut.
The **Past** tab cannot invoke or dismiss a saved entry. Escape from a detail
returns to the list; Escape again returns to the native menu. Longer bodies
have two-line pages: Left/Right (or click left/right inside the body) moves
between pages, while AT-SPI announces the complete original text. The inbox
refreshes every three seconds only while open; on a host error, it retains
the read-only view, disables stale actions and retries after 12 seconds.
On replacement or changed action keys, the selection must not silently invoke
a different action. The built-in 8×8 renderer supports Latin, Greek and
Hiragana; other scripts currently show replacement glyphs. Keyboard/AT-SPI
and pointer behavior, action result, long text, stale alerts and multi-output
focus still require real-device checks. App actions may have consequences determined
by their originating app; only explicitly select actions you recognize.

The corresponding non-automatic diagnostic command is:

```bash
ricebowl de notification-invoke --notification-id ID --action-key KEY --json
```

Use only an exact ID/action key reviewed in a fresh `de notifications --json`
result. Unlike the read-only inventory, this command deliberately invokes an
application action. No command from a rice or notification body is executed.

Discover the implemented authoring operations, required flags, safe effects,
versioned output and their limits without launching a model or a daemon:

```bash
ricebowl de creator-api --json
ricebowl de catalog --json
```

Creator API **v2** returns a machine-readable `feature_negotiation` block:
supported recipe schemas (currently v1–v10), the recommended authoring schema,
matching catalog version, and truthful supported/unsupported feature IDs.
The `authoring_workflow` lists existing read-only discovery, private draft,
native preview, package and explicitly reviewed activation operations. Every
command advertises its `mutation_scope` (`none`, private file, next-login,
current Wayland session or current user session) and whether an explicit user
invocation is required. The discoverable contract **does not grant access**
to active configuration or bypass native safety checks. A Creator must compare
feature IDs and versions before constructing a UI; unsupported widget actions
must remain disabled or request a new shared primitive.

#### Rice Creator 0.4 — component and nested panel editor

Creator 0.5 preserves the component and panel workflow below; new drafts are
schema v11, and legacy saved v10 drafts can be upgraded as an **additional
immutable version**. See the [0.5 visual asset contract](#rice-creator-05--private-font-and-icon-assets).

Launch `ricebowl creator` (or `macrice creator` from a checkout); the regular
user-local installer also adds a **Rice Creator (experimental)** application
entry. This is an on-demand GTK3 desktop application, **not** part of Wayland
login, RicePlate's resident process or the XFCE rice selector.

The graphical authoring workspace consumes the actual schema-v11 Runtime
contract: create from the Heritage Modern, Orbit Studio, Classic or Chrome
template; edit the panel edge/height, two menu presentations, bundled wallpaper,
responsive cutoff, font/spacing/state colors and reorder, remove or add supported
panel nodes in the start/center/end lanes. The same strict parser
and `draft-edit` allowlist validate every **Review & save…** operation. Invalid
or duplicate interactive controls cannot be installed by a failed draft edit.

**Creator 0.4** provides a dedicated **Component library** form. Add new
bounded IDs, pick a real status binding (`clock`, `network`, `audio`, `battery`)
or one of the fixed supported Linux actions/controls, and give each a short
label. Existing components can be updated; in-use references are listed and
prevent removal until detached from the panel, compact panel and desktop.
Renaming an ID implicitly is not supported: use an explicit new component.
The complete proposed component registry is validated before referencing it,
allowing a new component and its first panel use to be saved together in one
immutable draft revision (also in tool-neutral offline draft-edit data).

The **Panel composition** inspector now edits actual nested schema-v10 group
nodes, rather than merely displaying a group as one opaque row. Its selector
switches independently between **Wide** and **Compact** panel structures.
For each start/center/end lane, add widgets, registered components, safe
fixed actions/controls, 4–64 px gaps, 6–32 px dividers, 1–24 character
labels or a group. Group a node, add children up to the schema limit, edit
width/spacing/labels, reorder siblings or ungroup without losing its children.
The validator enforces at most three nested levels, six children per group,
eight lane roots and 24 nodes overall, as well as duplicate bindings and
required launcher/task invariants. Invalid edits stay out of the draft and
provide a visible error; nothing is written until **Review & save…** is approved.

The optional graphical **Edit layout** canvas now exposes the actual schema-v10
desktop composition. Choose a widget or shortcut in the layer list or click
its on-screen outline, then drag it or use the keyboard arrow keys (8 px,
Shift+arrow for 1 px) to adjust its logical output position. Select the
reserved application-window rectangle to move it in bounded percentages; its
width and height are editable in the inspector. The same inspector edits
static widget text, desktop shortcut label/action, compact-screen hiding,
and adds or removes strictly allowed status/static widgets and shortcuts.
Maximums remain **four desktop widgets and eight shortcuts**. Duplicate,
overlapping or unsupported icon definitions, invalid text, off-bounds regions
and unknown action bindings fail validation without changing an active desktop.
All edits use the existing immutable draft revision flow, not a new renderer.

**Edit layout is schematic**, with a gridded logical-coordinate view that
never claims to display true wallpaper pixels or client windows. Switch to
**Native capture**, then click **Render preview** for the true headless labwc /
RicePlate screenshot. The last capture is marked stale when edits are pending;
output aspect ratio follows the selected preview geometry. The GTK canvas uses
the distro's `python3-cairo` package (also installed by the documented Debian
setup) to produce an image in memory; no
`gi._gi_cairo` GTK signal converter or extra Creator daemon is required.

In the **Wallpaper library** inspector, choose any bundled wallpaper or import
an existing owner-controlled `.png` via the GTK file picker. The safe import
accepts only inspected 8-bit RGB/RGBA PNG data (maximum **2 MiB**, 4096 pixels
per side, bounded raster); it rejects symlink paths, unsafe permissions,
oversized/corrupt chunks, hostile compression and conflicting attribution
for the same content hash.
The image is stored once as an immutable, private, SHA-256-addressed asset.
Creator also keeps an immutable, 0600 sidecar with your chosen display name
and **user-declared** author, license, origin and optional public source
reference. These are not legal or license verification. Old CLI-imported PNGs
are listed with honest unspecified attribution; damaged assets are skipped.
The inspector previews the verified asset and marks missing references clearly.
Selecting an image changes only the *unsaved draft*; click **Review & save…**
and confirm the displayed changes to persist it, or reopen the previous version
to undo. The GUI ignores wheel
events over the wallpaper selector so scrolling the inspector cannot change
the selection accidentally. Exports include the PNG and its attribution in
the existing deterministic **RicePack v3**, with no active-session apply.
Schema-v11 font/icon artwork is documented separately below; arbitrary
reference-image conversion remains unsupported.

Saved drafts are owner-only files in the XDG state directory under
`ricebowl/creator/drafts/` (default `~/.local/state/ricebowl/creator/drafts/`).
Every **Review & save…** opens a scrollable before/after diff with the complete
source and proposed SHA-256 fingerprints. **Keep editing** creates no file;
**Create private version** revalidates both fingerprints before writing.
Each approved save creates a **new**, non-overwriting version and keeps the
earlier version accessible through **Previous version** or
the saved list. External modification is detected through the reviewed SHA-256;
the editor refuses a stale save. Opening another draft with pending changes
requires an explicit discard confirmation. **Export RicePack** creates a new
validated `.ricepack` without overwriting, importing or applying anything.

New Creator drafts also have a sibling owner-private `.history` receipt
(mode `0600`). The receipt binds each saved recipe's validated semantic SHA-256
to its predecessor's filename and SHA-256. **Previous version** survives
Creator restarts; **Version history…** shows and reopens up to 64 verified
versions in the same project lineage. Modified recipes, unsafe/symlinked
receipts and altered or missing ancestors are rejected during traversal;
the current valid version remains available if an older link is broken.
Drafts created before these receipts remain readable without a verified
predecessor. Like other files owned by your account, receipts can still be
altered or deleted by a process running as you; this feature detects
unexpected changes but is not a root-owned immutable backup.

For scripted/AI-assisted authoring, the same private ancestry is available
read-only using `ricebowl de creator-history --recipe /absolute/draft.json --json`.
It reports validated semantic hashes and filenames without creating
or activating anything. A damaged chain returns a structured `unverified_history`
error instead of silently trusting an altered ancestor.

**Render preview** first asks for review and approval of any pending edits,
then invokes the exact
existing isolated native `de render` backend in a worker thread at one of four
resolutions/scales. The real PNG is displayed in the editor after the renderer
has terminated its labwc/RicePlate children; no background compositor or
cache of private screen pixels remains. Missing `labwc`, `grim`, `wlr-randr`,
`swaybg` or the native `riceplate-native` binary yields an explicit unavailable
state instead of an illustrated preview. The preview is a static snapshot, not
an interactive nested session. The GTK Creator now also exposes a separate
**Install / switch…** menu. After **Review & save…**, choose **Install saved
version…** to install that exact reviewed SHA-256 into the owner-private
Wayland recipe collection; the desktop does not change. From within an opt-in
RiceBowl Wayland session, **Apply in Wayland…** and **Restore previous rice…**
check the live supervisor and require a second explicit confirmation. The
supervisor owns CAS-protected switching and compensated rollback, not the GTK
process. Conflicting installed IDs are never overwritten: choose **Fork as new
rice ID** to copy a revised saved layout under a new identity, then install
it explicitly. This is experimental;
hardware/input QA and stable-release acceptance are still required. Existing
CLI commands continue to
offer explicit reviewed apply and restore; the Creator 0.4 GUI **never** calls
them. No AI runtime, internet account or arbitrary plugin code is required;
the optional visual editor uses the documented GTK/PyGObject and Cairo packages.

#### Rice Creator 0.6 — private reference comparison

In the **Reference / visual QA** strip of `ricebowl creator` (requires
`python3-pil`, for example `sudo apt install python3-pil`), use **Load PNG…**
to select a local, owner-controlled `.png` screenshot (maximum 64 MiB,
16,777,216 decoded pixels). The file must be a readable PNG, not a symlink or
group/world-writable source. Creator checks the whole image and copies it by
SHA-256 to `~/.local/state/ricebowl/creator/references/` (or the matching
`XDG_STATE_HOME` directory), with `0700` directory and `0600` images and
selection metadata. Only the Creator draft ID is stored in the selection
record; no arbitrary image file path is stored in a recipe. A reference is
reloaded after opening a saved version with the same draft ID. **Unlink**
removes just the selection; existing immutable source copies are retained.

1. Choose or create a private draft, edit it, and approve **Review & save…**.
2. Choose the output resolution (for example **1366 × 768**). Your reference
   must have **exactly the same pixel dimensions**; Creator never stretches
   or crops it to improve a score.
3. Click **Render preview**. This launches isolated headless labwc/RicePlate
   and captures an actual PNG. The active XFCE or Wayland session is unchanged.
4. Click **Compare**. Pixel work runs in a worker and uses the same engine as
   `de visual-compare`. Choose **Native**, **Reference**, **Split 50/50**
   (left reference, right real capture), **Overlay 50/50**, or **Difference**
   (red tolerance-aware heatmap) to inspect the images.
5. Adjust **Pixel cutoff** (0–255, default 24) or **Raster tolerance**
   (0, 1 or 2 pixels; default 1), then compare again. The status reports both
   exact and tolerated changed-pixel fractions, mean RGB error and layout
   warnings. These are *pixel diagnostics*, not a promise of OS similarity,
   working controls or accessibility.

Editing a recipe, switching geometry or changing the comparison policy
invalidates its old result; render again after changing the recipe or size.
If the selected PNG is damaged, replaced or its private permissions change,
Creator rejects comparison and asks you to select a valid reference. The PNG references and
generated diagnostic images are **not** exported in RicePack v4. Direct
screenshot-to-recipe interpretation, automatic alignment, image asset license
verification and hardware acceptance are separate, unfinished work.

#### Rice Creator 0.7 — reviewable reference mapping

Creator 0.7 adds a **Reference mapping · review before editing** disclosure
under the 0.6 visual-QA controls. Create/open a draft, link a reference PNG and
save all pending edits first. Unlike visual comparison, **Analyze offline** does
not require a native render or a matching render resolution. It samples the
verified private PNG on a worker without network access. A sufficiently clear,
full-width top/bottom strip can produce proposed **panel edge**, **height**
(28–64 px) and **dominant panel color**; visibly contrasting neutral pixels
or saturated pixels may generate lower-confidence foreground/accent suggestions.
Uniform, small or ambiguous images yield no invented panel. Confidence is
**heuristic evidence, not a similarity score or recognition guarantee**.
The GTK review shows **strong/moderate/tentative** evidence instead of presenting
an uncalibrated numeric score as a probability.
Decorative full-width wallpaper stripes without contrasting UI marks are also
not treated as panels; screenshot geometry remains an uncertain visual hint.

The review list shows the exact schema field, proposed value and reasoning.
Only higher-confidence **offline** hints are prechecked; all external proposals
start unchecked. Review them before clicking
**Use checked hints in unsaved draft**. This updates the editable property
inspector, **not** a persisted version. Use **Review & save…** and then **Render
preview** to verify. The previous version remains recoverable. Switching
references or drafts, saving or changing a field invalidates stale proposals.

For additional assistance, **Export hints…** creates a new private JSON file
without overwriting or embedding screenshot pixels. An external AI or human
can inspect the image **only if you separately choose to share it** and return
an edited proposal in the same format. Discover the allowlisted vocabulary with
`ricebowl de creator-api --json` (`reference_mapping` section). For example,
replace the exported `suggestions` array with:

```json
"suggestions": [
  {
    "path": "/menu/presentation",
    "value": "sidebar",
    "confidence": 0.5,
    "evidence": "Human-reviewed menu appearance; not machine verified"
  }
]
```

Preserve the exported `mapping_version: 1`, SHA-256 identifiers, image size,
`regions` and `notes`; set `source` to `external`. Only the full JSON object
is accepted by **Import JSON…**. The importer checks owner-controlled regular
files at most 24 KiB, rejects symlinks, duplicates, unrecognized fields and
unsafe/out-of-range values, and runs both the standard draft validator and
full schema-v11 parser. Supported proposals are limited to panel placement,
height, colors, menu presentation, spacing and existing bounded panel-layout
nodes. AI proposals cannot define arbitrary commands, scripts, new executable
abilities or runtime changes. A mismatch with the selected PNG or saved draft
requires a fresh analysis/export. **Every imported file is classified as
external even if its JSON declares `source: offline`**, so its checkboxes start
unchecked. The selected reference is checked again before transfer or export
to catch changes made outside the Creator. The Creator does not upload images, launch
an AI service, auto-activate a rice or include references/proposals in RicePack.

**Not implemented:** general-purpose image semantic segmentation (which icon
is a clock, which rectangle is a menu, font recognition), reliable menu/window
geometry reconstruction, automatically generated assets or one-click faithful
desktop cloning. The JSON interface supports an external supervised AI authoring
loop, not an autonomous screenshot-to-desktop converter.

#### Rice Creator 0.9 — interactive region correction cycle

Creator 0.9 adds **Draw region on screenshot** to the Region QA disclosure.
After selecting a private reference PNG, activate that toggle. The GTK viewer
switches to the reference image; **press and drag** over the area you want to
check. A live colored outline follows the pointer. Release to add the region.
The selection is converted from fitted preview coordinates to the exact
original screenshot pixel bounds, clamped to the image, and rejected if it is
too small, duplicate, beyond the eight-region limit or outside the strict
0.8 geometry bounds. Press **Esc** during a drag to cancel. The numeric X/Y/
Width/Height controls remain available for precise keyboard editing.

For a **correction cycle**:

1. Mark one or more regions and render the saved draft at the reference's
   exact resolution. Select **Measure regions** to record the baseline.
2. Change a validated field in the existing inspector, or explicitly approve
   a 0.7 mapping suggestion; choose **Review & save…**. Regions and prior
   measurements stay attached to the same private screenshot and draft ID.
3. **Render preview** for the newly saved recipe, then choose **Measure regions**
   again. The correction cycle lists hashed recipe/capture identities and the
   change in *tolerated changed-pixel percentage points* for each area.
4. Repeat as needed. Only the most recent 12 comparable measurements are held
   in memory; identical recipe/capture measurements aren't duplicated.
   **Export pixel history JSON…** saves a new owner-private, versioned report
   containing measurements and deltas, never the images themselves.

An improvement in one pixel-error metric does **not** establish semantic,
interactive, visual or functional fidelity. The app does not generate or apply
corrections automatically; each recipe edit remains deliberate, validated and
saved as a separate draft revision. Changing region geometry, source PNG,
reference selection, draft identity or comparison policy clears the history.
Rendering runs in an isolated labwc session, not the active desktop.

#### Rice Creator 0.8 — manual region QA

Creator 0.8 adds **Region QA · measure selected areas** below Reference mapping.
Open a saved draft, load a private reference PNG, then **Render preview** with
exactly matching pixel dimensions. Open the Region QA disclosure and choose
**Panel**, **Menu**, **Desktop** or **Unknown**, then enter X, Y, width and height
in **original reference pixels**, not percent or scaled preview coordinates.
Select **Mark rectangle**. Each manually reviewed area is numbered, shown in
the list with a **Remove** button, and outlined in the *Marked regions* real-image
view. You can mark up to eight areas; zero-size, off-image, duplicated, excessive
or malformed regions are rejected. The list is operated with normal GTK
keyboard navigation; mouse dragging is not required.

After running the 0.7 **Analyze offline** action (or importing reviewed external
mapping geometry), **Use detected** can explicitly copy those geometric bounds
to the region list. This is not object recognition: even when the source says
`menu`, the label is only the provided human/heuristic annotation. It does not
authorize a recipe edit or automatically select a 0.7 proposed change.

Choose **Measure regions** to compare *each* marked rectangle against the
actual isolated native RicePlate capture, using the existing **Pixel cutoff**
and **Raster tolerance** controls. The summary shows raw changed-pixel ratio,
tolerated ratio and mean RGB error **per rectangle**. Neighborhood tolerance
includes pixels just outside rectangle edges (0/1/2 px), so shifts at the edge
of a mark are treated consistently with the full-image comparison. All figures
are pixel errors, never image similarity, recognized components or action QA.

**Export pixel history JSON…** optionally saves a new, owner-private, versioned
report containing dimensions, marked geometry, policy, raw/tolerated metrics
and SHA-256 identities for the exact reference PNG, native capture and saved
recipe. No screenshot pixels, absolute file paths, scripts or AI instructions
enter the report. In 0.9, `correction_cycle` additionally holds only bounded
SHA-identified measurement receipts and per-region changes, never images or
automatic edit commands. An AI assistant can consume it with the discoverable
`manual_region_qa` contract from `ricebowl de creator-api --json`, but image
sharing always requires a separate user decision. Changing the output size,
current render, reference or region geometry, or changing the comparison policy,
invalidates the current measurement. Changed policy, regions or reference also
clear the correction history; a saved revision of the same draft preserves
annotations and comparable past measurements. Switching drafts/references
discards temporary marks.
No active desktop changes and no resident analysis process are involved.

**Still open:** trusted semantic icon/menu recognition, unattended iterative
automatic correction, multi-monitor/fractional scaling hardware QA,
focus and real interaction testing of reconstructed rices.

#### Rice Creator 0.5 — private font and icon assets

Creator 0.5 adds a **Visual asset library** in the inspector. Import original
or appropriately licensed `.ttf` faces (TrueType outlines, maximum **1 MiB**)
and **48×48 8-bit RGBA** `.png` desktop shortcut graphics (maximum **128 KiB**).
The file picker never installs a system font, changes XFCE icon themes or
reads an arbitrary recipe-supplied path. Each import verifies file ownership,
permissions, format and size, then writes immutable owner-private bytes
addressed by SHA-256 and a separate immutable declared-attribution record.
Name, author, license, origin and source reference are visible in the Creator;
these declarations are **not** an independent verification of legal rights.

One schema-v11 `artwork.font` selects the native text font; each action key
(`applications`, `terminal`, `lock`) under `artwork.icons` selects an optional
custom desktop shortcut image. `builtin` is always available. Existing recipe
versions v1–v10 are still accepted, and existing saved drafts can be upgraded
to a **new private v11 revision** without overwriting the old file. The current
native Rust RicePlate renderer validates the private assets by permission,
type, size and SHA-256 before creating Wayland surfaces, caches glyph masks at
startup and draws the PNGs in the existing focusable shortcut rectangles.
It does not promise full Unicode shaping, custom system-wide icon themes or
font support in the Waybar fallback; that fallback retains standard fonts.

**RicePack v4** is selected when the exported recipe actually references a
private font or shortcut icon. The deterministic, uncompressed archive carries
only referenced `assets/font.ttf` and/or `assets/icons/{action}.png` files,
their original SHA-256 identities and declared attribution; a private PNG
wallpaper can coexist in `assets/wallpaper.png`. Archive names, file types,
size, contents, recipe semantic fingerprint, owner and mode are checked before
installing assets or the recipe. Import never activates the rice. Legacy
bundled-only exports remain v2 and wallpaper-only exports remain v3 for byte
compatibility. Visual appearance needs actual multi-DPI Wayland hardware QA.

The **Wayland RicePack v2** is a reproducible, local `.ricepack` ZIP with exactly
`ricepack.json` (format version, recipe identity, SHA-256 checksums and declared
provenance) and `recipe.json` (canonical schema-v1–v11 recipe). There is no
unpacking arbitrary archive paths or executing commands. Existing *bundled*
wallpapers are referenced by known IDs only. V2 records their exact SHA-256.
**V3** additionally carries one locally imported PNG wallpaper as the exact
third entry `assets/wallpaper.png` for a schema-v6 recipe. Its SHA-256-derived
`asset-…` ID is verified on import and runtime resolution, and the image is
stored separately as a private `0600` file. **V4** additionally supports the
limited schema-v11 font and desktop icon assets described below. Commands and
scripts remain forbidden. Older v1/v2/v3 packs remain readable;
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

#### Explicit live Rice switching (opt-in Wayland session only)

Inside an already running RiceBowl labwc session, review a built-in or
imported recipe first, then explicitly activate it without logging out:

```bash
ricebowl de creator-live-status --json
ricebowl de review --recipe chrome --json
ricebowl de creator-live-apply --recipe chrome \
  --expect-sha256 REVIEW_SUMMARY_SHA256 --expect-active classic --json
ricebowl de creator-live-restore --expect-active chrome --json
```

Replace `REVIEW_SUMMARY_SHA256` with the `summary.semantic_sha256` returned by
the preceding review; it must be exactly 64 lowercase hexadecimal characters.
The current session supervisor handles the request over an owner-private Unix
socket below `XDG_RUNTIME_DIR`, named for the current `WAYLAND_DISPLAY`.
Only installed IDs are accepted; absolute file paths and recipe commands are
not. The transaction preflights the recipe and wallpaper, starts a replacement
panel and swaybg, checks that they survive initial startup, reloads the
**private** labwc root menu, persists the next-login choice under the existing
selection lock, then stops the previous panel/background. In a **nested preview**
the live change stays temporary and does not persist the next-login choice.
A failure before commit retains the old components and restores the old menu. `restore` offers
one previous live rice; a restarted session can also use a hash-pinned previous
selection (or a built-in). If the newly active panel later crashes, the
supervisor tries one automatic live restore before falling back to Waybar.
JSON exits are `0` on success and `2` for a rejected/failed request.

This never touches an XFCE/X11 session, global labwc configuration or arbitrary
third-party apps. It does not yet transactionally theme RiceField or Taskotto,
prove full Wayland frame/input readiness, or guarantee recovery from power
loss. Test with the nested opt-in labwc session first, and retain the normal
XFCE login as the physical rollback path.

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
invalid recipe still fails before launching labwc. This selection affects the
Wayland shell layout; full cross-application desktop switching remains open.

Imports accept owner-controlled `0600` or `0644` regular `.json` files,
reject symlinks, unsafe directories, invalid schemas, reserved IDs and
duplicate names, and store the result privately in
`$XDG_CONFIG_HOME/ricebowl/recipes/` (or `~/.config/ricebowl/recipes/`).
Exported files are `0600` and existing files are never overwritten. Share
the exported JSON using your normal file-transfer tool; it contains no
executables or assets. The experimental Wayland `.ricepack` above adds portable
integrity/provenance metadata and one bounded PNG, **not** full cross-component
composition, a complete asset suite or cross-application live transaction/rollback.

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

This is an explicit developer opt-in. When its optional native package is
installed in `/usr/bin`, the login manager additionally offers the separate
**Native Wayland Preview** choice described above; the regular Wayland
Preview still defaults to Waybar. The temporary Waybar dependency remains
installed and available for recovery: if
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
