# SG4 — Creator reviewed export and native handoff (draft QA, 19 Nov 2026)

Scope: Owner lane for Creator/RicePack, no shell core, compositor renderer,
shared CI workflow or login-session changes. This document records executable
checks and unresolved acceptance; **it does not close SG4**.

## GUI workflow (new)

1. Make a private Heritage or Orbit draft, edit the real panel/layout/assets,
   and **Review & save** a version. No setting changes yet.
2. **Render preview** displays pixels from a supervised headless labwc
   process. The schematic composition is not screenshot evidence.
3. **Export RicePack** chooses an output, builds a temporary, owner-private
   self-contained pack, validates its archive/manifest and presents a GTK
   review of every embedded wallpaper, font and icon attribution, declared
   license and SHA-256. The export button stays disabled until the reviewer
   explicitly acknowledges the limits of such a declaration.
4. Publishing rechecks the saved version and archive integrity and atomically
   no-overwrite publishes the **exact bytes shown in the review**, not a
   second export built after confirmation. Cancel writes no destination.
5. **Import RicePack** uses a separate read-only preflight and a locked final
   import; **Edit installed rice** makes a new private editable copy.
   Install and live apply require separate confirmations, and restore is
   delegated to the same Wayland supervisor. Creator process lifetime does
   not own the active Wayland backend.

This release review is *not* a license clearance service. Complete SPDX-like
declarations and cryptographic integrity do not establish legal rights.
Unattributed packs are marked as incomplete. Independent asset ownership,
license conditions, source references and distribution permission remain a
blocking human sign-off before public publication.

## Execution and artifact contract

Run the code-only checks on the PR's final SHA:

```sh
python3 -m unittest \
  tests.test_sg4_creator_release \
  tests.test_sg4_pack_preflight \
  tests.test_creator_imported \
  tests.test_creator_style_assets \
  tests.test_wayland_creator_handoff -v
```

The repository's existing GTK Creator smoke must additionally exercise the
actual **Review portable RicePack** dialog: export is disabled initially and
can only be confirmed after an explicit acknowledgement. A mock approval
inside that isolated test is not production UI evidence.

With native RicePlate and labwc available as an unprivileged user, run:

```sh
mkdir -p /tmp/sg4-creator-captures
dbus-run-session -- python3 -m scripts.verify_wayland_creator_handoff \
  --output-dir /tmp/sg4-creator-captures
```

This creates **eight real PNG capture files** (Heritage and Orbit at
640×480 1.0, 1366×768 1.0, 1920×1080 1.0 and 1366×768 1.25),
plus a `manifest.json` with exact source commit, semantic and package SHA-256,
full decoded-raster hashes, portable asset hashes, attribution declaration
review and explicit `capture_is_interactive: false` /
`visual_tolerances_approved: false` markers. It must never substitute test
fixtures for real screenshots. The CI workflow already archives the native
handoff directory under `riceplate-native-preview-${{ github.sha }}`
after a successful native job.

The previous four-capture handoff is expanded, not replaced with simulated
pixels. Tests that patch the native renderer use synthetic images **only for
the test contract**, never as archived compositor proof. Actual rendered
captures cannot be asserted until the native job completes at the PR head.

## Apply/restore robustness evidence (WP4.2, local, 26 Nov 2026)

`tests/test_sg4_apply_restore_robustness.py` (16 tests, private HOME/XDG,
sentinel XFCE/login files asserted byte-identical) runs the real Creator
client code (`creator_activation`), a real supervisor process (control socket,
`_LiveSwitch`, journal, selection store) and real SIGKILLs injected at the
actual write boundaries:

- **Killed Creator:** SIGKILL the instant the confirmed apply (or restore) is
  written to the socket. The supervisor completes it exactly once, stays up,
  selection/journal/menu agree, and a new Creator process restores the
  original rice; a stale restore token is refused.
- **Interrupted journal:** kill before the journal is linked (only an unused
  temp file remains), after a complete journal but before the selection commit
  (rolled back to `unchanged`), and after the selection commit (restored to the
  exact prior pinned state). A torn/empty journal is never applied or guessed
  at: the login falls back to classic, the saved selection is left untouched,
  further live switching is refused (`recovery_required`) and the operator hint
  names the file to inspect and remove. The same crash points exist for RicePack
  import (pending archive, receipt, recipe): no partial rice is loadable or
  stageable until `pack-recover` rolls the exact archive forward; a torn or
  tampered pending archive stays blocked.
