# XP Luna Wayland ↔ X11 parity

This is a **feature-level comparison**, not a percentage claim or a visual
acceptance certificate. The original X11 `winxp` rice is the reference. Native
Wayland uses upstream labwc plus RicePlate. Original/licensed art only.

| XP behavior | X11/XFCE `winxp` | Native `xp-luna-columns` (current sprint) | Gap |
| --- | --- | --- | --- |
| Green Start, cobalt taskbar, active tasks and notifications | XFWM/GTK shell, real tasks/status | Native taskbar, real Quick Launch/Show Desktop, owner-private Auto-hide, live SNI icons, window-specific task-button context actions and XP-style system menus | Device QA, pinned application policy, taskbar locking, exact popup chrome |
| Two-column Start, program discovery and search | Installed apps, categories, search, pinned browser/mail | Native All Programs, search, saved actions and app-recents | Pinned browser/mail defaults; category flyout |
| My Computer, Documents, Pictures, Music | XDG/GVfs-backed locations and X11 Control Panel browser | Gio-backed real locations with safe missing-folder handling | Drive/volume explorer and path breadcrumbs |
| Control Panel | Dedicated XP category/task UI with applets | Native Start link opens XP-inspired category navigation in RiceSpice; deep links reach real audio, network, power, date/time and taskbar pages | More exact XP category/task hierarchy and physical-device QA |
| Help and Support | GTK Help Center with multiple pages | **Native Help window** for implemented Wayland shortcuts and capabilities | Dedicated interactive XP-style Help Center |
| Run | X11 Run dialog | **Native bounded Run dialog** using literal argv, no shell, with Unicode-safe caret editing (Left/Right/Home/End/Backspace/Delete) and proportional-font-aware horizontal input scrolling | No XDG app-name completion, IME integration or device keyboard QA |
| Recent programs and Start pins | Private favorites and history | Private persisted XP program recents; validated action pins | Reorderable Start favorites, browser/mail slots |
| Recent documents | Actual recent-file submenu | Not implemented | Recent-file provenance/privacy and file opener |
| Desktop | XFCE-managed desktop with shortcuts | Seven native shortcuts with double-click, drag/multi-select, shortcut context, and private labwc background menu with real Arrange/New Folder/Refresh/Properties actions | File-backed dynamic icons, fuller New submenu, physical input QA |
| File manager / Explorer | Styled Thunar with real file operations | Gio opens the registered file manager | RiceField/Explorer structural integration |
| Window decorations | XFWM Luna borders/buttons | labwc-managed decoration/theme support | Cannot skin all Wayland CSD windows |
| Display/login/recovery | Existing XFCE/X11 session | Opt-in labwc native preview; package rollback in CI | Physical Mint/ThinkPad sign-off |

## Native XP task-button actions (13 November 2026)

On the opt-in `xp-luna-columns` panel, right-clicking a **real task button**
or pressing Menu while it is focused opens a local context menu rather than
the general taskbar preferences. A single window supports Restore, Minimize,
Maximize and Close; application groups support selecting any of the first
20 real windows, Next window, Restore all, Minimize all and Close group.
Foreign-toplevel handles are captured by proxy identity and checked against
the current compositor task set before dispatch; app-controlled titles are
control-character filtered. The menu reuses the existing on-demand Wayland
layer without a resident background worker. Non-Luna rices retain their
original pointer behavior.

