# SG1 — shared native shell interaction matrix (XP Luna / Chrome)

**Scope:** software-only, headless labwc. **Integration baseline:** `main@3d4d716b7a9ad45beab2e65d34447648ba26b18d` (2026-11-22). The canonical acceptance criteria remain [#417](https://github.com/CopyPasteUser/Ricebowl/issues/417) and [SG1–SG7 evidence](sg1-sg7-evidence-progress.md). This is a **test coverage ledger**, not a sign-off or a hardware claim.

**Rices:** XP Luna uses schema-v12 columns, desktop, native local tray menus and a wide bottom taskbar. Chrome uses a schema-v1 single launcher shelf with a centered task region and status indicators. Both are rendered by the same Rust RicePlate engine; neither is a duplicate backend.

Legend: **existing** = currently exercised in repo smoke/tests; **PR test** = implemented in this draft, must pass exact-head CI before credit; **gap** = not accepted by this matrix. State verification means action receipt, file/DBus state, process/argv, or explicit native transition log rather than screenshot only.

| Control / scenario | XP Luna | Chrome | What is actually asserted | Remaining acceptance gap |
| --- | --- | --- | --- | --- |
| Panel / launcher pointer | existing | **PR test** | Real labwc pointer; native Luna menu state or external Chrome fuzzel process lifecycle | Cross-scale, all controls |
| Launcher keyboard | existing focus/shortcuts | **PR test** Escape | Compositor `wtype`, Chrome fuzzel exit; Luna native menu and Run editor verified in native smoke | Search results and action activation via keyboard across both |
| App search / paging | **#583 real**: Start pointer → native Search typed by compositor keyboard → reviewed private XDG desktop entry → production Gio Exec receipt | **#573 real**: pointer Chrome launcher → actual Fuzzel filtering → keyboard Enter → private Exec receipt | Independent real process receipts for both structurally different recipes; native Luna wheel/paging and AT-SPI live text tests exist separately | Cross-scale launch/readback and all advertised empty/error/busy states still require SG1 checkpoint 4 |
| Taskbar, window actions | existing | existing | Native XWayland/Wayland task focus smoke, shared window lifecycle | Full two-rice minimize/maximize/close, transient loss/restart matrix |
| Desktop icons / file operations | existing | shared desktop engine | labwc pointer + keyboard, file inventory, rename/Trash/RiceField and multi-output/hotplug smoke | Complete two-rice multi-select/drag/deny/permission and focus-lost matrix |
| SNI / DBusMenu remote menus | **#581 + #583** real owner turnover, primary and secondary pointer, nested keyboard action | **#581 + #583** real owner turnover, primary and secondary pointer, nested keyboard action | Private Gio provider receipts require exactly one new `clicked/21` for each primary activation, reject ItemIsMenu fallback, old-owner stale action and unsafe replay; tests execute under genuine labwc | Empty/disabled/denied/busy/focus and concurrent provider-update matrix remains open as SG1 checkpoint 4 |
| Luna local clock tray action | **PR test** | n/a (Chrome uses common status/tray) | Real labwc right-click + keyboard Return; exact `ricebowl de settings --luna --page timezone` argv in private shim, no host mutation | Denied/unavailable provider and focus-loss handling end-to-end |
| Tray invalid secondary click | existing | shared handler | Real Luna pointer secondary no-activation, primary close; Rust validates button IDs | Remote SNI on Chrome end-to-end |
| Notifications / system controls | existing partial | shared engine partial | Native OSD/RicePop preview and system-status tests | Real provider unavailable/denied/restart, locale/AT-SPI and both-rice focus |
| Empty / disabled / stale actions | **PR candidate**: real labwc SNI disabled/empty/denied/slow and Escape cancellation | **PR candidate**: same real provider states under Chrome labwc | Actual D-Bus ID/mode receipts, no stale clicks after empty/focus exit, denial and delayed layout with explicit recovery | Other shared controls, external focus theft, real simultaneous input+provider update and complete AT-SPI parity still need evidence |
| Focus / hotplug / parallel input | existing selective | existing selective | Native focus handoff to GTK, multi-output, resize, real virtual pointer/keyboard | Explicit mixed DPI and hotplug *during* open menus; simultaneous provider update and input |

## Accepted baseline and focused test candidate (22 November 2026)

- [#573](https://github.com/CopyPasteUser/Ricebowl/pull/573) added a real Chrome Fuzzel keyboard search, Return and private process-execution receipt under labwc.
- [#581](https://github.com/CopyPasteUser/Ricebowl/pull/581) added real XP Luna/Chrome SNI owner-restart and menu action receipts, closed old owner IDs and restored keyboard focus in an explicitly opened remote popup.
- A separate SG1 acceptance gap is the installed-app search-to-execution path in **XP Luna**. A private `XDG_DATA_HOME` fixture provides a real `.desktop` entry and a no-argument executable that records a private receipt. A real labwc pointer opens native Start; compositor keyboard `/sg1witness` selects the application; Enter must dispatch through the production Gio desktop-entry launcher to that executable. Chrome already has the structurally different Fuzzel equivalent in merged #573. Neither path claims physical keyboard acceptance.
- This focused follow-up tests the **separate primary SNI `ItemIsMenu=true` path** on both rices, using a second genuine compositor pointer/keyboard action and an incremental `Event(clicked, 21)` receipt. It rejects false positives from earlier secondary-click receipts and disallows `Activate/ContextMenu` fallback when a valid native menu was available. It does not alter production bindings, provider privileges or XFCE.
- **Acceptance (engineering checkpoint 3 only):** [#583](https://github.com/CopyPasteUser/Ricebowl/pull/583) passed exact-head Python and full Native/Mint CI, then [merged main@48d7ba73](https://github.com/CopyPasteUser/Ricebowl/commit/48d7ba73144c515cf76d225f86ec81a4aeefe6f5) passed exact-main Tests/Native at [#44995952470](https://github.com/CopyPasteUser/Ricebowl/actions/runs/44995952470) and [#44995952471](https://github.com/CopyPasteUser/Ricebowl/actions/runs/44995952471). Remaining state, error, focus, and recovery coverage keep SG1 formally open.

## Fourth-checkpoint negative-state candidate (22 November 2026)

- Both rices now exercise the real disposable D-Bus provider in **disabled, denied, empty, slow and normal** mode through live labwc pointer and keyboard input. Exact private receipts identify real action IDs, provider modes and D-Bus errors, while absent receipts prove revoked actions cannot execute.
- A compositor Escape cancels the menu selection, and deliberate reopen after all negative modes restores a working action. The delayed layout request proves a real pending provider transaction, **not** that the UI visually communicates loading.
- **Checkpoint four remains OPEN** until busy, unavailable/permission-denied, error, focus-loss and recovery states are accepted for *every advertised shared control*, including window/taskbar, desktop/file permissions, launcher empty/error, system controls and notifications.

## Reproduce and interpretation

```sh
cargo test --locked --manifest-path components/riceplate-wayland/Cargo.toml
cargo clippy --locked --manifest-path components/riceplate-wayland/Cargo.toml --all-targets -- -D clippy::correctness -D clippy::suspicious -D clippy::perf -D unused_must_use
sh -n scripts/smoke_riceplate_native.sh
# Once CI dependencies/builds are installed (see .github/workflows/riceplate-native.yml):
sh scripts/smoke_riceplate_native.sh
```

**Required before merging:** Python Tests, Rust/Clippy and the full Native RicePlate real-labwc run must pass on the **exact final PR head**, including the extended primary-click smoke; integration review is required. Verify the real input paths and external fuzzel fallback lifecycle complete, not only rendered screenshots. Confirm XFCE/X11 checks on that same head.

**SG1 decision:** still **OPEN (3/4 engineering checkpoints)**. Two-rice app/search/keyboard/SNI input acceptance has evidence; full shared loading/empty/busy/denied/focus/recovery-state acceptance remains missing. Do not check #417 or change the formal evidence index on the strength of this single hardening PR. Physical Mint/ThinkPad sign-off remains separate.
