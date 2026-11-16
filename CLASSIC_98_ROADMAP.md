# Windows 98 SE Classic · implementation roadmap

The goal is a **recognizable, genuinely functional Windows 98-style Linux XFCE
desktop**, not a generic silver recolor, an XP menu or a static illustration.
Original GPL-compatible RiceBowl art only; no proprietary Microsoft icons,
bitmaps, fonts or binaries. Keep Windows XP, 7, 10, ChromeOS, Frutiger and
macOS behavior and artwork unchanged.

## Source references and measured direction

- [GUIdebook: Windows 98](https://guidebookgallery.org/guis/windows/win98/)
  — screenshots of the original Start hierarchy, 3D controls and Explorer.
- [Windows 98 explained: Start menu figure](https://nmetau.edu.ua/file/130.pdf)
  — gray vertical-menu body with a blue side strip; compact hierarchical rows.
- [GUIdebook: Classic UI](https://guidebookgallery.org/screenshots/appearance/)
  — the historical system-control/appearance model. These are observation
  sources only; no pixels are copied into the project.
- Identity: flat `#008080` desktop, raised `#c0c0c0` surfaces, focused
  `#000080` menu and active XFWM title, sharp dark/white two-pixel relief,
  narrow sans-serif type, low-density icon palette and **zero rounded corners**.
  The original CRT/penguin symbol is the explicit Linux adaptation.

## Seven delivery steps

1. **[x] Audit actual renderer against the real Win98 UI.** Examine the
   1600×900 native screenshot, live GTK/XFWM files, Start and Control Panel
   behaviors, reversible presets and prior icon generator. The prior
   watery/glass wallpaper, spacious 430px menu and 53px generic taskbar
   contradicted Win98's 1998 look.
2. **[x] Restore the correct desktop and taskbar silhouette.** Regenerate a
   crisp solid-teal wallpaper, set a 34px panel, downscale the original custom
   Linux Start badge to 19px, compact launcher/task buttons, keep window state
   and real audio/network/battery indicators and use a single-line clock.
3. **[x] Build a real Win98 Start hierarchy.** Side-printed `RiceBowl 98` strip,
   dense item rows with true icons and hover/focus `Gtk.MenuButton` cascades:
   Programs (real Gio categories), Favorites, Documents and Settings. Find
   expands real installed-app search; Help/Run launch available XFCE utilities
   only; Shut Down opens XFCE's confirmation dialog, never executes immediately.
4. **[x] Draw native-era window chrome.** Generate brand-new square 22px XFWM
   minimize/maximize/close/shade buttons in four interaction states, 27px
   active navy/inactive silver title segments and embossed 3D frame borders.
5. **[x] Finish coordinated GTK/Thunar/icons.** Style focus, pressed/disabled,
   menu, notebook, scrollbar, toolbars and actual Thunar controls; use small
   original pixel icons for Start, Settings, Find, Help, Run and Shutdown.
   `--classic-only` regenerates this identity without touching other rices or
   overwriting existing hand-curated 98 icons.
6. **[x] Prove basic functionality and upgrade safety.** Retain event-driven
   Wnck/Gio app launch, right-click pinning, keyboard search, hardware status,
   safe session handoff and restore snapshots. Exact prior git blob hashes
   trust only unmodified managed files for backup-backed asset upgrades;
   custom user changes still block automatic replacement.
7. **[x] Validate and release real implementation.** Run all Python tests,
   GTK CSS parser, CI native-Xvfb shells and real 1600×900 + 1024×768
   screenshots; inspect the result, refine if needed, update current-only
   README gallery and then merge the tested PR into GitHub `main`. Verified:
   229 Python tests (1 environment skip), headless GTK/X11 smoke, 12 distinct
   1600×900 native captures plus 1024×768 Classic, XP, Win7 and Frutiger
   captures. Successful run: [41622039625](https://github.com/CopyPasteUser/RiceBowl/actions/runs/41622039625).

## Acceptance criteria

- At a glance it unmistakably reads as **Windows 98**, while the included
  artwork makes clear that the host remains Linux.
- The Start menu never overlaps the taskbar, including at 1024×768; cascading
  and keyboard-focused actions work as genuine GTK widgets.
- Control Panel presents usable real XFCE controls and actual device status.
- All original installer backups, theme conflict guards, external tools,
  installed program pinning and six other rice identities remain intact.
- GitHub screenshots are actual GTK/X11 captures of the merged code, not mockups.
- CI virtual desktop does not replace physical Mint/XFCE acceptance, which
  remains an owner-side smoke test.

## Complete Windows 98 SE fidelity backlog — 4 November 2026

**Status: OPEN.** The seven checked stages above describe a successful first-pass shell, **not** a complete Windows 98 recreation. This backlog is the next implementation contract. Do not mark a checkbox done because an icon, a CSS selector, a click handler or a screenshot exists: it must pass the behavioral acceptance test for that item.

### Product definition and boundaries

- Reference target: **Windows 98 Second Edition**, default classic desktop with the IE4 Desktop Update-era shell. Preserve the authentic late-1990s information architecture, control density, menu hierarchy, keyboard semantics and multi-click workflows while performing real Linux operations.
- `winclassic` now identifies **Windows 98 SE** only. A separate Windows 2000 preset remains future work and must have its own title bars, taskbar, icons, startup and shell details before being advertised.
- Keep the existing XFCE/X11 session, file associations, login manager, rollback journal and all six other rices safe. No proprietary Microsoft binaries, icon extractions, sounds, fonts, desktop bitmaps, IE/ActiveX, registry emulator or false C: drive semantics. This is a Linux shell inspired by Windows 98, not Windows 98 binary compatibility.
- **One-click promise:** every enabled item completes a real action; unavailable hardware/backend options remain visible where historically meaningful, disabled with the reason and a recovery path. Dialogs explain errors in the visual language of this rice, not as an unrelated modern dashboard.
- **Second-click promise:** every submenu, details window, property tab, context action, modal confirmation and system setting is as polished and interactive as the first Start-menu click. No fake controls or inert buttons.
- Primary operating target: owner's Linux Mint XFCE/X11 ThinkPad. CI with virtual X11 is a gate, not a substitute for keyboard, audio, Wi-Fi, battery, suspend, external display and session-switching acceptance on the real machine.

### Evidence-based baseline: what exists and what does not

`macrice/aero_shell.py:_create_classic_menu()` currently builds a 262×332 GTK Start popup with the vertical RiceBowl 98 rail, Gio Programs flyout, fixed Favorites/Documents folder lists, a small Settings flyout, in-menu Find, XFCE Help/Run and XFCE session logout. The bottom taskbar and Wnck window list are real. `macrice/heritage_shell.py` applies period colors and bevels, while `scripts/build_heritage_assets.py` produces the classic XFWM/GTK theme and limited original icons. `macrice/thunar.py` styles actual Thunar rather than supplying Explorer's navigation model. The `winclassic` branch in `_create_actions()` produces a bottom-right, undecorated 382px Control Panel popup with **eight launcher tiles**, hardware status and a verified volume control; it is not a full Control Panel application. Tray status clicks route audio/battery to that shared popup and network to a Linux editor. `tests/test_classic_98.py` largely tests markup, assets, style contracts and configured geometry; do not treat it as exhaustive end-to-end interaction coverage.

Current evidence: source files, existing roadmap, current repository screenshot *inventory*, and CI declarations. The installed physical desktop and every nested popup have **not** been visually inspected in this pass. All below is an open acceptance backlog, not reported implementation.

### Implementation checkpoint — riceSpice/ricePlate migration (4 November 2026)

**Code complete; physical Mint acceptance pending.** This checkpoint migrates
existing device flows without claiming the much wider Windows 98 SE backlog is
finished.

- [x] Route Classic taskbar status and verified volume/mute changes through a
  single closeable, bounded riceSpice GTK worker. Remove Classic-specific
  per-action threads, keep XFCE audio/network ownership and no extra daemon.
- [x] Give the small Classic Network dialog an actual Wi-Fi radio switch,
  available SSID list, manual scan, connect/disconnect and explicit failures;
  password-required connections hand off to the installed NM editor.
- [x] Add Bluetooth radio and paired-device actions plus audio output choice,
  brightness and available power schemes. Unsupported features stay disabled;
  every write is verified by the shared backend before success is shown.
- [x] Open these separate, beveled classic dialogs from actual Control Panel
  applets. Handle Escape, focus loss, rice/screen transitions, async stale
  callbacks and shell shutdown without losing XFCE's tray ownership.
- [x] Provide a bounded, read-only XFDesktop inventory via ricePlate, with
  explicit desktop-folder navigation; no icon placement, wallpaper, shortcut
  file or MIME mutation is performed.
- [x] Label the existing classic rice **Windows 98 SE** in the app catalog;
  Windows 2000 remains a future, separate option.
- [ ] CI native X11 smoke and current screenshots for this checkpoint.
- [ ] Physical Mint/XFCE tests: real Wi-Fi/credentials, Bluetooth, audio
  outputs, brightness, power profiles, keyboard-only navigation, offline and
  denied permissions, 1024×768, suspend/resume and full rice switch/recovery.

Remaining: full Win98 Control Panel tabs, desktop virtual folders and
recycle-bin semantics, native RiceExplorer skin, notification-era details,
advanced tray hosting and the other fidelity milestones below.

### Implementation checkpoint — functional shell phase A (4 November 2026)

**Status: partial, pending CI and physical Mint validation.** The broad milestones below remain unchecked until their entire acceptance gates pass. This increment adds functional descendants without confusing them with complete Windows 98 fidelity.

- [x] Split Win98-specific Start logic into `classic98_menu.py`: real Gio programs, categorized groups and unclassified applications without the previous 20-item truncation.
- [x] Read GTK recent-file history for Documents; offer confirmation before clearing history without deleting any files.
- [x] Import GTK bookmarks and maintain user-owned RiceBowl favorites with add, rename/update, remove, reorder and atomic 0600 persistence.
- [x] Add a dedicated Run dialog with Browse, explicit error display, shell-free argument parsing and no persisted command history.
- [x] Add cancellable, bounded, read-only filename search in a selected folder (not yet content/date/type search).
- [x] Add local Help topics covering RiceBowl Win98 Linux behaviors.
- [x] Add a normal movable/resizable Control Panel window with all-icons view, double-click/keyboard activation, available real Linux applets and disabled unavailable tools.
- [x] Add a separated pinned-app Quick Launch strip, Show Desktop and Wnck-backed context menus on individual running-window buttons (Restore, Move, Size, Minimize, Maximize, Close with real capability checks).
- [x] Add compact audio/network/battery/calendar popups using existing live hardware state and verified volume/mute handlers.
- [x] Add nine focused tests for persistence, URI safety, shell-free Run, applet discovery, live Wnck action dispatch and centered screenshot-crop regression.
- [x] Add dedicated classic Taskbar Properties, reachable from Start, Control Panel and a taskbar context menu: persistent per-rice clock/Quick Launch toggles with working Apply/OK/Cancel, private atomic settings and four regression tests. Unsupported auto-hide/position settings remain disabled.

- [x] Refine Win98 Run with a 12-item in-memory history, a Clear history action and inline failure text. Four ordering/bounds tests added; hardware interaction remains to be validated.
- [x] Add Programs submenu context actions for Open / Add to Quick Launch / Remove from Quick Launch, respecting the existing per-rice pin limit, with three focused menu-state tests. Real pointer/focus acceptance remains open.

### Implementation checkpoint — Windows 98 Find filters (4 November 2026)

**Implemented on feature branch; CI and physical Mint acceptance required before closing a full milestone.**

- [x] Extend Find → Files or Folders with real filename, extension, file/folder, modification-period, size and hidden-file filters; preserve the familiar single-window Find flow with an expandable advanced section.
- [x] Add bounded UTF-8 content search of ordinary files (1 MiB per file / 32 MiB per request). Content search never follows final symlinks or opens non-regular file devices.
- [x] Keep asynchronous worker scanning, 50,000-entry / 500-result caps, stale-generation protection and explicit Stop behavior; no indexing service or file mutation.
- [x] Add nine disposable-filesystem regressions for filtering, text matching, symlink avoidance, cancellation and bounded results.
- [ ] Validate full Find dialog on physical Mint, 640×480 and 1024×768, including keyboard-only operation, missing permissions, network volumes and very large folders.
- [ ] Integrate future RiceExplorer search backend instead of duplicating engines when its safe search API is ready; add Computer discovery only after GIO/GVfs integration.

**Still open:** complete original hover/cascade keyboard geometry; folders within Favorites; Programs context actions; persistent opt-in Run history and .desktop targeting; Finder Computer discovery, full-text indexing and rich search results; advanced Taskbar options (auto-hide/position), dedicated Folder Options; full Display Properties tabs; independent Quick Launch configuration; comprehensive tray NetworkManager/XEmbed operation; window context menus; desktop virtual folders; structural riceExplorer skin; Win98/2000 preset split; era accessories; and physical Mint acceptance. Do not close a milestone until its full gate passes.

### Implementation checkpoint — navigable Classic Help (4 November 2026)

**CI passed via PR #38; physical Mint validation still outstanding.**

- [x] Replace the original six-topic static Help dialog with a dedicated local Windows 98-style viewer offering Contents, alphabetical Index and on-device Search.
- [x] Add functional Back, Forward and Home navigation with real topic history and clearly labeled UI controls; topic pages document actual Linux behaviors, supported options and feature limitations.
- [x] Add four content/index/search regression tests plus a native GTK/Xvfb interaction test for opening topics, going Back and filtering Search.
- [ ] Complete contextual Help links from every Control Panel applet, localized documentation and advanced keyboard/screen-reader acceptance on physical Mint.

**Gate:** Help search and navigation must work after multiple clicks without opening a generic browser, losing focus or making unsupported Windows functionality claims.

### Implementation checkpoint — native System Properties (4 November 2026)

**Implemented on branch, pending full CI and physical Mint acceptance.**

- [x] Replace the external `xfce4-about` shortcut behind the Win98 Control Panel's **System** icon with a real tabbed **System Properties** dialog.
- [x] General reports the actual Linux distribution, kernel, architecture, CPU model and RAM; Device Manager lists actual network interfaces and block devices without pretending they are Windows drivers; Performance reports current available memory and uptime.
- [x] Provide a manual Refresh button instead of a permanent polling daemon. The applet reads only bounded `/etc/os-release`, `/proc` and `/sys` properties and cannot modify settings or devices.
- [x] Add five disposable-fixture regression tests and one native GTK/Xvfb System Properties construction test.
- [ ] Polish classic property tabs/icons and test localization, real laptop devices, unplug events, missing sysfs data and low-resolution sizing on Linux Mint.

**Gate:** the System applet must report correct real Linux facts and remain usable without privileged access or a process-monitoring daemon.

### Implementation checkpoint — mounted Computer browser (16 November 2026)

**Code delivered on a dedicated branch; CI and physical Mint acceptance pending.**
This is a narrow functional increment, not completion of Milestone 1, 3, or 5.

- [x] Replace the disabled Start > Find > Computer action with a native
  nonmodal Classic window. Also expose the same browser from Start > Programs >
  My Computer while retaining the original Explorer (Home) entry.
- [x] Display actual GIO mounted volumes, with local Home and filesystem
  fallback. Deduplicate URIs, cap the list at 128 mounts, and update only on
  real mount changes or user-initiated searches. Never invent Windows drives,
  mount devices implicitly or access remote data in the background.
- [x] Show Network Neighborhood browsing only when the active GVfs advertises
  the `network:///` handler; the installed file manager retains URI,
  authentication and error-handling ownership.
- [x] Implement search, keyboard-activatable list, Open/Close, unavailable
  messages and clean GIO signal disconnect when closing the window. Add pure
  tests for device removal, invalid mounts, duplicate roots, search privacy,
  bounds and unsupported GVfs.
- [x] On the explicit Classic Explorer Home entry and mounted local folders,
  prefer installed **RiceField 1.0** with its real `win98` UI via
  `ricefield --theme win98 --separate-window PATH`. Use argument vectors
  (never a shell) and fall back to the current GIO default file manager
  if the binary is absent or cannot start; keep remote URIs with GIO.
  Do not change systemwide MIME defaults or replace XFDesktop.
- [ ] Pass branch CI, including native GTK/X11 second-click smoke and updated
  screenshots from the exact branch commit.
- [ ] Validate USB, GVfs/SMB, no-network-backend, permission failures and
  keyboard navigation on the owner's physical Mint XFCE installation.

**Still open:** discovering *unmounted* network computers and full Network
Neighborhood, Computer desktop icon interactions, volume mount/eject workflows,
Recycle Bin integration, RiceExplorer virtual locations, and all other unchecked
milestones below.

### Milestone 0 — Freeze references, safe state and test harness (P0)

- [ ] Create an era-specific Win98 SE reference matrix with reference screenshots and behavior notes for: blank desktop, Start plus **each** flyout, crowded taskbar, Quick Launch, tray menus, My Computer, Explorer in classic and Web View, Control Panel and representative applets, Run, Find, shutdown, properties, copy conflict and error dialogs. Record source/date and observable behavior; never copy proprietary assets.
- [ ] Record actual first-click, second-click and third-click flow captures from current RiceBowl at 640×480, 800×600, 1024×768, 1600×900 and HiDPI. Include keyboard-only operation, long German/English labels, 125%/150% scaling and two monitors. Name every clipped, blank, inert or offscreen state.
- [ ] Record immutable baseline versions/commit, current shell processes, XFCE panel and xfdesktop configuration, shortcuts, Plank autostart, GTK and XFWM values, desktop icon layout, default file manager, notifications and clipboard ownership. Produce reproducible plan/apply/restore evidence.
- [ ] Add a Win98-specific behavior-test matrix alongside existing screenshots: menu path → expected Linux backend → success/error state → owner of interaction → screenshot/test. Tests must exercise live widgets, not only search for CSS strings.
- [ ] Audit current themes/icons for unsupported glyph names, stock fallback, wrong icon dimensions, bad low-DPI downsampling and cross-rice leakage. Document licensing and source of every new asset.
- [ ] Publish a small compatibility statement: GTK3 apps can be closely themed; GTK4/libadwaita, Qt, Electron, browsers and privileged dialogs cannot be made pixel-identical by a GTK3 stylesheet. The first-party shell remains consistent regardless.

**Gate:** complete reproducible baseline, no data-destructive test against real user folders, all original profile restore tests still pass.

### Milestone 1 — Authentic Start menu and its real descendants (P0)

- [ ] Match Windows 98 geometry: compact width, genuine left-side vertical wordmark, sharp blue selection highlight, correct 16px icons, separators and disabled shadows; preserve a usable menu at 640×480 and with enlarged fonts.
- [ ] Implement the original hierarchy and order: **Programs**, **Favorites**, **Documents**, **Settings**, **Find**, **Help**, **Run…**, **Shut Down…**. Submenus must open to the available screen side without covering their parent, maintain hover intent/focus and never remain orphaned after profile switch.
- [ ] Programs: actual categories, nested subfolders, alphabetical ordering and unclassified `.desktop` entries; executable/desktop-file validation; no shell interpolation; working context menu for launch, pin/add shortcut, open location (where valid), properties and remove user pin. Handle uninstalled/reinstalled programs.
- [ ] Accessories folder: map to genuine Calculator, Text Editor/Notepad equivalent, Paint equivalent (when available), Character Map, Accessibility and Terminal; Games folder only with installed games. Preserve user-created groups, ordering, favorite shortcuts and reversible configuration.
- [ ] Favorites: editable bookmark hierarchy and folders from an explicit XDG/RiceBowl source, not a hardcoded Home/Desktop/Downloads stand-in. Add/remove/rename/reorder with safe local persistence; launch URL through default browser and folder through the selected file manager.
- [ ] Documents: genuinely recent user documents via an appropriate GTK/XDG recent-files source, with privacy opt-out, clear-history confirmation, missing-file indication and correct default-app launch. Keep “My Documents” as a separate known folder; do not confuse recent documents with fixed Pictures/Music folders.
- [ ] Settings flyout: **Control Panel, Printers, Taskbar & Start Menu, Folder Options**, plus hardware-dependent items. Each opens a dedicated functional window/dialog; no settings destination may silently route to an unrelated global popup.
- [ ] Find flyout: **Files or Folders** (real cancellable filename/content/date/type/location search), **Computer** (discover or open real network resources when available), plus clear “not available” information for unsupported targets. Never present ordinary app search as a substitute for file search.
- [ ] Run: dedicated Win98-style `Run…` modal with history, browse, env/tilde-safe parsing, URI and desktop-app support, working cancel/enter/escape; no arbitrary shell execution by string concatenation, no privilege escalation, no saving secrets in command history.
- [ ] Help: original RiceBowl help viewer or clear local HTML/documentation index with hierarchical topics, Contents/Index/Search/Back, Linux equivalents and working links. Don't disguise `xfce4-about` as Windows Help.
- [ ] Shut Down: custom classic dialog with real, separately confirmed Log Out, Restart, Shut Down, Suspend and Cancel **only if the session exposes them**. No automatic restart or fake standby; test denied permission, running updates and dirty-window safety.
- [ ] Keyboard: `Ctrl+Esc`/Super Start, arrows to traverse cascades, Enter/Space, Esc, type-to-select, mnemonic underlines where practical, Shift+F10 context, Win+R, Win+E, F1 and focused Alt+F4. Do not steal global shortcuts without a reversible, opt-in binding and conflict check.
- [ ] Test pointer-only, keyboard-only, rapid repeated opening, pinned app removal during menu display, missing `.desktop` executable, 640px narrow screens and long translations. Assert focus return to Start and no invisible active submenu.

**Gate:** 100% of enabled Start paths launch genuine targets and every three-level cascade remains navigable without clipping/focus loss.

### Milestone 2 — Taskbar, Quick Launch and notification area (P0)

- [ ] Classic 28–34px taskbar silhouette with configurable 3D raised borders, recessed active button, non-grouped running-window text buttons, classic divider and narrow, consistently positioned clock; correct active/inactive and minimized states from Wnck/X11, not guessed state.
- [ ] Real **Quick Launch** section beside Start: separate from running windows and ordinary pins, configurable shortcut collection, reorder by drag and drop, add/remove from context menu, hover tooltip, visible separator and dedicated **Show Desktop** action.
- [ ] Full window-button context menu: Restore, Move, Size, Minimize, Maximize and Close according to actual WM capabilities; correct task ordering, window titles/icons, focus switching, urgent attention indication and right-click on group/overflow. No automatic Windows 7 grouping in Classic.
- [ ] Functional taskbar context menu and **Taskbar Properties** dialog: Always on Top (subject to WM), Auto Hide, Small Icons, Show Clock, Quick Launch/toolbars, Lock Taskbar, notification-area behavior and taskbar position. Journal every changed XFCE/Wnck setting and restore exactly when switching rice.
- [ ] Support overflow safely, several dozen windows, long/non-Latin titles, fullscreen games, modal-child windows, two monitors, moved taskbar and auto-hide without hiding dialogs behind it. X11 workarea/struts must reflect actual orientation and size.
- [ ] Complete tray host interoperability: existing StatusNotifier integration plus a guarded XEmbed compatibility strategy for legacy X11 tray icons; do not steal the selection/host from XFCE or duplicate icons on switching profiles. Apps retain their own real menus and activation semantics.
- [ ] Small icon-anchored **audio** popup: real slider, mute, output device, clear backend errors, update confirmation; classic 3D control styling and accessibility names.
- [ ] Small **network** popup: show live wired/Wi-Fi state, connected SSID, signal where provided, available WLANs and connect/disconnect only via NetworkManager/Polkit with asynchronous confirmation; no fake ON toggle.
- [ ] Small **battery/power** popup: UPower charge state, charging/discharging, time estimate if available, brightness when supported, accessible power setting; no fabricated percentages on a desktop PC.
- [ ] **Clock/calendar**: 12/24h and locale-aware short date, optional double-click date/time dialog, current timezone and calendar. Permission-requiring changes must use the installed system mechanism rather than `sudo` execution from GUI.
- [ ] Real removable-media, print queue and Bluetooth notification-menu integrations when installed; distinguish installed/disconnected/unsupported states. Tray icons and popups must close on outside click, Esc, session switch or loss of device without hanging focus.
- [ ] Period-faithful **tooltips and small dialogs**, not XP balloons or a Windows 10 Action Center. Optional notification messages only for real events, deduplicated and dismissible without breaking the desktop's notification daemon.

**Gate:** open and use all supported popups on ThinkPad Wi-Fi, speakers, battery and HDMI; repeat after suspend/reconnect; no lost tray items or multiple tray hosts.

### Milestone 3 — Desktop surface, special folders and right-click behavior (P0/P1)

- [ ] Desktop icons for **My Computer, My Documents, Network Neighborhood, Recycle Bin** and user shortcuts; correct double-click behavior, selected/focused label colors, shadow/dotted rectangles, drag selection and configurable traditional grid (aligned/auto-arranged/manual).
- [ ] Use existing xfdesktop where its actual capabilities suffice. If independent placement, layered widgets or special virtual folder behavior cannot be implemented without fighting XFCE, build an **optional, separately owned `riceDesktop` surface module** with clean X11 desktop-window ownership and rollback, rather than injecting competing icons/selection on top of xfdesktop.
- [ ] Desktop right-click: Arrange Icons (by Name/Type/Size/Date, Auto Arrange, Align to Grid), Refresh, Paste, Paste Shortcut, New (Folder/Text/Shortcut), Properties. Each operation must work on the target, deny safely when unwritable and reflect file changes immediately.
- [ ] Icon context menus: Open/Explore, Send To (only supported destinations), Cut/Copy/Create Shortcut/Rename/Delete/Properties; multiple selection, keyboard F2/Delete/Shift+Delete and safe confirmation of permanent deletion.
- [ ] Recycle Bin maps to XDG Trash with restore/original path, Empty confirmation, permission/error states and accurate full/empty icon; never silently implement delete with `rm -rf`.
- [ ] My Computer lists actual mounts, filesystems and devices using GIO/UDisks2, with Linux-native labels/capacities and no fictional drive letters; optional aesthetic drive letters only as explicit aliases that do not affect paths.
- [ ] Network Neighborhood browses actual mounts/SMB discovery or explains missing backend, authentication and offline status; do not invent a Windows domain/workgroup.
- [ ] Desktop properties: wallpaper color/image/tiling, grid/icon size, screensaver (available app), resolution/scale, classic appearance and effects; keep user-specific icon positions and wallpaper reversible on switching rice.
- [ ] Optional Active Desktop **look** with safe static, local opt-in widgets only, no IE/ActiveX execution and no arbitrary remote HTML as desktop wallpaper. Classic non-Web mode remains the default.

**Gate:** every special icon has a working destination and desktop actions survive logout/relogin, unplugged disks and profile restore.

### Milestone 4 — Full Windows 98-style Control Panel program (P0/P1)

- [ ] Replace the **undecorated bottom-right eight-tile status popup** with a real independent, movable, resizable classic window with XFWM frame, statusbar, icon grid, Help/menu behavior, scroll/focus support and launchable applets. Keep tray volume/status in separate mini-popups.
- [ ] Preserve Win98's **all-icons Control Panel**, not XP category view or Windows 7 search-first categories. Original-art 32px icons, captions, selected/focused states, keyboard navigation, double-click activation and optional large/small icon/list/detail views.
- [ ] **Display Properties** applet with classic tabs: Background (actual wallpaper/color/position), Screen Saver (installed backend), Appearance (RiceBowl classic palette/accessible fonts), Effects (supported visual effects), Settings (real display configuration, confirm and time-limited rollback after mode change). No unsupported driver claims.
- [ ] **Mouse** applet: button handedness, speed, double-click test, pointer scheme where supported; use XFConf/GSettings with accurate readback. Keyboard applet: repeat rate/delay and accessible focus controls.
- [ ] **Sounds/Multimedia**: devices, verified output/input/mute, volume slider, actual default device selection, optional sound-event mapping. The current working global volume control is reused, not reimplemented differently.
- [ ] **Network**: active interfaces, Wi-Fi connect/disconnect, DNS/IP status read-only, network connections editor, retry and permissions. A network applet must not pretend to configure unsupported legacy protocols.
- [ ] **System**: OS/hardware information, mounted volumes, process/memory overview where safe, hardware manager links, kernel/driver facts clearly labeled Linux rather than a fictional Windows device manager.
- [ ] **Add/Remove Programs**: list real package-managed, Flatpak and user-installed applications where discoverable; launch the system's authorized software-management/uninstall path; don't write a custom package remover or claim universal uninstall support.
- [ ] **Printers**, **Fonts**, **Accessibility Options**, **Power Management**, **Regional Settings**, **Date/Time**, **Folder Options**, **Internet Options / browser defaults** and optional **Bluetooth**: each requires a period-styled page or a clearly labeled supported system tool, correct disabled/error state and documentation of its Linux backend.
- [ ] **Properties/dialog consistency:** tab controls, group boxes, sliders, checkboxes, sliders' arrows, progress, listviews, Apply/OK/Cancel, keyboard mnemonics, reset and validation match Classic's 3D rhythm. Apply changes only after verification; Cancel restores unapplied changes.
- [ ] Use shared backend adapters for Xfconf, UPower, NetworkManager, PipeWire/PulseAudio and XDG/GIO; do not create root daemons or permanent polling merely for the theme. Backend reads/writes remain asynchronous and permission-aware.
- [ ] Control Panel can open from Start, My Computer, keyboard shortcut and help links; all routes target **the same** applet/window and may raise an already-open window.

**Gate:** open every icon, complete one representative real setting per category, cancel/restore and retest on the ThinkPad; missing tools never masquerade as working applets.

### Milestone 5 — RiceField: structural Windows 98 Explorer integration, not Thunar CSS (P0 dependency)

**Dependency update (16 November 2026):** The repository previously named
riceExplorer is now [RiceField](https://github.com/CopyPasteUser/Ricefield).
RiceField 1.0.0 already has a tested Rust file-management core and a distinct
`win98` style. The Classic shell can now launch that style for local locations;
that does **not** prove the complete legacy Explorer menu tree, virtual My
Computer/Network Neighborhood/Recycle Bin, all dialog styles, DnD or hardware
acceptance below. Earlier references to riceExplorer in historical checkpoints
refer to the same renamed project, not a second file manager.

**Owner:** `CopyPasteUser/riceExplorer`. Do **not** fork a second file-operations engine into RiceBowl. RiceExplorer's backend safety/recovery work (0.3), GIO volumes/network (0.4), everyday navigation (0.6) and shell integration (0.9) must pass their own gates before it becomes the default. Thunar stays installed and one-click recoverable.

- [ ] Build a real **Win98 shell layout** under a versioned RiceExplorer theme schema: classic menu bar (File/Edit/View/Go/Favorites/Tools/Help), large/small icon options, Back/Forward/Up toolbar, Address combobox, folders tree, file grid, status bar and optional Explorer bar/Web View. This must rearrange maintained UI components, not just repaint `egui` buttons.
- [ ] Start > Programs > Windows Explorer, My Computer and desktop folder icons open RiceExplorer's correct virtual location/URI. Window title/icon, history and toolbar buttons reflect the actual selected view; identical open/launch semantics in all themes.
- [ ] My Computer page for real filesystems, removable disks and mounted network shares; capacity, type, filesystem and mount/unmount/eject via safe GIO/UDisks2 operations. No fictional C: and no operations that bypass Polkit.
- [ ] Network Neighborhood page backed by GVfs discovery and SMB/SFTP/WebDAV connections, with credentials via supported secret storage, reconnect/timeouts, offline/error states and privacy controls.
- [ ] Recycle Bin virtual location maps to XDG Trash with restore, original-path details, permanent-delete confirmation and drag/drop integration.
- [ ] Folder tree with expandable/collapsible nodes, lazy navigation, context menus, selection synchronization, rename and deep-tree keyboard use, preserving performance for huge paths and network latency.
- [ ] View options: Large Icons, Small Icons, List, Details; correct column sorting, hidden files, extensions, grouping and folder-specific view persistence. Optional Web View shows **safe local file metadata**, not an embedded unrestricted browser or IE engine.
- [ ] Full File/Edit menus, drag-and-drop within/between windows and applications, desktop clipboard URI integration, Ctrl+C/X/V/Z, Shift/Control selection, F2 rename, Delete/Shift+Delete, context actions and safe Send To targets.
- [ ] Classic folder/file properties: name, type, actual path/URI, size, modified/access times, access permissions/ownership, MIME/Open With, optional read-only/hidden Unix mapping with explicit behavior. Show actual file metadata rather than pretend Windows attributes.
- [ ] Real transfer queue with cancel, progress, ETA, conflicts (replace/skip/rename/compare/apply-to-all), cross-device moves, interrupted-transfer recovery, explicit partial outcomes and undo where safe. Protect existing data with fault-injection tests and crash/restart trials before making it default.
- [ ] Search/Find files window backed by RiceExplorer engine (not application search); filename/text/date/size criteria, location picker, asynchronous cancellation, invalid/empty/no-results/offline states and keyboard-driven results.
- [ ] File associations and Open With through MIME/GIO, desktop launcher behavior, network URIs, USB mount signals, status bar count/free-space and explicit permissions for destructive operations.
- [ ] Integrate skin change via RiceBowl IPC/config so a running RiceExplorer can switch layouts without losing tabs, selection, history, bookmarks or transfers; fallback on malformed/missing themes; tests prove Windows 98 vs Windows 7 vs macOS are structurally distinct.

**Gate:** complete a real file-workflow matrix on local SSD/HDD, USB, Trash and at least one network share, then switch themes mid-transfer. No data loss, double-action or unresponsive UI. Only then replace the `winclassic` file-manager target; preserve Thunar fallback.

### Milestone 6 — Consistent native-era dialogs, visual states and shared widgets (P1)

- [ ] One reusable **classic widget/dialog layer inside RiceBowl** for raised/sunken borders, dotted focus, menu separators, radio/checkboxes, tabs, list/tree views, scrollbars, spin buttons, progress, file/property dialog shells, tooltips, disabled states, nested menus and keyboard mnemonic styling.
- [ ] Standard Error/Warning/Question/Information dialogs with period-consistent 16/32px original glyphs and genuine specific message/cancel/repair paths; no generic alarming “Error occurred” or silent failure.
- [ ] Applets, Start, taskbar, tray and built-in RiceBowl dialogs share control metrics and current theme tokens. Do not forcibly restyle privileged system dialogs, browsers or GTK4/Qt applications beyond officially supported mechanisms.
- [ ] Pixel-faithful era state matrix: focused/unfocused window, active/inactive menu, hover/pressed/disabled button, selected/unselected list item, checkbox toggled, read-only field, busy progress, drag target, context menu and keyboard focus.
- [ ] Classic Window System: titlebar active navy/inactive gray, accurately sized bitmap-like controls for minimize/maximize/restore/close, tiny system-menu icon, double-click caption maximize, correct resize borders and snapping-free drag by default. Implement only supported XFWM behavior; never replace the WM without a clear, reversible need.
- [ ] Original-art Win98-inspired icon set: 16/24/32/48px apps, drives, printer, network, folders, Trash, MIME categories, shortcuts, warnings and Control Panel; inspect pixel-grid rendering at 100/125/150/200% and maintain accessible contrast. Do not stretch unrelated flat symbolic GNOME icons across classic controls.
- [ ] Original or appropriately licensed pointer shapes: arrow, busy/wait, help, resize, text, link and drag; clear focus and minimum target accommodations. Original/licensed sounds for login, error, success, critical event and shutdown are optional and independently toggled.
- [ ] Locale/typography: compact metrically appropriate freely licensed font, correct traditional menu density, baseline/underline alignment, English/German translations, 12/24h clock and right-to-left label fallback without truncation.

**Gate:** representative first-party UI has no generic GTK popup that abandons 3D Classic visual language on the second click; no regressions in disabled/error/focus states.

### Milestone 7 — Era-appropriate bundled tools (P1/P2; create only when needed)

| Tool / entry | Reality and target | Owner / scope |
| --- | --- | --- |
| **Run dialog** | Required: typed commands/URI/desktop app selector, browse, history, validation, errors | `macrice/classic_run.py` or shared shell dialog, **new UI**, reuse safe launcher |
| **Find: Files or Folders** | Required: independent criteria/results window, real cancellable search | RiceExplorer backend + Win98 search skin; not a second search daemon |
| **Control Panel** | Required: all-icons index, dedicated functional applets with proper tabs | `macrice/classic_control_panel.py`; use existing Linux backend adapters |
| **Display/Taskbar Properties** | Required: reversible profile settings, actual XFCE values and confirmation | RiceBowl applets; no replacement window manager |
| **Explorer / My Computer / Trash** | Required: genuine file management, mounts, virtual locations and views | RiceExplorer structural Win98 theme; keep Thunar fallback |
| **Help / About Windows 98-style rice** | Required: contextual local help and accurate Linux/RiceBowl identification | Small original offline HTML/GTK help browser |
| **Notepad / WordPad-like editor** | Strongly desirable: classic one-document editor UI with save/open/encoding/error protection | First test Mousepad/GTK embedding; write `riceNotepad` **only if** external editor cannot be skinned to the needed anatomy |
| **Paint-like editor** | Optional for highly complete nostalgia: bitmap drawing, palette, save/crop/undo | Existing native Linux app preferred; independent `ricePaint` only if full functional demand justifies maintenance |
| **Calculator / Character Map** | Working historical Accessories launch and period-styled UI where practical | Installed calculator/charmap or narrow first-party facade; no second math engine |
| **MS-DOS Prompt analogue** | Explicitly labeled **Linux Terminal** with classic shell visual; optional DOSBox integration if the user separately wants DOS apps | Existing terminal; never pretend native DOS compatibility |
| **Media Player / CD Player / Sound Recorder** | Optional authentic windows over supported Linux media backends and devices | Existing media apps first; dedicated sideprojects only after core fidelity gates |
| **Minesweeper / Solitaire** | Optional era accessories with independent, licensed/original artwork and input | Small separate game components, not rice-shell blockers |
| **Scandisk / Defrag / Registry Editor** | Do not fake Windows maintenance/registry. Offer correctly named Linux disk-health/filesystem tools with permission checks and explicit warnings | System tools and help docs, not a custom registry/defrag subsystem |

**Prioritization rule:** new programs are justified where **behavior or screen structure** cannot be provided by an existing maintained Linux component. Reuse the system backend; build replaceable frontends and original assets. No fake app shells with inert content.

### Milestone 8 — Windows 98-only integration, optional session theatre (P2)

- [ ] Optional startup/lock/logoff/shutdown visual theme using supported LightDM/XFCE hooks only; opt-in, backup before write, recoverable after display-manager failure and unaffected when switching to another rice. Never silently replace LightDM or take over security-sensitive authentication.
- [ ] Original or safely licensed startup/shutdown/notification sounds; output profile respecting mute, accessibility and reduced-motion/quiet settings.
- [ ] Classic-style short progress/transfer feedback, hourglass cursor and restrained animation with no expensive always-on renderer; respect reduced-motion and low-power mode.
- [ ] Windows-style desktop properties, Taskbar Properties and Folder Options as persistent, per-rice settings; applet changes survive session restarts but restore user XFCE state when leaving the rice.
- [ ] Optional historical screensaver themes and desktop patterns, with safe fallback on Wayland (outside current support) and multiple monitor sizes.
- [ ] Explicit *not in scope* for this Linux rice: Internet Explorer/ActiveX, original Windows 98 system files/registry, Win9x driver model, running Windows programs without Wine, actual FAT drive-letter semantics, proprietary Microsoft media assets and a DOS kernel. Wine/DOSBox may be separate launch integrations with truthful labeling if desired.

### Milestone 9 — Performance, safety, QA and release (P0 gate for 1.0 claim)

- [ ] Cross-rice regression: Win98 → XP → Win7 → Windows10 → ChromeOS → Frutiger → macOS → Win98, including Plank/XFCE panel ownership, autostart, hotkeys, GTK theme, file-manager selection, icon/cursor theme, notification host, wallpaper and rollback. Verify no stale processes, duplicate taskbars or missing tray icons.
- [ ] Real-hardware matrix: 800×600, 1024×768, 1600×900, 125/150/200% scale, two monitors, disconnected HDMI, keyboard-only, mouse, touchscreen if available; no offscreen menus, out-of-frame tooltips or unreachable confirm buttons.
- [ ] Thin-client/old hardware matrix: user's i7-7600U ThinkPad/16GB and an older 4GB Linux box; measure cold/warm startup, per-process PSS and idle wakeups, CPU from 20-minute idle, UI frame responsiveness, app lists of 500+ items, 1000+ desktop shortcuts and 100k-entry explorer folders. Define budgets **from the measured baseline**, then prevent regressions; no fabricated performance numbers.
- [ ] Validate X11 focus/struts, WM_CLASS, taskbar stacking, hotplug, suspend/resume, missing `nmcli`/`pavucontrol`/`upower`/UDisks, unauthorized Polkit actions, NetworkManager disconnect, USB removal and corrupted XDG config.
- [ ] Live e2e exercise for every enabled Start, tray, taskbar, desktop and Control Panel action including second/third-level menus and close/reopen cycles. Unit tests, GTK CSS parser tests, Xvfb interactions and actual screenshots from the exact tested commit; capture relevant states, not only open menu screenshots.
- [ ] File safety: temporary dirs/USB test images only; collision, missing permissions, interrupted transfers, Trash restore, permanent-delete confirmation, read-only mounts, symbolic links and external-process file changes. No test against home directories that can modify real personal files.
- [ ] Accessibility: logical labels, readable contrast, keyboard navigation, screen reader exposure of menus, focus return and no traps, alternative to hover-only flyouts, zoom/reflow at 800×600, disabled-reason tooltips and high-contrast option. Historical pixel density must not make controls unusable.
- [ ] Installation and rollback: dry-run → apply → logout/login → update → apply another rice → restore → uninstall on Mint XFCE; preserve user-customized themes, icons, desktop launchers and file associations. Failure injection verifies cleanup without deleting user data.
- [ ] Docs/release: this roadmap checkboxes reflect only tested merges, README links to this document and displays **current** tested 98 Start/Control Panel/Explorer/tray states, changelog records implemented changes, correct credits/license sources, install/restore commands verified. Release notes identify limitations and any physical sign-off still outstanding.

**Definition of done:** An observer recognizes Windows 98 SE before clicking, and after repeatedly using Start, taskbar, tray, desktop, Explorer, Control Panel, dialogs and accessories they continue encountering period-correct working interfaces. All enabled actions use real Linux services, all failure states explain themselves, files remain safe, and leaving the rice restores the original XFCE session. A single screenshot or passing CSS string test is **not** completion.

### Implementation order, dependencies and delivery size

| Order | Milestone | Priority | Relative size | External dependency | Proof to merge |
| --- | --- | --- | --- | --- | --- |
| 0 | Reference/harness and regression baseline | P0 | M | None | Baseline captures and repeatable tests |
| 1 | Start + real Run/Find/Help | P0 | L | RiceExplorer search for full Find | Complete nested flows |
| 2 | Taskbar, tray and classic popovers | P0 | XL | NM/UPower/audio services | ThinkPad hardware acceptance |
| 3 | Desktop special icons/context | P0/P1 | XL | XFDesktop or `riceDesktop` | Drag, rename, Trash, persistence |
| 4 | True Control Panel and applets | P0/P1 | XL | System settings adapters | Real settings + rollback |
| 5 | RiceExplorer Win98 interface | P0 dependency | XXL | RiceExplorer 0.3/0.4/0.6/0.9 gates | Data safety + distinct shell |
| 6 | Common dialogs and assets | P1 | L | Modules 1–5 | 2nd/3rd-click screenshots |
| 7 | Accessories | P1/P2 | M–XL | Installed apps first | Actual workflows, not facades |
| 8 | Session visuals/sound | P2 | M | Supported LightDM/XFCE hooks | Opt-in and recovery tested |
| 9 | Real hardware, polish, release | P0 gate | L | All above | Signed-off acceptance matrix |

**Dependency ownership:** RiceBowl owns session, shell, Control Panel and integration; RiceExplorer owns file management, search and virtual filesystem views; an optional `riceDesktop` owns desktop-icon behavior only if XFDesktop truly cannot supply it. Shared widget/backend utilities stay inside their owning projects until real duplication requires a library. Do not create another repository for each dialog or setting.

### Historical/technical references

- Microsoft [The Taskbar](https://learn.microsoft.com/en-us/windows/win32/shell/taskbar): historical Start, Quick Launch and notification-area structure.
- Microsoft documentation [Customizing a Folder's Web View](https://learn.microsoft.com/en-us/windows/win32/lwef/web-view): classic Explorer tree/list and Windows 98-era folder Web View concepts.
- Archived Microsoft KB [Windows Desktop Update](https://ftp.zx.net.nz/pub/archive/ftp.microsoft.com/MISC/KB/en-us/165/695.HTM): Active Desktop, Explorer Web View and Web-integrated shell behaviors.
- Microsoft [Shell32 versions](https://learn.microsoft.com/en-us/windows/win32/shell/versions): Windows 98 vs Windows 2000 shell differences, another reason not to treat them as one rice.
- [GUIdebook Windows 98](https://guidebookgallery.org/guis/windows/win98/): visual observation only; no asset extraction.
- RiceExplorer [functional roadmap](https://github.com/CopyPasteUser/riceExplorer/blob/main/ROADMAP.md), [UX contract](https://github.com/CopyPasteUser/riceExplorer/blob/main/UX-CONTRACT.md) and [design system](https://github.com/CopyPasteUser/riceExplorer/blob/main/DESIGN.md): canonical dependencies and shared file-safety contracts.
