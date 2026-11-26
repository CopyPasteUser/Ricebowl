# SG1–SG7 — remaining, testable work packages

Snapshot: 26 November 2026, `main@97c79af`. Authority stays with
[issue #417](https://github.com/CopyPasteUser/Ricebowl/issues/417) and the
[evidence index](sg1-sg7-evidence-progress.md); this file only breaks the
**12 open checkpoints** into work packages (WPs) with a definition of done.
It closes nothing and changes no percentage. Open PRs at snapshot: #601 (SG1),
#596 (SG7).

**Where:** `L` = runnable locally in a disposable headless labwc session
(the `ricebowl` cloud environment: labwc 0.7.1, Mako 1.8, non-root `rbdev`,
helpers `rb-sync`/`rb-run`). `L!` = local, but blocked by WP0 first.
`CI` = needs exact-head/exact-main hosted Actions (not before December 2026).
`OWNER` = owner decision or review. Physical hardware is not an SG item.
**Model hint:** `S` = routine fix/test (Sonnet, medium), `O` = diagnosis,
races, protocol or security-sensitive design (Opus, high).

Formal closure of every SG still requires its CI evidence; local green is
the prerequisite, not the acceptance.

## Local baseline (measured 26 Nov 2026, non-root, headless labwc 0.7.1)

| Result | Checks |
| --- | --- |
| PASS | Python suite (1,949 passed via pytest; CI uses `unittest discover -s tests`), Rust `cargo test` (503), `smoke_sg1_sni_labwc`, `smoke_sg1_window_recovery_labwc`, `smoke_riceplate_windows --luna`, `smoke_riceplate_luna_autohide`, `smoke_riceplate_multioutput`, `smoke_luna_hotkeys`, `smoke_wayland_shared_rice_engine`, `smoke_luna_settings_labwc`, `smoke_creator_gui_labwc`, `smoke_wayland_session` |
| Fixed since snapshot | `smoke_riceplate_native` (WP0.1, 3/3 local passes), `smoke_riceplate_windows --xwayland`, `smoke_wayland_clipboard`, `smoke_luna_window_chrome` (WP0.2), `smoke_luna_atspi` with the CI-pinned labwc 0.7.2 (WP0.3), opt-in `smoke_riceplate_desktop_focus` (WP0.4) |

### Running checks locally (ricebowl environment)

```sh
rb-sync                                    # copy checkout to /home/rbdev (keeps target/)
rb-run env XDG_RUNTIME_DIR= dbus-run-session -- xvfb-run -a \
  python -m unittest discover -s tests     # CI-equivalent Python suite
rb-run sh -c 'cd components/riceplate-wayland && cargo test --locked'
rb-run env XDG_RUNTIME_DIR= dbus-run-session -- sh scripts/<smoke>.sh
RB_PATH_PREFIX=/opt/labwc-sg5 rb-run env XDG_RUNTIME_DIR= \
  dbus-run-session -- sh scripts/smoke_luna_atspi.sh   # SG5 IME needs labwc 0.7.2
```

Run compositor smokes one at a time: several use `pgrep -u` and timing
budgets. Release binaries must exist in the synced `target/` (build as root
in `/home/rbdev/Ricebowl/components/riceplate-wayland`, then `chown`).
| Environment limit | `smoke_wayland_portals` (no FUSE for the document portal, no running PipeWire). `smoke_real_mako_111` runs locally once `libnotify-bin` is installed (WP0.5) |

## WP0 — make the local baseline trustworthy (do first)

| WP | Task | Done when | Where | Model |
| --- | --- | --- | --- | --- |
| 0.1 | **DONE (harness):** after the active `wtype` keyboard disconnects, labwc 0.7.1 sends a new client `wl_keyboard.enter/modifiers` without a keymap and Fuzzel 1.9.2 segfaults in `xkb_state_update_mask`. The smoke now attaches a fresh self-expiring virtual keyboard before each re-open. No RicePlate change; 3/3 local full passes | Done | L | O |
| 0.2 | **DONE (environment):** the session had no locale (POSIX); xterm under XWayland exits immediately without one. CI runners use `C.UTF-8`; `rb-run` now sets it. All three XWayland smokes pass | Done | L | O |
| 0.3 | **DONE (environment):** the menu IME step needs input-method-v2, which stock labwc 0.7.1 lacks; CI builds a pinned private labwc 0.7.2 (`b41af54a`) for this step only. With that build the full smoke passes locally | Done | L | O |
| 0.4 | **DONE:** the opt-in `smoke_riceplate_desktop_focus` failed because `riceplate_focus_probe` never bound the already-announced seat; fixed with the SG5 Rename IME work (`8f20bc4`), smoke passes locally. Still not run by any workflow | Done | L | S |
| 0.5 | **DONE locally (26 Nov):** `smoke_real_mako_111.sh` was not failing on FUSE or the document portal (both only log noise). Failing assertion: `PermissionError: notify-send` because `libnotify-bin` was not installed in the container (CI installs it); the root-only directories in `rb-run`'s `PATH` turned ENOENT into EACCES. With it installed the real Mako 1.11 arrival, inbox, live-update, `ActionInvoked` and crash-restart smoke passes. Fixed: the script now checks its tools up front, and runs on a private bus that cannot activate the portal family (`RICEBOWL_SMOKE_NO_PORTALS`, default for this script only; no portal log lines). Also found and fixed a 1-in-6 flake in the external AT-SPI step (parent serviced each AT-SPI round trip only every 15-20 ms; now blocks in the main loop). 20/20 local passes afterwards | Done | L | S |

## SG1 — shared shell (3/4): every advertised control × every state

| WP | Task | Done when | Where | Model |
| --- | --- | --- | --- | --- |
| 1.1 | **DONE:** [inventory](sg1-control-state-inventory.md) (154 cells: 39 compositor, 40 unit-only, 36 gaps). Inventory every advertised shared control in both rices (XP Luna, Chrome) × {loading, empty, busy, unavailable/denied, error, focus loss, recovery} in the SG1 matrix | Complete table, each cell linked to a test or marked gap | L | S |
| 1.2 | Taskbar/window: two-rice minimize/maximize/close, transient loss/restart | Real labwc receipts in both rices | **DONE (local):** `scripts/smoke_sg1_interaction_labwc.sh` stage `windows` (Chrome and XP Luna): labwc `W-a` maximize/unmaximize with real client geometry, taskbar minimize+restore of a maximized window, labwc `A-F4` close request drops the task, RicePlate SIGKILL + restart re-reads a minimized window and restores it, a window closed while the shell was down leaves no ghost, a same-app-id window afterwards needs one click. The taskbar has no maximize/close control of its own (labwc owns them), so none is claimed. Wired in the native workflow (runs from December) | L | S |
| 1.3 | Desktop/files: multi-select, drag, permission denied, focus lost, both rices | Negative + recovery receipts | **DONE (local, Luna; Chrome has no desktop block):** `smoke_sg1_interaction_labwc.sh` stage `files`: Shift+Down range multi-select pixels, chmod 000 open refused, rename in a chmod 500 Desktop refused with a visible dialog notice, New Folder denied, drag with an unwritable position store snaps back, focus theft revokes the lease (no stale F2/Delete), each case recovers. **Open:** pointer+Ctrl/Shift multi-select (modifiers only reach the shell through the post-click keyboard lease), empty-desktop render, busy (back-to-back) operations, a failed `gio trash` helper is not surfaced after the dialog closes | L | S |
| 1.4 | Launcher empty/error/busy in both rices | Real input; no stale action after empty/error | **DONE (local):** Chrome absent/crashing/busy/empty/Escape were already proven by `smoke_riceplate_native.sh` (`NAT:457-741`) and Luna failing-Exec/missing-TryExec by `smoke_sg1_sni_labwc.sh`; `smoke_sg1_interaction_labwc.sh` stage `launcher` adds Luna slow-helper busy (one launch per gesture), helper error, no-match and idle-Start Return launching nothing for the failed entry, and recovery, with exact `gio` receipts. Errors are log lines only (no visible Start-menu notice exists) | L! (0.1) | S |
| 1.5 | System controls and notifications: provider unavailable/denied/restart under labwc | Shared with SG2/SG3 fixtures; both rices. **Status controls DONE locally:** `scripts/smoke_sg1_status_labwc.sh` (Luna tray menus + schema-v7 panel controls with private `nmcli`/`wpctl` shims; Chrome asserted read-only; not yet in a workflow). Notifications and provider restart still open | L | S |
| 1.6 | Luna clock tray: denied/unavailable provider, focus loss | End-to-end smoke | **DONE (local):** `smoke_sg1_interaction_labwc.sh` stage `clock`: `ricebowl` absent (ENOENT), present but not executable (EACCES), failing (exit 3, one exact-argv call, no replay), keyboard theft by an exclusive external client (menu closes, keys reach only the thief), recovery. Product bug fixed: settings/terminal/Run helper `Child` was dropped (zombie per launch); now tracked by the bounded reaper (unit test + zombie assertion that fails on the old binary). Chrome's clock is read-only (no click reaches a provider). The calendar popup is not covered; errors are log lines, there is no visible notice | L | S |
| 1.7 | Remote SNI invalid secondary click on Chrome, end to end | Smoke receipt | **DONE (local, Chrome and Luna):** `smoke_sg1_interaction_labwc.sh` stage `sni` with the extended `sg1_sni_provider.py` (`--plain`, `item-error`): a secondary press on an open menu row activates nothing (a primary press at the same spot does), an emptied menu paints no popup and falls back to no ContextMenu/Activate, a plain item gets ContextMenu exactly once at the tray icon, a provider error is logged and the next click works | L | S |
| 1.8 | Hotplug and scale change while menus are open; provider update during input | Deterministic smoke, no stale surfaces | **DONE (local):** `smoke_sg1_interaction_labwc.sh` stage `outputs` (own two-output labwc): Luna Start menu and the SNI tray popup (Luna + Chrome) across a scale change (re-laid out, one action per gesture, no ghost frame) and an unplug/re-plug of the hosting output (closes, provider told, no key leaks, clean recovery); provider update during input was already `smoke_sg1_sni_labwc.sh` (relabel/remove). **Product bug fixed:** `output_destroyed` left the Start menu logically open and invisible with keyboard focus, so Return launched its entry; it now closes menu, tray popup and calendar. **Open:** unplug of a different output, new-output hot-add, calendar/context/Run dialog across output changes | L | O |
| 1.9 | Finish PR #601 | Local exact-head run, guarded self-merge per governance | L | S |
| 1.10 | **DONE (wired, runs from Dec):** wire `smoke_sg1_window_recovery_labwc.sh`, `smoke_sg1_status_labwc.sh` and `smoke_riceplate_windows.sh --chrome` into the native workflow (found unreferenced by WP1.1); integration-lane file | Workflow step exists | L (edit) / CI | S |
| 1.11 | Formal evidence | Exact-head + exact-main runs | CI | – |

## SG2 — RiceSpice (2/4)

| WP | Task | Done when | Where | Model |
| --- | --- | --- | --- | --- |
| 2.1 | **DONE:** [inventory](sg2-adapter-state-inventory.md) (186 cells: 93 covered, 14 partial, 35 gaps). Matrix per adapter (display, input, network, audio, Bluetooth, accessibility, power, time/NTP) × {verified readback, authorization denied, provider disconnected/unavailable, rollback}. A rough grep suggests input, Bluetooth, accessibility and NTP have the fewest co-located negative tests; verify | Table with test links and gaps | L | S |
| 2.2 | **DONE locally (26 Nov):** `tests/test_de_sg2_gap_fill.py` (9 adapter tests: N5 `con add` denial, P1 power-profile denial, B3/B4 backend-only refusals, A5 vanished player, I3 Orca missing) and `tests/test_de_sg2_gap_gui.py` (14 real-Gtk tests: N5/N6/N7 dialogs, A1 audio defaults, D5 trial toggle, I1/I2/I3 pages); every inventory `gap` cell is now covered or `n/a` with a reason ([inventory](sg2-adapter-state-inventory.md)). **Product bug found and fixed:** a polkit/AccessDenied refusal of `powerprofilesctl set` surfaced as "outcome unknown"; it is now the typed denial. Fake-provider evidence only; no real polkit/D-Bus acceptance | Every cell covered or explicitly unsupported in the UI | L | S |
| 2.3 | **DONE:** #552 (NM post-write uncertainty) merged 20 Nov 2026; its tests run in the local suite | Merged with evidence, or reworked | L | S |
| 2.4 | GUI pass per page in headless labwc showing denied/unavailable/busy visibly | Real GTK GUI under labwc, not CLI only | L | S |
| 2.5 | Whole matrix at one final `main` SHA | Exact-main run | CI | – |

## SG3 — RicePop (2/4)

| WP | Task | Done when | Where | Model |
| --- | --- | --- | --- | --- |
| 3.1 | **PARTIAL (local, 27 Nov):** XP Luna native inbox: live updates, real-keyboard and AT-SPI action semantics (already 17 receipts) plus the volume OSD from external sink changes (value/bar readback, live update, expiry, negatives, input transparency over the open inbox). Chrome (no native inbox by design): same OSD receipts and the RiceSpice GTK inbox against real Mako 1.11: live arrival/replace/close, AT-SPI `doAction` invoke and dismiss, one real `ActionInvoked`. **Open:** GTK keyboard traversal/Return (a real `wtype` Tab/Return is not delivered to GTK3 toplevels in this harness, even a plain two-button window; GTK inbox keyboard NOT claimed), brightness OSD (needs `/sys/class/backlight`), OSD pointer pass-through, screen-reader announcement of the OSD (not exposed over AT-SPI), CI/exact-head | Real Mako + labwc + AT-SPI receipts | L | S |
| 3.2 | **PARTIAL (local, 27 Nov):** privacy/restart in both rices (bodies leave the accessibility tree on close/navigation/host loss, no canary or state file on disk, recycled ID on a new owner reaches nothing); rendered-text matrix in the native inbox with the real installed fonts (Hindi, CJK, Arabic, Hangul draw real glyphs, never `?`/blank; fonts hidden via the kill switch -> exactly the `?` replacement); German OSD (`LC_ALL=de_DE`) and German GTK accessible names. **Product bug fixed:** wide CJK summaries/bodies ran off the popup edge and silently lost their tail. **Open:** the native inbox/OSD labels are English-only (only OSD is German), Arabic/Hangul negative uses the same rule but no RTL layout check, GTK rendered text is Pango's, CI/exact-head | Matrix with negative tests | L | S |
| 3.3 | **DONE:** #553 (`ActionInvoked`) merged 20 Nov 2026; real-Mako action receipt in `smoke_sg3_ricepop_native_labwc.sh` | Merged with evidence, or reworked | L | S |
| 3.4 | Real Mako 1.11 matrix | Local after 0.5, otherwise CI | L (0.5 done) | S |
| 3.5 | **DONE (workflow step exists; CI run pending):** `riceplate-native.yml` now path-filters the SG3 script, driver and `smoke_real_mako_111.sh`, runs `sh -n`/`py_compile`, builds Mako v1.11.0 from the same source-locked commit (`91c6b799`) and meson options as `smoke_real_mako_111.sh` into `$RUNNER_TEMP` (PATH for the SG3 step only), then runs the smoke under `timeout 150s`. Not yet run on a hosted runner | Workflow step exists | L (edit) / CI | S |

**Local evidence, 26 Nov (progress on 3.1/3.2/3.4, nothing closed; SG3 stays 2/4).** New `scripts/smoke_sg3_ricepop_native_labwc.sh` + `smoke_sg3_ricepop_native_driver.py` (Luna only; real labwc, real `wtype` keyboard and pointer, native `riceplate-native`, ONE real Mako 1.11 started with the shipped config, external AT-SPI; 17 `PASS:` receipts, 3/3 local runs, about 55 s, **not wired into any workflow**; needs Mako 1.11 on `PATH` (1.8 never emits `ActionInvoked` for `makoctl invoke`), the release binaries, `wtype`, `grim`, `pyatspi`, PIL). Newly covered: live arrival, same-ID replacement and external close with the native inbox open (no manual refresh, via the 3 s open-only refresh); selected row vanishing leaves no selection and Delete cannot retarget; real Up/Down/Tab, Return (detail), action pick, Delete; exactly one real `ActionInvoked` for the keyboard-selected key; AT-SPI `doAction` open-detail, invoke and dismiss; host SIGKILL while open (unavailable state, rows, detail and bodies gone from the whole accessibility tree), restarted Mako empty (active and in-memory history), recycled ID with identical text on the new owner: stale Return/Delete reach nothing, then refresh + fresh selection invokes once; closing the inbox leaves no body in the accessibility tree; a unique private-text canary is absent from every file under HOME, XDG and the runtime dir and no notification-state files appear; unsupported script (Tifinagh) keeps its real text in AT-SPI while the pixels equal literal `?` glyphs and differ from blank. **27 Nov addendum (3.1/3.2 still PARTIAL).** The same script now takes a mode: `luna` (26 receipts: the above plus OSD matrix, OSD-over-inbox focus, CJK detail wrap, Hindi/CJK/Arabic/Hangul glyph matrix), `luna-de` (German OSD), `luna-nofonts` (`RICEBOWL_SYSTEM_FONT_FALLBACK=0` -> `?`) and `chrome` (18 receipts: no native inbox, OSD, RiceSpice GTK inbox). A panel restart inside one compositor session loses keyboard delivery after the first replacement, hence one compositor per mode. Private `wpctl`/`pactl` shims feed the OSD; no real audio is touched. Mako 1.11 comes from a private source-locked build on `PATH`. Existing coverage found first: `smoke_ricepop_live_updates.py` (in-process GTK live add/replace/dismiss/`ActionInvoked`), `smoke_ricepop_recovery.py` (GTK host crash), `smoke_real_mako_111.sh` (driver for both), `tests/test_de_notification*.py`/`test_de_ricepop_*.py` (unit), `smoke_riceplate_native.sh` (OSD/inbox pixel previews only). Product fix: `overlay_renderer.rs` fits notification labels to the real painted advance and `ricepop.rs` wraps wide graphemes as two cells. Still open: GTK keyboard traversal, brightness OSD, Chrome/Luna CI run, #553 status, native busy/pending-mutation state.

## SG4 — Creator/RicePack (2/4)

| WP | Task | Done when | Where | Model |
| --- | --- | --- | --- | --- |
| 4.1 | **DONE locally (26 Nov, `main@8f1398c`):** `scripts.verify_wayland_creator_handoff` produced 8 real labwc captures (Heritage/Orbit × 640×480, 1366×768 @1.0/@1.25, 1920×1080) and a manifest with `capture_is_interactive: false`, `visual_tolerances_approved: false`. Needs `target/release` on PATH, as in CI. Still requires CI archive (4.6) | Done (local) | L | S |
| 4.2 | **PARTIAL (26 Nov, local):** killed Creator, interrupted journal (incl. torn journal, RicePack import crashes), malformed config and next-login/restart are proven with real Creator/supervisor processes and SIGKILLs at the real write boundaries (`tests/test_sg4_apply_restore_robustness.py`, 16 tests, 3 passes; full suite 2000 OK). Found/fixed: FIFO over selection/lock/recipe hung `open()`. **Open:** real-labwc Creator apply/restore smoke and real GUI export→import run | Disposable-session tests for each case | L | O |
| 4.3 | Interactive pointer/keyboard/error/popup/AT checks on both imported rices | Real input receipts | L | S |
| 4.4 | Approved reference captures and geometry/clip/text/hit-target tolerances | Owner approves tolerances; then tests enforce them | OWNER + L | S |
| 4.5 | Rights audit of every asset (`rights_independently_verified` stays false until then) | Owner sign-off | OWNER | – |
| 4.6 | Exact-head native capture archive | CI run | CI | – |

## SG5 — text and input (2/4)

| WP | Task | Done when | Where | Model |
| --- | --- | --- | --- | --- |
| 5.1 | **Rename IME + dialog focus leave/re-enter DONE locally** (labwc 0.7.2, 3/3, `smoke_luna_atspi.sh`; see SG5 ledger). Open: menu focus cycle, candidate selection, RTL flows. IME v2→v3 for Rename; focus leave/re-enter; candidate selection; RTL flows | Protocol smoke per surface | L! (0.3) | O |
| 5.2 | **DONE locally (27 Nov):** menu IME (#600) preedit/commit/delete passes for Start search and All Programs, 3/3 `smoke_luna_atspi.sh`; #595 stays open for menu focus cycle, candidate selection, RTL and composition pixels (see SG5 ledger). Confirm menu IME (#600) and issue #595 in the final matrix | Ledger updated with local evidence | L | S |
| 5.3 | **DONE locally (27 Nov, 2/2 `smoke_luna_atspi.sh`, `RB_PATH_PREFIX=/opt/labwc-sg5`):** the Run field already round-tripped external `wl-copy` -> paste and Ctrl+C/X -> `wl-paste`; new receipt adds the Rename field (external `wl-copy` pasted over a selection, typed text copied out and read by an external `wl-paste`). Exact-main/CI and physical-device runs stay open | `wl-copy`/`wl-paste` smoke green | L! (0.2) | S |
| 5.4 | **Rust DONE locally (27 Nov):** installed `fonts-lohit-deva` / `fonts-wqy-microhei`, real GSUB/GPOS and grapheme caret tests, explicit `FONT UNAVAILABLE` failure; CI apt line updated. **Compositor positive DONE locally (28 Nov, 11/11):** trusted `/usr/share/fonts` system fallback (lazy, cached, `O_NOFOLLOW`, regular file <= 32 MiB, rustybuzz + own outline rasterizer): real Run editor paints non-blank Hindi/CJK/Hangul glyphs != `?`, AT-SPI text/caret real; kill-switch run keeps the `?` replacement; RSS +0.6 MB Hindi, +5.1 MB CJK. Exact-head CI and RTL/physical review still open. Positive Hindi/CJK font coverage with measured glyph/caret positions (installable Noto fonts) | Rust + compositor pixel/metric tests | L | O |
| 5.5 | **DONE locally (27 Nov, 3/3):** `doAction` on the Rename menu item and OK/Rename/Cancel buttons (new accessible controls), refused/cancelled/confirmed transitions with file-system receipts. AT-SPI action invocation for Rename; dialog transitions | External AT-SPI client receipts | L | S |
| 5.6 | **DONE locally (27 Nov, 3/3):** Hindi/CJK/Hangul in the real Run editor: AT-SPI real text + caret, `grim` pixels equal one `?` per grapheme, never coverage; Rust matrix too. Fallback/missing-font matrix with an accessible client | Matrix complete; missing glyph never reported as success (replacement half re-proved with the fallback kill switch on 28 Nov) | L | S |

## SG7 — final software acceptance (1/4), last

| WP | Task | Done when | Where | Model |
| --- | --- | --- | --- | --- |
| 7.1 | Finish PR #596 (live-PR pinning, receipt IO) | Local tests + guarded merge | L | S |
| 7.2 | Longer headless resource/leak soak (idle PSS/CPU over time) | Documented local measurement; not a hardware benchmark | L | S |
| 7.3 | **DONE (doc, 26 Nov):** [sg7-unsupported-error-states.md](sg7-unsupported-error-states.md) lists unsupported/denied/unavailable/error states per component (RicePlate panels/launcher/desktop, RiceSpice, RicePop, Creator/RicePack, session/supervisor), each with source and test citations; entries without a test are marked `unverified` and Rust rows were grep-checked, not run | Reviewed list | L | S |
| 7.4 | Exact final `main`: all workflows, strict portal, SG7 dossier | Only after SG1–SG5 merges | CI | – |

## Suggested order

WP0 → inventories 1.1 and 2.1 (cheap, make "done" measurable) → SG5 and SG1
(hardest, mostly `O`) → SG2/SG3 (mostly `S`) → SG4 (needs owner decisions
4.4/4.5) → SG7 (December, CI). One lane and one WP per session.
