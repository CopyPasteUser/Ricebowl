# RiceBowl visual and interaction contract

RiceBowl is an XFCE/X11 desktop-style studio. The GTK3 manager is intentionally
modern and compact; the *applied desktop shells* follow the visual language of
their selected era. The app is not a pixel-accurate OS emulator, and all art is
original Linux artwork. Windows 11 and Liquid Glass are out of scope.

## Hub UI (GTK3)

The manager is a compact desktop-style selector: choose a rice, inspect its
current capture, then check and apply it with a restore point. Seven installable
styles share one searchable list. Recovery, macOS tools and performance are
secondary pages; prototypes and the release roadmap do not crowd the selector.

- Runtime visual tokens: `macrice/hub.py` (`TOKENS`). Dark navy surfaces,
  light text, distinct blue selection and explicit keyboard focus states.
- Catalog copy and variants: `macrice/hub_catalog.py`.
- Rice logos and preview manifest: `macrice/hub_art.py`.
- Preview images: `assets/hub-previews/`, derived from actual X11 captures in
  `screenshots/current/` by `bash scripts/refresh_hub_previews.sh`.
  JPEG keeps the installed GTK app independent of WebP decoder availability.
- The macOS selection currently previews its wallpaper rather than a full
  desktop capture; the hub labels that distinction explicitly.

## Rice Creator workspace (GTK3, experimental 0.9)

The Creator is a compact desktop authoring instrument, not a themed desktop
simulation. Its one memorable surface is the **central real-shell capture**:
the preview is deliberately labeled as a static, isolated native RicePlate
render, with geometry controls and visible loading/unavailable states. The
separate **Edit layout** surface is explicitly a schematic coordinate editor,
not a fake live preview: it shows bounded desktop layers in real logical-pixel
positions, the reserved window rectangle in percent, and an orientation-only
panel. Its selectable outline is a functional drag/keyboard target, not
ornament. Layer selection, the focused canvas and the native GTK inspector
form a single editing state; arrows nudge eight pixels (Shift: one pixel),
and every committed move is checked by the Runtime recipe parser. Output
geometry selection preserves aspect ratio. The layer list uses navy surfaces
and high-contrast labels with a visible selected row rather than the system's
default light list background. A fresh native screenshot must be explicitly
rendered after changes; stale real pixels are never presented as live updates.
The left rail contains four real starting templates and saved draft versions; the
right scrollable inspector groups actual schema-v11 properties and structurally
editable panel lanes. Actions form a clear reversible sequence: create → edit
→ save a new private version → render → optionally export. The latest and
previous versions remain distinct. A separate **Install / switch…** popover
offers the guarded path from an immutable saved version to an installed recipe,
plus a one-click non-destructive fork under a new rice ID when a prior version
is installed,
then an explicitly confirmed live apply/restore only in an opt-in RiceBowl
Wayland session. Save and preview never activate a rice. The status view and
confirmation name the reviewed recipe SHA, current selection, persistence and
restoration; each live operation uses the existing supervisor's compare-and-swap
and compensated rollback. These experimental controls still require physical
hardware acceptance before any stable-release claim.

The Wallpaper library is a native GTK expander in the same scrollable inspector:
one image selector with included/private labels, a genuine thumbnail and
read-only declaration summary, followed by a restrained form for PNG import,
license/origin and attribution. Errors remain visible in the existing status
surface. GTK's file picker owns path selection, and scroll-wheel events cannot
silently change the selected wallpaper while scrolling the inspector. Imported
images are never confused with a live capture: they are authored assets and
only become part of an immutable draft after explicit Save version.

The v0.4 **Component library** keeps stable declarative identifiers visible
alongside real status/action binding selectors. Create, update and remove share
the same offline recipe validator; the editor visibly names in-use references
and does not offer deletion of a component still used by any layout or desktop
widget. The panel inspector now expresses the *actual bounded tree*: wide and
compact layouts are separate deliberate modes, child groups remain nested,
and each row has keyboard-accessible move, group/ungroup, edit and insertion
actions. Native GTK controls handle focus and popup behavior. The existing
workspace Save version is the single commit action: typing or organizing a
draft never mutates a current session or rewrites another saved revision.

The v0.5 **Visual asset library** adds native GTK selectors for a private
TrueType face and three action-specific 48×48 RGBA shortcut icons. Explicit
file-pickers require named owner-controlled assets and visible attribution.
SHA-256 identities are immutable; the native renderer checks owner, mode and
digest before loading the image/font. Older schema-v10 drafts have a separate
immutable v11 upgrade. Icons fit the existing hit areas; a bounded glyph cache
renders custom text in native styled panel, launcher, menu, desktop-icon and
widget labels, plus the calendar popup and volume OSD when explicitly opted in.
The latter two preserve the original 8px bitmap painter for built-in-font
recipes; importing a font must never silently restyle existing auxiliary
surfaces. A user-selected TrueType face retains a bounded font object for
on-demand Greek/Cyrillic/other Unicode masks, with a 512-glyph FIFO budget
beyond the prewarmed Latin set. Unsupported glyphs keep a visible fallback;
this per-codepoint monospace treatment is not complex-script shaping or an
installed system font. The built-in font remains the default and requires no
extra resident font allocation. Waybar still uses its standard fonts/icons.
RicePack v4 carries selected images, fonts and provenance without code,
scripts or active-session changes.

