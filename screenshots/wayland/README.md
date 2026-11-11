# RiceBowl · Wayland screenshots

[← Wayland overview](../../WAYLAND_PROGRESS.md) · [Desktop status](../../DESKTOP_ENVIRONMENT_STATUS.md) · [Native capture workflow](../../.github/workflows/riceplate-native.yml)

**Real headless labwc/RicePlate renders — not mockups or screenshots of a signed-off physical desktop.** These optimized WebP previews are permanently stored in this repository, not linked from a temporary CI artifact. Select an image to view it directly.

## XP Luna · native two-column Start menu

| Desktop with original Luna hills | Opened native Start menu |
| :---: | :---: |
| [![XP Luna Wayland desktop with green hills, green Start and blue taskbar](luna-desktop.webp)](luna-desktop.webp) | [![Native XP Luna Start menu showing Programs and Installed Apps left, System and Session right](luna-menu.webp)](luna-menu.webp) |
| Full 1366×768 compositor capture | Readability crop from an actual 1366×768 compositor capture |

`xp-luna-columns` is an **opt-in successor**, not a replacement of existing
`xp-luna` imports. The native RicePlate panel/menu and the separate `swaybg`
wallpaper process were rendered together by headless labwc. The menu is truly
open in the second capture; it is not composited onto an image afterwards.

