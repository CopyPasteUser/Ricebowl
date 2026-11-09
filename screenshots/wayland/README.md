# RiceBowl · Wayland screenshots

[← Wayland overview](../../WAYLAND_PROGRESS.md) · [Desktop status](../../DESKTOP_ENVIRONMENT_STATUS.md) · [Native capture workflow](../../.github/workflows/riceplate-native.yml)

**Real headless labwc/RicePlate renders — not mockups or screenshots of a signed-off physical desktop.** These optimized WebP previews are permanently stored in this repository, not linked from a temporary CI artifact. Select an image to view it directly.

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