- **Malformed configuration:** truncated/empty/garbage/oversize/wrong-ID/
  group-readable/symlinked installed recipes, corrupt selection state
  (truncated, duplicate keys, unknown version, path IDs, mode, symlink), unsafe
  or symlinked recipe directory, corrupt provenance receipts. Each fails closed
  with no spawned component, menu/selection/journal untouched; the running rice
  stays active and restorable. A FIFO planted over the selection, selection
  lock or an installed recipe previously **hung** the reader in `open()`
  (login/supervisor); the opens are now `O_NONBLOCK` and refuse non-regular
  files. A corrupt receipt blocks export but not applying the local rice.
- **Next login:** a staged selection, a confirmed live apply and a killed
  supervisor are read back by a new process exactly as confirmed (ID and
  semantic SHA-256); a rolled-back stage, a stale-review stage and a failed
  live apply never reappear.

Limits: compositor children are in-process stand-ins and no real labwc was
started, so this does not replace the real-compositor Creator apply/restore
smoke or hardware checks. A damaged journal requires a manual removal (no
automated clearing, by design). Results: three passes of the new module, full
suite 2000 tests OK (4 skipped).

## Interactive evidence for both imported rices (WP4.3, local, 26 Nov 2026)

"The two imported rices" are the **Heritage Composer** (bottom taskbar, tabbed
menu) and **Orbit Composer** (top panel, sidebar menu) Creator templates, the
same pair the native handoff captures (see above). `scripts/smoke_sg4_imported_rices_labwc.sh`
(about 80 s, wired into the native workflow from December) drives both with
real input on a disposable headless labwc 0.7.1 and the real `riceplate-native`
release binary. Every rice goes through the real Creator backend first
(`scripts/sg4_imported_rices_setup.py`: draft + saved revision, verified RicePack
export under an *author* profile, read-only preflight and locked import into a
different, fresh profile; the import changes no selection). Only the imported
IDs are used afterwards. Private HOME/XDG/runtime and D-Bus session, a PATH with
logging shims only (no real `foot`/`fuzzel`/`nmcli`/`wpctl`).

**Stage `apply`** (supervised `launcher.py de start --nested --panel native`):
Creator live apply classic -> imported rice (`creator-live-apply` with the
reviewed SHA-256, compositor-frame acknowledged), exactly one native shell for
that recipe file, panel pixels differ from the classic panel, the real pointer
opens the rice's own launcher menu, Down/Escape close it, a pointer click on a
menu row runs the exact helper once, `creator-live-restore` returns to classic
(imported shell gone, classic panel pixels restored). After `labwc --exit`: no
process, no changed file anywhere in the private HOME/XDG profile (content
digest before/after), no runtime-dir leftovers, saved selection still classic.

**Stage `input`** (per rice, directly started native shell with the AT-SPI
bridge; see limits):

| Area | Receipt (both rices unless noted) |
| --- | --- |
| Primary launcher/menu | pointer click opens it (pixels + AT-SPI `menu`); Down moves AT-SPI focus Applications -> Terminal; Return runs `foot` once and closes; keys afterwards reach nothing; pointer click on the Terminal row; AT-SPI `doAction` on Terminal; Escape closes without a call; Return on Applications reaches the external launcher once |
| Group switch | Right moves to the Session group; **Log out is exposed as "..., unavailable" with no AT-SPI action** (outside a labwc-managed session) |
| Popup | clock click opens the calendar dialog; AT-SPI "Next month" changes the month; Escape dismisses |
| Desktop shortcut | pointer click and AT-SPI `doAction` each run the bound action once |
| Unsupported capability | with no `nmcli`/`wpctl`: "Wi-Fi, N/A, unavailable" (Heritage also "Mute, N/A, unavailable") expose no action; clicks reach no provider; no failure notice |
| Error path (helper) | `ricebowl de lock` exits 3: one attempt, a painted "Command / Could not run" notice and exactly one AT-SPI alert, self-clearing after about 4 s, no replay; the next lock works |
| Error path (provider) | a failing `nmcli` toggle: exactly one attempt, state unchanged, "Wi-Fi, On, failed" (and a differently painted caption), retry works ("Off"), AT-SPI `doAction` toggles back; Heritage Mute likewise |
| Smaller screen | at 640x480 each recipe's compact layout applies (Heritage keeps the clock; Orbit drops it for the audio status; Wi-Fi/Mute hidden), the launcher menu opens fully inside the output, Down+Return runs Terminal |

Gate: two consecutive full local passes; `tests/test_sg4_imported_rices_smoke.py`
runs the real author/export/import helper without a compositor.

Platform limits and findings (nothing here is fixed by the smoke):

- A nested supervised session never enables the AT-SPI bridge (by design:
  previews do not own accessibility), so the AT-SPI receipts use a directly
  started shell (`RICEBOWL_DE_NESTED=0`, `RICEBOWL_DE_SCREEN_READER=1`) on the
  same imported recipe files; the compositor + supervisor apply is covered by
  stage `apply` with pixels, the process table and real input only.
