# XP Luna Wayland ↔ X11 parity

This is a **feature-level comparison**, not a percentage claim or a visual
acceptance certificate. The original X11 `winxp` rice is the reference. Native
Wayland uses upstream labwc plus RicePlate. Original/licensed art only.

| XP behavior | X11/XFCE `winxp` | Native `xp-luna-columns` (current sprint) | Gap |
| --- | --- | --- | --- |
| Green Start, cobalt taskbar, active tasks and notifications | XFWM/GTK shell, real tasks/status | Native painted buttons, live toplevels/tray/status | Full device QA and exact chrome |
| Two-column Start, program discovery and search | Installed apps, categories, search, pinned browser/mail | Native All Programs, search, saved actions and app-recents | Pinned browser/mail defaults; category flyout |
| My Computer, Documents, Pictures, Music | XDG/GVfs-backed locations and X11 Control Panel browser | Gio-backed real locations with safe missing-folder handling | Drive/volume explorer and path breadcrumbs |
| Control Panel | Dedicated XP category/task UI with applets | **Control Panel** Start link opens real RiceSpice settings | No native XP nine-category presentation |
| Help and Support | GTK Help Center with multiple pages | **Native Help window** for implemented Wayland shortcuts and capabilities | Dedicated interactive XP-style Help Center |
| Run | X11 Run dialog | **Native bounded Run dialog** using literal argv, no shell | No XDG app-name completion; device keyboard QA pending |
| Recent programs and Start pins | Private favorites and history | Private persisted XP program recents; validated action pins | Reorderable Start favorites, browser/mail slots |
| Recent documents | Actual recent-file submenu | Not implemented | Recent-file provenance/privacy and file opener |
| Desktop | XFCE-managed desktop with shortcuts | Seven native originals, double-click, draggable positions and shortcut context | Desktop background context, properties, multi-select |
| File manager / Explorer | Styled Thunar with real file operations | Gio opens the registered file manager | RiceField/Explorer structural integration |
| Window decorations | XFWM Luna borders/buttons | labwc-managed decoration/theme support | Cannot skin all Wayland CSD windows |
| Display/login/recovery | Existing XFCE/X11 session | Opt-in labwc native preview; package rollback in CI | Physical Mint/ThinkPad sign-off |

## New native Run/Help design

The opt-in themed v12 two-column menu exposes **Help and Support** and
**Run...** in its ten-action right shelf. The two remaining session actions
and the independent Lock/Log off footer are preserved. System layout validates
identical bounds in Rust and Python Creator.

Both commands create an on-demand 448×232 logical-pixel Wayland layer, centered
inside the selected output's usable area and destroyed when dismissed.
No daemon, extra compositor, global keyboard grab while closed, or change to
XFCE defaults.

Run accepts user-typed commands with bounded UTF-8 input and quoted arguments.
It rejects shell operators, unclosed quoting, relative executable paths,
control characters and unbounded argument counts. Successful confirmation
uses direct `std::process::Command` argv execution; it **does not** start a
shell, parse arbitrary recipe strings or perform `eval`. Missing executable
and invalid input yield visible feedback. No command executes on dialog open
or on an empty confirmation.

Help shows only supported, actually implemented keyboard and shortcut
instructions; it does not pretend to provide online support or full Control
Panel task coverage.

## Native capture and acceptance

`scripts/smoke_riceplate_native.sh` captures **real labwc/grim PNG frames**
at 1366×768 with direct compositor pointer input:

- `xp-luna-parity-start.png` — newly expanded Start columns
- `xp-luna-parity-help.png` — opened native Help dialog
- `xp-luna-parity-run.png` — opened native Run dialog
- `xp-luna-parity-run-empty.png` — visible invalid-input feedback

It asserts actual dialog-region pixel differences and closes both surfaces by
their real hit targets. Headless tests cannot certify physical keyboard
handling, IME, DPI, file-manager integration or a final visual match to XP.

See [Wayland progress](WAYLAND_PROGRESS.md),
[the X11 Luna benchmark](XP_LUNA_ROADMAP.md) and
[the native CI workflow](.github/workflows/riceplate-native.yml).
