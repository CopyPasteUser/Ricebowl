# Local CI receipt for `10aa421946b2`

**COMPLETE** - every catalog step PASS on a clean exact checkout: `true`

- Commit: `10aa421946b22d4661e42344645ecf7648aa2899` (2026-11-27T13:30:24+00:00)
- Checkout clean at start: `True`; tracked files modified by the run: 0
- Result: 79 PASS, 0 FAIL, 1 BLOCKED, 0 SKIPPED
- Host: Ubuntu 24.04.5 LTS / kernel 6.18.44-fc-v880 #1 SMP PREEMPT_DYNAMIC @0 (ran as `rbdev`, worker `host-a`)
- Started 2026-11-27T13:41:45+00:00, finished 2026-11-27T14:26:52+00:00
- Tools: cargo=cargo 1.88.0 (873a06493 2025-05-10); clippy=clippy 0.1.88 (6b00bc3880 2025-06-23); docker=Docker version 29.9.3, build 5457199; dpkg_deb=Debian 'dpkg-deb' package archive backend version 1.22.6 (amd64).; gtk=GTK 3.24.41; labwc=labwc 0.7.1; labwc_sg5=labwc 0.7.2; mako=mako-notifier 1.8.0-2build2; mako_1_11=mako 1.11.0 source-locked 91c6b7998557; meson=1.3.2; python=Python 3.12.3; rustc=rustc 1.88.0 (6b00bc388 2025-06-23); rustfmt=rustfmt 1.8.0-stable (6b00bc3880 2025-06-23)