The opt-in Wayland font picker uses the installed GTK FontChooser's native
family/style preview and a read-only Fontconfig inventory. Fontconfig is the
discovery source; the validated private TrueType digest is the runtime token
owner. Choosing a face does not install fonts or change GTK/Qt application
defaults. After the user supplies name and redistribution provenance, Creator
copies the selected file into its content-addressed asset store; Save version
and a subsequent real-shell render remain separate review actions. Native
RicePlate prewarms common Latin glyphs and rasterizes extra Unicode codepoints
on demand into a bounded fixed-cell cache. This intentionally preserves
current geometry and memory limits; complex-script shaping and full font
metrics are not yet supported.

The v0.6 **Reference / visual QA** strip belongs to the real capture surface,
not the schematic composition editor. A selected local PNG is checked and
copied by digest to an owner-private, per-draft reference library. The selected
reference survives immutable revisions but never becomes a recipe asset or
RicePack attachment. Only a fresh native render at the *identical* logical
size can be compared: the view selector explicitly distinguishes the actual
capture, original reference, side-by-side 50/50 wipe, 50% blend overlay and
red tolerance-aware heatmap. The existing offline comparison engine owns
pixel metrics and region checks; UI labels never call these fidelity scores.
Pixel cutoff and the 0–2 px tolerance are explicit, keyboard-accessible
controls. Any changed recipe, geometry or policy invalidates old comparison
results. Blocking pixel work runs off the GTK main loop. Damaged or missing
reference files leave the editor available with a direct explanation.

The v0.7 **Reference mapping** disclosure sits directly below visual QA to
preserve the screenshot as the focal point. Three secondary actions — offline
analysis, import JSON, and export hints — precede a short, scrollable list of
suggested bounded changes with source evidence and confidence explicitly
labeled as qualitative *heuristic strength* (or *unverified external*), not as visual/functional
accuracy. Low-confidence offline colors and **all external proposals** start
unchecked. The single primary **Use checked hints in unsaved draft**
action is disabled until at least one row is selected and cannot replace Save
version. The normal GTK property inspector refreshes after transferring hints,
letting users adjust the actual validated controls; there is no hidden apply.
Stale screenshot, revision, edit and import states invalidate the suggestion
list, and the local PNG is never included in a JSON hints export. Rows remain
native keyboard-focusable GTK controls and live in a capped scrolling region
on smaller laptop screens. Imported files are never treated as in-process
offline analysis regardless of claimed JSON origin; their proposals remain
unchecked, and the currently selected private reference is reverified before
any export or transfer.

The v0.8 **Region QA** disclosure adds a deliberately manual layer to visual
assessment. A small coordinate form labels at most eight source-pixel rectangles
as panel, menu, desktop or unknown. Each numbered rectangle appears as a clear,
colored outline on a *copy* of the private reference in the existing real-image
viewer. Type and exact coordinates remain readable in the list, and native GTK
Remove buttons provide a non-pointer alternative. The separate **Measure
regions** action runs off the GTK thread against a matching native render,
showing independent raw/tolerant pixel-change percentages and RGB error for
each marked region, with no invented visual or functional quality score. The
report may be explicitly exported as new, owner-private, digest-pinned JSON
without image bytes. Editing geometry, changing pixel policy or replacing a
capture clears stale measurements; switching drafts or reference clears the
temporary rectangles. A detected 0.7 region may be copied only on explicit
**Use detected** action; it is geometry, not a recognized functional widget.

The v0.9 **interactive correction cycle** extends that disclosure without
expanding recipe permissions. A native GTK overlay in the fitted reference
viewer accepts a deliberate primary-button drag and draws a live, translucent
rubber band. It translates display coordinates into outward-rounded source
pixels with clamp and minimum-drag guards, then passes through the exact 0.8
rectangle validator. The original coordinate spin controls are kept for
keyboard-only and precise editing; Escape cancels a pending drag. Reference
annotations remain across *immutable revisions of the same draft* if the
private screenshot digest is unchanged, while current measurements expire.
The user can adjust an allowlisted inspector field, save the draft, render in
isolated labwc, and re-measure the same regions. An in-memory, 12-measurement
history records SHA-256-pinned results and percentage-point changes per region.
Reference, region or pixel-policy changes invalidate history; the private JSON
export includes the versioned cycle but never screenshot bytes. These deltas
are **pixel error changes**, not semantic recognition, automatic repair or
assertions of visual fidelity. The desktop remains untouched throughout.

