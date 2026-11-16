# XP Luna Wayland — first large acceptance pass (opt-in)

**Purpose:** a repeatable, evidence-driven first **device** trial of the
experimental native RiceBowl/labwc desktop. This is **not** a 1.0 release
approval, nor proof that SG1–SG7 in issue #417 are complete. Keep XFCE/X11
installed and selectable. Never change the default login session implicitly.

## 0. Source and software baseline

Record the exact tested Git commit and review the recent `main` CI:
`Tests`, `Native RicePlate prototype` (including headless labwc), and,
where applicable, `Wayland session preview`. A green PR head alone is not
accepted as a post-merge test. Capture the workflow URLs in the human notes.

From your normal XFCE session, without changing defaults:

```bash
ricebowl de check --json
# Optional, entirely separate preview:
ricebowl de start --nested --panel native --recipe xp-luna-columns
```

A nested test can exercise desktop interaction but **cannot** certify
display-manager login, lid/suspend, physical lock/unlock or a real GPU portal.

## 1. Real session, only when ready

Use the **RiceBowl (Native Wayland Preview)** login-manager entry that is
documented in [WAYLAND_SESSION.md](../WAYLAND_SESSION.md). Keep the original
XFCE entry independently available, and save all open work before changing
sessions. Do not disable XFCE autologin or remove any packages during this
first pass.

In a terminal launched inside the native session:

```bash
ricebowl de acceptance --json
# From a source checkout whose commit you have recorded:
python3 scripts/qa_xp_luna_first_pass.py \
  --output "$HOME/ricebowl-xp-acceptance-01" --json
```

The private evidence folder **must not exist already**. Use a new absolute
path for subsequent runs. The second command creates a mode-0700 folder,
a mode-0600 JSON report, an exact current-session preflight and a same-UID
snapshot of labwc/RicePlate/Mako/Waybar/idle-lock RSS/PSS. No commands,
window titles, monitor serials or Wi-Fi credentials are collected. It does
**not** benchmark idle CPU, startup time or certify any device check.

To additionally retain a real screenshot for visual review, opt in explicitly:

```bash
python3 scripts/qa_xp_luna_first_pass.py \
  --output "$HOME/ricebowl-xp-acceptance-screen-01" --capture
```

The screenshot may include **private on-screen contents**. Its PNG remains
local, permission 0600, with size/hash receipt; inspect and redact it before
sharing. A failed screen capture is reported as failed, never as passed.
Without `--capture`, the tool does not invoke grim.

## 2. Manual acceptance matrix

The operator must perform these actual interactions and record **PASS**,
**FAIL**, **NOT RUN** or **N/A**, plus a short symptom, time, commit and
screenshot/log reference. Do not copy/paste commands with private data to
public issues. Neither automated CI nor a successful preflight may fill in
these results.

| Area | Actions on actual Mint/ThinkPad | Result |
| --- | --- | --- |
| Login and recovery | Greeter choice, repeated native login/logout, return to XFCE | NOT RUN |
| Start and search | Open/cancel, multiword app search, keyboard navigation, actual launch | NOT RUN |
| Luna Run | Super+R, editing, Shift selection, Ctrl+A, Unicode insertion, failed executable, Escape | NOT RUN |
| Desktop files | Create folder, rename, Trash/restore, file manager/RiceField, denied/stale action | NOT RUN |
| Taskbar/windows | Native and XWayland application tasks, minimize/restore, Alt+Tab, Show Desktop | NOT RUN |
| Tray and controls | SNI context menu, Wi-Fi/volume unavailable and write/readback states | NOT RUN |
| Multi-display | Different scales, move shortcut, detach/reconnect, owner-local menu/calendar | NOT RUN |
| Input and accessibility | Physical keyboard, IME preedit+commit, Orca focus/text selection, mouse | NOT RUN |
| Portals/media | Clipboard, Flatpak file dialog consent/cancel, real PipeWire screen frames | NOT RUN |
| Power and lock | Swaylock, idle lock, lid suspend/resume, watcher crash fail-safe | NOT RUN |
| Resources | Cold startup, 10-min idle CPU/wakeups, settled PSS, repeated rice switching/leak trend | NOT RUN |
| Rollback | Logout and normal XFCE login with unchanged user configuration | NOT RUN |

**Stop criteria:** any unlock bypass, insecure session fallback, unsaved-file
loss, incorrect cross-display action target, input focus deadlock or failure
to return to XFCE. Preserve logs, reproduce safely, revert the changed
optional preview, and open a focused issue with the exact tested commit.
Never disable locking or weaken assertions to get a green result.

## 3. What actually counts as acceptance

- **Software:** native Rust/unit/Clippy and real compositor smoke, packaging
  rollback and exact-main CI all green on the same tested SHA, with links.
- **Device:** operator marks every relevant item above using real hardware,
  with date, distro/kernel, GPU/session/display conditions and evidence.
- **Release 1.0:** all shared software issue #417 gates and physical
  release sign-off in [RELEASE_1_0_GATES.md](../RELEASE_1_0_GATES.md) are met.
  The acceptance script *never* writes or approves sign-off JSON.

After this first pass, focus XP Luna fidelity on **observed** differences:
taskbar and Start proportions, native menu hierarchy, window interactions,
font sizing, icon composition and sound/animation polish. Keep upstream labwc
as compositor and all Linux services on their shared backends.
