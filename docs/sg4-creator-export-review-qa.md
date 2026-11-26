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
- **Open visual finding (belongs to WP4.4 tolerances):** Orbit's template uses
  `font_scale` 2 in the fixed 320 px menu, so labels are cut without a marker
  ("Applicatio", "Explo", "Sessi", the Find/Saved buttons show "F"/"S"); the
  accessible names stay complete. The same bounded truncation exists in the
  drawing code for every recipe.
- Not covered: pointer drag of shortcuts, IME in these menus (SG5), multi-output
  and physical-device behaviour, the Creator GUI click-through: the GTK Creator exists, but a real export->import run through its file choosers under labwc is still open (the smoke calls the same `creator_workspace`/`pack` functions the GUI buttons call).

## Remaining blocking SG4 sign-offs

- Exact-head native CI success and archived, decoded labwc captures for both
  imported rices on all four geometries.
- Approved, versioned per-output reference captures with reproducible
  geometry, clipping, text and hit-target tolerances; interactive Wayland
  pointer/keyboard, error-state, popup and accessibility checks. A static
  PNG cannot validate those interactions.
- Real GUI export→import and Creator-exit→supervisor apply/restore, including
  terminated Creator, interrupted journal, malformed configuration and
  subsequent login/restart, using controlled disposable sessions. Python
  supervisor tests do not alone certify a real compositor.
- Independent rights audit for every artwork, font, icon, wallpaper and
  attribution chain; the `rights_independently_verified` field remains false.
- Integration lane review of this draft, current-main rebase if necessary,
  source-locked CI run and explicit merge authorization.

**Status:** SG4 remains **2/4** in the source evidence index until every
blocking criterion is proven with real artifacts.
