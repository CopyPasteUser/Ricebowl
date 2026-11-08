# RiceBowl changelog

## Unreleased — RiceSpice secure enrollment and native RicePlate AT-SPI (8 November 2026)

- Add a native PEAP/TTLS Enterprise Wi-Fi profile form. It requires a named
  RADIUS-server domain plus system or selected CA trust, disables autoconnect
  and password persistence, verifies the saved UUID, and accepts one-time
  802.1X credentials through NetworkManager's stdin-backed `passwd-file`
  interface only after checking the profile's security policy. No secret
  enters command arguments, configuration or diagnostic output.
- Add a local OpenVPN/WireGuard import chooser that hands the selected
  `.ovpn`/`.conf` file to NetworkManager and disables autoconnect. Unsupported
  EAP-TLS/client-certificate and provider-specific VPN authoring still uses
  NetworkManager's installed editor.
- Add opt-in AccessKit/AT-SPI integration to RicePlate's native Rust layer-shell
  UI. Visible panels, tasks, launcher, status, tray/DBusMenu, desktop shortcuts,
  grouped menu, calendar and notifications appear in a named accessible tree
  with real keyboard focus. AT actions return to the Wayland event loop and
  reuse already validated commands; private notifications disappear from the
  tree when closed. No new resident process when accessibility is disabled.
- Cover secure enterprise enrollment failures/secret boundaries and native
  accessibility model/action safety with regression tests. Orca/device QA on
  actual Wayland hardware remains the release gate.

## Unreleased — Advanced RiceSpice controls (8 November 2026)

- Show actual active PulseAudio/PipeWire playback streams. Explicit verified
  per-app output routing, bounded 0–150% volume and mute controls fail closed
  if a stream disappears or changes between review and action.
- List saved NetworkManager Ethernet, Wi-Fi and VPN profiles by real UUID,
  activate/deactivate only reviewed identities with system-state readback and
  a connection-loss warning. New EAP credentials/certificates remain in the
  installed NetworkManager connection editor, never RiceBowl or process args.
- Add guarded `wlr-randr` monitor X/Y positioning to the 18-second rollback
  worker. Save/forget private, validated monitor layout presets and restore
  each output only through an explicit guarded trial. Do not auto-apply at
  login or disable outputs during a hotplug/dock change.
- Migrate old RiceSpice preference JSON safely to v2; add opt-in GTK high-
  contrast theme and supervised Orca screenreader startup only in full
  non-nested RiceBowl sessions. Cross-application AT-SPI semantics and live
  device/assistive-tech QA still require acceptance.
- Add a guarded manual local date/time editor through timedated. It refuses
  changes while automatic time is enabled, validates the complete timestamp,
  confirms the system-wide impact and checks actual local clock readback.
- Extend Python regressions for partial-service failures, profile parsing,
  stale state, stream actions, display positioning, private presets, legacy
  preferences and Orca supervision; preserve XFCE/X11 and no new resident daemon.

## Unreleased — Native RiceSpice display, input and accessibility controls (8 November 2026)

- Replace three formerly delegated RiceSpice pages with real on-demand editors:
  active wlroots outputs can select an advertised resolution/refresh and a bounded
  scale, with an independent 18-second confirm-or-rollback process. No monitors
  are enabled/disabled, no automatic arrangement changes or persistent output
  overrides are written.
- Add owner-private, validated/atomic next-login input preferences (labwc
  pointer speed, natural scroll, touchpad tap and keyboard repeat) and limited
  accessibility preferences (cursor size and GTK text scaling). Generate isolated
  compositor XML only for the opt-in RiceBowl session; preserve XFCE settings.
- Cover malformed/stale preferences, compositor XML, session cleanup, monitor
  parsing and rollback in Python regression tests. Real monitor, touchpad,
  cursor-theme and assistive-technology acceptance is still required.
- Expose timedated's real automatic time-sync status on the Date & Time page;
  provide guarded polkit-gated enable/disable with stale-state verification and
  a confirmation before disabling system-wide NTP. Missing services do not
  block timezone selection.

## Unreleased — Creator approved visual regression baselines (8 November 2026)

- Compare actual Wayland PNG captures with optional 1–2 px **bidirectional**
  local RGB tolerance for antialiasing/font rasterization jitter. Report both
  raw and tolerated pixel differences and optionally write a private tolerated
  heatmap; disappearing contours are not silently ignored.
- Add explicit `de visual-baseline --approve-reference` to pin the reviewed
  reference PNG hash, exact recipe fingerprint, resolution and change limits.
  `de visual-compare --baseline` checks these before issuing a reproducible
  PASS (exit 0) or regression (exit 3); malformed/stale baselines fail closed
  (exit 2). No automatic approval, active desktop change or fidelity claim.
- Keep the Creator catalog under its 16 KiB bound, extend the standalone helper,
  and cover changes, tampering, privacy and failure contracts with tests.

## Unreleased — portable RicePack v3 PNG wallpapers (7 November 2026)

- Add schema-v6 wallpaper references by immutable `asset-<sha256>` ID and an
  explicit `de asset-import --asset /absolute/image.png`; reject arbitrary
  filesystem paths, symlinks, malformed PNG/chunk CRC, oversized dimensions,
  unowned or writable files. Assets are 0600 in a private user collection.
- Export deterministic v3 RicePacks with one verified `assets/wallpaper.png`
  and user-declared provenance; inspect/import hash and revalidate its bytes
  before writing any recipe. Preserve v1/v2 reading, v2 bundled-only exports
  and non-applying/no-overwrite semantics. No fonts/icons/multiple assets or
  live cross-component apply are claimed.
- Extend Python/Rust schema parsing, Creator capability contracts and tests;
  guard a rare disappearing `/proc` entry in the existing cleanup regression.

## Unreleased — native menu search and saved actions (7 November 2026)

- Filter approved native RicePlate menu actions by typing their visible label;
  navigate a four-row viewport with the keyboard or mouse, and switch back to
  recipe groups with Escape. This does not search arbitrary installed apps.
- F2 pins/unpins the selected fixed action, F3 toggles the saved-actions view.
  Save up to eight favorites per rice in an owner-private, atomic JSON file;
  reject stale, malformed, symlinked and untrusted state. No executable
  commands, extra background process or source-recipe mutation.
- Update Creator capability discovery, regression checks and the Wayland
  usage guide. Real hardware input/assistive testing remains outstanding.

## Unreleased — RiceSpice on-demand settings hub

- Add a real opt-in GTK3 RiceSpice settings window from the fixed `settings`
  shell action (`ricebowl de settings`), with nine navigable categories and
  keyboard-focusable controls. The application runs only while open.
- Wire actual checked settings to PulseAudio-compatible device selection,
  NetworkManager Wi-Fi state, BlueZ paired devices/adapter power, screen lock,
  confirmed logind suspend and private next-login rice choice. Use bounded
  worker concurrency and stale-state guards, not UI-thread D-Bus or shell.
- Clearly delegate displays, pointer/input, accessibility and timezone to
  installed system editors; missing editors are reported rather than emulated.
  Complete native editors, a live pack transaction and hardware acceptance
  remain open. No privileged service, permission bypass or default-session
  takeover is introduced.
- Make the existing two-output Waybar CI smoke wait for **genuine rendered
  panel pixels** (bounded retries), not merely a newly spawned Waybar PID.
  Persistent missing panels still fail the same pixel check.

## Unreleased — Native RicePop history tabs

- Extend the opt-in RicePlate/Mako notification view with a distinct read-only
  **Past** tab alongside active alerts. Both tabs support bounded three-row
  keyboard/pointer navigation and on-demand refresh. Only active entries expose
  ID-bound dismissal; history cannot replay actions or mutate notifications.
- Validate both Mako inventories, reject truncation and malformed IDs, and
  discard both active and historical private text when the view closes. No
  second notification owner, persistent log or background polling. OSD and
  accessibility/hardware acceptance remain open.

## Unreleased — Native RicePop active alerts

- Add an opt-in native RicePlate menu view for actual active Mako notifications
  with bounded three-row navigation, page movement, explicit refresh, and
  individual dismissal through RicePop's already-validated Python adapter.
- Fetch only on explicit opening/refresh, keep Mako as sole notification owner,
  avoid duplicate daemons or background message polling and discard private
  content when leaving. Show unavailable/empty/loading/refused states.
  History UI, OSD, AT semantics and real hardware tests are still open.

## Unreleased — RicePop Wayland notification bridge

- Add opt-in, read-only `ricebowl de notifications --json` integration with the
  existing Mako notification owner in experimental labwc sessions. Return
  bounded active/history records and explicit unavailable/error state without
  storing messages, invoking third-party actions or launching a second daemon.
- Keep personal notification contents available only through an explicit user
  query. The broader history notification center/OSD is not implemented yet.

## Unreleased — RicePack v2 bundled wallpaper integrity

- Deterministically export v2 RicePacks with a SHA-256 receipt for the exact
  bundled wallpaper bytes plus optional, separate user-declared author/license/
  origin/source metadata for that asset. Inspect/import verify the identity and
  checksum; read-only validation still accepts legacy format-v1 archives.
- Keep archive entries limited to `ricepack.json` and `recipe.json`, with no
  executable payload or untrusted external asset. No automatic rice activation.

## Unreleased — RiceSpice native quick actions

- Implement opt-in native-menu quick actions to toggle Wi-Fi, mute/unmute the
  default audio sink and adjust volume by 5%. The existing sleeping RicePlate
  worker executes only fixed NetworkManager/WirePlumber arguments with bounded
  subprocess times and no shell/privileged helper. An asynchronous footer
  reports applied, unavailable or permission-denied outcomes.