The headless compositor [taskbar CI run #43402926584](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43402926584)
validated pointer hit-testing, the visible menu, and a real Minimize/Restore
state transition. [Original screenshots and their limits](screenshots/wayland/README.md#real-xp-luna-taskbar-window-menu--13-november-2026).
Full XP context-menu visual fidelity, accessible global keyboard focus,
physical-device acceptance and support for other compositor protocols
remain open.

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
and other rices are untouched. The XP Luna Taskbar and Start Menu page now offers an actual **12/24-hour
clock-format setting** saved atomically in owner-private
`~/.config/ricebowl/luna-panel.json` (or the user's absolute
`XDG_CONFIG_HOME`). RicePlate reads this preference **once at Luna startup**:
the change takes effect at the next Luna session, never restarts the current
panel, and does not affect the non-Luna clock. The existing system control
links remain working. An independent owner-private `luna-taskbar.json`
stores real Quick Launch and Auto-hide options, applied at next Luna startup.
Taskbar locking, drag-to-reposition and per-provider icon hiding remain
unimplemented and are never shown as fake switches.

**Open:** XP-style network/audio/power menu interaction and keyboard/AT-SPI
focus need actual labwc/ThinkPad sign-off. Native pin reordering, show/hide per
app icon, taskbar locking and exact historical artwork remain future work;
no hardware completion is implied by Rust or Python tests.

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

## Refreshed Wayland screenshot evidence (13 November 2026)

The checked-in [six-view native Luna gallery](screenshots/wayland/README.md)
now shows real labwc desktop, Start, Help, typed Run, right-click context and
shortcut Properties surfaces from successful CI
[#43354447753](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43354447753)
at source commit `c0bdb46c`. A reproducible, fail-closed publisher verifies
the compositor manifest and produces RGB WebP previews without UI simulation.
It is *not* evidence of visual parity against all X11 dialogs or acceptance
on a physical Mint laptop.

The current X11 parity gaps remain: recent documents, fuller Explorer/drive
workflow, pinned default browser/mail, category navigation and hardware
integration. Avoid presenting a successful headless screenshot as proof these
gaps are closed.

## Real browser and mail entries in native Luna (13 November 2026)

On a fresh XP-Luna Start menu, the two limited installed-app preview slots
prioritize **actually discovered** Firefox/Chromium and Thunderbird/Evolution
desktop files where present. Prior user-launched programs still outrank these
defaults; missing/uninstalled/hidden XDG entries are never fabricated, and
remaining slots fall back to the existing alphabetical app index. All Programs,
non-Luna rices and the private recent-history format remain unchanged.
This is tested XDG discovery and menu ordering, **not** a hard-coded browser
or mail app installed by RiceBowl, and not a full XP Internet/E-mail preference
editor.

## Native XP Luna fidelity: layered taskbar and Start-menu hierarchy

The opt-in `xp-luna-columns` renderer uses a brighter cobalt rim, a darker
taskbar underside, a real status-area boundary, and distinct raised/recessed
task-button states. The Start button gains an additional bounded green bevel.
The original RiceBowl user tile now has a more substantial recessed frame;
the two menu columns have independent ivory / pale-blue faces and a beveled
session footer. Enlarged (400×380 or 480×456) menus smooth the *same*
320×304 logical canvas; no pointer/action geometry is inferred from pixels.

The first XP-like **functional** menu reorganization shows the two actually
discovered/persisted-recent program previews at the top left, the real Terminal
action in the center, and the real All Programs action just above the footer.
These are shared `MenuTile` hit targets, not inactive imitation rows. Mouse,
keyboard, AT summaries, and virtual-pointer labwc smoke use the same order.
The fallback recipe without a Luna palette, all other rices and compact menu
layout retain their previous behavior. Unknown XDG apps receive an original
generic application-window symbol, never a pretend vendor icon.

The [native CI workflow](.github/workflows/riceplate-native.yml) exercises
the moved All Programs pointer target and full-resolution labwc/grim captures
at 1024×768, 1366×768, 1920×1080 and 125% output scale. Visual correctness on
headless pixman is *not* a physical Mint/ThinkPad 1:1 XP acceptance, and this
pass does not claim an original Microsoft theme.

## Sprint 3 – Visuelle Fidelity 2.0 (13 November 2026)

This sprint targets the **native labwc + RicePlate XP Luna Columns** rice only.
Its goal is clearer, more consistent XP-era UI art, not a pixel-exact claim
about proprietary Windows assets.

- **Typography:** native proportional glyph advances center the Start label,
  12/24-hour clock and desktop shortcut captions correctly. Long real window
  titles and XDG menu actions use bounded, Unicode-safe ellipsis truncation
  against their drawing rectangles instead of assuming eight pixels per glyph.
- **Desktop labels:** unfocused shortcuts now float directly above the wallpaper
  with a dark text shadow rather than permanently opaque label pills. Only
  focused icons keep the blue highlight; icon surfaces and focus input stay
  the same.
- **Menu symbols:** Programs and Control Panel now have distinct folder/gear
  glyphs; Lock and Log off have distinct lock/door-arrow glyphs. The artwork is
  original raster drawing without a system icon-theme dependency.
- **Window chrome:** private, opt-in labwc server-side Luna chrome receives a
  brighter active cobalt gradient and muted inactive steel-blue frame. The
  tested border width and 26-pixel titlebar buttons remain unchanged.
- **Regression protection:** Rust checks exercise font-width and menu-icon
  pixels. Python checks verify the private theme and non-Luna isolation.

**Unchanged:** recipe schema, native menu logical 320×304 hitboxes, pointer
inverse mapping at 400×380/480×456, X11/XFCE, global labwc theme, session
commands, unrelated recipes or desktop icon hit regions.

**Acceptance gate:** passing Tests and Native RicePlate prototype workflows
on the exact sprint head, plus a genuine headless labwc screenshot. A capture
from an unmerged revision must never be described as a current-main capture.

Physical hardware input, client-side GTK/Qt titlebar styling and the separate
labwc keyboard-focus issue are not resolved by this visual sprint.

## XP Luna Desktop/Taskbar functional Sprint 1 (13 November 2026)

Opt-in `xp-luna-columns` now has three genuine compact Quick Launch buttons:
Apps, Terminal and Show Desktop. The first two dispatch their existing
allowlisted program actions; Show Desktop requests minimize/unminimize through
real wlr foreign-toplevel handles, and only remembers windows it actually
minimized. The restore request is idempotent on a fast second click and never
reopens a previously closed toplevel.

Luna taskbar settings expose Quick Launch visibility and Auto-hide. The
`luna-taskbar.json` options use a separate versioned, 0600 owner-private,
CAS-guarded atomic file under `$XDG_CONFIG_HOME/ricebowl/`; the GTK settings
client and native Rust renderer validate the same bounded contract at next
login. Auto-hide adjusts layer-shell exclusive zones on the primary/mirrored
panels and leaves a 3-pixel handle for compositor pointer reveal. Settings
never change XFCE or the shared schema-v12 recipe file.

Labwc's existing root-menu binding handles a right-click on **empty desktop
space** without adding a full-screen input surface. Only Luna's temporary
private labwc menu exposes four fixed commands: Arrange Icons (reorder
the validated built-in shortcut layers), New Folder (create a uniquely named
real subdirectory inside an existing owned XDG Desktop and open it in Gio),
Refresh (rescan the app index and redraw icons), and Properties (open real
RiceSpice Appearance). These are sent to the existing RicePlate session over
a non-world-readable Unix datagram socket, with strict allowlist and no
shell-evaluated recipe commands. No root daemon or new background worker.

**Limitations:** The desktop uses fixed, recipe-defined shortcut layers,
not a file-backed dynamic desktop: a New Folder does not yet appear as a new
shortcut. Taskbar drag-locking is not exposed because taskbar position is
currently recipe-managed and not freely draggable. Linux apps owning their
own client-side window frames are outside Luna's border styling. These are
software increments, not a physical ThinkPad or Orca acceptance certificate.

## Follow-up sprint – Native XP keyboard shortcuts (13 November 2026)

The opt-in **native** `xp-luna-columns` profile now compiles a private
labwc keyboard map for the XP-era Super/Windows-key combinations:

| Key | Actual native action | Guarantee |
| --- | --- | --- |
| Super+D | Toggle RicePlate Show Desktop | Shares the real taskbar restoration list; does not invent a second compositor window-state model |
| Super+E | Open My Computer | Uses the existing RiceField-then-Gio local navigation fallback |
| Super+R | Open native Run | Uses the existing explicit Run dialog with argv-only execution, not a shell |

The session compiler only enables these fixed, allowlisted IPC commands for
a full native XP Luna session. Nested previews, Waybar and all other rices
keep labwc's original defaults, including its own Super+D binding.
Live rice switching adds/removes the shortcuts transactionally and restores
the exact previous XML if reconfigure or persistence fails. A successful
Waybar rescue removes stale IPC shortcuts. No global/XFCE/system labwc
configuration is changed. Super+L and Super+Return remain the existing
RiceBowl Lock and Terminal shortcuts.

**Not a keyboard focus fix:** This does not change the draft desktop icon
context-menu type-to-select PR #327. labwc's keyboard focus limitation for
unfocused Bottom/Overlay layer-shell shortcuts still needs an xdg-popup-backed
solution and a real compositor/keyboard acceptance test. The new hotkeys
themselves must pass headless labwc CI and physical hardware QA before
1.0 sign-off.

## Sprint 2 – Auto-hide lifecycle & real Show Desktop acceptance (13 November 2026)

The optional XP Luna taskbar now tracks **real compositor pointer focus** over
its layer surfaces. A pointer leaving the bar while Start, the calendar or an
SNI/status popup is open does not prematurely shrink it. On dismissal, a
shared, tested policy checks the actual pointer location and remaining active
popups, then collapses the bar if appropriate. It does not poll hardware,
add a timer, move the pointer or alter other RicePlate rices.

Closed real window handles and a terminated wlr foreign-toplevel manager are
pruned from the in-memory Show Desktop restoration transaction. This avoids
retaining dead proxies after clients exit without restoring a window that the
user had already minimized before Show Desktop was clicked.

The native CI now has a dedicated headless **labwc + real `foot` window**
case. It presses the actual 32px Show Desktop region using the Wayland
virtual-pointer client, waits for `minimized=true`, presses again and waits
for `minimized=false`. Screenshots are captured through `grim`, with
`luna-taskbar-window-open.png`, `luna-taskbar-show-desktop.png` and
`luna-taskbar-window-restored.png` written into the native preview artifact
only on a passing run; pixel difference is checked between open and hidden
states. Classic and XWayland taskbar tests remain separate and unchanged.

These checks validate actual compositor behavior on the headless pixman backend,
not Mint/ThinkPad hardware or the still-blocked native type-to-select focus
work. No new visual assets are fabricated for the screenshots.
