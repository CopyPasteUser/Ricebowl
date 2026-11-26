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
| 1.2 | Taskbar/window: two-rice minimize/maximize/close, transient loss/restart | Real labwc receipts in both rices | L! (0.2) | S |
| 1.3 | Desktop/files: multi-select, drag, permission denied, focus lost, both rices | Negative + recovery receipts | L | S |
| 1.4 | Launcher empty/error/busy in both rices | Real input; no stale action after empty/error | L! (0.1) | S |
| 1.5 | System controls and notifications: provider unavailable/denied/restart under labwc | Shared with SG2/SG3 fixtures; both rices. **Status controls DONE locally:** `scripts/smoke_sg1_status_labwc.sh` (Luna tray menus + schema-v7 panel controls with private `nmcli`/`wpctl` shims; Chrome asserted read-only; not yet in a workflow). Notifications and provider restart still open | L | S |
| 1.6 | Luna clock tray: denied/unavailable provider, focus loss | End-to-end smoke | L | S |
| 1.7 | Remote SNI invalid secondary click on Chrome, end to end | Smoke receipt | L | S |
| 1.8 | Hotplug and scale change while menus are open; provider update during input | Deterministic smoke, no stale surfaces | L | O |
| 1.9 | Finish PR #601 | Local exact-head run, guarded self-merge per governance | L | S |
| 1.10 | **DONE (wired, runs from Dec):** wire `smoke_sg1_window_recovery_labwc.sh`, `smoke_sg1_status_labwc.sh` and `smoke_riceplate_windows.sh --chrome` into the native workflow (found unreferenced by WP1.1); integration-lane file | Workflow step exists | L (edit) / CI | S |
| 1.11 | Formal evidence | Exact-head + exact-main runs | CI | – |

## SG2 — RiceSpice (2/4)

| WP | Task | Done when | Where | Model |
| --- | --- | --- | --- | --- |
| 2.1 | **DONE:** [inventory](sg2-adapter-state-inventory.md) (186 cells: 93 covered, 14 partial, 35 gaps). Matrix per adapter (display, input, network, audio, Bluetooth, accessibility, power, time/NTP) × {verified readback, authorization denied, provider disconnected/unavailable, rollback}. A rough grep suggests input, Bluetooth, accessibility and NTP have the fewest co-located negative tests; verify | Table with test links and gaps | L | S |
| 2.2 | Fill the gaps with fake-provider unit tests plus disposable D-Bus tests | Every cell covered or explicitly unsupported in the UI | L | S |
| 2.3 | Check status of candidates #552 (NM post-write uncertainty) | Merged with evidence, or reworked | L | S |
| 2.4 | GUI pass per page in headless labwc showing denied/unavailable/busy visibly | Real GTK GUI under labwc, not CLI only | L | S |
| 2.5 | Whole matrix at one final `main` SHA | Exact-main run | CI | – |

## SG3 — RicePop (2/4)

| WP | Task | Done when | Where | Model |
| --- | --- | --- | --- | --- |
| 3.1 | Inbox/OSD live updates, keyboard and AT-SPI action semantics in both rices | Real Mako + labwc + AT-SPI receipts | L | S |
| 3.2 | Privacy (no unexpected persistence, bodies cleared), restart, localization and rendered-text matrix | Matrix with negative tests | L | S |
| 3.3 | Check status of candidate #553 (`ActionInvoked`) | Merged with evidence, or reworked | L | S |
| 3.4 | Real Mako 1.11 matrix | Local after 0.5, otherwise CI | L (0.5 done) | S |
| 3.5 | Wire `smoke_sg3_ricepop_native_labwc.sh` into the native workflow; needs a Mako 1.11 build step there (as `smoke_real_mako_111.sh` does) | Workflow step exists | L (edit) / CI | S |