- Ship a separate `quick-controls` schema-v4 example; the Waybar/labwc fallback
  omits native-only actions instead of rendering dead buttons. The status
  widgets remain labels, not misleading clickable toggles.

## Unreleased — Native desktop icons on multiple outputs

- Replicate native schema-v5 desktop shortcuts on additional labwc outputs,
  with independent logical-bounds placement and hotplug recovery in the same
  RicePlate process. Keyboard Tab/Shift-Tab moves between visible shortcuts on
  the focused monitor; Enter/Space activates the selected known action.
- Assert actual icon backplate pixels in two-output headless labwc captures
  before and after unplug/replug. No new daemon or default-session changes.

## Unreleased — live native network/audio status (7 November 2026)

- Render real NetworkManager connectivity states and WirePlumber default-sink
  volume/mute indicators in native RicePlate, with explicit unavailability.
  Never present a status-only widget as a working quick-action button.
- Use one optional, sleeping worker thread with bounded `nmcli`/`wpctl`
  subprocess timeouts and calloop wakeups, keeping input and frame processing
  responsive. Do not start a separate daemon or poll on every UI event.
- Preserve the taskbar's window-group capacity by hiding lower-priority status
  slots when space is tight. Add parser, geometry and genuine framebuffer
  painting tests; keep the SNI tray, native controls and hardware signoff open.

## Unreleased — kernel-backed native battery indicator (7 November 2026)

- Render the first real native RicePlate hardware-status widget: battery
  percentage and charging state read from Linux sysfs, without adding a
  resident poller, network service or privileged dependency. Show honest
  unavailable/unknown labels when no usable battery data exists.
- Retain taskbar capacity on compact/overflowed panels by hiding the optional
  battery label when it would remove a window-group slot. The shared layout
  and paint path also works on secondary outputs.
- Add deterministic sysfs fixture, layout and painter tests; update Creator
  catalog/review capability reporting. Full native network/audio/tray, events
  and real-device acceptance are still outstanding.

## Unreleased — truthful Creator shell catalog v6 (7 November 2026)

- Update `ricebowl de catalog --json` to reflect verified native keyboard
  launcher/task controls, output-bound menus and calendars, and desktop icon
  drag, arrow movement and private per-rice persistence.
- Add a distinct, non-executable `shell_components` inventory for the native
  menu, calendar and desktop shortcut, listing safe actions, focus/inputs,
  multi-output ownership and unsupported features. Keep existing panel IDs and
  recipe schemas unchanged; catalog contract version moves from 5 to 6.
- Assert catalog accuracy and action allowlists in tests. No AI service,
  privileged action or new long-running Creator component is introduced.

## Unreleased — output-owned native Wayland start menus (7 November 2026)

- Give every schema-v4/v5 native RicePlate panel an in-process start menu on
  its own output, reusing validated grouped actions, mouse and keyboard input.
  Switch/close the single visible popup without duplicating shell processes.
- Cleanly drop the active menu on output removal, rebuild hidden per-output
  popup layers on reconnect, and keep the simple fuzzel fallback for recipes
  without a native menu. No change to the default XFCE/Waybar sessions.
- Extend genuine two-output labwc screenshot/hotplug smoke and pixel assertions
  to the native menu; save evidence in the workflow artifact. Physical focus,
  assistive-technology and mixed-DPI signoff remain open.

## Unreleased — output-owned native Wayland calendars (7 November 2026)

- Give each secondary native RicePlate clock a real output-bound calendar
  popup, reusing the primary calendar state, painting and safe controls without
  launching another process. Show at most one calendar at a time.
- Retire disconnected output calendars and clear focus/visibility; reconnecting
  a screen recreates its calendar surface but does not reopen the popup.
- Add real two-output labwc calendar captures, exactly-one-output pixel
  assertions, removal/reconnect smoke and archived visual evidence. Mixed-DPI,
  physical focus/input and accessibility checks remain outstanding.

## Unreleased — interactive native Wayland calendar (7 November 2026)

- Make the primary native RicePlate clock open a bounded, rice-colored calendar
  layer-shell popup, with local dates, leap-year-aware month grids, month
  navigation, a Today button, day selection and arrow/PageUp/PageDown/Escape
  keyboard controls. The popup is in-process and sleeps between input events.
- Preserve Waybar and XFCE clock behavior; output-local calendar ownership is
  delivered by the separate native milestone above.
- Extend real headless labwc CI with a visible calendar screenshot and pixel
  distinction from the normal desktop, plus pure Rust date, hit and drawing
  tests. Physical input/focus and accessibility signoff remain outstanding.

## Unreleased — keyboard-accessible native Wayland taskbar (7 November 2026)

- Support on-demand keyboard focus for the primary and secondary native
  RicePlate panels. Left/Right/Tab select the launcher or grouped windows,
  with a visible keyboard focus frame; Enter/Space activate and Escape clears
  the selection. Repeated activation keys never launch multiple apps.
- Bring an offscreen selected window group into view on its own monitor,
  leaving the other panels' independent task paging unchanged.
- Reuse existing allowlisted launcher and window activation paths, preserving
  the original pointer behavior. Hardware and assistive-technology QA remain
  separate from automated geometry/paint tests.

## Unreleased — native desktop icon movement and private placement (7 November 2026)

- Native RicePlate desktop shortcuts now distinguish activation from a
  pointer drag. Keyboard focus is visibly marked; arrow keys move the focused
  icon in 16-pixel steps and Enter/Space keep the existing safe actions.
- Persist icon placements per rice without rewriting the validated source
  recipe. Require owner-private bounded JSON and reject stale identities,
  oversized coordinates, symlink destinations and unsafe permissions.
- Keep nested Creator/headless screenshots deterministic by ignoring local
  overrides; retain Waybar/XFCE behavior and the unfinished multi-output and
  physical-input acceptance gates.

## Unreleased — reliable isolated Creator renderer shutdown (7 November 2026)

- Supervise an owned Creator render process family, including descendants that
  outlive a wrapper. Use process identity guards before teardown.
- Verify staged PNG size and content hash against the capture receipt and
  publish without overwriting only after cleanup; add injected failure and
  real native headless regression cases.

## Unreleased — experimental native secondary Wayland panels (6 November 2026)

- Draw a separate output-bound layer-shell panel for each secondary display
  without starting another RicePlate process or window-discovery backend.
- Share the same validated recipe/renderer, task groups and clock, but maintain
  independent task paging and framebuffer state for each panel.
- Add a genuine two-output native screenshot and secondary hotplug CI gate;
  save four genuine output captures in the native preview workflow artifact.
  Recover when a compositor temporarily leaves the primary Wayland surface
  unassigned during a display transition. Full per-output native menus/icons
  and primary-monitor failover remain open.

## Unreleased — two-output Waybar fallback verification (6 November 2026)

- Extend the real labwc/Waybar session smoke with two independently captured
  Wayland outputs, a disconnect/reconnect cycle and visible panel verification.
- Keep the native Rust panel's single-output limitation explicit; a green
  fallback monitor test is not native per-monitor or physical-device QA.

## Unreleased — first native Wayland start menu (6 November 2026)

- Replace the schema-v4/v5 native launcher fallback with an actually rendered,
  recipe-grouped start menu inside the existing RicePlate Rust process.
- Add focus-on-open keyboard navigation (arrow keys, Tab, Enter, Escape),
  pointer tabs and action rows, a visible selection and recovery through
  the existing labwc root menu.
- Bind only known actions, explicitly disable logout when not labwc-managed,
  keep the menu parked/unfocused while closed, and capture a real open-menu
  Wayland CI screenshot alongside the established desktop galleries.

## Unreleased — two real Creator demonstration rices (6 November 2026)

- Author one classic OS-inspired and one original Wayland desktop strictly
  through the same schema-v5 panel, menu, wallpaper, tokens and shortcut
  contract, without copied OS imagery, custom shells or unbound fake buttons.
- Run both through isolated native labwc CI at four output geometries; archive
  eight actual compositor screenshots and per-capture hashes, semantic
  fingerprints and visible-geometry diagnostics for reproducible comparison.
- Publish an offline agent-authoring exercise and explicit unsupported-action
  inventory; visuals alone do not certify full OS fidelity or hardware QA.

## Unreleased — reviewed next-login Creator staging (6 November 2026)

- Add `de creator-status`, `de creator-stage` and `de creator-rollback` with
  machine-readable stage v1 responses, semantic SHA-256 preconditions,
  optional concurrent-selection guards and explicit one-step restore.
- Persist reviewed recipe fingerprints in backward-compatible owner-private
  v2 next-login selection state. A recipe changed after review cannot silently
  be loaded as the staged design; the next Wayland session uses classic
  fallback and leaves XFCE untouched. No live desktop mutation is implied.

## Unreleased — portable Wayland Creator recipes (6 November 2026)

- Publish a versioned, offline `de creator-api --json` registry for implemented
  component discovery, safe editing, semantic review, native headless capture,
  visual comparison and package transfer, including honest capability gaps.
- Build reproducible `.ricepack` archives with canonical validated schema-v1–v5
  recipes, exact byte and semantic fingerprints and optional user-declared
  authorship/license provenance. Add safe, bounded inspect and import commands
  that reject malformed ZIP entries, symlinks, collisions and hash mismatches.
- Keep new packs entirely declarative, using only bundled Wayland wallpapers.
  Import does not change active or next-session appearance; existing XFCE
  Riceware ZIP packs and legacy JSON recipes remain supported independently.

## Unreleased — native desktop shortcuts (6 November 2026)

- Add opt-in schema-v5 desktop-icon recipes: bounded labels, safe action IDs,
  non-overlapping positions and strict Rust/Python validation.
