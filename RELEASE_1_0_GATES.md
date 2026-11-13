# RiceBowl 1.0 — honest release gates

RiceBowl currently ships a working XFCE/X11 rice preview and an **opt-in,
unfinished** labwc/Wayland desktop preview. The two must not be presented
as the same release state. This file is a release checklist, not proof of
physical-device compatibility.

## Automated checks

**Active development priority:** close the software-only checklist first.
Physical Mint/ThinkPad sign-off is temporarily excluded from development
progress percentages, but it remains mandatory for an actual public 1.0 tag;
the sign-off guard and its tests are deliberately unchanged.

- [x] The read-only Wayland `de check` verifies the mandatory launcher
  executables, separates nested, full and native-login prerequisites and
  fails when a required program is missing. Availability is not proof of
  successful login or working hardware.
- [x] Python package and CLI version agree at the current 0.9.1 baseline.
- [x] A source archive job is defined for `v1.0.0-rc.N` / `v1.0.0` tags.
- [x] A stable 1.0 tag is blocked by default until real-device acceptance is
  explicitly documented in `.github/release-signoff-1.0.json`.
- [x] The separate **preview session-entry** Debian package builds
  reproducibly with normalized timestamps and `SOURCE_DATE_EPOCH` support.
- [ ] All project CI, including real X11 screenshots, Wayland session smoke
  and native RicePlate Rust/headless labwc tests, is green for the release SHA.
- [ ] Rust application builds and the complete Wayland desktop package use
  tracked lock/version metadata; final binary/install artifacts reproduce.
- [x] Native RicePlate CI emits an explicitly experimental, checksummed
  Ubuntu 24.04 preview binary plus its resolved Cargo.lock for QA download;
  this is **not** a reproducible or signed 1.0 distribution.
- [x] Headless native CI has a separate real Wayland terminal integration
  check for task appearance, panel painting and task removal on close;
  this is **not** proof of physical click/focus or XWayland compatibility.
- [x] A separate amd64 native RicePlate preview `.deb` is assembled from that
  tested executable with dynamically derived shared-library dependencies; CI
  checks repeat-build identity and verifies the extracted binary matches.
  The artifact is opt-in and does not replace the XFCE login or full installer.
- [x] The optional standalone Wayland core and dependency-only desktop
  metapackage have reproducible Debian builds. CI checks a disposable
  Ubuntu 24.04 install/reinstall/purge and that package removal leaves
  synthetic user configuration untouched. Does not certify live DM login.
- [x] An isolated Ubuntu 24.04 job installs Core/Meta from the immutable
  previous preview1 release, upgrades to preview2, rejects corrupted
  packages without losing the old installation, downgrades back to preview1,
  re-upgrades and purges. Pinned old source tree, version provenance and
  test-user recipe/XFCE state checks prevent an in-name-only upgrade test.
  Only Core and Meta change versions; native/session stay on their existing
  preview revisions.
- [x] CI starts the **installed native login wrapper** from the complete
  `.deb` bundle in a disposable Ubuntu container with an unprivileged user,
  private Wayland runtime and D-Bus. It checks the live compositor socket,
  native RicePlate, `swayidle` and a screenshot. This is not a physical display
  manager or GPU login acceptance test.
- [x] The same disposable installed-login test kills the native panel and
  requires a live Waybar recovery, then kills `swayidle` and requires the
  unprotected compositor to exit. A fresh native login must work afterward.
  This proves packaged software failure paths in CI, not real suspend,
  crash recovery or display-manager behavior on physical hardware. Validated
  by the complete native package CI in PR #219.
- [x] Isolated headless labwc portal CI goes beyond D-Bus introspection:
  verify a real PNG Screenshot, create a ScreenCast session, select a monitor
  and attempt Start. The CI pixman renderer rejects Start with response 2;
  this is explicitly reported as an **untested ScreenCast backend**, never as
  PipeWire-stream success. The unattended chooser override is CI-private.
- [ ] Verify successful ScreenCast Start, PipeWire node/FD, consent UX and
  actual frame delivery on a GPU-backed Wayland session; also Flatpak sandbox,
  permissions, denial and multi-monitor behavior on real hardware.
- [ ] Installation, upgrade, uninstall and rollback pass from clean systems.
- [ ] Native RicePlate/RiceSpice/RicePop feature parity and mockup-to-rice
  authoring gates from `RICEBOWL_DE_ROADMAP.md` are satisfied.
- [x] Panel-only v1 recipes can be validated, imported and exported offline
  with bounded files and no desktop mutation; full RicePack compatibility
  remains an independent 1.0 gate.
- [x] A selected Wayland panel recipe persists across sessions and can be
  restored one step, with safe classic fallback after missing/corrupt state;
  no claim of live multi-component rice switching.

## Multi-lane integration gate

For Wayland DE changes, apply the [parallel integration contract](docs/de-integration-governance.md). Each parent and stacked PR must be reviewed and tested at its exact final head, and the relevant full workflows must be rerun on the resulting `main` merge commit. Green checks on an earlier head or unrelated branch are insufficient; CI-only success never substitutes for the physical-device gates below. The contract does not relax the existing 1.0 sign-off requirements.

## Deferred: real-hardware acceptance (not done; not in software progress %)

- [ ] Login and logout on physical Mint 22 hardware, including crash recovery.
- [ ] XFCE remains independently selectable and untouched after rollback.
- [ ] XWayland, Flatpak portals, clipboard, polkit, screen capture and input.
- [ ] Taskbar, tray, network, audio, Bluetooth, power, lock, suspend and
  multi-monitor/hotplug behavior with honest unavailable/error states.
- [ ] Two compositionally distinct rice authoring demonstrations, including
  offline import, preview, apply and restore.
- [ ] Measured cold start, settled PSS/RSS, idle CPU/wakeups, mixed-DPI and
  long-running memory behavior on actual devices.

After those tests, add the **real device, date and traceable evidence** for
every area to `.github/release-signoff-1.0.json`; then set `status` to
`approved` in a reviewed commit. The check script verifies completeness, but
cannot establish the truth of a human sign-off. Do not edit it merely to
make CI green.

## Candidate preparation

```bash
/usr/bin/python3 scripts/check_release_contract.py
/usr/bin/python3 -m unittest discover -s tests -q
```

The GitHub source-artifact job runs on `v1.0.0-rc.N` and `v1.0.0` tags once
the package/CLI source version is 1.0.0. It **does not automatically publish
a release**: full CI, hardware sign-off and real installer/binary artifacts
are mandatory before publication. Tagging 1.0 prematurely is prohibited.
