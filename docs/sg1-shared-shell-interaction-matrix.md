# SG1 — shared native shell interaction matrix (XP Luna / Chrome)

**Scope:** software-only, headless labwc. **Integration baseline:** `main@3d4d716b7a9ad45beab2e65d34447648ba26b18d` (2026-11-22). The canonical acceptance criteria remain [#417](https://github.com/CopyPasteUser/Ricebowl/issues/417) and [SG1–SG7 evidence](sg1-sg7-evidence-progress.md). This is a **test coverage ledger**, not a sign-off or a hardware claim.

**Rices:** XP Luna uses schema-v12 columns, desktop, native local tray menus and a wide bottom taskbar. Chrome uses a schema-v1 single launcher shelf with a centered task region and status indicators. Both are rendered by the same Rust RicePlate engine; neither is a duplicate backend.

Legend: **existing** = currently exercised in repo smoke/tests; **PR test** = implemented in this draft, must pass exact-head CI before credit; **gap** = not accepted by this matrix. State verification means action receipt, file/DBus state, process/argv, or explicit native transition log rather than screenshot only.

| Control / scenario | XP Luna | Chrome | What is actually asserted | Remaining acceptance gap |
| --- | --- | --- | --- | --- |
| Panel / launcher pointer | existing | **PR test** | Real labwc pointer; native Luna menu state or external Chrome fuzzel process lifecycle | Cross-scale, all controls |
| Launcher keyboard | existing focus/shortcuts | **PR test** Escape | Compositor `wtype`, Chrome fuzzel exit; Luna native menu and Run editor verified in native smoke | Search results and action activation via keyboard across both |
| App search / paging | existing pointer transitions | Rust-only for search semantics | Native menu hit/paging tests, Luna pointer state frames | Verify actual Chrome search/app launch and empty/busy/error states under compositor |
| Taskbar, window actions | existing | existing | Native XWayland/Wayland task focus smoke, shared window lifecycle | Full two-rice minimize/maximize/close, transient loss/restart matrix |
| Desktop icons / file operations | existing | shared desktop engine | labwc pointer + keyboard, file inventory, rename/Trash/RiceField and multi-output/hotplug smoke | Complete two-rice multi-select/drag/deny/permission and focus-lost matrix |
| SNI / DBusMenu remote menus | real two-rice smoke #581 | real two-rice smoke #581 | #581 proved actual secondary-pointer, nested keyboard `clicked/21`, provider owner death/new generation with stale click revoked in real labwc. This sprint additionally requires primary `ItemIsMenu=true` to dispatch a distinct new receipt on each rice, with no fallback to SNI item method | Primary path awaiting exact-head green CI; empty/disabled/denied/busy and concurrent ownership/input matrix remains open |
| Luna local clock tray action | **PR test** | n/a (Chrome uses common status/tray) | Real labwc right-click + keyboard Return; exact `ricebowl de settings --luna --page timezone` argv in private shim, no host mutation | Denied/unavailable provider and focus-loss handling end-to-end |
| Tray invalid secondary click | existing | shared handler | Real Luna pointer secondary no-activation, primary close; Rust validates button IDs | Remote SNI on Chrome end-to-end |
| Notifications / system controls | existing partial | shared engine partial | Native OSD/RicePop preview and system-status tests | Real provider unavailable/denied/restart, locale/AT-SPI and both-rice focus |
| Empty / disabled / stale actions | new and existing Rust menu tests | shared menu state | `MenuChoice::None`, stale-selection sentinel, disabled rows, bounded menu snapshot | Every visible control under real labwc, including concurrent events |
| Focus / hotplug / parallel input | existing selective | existing selective | Native focus handoff to GTK, multi-output, resize, real virtual pointer/keyboard | Explicit mixed DPI and hotplug *during* open menus; simultaneous provider update and input |

## Accepted baseline and focused test candidate (22 November 2026)

- [#573](https://github.com/CopyPasteUser/Ricebowl/pull/573) added a real Chrome Fuzzel keyboard search, Return and private process-execution receipt under labwc.
- [#581](https://github.com/CopyPasteUser/Ricebowl/pull/581) added real XP Luna/Chrome SNI owner-restart and menu action receipts, closed old owner IDs and restored keyboard focus in an explicitly opened remote popup.
- This focused follow-up tests the **separate primary SNI `ItemIsMenu=true` path** on both rices, using a second genuine compositor pointer/keyboard action and an incremental `Event(clicked, 21)` receipt. It rejects false positives from earlier secondary-click receipts and disallows `Activate/ContextMenu` fallback when a valid native menu was available. It does not alter production bindings, provider privileges or XFCE.
- **Not accepted until exact-head Native CI** proves the new actual primary-click scenario. The remaining control/error/focus/hotplug acceptance gaps keep SG1 formally open.

## Reproduce and interpretation

```sh
cargo test --locked --manifest-path components/riceplate-wayland/Cargo.toml
cargo clippy --locked --manifest-path components/riceplate-wayland/Cargo.toml --all-targets -- -D clippy::correctness -D clippy::suspicious -D clippy::perf -D unused_must_use
sh -n scripts/smoke_riceplate_native.sh
# Once CI dependencies/builds are installed (see .github/workflows/riceplate-native.yml):
sh scripts/smoke_riceplate_native.sh
```

**Required before merging:** Python Tests, Rust/Clippy and the full Native RicePlate real-labwc run must pass on the **exact final PR head**, including the extended primary-click smoke; integration review is required. Verify the real input paths and external fuzzel fallback lifecycle complete, not only rendered screenshots. Confirm XFCE/X11 checks on that same head.

**SG1 decision:** still **OPEN (2/4 engineering checkpoints)** until #417's full two-rice interaction, provider recovery, keyboard/pointer/error and empty/busy-state matrix is accepted. Do not check #417 or change the formal evidence index on the strength of this single hardening PR. Physical Mint/ThinkPad sign-off remains separate.