- Draw clickable transparent Bottom-layer icon surfaces in the existing native
  RicePlate process without an extra desktop daemon. Keep unused desktop areas
  available to labwc and maintain schema-v1–v4 behavior.
- Extend AI Creator catalog, no-apply draft edits, semantic review, templates,
  shared test fixtures and real headless labwc CI capture to v5.
- Waybar cannot render icons; keyboard, drag, hotplug and widgets remain open.

## Unreleased — RiceBowl shell composition and genuine Wayland visual QA (6 November 2026)

- Add optional strict schema-v4 shell recipes: a generated labwc root menu
  with fixed safe actions, bundled original desktop wallpapers, shared label
  padding/corner radius tokens and compact layout variants.
- Render compact panel variants live in native Rust, and compile a specified
  width through the Waybar fallback; keep schemas v1–v3 and XFCE unchanged.
- Extend Creator discovery, draft editing and semantic diffs to the new shell
  regions. Validate untrusted data before any session files are written.
- Add genuine compositor-framebuffer capture via `grim`, a small offline PNG
  difference analyzer and CI artifact. Neither synthetic mockups nor a pixel
  error ratio are presented as proof of 95% visual fidelity.
- Movable icons/widgets, hotplug-aware Waybar adaptation, real-device checks
  and complete multi-region RicePack composition remain open.

## Unreleased — RicePlate nested panel composition (6 November 2026)

- Add opt-in, strict schema-v3 horizontal panel trees: typed groups, bounded
  spacing, noninteractive safe labels and unique real widget references.
- Consume the same nested layout through native Rust drawing/hit testing and
  the temporary Waybar adapter; keep existing schema-v1/v2 recipes intact.
- Expose the exact compositional vocabulary through the versioned AI Creator
  catalog, private draft edits, semantic review and new v3 recipe templates.
- Test one shared v3 example through Python, Rust unit geometry and the
  headless labwc native startup workflow. Full desktop-wide composition and
  physical display acceptance remain outstanding.

## Unreleased — reliable in-app updates (5 November 2026)

- The Hub now compares GitHub to the **installed** RiceBowl revision, not only
  to the local Git checkout. Manually pulling Git without reinstalling no
  longer produces a false "up to date" message.
- Clean direct installations and pinned GUI updates record their source commit.
  Existing installations without a recorded revision offer a one-time refresh.
  When a dirty checkout is preserved, its installed update is no longer
  offered repeatedly.
- The `ricebowl update` command checks for updates; `ricebowl update check`
  and `ricebowl update apply --yes` now also work through the installed launcher.
  The GUI shows installed, GitHub and local source revisions separately.

## Unreleased — Windows 10 native interaction expansion (5 November 2026)

- Build native 22H2-inspired sound, Bluetooth, battery and calendar flyouts
  using existing verified Linux adapters. Keep Wi-Fi in its independent
  NetworkManager flyout; no new resident service or Microsoft artwork.
- Persist independent Start tile groups, names, sizes (Small/Medium/Wide/Large),
  drag order and pins in a bounded private config file. Retain absent app IDs.
- Add the characteristic optional taskbar search box with automatic small-screen
  icon fallback, safe migration of older visibility preferences and drag/drop
  reorder of taskbar pins with genuine recent-file Jump Lists.
- Make Task View a two-column, real-app-icon overview with window close,
  activation, workspace move and live XFCE desktop management.
- Add native Settings Storage, Power & sleep and installed-app browsing pages;
  Start can also search Settings and real local folder shortcuts.
- Extend native-X11 CI capture sequence with volume/calendar/network/Task View,
  Storage and Apps screenshots; import all 42 verified current images from the
  green final CI run and refresh the Hub's preview. Device and multi-monitor acceptance remain open
  until verified on a real Mint XFCE laptop.
- Add a detailed, non-destructive physical acceptance checklist in
  `WINDOWS10_MANUAL_ACCEPTANCE.md`.

## Unreleased — Windows 10 22H2 interaction pass (5 November 2026)

- Add a working A–Z Start-menu jump list for real installed applications,
  including German umlaut groups, without expanding the list at startup.
- Give the Windows 10 taskbar persistent, per-rice Search/Task View visibility
  options in its right-click menu, plus a native Personalization entry.
- Group genuine XFCE notifications by application with original icon/time,
  per-item read/dismiss and confirmed asynchronous Clear all. Allow Quick
  Actions to expand/collapse; unsupported providers remain disabled.
- Keep the Start menu mapped while its native A–Z or navigation popup owns
  focus; give the letter grid an explicit visible dark surface. Let the tall
  Action Center scroll history above its expanded quick-action controls.
- Refresh the real 1600×900 GTK/XFWM gallery, including separate A–Z Start
  and expanded Action Center views; regenerate the hub's JPEG previews.
- Keep all other desktop styles, global XFCE settings and pre-existing
  Microsoft-free RiceBowl artwork unchanged.

## Unreleased — XP Luna native fidelity overhaul (5 November 2026)

- Bring XP Control Panel closer to Explorer with a real Back/Home/Search strip,
  descriptive address breadcrumb and preserved category/classic/search routes.
- Rework taskbar properties with 2001-style grouped settings, live sample,
  real notification-icon customization and confirmed recent-program clearing
  without touching Start favorites or other desktop profiles.
- Prefer the genuine Gio device/volume browser for My Computer with a safe
  filesystem fallback. Add original recent-document artwork and cohesive
  Luna-only GTK controls, context menus, keyboard focus and hover states.
- Ensure Taskbar and Start Menu Properties has a real, draggable Luna titlebar
  instead of relying on decoration of a dialog transient for the XFWM dock.


## Unreleased — secure visual Rice packs v2 (5 November 2026)

- Build, inspect and import local ZIP packs containing declared and SHA-256
  verified wallpaper, GTK CSS, XFWM4 and PNG/JPEG icon assets. Reject unsafe
  archive paths, symlinks, scripts, embedded SVG and CSS resource imports.
- Require an explicit license/provenance declaration and user acknowledgment;
  reserve versioned user-local theme/icon names without overwriting existing
  themes. Imported packs appear in the existing Hub style selector.
- Apply custom appearances through the existing RiceBowl preflight and desktop
  rollback journal. The login reconciler recognizes installed GTK pack themes
  and keeps the correct native rice shell; inactive packs can be moved into
  private recovery storage instead of being erased.
- No background process, network download, elevated privilege or new runtime dependency.

## Unreleased — data-only Rice pack discovery (5 November 2026)

- Add a versioned, inspectable Rice pack catalog for all built-in styles and
  validated user-owned JSON presets. On-demand capability reports identify
  essential XFCE/X11 commands and optional riceExplorer/device helpers.
- Expose `macrice riceware packs list|show|check|template|apply`; the only
  mutation is explicit `apply ID --yes`, which reuses the real RiceBowl
  preflight, journal, rollback and session handoff. Custom packs currently
  alias a supported built-in appearance; arbitrary scripts/assets are rejected.
- Show validated user presets within the correct family in the existing GTK
  Hub Appearance picker; preview, preflight and apply use the actual supported
  base style, with the user's preset name visible during confirmation.
- Resolve session shell ownership from the same canonical style/family mapping
  used by manifests, removing a separate hand-maintained GTK-theme router.
  No new resident monitor, background service or forced XFCE component removal.

## Unreleased — rice-specific plug-and-play checks (5 November 2026)

- Extend the existing read-only `macrice doctor` with `--style STYLE` and
  `--json`. It reuses that rice's real asset/settings preflight and reports
  whether the plan succeeds, including a count of proposed changes; it does
  not apply a theme or start a background checker.
- The Hub's existing **Run read-only system check** now also checks the
  currently chosen rice. Failures show a safe follow-up command without
  exposing private configuration paths in the health summary.
- Bundle the ricePlate desktop and XFCE recovery guides in user-local
  installs, so their links stay usable after installation.

## Unreleased — internal ricePlate desktop preview (5 November 2026)

- Preview Desktop icons now refresh automatically through Gio directory change
  notifications (coalesced into a single short update). There is no idle poller,
  timer-based scanning or extra background service. Filesystems without monitor
  support retain an explicit Refresh fallback; monitors are cancelled on close.
- Kept ricePlate within RiceBowl as a reusable, no-daemon backend plus optional
  GTK3 desktop canvas. `macrice riceware plate preview --style STYLE` displays
  the real current-user Desktop folder against the chosen rice's checked-in
  wallpaper. Desktop ownership, window management, wallpaper preferences,
  autostart, default file manager and all desktop files stay unchanged.
- Added separate, atomically saved per-rice icon size, alignment, visibility
  and hidden-file preferences in a private user-local config. ChromeOS defaults
  to an icon-free canvas; Mac icons default right, classical Windows icons left.
- Added keyboard/selection/context Open and Refresh interactions, bounded
  asynchronous inventory, safe symlink handling, error/empty states and
  native-X11 tests. Future XFDesktop retirement is explicitly gated on real
  compatibility, recovery, multi-monitor and resource acceptance.

## Unreleased — lean XFCE session and measured resource ownership (5 November 2026)

- Avoid launching Python/GTK `--quit` helpers for inactive RiceBowl shells
  whose session D-Bus name and actual user-owned process are both absent.
  Keep the conservative fallback when a shell is starting or D-Bus fails.
- Add on-demand `macrice performance desktop [--samples N] [--json]` alongside
  the original RiceBowl-only `report`. Inventory recognized XFCE processes,
  show their role and real sampled PSS/CPU, and identify duplicated
  panels/docks. The Hub's existing Measure button includes these processes.
- Document which XFCE services cannot yet be replaced safely. No resident
  monitor, background-service shutdown, autostart rewrite or simulated memory
  saving was introduced. Actual Mint/XFCE idle savings need owner measurement.

