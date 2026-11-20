# SG1–SG7 — transparent engineering evidence index

Last reviewed: 2026-11-20 (SG2/SG3 draft candidates; original checkpoint evidence unchanged). Authority for release acceptance: [issue #417](https://github.com/CopyPasteUser/Ricebowl/issues/417) and [RELEASE_1_0_GATES.md](../RELEASE_1_0_GATES.md).

## How to read these percentages

**Formal SG acceptance: 0 / 7 = 0%.** None of the seven blocking SG checkboxes in #417 has been closed with the required **full** software-only evidence.

**Engineering evidence coverage: 14 / 28 = 50%.** This is a deliberately separate, *author-defined and equally weighted* set of 28 inspectable checkpoints (four for each SG), not an official SG completion percentage or a timeline prediction. A checked checkpoint means some specific code **and test evidence** exist; it does not mean a gate is complete. The 28 checkpoint denominator is an engineering tracking convenience, not an authoritative weighting of remaining work. A checkbox must be reversed if its linked evidence regresses.

**Never interpret 50% as half the remaining effort.** The outstanding real compositor, accessibility, multi-output, provenance and performance acceptance may be harder than the items already checked. A future change may alter this index, and **0% formal** remains until a complete individual gate is closed.

## Evidence checkpoints

### SG1 — Native shared shell: 2 / 4
- [x] Native taskbar/window lifecycle and XWayland integration exercised by installed real-labwc smoke ([Native post-merge #43678051154](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43678051154)).
- [x] Desktop icon/multioutput positions and file actions exercised by native compositor smoke ([Native post-merge #43678051154](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43678051154)).
- [ ] Actual pointer **and** keyboard dispatch, app/search/SNI/DBusMenu on two structurally distinct rices accepted as a complete matrix.
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

### SG6 — Installer, packages and recovery: 3 / 4
- [x] Source-locked Core/Meta/native/session package install, upgrade, downgrade and purge tested in disposable Ubuntu ([release gates](../RELEASE_1_0_GATES.md)).
- [x] Corrupt Debian package rejection and simulated interrupted dpkg recovery tested ([roadmap](../RICEBOWL_DE_ROADMAP.md)).
- [x] XFCE and synthetic user state preserved across install/recovery/uninstall tests ([Native #43678051154](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43678051154)).
- [ ] Complete source provenance, stable reproducibility, Mint-compatible software install and final recovery matrix accepted.

### SG7 — Exact-main final software acceptance: 1 / 4
- [x] A prior exact-main native labwc test includes real task focus, two-rice switching and XWayland ([Native #43678051154](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43678051154)); **this is historical evidence, not final-source approval**.
- [ ] Exact **final** main Python/Rust/Clippy, native compositor and session workflows all green with no pending/failed checks.
- [ ] Strict software PipeWire frame/portal transport and recovery on same final SHA (dispatch explicitly when path filters skip it).
- [ ] Resource/leak benchmarks, unsupported/error states and complete release provenance documented and independently reviewed.

## Calculations and evidence hygiene

| SG | Checked | Checkpoints | Evidence coverage |
| --- | ---: | ---: | ---: |
| SG1 | 2 | 4 | 50% |
| SG2 | 2 | 4 | 50% |
| SG3 | 2 | 4 | 50% |
| SG4 | 2 | 4 | 50% |
| SG5 | 2 | 4 | 50% |
| SG6 | 3 | 4 | 75% |
| SG7 | 1 | 4 | 25% |
| **Total** | **14** | **28** | **50%** |

Do not check formal #417 SG items from this table alone. Physical Mint/ThinkPad GPU, login, Flatpak permissions, screen reader and mixed-DPI signoff is **later**; the stable 1.0 signoff JSON is untouched. Screenshots or command-line mocks alone do not satisfy any missing real-input criterion.

When updating, preserve the explicit evidence links, review current `main` and check run conclusions, update the table arithmetic, and keep formal SG acceptance distinct from this review index.
