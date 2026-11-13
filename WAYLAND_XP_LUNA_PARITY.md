# XP Luna Wayland ↔ X11 parity

This is a **feature-level comparison**, not a percentage claim or a visual
acceptance certificate. The original X11 `winxp` rice is the reference. Native
Wayland uses upstream labwc plus RicePlate. Original/licensed art only.

| XP behavior | X11/XFCE `winxp` | Native `xp-luna-columns` (current sprint) | Gap |
| --- | --- | --- | --- |
| Green Start, cobalt taskbar, active tasks and notifications | XFWM/GTK shell, real tasks/status | Native taskbar, live SNI app icons and overflow, interactive network/audio/battery controls with bounded XP-style context menus | Device QA, configurable quick launch/notification-area policy, exact chrome |
| Two-column Start, program discovery and search | Installed apps, categories, search, pinned browser/mail | Native All Programs, search, saved actions and app-recents | Pinned browser/mail defaults; category flyout |
| My Computer, Documents, Pictures, Music | XDG/GVfs-backed locations and X11 Control Panel browser | Gio-backed real locations with safe missing-folder handling | Drive/volume explorer and path breadcrumbs |
| Control Panel | Dedicated XP category/task UI with applets | Native Start link opens XP-inspired category navigation in RiceSpice; deep links reach real audio, network, power, date/time and taskbar pages | More exact XP category/task hierarchy and physical-device QA |
| Help and Support | GTK Help Center with multiple pages | **Native Help window** for implemented Wayland shortcuts and capabilities | Dedicated interactive XP-style Help Center |
| Run | X11 Run dialog | **Native bounded Run dialog** using literal argv, no shell, with Unicode-safe caret editing (Left/Right/Home/End/Backspace/Delete) and proportional-font-aware horizontal input scrolling | No XDG app-name completion, IME integration or device keyboard QA |
| Recent programs and Start pins | Private favorites and history | Private persisted XP program recents; validated action pins | Reorderable Start favorites, browser/mail slots |
| Recent documents | Actual recent-file submenu | Not implemented | Recent-file provenance/privacy and file opener |
| Desktop | XFCE-managed desktop with shortcuts | Seven native originals, double-click, draggable positions and shortcut context | Desktop background context, properties, multi-select |
| File manager / Explorer | Styled Thunar with real file operations | Gio opens the registered file manager | RiceField/Explorer structural integration |
| Window decorations | XFWM Luna borders/buttons | labwc-managed decoration/theme support | Cannot skin all Wayland CSD windows |
| Display/login/recovery | Existing XFCE/X11 session | Opt-in labwc native preview; package rollback in CI | Physical Mint/ThinkPad sign-off |

## Native XP notification area and Control Panel (November 2026)

The opt-in `xp-luna-columns` panel now retains NetworkManager, WirePlumber,
power and clock icons alongside the live StatusNotifier (SNI) application tray
at regular and compact widths where a task slot can fit. SNI icons continue to
activate their real providers and use provider-owned D-Bus menu actions;
overflow paging is used if more than three app icons need space. The native
Network, Volume, Power and Clock indicators open XP-colored, keyboard-navigable
local menus rather than sending fake SNI events. Actions are capability-gated
and use the existing bounded, verified system-control workers.

The `ricebowl de settings --luna` command opens a searchable XP-inspired
Control Panel category overview with a scrollable sidebar and accessible
category rows. Direct links via `--page <category>` continue to reach the
same real RiceSpice service backends; generic RiceSpice remains unchanged. Available pages: network, audio, notifications, bluetooth,
displays, input, accessibility, timezone, power, appearance and taskbar.
`ricebowl de settings` retains its original presentation; XFCE defaults
and other rices are untouched. Taskbar settings currently provide real links
and describe unimplemented options instead of presenting nonfunctional
checkboxes.

**Open:** XP-style network/audio/power menu interaction and keyboard/AT-SPI
focus need actual labwc/ThinkPad sign-off. Native pin reordering, show/hide per
app icon, quick-launch preferences, auto-hide and exact historical artwork
remain future work; no hardware completion is implied by Rust or Python tests.

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

The Run entry now supports **in-place editing** rather than forcing deletion
from the end: Left/Right moves one Unicode scalar, Home/End jumps to the ends,
Backspace removes the preceding scalar and Delete removes the following one.
The visible caret and horizontally scrolled input share the actual selected
font's measured advances; the existing 192-character/16-argument and no-shell
execution restrictions are unchanged. This is Unicode scalar-safe editing,
not full grapheme-cluster editing or IME composition.

The headless-labwc Run smoke now injects **real Wayland virtual-keyboard
events** through `wtype` (available in Ubuntu 24.04) and archives the original
unmodified compositor PNGs: `xp-luna-parity-run-typed.png`,
`xp-luna-parity-run-edited.png`, and `xp-luna-parity-run-cleared.png`.
The sequence types `abcd`, uses Left/Backspace and inserts `X`, then uses
Home/Delete to clear the field, all without executing the command. Pixel
diffs on the real input rectangle and a separate caret-pixel assertion
reject a fake or inert native editor. The Rust tests additionally cover
multibyte input and actual proportional-font width calculations.

**Evidence status: pending green Native RicePlate CI on the exact PR head.**
These screenshots are compositor-generated CI captures, not physical device,
IME, screen-reader, or pixel-fidelity certification.

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
