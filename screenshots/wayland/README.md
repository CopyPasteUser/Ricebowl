# RiceBowl · Native Wayland screenshots

[← RiceBowl](../../README.md) · [Wayland setup](../../WAYLAND.md) ·
[XP Luna parity](../../WAYLAND_XP_LUNA_PARITY.md) · [XFCE/X11 gallery](../current/README.md)

**Real labwc + native Rust RicePlate captures, not rendered mockups.**
They were recorded in an isolated headless compositor with a pixman renderer
and virtual input. They show the experimental Wayland desktop, **not**
physical-hardware acceptance or completed Windows XP fidelity.

## XP Luna · verified screenshot gallery (13 November 2026)

Source: successful [Native RicePlate CI run #43368674306](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43368674306),
on the then-current **main** commit
[bdbae75](https://github.com/CopyPasteUser/Ricebowl/commit/bdbae75b4c3fbc1c721fed4c20a231c227ef0a54).
Each preview links to the full-size checked-in WebP.

| Desktop and taskbar | Two-column Start menu |
| :---: | :---: |
| [![Native Wayland XP Luna desktop with shortcut icons and taskbar](luna-desktop-20261113.webp)](luna-desktop-20261113.webp) | [![Native XP Luna two-column Start menu](luna-start-20261113.webp)](luna-start-20261113.webp) |

| All Programs · pointer navigation | Taskbar calendar |
| :---: | :---: |
| [![All Programs page navigated with genuine Wayland pointer input](luna-all-programs-20261113.webp)](luna-all-programs-20261113.webp) | [![Calendar panel beside a real terminal window on the native desktop](luna-calendar-20261113.webp)](luna-calendar-20261113.webp) |

| Desktop shortcut context menu | Shortcut properties |
| :---: | :---: |
| [![Recycle Bin shortcut context menu opened by right-click](luna-context-20261113.webp)](luna-context-20261113.webp) | [![Native shortcut properties opened through the context menu](luna-properties-20261113.webp)](luna-properties-20261113.webp) |

| Help & Support | Run dialog |
| :---: | :---: |
| [![Native XP-inspired Help and Support dialog](luna-help-20261113.webp)](luna-help-20261113.webp) | [![Run dialog with text entered through a virtual Wayland keyboard](luna-run-20261113.webp)](luna-run-20261113.webp) |

The [provenance record](luna-gallery-provenance-20261113.json) pins each
original PNG filename, source commit, CI run, framebuffer dimensions,
SHA-256 of the source and SHA-256 of the published WebP. All eight previews
come from [the verified-artifact importer](../../scripts/import_native_wayland_gallery.py).
No desktop elements are added or painted after capture. Six established WebP
URLs are retained; All Programs and calendar are new entries.

**More recent, unmerged fidelity work:** [XP Luna PR #335](https://github.com/CopyPasteUser/Ricebowl/pull/335)
has separate, genuine captures in [successful CI candidate #43377726436](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43377726436)
on commit 0d85613a. Full-resolution PNGs are available from the
riceplate-native-preview artifact of that run. These unfinished visuals are
**not silently mixed** into the main-branch gallery.

## Native input interactions

| Find after pointer click | Saved after context-menu pin |
| :---: | :---: |
| [![Find page opened through Wayland pointer input](luna-pointer-find.webp)](luna-pointer-find.webp) | [![Saved actions populated by genuine right-click](luna-saved-pinned-rightclick.webp)](luna-saved-pinned-rightclick.webp) |

Source: [Find/Back CI #42973287104](https://github.com/CopyPasteUser/Ricebowl/actions/runs/42973287104) ·
[Pin/unpin CI #42977523704](https://github.com/CopyPasteUser/Ricebowl/actions/runs/42977523704).
These are earlier tested interactions, not captures from the gallery revision.

## Resolution, scaling and window frames

| 1024×768 | 1920×1080 | 125% output scale |
| :---: | :---: | :---: |
| [![Native Start menu at 1024 by 768](luna-live-1024.webp)](luna-live-1024.webp) | [![Native Start menu at Full HD](luna-live-fullhd.webp)](luna-live-fullhd.webp) | [![Native Start menu at 125 percent output scale](luna-live-scale125.webp)](luna-live-scale125.webp) |

[Live output reconfiguration CI #42963768429](https://github.com/CopyPasteUser/Ricebowl/actions/runs/42963768429).
The Full HD preview is downscaled for viewing; original PNGs are in its
CI artifact. This does not establish mixed-DPI hardware support.

| Default XWayland frame | Optional Luna-colored frame |
| :---: | :---: |
| [![Default labwc server-side XWayland frame](luna-window-default.webp)](luna-window-default.webp) | [![Luna-inspired server-side XWayland frame](luna-window-chrome.webp)](luna-window-chrome.webp) |

[Window chrome CI #42907311728](https://github.com/CopyPasteUser/Ricebowl/actions/runs/42907311728).
This only covers tested server-side decorations, not arbitrary client-side
decorated windows.

## Other experimental Wayland compositions

| Orbit Studio | Heritage Modern |
| :---: | :---: |
| [![Native Orbit Studio composition](orbit.webp)](orbit.webp) | [![Native Heritage Modern composition](heritage.webp)](heritage.webp) |

Source: [creator example CI #42625109733](https://github.com/CopyPasteUser/Ricebowl/actions/runs/42625109733).

## Settings screenshots and capture limits

The separate GTK3 Control Panel client has genuine Xvfb screenshots in
[Tests CI #43368674304](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43368674304),
including luna-control-panel-home.png and luna-control-panel-taskbar.png.
The keyboard-search version also produced luna-control-panel-search.png in
[Tests CI #43375407093](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43375407093).
They are **GTK/Xvfb screenshots, not native labwc compositor captures**.

Headless CI cannot confirm physical trackpad/keyboard input, real GPU
rendering, Wayland login, audio/network hardware, suspend/resume,
accessibility or pixel-perfect XP parity. For a capture of your own running
Wayland session use the capture script with grim installed:

    scripts/capture_wayland_panel.sh /absolute/new-capture.png

Existing files are never overwritten.

See the [native CI workflow](../../.github/workflows/riceplate-native.yml),
[engineering progress](../../WAYLAND_PROGRESS.md) and
[release gates](../../RELEASE_1_0_GATES.md).