## Unreleased — Frutiger taskbar pointer evidence (5 November 2026)

- Added an explicitly enabled Frutiger interaction trace for Start, pinned
  apps, audio/network/power/Bluetooth, mounts, notifications and calendar.
  `macrice frutiger-shell --trace-actions` begins recording on the existing
  shell; `--trace-stop` ends it; `--trace-path` prints the private output path.
- Records only allowlisted targets, click/dispatch/result phases and Boolean
  popup visibility. Cache file is private, size-limited and rejects symlinks;
  no auto-start, secret capture, polling loop or device mutation is added.
- The root cause of the owner's inert-button report is **still unverified**;
  physical Mint/XFCE evidence is needed before claiming it fixed.
- Recorded `RiceTask` as a future separate Rust process-manager project,
  explicitly deferred until the owner authorizes creating the repository.

## Unreleased — consistent real Task Manager access (5 November 2026)

- Windows 98, XP Luna and Windows 10 now include a real Task Manager action
  in the empty taskbar area's right-click menu. The existing Windows 7 action
  uses the same resolver. ChromeOS and Frutiger retain their Settings links.
- Prefer installed `xfce4-taskmanager`, falling back to `gnome-system-monitor`.
  If neither is installed the action is disabled with a useful explanation;
  no fake process UI or new daemon is launched.
- Added a shared deterministic resolver, hermetic selection and source tests,
  and GTK/X11 shell-smoke assertions covering all four taskbar menu variants.
  Real hardware verification remains open.

## Unreleased — cross-application window theme diagnostics (5 November 2026)

- Added `macrice app-compat --select` and `--window-id HEX [--json]` for
  read-only X11 window-class/decoration-hint and current GTK/XFWM theme checks.
  Bounded subprocess calls exclude private titles, arguments and profiles.
- Documented PhotoCraft's egui/System Title Bar and Thunderbird's native
  title-bar settings. XFWM cannot theme their custom-drawn application content.
  No third-party preferences, GTK profiles or Thunderbird CSS are rewritten.
- Confirmed existing XFCE/GNOME Task Manager fallbacks instead of claiming a
  custom themed process monitor. On-device app/window acceptance stays open.

## Unreleased — Windows 10 Settings navigation and visual depth (5 November 2026)

- Rebuilt the native Windows 10 Settings experience with a centered category
  Home, system-theme icons, scrollable detail navigation, search results that
  open real subpages and a no-results state. Back/Escape/Ctrl+F keep the flow
  keyboard-reachable; search is synchronized between Home and detail views.
- Replaced menu-like text controls with 22H2-style rectangular action rows,
  well-spaced category hierarchy and compact native GTK radio/notification/
  audio switches. Unavailable tools are visibly disabled, and backend errors
  remain legible after readback; no unverified Linux switch state is faked.
- Added genuine Linux handoff categories for Gaming, Search and Update &
  Security. No software updates or sensitive permissions are changed silently.
- Added hermetic regressions and native-X11 Home/Sound screenshot gates at
  1600×900 and 1024×768. Real-hardware acceptance remains open.

## Unreleased — safe update of dirty checkouts (5 November 2026)

- Added a dedicated, explicitly confirmed Hub recovery path for an existing
  official Git `main` checkout with local tracked or untracked edits. RiceBowl
  can stage and install a pinned official revision into the managed application
  while leaving the *entire source checkout* unchanged; no stash, reset, merge
  or automatic reapplication of personal edits is attempted.
- The new `macrice update check --refresh --preserve-checkout` and
  `macrice update apply --yes --preserve-checkout` CLI options expose the same
  opt-in path. Normal clean-checkout updates still fast-forward as before.
- The Hub displays affected path names and warns that the checkout will stay
  at its old SHA. A later in-app fix records the installed commit separately,
  so unchanged local files do not trigger the same update again.
- Isolated local-Git tests cover dirty files, conflicting upstream edits,
  unchanged stash lists, stale review, rollback on failed installation and
  clean-checkout compatibility. Physical-device acceptance is pending.

## Unreleased — owner QA interaction follow-up (5 November 2026)

- ChromeOS WLAN shelf button opens the native Network page of its Quick
  Settings panel and toggles it on repeat clicks instead of spawning an
  external settings tool. Added GTK smoke and source contract regressions.
- Windows 7 Control Panel category, task and Large/Small icon pages explicitly
  reveal both their `no-show-all` GTK containers **and their child widgets**;
  native smoke verifies visible page contents rather than just navigation.
- Windows 98 tray popups calculate root coordinates from the clicked status
  button rather than the shared taskbar's window; 1024px/offset-monitor
  placement has deterministic geometry regressions.
- XP Luna Control Panel uses the shared, keyboard-accessible GTK EventBox
  caption handle; Close stays outside the draggable region.
- The opt-in updater reports changed Git path names safely (including spaces
  and staged renames), retains its refusal to overwrite dirty checkouts and
  exposes the full selectable preservation guidance inside Hub Recovery.
- Explicit Gio desktop-launch failure from any pinned or menu app now shows
  an error instead of silently treating `False` as successful.
- Extended Frutiger native-X11 pointer test coverage to actual tray flyouts,
  Start and app pins; **this is diagnostic coverage, not proof that the user's
  inert-icon report is resolved**. All physical Mint/XFCE acceptance remains
  open in the owner QA sheet; no new release has been declared.

## Unreleased — Windows 98 Start cascade focus guard (5 November 2026)

- Share the existing XP native-popup focus guard with Windows 98: root and
  nested GTK cascades are tracked while mapped, so an X11 focus transfer to
  Programs/Favorites/Settings no longer triggers the 650 ms Start dismissal.
  Intentional Start toggles and menu actions still close the popup tree.
- Added a headless regression contract and a native GTK smoke assertion for
  the mapped Programs cascade. Full pointer traversal on the owner's Mint/XFCE
  laptop remains an explicit acceptance gate in `OWNER_QA_2026-11-05.md`.

## Unreleased — Frutiger launcher escape and real tray menus (5 November 2026)

- Fixed a focus-dependent Settings dead end: selecting an Aqua Control Center
  category hides the keep-above launcher even when the Control Center was
  already visible. Added a synchronous repeat-open assertion to native X11
  tests and kept Apps/Places exit buttons above the Settings scroll area.
- Reworked the Frutiger Wi-Fi, sound/media, Bluetooth and power taskbar
  flyouts around **direct, scrollable hardware actions** rather than large
  “More settings” buttons. Device rows, action buttons and accessible icon
  controls use a consistent pearl-glass style. Backend verification and
  confirmation before disabling radios are unchanged.
- GTK regressions cover the new flyout layout and full Settings shortcut;
  physical Mint/XFCE network, audio and Bluetooth acceptance remains open.
  macOS Aurora and riceExplorer integration are unchanged.

## Unreleased — cross-rice persisted windows, limited file drops and display guard (5 November 2026)

- Six non-macOS Settings windows now persist independently in bounded,
  private user geometry files. Hidden/reopened windows retain size/position;
  stale off-screen coordinates are recovered after a display change.
- Added `ricePlate` copy-only, `text/uri-list` GTK drop targets to XP/Win7/Aqua
  folder shortcuts and the Win98 Desktop inspector. A drop confirms the exact
  folder and count; background copies refuse existing names, do not follow
  symlinks and offer an undo for unchanged new files. Desktop ownership stays
  with XFDesktop/Thunar, and full folder moves await riceExplorer **1.0**.
- Aqua Display now has an explicit temporary mode/position editor for one
  active X11 output; its detached, private-session rollback helper reverts
  after 18 seconds unless user-confirmed. Rotation, scaling, physical HDMI
  failure/black-screen recovery and full multi-output transactions are not
  claimed complete. No root process or persistent daemon was added.