**Local evidence, 26 Nov (progress on 3.1/3.2/3.4, nothing closed; SG3 stays 2/4).** New `scripts/smoke_sg3_ricepop_native_labwc.sh` + `smoke_sg3_ricepop_native_driver.py` (Luna only; real labwc, real `wtype` keyboard and pointer, native `riceplate-native`, ONE real Mako 1.11 started with the shipped config, external AT-SPI; 17 `PASS:` receipts, 3/3 local runs, about 55 s, **not wired into any workflow**; needs Mako 1.11 on `PATH` (1.8 never emits `ActionInvoked` for `makoctl invoke`), the release binaries, `wtype`, `grim`, `pyatspi`, PIL). Newly covered: live arrival, same-ID replacement and external close with the native inbox open (no manual refresh, via the 3 s open-only refresh); selected row vanishing leaves no selection and Delete cannot retarget; real Up/Down/Tab, Return (detail), action pick, Delete; exactly one real `ActionInvoked` for the keyboard-selected key; AT-SPI `doAction` open-detail, invoke and dismiss; host SIGKILL while open (unavailable state, rows, detail and bodies gone from the whole accessibility tree), restarted Mako empty (active and in-memory history), recycled ID with identical text on the new owner: stale Return/Delete reach nothing, then refresh + fresh selection invokes once; closing the inbox leaves no body in the accessibility tree; a unique private-text canary is absent from every file under HOME, XDG and the runtime dir and no notification-state files appear; unsupported script (Tifinagh) keeps its real text in AT-SPI while the pixels equal literal `?` glyphs and differ from blank. Still open: Chrome (no Notifications entry), the OSD, localization beyond the existing unit tests, CI/exact-head, #553 status, native busy/pending-mutation state.

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
| 5.3 | Cross-app clipboard on final source | `wl-copy`/`wl-paste` smoke green | L! (0.2) | S |
| 5.4 | **Rust DONE locally (27 Nov):** installed `fonts-lohit-deva` / `fonts-wqy-microhei`, real GSUB/GPOS and grapheme caret tests, explicit `FONT UNAVAILABLE` failure; CI apt line updated. **Compositor positive OPEN:** no product path renders a shaped Indic/CJK face (private recipe fonts unshaped, 1 MiB cap). Positive Hindi/CJK font coverage with measured glyph/caret positions (installable Noto fonts) | Rust + compositor pixel/metric tests | L | O |
| 5.5 | **DONE locally (27 Nov, 3/3):** `doAction` on the Rename menu item and OK/Rename/Cancel buttons (new accessible controls), refused/cancelled/confirmed transitions with file-system receipts. AT-SPI action invocation for Rename; dialog transitions | External AT-SPI client receipts | L | S |
| 5.6 | **DONE locally (27 Nov, 3/3):** Hindi/CJK/Hangul in the real Run editor: AT-SPI real text + caret, `grim` pixels equal one `?` per grapheme, never coverage; Rust matrix too. Fallback/missing-font matrix with an accessible client | Matrix complete; missing glyph never reported as success | L | S |

## SG7 — final software acceptance (1/4), last

| WP | Task | Done when | Where | Model |
| --- | --- | --- | --- | --- |
| 7.1 | Finish PR #596 (live-PR pinning, receipt IO) | Local tests + guarded merge | L | S |
| 7.2 | Longer headless resource/leak soak (idle PSS/CPU over time) | Documented local measurement; not a hardware benchmark | L | S |
| 7.3 | Unsupported/error states documented across components | Reviewed list | L | S |
| 7.4 | Exact final `main`: all workflows, strict portal, SG7 dossier | Only after SG1–SG5 merges | CI | – |

## Suggested order

WP0 → inventories 1.1 and 2.1 (cheap, make "done" measurable) → SG5 and SG1
(hardest, mostly `O`) → SG2/SG3 (mostly `S`) → SG4 (needs owner decisions
4.4/4.5) → SG7 (December, CI). One lane and one WP per session.