- The harness renews its virtual keyboard after each supervisor-driven shell
  replacement (labwc 0.7.1 + `wtype`, WP0.1); a physical keyboard is unaffected.
- The native menu has no click-away dismissal (a click on the desktop leaves it
  open); dismissal is Escape, the close button or the launcher.
- The desktop shortcut context menu (right click) is a Luna-only feature; these
  rices do not offer it, so none is claimed.
- **Visual finding fixed (27 Nov):** Orbit's template uses `font_scale` 2 in the
  fixed 320 px menu, and labels used to be cut with `.chars().take(n)` without a
  marker ("Applicatio", "Explo", "Sessi", Find/Saved shown as "F"/"S"). All native
  menu, popup and desktop-widget label cuts now go through one shared helper
  (`text_render::fit_cells`, a grapheme-safe wrapper over `fit_rice_text`), so an
  overflowing label ends in an ellipsis ("Applicati…", "Expl…", "Sess…", "F…");
  labels that already fit are byte-identical, and the bitmap face gained the
  missing U+2026 sprite (it used to fall back to `?`). Rust unit tests cover the
  helper and a painted Orbit-style sidebar row; the Orbit stage of
  `smoke_sg4_imported_rices_labwc.sh` asserts it on real `grim` pixels
  (`sg4_menu_ellipsis_check.py`: last cell = the three-dot sprite, the cell before
  it = a letter) while the AT-SPI names stay `Applications`/`Terminal` in full.
  What is still WP4.4: approved per-output tolerances.
- Not covered: pointer drag of shortcuts, IME in these menus (SG5), multi-output
  and physical-device behaviour. This smoke imports through the same backend
  functions the GUI calls; the GTK Creator's real file-chooser click-through is the
  next section.

## Creator GUI export -> import round trip (WP4.2, 27 Nov)

`scripts/smoke_sg4_creator_gui_roundtrip_labwc.sh` stage 1 (about 30 s; wired into
the native workflow on 27 Nov, runs from December) starts the real `launcher.py creator` window on a headless labwc
(`GDK_BACKEND=wayland`, 1920x1080 so the grown window fits, every window placed at
0,0 without server decoration by a `windowRule` so AT-SPI window coordinates map to
output pixels) and drives it through `sg4_creator_gui_roundtrip_driver.py`:

| Step | Receipt |
| --- | --- |
| Author profile | *Heritage Composer* creates a private v11 draft; the real *Export RicePack…* chooser takes the destination path in its name field; the *Review portable RicePack* dialog keeps *Export reviewed bytes* disabled until the acknowledgement is ticked; the pack carries the draft's ID and semantic SHA-256; selection stays `classic`; the status line says it is not installed or applied |
| Malformed packs (fresh importing profile) | a garbage file and a truncated archive, chosen through the real *Import RicePack…* chooser, each give `RicePack invalid_archive: Corrupt or invalid RicePack archive. No session was changed.`; no confirmation dialog; the profile's config/state tree is byte-identical, no installed rice, no draft, nothing RiceBowl-owned under HOME |
| Valid pack | the confirmation names the ID and SHA-256 prefix and says neither desktop is changed; *Import and edit* installs exactly one rice, opens one editable copy with a new ID, selection stays `classic` |
| Identity | the installed recipe and the authored draft are equal after the product's strict validation (21 fields); the stored JSON differs only by the omitted default `menu.presentation: tabs`; the installed ID/semantic hash equal the authored ones |
| Preview | *Render preview* shows the real native capture of the imported rice (caption `Native RicePlate · 1366 × 768 · scale 1.0`, its Classic Teal desktop on screen), not the schematic |

Platform notes (honest limits): a `wtype` key sent alone or as the last key of a call
does nothing in a GTK3 toplevel (GDK3 ignores the highest keycode of `wtype`'s throw-away
keymap for key bindings; a trailing pad key fixes it, see WP3.1), so no GTK keyboard
traversal is claimed for these dialogs. The buttons that open a
modal chooser/dialog are pressed with **real compositor pointer events**, because an
AT-SPI `doAction` that opens `Gtk.Dialog.run()` makes the application's AT-SPI
service unresponsive while the dialog is open (reproduced with a plain
`MessageDialog`); inside the dialogs the driver uses AT-SPI actions, EditableText
and pointer clicks on the places sidebar and file rows. The Creator window is
taller/wider than a 1366x768 output once a draft was loaded (minimum request about
1530x1030 px), which is why stage 1 runs at 1920x1080. That layout limit is **fixed in
the product on 27 Nov** (see the next section); stage 1 stays at 1920x1080 only because
its native *Render preview* capture is a 1366x768 image.