- New hermetic unit tests cover rollback failures/timeouts, off-screen
  window recovery, file collision/cancellation/undo and GTK drop registration.
  [PR #68](https://github.com/CopyPasteUser/RiceBowl/pull/68) passed native
  GTK/XFWM4 CI (628 headless tests plus native smoke/captures); an initial
  1024px screenshot failure exposed partially off-screen restored Settings,
  which was fixed with full-monitor clamping and a regression test. Physical
  Mint/XFCE hardware checks remain required.

## Unreleased — native settings windows and Hub update entry (5 November 2026)

- Added a visible two-stage **Check for updates → Install update…** action to
  the Hub sidebar, reusing the verified official-origin pinned updater,
  confirmation, archived recovery and failure messages already in Recovery.
- Added shared WM-integrated settings-window behavior: custom mouse/keyboard
  draggable captions, normal taskbar/Alt-Tab identity and focus persistence
  in Aqua/XP Control Centers and Windows 10 Settings. No macOS UI changes.
- Extended Aqua's own Bluetooth settings page with short, cancellable scans
  and pairing through the *existing Linux BlueZ agent*. Local PIN-agent,
  file drag-and-drop and writable display layout are still open workstreams.
- Added headless WM contracts and native GTK/X11 smoke coverage; tracked
  the explicit cross-rice window and DnD acceptance gates separately.

## Unreleased — BlueZ discovery and native display topology (5 November 2026)

- Added real, nine-second BlueZ D-Bus device discovery inside the Frutiger
  Bluetooth flyout, with cancellation when closing, one owned discovery session
  at a time, guaranteed stop and no new background daemon.
- Pairing now uses BlueZ `Device1.Pair` and its system default agent for any
  interactive PIN/confirmation; missing agents or rejected pairing are reported
  as failures, not success. No auto-trust or automatic post-pair connection.
- Aqua's Display Control Center lists actual RandR outputs, current mode,
  screen position, primary flag and available modes. It performs no monitor
  writes; safe resolution changes stay with XFCE Display Settings for now.
- Extended deterministic DBus/scan-cancel/parser tests and README readiness
  matrix. Mac Aurora remains unchanged; physical hardware acceptance pending.

## Unreleased — Frutiger media and mounted-location follow-up (4 November 2026)

- Added native MPRIS player status and capability-gated Play/Pause/Next/Previous
  inside Aqua's existing Sound & Media flyout. Media metadata is queried only
  on user-triggered refresh and discarded on closing the popup; no resident
  monitoring, additional service or new mandatory Python dependency.
- Added a separate pearl-glass connected-locations tray flyout based on Gio's
  existing event-driven VolumeMonitor. It opens real mounted locations,
  displays empty/provider states and offers explicitly confirmed asynchronous
  unmount without forcing device ejection.
- Added hermetic MPRIS allowlist/readback and mount confirmation tests, plus a
  native GTK constructor/signal smoke case for the new mounted-locations UI.
- Made 1.0 readiness and missing release gates more prominent in the README.
  macOS Aurora remains visually unchanged; live-device and native-X11 CI
  signoff for this follow-up are pending.

## Unreleased — read-only diagnostics, safe updater and 1.0 acceptance preflight (4 November 2026)

- Added `macrice doctor [--json]` and a native Hub Recovery diagnostics panel;
  it inspects XFCE/X11, package/launcher availability, optional backends and
  private shortcut recovery records without starting processes or exposing
  private shortcut commands.
- Added opt-in `macrice update check --refresh` / `update apply --yes` and Hub
  update confirmation. Only clean `main` with an allowlisted official remote
  can fast-forward. A pinned staged installation retains the prior managed
  bundle and attempts recovery on failure; no unattended update. Signed release
  verification and fully atomic multi-component rollback remain future gates.
- Extended Aqua Wi-Fi with a password-only-on-stdin WPA connection flow and
  BlueZ Pair on known, discovered devices (PIN/enterprise cases keep native
  system fallbacks), plus a local GTK Calendar on Frutiger's tray clock.
- Added sequential multi-rice/failure-handoff simulations, updater rollback and
  wrong-origin security tests, credentials non-disclosure contracts, and an
  on-demand `performance report --samples N --json` median snapshot.
- Documented physical Mint/X11, external monitor, battery, suspend, PSS and
  incomplete Frutiger P0 acceptance gates in `ACCEPTANCE_1_0.md`. No Aurora
  visual changes and **no stable 1.0 sign-off**.

## Unreleased — session fallback, resource reporting and Aqua quick controls (4 November 2026)

- Fixed the session synchronization escape hatch: returning to a stock XFCE
  theme recovers XFCE Panel and original shortcuts; failed shell starts,
  shutdowns and handoffs also attempt stock-panel recovery.
- Extended the existing **on-demand** `macrice performance report` to recognize
  all six RiceBowl non-macOS shells and display per-process PSS, sampled CPU and
  thread count, without introducing an idle monitor or extra worker.
- Added Frutiger-only pearl-glass tray flyouts for actual Wi-Fi networks,
  paired Bluetooth connections, audio output devices and power profiles.
  Actions go through the shared verified Riceware facade; disabling either
  wireless radio needs a second confirmation click. Missing backends and
  failed writes show errors, and hidden popups discard stale results.
- Extended lifecycle, error-path and session-recovery regressions plus the
  native Frutiger GTK smoke scenario. On-device Mint acceptance remains open.
  The macOS Aurora UI is unchanged.

## Unreleased — Frutiger Aero shared Riceware integration (4 November 2026)

- Migrated Aqua World taskbar hardware status, volume and mute controls to one
  per-shell bounded riceSpice worker with verified readback and safe shutdown.
- Shared the native hardware facade with ChromeOS without coupling the two
  independently styled desktop UIs. Aqua Control Center device controls and
  bounded read-only Linux probes now use the Frutiger worker; navigating away
  disposes stale callbacks and debounced writes.
- Added an original Aqua notification bubble for XFCE's existing ricePop
  history, real Do Not Disturb with verification and explicit mark-read. No
  replacement notification daemon, synthetic toggles or new persistence.
- Expanded adapter and notification tests plus Frutiger GTK smoke coverage.
  Actual Mint hardware, suspend/resume and the complete Aqua P0 roadmap
  remain open.

## Unreleased — ChromeOS shared Riceware integration (4 November 2026)

- Migrated Material You shelf device status, Quick Settings volume/mute and
  native Wi-Fi/Bluetooth/audio/brightness/battery/power controls to a single
  bounded, closeable riceSpice worker with verified write-readback.
- Reused those native device pages inside the separate searchable ChromeOS
  Settings window. Advanced Linux utility links remain optional; unsupported
  devices are disabled honestly and changes never imply success prematurely.
- Reused ricePop for XFCE's existing notification history, unread badge,
  DND, mark-read and dismiss actions with one shared worker and an event
  observer that closes on shutdown; no second notification daemon or log.
- Added stale-page invalidation, hardware detail navigation and adapter
  tests. Original Shelf, Launcher and ChromeOS artwork remain unchanged.
- Physical Mint hardware, suspend/reconnect, multi-monitor geometry, full
  ChromeOS fidelity and riceExplorer theme acceptance remain open.

## Unreleased — Windows 98 SE Riceware device and desktop integration (4 November 2026)

- Migrated Classic taskbar status, volume and mute writes onto the same bounded,
  verified riceSpice worker as the newer rices, removing independent Classic
  hardware threads and retaining XFCE ownership.
- Added original square/beveled Windows 98 network, Bluetooth, output-device,
  brightness and power-scheme controls with live data, explicit writes, bounded
  discovery lists, stale-callback suppression and recoverable backend errors.
- Opened those Classic dialogs from corresponding native Control Panel applets,
  including on installations without third-party settings launchers; kept
  advanced Linux tools accessible where available.
- Added a read-only ricePlate/XFDesktop desktop icon inspector with actual file
  metadata, folder navigation and no competing desktop or shortcut service.
- Narrowed the `winclassic` identity to **Windows 98 SE**, leaving a potential
  distinct Windows 2000 rice for later. Preserved original Linux artwork.
- Added regression tests and actual GTK/X11 smoke for new popups; real Mint
  hardware, suspend/reconnect and advanced full-fidelity applets remain open.

## Unreleased — Windows 10 native Settings, Network and Task View (4 November 2026)

- Added independently rendered Windows 10 Settings with nine discoverable
  categories and real sound/mute/brightness, Wi-Fi/Bluetooth and Focus Assist
  controls, category/subpage navigation and explicit native advanced-tool links.
- Added a NetworkManager-backed network flyout with bounded SSID list, manual
  rescan, explicit connect/disconnect and honest unavailable/credential states.
- Added Task View over real libwnck windows and XFCE workspaces, with explicit
  switching, window relocation and guarded workspace create/remove operations;
  no additional window manager or desktop daemon.
- Added an optional RiceExplorer `--theme win10` launch in Start when installed,
  without modifying Thunar, MIME defaults or file associations.
- Expanded regression and native X11 smoke coverage; full Win10 Settings and
  global shortcut coverage, physical devices and multi-monitor tests remain open.

## Unreleased — Windows 10 Riceware Action Center migration (4 November 2026)

- Migrated Windows 10 taskbar hardware status and Action Center volume/mute
  controls to shared, verified riceSpice backends with a bounded worker.
- Replaced static Action Center notification placeholders with live XFCE
  ricePop history, explicit mark-read and individual dismiss; release private
  notification text when the drawer is hidden, and keep XFCE as sole host.
- Added truthful radio switches for Wi-Fi and Bluetooth plus Focus Assist via
  XFCE Do Not Disturb; unavailable hardware leaves switches disabled and failed
  writes never show optimistic success.
- Preserved Windows 10's own square, charcoal 22H2 UI and settings launchers;
  added hermetic adapter tests. Physical hardware and full Fidelity roadmap
  acceptance remain open.

## Unreleased — Windows 7 Action Center and native Control Panel devices (4 November 2026)

- Added the independent Windows 7 white-flag Action Center flyout that reads
  the actual XFCE notification log via ricePop; unread/quiet/unavailable status
  is truthful and marking read is explicitly user-triggered. Stored third-party
  actions are never replayed, and XFCE remains the only notification host.
- Added original Aero-style, dismissible hardware transition balloons for
  network/battery/removable drives; suppress them when native DND is enabled or
  cannot be established. No duplicate third-party toast delivery.
- Linked Power, Network, Sound and Bluetooth Control Panel detail pages to
  the same live Win7 Riceware device flyouts, retaining advanced Linux tools.
- Added hermetic checks and native GTK/X11 small-screen Action Center capture.
- Physical Mint acceptance, full native Win7 file manager, edge-drag Snap and
  compositor-level DWM fidelity remain separate unfinished release gates.

## Unreleased — Windows 7 Aero Riceware integration (4 November 2026)

- Reused the verified LunaTray riceSpice device API and bounded GTK worker
  behind Win7Tray's independently styled Aero flyouts.
- Migrated Windows 7's taskbar status and shared Control Panel volume/mute
  actions away from per-action backend threads; close the worker on shutdown.
- Routed opt-in Windows 7 desktop shortcuts through ricePlate, preserving
  byte-identical/user-edited-file safety and XFDesktop ownership.
- Added Win7-specific regressions and maintained virtual-X11 smoke coverage;
  physical Mint tests and deeper applet/notification migration remain open.

## Unreleased — Windows XP Luna shared Riceware migration (4 November 2026)

- Migrated XP Luna's live taskbar hardware status, audio volume/mute/output,
  Wi-Fi radio/scan/connect/disconnect, Bluetooth power/device connections,
  power profiles and brightness onto the shared riceSpice API with verified
  state readback and per-shell bounded GTK worker dispatch.
- Routed opt-in XP desktop shortcuts through ricePlate while retaining the
  existing safe XFDesktop ownership and user-modified-file preservation.
- Added explicit riceSpice Wi-Fi rescan and deterministic XP adapter regressions;
  left other rice renderers, native XFCE advanced tools and Linux services
  untouched. GUI/physical hardware certification is tracked separately.

## Unreleased — Riceware migration API 1.0 (4 November 2026)

- Introduced a source-compatible `macrice.riceware` 1.0 API contract, stable
  style-to-rice-family mapping and capability/action discovery for independent
  XP/Classic/Win7/Win10/ChromeOS/Frutiger/macOS renderers.
- Added a bounded, lifecycle-owned GTK main-loop worker bridge with stale-result
  suppression; no GTK calls or hardware subprocesses are required on UI threads.
- Added typed riceSpice action metadata/validation, an opt-in event-driven XFCE
  notification observer, and safe bounded desktop launcher metadata reads.
- Added a private, locked, atomic riceWine app catalog with register/list/run/
  unregister operations for shared Windows-app launchers. No application file,
  user MIME default, Wine prefix or desktop settings are deleted.
- Published a per-rice migration guide and new deterministic contract/security
  tests. API 1.0 does **not** claim a RiceBowl 1.0 desktop release or completion
  of physical Mint, Wine GUI or multi-rice interaction acceptance.

## Unreleased — Riceware backend reliability hardening (4 November 2026)

- riceSpice now checks each requested mutation against actual device readback,
  serializes conflicting in-process device writes and surfaces malformed or
  unavailable provider responses without reporting false success.
- ricePop now exposes truthful host capabilities and validates history IDs;
  clearing notification history through the CLI requires explicit `--yes`.
- ricePlate now bounds desktop inventory memory, reports truncation and treats
  special filesystem entries honestly instead of pretending they are files.
- riceWine now requires a real registry before marking a prefix initialized,
  locks concurrent init/recovery, supports explicit retries and private bounded
  diagnostic reads, kills only its own timed-out init process group, rejects
  immediate failed launches and reports unsafe prefix permissions.
- Added isolated concurrency/fault-injection checks. This hardens the core API;
  it is **not** physical hardware, cross-rice UI or full Wine-app certification.

## Unreleased — Shared Riceware backend foundations (4 November 2026)

- Added on-demand `macrice.riceware` backends for riceSpice (real hardware reads,
  explicit writes and readback), ricePop (XFCE-native notification history and
  delivery), ricePlate (read-only desktop inventory plus reversible existing
  XP/Win7 shortcuts) and an opt-in riceWine managed-prefix prototype.
- Added `macrice riceware` commands for manual/backend testing. No new daemon,
  desktop owner, Wine requirement, default file-manager switch or theme/UI
  migration is introduced.
- Added hermetic contract/security tests and required bundle file checks.
  Hardware, Wine GUI execution and seven-rice renderer integration remain
  separate acceptance gates; the tagged v0.9.1 release is unchanged.

## Unreleased — Verified one-run screenshot refresh (4 November 2026)

- Replaced the six current desktop-style Start/launcher, control and genuine
  XFWM4/Thunar captures with images from a single green GitHub Actions run.
  Regenerated the Hub's six JPEG previews from the same source images.
- Added actual ChromeOS Settings and notification-history screenshots, XP Luna
  programs/control views, Taskbar Properties, notification-icon settings, Run
  and five system-tray flyouts, plus standalone dark MacMenu.
- Store the exact source commit, CI run ID, original PNG hashes, converted WebP
  hashes and dimensions in the current gallery manifest. The importer refuses
  missing, duplicate, malformed or visibly empty required captures rather
  than mixing screenshot revisions. Current preview links and component docs
  now point to the refreshed images.
- Only virtual-X11 behavior has been validated: neither integrated MacBar/Plank
  nor physical Mint hardware testing is claimed by these screenshots.

## Unreleased — ChromeOS genuine XFCE notification center (4 November 2026)

- Added a dedicated Shelf notification bell with a real unread marker backed
  by XFCE's `org.xfce.Notifyd.Log` D-Bus interface and change signals.
- ChromeOS Quick Settings now displays bounded, application-grouped notification
  history with real titles, timestamps and descriptions, individual Mark read /
  Dismiss actions, Mark all read and confirmation before deleting all history.
- Do Not Disturb uses XFCE's persisted `xfconf-query` setting with read-back
  verification. The control is disabled when the native provider is missing.
- D-Bus, XFConf and notification updates run off the GTK main thread. Private
  history entries are discarded from the view when Quick Settings closes.
- Added backend schema/sanitization/error tests and a real GTK smoke path for
  opening/closing the notification panel. No replacement notification daemon,
  synthetic app notifications or replayed expired actions.

## Unreleased — ChromeOS local Shelf calendar (4 November 2026)

- The ChromeOS Shelf clock now opens a genuine local monthly calendar rather
  than simply toggling Quick Settings. The Quick Settings date also opens it.
- GTK provides locale-aware month/day navigation and current-day highlighting,
  with a dedicated Today button, Back and Escape. There are no synthetic
  online event entries or implied Google-account synchronization.
- Added a leap-year/month-index regression test and extended the virtual-X11
  ChromeOS smoke flow to open, verify and leave the calendar page.

## Unreleased — ChromeOS hierarchical device settings (4 November 2026)

- Added an independent Material You Settings window with seven searchable
  categories, section/detail navigation, Back/Escape behavior and deep links
  from the launcher and Quick Settings. Missing installed Linux tools are
  disabled with an explicit explanation, not represented as fake Google APIs.
- Replaced the six first-click Quick Settings utility launches with navigable
  detail pages, truthful live hardware status and explicit local Linux actions.
- Reused the existing asynchronous, read-back-verified Wi-Fi, Bluetooth,
  brightness, battery and power-profile controls with ChromeOS-scoped styling.
  The network adapter's existing explicit radio-off confirmation is retained.
- Added search, backend availability and status regression tests. The dedicated
  ChromeOS X11 smoke path now exercises Quick Settings Back and multi-level
  Settings navigation. Physical-device acceptance remains outstanding.

## Unreleased — Windows 7 persistent Superbar pin ordering (4 November 2026)

- Reorder pinned Windows 7 launchers by dragging onto another pin's left/right
  half. The GTK target accepts drags only from this running application and
  validates stable existing `.desktop` IDs before writing anything.
- Add keyboard-accessible **Move pin left/right** actions to pinned launcher
  Jump Lists, disabled at the corresponding list edge. Persist order through
  the existing validated, atomic Aero pin file with visible save errors.
- Add pure before/after/no-op/corruption tests and native GTK/X11 DnD target
  registration smoke assertions. The other rice families keep their previous
  pin behavior. Physical DnD acceptance on Mint XFCE is still open.

## Unreleased — Windows 7 taskbar window layout and Task Manager (4 November 2026)

- Completed native blank-Superbar context actions for **Cascade windows**,
  **Show windows stacked**, **Show windows side by side**, and **Undo window
  arrangement**. Move only normal, visible, non-fullscreen windows on the
  active monitor; cap at 12 and disable layouts with unusably small cells.
  The original per-window geometry is retained for an explicit restore.
- Added **Start Task Manager** backed by the installed `xfce4-taskmanager` or
  `gnome-system-monitor`; without either utility it is honestly disabled.
- Added pure geometry and reversible-lifecycle tests plus a native GTK/X11
  smoke check for all new menu entries. RiceExplorer and other rice shells
  are unaffected. Physical Mint/XFCE window-management acceptance remains open.

## Unreleased — Windows 7 native window arrangement and attention (4 November 2026)

- Show a distinct amber Aero Superbar state for real X11 window-attention
  requests, including inactive members of grouped applications. Native
  Wnck state-change signals clear the warning when the request is dismissed.
- Add per-window **Snap left/right**, **Maximize** and **Restore previous size**
  to the running-app Jump List (under **Arrange windows** for app groups).
  Actions target existing XFWM4 windows without changing global keybindings;
  tile bounds respect each window's monitor workarea, including negative
  coordinates and taskbar/panel reservations. Closed windows discard cached
  geometry. Fullscreen and non-task windows are not rearranged.
- Add dedicated unit tests for odd-width split, multi-monitor choice, state
  restoration, closed windows and real attention snapshot propagation; extend
  the native GTK smoke test for grouped menus and attention styling.
- Edge-drag, global Win+Arrow keybindings, Shake, preview compositor parity
  and physical Mint acceptance remain open.

## Unreleased — Windows 7 personalized notification icons (4 November 2026)

- Added an Aero-themed **Customize Notification Area Icons** dialog reachable
  from the hidden-icons chevron or a blank Superbar right-click. Choose 0–8
  directly displayed app icons and per-app Automatic / Show / Hide preferences.
- Persist preferences only for valid stable StatusNotifier `Id` values in a
  bounded, versioned, atomically written user-local JSON file. Ephemeral D-Bus
  names are never saved; malformed or symlinked configuration is preserved.
  A Restore defaults button clears stored overrides.
- Preference changes reorder real running SNI icons immediately, without
  affecting device widgets or any non-Windows-7 rice.
- Added filesystem, format, symlink, priority and regression tests. Real device
  and live third-party SNI testing on the owner's laptop remains open.

## Unreleased — Windows 98 classic functionality (4 November 2026)

- Enhanced Find with real type, extension, date, size and hidden-file filters, plus bounded text-content search (1 MiB/file, 32 MiB total). The search remains cancellable, read-only and capped at 50,000 entries / 500 results.
- Replaced the static Help dialog with a local Contents/Index/Search viewer and Back/Forward/Home navigation.
- Added a native read-only System Properties applet with real Linux kernel, CPU, RAM, network, disk and uptime data, plus manual Refresh.
- Added disposable-file-system and native GTK/Xvfb regression coverage. Physical Mint acceptance and the remaining Classic roadmap remain outstanding.

## Unreleased — Windows 7 Superbar overflow and desktop integration (4 November 2026)

- Added a Windows 7-only StatusNotifier overflow chevron. The Superbar shows up
  to three active application tray icons, prioritizes urgent attention icons,
  and opens a keyboard-accessible Aero popup for remaining live SNI entries.
  Passive icons stay hidden; XP/ChromeOS/Frutiger tray behavior is unchanged.
- Added opt-in, safely removable Windows 7 desktop shortcuts for Computer,
  Documents, Network and Recycle Bin via XFDesktop/GIO. Installation/removal
  requires confirmation, never overwrites existing/edited files, and does not
  alter default file manager or XFCE configuration.
- The blank Windows 7 taskbar now has a right-click menu for Show Desktop,
  managed desktop icon installation/removal, and the actual XFDesktop settings.
- Added selection, icon-state and filesystem-safety regression tests.
  Live SNI applets and physical Mint/XFCE acceptance remain outstanding.

## Unreleased — Windows 7 Aero deep controls (4 November 2026)

- Added distinctly Windows 7-style native tray windows for volume/output
  devices, Wi-Fi, power/brightness, Bluetooth and date/calendar. They reuse
  bounded asynchronous Linux hardware transactions with read-back verification;
  unsupported hardware or permissions never become pretend toggles.
- Added Control Panel Category/Large/Small views, browser-like Back/Forward
  navigation and third-level Linux-app task pages with disabled states.
- Added an optional Start shortcut for RiceExplorer's structural `win7`
  renderer when installed, without changing Thunar or global file associations.
- Extended unit and GTK/X11 smoke checks. Fresh native screenshots and physical
  Mint acceptance remain pending; published v0.9.1 is unchanged.

## Unreleased — Frutiger Aero Pearl Glass polish (3 November 2026)

- Rebalanced the real Aqua World launcher around pearl-white glass, calmer
  mint app tiles, a clearer Discover section and distinct lime selected tabs.
  The home grid prioritizes saved pinned apps and familiar installed desktop
  programs, while search still covers the complete application catalog.
  A fresh desktop no longer mistakes XFCE's File Manager Settings for the
  actual Thunar File Manager when seeding its default taskbar pins.
  The real `org.xfce.thunar` icon now resolves to the matching original Aqua
  file-manager artwork in both the taskbar and the launcher.
  Optional native X11 corner masks eliminate rectangular popup backing when
  XFWM4 runs without a compositor.
- Quick Home/Documents/Music links and the Places page now resolve XDG user
  directories correctly; missing directories can be created only after an
  explicit confirmation. The launcher returns to Apps when reopened.
- Improved the actual right-side GTK Control Panel with a dedicated Aqua
  header, more readable captions and better differentiated device-status
  surfaces; verified Linux volume, mute and real settings links are retained.
- Refined native Thunar into an Aqua file manager: one pearl breadcrumb field,
  compact functional navigation buttons, pastel-green sidebar, clean content
  and a restrained lime selection state instead of a wall of turquoise pills.
  A separate CSS overlay migrates exact previous versions but preserves custom
  user styling; the prior native GTK theme hash is whitelisted for backup-safe
  installation upgrades.
- Added 1024×768 actual XFWM4/Thunar screenshot checks in CI, as well as app
  ordering and managed CSS migration regression tests. Physical Mint XFCE
  acceptance remains pending; the v0.9.1 tag is unchanged.

## Unreleased — Windows XP Luna Explorer and Control Panel fidelity (3 November 2026)

- Replaced XP's narrow right-edge settings popup with a centered 2001-style
  Control Panel, offering functional Category/Classic View switching, eight
  Linux-backed applets and a blue sidebar with verified audio/network status.
- Start > Control Panel opens this window. My Documents/Pictures/Music respect
  XDG user directories; missing folders require confirmation before creation.
  Recent Documents now has a proper icon and date-ordered submenu.
- Changed only XP's Thunar controls to a warmer beige Explorer command bar,
  flatter address navigation and blue tasks-pane styling, while retaining
  genuine Thunar filesystem operations and exact CSS migration safeguards.
- Added 1600×900 / 1024×768 native XFWM4/Thunar acceptance captures, matching
  the actual applied window button layout, and replaced only XP's current
  screenshots from the passing GitHub Actions run `41691336596`.
- Remaining: the proprietary Explorer task-pane internals cannot be provided
  by GTK CSS; physical Mint XFCE confirmation is still needed.

## Unreleased — Cross-rice visual QA and native application coverage (3 November 2026)

- Fixed short initial XP Luna/Classic Control Panels and added a capture-time
  regression check for initially hidden volume/mute controls.
- Refined Classic settings to a 1998-style icon view; added functioning Windows 7
  Control Panel search and improved disabled-link contrast in Win7 and XP.
- Reduced Windows 10 taskbar search to a compact button opening existing app
  search; ChromeOS settings links have distinct navigation chevrons.
- Added disposable Xvfb/DBus workspace captures for six actual Thunar windows
  with per-rice GTK/icon styling and XFWM4 frames, rather than mockups.
- Fixed top-level Thunar menu-item spacing in Aero, XP, ChromeOS and Frutiger,
  preserving exact previous managed CSS blocks and unrelated user styles.
- Physical Mint/Plank acceptance and macOS equivalent captures remain open.
  The tagged v0.9.1 release and existing user settings are unchanged.

## Unreleased — ChromeOS Material You native fidelity (3 November 2026)

- Rebuilt the 56px ChromeOS shelf with native Gio pinned and running app icons,
  distinct launcher glyph, activity highlights and live hardware status.
- Added a left-anchored rounded application launcher with bounded 4-column
  grid, genuine installed applications, favorites, search and context pinning.
- Rebuilt right-side Quick Settings around verified output volume/mute,
  battery/network status, local date and real XFCE settings navigation;
  unavailable utilities are visibly disabled, and notifications are not faked.
- Shipped an original flowing pastel wallpaper, rounded XFWM4 button sprites
  and coordinated GTK3/Thunar controls, with a deterministic single-theme
  regeneration command and exact historical managed hashes for safe upgrades.
- Added focused ChromeOS tests, 1024×768 X11 capture checks and up-to-date
  screenshot gallery. Other Rices retain their own designs.
- The historical v0.9.1 release tag remains unchanged; use `main` for current work.

## Unreleased — Windows 10 native fidelity (3 November 2026)

- Replaced the oversized penguin wallpaper with an original deep-blue
  four-pane light composition, retaining a discreet Linux mascot signature;
  both Blue and Midnight retain the recognizable Windows 10 silhouette.
- Rebuilt the actual GTK Start menu into functional navigation, alphabetically
  grouped genuine Gio applications with search and Productivity/Explore tiles
  drawn only from installed applications and saved pins.
- Refined the 40px flat charcoal taskbar with a compact four-pane Linux Start
  badge, live search launcher, icon-only running windows and underline states.
- Built a right-edge Action Center with real settings launchers, honest
  notification scope, battery/network/audio details, verified output volume
  and mute, and disabled states for missing XFCE utilities.
- Updated dark/light GTK3, Thunar and sharp XFWM4 chrome, hover/focus states,
  and original sprite art. The other desktop families stay independent.
- Included exact historical Ten theme/icon hashes for safe backup-backed
  upgrades that never silently overwrite user customization.
- Added Windows 10 native 1024x768 screenshot checks and focused fidelity tests.
- The source-only work does not move the existing v0.9.1 release tag.

## Unreleased — Windows 98 / 2000 Classic fidelity (3 November 2026)

- Replaced the inaccurate ocean-style desktop with original solid Windows-98-era
  teal; the actual Linux shell now uses a slim 34px gray beveled taskbar and a
  19px pixel-art CRT/penguin Start emblem.
- Rebuilt the native Classic launcher as a dense cascading Programs, Favorites,
  Documents and Settings menu with real Gio apps, places, system tools, Find,
  Run, Help and session-confirmation shutdown; unavailable tools stay disabled.
- Drew original square XFWM4 navy/silver 27px titlebars and 22px buttons in
  normal, disabled, hovered and pressed states. Coordinated GTK3, Thunar and
  retro pixel menu controls retain native keyboard and accessibility semantics.
- Added narrowly scoped `--classic-only` asset rebuilding and precise original
  Classic asset hashes for backup-backed upgrades without overwriting user art.
- Added Classic 1024×768 native-X11 gallery regression and Classic-specific
  fidelity tests; 229 tests and all six native shell captures passed GitHub CI.
- Corrected the gallery validator's old PNG-size assumption: solid teal really
  produces smaller losslessly compressed screenshots, and proper screenshot
  dimensions, uniqueness and visible controls remain independently checked.
- The Classic Control Panel now has a functional navy 1998 caption and close
  button while preserving its real audio/network/device settings.
- Source improvements are not a retroactive change to the tagged v0.9.1 build.

## Unreleased — Frutiger Aero / Aqua World fidelity (3 November 2026)

- Hand-drew a deeper pearlescent cyan/lime taskbar, an organic water/leaf Start orb,
  the original glass XFWM4 window-frame/button states and corresponding GTK3/Thunar controls.
- Redesigned the **actual native GTK launcher** into a luminous `Your World`
  dashboard with real hardware status, working places/settings quick links,
  searchable three-column Gio application tiles, context pinning and Show more.
- Gave Frutiger its own icon theme inside Xvfb previews without changing the
  OS-wide GTK settings. Normalized unusual application icons to 48 px.
- Made Frutiger Control Panel larger and more useful, with visible device
  details, verified audio controls and a distinct refractive hardware card.
- Added trusted hashes for unmodified pre-Aqua theme/icon bundles so updates
  remain backup-backed; user-customized files continue to be protected.
- Extended native 1024×768 screenshot tests to Frutiger and verified all
  six non-macOS shells; refreshed only current gallery screenshots.
- No tagged release is moved by these source-only improvements. Physical
  Linux Mint XFCE and compositor-dependent rendering still need owner review.

## 0.9.1 — XP popup geometry and safer panel handoff (3 November 2026)

- Position the XP Luna Start menu against the actual mapped GTK window height, not its requested 560 px; shrink its program-list minimum height so the taskbar stays exposed.
- Add a native GTK application readiness action on taskbar map and verify it over the local D-Bus session before retiring the stock XFCE Panel.
- On a failed taskbar startup, stop the incomplete replacement and attempt to recover XFCE Panel and previously saved keyboard shortcuts. Preserve Plank ownership and the existing restore snapshots.
- Move post-apply and post-restore session reconciliation off the Hub's GTK main thread to avoid UI stalls during startup checks.
- Extend layout and session regressions, and gate the release on real virtual-X11 popup bounds, smoke tests and 12 fresh gallery captures.
- The owner accepted the 0.9.0 desktop designs and functionality, with the XP menu/taskbar overlap identified as the remaining issue. The 0.9.1 geometry fix still needs a final physical-machine check.

## 0.9.0 — Four reference-driven GTK/XFCE rice refinements (3 November 2026)

### Implemented, not rendered mockups
- **XP Luna:** independently built two-column Start menu, blue user band, light program list, bright blue Places column and real session-dialog controls; raised green Start button, glossy blue taskbar and live hardware controls.
- **Windows 98 / 2000:** a native cascading Programs menu populated from installed desktop applications, vertical navy brand rail, inset gray taskbar, square controls, genuine Find search and real system shortcuts.
- **ChromeOS:** 12 installed-app launcher tiles with search-on-demand, distinct left launcher, centered app shelf and rounded right-hand status cluster; icon-only running-window buttons and soft pastel control styling.
- **Frutiger Aero:** live Apps / Places / Settings pages with actual installed apps, folders and XFCE tools; luminous cyan glass, bright lime selected tabs and profile-specific hardware controls.
- More faithful native Thunar GTK3 chrome for each of those four: toolbars, menu bars, path controls, sidebars, selected rows and status bars. Thunar functionality remains Thunar; the reference mockups' custom file-dashboard layout is not claimed.
- 36 additional original folder, document, media, desktop, disk and network icons, preserved by the heritage asset generator; previous curated assets retained.
- Working, debounced **volume slider and mute toggle** with bounded PipeWire/PulseAudio commands and read-back verification. Battery and network detail text show real hardware state.
- Recognize exact 0.8 managed theme hashes and old 0.8 Thunar CSS blocks during upgrades; protect unrelated customizations and preserve the entire macOS implementation.
- Virtual X11 screenshot validation and additional migration, hardware, and icon regression tests. Physical Linux Mint XFCE/Plank/multi-monitor testing remains necessary before a stable release.

## 0.8.0 — Distinct identities, hardware tray and recoverable theme upgrades (3 November 2026)

### More individual non-macOS desktops

- Added **42 original vector icons** for file manager, folders, settings, browser, terminal, home and trash across Aero 7, Windows 10, XP Luna, Classic 98/2000, ChromeOS and Frutiger Aero; the previous clones are gone.
- Added **four independent heritage Start icons** and **66 status icons** for each desktop's battery, Wi-Fi/Ethernet and audio indicators.
- ChromeOS now has a centered app/search dashboard, not a recolored Windows 10 Start screen. Frutiger Aero has an independent organic-glass dashboard with quick places; XP, Classic, Aero and Ten retain appropriate distinct navigation.
- Extended per-rice notification-area geometry, colors, control surfaces, hover/focus states, spacing, and matching native Thunar treatments.

### Real tray behavior

- Show actual Linux battery percent/charging state from sysfs, aggregated over multiple batteries; hide the widget when no battery is present.
- Read active route, including VPN-underlay Wi-Fi fallback; read PipeWire/WirePlumber/PulseAudio volume and mute using bounded subprocesses.
- Launch installed XFCE settings utilities instead of fake toggles; the probes run on a background worker to keep GTK responsive.

### Theme conflict remediation and safety

- Automatically recognize *exact* official 0.6, 0.7.0 and 0.7.1 assets by embedded trusted Git blob hashes, then upgrade with **dated whole-theme backups**.
- Leave user-modified themes untouched by default; use the explicit, confirmed Hub **Repair local theme assets…** button or `macrice rice repair-assets STYLE` to back up and replace only that style's assets.
- Fail closed on symlinks, unmanaged paths and unexpected files. Keep macOS implementation, D-Bus IDs, session coordinators and user state compatible.

### Validation

- Full Python regression suite, six virtual-X11 shell smoke tests, native Wnck window-lifecycle test, and 12 real GTK menu/control captures in CI.
- Physical Mint XFCE battery/Plank/multi-monitor acceptance remains outstanding; release is a **pre-release** until confirmed.

## 0.7.1 — Consistent RiceBowl branding (3 November 2026)

- Standardized RiceBowl names across GTK window titles, sidebar icon, desktop entries, system tools, documentation and the package metadata (which previously reported 0.5.0rc2).
- GitHub repository now uses the canonical name `CopyPasteUser/RiceBowl`; old `CopyPasteUser/RiceHub` URLs redirect.
- Updated visible GTK/icon theme names and the accessible labels in original SVG artwork; retained the existing RiceHub-prefixed theme directories as compatibility identifiers.
- Safely recognize exact old theme metadata and managed autostart entries. Back up original theme indices and SVG metadata before an atomic label-only migration; customized artwork and entries are not overwritten.
- Updated the source asset generators and added migration regression tests. This maintenance release supersedes v0.7.0 without changing the working macOS rice.

## 0.7.0 — RiceBowl identity and themed controls (3 November 2026)

### Desktop experience
- Introduced the RiceBowl name, original rice-bowl SVG application icon and user-local `ricebowl` desktop/CLI launcher.
- Refined live system-control panels for XP Luna, Windows 98/2000 Classic, ChromeOS and Frutiger Aero. The controls expose actual available XFCE/system settings applications and disable unavailable commands.
- Added differentiated Thunar toolbars, location controls and sidebars for **all six non-macOS** desktop families (Aero 7, Ten, XP, Classic, ChromeOS, Frutiger). Existing 0.6 managed CSS is recognized during upgrades, while modifications outside the owned block remain untouched.
- Preserved the existing macOS implementation and dock behavior.

### Upgrade safety
- The `ricehub` and `macrice` commands, user state paths, managed startup entries and D-Bus shell identifiers remain compatible.
- The old RiceHub desktop shortcut stays installed but is hidden from the app menu to avoid duplicates.
- Added regression tests for new/legacy launcher coexistence, Thunar migration, custom CSS protection and SVG validity.
- Repository rename is **not complete**. Until owner-side GitHub Settings changes the name, the canonical clone URL remains `CopyPasteUser/RiceBowl`.

### Validation
- Automated Python tests and isolated GTK/X11 checks are managed by the repository's GitHub Actions workflow; results must be checked per commit.
- Physical Linux Mint XFCE multi-monitor, compositor, fast profile switching and Plank-autostart acceptance remain open.

## 0.6.0 — Seven installable rices (2 November 2026)

### New desktop families

- **Windows XP Luna:** blue taskbar, green Penguin Start, original grassland wallpaper, searchable applications and a native control panel.
- **Windows 98 / 2000 Classic:** square GTK/WM chrome, compact gray taskbar, narrow branded Start menu and original teal landscape.
- **ChromeOS:** pastel wallpaper, centered native shelf and launcher, pinned applications and XFCE-backed quick settings.
- **Y2K / Frutiger Aero:** original eco-futurist wallpaper, aqua GTK/window theme, translucent-looking taskbar and searchable application menu.
- All four ship original installable GTK3 and XFWM4 themes, icons, wallpaper artwork, themed Thunar styles and persistent pin files. The existing concept dialogs remain read-only.

### Session, safety and compatibility

- Apply, restore and switch among **seven** families using the single RiceHub session coordinator.
- Backups use schema 5 for additional autostart entries; supported older schema 1–4 snapshots remain readable.
- `Super_L` toggles the active rice's menu, `Control_R` its settings surface. The previous XFCE shortcuts remain recoverable.
- Inactive RiceHub taskbars are closed during handoff; Plank is reserved for the macOS rice. Third-party panel processes are not killed by unverified PID.
- Independent taskbar pin files prevent preferences from leaking between rices.
- Preserved the native Wnck window-lifecycle fix that prevents shell crashes after applications close.

### Verification

- 146 Python tests pass (one hardware-only test skipped in a non-X11 local run).
- GitHub Actions executes native GTK startup, search, menu/action toggles, real Wnck disposal and screenshot capture under isolated X11.
- Eight real GTK menu/controls screenshots are in [`screenshots/`](screenshots/), and the [README](README.md) shows each new style.

### Known limitations

- The 0.6 release has CI/virtual-X11 acceptance, not a completed physical Linux Mint XFCE hardware matrix. Before calling the project 1.0, verify login/relogin, multi-monitor, accessibility, compositor differences, rapid switching and repeat CADCraft close/reopen on physical hardware.
- No true compositor blur; native tray icons depend on host services. Legacy XEmbed tray is not supported.
- Windows 11 and Liquid Glass presets are not planned.
