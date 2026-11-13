# RiceBowl screenshot gallery

**42 real GTK/X11 captures** from a verified pull-request build. Click any preview to open it full-size.

**Looking for Wayland?** These are *XFCE/X11* captures. See the separate [Wayland guide](../../WAYLAND.md) and [Wayland screenshot gallery](../wayland/README.md) instead; its CI artifact contains actual RicePlate frames, not simulated XFCE themes.

<p align="center">
  <a href="aero-start.webp"><img src="aero-start.webp" alt="Windows 7 Aero Start menu" width="48%"></a>
  <a href="windows10-start.webp"><img src="windows10-start.webp" alt="Windows 10 Start menu" width="48%"></a>
  <a href="winxp-start.webp"><img src="winxp-start.webp" alt="Windows XP Luna Start menu" width="48%"></a>
  <a href="winclassic-start.webp"><img src="winclassic-start.webp" alt="Windows 98 Start menu" width="48%"></a>
  <a href="chromeos-start.webp"><img src="chromeos-start.webp" alt="ChromeOS launcher" width="48%"></a>
  <a href="frutiger-start.webp"><img src="frutiger-start.webp" alt="Frutiger Aero launcher" width="48%"></a>
</p>

## Explore the details

| Style | Controls | Real application window |
| --- | --- | --- |
| Windows 7 | [Control Panel](aero-controls.webp) | [Thunar / XFWM4](aero-workspace.webp) |
| Windows 10 | [Action Center](windows10-controls.webp) · [Expanded](windows10-actions-expanded.webp) · [A–Z Start](windows10-letters.webp) · [Settings home](windows10-settings-home.webp) · [Sound](windows10-settings-sound.webp) · [Storage](windows10-settings-storage.webp) · [Apps](windows10-settings-apps.webp) · [Volume](windows10-audio.webp) · [Calendar](windows10-calendar.webp) · [Network](windows10-network.webp) · [Task View](windows10-task-view.webp) | [Thunar / XFWM4](windows10-workspace.webp) |
| XP Luna | [Control Panel](winxp-controls.webp) · [All Programs](winxp-programs.webp) · [Detail](winxp-detail.webp) · [Classic view](winxp-classic.webp) | [Thunar / XFWM4](winxp-workspace.webp) |
| Windows 98 | [Control Panel](winclassic-controls.webp) | [Thunar / XFWM4](winclassic-workspace.webp) |
| ChromeOS | [Quick Settings](chromeos-controls.webp) · [Notifications](chromeos-notifications.webp) · [Settings](chromeos-settings.webp) | [Thunar / XFWM4](chromeos-workspace.webp) |
| Frutiger Aero | [Aqua controls](frutiger-controls.webp) | [Thunar / XFWM4](frutiger-workspace.webp) |

**XP extras:** [Taskbar properties](winxp-properties.webp) · [Notification icons](winxp-notification-icons.webp) · [Run](winxp-run.webp) · [Audio](winxp-tray-audio.webp) · [Network](winxp-tray-network.webp) · [Battery](winxp-tray-battery.webp) · [Bluetooth](winxp-tray-bluetooth.webp) · [Clock](winxp-tray-clock.webp)

**macOS Aurora:** [Live standalone MacMenu](macmenu-dark.webp). A current integrated MacBar/dock desktop capture is still pending.

<details>
<summary>Capture provenance and limitations</summary>

These are actual applications rendered under XFWM4 in virtual X11 at 1600×900, not mockups. The [successful 5 November 2026 CI run](https://github.com/CopyPasteUser/RiceBowl/actions/runs/42045518423) captured commit [`cdf458a`](https://github.com/CopyPasteUser/RiceBowl/commit/cdf458a899051d26f563ce0c7eddfea7e2c61ab7). The [manifest](manifest.json) records original and converted image hashes; compact 1024×768 captures are in the CI artifact. Historical `0.9.1` capture filenames are script compatibility names, not the tested release version.

Virtual-X11 captures do not establish physical Mint/XFCE hardware, suspend or multi-monitor acceptance. Unavailable device features in CI are shown honestly.

</details>
