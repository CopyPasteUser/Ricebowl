# SG1–SG7 — transparent engineering evidence index

Last reviewed: 2026-11-22 (SG6 preserved; SG1 third checkpoint reconciled against exact-main two-rice compositor and app-launch evidence). Authority for release acceptance: [issue #417](https://github.com/CopyPasteUser/Ricebowl/issues/417) and [RELEASE_1_0_GATES.md](../RELEASE_1_0_GATES.md).

## How to read these percentages

**Formal SG acceptance: 1 / 7 ≈ 14.3%.** [Issue #417](https://github.com/CopyPasteUser/Ricebowl/issues/417) formally closes SG6 on pinned exact-main software-only evidence. SG1–SG5 and SG7 remain open; hardware sign-off remains separate.

**Engineering evidence coverage: 16 / 28 ≈ 57.1%.** This is a deliberately separate, *author-defined and equally weighted* set of 28 inspectable checkpoints (four for each SG), not an official SG completion percentage or a timeline prediction. A checked checkpoint means some specific code **and test evidence** exist; it does not mean a gate is complete. The 28 checkpoint denominator is an engineering tracking convenience, not an authoritative weighting of remaining work. A checkbox must be reversed if its linked evidence regresses.

**Never interpret 57.1% as the fraction of engineering effort completed.** Outstanding real compositor, accessibility, multi-output and performance acceptance may be harder than checked items. A future change may alter this index; **only SG6 (1/7 gates) has formal software-only acceptance**.

## Evidence checkpoints

### Offline integration checkpoint — 25 November 2026

The native menu IME landed in [#600](https://github.com/CopyPasteUser/Ricebowl/pull/600) at [`main@4bfd479b`](https://github.com/CopyPasteUser/Ricebowl/commit/4bfd479b00ac62376e3d0f0d207043444432c1d3). Real IME-v2 through private labwc verified Japanese preedit, commit, UTF-8 deletion and public AT-SPI teardown for both menu fields. The candidate and merged tree passed 503 Rust tests and the Python suite (1,929 discovered, 33 skipped). The full SG5 font, RTL and editor matrix remains open. [Integration evidence and resume checkpoint](https://github.com/CopyPasteUser/Ricebowl/issues/360#issuecomment-7161355589)

### SG1 — Native shared shell: 3 / 4
- [x] Native taskbar/window lifecycle and XWayland integration exercised by installed real-labwc smoke ([Native post-merge #43678051154](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43678051154)).
- [x] Desktop icon/multioutput positions and file actions exercised by native compositor smoke ([Native post-merge #43678051154](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43678051154)).
- [x] Actual pointer **and** keyboard dispatch, app/search/SNI/DBusMenu on two structurally distinct rices accepted as a complete matrix. Chrome real Fuzzel search/keyboard→private Exec is exercised by [#573](https://github.com/CopyPasteUser/Ricebowl/pull/573); XP Luna native Start→app search→keyboard Return→Gio process receipt and both-rice primary/secondary SNI DBusMenu + owner turnover are exercised by [#583](https://github.com/CopyPasteUser/Ricebowl/pull/583) building on [#581](https://github.com/CopyPasteUser/Ricebowl/pull/581). [Exact PR-head Tests #44994830678](https://github.com/CopyPasteUser/Ricebowl/actions/runs/44994830678) and [Native/Mint #44994830698](https://github.com/CopyPasteUser/Ricebowl/actions/runs/44994830698), followed by [exact merged-main Tests #44995952470](https://github.com/CopyPasteUser/Ricebowl/actions/runs/44995952470) and [Native #44995952471](https://github.com/CopyPasteUser/Ricebowl/actions/runs/44995952471) at `main@48d7ba73144c515cf76d225f86ec81a4aeefe6f5`. Each witness uses real labwc input and external provider/process receipts, not screenshot-only evidence.
- [ ] Loading, empty, busy, error, focus and recovery states for every advertised shared control accepted in compositor tests.

### SG2 — RiceSpice Linux integrations: 2 / 4
- [x] Both X11/Wayland display changes have independent rollback and fail-closed monitor confirmation coverage ([#522](https://github.com/CopyPasteUser/Ricebowl/pull/522)).
- [x] NetworkManager connection identity, VPN import state and Enterprise trust verification covered by negative tests ([#517](https://github.com/CopyPasteUser/Ricebowl/pull/517), [#519](https://github.com/CopyPasteUser/Ricebowl/pull/519)).
- [ ] All display/input/audio/Bluetooth/accessibility/power/time GUI adapters accepted with complete denial, readback and disconnected-provider coverage.
- [ ] Full disposable D-Bus, real headless compositor and rollback/recovery acceptance matrix complete at one final `main` SHA.

### SG3 — RicePop notifications: 2 / 4
- [x] A single owned Mako notification host, real daemon delivery and owner restart paths exercised ([roadmap](../RICEBOWL_DE_ROADMAP.md)).
- [x] Native stale notification ID/action and owner-bound guarded mutation path has regression tests ([roadmap](../RICEBOWL_DE_ROADMAP.md)).
- [ ] Inbox/OSD, live updates, keyboard and AT-SPI action semantics accepted across structurally distinct rices.
- [ ] Privacy, restart, persistence, localization and rendered text accepted as a complete real-Mako/labwc matrix.

**SG3 local progress (27 Nov 2026; checkboxes unchanged, formal acceptance open):** `scripts/smoke_sg3_ricepop_native_labwc.sh [luna|luna-de|luna-nofonts|chrome]` adds local real-Mako-1.11/labwc/AT-SPI receipts for the volume OSD, the Luna native inbox, the Chrome RiceSpice GTK inbox, privacy/restart and a Hindi/CJK/Arabic/Hangul rendered-text matrix. Open: GTK keyboard traversal, brightness OSD, hosted-CI/exact-head runs. See `docs/sg-remaining-work-packages.md` rows 3.1/3.2.

### SG2/SG3 focused candidates (20 November 2026; **not yet accepted**)

- **SG2 candidate [#552](https://github.com/CopyPasteUser/Ricebowl/pull/552):** NetworkManager saved-profile operations classify post-write inventory loss as an indeterminate outcome and reject type-changed UUID reuse. Unit tests use fake providers; they **do not** establish complete network/display/audio/BlueZ/power/time GUI parity, authorization or real D-Bus/compositor acceptance.
- **SG3 candidate [#553](https://github.com/CopyPasteUser/Ricebowl/pull/553):** Mako freedesktop `ActionInvoked` is added to the view-scoped live watcher with malformed-signal tests; the existing private Mako 1.11/labwc smoke now requires one **real** `ActionInvoked` bus emission. No second notification owner or durable inbox is introduced.
- **Evidence policy:** these are review candidates, not checked acceptance items. Require green exact-head jobs, independent real-Mako/labwc/AT-SPI verification and post-integration exact-main provenance before changing any SG2/SG3 checkbox or coverage count. The full #417 gate requirements remain outstanding.

### SG4 — Creator/RicePack: 2 / 4
- [x] Versioned v1 panel recipe validation and offline import/export supported ([release gates](../RELEASE_1_0_GATES.md)).
- [x] Compositor-confirmed distinct rice apply/restore transaction with native frame acknowledgment ([#381](https://github.com/CopyPasteUser/Ricebowl/pull/381), [Native #43678051154](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43678051154)).
- [ ] Two complete rices authored/exported/imported with full schema, layout/scale/interaction evidence and Creator exit/restore tests.
- [ ] Entire referenced asset licensing/provenance and visual geometry tolerance review approved.

### SG5 — Unicode, text, IME, accessibility: 2 / 4
- [x] UAX #29 grapheme-bounded text editing, clipping and caret preservation are covered in Rust text/editor tests ([native source](../components/riceplate-wayland/src/text_render.rs)).
- [x] Unicode BiDi caret mapping and native OpenType shaping are implemented and regression-tested ([#524](https://github.com/CopyPasteUser/Ricebowl/pull/524), [native source](../components/riceplate-wayland/src/style_art.rs)).
- [ ] Real Wayland IME composition, deletion and keyboard focus handoff fully accepted across all dialog surfaces and CJK/RTL flows.
- [ ] Full fallback script/font/render/AT-SPI metadata matrix verified with accessible clients and missing-font conditions.

### SG6 — Installer, packages and recovery: 4 / 4 (software gate closed)
- [x] Source-locked Core/Meta/native/session package install, upgrade, downgrade and purge tested in disposable Ubuntu ([release gates](../RELEASE_1_0_GATES.md)).
- [x] Corrupt Debian package rejection and simulated interrupted dpkg recovery tested ([roadmap](../RICEBOWL_DE_ROADMAP.md)).
- [x] XFCE and synthetic user state preserved across install/recovery/uninstall tests ([Native #43678051154](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43678051154)).
- [x] Exact-main source provenance and reproducible four-package archives from separate hosted build jobs, signed comparison report and four package subjects, and successful installed Ubuntu/Mint recovery at [main@344d5557](https://github.com/CopyPasteUser/Ricebowl/commit/344d5557a749213dfdd83be2db4a5ba21e8b2624) ([Tests #44881618535](https://github.com/CopyPasteUser/Ricebowl/actions/runs/44881618535), [Native/Mint #44881618473](https://github.com/CopyPasteUser/Ricebowl/actions/runs/44881618473), [SG6 cross-runner #44881618480](https://github.com/CopyPasteUser/Ricebowl/actions/runs/44881618480), [report attestation #70471969](https://github.com/CopyPasteUser/Ricebowl/attestations/70471969), [four-deb attestation #70471973](https://github.com/CopyPasteUser/Ricebowl/attestations/70471973), [#417](https://github.com/CopyPasteUser/Ricebowl/issues/417)). Hosted-runner repeatability is **not** third-party machine/toolchain or physical Mint/ThinkPad certification.

### SG7 — Exact-main final software acceptance: 1 / 4
- [x] A prior exact-main native labwc test includes real task focus, two-rice switching and XWayland ([Native #43678051154](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43678051154)); **this is historical evidence, not final-source approval**.
- [ ] Exact **final** main Python/Rust/Clippy, native compositor and session workflows all green with no pending/failed checks.
- [ ] Strict software PipeWire frame/portal transport and recovery on same final SHA (dispatch explicitly when path filters skip it).
- [ ] Resource/leak benchmarks, unsupported/error states and complete release provenance documented and independently reviewed.

## Calculations and evidence hygiene

| SG | Checked | Checkpoints | Evidence coverage |
| --- | ---: | ---: | ---: |
| SG1 | 3 | 4 | 75% |
| SG2 | 2 | 4 | 50% |
| SG3 | 2 | 4 | 50% |
| SG4 | 2 | 4 | 50% |
| SG5 | 2 | 4 | 50% |
| SG6 | 4 | 4 | 100% |
| SG7 | 1 | 4 | 25% |
| **Total** | **16** | **28** | **57.1%** |

Only SG6 is formally closed in #417 on separately inspected exact-main evidence; do not infer other SG acceptance from this table. Physical Mint/ThinkPad GPU, login, Flatpak permissions, screen reader and mixed-DPI signoff is **later**; the stable 1.0 signoff JSON is untouched. Screenshots or command-line mocks alone do not satisfy any missing real-input criterion.

When updating, preserve the explicit evidence links, review current `main` and check run conclusions, update the table arithmetic, and keep formal SG acceptance distinct from this review index.