| Step | Status | Seconds | Mirrors (workflow / job / step) |
| --- | --- | ---: | --- |
| `py-compile` | PASS | 1.8 | ci.yml / test / Validate and test the suite [compileall] |
| `py-tests` | PASS | 94.8 | ci.yml / test / Validate and test the suite [unittest discover] |
| `native-syntax` | PASS | 1.1 | riceplate-native.yml / native-layer-shell / Fail fast on SG5 external harness syntax |
| `shell-syntax` | PASS | 1.2 | riceplate-native.yml / native-layer-shell / Build and test native RicePlate [harness syntax checks] |
| `py-native-unit` | PASS | 1.8 | riceplate-native.yml / native-layer-shell / Build and test native RicePlate [Python unit tests] |
| `sg7-matrix-unit` | PASS | 1.4 | sg7-exact-main.yml / dossier / Verify SG7 exact-main collector unit tests |
| `release-contract` | PASS | 1.2 | release-candidate.yml / source-gate / Require matching version and documented hardware approval for stable 1.0 |
| `release-workflows-unit` | PASS | 1.2 | release-candidate.yml / source-gate / Require exact-source main CI for candidate and stable artifacts |
| `release-source-verify` | PASS | 1.6 | ci.yml / publish-ricebowl / Verify release source and package |
| `release-source-archive` | PASS | 1.6 | release-candidate.yml / source-gate / Produce source archive and checksum |
| `portal-unit` | PASS | 1.3 | wayland-portal-strict.yml / portal-unit / Test negative paths and validate shell / Python syntax |
| `session-unit` | PASS | 17.3 | wayland-session.yml / session-smoke / Validate and test isolated session runtime |
| `ricespice-pulse` | PASS | 1.8 | wayland-session.yml / session-smoke / Validate and test isolated session runtime [PulseAudio smoke] |
| `rust-fmt` | PASS | 3.8 | (none) -- local-only addition; no hosted workflow runs rustfmt. |
| `rust-test` | PASS | 71.2 | riceplate-native.yml / native-layer-shell / Build and test native RicePlate [cargo test] |
| `rust-clippy` | PASS | 37.9 | riceplate-native.yml / native-layer-shell / Build and test native RicePlate [cargo clippy] |
| `rust-build` | PASS | 109.0 | riceplate-native.yml / native-layer-shell / Build and test native RicePlate [release build and examples] |
| `rust-repro` | PASS | 99.5 | riceplate-native.yml / native-layer-shell / Verify same-source native ELF reproducibility from a fresh target |
| `pkg-build` | PASS | 11.7 | sg6-cross-runner.yml / build / Independently compile, package and verify from exact committed source |
| `x11-gtk-unit` | PASS | 11.4 | ci.yml / test / Validate and test the suite [GTK unit suites under Xvfb] |
| `x11-luna-panel-capture` | PASS | 3.9 | ci.yml / test / Validate and test the suite [Luna Control Panel capture] |
| `x11-hub-creator-smoke` | PASS | 7.6 | ci.yml / test / Validate and test the suite [hub and Creator smoke] |
| `x11-shell-smoke` | PASS | 36.6 | ci.yml / test / Validate and test the suite [shell smoke tests] |
| `x11-gallery` | PASS | 110.2 | ci.yml / test / Validate and test the suite [screenshot gallery and compact-screen captures] |
| `components-tests` | PASS | 14.8 | ci.yml / test / Validate and test the suite [macmenu, macbar, control-center] |
| `pkg-preview-artifact` | PASS | 1.1 | riceplate-native.yml / native-layer-shell / Prepare native preview artifact with build provenance |
| `pkg-native-deb` | PASS | 13.5 | riceplate-native.yml / native-layer-shell / Build reproducible, removable native amd64 preview package |
| `pkg-session-deb` | PASS | 1.3 | riceplate-native.yml / native-layer-shell / Validate native login and both reproducible preview packages together |
| `pkg-core-desktop` | PASS | 5.9 | riceplate-native.yml / native-layer-shell / Package complete standalone Wayland app and aggregate desktop |
| `pkg-verify-set` | PASS | 1.9 | riceplate-native.yml / native-layer-shell / Reject inconsistent or unsafe Wayland release packages |
| `pkg-clean-rebuild` | PASS | 10.7 | riceplate-native.yml / native-layer-shell / Rebuild all four packages from clean tracked source |
| `pkg-tamper` | PASS | 13.3 | riceplate-native.yml / native-layer-shell / Reject source-stamped but payload-tampered core package |
| `pkg-source-identity` | PASS | 1.2 | riceplate-native.yml / attest-native-preview / Verify downloaded package and committed-source identity |
| `pkg-docker-install` | PASS | 157.2 | riceplate-native.yml / native-layer-shell / Install, reinstall and purge complete preview in disposable Ubuntu |
| `pkg-upgrade-rollback` | PASS | 223.2 | riceplate-native.yml / native-layer-shell / Upgrade all historical Debian components, inject failures and recover |
| `mint-compat` | PASS | 88.2 | riceplate-native.yml / sg6-mint221-compat / Install and recover four exact-source packages in isolated Mint 22.1 |
| `creator-examples-validate` | PASS | 1.4 | riceplate-native.yml / native-layer-shell / Validate both declarative Creator examples |
| `creator-supervisor-e2e` | PASS | 1.9 | riceplate-native.yml / native-layer-shell / Prove Creator install and recovery through the real Wayland supervisor socket |
| `calendar-analyzer-unit` | PASS | 1.3 | riceplate-native.yml / native-layer-shell / Validate two-output calendar pixel analyzer |
| `menu-analyzer-unit` | PASS | 1.3 | riceplate-native.yml / native-layer-shell / Validate two-output menu pixel analyzer |
| `sg4-creator-gtk-input` | PASS | 3.8 | riceplate-native.yml / sg4-creator-gtk-input / Verify real Wayland Tab/Return reaches both GTK Creator templates |
| `sg1-sni` | PASS | 56.8 | riceplate-native.yml / native-layer-shell / Prove real SNI provider owner lifecycle on Chrome and XP Luna under labwc |
| `sg1-window-recovery` | PASS | 7.0 | riceplate-native.yml / native-layer-shell / Prove real SG1 window minimize/restore/close recovery on Chrome and XP Luna |
| `sg1-status` | PASS | 173.3 | riceplate-native.yml / native-layer-shell / Prove honest native status controls (Wi-Fi/volume/mute) under labwc |
| `mako-build` | PASS | 1.1 | riceplate-native.yml / native-layer-shell / Build source-locked real Mako 1.11 for SG3 only |
| `sg3-ricepop` | PASS | 214.3 | riceplate-native.yml / native-layer-shell / Prove native RicePop inbox against real Mako 1.11 under labwc |
| `sg1-interaction` | PASS | 488.3 | riceplate-native.yml / native-layer-shell / Prove SG1 window/launcher/clock/SNI/failure-notice/desktop-file/output interaction negatives under labwc |
| `sg4-imported-rices` | PASS | 80.5 | riceplate-native.yml / native-layer-shell / Prove interactive pointer/keyboard/popup/error/AT-SPI behavior of both imported Creator rices (Heritage, Orbit) under labwc |
| `sg2-settings-gui` | PASS | 54.5 | riceplate-native.yml / native-layer-shell / Prove RiceSpice denied/busy/unavailable states on every settings page (real GTK under labwc, fake providers) |
| `sg4-creator-gui-roundtrip` | PASS | 47.1 | riceplate-native.yml / native-layer-shell / Prove the real GTK Creator export/import and install/apply/restore dialogs against a supervised session under labwc |
| `sg5-labwc-pin` | PASS | 1.1 | riceplate-native.yml / native-layer-shell / Build source-locked IME-capable labwc for SG5 only |
| `sg5-atspi` | PASS | 42.4 | riceplate-native.yml / native-layer-shell / Verify real input-method-v2 transactions and AT-SPI against native Run |
| `portal-smoke` | PASS | 2.2 | riceplate-native.yml / native-layer-shell / Validate portal screenshot and headless ScreenCast negotiation |
| `native-smoke` | PASS | 137.7 | riceplate-native.yml / native-layer-shell / Boot native Wayland layer surface |
| `shared-engine-smoke` | PASS | 20.0 | riceplate-native.yml / native-layer-shell / Prove shared Rice engine across three native compositor-confirmed live layouts |
| `sg7-resource-receipts` | PASS | 1.2 | riceplate-native.yml / native-layer-shell / Verify SG7 compositor resource growth receipts at exact source SHA |
| `windows-taskbar` | PASS | 9.5 | riceplate-native.yml / native-layer-shell / Prove live Wayland application taskbar lifecycle |
| `luna-show-desktop` | PASS | 5.5 | riceplate-native.yml / native-layer-shell / Prove XP Luna Show Desktop with real Wayland window and screenshot changes |
| `chrome-window-lifecycle` | PASS | 5.1 | riceplate-native.yml / native-layer-shell / Verify real Chrome-rice Wayland window lifecycle |
| `luna-autohide` | PASS | 5.2 | riceplate-native.yml / native-layer-shell / Prove real XP Luna Auto-hide and Start popup lifecycle |
| `xwayland-taskbar` | PASS | 5.8 | riceplate-native.yml / native-layer-shell / Prove legacy XWayland application uses native RicePlate taskbar |
| `clipboard` | PASS | 4.6 | riceplate-native.yml / native-layer-shell / Prove bidirectional Wayland and XWayland clipboard |
| `multioutput` | PASS | 21.6 | riceplate-native.yml / native-layer-shell / Prove two native outputs, secondary calendar/menu and hotplug |
| `creator-headless-render` | PASS | 2.6 | riceplate-native.yml / native-layer-shell / Render validated recipe in isolated Creator compositor |
| `creator-teardown` | PASS | 5.1 | riceplate-native.yml / native-layer-shell / Prove Creator teardown after real success and injected failures |
| `capture-validation` | PASS | 16.8 | riceplate-native.yml / native-layer-shell / Validate and record real multi-resolution captures |
| `luna-window-chrome` | PASS | 5.5 | riceplate-native.yml / native-layer-shell / Capture reversible Luna compositor window decorations |
| `luna-hotkeys` | PASS | 4.4 | riceplate-native.yml / native-layer-shell / Verify real XP Super+D/E/R shortcuts and native Run dialog |
| `creator-examples-render` | PASS | 31.5 | riceplate-native.yml / native-layer-shell / Render both Creator demonstrators at four real output geometries |
| `creator-composers-render` | PASS | 17.1 | riceplate-native.yml / native-layer-shell / Render two distinct Composer rices through native labwc |
| `creator-handoff-render` | PASS | 12.5 | riceplate-native.yml / native-layer-shell / Render installed Creator drafts in real isolated Wayland compositors |
| `creator-gtk-wayland` | PASS | 3.8 | riceplate-native.yml / native-layer-shell / Test real Wayland GTK Creator keyboard focus for both Composer rices |
| `portal-pixman-repeat` | PASS | 2.9 | wayland-portal-strict.yml / portal-pixman-repeat / Repeat existing pixman acceptance and verify no runtime leftovers |
| `portal-crash-recovery` | PASS | 1.5 | wayland-portal-strict.yml / portal-pixman-repeat / Crash labwc before socket creation and verify runtime recovery |
| `portal-strict-frame` | PASS | 6.0 | wayland-portal-strict.yml / portal-strict-software-frame / Strict no-DRM ScreenCast from real wlroots SHM frames to GStreamer |
| `portal-gpu-frame` | BLOCKED | 0.0 | wayland-portal-strict.yml / portal-gpu-frame / Strict ScreenCast and real frame acceptance (fail closed) |
| `session-deb` | PASS | 3.3 | wayland-session.yml / session-smoke / Build non-installed login session package |
| `session-boot` | PASS | 14.8 | wayland-session.yml / session-smoke / Boot actual labwc and Waybar headlessly |
| `mako111-real` | PASS | 14.4 | wayland-session.yml / session-smoke / Verify real source-locked Mako 1.11 notification arrivals in labwc |
| `luna-settings-labwc` | PASS | 6.5 | wayland-session.yml / session-smoke / Capture real Luna GTK system UI under native labwc |

## Not passing
- `portal-gpu-frame` BLOCKED: no DRM render node (/dev/dri/renderD*)

Logs and SHA-256 of each log are in `receipt.json`; logs are local-only (`logs/` is git-ignored). Passing local CI is software evidence only: physical-device checks and hosted attestations remain separate.