The established `macrice/hub.py:TOKENS` palette is the **single runtime color
source** for Creator chrome; `macrice/creator_gui.py` uses those named tokens
in an additive GTK CSS adapter. The deliberately quiet navy preview surround
makes different authored rices legible without forcing them into the Creator's
own skin. Native GTK3 labels, buttons, combo boxes, spin buttons, color
selectors and keyboard focus preserve installed Linux accessibility and do
not require new fonts, remote images or frontend dependencies. Separate,
scrollable panes retain each control on laptop displays. This is tooling UI,
not a redesign of the seven existing rice themes or the RiceBowl Hub.

## Canonical owners

| Concern | Source of truth |
| --- | --- |
| Catalog names, variants and status | `macrice/hub_catalog.py` |
| User-visible full-rice presets | `macrice/rice.py` |
| Native shell lifecycle / keyboard / window list | `macrice/aero_shell.py` |
| Per-rice taskbar / launcher skin | `macrice/heritage_shell.py`, `macrice/chrome_shell.py` or `macrice/ten_shell.py` |
| Desktop GTK/XFWM/icons/wallpaper assets | `scripts/build_heritage_assets.py` and targeted `scripts/build_chrome_assets.py` → checked-in `assets/` |
| Exclusive active shell, Plank, MacBar and XFCE panel | `macrice/shell_session.py` |
| Optional read-only desktop preview, per-rice icon preferences and inventory | `macrice/riceware/plate.py`, `macrice/riceware/plate_preview.py` |
| Recoverable Super_L and Control_R shortcuts | `macrice/session_shortcuts.py` |
| Backups and partial restore | `macrice/rice.py`, schema 5 |

## Desktop identity

- **Aurora / macOS:** restrained dark/light WhiteSur, native MacBar and user-managed Plank.
- **Windows 7:** icon-only Aero penguin Start orb, 48px glass Superbar,
  smoky slate-blue (not cyan-water) taskbar with active/hover glass backplates,
  two-column ivory-program/steel-blue-places Start,
  working All Programs and search, amber session-dialog shutdown, original blue
  XFWM4 frame/button sprites and Explorer-like Thunar controls. The Aero file
  manager has its own light Windows 7 Explorer styling in
  `macrice/thunar.py:AERO_EXPLORER_CSS`: native flat toolbar buttons, a unified
  breadcrumb, unboxed shortcut navigation, white canvas and pale status strip.
  The applied profile manages Thunar's real `/last-menubar-visible` Boolean:
  hidden in Seven, restored visible on the other rices, journaled for rollback.
  Original golden folder, drive, network and MIME-type icons live in the Aero
  icon theme's scalable places/mimetypes directories; they never alter the
  other themes. True Libraries, native details pane and contextual Explorer
  commands are beyond CSS-only Thunar theming and are not simulated. The live Win7
  shell owns `win7-*` CSS classes and `_create_win7_menu()` in `aero_shell.py`;
  `macrice/aero_superbar.py` groups immutable Wnck snapshots by WM_CLASS,
  supplies active-aware group overflow, and feeds GTK window previews and Jump
  Lists. Inactive groups with a genuine Wnck `needs_attention()` signal receive
  an amber Aero highlight, not an artificial timer. Running-window context
  menus offer left/right half-tiling, maximize and restore of the previous
  window geometry; the native Wnck actions use the actual display workarea and
  leave XFWM4 shortcuts untouched. The blank taskbar's classic Arrange commands
  cascade, stack or place genuine visible windows side by side on the active
  monitor, with reversible snapshots and an optional installed Task Manager.
  Aero pins have same-application drag/drop movement with exact left/right drop
  halves, plus keyboard-accessible context actions; their existing atomic
  Aero-only preference file is the single authority for persistent order.
  Edge-drag, global Win+Arrow and Shake remain
  open. A 450ms Show Desktop hover provides reversible Peek; it is not full
  compositor transparency. `scripts/build_aero_assets.py` owns generated art;
  curated generic-folder SVG is maintained directly in `assets/icons/RiceHub-Aero/`.
  Both wallpapers now use a **2009 Aero cobalt/navy glow** with an original glass
  Linux penguin, not green valleys or watery transparency (those belong to
  Frutiger Aero). Stable profile keys `aero-meadow` / `aero-cascade` remain for
  backup compatibility; their visible names are **Aero Seven Blue / Night**.
  Runtime colors are owned by the `win7-*` CSS in `aero_shell.py` and mirrored
  here as design intent. `macrice/win7_control_panel.py` owns a separate real
  decorated 810×565 Control Panel window using the eight historical Windows 7
  categories, Category/Large/Small views, Back/Forward navigation, nested task
  detail pages and search. Only installed XFCE/Linux tools can launch; missing
  actions are disabled with explanatory tooltips. Real device status and volume controls
  remain in a clearly named expandable Linux hardware region, never a fake
  Windows toggle. Its eight 64×64 original SVG category icons live exclusively
  in the Aero theme's `scalable/apps/ricehub-cp-*.svg` assets, avoiding accidental
  changes to other rices or missing system-theme glyphs. The Control Panel is
  opened from Start or `Control_R`; no
  anachronistic Control Panel gear occupies the right notification area.
  `macrice/win7_tray.py` owns five independent Aero status flyout layouts
  (sound/output, Wi-Fi, power/backlight, Bluetooth, calendar) with silver-blue
  headers and white bodies, including the Win7-style upright speaker slider.
  Its inherited backend transactions live in `luna_tray.py`: reusing hardware
  code does not mean reusing XP's flyout skin. The Win7-specific CSS in
  `aero_shell.py` is canonical for these visual states; this DESIGN entry
  mirrors their purpose rather than introducing duplicate runtime tokens.
  The optional SNI application icons use a small Aero chevron for overflow:
  three directly visible active icons, `NeedsAttention` prioritized, `Passive`
  hidden, and an accessible native menu for actual activation. An original Aero
  settings dialog can set an explicit visible icon count (0–8) and individual
  Automatic/Show/Hide behavior for stable StatusNotifier IDs. Its preferences
  live in the narrowly scoped `ricehub/win7-tray.json`, not XFCE settings.
  This is not a
  Windows 10 Action Center or synthetic status feed. XFDesktop owns the
  desktop icons; Windows 7's original Computer/Documents/Network/Recycle Bin
  links are opt-in and removable only when unmodified. The shell must not take
  over the desktop, overwrite personal launchers or silently replace Thunar.
  An installed Rust RiceExplorer can be launched from Start in explicit
  `--theme win7` preview mode, leaving Thunar and system MIME defaults alone
  until file recovery and mount support pass acceptance. The 48px bar carries
  larger pinned and running-app icons; Wnck supplies original
  large icons where available. XP, Classic, Frutiger and Ten stay untouched.