Sources (10 November 2026): the desktop image comes from [native capture run #42890753472](https://github.com/CopyPasteUser/Ricebowl/actions/runs/42890753472), `xp-luna-columns.png`. The updated menu image comes from [native capture run #42898859348](https://github.com/CopyPasteUser/Ricebowl/actions/runs/42898859348), `xp-luna-columns-menu.png`, which verifies readable `Settings` and `Log out (N/A)` labels in the right shelf. Both permanent WebP files are derived directly from real headless compositor captures, not mockups. Hardware status widgets may read `N/A`; this is expected in a virtual headless session. **Physical ThinkPad input, scaling, power and session acceptance remain open.**

### Original Luna desktop icons · verified before/after (11 November 2026)

| Existing RicePlate shortcuts | Original Luna icon family |
| :---: | :---: |
| [![Real XP Luna desktop with the older built-in shortcut pictograms](luna-icons-before.webp)](luna-icons-before.webp) | [![Same real XP Luna compositor desktop with RiceBowl-original folder, CRT terminal and brass lock icons](luna-icons-after.webp)](luna-icons-after.webp) |
| `artwork.icons: builtin` | `artwork.icons: builtin-luna` |

[![Actual headless Luna desktop with the new pictograms and its open two-column Start menu](luna-icons-menu.webp)](luna-icons-menu.webp)

All three 1366×768 frames are optimized from **real headless labwc PNGs**
(`xp-luna-default-icons.png`, `xp-luna-columns.png` and
`xp-luna-columns-menu.png`) archived by [green native run #42960890682](https://github.com/CopyPasteUser/Ricebowl/actions/runs/42960890682)
for [PR #239](https://github.com/CopyPasteUser/Ricebowl/pull/239).
The screenshot test changes *only* the desktop icon choice in an otherwise
identical recipe, then requires more than 600 changed RGB pixels inside an
actual icon's 48×48 compositor region. The pictograms are drawn directly by
the native Rust RicePlate code, not supplied by third-party icon packs or
Windows artwork. The labels and wallpaper are unchanged; headless hardware
widgets may display `N/A`. Physical hardware acceptance remains pending.

### Luna live output matrix · 1024×768, Full HD and 125% scale (11 November 2026)

| 1024×768 at 100% | 1920×1080 at 100% | 1366×768 at 125% |
| :---: | :---: | :---: |
| [![Native Luna menu at 1024 by 768, with original shortcut artwork and full two-column menu](luna-live-1024.webp)](luna-live-1024.webp) | [![Native Luna menu at Full HD, showing the same compact taskbar and Start menu](luna-live-fullhd.webp)](luna-live-fullhd.webp) | [![Native Luna menu at 125 percent compositor scale, with larger panel and desktop shortcuts](luna-live-scale125.webp)](luna-live-scale125.webp) |
| Original 1024×768 capture | Original 1920×1080 capture, preview downsampled to 1200×675 | Original 1366×768 capture |

The **same running native RicePlate process** was exercised while labwc
switched between 1024×768, 1366×768, 1920×1080 and 1366×768 at 125%.
The smoke test first restores the output to 100% after unrelated scaling QA;
it then captures the actual compositor with the menu both closed and open at
each geometry. CI checks real screenshot dimensions, the `swaybg` wallpaper,
the taskbar pixels and an opened-menu pixel delta over 10,000. The three
optimized WebPs above are directly derived from unaltered PNG frames in
[successful native CI run #42963768429](https://github.com/CopyPasteUser/Ricebowl/actions/runs/42963768429)
(`xp-luna-columns-menu-1024x768.png`,
`xp-luna-columns-menu-1920x1080.png` and
`xp-luna-columns-menu-scale-125.png`). The full-resolution originals and all
eight captures remain in that run's artifact.

At Full HD the fixed-size Start menu is noticeably compact. This matrix
verifies compositing and geometric visibility, **not** font-size/accessibility
quality or physical mixed-DPI, touch, pointer, focus and monitor hotplug.

### Luna visual review · actual opened-menu difference maps

| 1024×768 · 100% | 1366×768 · 125% |
| :---: | :---: |
| [![Red-on-black real framebuffer heatmap of the opened native Luna menu at 1024 by 768](luna-menu-heatmap-1024.webp)](luna-menu-heatmap-1024.webp) | [![Red-on-black real framebuffer heatmap of the opened native Luna menu at 125 percent compositor scale](luna-menu-heatmap-scale125.webp)](luna-menu-heatmap-scale125.webp) |
| 93,748 pixels changed beyond RGB threshold 24 | 146,330 pixels changed beyond RGB threshold 24 |

These are **real pixel-difference maps** between the corresponding closed
and open Start-menu PNGs from [native run #42963768429](https://github.com/CopyPasteUser/Ricebowl/actions/runs/42963768429),
made with RiceBowl's existing offline `compare_wayland_captures.py` tool.
Red indicates a pixel difference; black indicates no change. The full-width
panel is not painted red because opening the menu does not repaint it. The
native CI pipeline now runs that same comparison for **all four geometries**,
archives the full-resolution heatmaps and a structured, SHA-256-attributed
`luna-menu-visual-review.json` containing panel, desktop and icon diagnostics.
The result verifies a compositor-visible state change in the expected area;
it does **not** certify interactive hit targets, screenshot fidelity to
Windows XP, accessibility or hardware performance.

### Luna Start button · real Wayland pointer click (11 November 2026)

| After first native Start click | After second native Start click |
| :---: | :---: |
| [![True 1024 by 768 compositor screenshot after a virtual Wayland pointer clicked the green Luna Start button and opened the two-column menu](luna-pointer-open.webp)](luna-pointer-open.webp) | [![The same live Luna Wayland session after a second pointer click closed the Start menu and restored the wallpaper](luna-pointer-closed.webp)](luna-pointer-closed.webp) |
| Actual menu opened by compositor input | Actual menu dismissed and desktop restored |

Both full 1024×768 WebPs are optimized from **genuine headless labwc
captures** (`xp-luna-pointer-open-1024x768.png` and
`xp-luna-pointer-closed-1024x768.png`) produced in
[successful native run #42968039762](https://github.com/CopyPasteUser/Ricebowl/actions/runs/42968039762)
for [PR #247](https://github.com/CopyPasteUser/Ricebowl/pull/247).
Unlike a `--preview-menu` screenshot, these frames follow actual
`zwlr_virtual_pointer` motion, press and release events delivered through
the compositor to the native green Start button. CI verifies the opened menu
changes more than 10,000 pixels and the second click restores the original
desktop within 5,000 pixels, including live reconfiguration at Full HD and
125% scale. All six unmodified PNGs remain in the run artifact. Input was
isolated to the throwaway CI compositor; **real ThinkPad mouse, keyboard,
touch, focus and accessibility acceptance remain open**.

### Opt-in portable font · real compositor comparison

| Bundled bitmap font | Imported private TrueType font |
| :---: | :---: |
| [![XP Luna menu using its original built-in glyphs](luna-menu.webp)](luna-menu.webp) | [![XP Luna menu using a separately imported DejaVu Sans Mono TrueType font, with readable two-column actions](luna-font.webp)](luna-font.webp) |
| Default `xp-luna-columns` | Temporary `xp-luna-font-preview` |

The right capture is a **real native RicePlate rendering** in headless labwc
from [successful native CI run #42904147986](https://github.com/CopyPasteUser/Ricebowl/actions/runs/42904147986),
`xp-luna-font-menu.png`, cropped for readability. CI imports a redistributable
DejaVu Sans Mono test font into an isolated, owner-private directory, references
its content-addressed ID from a temporary recipe and compares both real
framebuffers. No font is installed globally, and existing rices retain their
selected font. Complex shaping, toolkit-wide fonts and physical-DPI acceptance
are outside this verified feature.

### Luna calendar · native popup font comparison

| Original bitmap calendar | Owner-private DejaVu TrueType calendar |
| :---: | :---: |
| [![The native Luna calendar using built-in bitmap text, including its month heading and day grid](luna-calendar-default.webp)](luna-calendar-default.webp) | [![The native Luna calendar using the imported DejaVu Sans Mono TrueType font for its heading, weekday labels and day grid](luna-calendar-font.webp)](luna-calendar-font.webp) |
| Default `xp-luna-columns` | Temporary `xp-luna-font-preview` |

Both crops are taken from **real 1366×768 headless labwc compositor frames**
in [successful native CI run #42909714051](https://github.com/CopyPasteUser/Ricebowl/actions/runs/42909714051):
`xp-luna-columns-calendar.png` and `xp-luna-font-calendar.png`. CI opens the
native calendar popup for each recipe and verifies a visible difference inside
the calendar surface. The imported font also reaches the native volume OSD;
its own compositor proof is documented immediately below.
The original bitmap calendar pixels remain the fallback when no private face
is selected. CI uses an owner-private test asset; no global font configuration
or existing rice is modified. These previews do not replace physical display,
keyboard and accessibility acceptance.

### Luna volume OSD · real compositor comparison

| Original bitmap volume overlay | Private TrueType volume overlay |
| :---: | :---: |
| [![The real native Luna OSD with its original bitmap Volume and 68 percent labels](luna-osd-default.webp)](luna-osd-default.webp) | [![The real native Luna OSD with owner-private DejaVu Sans Mono for Volume and 68 percent labels](luna-osd-font.webp)](luna-osd-font.webp) |
| Default `xp-luna-columns` | Temporary `xp-luna-font-preview` |

Real **1366×768 headless labwc/RicePlate screenshots**, cropped around the
actual overlay, from [successful native CI run #42914562690](https://github.com/CopyPasteUser/Ricebowl/actions/runs/42914562690):
`xp-luna-columns-osd.png` and `xp-luna-font-osd.png`. The explicit
`--preview-osd` mode paints a deterministic **simulated** 68% notice into
the real, input-transparent Wayland overlay; it never changes the system
volume. The normal volume overlay still expires after 1.8 seconds. This
capture's 125%-scaled output places the 248×70 logical surface across about
310×88 physical pixels. A full overlay comparison detects **880 changed
RGB pixels**, whereas a crop assuming 100% scale missed its left-hand text.
The proof covers rendering, not hardware mixer events or physical focus.

### Luna window chrome · real XWayland before/after

| Default labwc server-side window frame | Private Luna palette-driven frame |
| :---: | :---: |
| [![Real XWayland terminal in headless labwc with the default gray titlebar](luna-window-default.webp)](luna-window-default.webp) | [![The same real XWayland terminal with a cobalt Luna titlebar, ivory client area and blue panel](luna-window-chrome.webp)](luna-window-chrome.webp) |
| Existing tabs/sidebar and unthemed recipes | Opt-in two-column Luna recipe |

Both full 1366×768 WebP files originate from the **same real headless
compositor session** in [successful native CI run #42907311728](https://github.com/CopyPasteUser/Ricebowl/actions/runs/42907311728),
`xp-luna-window-default.png` and `xp-luna-window-chrome.png`. CI boots labwc,
native RicePlate, original `swaybg` wallpaper and a genuine XWayland `xterm`,
then applies `themerc-override` only inside a temporary, owner-private config
directory. A real labwc reload changes **19,980 pixels inside the window
region** in this run; the test deliberately excludes the panel clock and
surrounding wallpaper. The photos are **not mockups**.
Third-party GTK/Qt client-side decorations do not necessarily follow this
server-side theme; focus, moving, resizing and mixed-DPI remain unaccepted on
physical hardware.

## Two different desktop compositions

| Orbit Studio | Heritage Modern |
| :---: | :---: |
| [![Orbit Studio Wayland desktop with an upper panel and custom status widgets](orbit.webp)](orbit.webp) | [![Heritage Modern Wayland desktop with a lower taskbar and desktop widgets](heritage.webp)](heritage.webp) |
| Original, dark, top-oriented layout | Classic, light, bottom-oriented layout |

## Native shell surfaces

| Native workspace | Native menu |
| :---: | :---: |
| [![Isolated native RicePlate desktop framebuffer](workspace.webp)](workspace.webp) | [![Native RicePlate sidebar menu](menu.webp)](menu.webp) |
| Native compositor framebuffer | Real native menu, cropped to show the important area |

## Where the images came from

Source: [Successful GitHub Actions run #42625109733](https://github.com/CopyPasteUser/Ricebowl/actions/runs/42625109733), commit [`8001a0a`](https://github.com/CopyPasteUser/Ricebowl/commit/8001a0a24db469358f420cc82a8ccaf4522b26c6), 9 November 2026. These are resized/compressed copies of the captured PNGs:

| File in this folder | PNG in CI artifact |
| --- | --- |
| `orbit.webp` | `creator-examples/orbit-studio-v10-1366x768-scale-1-0.png` |
| `heritage.webp` | `creator-examples/heritage-modern-v10-1366x768-scale-1-0.png` |
| `workspace.webp` | `isolated-v5.png` |
| `menu.webp` | `menu-sidebar-v6.png` (cropped) |

The full-resolution source images and SHA-256 manifests are in the run artifact while its retention period lasts. Hardware-dependent widgets may show `N/A`; that is honest headless state, not a connection failure on your device. The [XFCE/X11 screenshot gallery](../current/README.md) shows a different implementation.
