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
  The package now stamps the staged native ELF SHA-256 and the read-only
  four-package verifier rejects missing/invalid digests and modified native
  payloads. Native CI additionally rebuilds the locked Rust executable in an
  independent clean target and compares its bytes before packaging.
  This establishes same-run binary consistency, **not** cryptographic
  provenance, cross-host bit-reproducibility, or that an externally supplied
  ELF came from the stamped commit. The artifact is opt-in and does not
  replace the XFCE login or full installer.
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
- [x] Isolated headless labwc portal baseline verifies a real Screenshot PNG
  and ScreenCast request behavior. A rejected pixman/wlr Start (response 2)
  remains a failed capture path, **not** proof of usable ScreenCast.
- [x] Separate disposable, CI-only **generic/pixman** software frame acceptance
  (#382) now verifies CreateSession, SelectSources, Start, stream node, real
  OpenPipeWireRemote FD and a nonempty GStreamer video/x-raw buffer with a
  genuine animated GTK Wayland witness and private PipeWire/WirePlumber.
  The CI-patched generic backend is **not** installed as the production portal.
  The optional production wlr/GLES2 hardware lane was prepared in #384, but
  has **not** been accepted on a DRM-capable runner.
- [ ] Verify successful ScreenCast Start, PipeWire node/FD, consent UX and
  actual frame delivery on a GPU-backed Wayland session; also Flatpak sandbox,
  permissions, denial and multi-monitor behavior on real hardware.
- [ ] Installation, upgrade, uninstall and rollback pass from clean systems.
- [ ] Native RicePlate/RiceSpice/RicePop feature parity and mockup-to-rice
  authoring gates from `RICEBOWL_DE_ROADMAP.md` are satisfied.
- [x] Panel-only v1 recipes can be validated, imported and exported offline
  with bounded files and no desktop mutation; full RicePack compatibility
  remains an independent 1.0 gate.
- [x] A selected Wayland recipe persists across sessions and can be restored
  one step, with safe classic fallback after missing/corrupt state.
  The owner-private shared live-switch transaction now waits for an actual
  native RicePlate compositor-frame acknowledgement, supports guarded
  apply/restore across its managed components, and tests composited
  Classic -> Chrome -> XP Luna -> Chrome (#381; post-merge Native run
  #43678051154). This is **not** an atomic frame boundary across third-party
  clients or a physical device acceptance.

## Software-only post-merge checkpoint (15 November 2026)

- Base under test: `main@fca6910d5a885d0bfd0f37d757f199775f821983`
  (guarded merge of #383). The **push-triggered** [Tests run #43678051131](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43678051131)
  and [Native RicePlate run #43678051154](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43678051154)
  both completed successfully on this exact SHA; this is post-merge evidence,
  not just a green PR head. No blanket 1.0 release-signoff is implied.
- That Native run covers real same-seat desktop keyboard Enter and return to
  an external GTK Wayland text-entry client; file context actions, Trash,
  new folder, dragging and two-output position persistence; composited
  multi-rice apply/restore; upgrade/downgrade and user/XFCE preservation;
  native installed-session failure guards, XWayland and compositor cleanup.
- Remaining separate gates: exact final-release SHA/complete workflow set,
  real Mint/ThinkPad input, IME, Orca, power and display acceptance,
  GPU-backed production wlr/GLES2 capture, Flatpak consent/denial/permissions,
  and physical multi-monitor testing. The absence of a DRM node in the
  software acceptance environment is not proof of hardware readiness.

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

After those tests, add the **real device, date, traceable evidence and
`tested_source_commit`** (the 40-character Git SHA of the *hardware-tested*
code) to `.github/release-signoff-1.0.json`; then set `status` to
`approved` in a reviewed, sign-off-only commit. The stable-release gate
requires that tested commit be an ancestor of the release tag and rejects
all intervening file changes **except the sign-off JSON itself**. This avoids
the impossible requirement for a commit to contain its own SHA and blocks
reusing device approval after subsequent code changes. The tag workflow
fetches the necessary Git history. Shallow source snapshots cannot certify
stable 1.0. The gate verifies provenance and completeness, **not the truth of
human measurements**. Do not edit evidence merely to make CI green.

## Sprint 9 — signed native preview provenance (CI-gated)

After the native suite passes on a **trusted `main` push**, a separate job
downloads the exact smoke-tested preview bundle and verifies its `SHA256SUMS`,
Git source commit, staged ELF digest and extracted Debian binary before
creating a GitHub/Sigstore build provenance attestation using
`actions/attest@v4`. Only that post-test job requests OIDC,
`attestations: write` and artifact metadata permissions; pull requests and
forks cannot run the signing job. The native preview package and source commit
can then be independently checked with:

```sh
gh attestation verify ricebowl-riceplate-native_0.1.0~preview2_amd64.deb \
  --repo CopyPasteUser/Ricebowl
```

This produces *signed CI identity/subject evidence* after the first successful
post-merge run. It does **not** certify third-party uploaded binaries, a
reproducible byte-for-byte cross-machine toolchain, an installer, stable
version 1.0, a device test or reviewed human sign-off. The public release
and hardware checklist remains fully enforced.

## Exact-source GitHub CI gate for release artifacts

The `v1.0.0-rc.N` / `v1.0.0` source-artifact workflow now requires
successful, completed exact-SHA **main-branch** runs for all three canonical
workflows: Tests (`ci.yml`, requires a main `push`), Native RicePlate
(`riceplate-native.yml`), and Wayland session preview (`wayland-session.yml`).
The last two expensive, path-filtered workflows additionally support a
**manual GitHub Actions workflow dispatch** at the exact main revision.
A release engineer must deliberately run them before tagging when automatic
path filters did not include that SHA; this avoids widening normal CI on every
push. Only `push` or `workflow_dispatch` on `main` is trusted for those
two workflows. The latest matching run for each workflow is checked by ID,
so an older success cannot hide a later failure. Missing, pending, cancelled,
untrusted-branch or unreachable evidence blocks artifact assembly. Workflow
identity is pinned by both name and file path.

A stable 1.0 tag checks the `tested_source_commit`, after the separate
Git ancestry/sign-off gate has verified that only the sign-off JSON changed
since the physical test. RC tags check the tagged SHA directly. This is a
**CI evidence gate**, not a physical hardware test, reproducible binary
certificate or automatic public-release publisher.

## Candidate preparation

```bash
/usr/bin/python3 scripts/check_release_contract.py
/usr/bin/python3 -m unittest discover -s tests -q
```

The GitHub source-artifact job runs on `v1.0.0-rc.N` and `v1.0.0` tags once
the package/CLI source version is 1.0.0. It **does not automatically publish
a release**: full CI, hardware sign-off and real installer/binary artifacts
are mandatory before publication. Tagging 1.0 prematurely is prohibited.