- **Windows 10:** native 22H2-era flat charcoal (#101014) 40px taskbar,
  compact four-pane/penguin Start mark, optional taskbar search box/icon/hidden
  opening the functional Start search field (not two simultaneous search boxes), icon-first
  running-app buttons with active bottom underline, real network/audio/battery
  status and a two-line clock. The ten-shell GTK CSS in macrice/ten_shell.py
  owns the runtime #0078d7 accent and rectangular hover/focus treatments.
  aero_shell._create_ten_menu() owns a three-zone nav rail / alphabetical Gio
  application list / genuine-app pinned tile groups (saved pins/context menus).
  `ten_tiles.py` owns a separately persisted schema-validated four-column
  Start mosaic: square 68×68 base cells, 5px gutters, Small 1×1, Medium 2×2,
  Wide 4×2, Large 4×4; drag/drop order, group names and absent-app retention
  never alter taskbar pins. A 331px independent scroll lane holds the groups.
  The dark 362px Action Center is built by macrice/ten_action_center.py: a
  truthful RiceBowl notifications area, real Linux settings launchers and
  shared verified output volume, mute, network and battery readers, not fake
  connectivity switches. scripts/build_ten_assets.py owns the original deep
  cobalt four-pane beam/penguin wallpapers, crisp flat dark/light GTK3/Thunar
  controls and sharp 31px XFWM4 buttons. Exact historical original hashes in
  assets/trusted-ricebowl-ten-before-fidelity.json allow safe backup-backed
  upgrades while preserving custom theme edits. No blur, Win7 glass, XP gloss
  or Windows 11 centered widgets belong in Ten.
  The native Settings window uses an independent dark #202020 Win10 canvas,
  white category text, #0078d7 selected-navigation rail, 3-column icon-first
  Home and compact square rows. Sidebar navigation is for inner pages, not
  a permanently visible Windows 11-style home. Two search fields share one
  real destination index; native GTK switches and inline verification text
  always reflect Linux-backed action state. `ten_settings.py` owns the widget
  hierarchy and search behavior; `.ten-settings-*` rules in `ten_shell.CSS`
  remain the sole runtime visual owner. No shared hub, XP or Aero tokens change.
  Start has a native A–Z picker for real Gio apps; the taskbar's context-menu
  Search mode/Task View visibility is saved atomically in a Windows-10-only file.
  Wide desktops display the characteristic square light search field; narrow
  desktops fall back to a search icon. Legacy boolean preferences migrate
  to schema 2 without touching XFCE global panel settings. Taskbar pins also
  support native intra-panel drag/drop and real-app recent-file Jump Lists.
  `ten_tray.py` owns four Win10-flat flyout surfaces over the already verified
  on-demand audio/BlueZ/power/date Linux adapters; NetworkManager retains its
  separate Win10 WLAN flyout. `ten_task_view.py` renders real Wnck windows in
  two-column cards with desktop switching, safe window close and move; no
  synthetic thumbnails are fabricated. Native Settings now includes truthful
  Storage, Power & sleep and an installed Gio-app browser. Start search also
  finds native Settings destinations and actual user-folder shortcuts; it is
  not represented as an index of every file on disk.
  Action Center groups the XFCE notification log by app with real timestamps
  and icons, confirms permanent history clearing and can collapse the optional
  second row of Linux shortcuts. The look stays square and charcoal/cobalt.
- **XP Luna:** 40px cobalt/green molded taskbar, contiguous bright-cyan notification
  tray, user-account Start header, ivory programs and pastel-blue system-links
  columns, separate log-off/power affordances, and a warm meadow wallpaper.
  Live menu structure and geometry are in `macrice/aero_shell.py`; XP-only
  colors and states are in `heritage_shell.DETAIL_CSS["winxp"]` and
  `CONTROL_DETAIL_CSS["winxp"]`. User folders resolve through XDG directory
  settings; missing folders offer an explicit create/open confirmation.
  `scripts/build_heritage_assets.py --luna-only` also installs the checked-in
  Luna GTK fidelity control layer (focus rings, selection, check/radio, scale,
  scrollbar and tooltip states). The taskbar properties view mirrors the
  native 2001-style grouped options and provides a noninteractive preview that
  updates with each control; its Clear List action asks first and erases only
  XP-specific recent-program history. The Control Panel adds a real Back/Home/
  Search toolbar and breadcrumb above the original category/task layout.
  My Computer opens Gio's `computer:///` view when supported, falling back to
  the filesystem root on installations without the GVfs backend. Original
  recent-document artwork replaces the default OS-specific action glyph.
  `scripts/build_heritage_assets.py --luna-only` refreshes the original drawn
  XFWM4 titlebar/button states and layered GTK/Thunar controls without touching
  other reviewed themes. `macrice/luna_control_panel.py` is a centered XP category
  window with an actual Classic View switch, nine XP-era settings
  categories and a pale-blue sidebar with truthful network, battery and verified
  output-volume controls. `macrice/thunar.py:LUNA_EXPLORER_CSS` confines XP Explorer's
  warm beige toolbar, flatter path controls and blue tasks-pane treatment to
  Thunar; it cannot replace Thunar's actual shortcuts pane with Windows Explorer
  tasks. Missing Linux utilities remain visibly disabled. The window scrolls on
  compact monitors; XFCE taskbar/session recovery is unchanged.
  XP flyouts are themed on the native GTK popup windows via `menu.luna-popup`,
  not descendant selectors of the Start window. Ivory `#f9fbff`, cobalt
  selection `#316ac5` and compact 25px rows carry through nested program,
  recent-document and pin menus; flyouts retain focus during traversal.
  Control Panel is navigable *category → task → installed Linux utility*;
  Classic View lists individual applets, while search covers tasks and their
  descriptions. Reopening returns to its home view, and unavailable leaf tools
  show an explicit reason. `heritage_shell.py` remains the runtime palette owner;
  the values here document the historical identity, not a parallel token source.
  The original category and task icons are generated by
  `scripts/build_luna_control_icons.py` into the Luna theme only: nine modeled
  XP-era control devices and individual task badges, never blue generic squares
  or copied Microsoft bitmaps. The notification area owns five small anchored
  `luna_tray.LunaTray` flyout windows (audio, WLAN, power, Bluetooth, clock),
  each independently positioned above its dock icon and styled in ivory/cobalt:
  verified output volume/mute/device selection, NetworkManager radio and
  nearby connection/disconnection actions, battery/backlight and optional
  power profiles, a BlueZ adapter/device popover and an interactive calendar.
  Network, audio, Bluetooth and brightness writes are asynchronous, report
  failures and verify read-back;
  unsupported Linux hardware and tools are explicitly unavailable. These
  flyouts never replace the full Control Panel or change other rice themes.
  XP also persists its Start-only favorites independently of taskbar pins;
  right-click offers pin/unpin/reorder, while the lower program list sorts by
  actual successful launches (bounded user-local history, never telemetry).
  RiceBowl-owned Luna dialogs use `luna_dialog.attach_luna_dialog_chrome` for a
  single draggable cobalt caption and original red close button, with modal
  GTK responses unchanged. Taskbar Properties, Run, notification-icon settings,
  Help Center and System Properties share that title treatment; Help remains
  resizable. XFWM4 still moves/manages every window and non-Luna dialogs are
  unaffected. This does not claim GTK3 can repaint arbitrary Qt/Electron apps.
- **98 / 2000:** visually faithful 1998 desktop: solid `#008080` wallpaper,
  compact 34px `#c0c0c0` taskbar, 19px original CRT/penguin Start badge,
  2px white/light-gray/dark recessed versus raised frames, `#000080` focused
  menu and active XFWM title, and 27px high hard-edged window title chrome.
  `aero_shell._create_classic_menu()` alone owns the dense 262px vertical
  `RiceBowl 98` side rail plus true GTK cascading Programs, Favorites,
  Documents and Settings; Find, Run, Help and Shutdown launch only real
  installed Linux services or are disabled. `heritage_shell.DETAIL_CSS[
  "winclassic"]` owns the live taskbar/menu states, including keyboard focus;
  `scripts/build_heritage_assets.py --classic-only` owns the original GTK,
  XFWM, pixel app icons and teal wallpaper, with carefully preserved existing
  curated folder artwork. `assets/trusted-ricebowl-classic-before-fidelity.json`
  enables safe, backup-backed upgrades of byte-identical older managed assets.
  The palette must never use gloss, water, transparency or XP-rounded controls.
  Its Control Panel uses an inset three-column icon view with centered labels
  and a vintage caption, rather than Luna's category navigation list.
- **ChromeOS / Material You:** independent pastel-indigo `#e7e9f8` and iris
  `#4b66d7` identity with an original flowing wallpaper, 56px shelf,
  consistent app circles, window activity underline and accessible status pill.
  `aero_shell._create_chrome_launcher()` renders a 610px left-anchored rounded
  app launcher: real Gio apps, four saved/favorite pinned shortcuts, bounded
  multirow grid, filter, keyboard focus, load-more and actual pin contexts.
  `macrice/chrome_quick_settings.py` renders a 396px bottom-right settings
  popup with date, verified Linux volume/mute, real network and battery status
  and installed XFCE/NetworkManager utility navigation. All switches reflect
  read-back-verified Linux state; XFCE still owns notification delivery. A
  separate Shelf bell reveals a log-backed notifications detail panel using
  `org.xfce.Notifyd.Log`: live unread badge, application groups, bounded
  history, read/dismiss controls, confirmation before Clear all and verified
  XFConf Do Not Disturb. Asynchronous D-Bus reads leave GTK responsive and
  the UI forgets notification content after closing. Missing providers show
  explicit empty/unavailable states; no second daemon or expired app actions.
  Settings
  links use navigation chevrons rather than fake connection switches.
  The latest milestone replaces direct utility launches with six navigable
  Quick Settings detail pages and a separate `chrome_settings.py` Settings
  window: seven categories, live search, detail navigation and contextual
  Linux utility links. Quick Settings includes *real* read-back-verified
  Wi-Fi, Bluetooth, backlight and power controls using shared asynchronous
  adapters, styled with `chrome-native-*` instead of Aqua World CSS.
  Unsupported devices show explicit unavailable states; no pretend Google
  identity, Android, Cast or privacy policy switches are displayed.
  The Shelf clock and date label in Quick Settings route to a shared embedded
  GTK monthly calendar page; system locale and current local date are the
  source of truth, and online events remain an explicitly absent integration.
  `macrice/chrome_shell.py` owns Chrome-only selectors and
  optional X11 rounded popup window shapes even without a compositor.
  `scripts/build_chrome_assets.py` generates this profile's original wallpaper,
  35px XFWM4 frames/buttons and light GTK3/Thunar styles. Rebuild with
  `python3 scripts/build_heritage_assets.py --chrome-only`; all-rice builds
  call the same generator last. The Chrome historical managed asset manifest
  allows safe upgrade of matching old installations, retaining user edits.
- **Frutiger Aero / Aqua World:** independent luminous turquoise/cyan and lime
  eco-futurist identity over original water/grass/blue-sky artwork. The live
  taskbar has a thick pearlescent top light, a recognizable aqua Start orb,
  rounded glass-like running-window capsules and a separate green-blue status
  cluster; it must never inherit Windows 7's slate-blue Superbar visual code.
  `macrice/frutiger_control_center.py` owns an independent Aqua Control Center
  with a nine-category overview, task pages, detail leaves, search and Back
  navigation. `heritage_shell.DETAIL_CSS["frutiger"]` extends the Pearl/Lagoon/
  Lime grammar to its nested surfaces. The original verified sound volume/mute
  backend and live network/battery readings remain intact. The launcher uses
  synchronized Apps/Places/Settings tabs, a visible Settings-to-Apps escape and
  a non-homogeneous scrollable settings page. The Aqua Control Center now embeds
  `frutiger_native_controls.py`: GTK switches for Wi-Fi and Bluetooth, sliders
  for real output/microphone volume and backlight, a true default-sink selector,
  Wi-Fi network actions, a battery meter and supported power-profile choices.
  Device writes run off the UI thread with backend read-back, explicit errors
  and a refresh action; Wi-Fi disable asks for confirmation. Launcher Settings,
  its gear and the network/audio/power tray controls open relevant Aqua views;
  installed allowlisted Linux utilities are available from their detail pages
  with explicit feedback when missing. `Your World` Places uses Gio's real
  mount monitor for hotplugged storage and network locations, plus XDG Trash.
  The native `Your World` search merges installed Gio apps, bounded XDG place
  names, Trash and indexed Control Center task metadata. Settings search results
  navigate directly to the matching native detail leaf, without filesystem
  traversal or network lookups on typing.
  `macrice/frutiger_device_details.py` provides bounded asynchronous read-only
  probes (NetworkManager Wi-Fi names/strengths, BlueZ adapter, audio sinks,
  XRandR displays, actual kernel/disk details). Stale views cannot overwrite
  a newer settings page. `macrice/frutiger_flyouts.py` owns small anchored
  network, sound and power bubbles with actual sound volume/mute controls and
  deep links into the native Aqua pages, reusing the shared status poller.
  Aqua tray bubbles use lazy, separate XFWM-managed utility windows to escape
  the shallow DOCK's clipping boundary; their original colors and shared
  Linux hardware backends remain unchanged.
  The installed third-party app's windows are *not* misleadingly represented
  as Aqua-native settings; advanced networking still uses real Linux tools.
  `_create_frutiger_menu()` renders a rounded `Your World` head with **real**
  Wi-Fi/Ethernet, audio and battery status; accessible search; four working
  system locations; and **Apps / Places / Settings** pages. The Apps view is an
  icon-first Gio app grid with working search, launch, Show more and pin menus;
  unavailable Linux settings tools are disabled. Dedicated selectors live in
  `heritage_shell.DETAIL_CSS["frutiger"]` and are scoped with `frutiger-*` /
  `aqua-*`. `scripts/build_heritage_assets.py --frutiger-only` regenerates
  original glossy XFWM4 button sprites and GTK3/Thunar widget styling without
  rebuilding other rices. Exact prior asset hashes in
  `assets/trusted-ricebowl-frutiger-before-aqua.json` allow backup-backed
  upgrades while protecting genuine user customization. This is native GTK
  refraction **suggestion**, not claimed GPU backdrop blur.
  The refined Aqua launcher puts real pinned/familiar Gio apps first, preserves
  full search and returns to Apps on reopening. Its locations resolve XDG
  folders and require explicit confirmation to create any that are missing.
  Frutiger alone uses `thunar.FRUTIGER_EXPLORER_CSS`, reducing the breadcrumb
  into a single pearl glass address surface, compacting real GTK toolbar
  actions and calming the file canvas and mint navigation pane. The native GTK
  asset generator mirrors this visual polish. The older unmodified Aqua GTK
  asset is upgradeable through an exact-hash manifest, without overwriting
  edited user themes. A future optional RiceExplorer could own the structural
  UI that GTK CSS cannot control; Thunar remains the stable default.

Desktop styles must remain recognizable without blur, desktop GPU effects or
third-party panels. Do not depend on non-existent proprietary OS resources.
`heritage_shell.CSS` is the live shell palette; the build script creates matching
GTK/XFWM assets. Change both together when a theme identity changes.

## Behavioral rules

Native labwc/RicePlate menu presentation belongs to the same validated
recipe as its action groups, not to a separate theme renderer. In schema v6,
`menu.presentation` defaults to `tabs` (horizontal 40px group strip) or may
be `sidebar` (112px vertical group rail with 44px rows and a separate action
column). The sidebar consumes the existing recipe background, foreground and
active colors; no new free-form styles or commands are accepted. Its group
buttons and content rows remain keyboard/pointer/AT-addressable; the Waybar
fallback preserves grouped labwc actions without promising layout parity.
Schema-v6 `menu.groups[].content` additionally supports one or two bounded
body sections (`actions`, `favorites`, `apps-list`, `apps-grid`) totaling at
most four visible items. Native RicePlate uses a shared geometry model for
rendering and pointer hits, with two-column initial-letter app tiles in grid
mode. Sections inherit the same rice color tokens and preserve default menus
when absent; no recipe-supplied paths, executable code, or free-form styling
are accepted. The native compact composition is a structural primitive,
not an icon-accurate Windows XP/7 recreation. Future XP/7-specific structures
require separately audited primitives, not a CSS-only identity swap.

Schema-v12 `menu.presentation = "columns"` is now an opt-in, bounded native
two-column composition for `xp-luna-columns`; the original `xp-luna` recipe
and the legacy sidebar/tabs behavior remain unchanged. The narrow blue
system shelf shows concise, unambiguous names (`Settings`, `Log out`, or
`Log out (N/A)` when a real logout session is unavailable), while search,
action dispatch and AT-SPI keep the complete original action descriptions.
The shared menu state and tile geometry remain the source of truth for pointer,
keyboard, paint and screen-reader behavior; visible text is never an executable
command or a replacement for its canonical action identifier.

The same **validated schema-v12 two-column palette** can opt into
labwc-owned server-side window frames. `macrice/de/window_chrome.py` maps only
existing colors to a bounded `themerc-override` in the private labwc session;
no template-controlled paths or compositor commands are accepted. The active
frame uses the recipe's header/panel blues, the inactive frame uses its softer
menu colors. No override exists for tabs/sidebar recipes. Live switching
transactionally changes the private root menu and frame override and restores
both on failure. GTK/Qt client-side titlebars remain with their applications;
the preview is neither a global theme nor a claim of XP pixel fidelity.

Schema-v6 nested panel layouts may also contain a **real, focusable action
button** (`type: action`, `id`, `label`). Only four fixed IDs are supported:
`applications`, `terminal`, `settings` and `lock`. Labels are bounded safe ASCII
(1–16 characters), ID repetition within a layout is rejected and wide/compact
variants of the same ID retain the same label. Native and Waybar renderers
consume these same validated leaves and map IDs to existing, fixed Linux
actions. Native panel painting, pointer hits, Tab/arrow focus, Enter/Space and
AT-SPI activation must resolve through the one shared action dispatcher.
No arbitrary recipe-supplied command, path, keybinding or dynamic argument is
ever interpreted. Schema-v7 adds `type: control` with the fixed IDs
`wifi-toggle`, `audio-mute`, `audio-up` and `audio-down`. These share native
RicePlate's bounded NetworkManager/WirePlumber worker and its existing menu
dispatcher. Each painted button has a live, hardware-derived second line
(`On`/`Off`, `Muted`, volume percentage or `N/A`), a visible pending/failed
state (including a `Busy` sibling state) and an AT-SPI name including the current state. Controls with no provider
or while another write is pending expose no AT-SPI activation and ignore
clicks; no recipe can command arbitrary hardware. Geometry and focus remain
stable during status changes. The Waybar fallback shows a visibly disabled
`N/A` control without a click command because it lacks that verified worker.
These are shared framework controls, never OS-specific costume toggles.

Schema-v9 component references also support **native desktop action widgets**
when the declared component has `role: action`. Reuse the exact same fixed
action/verified control dispatcher as panel buttons; only the explicit
200×96 action surface accepts pointer clicks and on-demand keyboard focus.
Within the current output, Tab/Shift-Tab cycles action widgets and Enter/Space
activates the selected one; AT-SPI exposes a button only when enabled.
Visible normal/focus/hover/disabled and pending/failure states inherit the
rice's existing active/focus/hover/disabled tokens. Status and text desktop
widgets remain noninteractive and input-transparent. Do not infer a generic
execute-script capability or enable Waybar actions where that backend has no
desktop layer.

**Prioritization:** the reusable Wayland shell/Creator contracts and safe
switching remain ahead of pixel-perfect historical XP/7/10 menu, titlebar and
icon fidelity. The latter are separate post-framework acceptance work; existing
XFCE rices and recognizable opt-in native themes are preserved meantime.

- `Super_L` toggles the active rice's menu; `Control_R` toggles its quick settings.
- Every shell performs actual Gio app discovery/launch and event-driven Wnck
  task switching. Menu and settings are independent toggles with Escape support.
- Windows 98, XP Luna, Windows 7 and Windows 10 reserve blank-taskbar
  right-click menus for genuine desktop actions, including Task Manager.
  One shared installed-tool resolver prefers XFCE's system process monitor,
  then GNOME's. Missing tools disable the action rather than showing fake
  process data. Pinned apps and tray icons keep their own click handlers.
- Exactly one RiceBowl taskbar may be active. The manager must stop inactive bars,
  Plank and MacBar before starting the selected taskbar; XFCE's stock panel
  exits only after a successful replacement handoff.
- A preview remains read-only sample data, even when its rice is installable.
- ricePlate's optional canvas may preview **real** current-user desktop icons,
  but it must remain a normal window until a separately reviewed ownership
  handoff exists. Its icon size, alignment and visibility preferences are
  per-rice, never written through XFConf; `xfdesktop` stays authoritative.
- Applying a rice journals a backup *before* writing XFCE preferences.
  Restoration preserves subsequent user edits and never overwrites custom art.
- Desktop workarea and search/menu geometry adapt to the current monitor.
- GTK3 semantic button widgets, explicit accessible names, visible focus, and
  keyboard search are core features; color alone must not indicate activity.

## Release acceptance

Headless tests, native GTK/Xvfb shell smoke, window-close crash regression,
fresh install, login reconcile, rapid multi-rice switching and real Mint XFCE
hardware tests must pass before declaring a fully stable release. Screenshots
must be real X11 captures or explicitly labeled illustrations.

The gallery also needs genuine Thunar processes for all six non-macOS rices,
with their own GTK, icon and XFWM4 themes under a real X11 window manager.
Disposable `*-workspace-*` captures are not image-composited file managers.
macOS still needs an equivalent current live MacBar/Plank capture. Neither
CI alone nor mockups replace the owner's real Mint/Plank sign-off.
