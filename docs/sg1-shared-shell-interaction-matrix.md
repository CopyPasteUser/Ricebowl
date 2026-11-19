# SG1 — shared native shell interaction matrix (XP Luna / Chrome)

**Scope:** software-only, headless labwc. **Integration baseline:** `main@019f255fbc3fc07fddb68283f632e628f5226649` (2026-11-19). The canonical acceptance criteria remain [#417](https://github.com/CopyPasteUser/Ricebowl/issues/417) and [SG1–SG7 evidence](sg1-sg7-evidence-progress.md). This is a **test coverage ledger**, not a sign-off or a hardware claim.

**Rices:** XP Luna uses schema-v12 columns, desktop, native local tray menus and a wide bottom taskbar. Chrome uses a schema-v1 single launcher shelf with a centered task region and status indicators. Both are rendered by the same Rust RicePlate engine; neither is a duplicate backend.

Legend: **existing** = currently exercised in repo smoke/tests; **PR test** = implemented in this draft, must pass exact-head CI before credit; **gap** = not accepted by this matrix. State verification means action receipt, file/DBus state, process/argv, or explicit native transition log rather than screenshot only.

| Control / scenario | XP Luna | Chrome | What is actually asserted | Remaining acceptance gap |
| --- | --- | --- | --- | --- |
| Panel / launcher pointer | existing | **PR test** | Real labwc virtual-pointer click; menu presentation or menu-state trace | Cross-scale, all controls |
| Launcher keyboard | existing focus/shortcuts | **PR test** Escape | Compositor `wtype`, menu hide trace; Luna Run editor and desktop shortcuts verified in native smoke | Search results and action activation via keyboard across both |
| App search / paging | existing pointer transitions | Rust-only for search semantics | Native menu hit/paging tests, Luna pointer state frames | Verify actual Chrome search/app launch and empty/busy/error states under compositor |
| Taskbar, window actions | existing | existing | Native XWayland/Wayland task focus smoke, shared window lifecycle | Full two-rice minimize/maximize/close, transient loss/restart matrix |
| Desktop icons / file operations | existing | shared desktop engine | labwc pointer + keyboard, file inventory, rename/Trash/RiceField and multi-output/hotplug smoke | Complete two-rice multi-select/drag/deny/permission and focus-lost matrix |
| SNI / DBusMenu remote menus | Rust tests; prior Luna native pointer menu | shared SNI host when enabled | Live ID reorder, disabled/removed/duplicate IDs, local-vs-remote ownership; **PR tests** revoke relabelled/reparented submenu paths | Real disposable SNI provider restart, owner change and remote keyboard action receipts **for both** |
| Luna local clock tray action | **PR test** | n/a (Chrome uses common status/tray) | Real labwc right-click + keyboard Return; exact `ricebowl de settings --luna --page timezone` argv in private shim, no host mutation | Denied/unavailable provider and focus-loss handling end-to-end |
| Tray invalid secondary click | existing | shared handler | Real Luna pointer secondary no-activation, primary close; Rust validates button IDs | Remote SNI on Chrome end-to-end |
| Notifications / system controls | existing partial | shared engine partial | Native OSD/RicePop preview and system-status tests | Real provider unavailable/denied/restart, locale/AT-SPI and both-rice focus |
| Empty / disabled / stale actions | new and existing Rust menu tests | shared menu state | `MenuChoice::None`, stale-selection sentinel, disabled rows, bounded menu snapshot | Every visible control under real labwc, including concurrent events |
| Focus / hotplug / parallel input | existing selective | existing selective | Native focus handoff to GTK, multi-output, resize, real virtual pointer/keyboard | Explicit mixed DPI and hotplug *during* open menus; simultaneous provider update and input |

## Focused draft change

- `tray.rs::MenuPopup::sync` now preserves a remote submenu path only when each parent retains its **ID, label, enabled state and submenu type**. A renamed parent or revoked subtree closes that path; even a promoted child with the same ID and label cannot inherit its earlier keyboard selection. This is an identity/safety hardening of **live in-process menu snapshots**, not a claim of D-Bus owner generation isolation.
- New Rust negative tests cover parent relabel + reused child, nested relabel while retaining the outer parent, and a promoted child that must require a new keypress.
- The existing **disposable** `scripts/smoke_riceplate_native.sh` adds Chrome pointer-open + keyboard-Escape state assertions and Luna clock tray compositor keyboard Enter -> captured exact settings argv. The settings shim is only active inside the test runtime and does not alter the user's timezone or run a real system settings GUI.

## Reproduce and interpretation

```sh
cargo test --locked --manifest-path components/riceplate-wayland/Cargo.toml
cargo clippy --locked --manifest-path components/riceplate-wayland/Cargo.toml --all-targets -- -D clippy::correctness -D clippy::suspicious -D clippy::perf -D unused_must_use
sh -n scripts/smoke_riceplate_native.sh
# Once CI dependencies/builds are installed (see .github/workflows/riceplate-native.yml):
sh scripts/smoke_riceplate_native.sh
```

**Required before merging:** Rust tests + Clippy + Python Tests + Native RicePlate labwc on **exact final PR head**, including the extended smoke, and core/desktop/integration lane approval for the shared smoke-script diff. Verify that the smoke's real input paths complete, not only the rendered screenshots. Confirm XFCE/X11 checks on that same head.

**SG1 decision:** still **OPEN (2/4 engineering checkpoints)** until #417's full two-rice interaction, provider recovery, keyboard/pointer/error and empty/busy-state matrix is accepted. Do not check #417 or change the formal evidence index on the strength of this single hardening PR. Physical Mint/ThinkPad sign-off remains separate.