## Creator GUI install / apply / restore dialogs (WP4.2, 27 Nov, local)

Stage 2 of the same script starts a REAL supervised nested session
(`launcher.py de start --nested --panel native --recipe classic`: real labwc, the real
`riceplate-native` shell, the real live supervisor socket) at **1366x768** and drives the
real Creator in that session's profile. The only seam is a `labwc` wrapper on `PATH`
that appends the same `windowRule` as stage 1 (window at 0,0, no server decoration) to
the session's private `rc.xml` before the real labwc starts; `--exit`/`--reconfigure`
pass through. Session tools `foot`/`fuzzel`/`gio`/`ricebowl` are logging no-op shims.

| Step | Receipt |
| --- | --- |
| Window fits | with a draft loaded the Creator frame is 1280x696 at 0,0, inside the 1366x768 output; toolbar and status line stay fixed, the editing panes scroll |
| Install | *Install / switch…* (menu button) -> *Install saved version…* (real pointer clicks) -> the real confirmation dialog names the ID and SHA-256 prefix and says neither desktop changes; *Install version* -> `Installed <id>. No desktop or login changed.`; exactly that rice is installed; selection and running desktop still `classic` |
| Negative 1: cancelled apply | *Apply in Wayland…* -> dialog names the ID, `Current rice: classic` and `nested session; the choice will not persist` -> *Cancel* -> `Live change cancelled. Desktop unchanged.`; supervisor still `classic`, no shell for the rice, panel pixels unchanged |
| Negative 2: refused after confirmation | the desktop is moved by the CLI while the dialog is open; *Apply live* -> `Live change not confirmed: Active rice changed; review again` (never `Active Wayland rice`); the supervisor keeps exactly the state the other caller left |
| GUI restore | *Restore previous rice…* -> dialog names `Current: <id>` / `Restore: classic` -> *Restore live* -> `Active Wayland rice: classic. …`; supervisor `classic`, the rice's native shell is gone |
| Real apply + restore | *Apply live* -> `Active Wayland rice: <id>. …`; supervisor `active=<id> previous=classic`, exactly one `riceplate-native` on that recipe, panel pixels differ from classic, nothing persisted for next login; *Restore live* -> classic again, shell gone, panel pixels equal the classic panel |
| Negative 3: supervisor unavailable | a Creator whose `WAYLAND_DISPLAY` is a second name for the compositor socket has no `ricebowl-live-<display>.sock`: *Apply in Wayland…* -> `Live change unavailable: No responsive RiceBowl live Wayland supervisor`; no dialog, session untouched |

Product bugs found by this pass and fixed (tests: `tests/test_creator_window_size.py`):

1. The *Install / switch…* popover opened as an **empty bubble**: a `Gtk.Popover`'s
   content is not reached by the window's `show_all()`. Only programmatic `clicked()`
   calls had exercised the menu before.
2. The editing panes demanded about 1530x1030 px, so the window ran off a 1366x768
   output (the right inspector and the toolbar's Render/Export buttons were clipped,
   the foot of the sidebar unreachable). The panes now scroll (`creator-main-scroll`),
   the default size is clamped to the output (`initial_window_size`), and the menu
   button's popover opens upward (a downward popover is clipped at the sidebar foot).

Limits (honest): confirmation dialogs are real, but the buttons are pressed by AT-SPI
`doAction` inside the dialog and real pointer events outside (see above); no GTK
keyboard traversal is claimed. A *nested* session only: a full-login apply (which
persists the next-login selection) is the 4.3 CLI path and physical-device work. The
horizontal minimum of the editing panes (about 1530 px) is unchanged: below that width
the panes scroll horizontally rather than shrink.

## Remaining blocking SG4 sign-offs

- Exact-head native CI success and archived, decoded labwc captures for both
  imported rices on all four geometries.
- Approved, versioned per-output reference captures with reproducible
  geometry, clipping, text and hit-target tolerances; interactive Wayland
  pointer/keyboard, error-state, popup and accessibility checks. A static
  PNG cannot validate those interactions.
- ~~Real GUI export→import and Creator-exit→supervisor apply/restore~~ proven
  locally (27 Nov): terminated Creator, interrupted journal, malformed configuration
  and restart in `tests/test_sg4_apply_restore_robustness.py`; the GTK export→import
  and the install/apply/restore dialogs above. Exact-head CI and keyboard traversal
  of the GTK Creator remain open.
- Independent rights audit for every artwork, font, icon, wallpaper and
  attribution chain; the `rights_independently_verified` field remains false.
- Integration lane review of this draft, current-main rebase if necessary,
  source-locked CI run and explicit merge authorization.

**Status:** SG4 remains **2/4** in the source evidence index until every
blocking criterion is proven with real artifacts.
