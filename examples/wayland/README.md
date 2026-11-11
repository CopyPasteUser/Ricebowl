# Wayland Creator examples and Luna preview

## XP Luna for native Wayland (schema v12)

[`xp-luna.json`](xp-luna.json) is a **third, opt-in rice** inspired by RiceBowl's
existing X11 Luna presentation. It uses RiceBowl's own `luna-hills` wallpaper,
a cobalt bottom taskbar, **independently green rounded `start` launcher**,
separately blue active tasks, pale Start-menu body with cobalt heading,
sidebar Programs/System/Session categories, and responsive desktop shortcuts.
The green launcher and five-color native menu are reusable schema-v12 primitives,
not special-case code for this rice. Launcher hit testing, real task activation,
app discovery, lock and logout retain their normal shared behavior.

### XP Luna next sprint: real two-column Start menu (native preview)

[`xp-luna-columns.json`](xp-luna-columns.json) is the new **opt-in successor**
to the original `xp-luna` recipe. On sufficiently large Wayland outputs its
Start menu now has two *simultaneously interactive* panes: a cream programs
area on the left (All Programs, Terminal and installed applications) and a
pale-blue places/system/session area on the right (My Documents, My Computer,
RiceSpice settings, notifications, lock, logout). The selected row uses the cobalt header color with white text.
These are real, allowlisted application/system actions, not decorative labels.
The narrow system shelf uses fitting on-screen labels (for example `Settings`
and `Log out (N/A)`), but retains the full canonical action names in native
search, dispatch and accessibility. A missing session logout is not presented
as an available command.

The reusable `menu.presentation = "columns"` variant is accepted **only
with schema v12 and a bounded three-group layout**; right-hand groups cannot
supply arbitrary content or more than four actions each. The opt-in Luna places
shelf uses shorter native rows so every action and the footer remain reachable. The same computed
tiles drive painting and pointer hits. Left/right keyboard navigation crosses
columns, search and saved actions continue using the shared engine, and
small screens fall back to the full-resolution paged menu. AT-SPI exposes
visible actions rather than hidden tabs. Python Creator validation, schema,
catalog and Rust agree on the new variant.

See the [real headless Wayland Luna screenshots](../../screenshots/wayland/README.md):
desktop with the separately running original `swaybg` wallpaper and the opened
two-column native Start menu. These are CI captures, not hardware acceptance.

The original `xp-luna` rice and any existing private imported recipe remain
unchanged. The preparation script imports `xp-luna-columns` under a new ID
and the 120-second TTY test starts only that preview. No display-manager,
autologin, package, or XFCE configuration is changed. Existing installed
`.deb` versions are **not** compatible with this additional menu variant;
use the rebuilt local native binary via the scripts below.

### Opt-in compositor-owned Luna window chrome

An explicit **two-column recipe with a validated menu palette** now also
receives a matching blue/ivory **labwc server-side titlebar**, with a vertical
cobalt gradient, distinct unfocused frame, legible title text and bounded
window-button geometry. The existing `xp-luna`, tabs and sidebar recipes keep
their previous compositor theme. This is a generic use of the shared palette,
not a new arbitrary theme-file path or a proprietary XP visual asset.

RiceBowl writes the compiled `themerc-override` only into its disposable,
owner-private labwc `--config-dir`. Supervised **live apply and restore** update
the private menu and window chrome together; on failures both previous files
are restored and labwc is asked to reconfigure again. Nothing touches XFCE,
`~/.config/labwc`, the system's GTK/Qt themes or SDDM. Toolkit-owned
**client-side decorations** are not overridden; only the window frames that
labwc itself draws participate. Headless CI additionally captures an actual
XWayland window before and after the private reconfigure. Physical-device
focus, dragging and mixed-DPI acceptance are still pending.

### Luna taskbar polish (native Rust preview)

An explicitly decorated schema-v12 launcher now opts into a reusable taskbar
surface treatment: a gentle blue vertical highlight/shadow, a brighter
right-side status/clock shelf, a green beveled Start capsule and distinct
raised/inset task buttons. Layout geometry, hit-testing, keyboard focus,
screen-reader actions, live task activation and XFCE remain unchanged.
Undecorated recipes continue using the original pixel-identical flat bar.
This is rendering only; it does not theme unrelated GTK/Qt windows or install
new services. Rust pixel regression tests cover both routes, the status shelf,
active tasks and narrow geometry.

### Luna visual fidelity pass · native Start menu and taskbar

The existing schema-v12 `xp-luna-columns` rice now uses additional **original
Rust-painted chrome**, without a licensed Windows image dependency. The
two-column Start menu has a graduated cobalt account bar, a custom RiceBowl
account tile, a subtle ivory/azure divider, its own small program/system
glyphs and a bevelled **Close** control in the existing clickable footer.
The real Find/Saved header buttons also receive matching raised states; no
fake or inert power controls were introduced. The green Start capsule gets a
stronger highlight, darker lower edge and an original four-tile emblem.

The Luna system tray now draws small connected-network and speaker pictograms
with disconnected/muted badges instead of wide textual status placeholders;
these remain the same accessible network/audio actions.

The same existing validated menu actions, keyboard navigation, pointer hits,
search, pinned actions, accessibility labels and private rollback paths stay
in use. On logical outputs at least 1280px wide, Luna-columns menus present
at **400×380**; on outputs at least 1600px wide with enough free height,
**480×456**. Other menus retain 320×304, and 1024px/rotated/small displays
retain the existing original-size or readable compact behavior. Rendering
and input use the same inverse scale. This is nearest-neighbor presentation
of the native 320×304 canvas; typography and controls still need a fully native
high-resolution pass before claiming pixel-level historical fidelity.

All decorative dimensions remain data-only or renderer-owned; no global
desktop/theme changes or proprietary Microsoft artwork are installed.

### Optional portable text font · Creator visual assets

The `xp-luna-columns` recipe selects original compiled-in 48×48 Luna desktop
pictograms (`builtin-luna`) for Programs, Terminal and Lock. The schema-v12
choice is available in Creator, and data-only RicePack exports need no private
PNG for these icons. Other recipes and explicitly imported icons remain
unchanged. These are RiceBowl originals, not Microsoft assets.

The same recipe now opts into `builtin-luna-ui`: an unmodified, embedded
Liberation Sans TrueType face (SIL Open Font License 1.1; license in
`assets/fonts/LiberationSans-LICENSE.txt`). Unlike the previous bold 8×8
bitmap lettering, this is anti-aliased, proportionally advanced text. It
works without a private font import or host Fontconfig setup and is available
as a schema-v12 Creator font choice. Earlier recipes still use their original
fonts unless explicitly changed.

Creator can already import a locally owned TrueType `.ttf` (maximum 1 MiB)
with declared attribution into an owner-private, SHA-256-pinned collection.
Select the face in **Visual asset library → Text font**, save a new immutable
draft, then render it in isolated native labwc. The selection travels with a
verified RicePack v4 export; it does not install fonts globally. Native
RicePlate now uses that same selected face for panel, Start menu, desktop
shortcut labels, widgets, the calendar popup and the volume OSD. The calendar
and OSD retain their legacy 8px bitmap text unless an owner-private face is
explicitly selected; other rices keep pixel-identical auxiliary typography.
Additional Unicode glyphs are cached lazily with
a fixed limit, rather than being reduced to a small pre-rendered Latin set.
Absent glyphs still use a readable replacement. Full complex-script shaping,
automatic font import without user attribution, a Waybar custom-face path and
third-party GTK/Qt window fonts are **not** yet implemented. Read-only
Fontconfig discovery and a Creator installed-font chooser are available;
import still requires explicit user review. The default built-in bitmap font
and legacy recipes retain their former behavior.

**Existing 0.1.0 preview `.deb` packages still contain an older native
binary.** Test through the source build script below. Do not overwrite the
installed default session or disable automatic XFCE login to try this style.

For the ThinkPad's existing XFCE/X11 + SDDM autologin, this **source-preview
route does not install/replace a display manager, change the default session or
modify XFCE settings**. Use the graphical XFCE terminal for compilation:

```sh
cd ~/RiceBowl-Wayland-Test
git pull --ff-only
bash scripts/prepare_wayland_xp_luna.sh
```

Then switch to a text console (e.g. Ctrl+Alt+F3), sign in and type only:

```sh
bash ~/RiceBowl-Wayland-Test/scripts/try_wayland_xp_luna.sh
```

The preview ends after 120 seconds and returns to the TTY. Switch back to XFCE
with Ctrl+Alt+F1 on this machine. Importing the recipe does not activate it.
Re-run preparation only if updating the source or Rust binary; existing private
recipe IDs are never overwritten. Check its semantic changes before replacing
an imported copy. The current installed `.deb` previews predate schema v12;
**start this version from the repository script**, not the older installed
`ricebowl-wayland-app`, until the packages are rebuilt and updated.

Boundaries: this is the first functional native Luna shell composition, not an
XP replica. Client window titlebars remain under labwc/GTK/Qt control; desktop
icons are RiceBowl originals rather than proprietary XP icons, native fonts are not XP's fonts,
and physical-device input, power, multimonitor and sleep tests are still open.
No Microsoft logo, proprietary icon collection or Bliss photograph is bundled.

These are **real schema-v5 recipes**, authored only with the public declarative
RicePlate contract. They are design **demonstrators**, not Windows artwork or
a promise of 1:1 desktop fidelity. Both are offline and use existing RiceBowl
wallpapers; neither adds a shell daemon or executable extension.

| Rice | Direction | Native layout | Wallpaper | Actions |
| --- | --- | --- | --- | --- |
| `heritage-workstation` | Classic desktop / OS-inspired | Bottom panel, square tasks, left desktop shortcuts | Bundled `classic-teal` | Applications, terminal, lock; logout in root menu |
| `orbit-atelier` | Original evening-workspace concept | Tall top panel, separate central task area, right-area shortcuts | Bundled `aurora-night` | Same known Linux action IDs, different composition |

## Modern schema-v10 Creator acceptance pair

These two **additional** data-only examples exercise the currently implemented
shared status/action component library and real v10 design-token renderer.
They intentionally have different structural layouts, menu navigation,
typography, state colors and spacing. They are not pixel-accurate clones of a reference
OS or proof of physical-device input acceptance.

| Rice | Distinguishing composition | Real bindings | Design tokens |
| --- | --- | --- | --- |
| `heritage-modern-v10` | Compact square-bottom taskbar, tabbed menu, left grid shortcuts, classic-style desktop text/status | Network on desktop, live panel audio status, guarded Wi-Fi button | Regular compact text, 2px spacing, restrained focus/hover colors |
| `orbit-studio-v10` | Tall upper panel, nested launcher/action group, sidebar menu, right-side shortcuts and separate desktop status | Live native network/audio, guarded Wi-Fi button | Bold 2× text, 12px spacing and contrasting hover/focus/disabled colors |

Both are validated, exported as non-executable RicePacks and included in the
native CI headless gallery at 1024×768, 1366×768, 1920×1080 and scale 1.25.
Waybar renders honest disabled feedback for its unsupported interactive
controls; it never claims to implement native desktop widgets.

```sh
ricebowl de recipe-import --recipe "$PWD/examples/wayland/heritage-modern-v10.json"
ricebowl de recipe-import --recipe "$PWD/examples/wayland/orbit-studio-v10.json"
ricebowl de review --recipe heritage-modern-v10 --json
ricebowl de review --recipe orbit-studio-v10 --json
ricebowl de render --recipe orbit-studio-v10 --output "$PWD/orbit-modern-preview.png" --json
```

The import does **not** activate either rice. For active changes, first review
the semantic SHA and explicitly use the existing `creator-stage` or supervised
`creator-live-apply` workflow; retain `creator-rollback`/`creator-live-restore`.
The headless screenshots verify renderer output, not clicking Wi-Fi on a
physical device, external windows or an actual suspend/resume cycle.

`quick-controls.json` is a separate schema-v4 **native RiceSpice prototype**.
Import it using `ricebowl de recipe-import --recipe "$PWD/examples/wayland/quick-controls.json"`,
then explicitly preview it with `ricebowl de start --nested --panel native --recipe quick-controls`.
Open its native start menu and choose **Quick actions** to toggle Wi-Fi radio,
mute/unmute sound or change the default sink volume. The commands use existing
user-session NetworkManager/WirePlumber permissions: refused or unavailable
operations show an error in the menu. **Wi-Fi toggling can disconnect the
session**; test locally when safe. The **Session → Notifications** entry opens
the first native RicePop active-alert view. Up/Down, Tab and PageUp/PageDown
navigate; Enter/Delete dismiss the selected active alert, `R` refreshes and
Escape/Backspace returns to the main menu. Pointer users select a row and
explicitly choose Dismiss. Loading, empty, Mako-unavailable and refusal states
are shown without inventing notifications. No message content is saved or
replayed, and the underlying Mako owner is unchanged. This is not yet a full
notification-history UI or system OSD. The Waybar fallback hides native-only
entries.

## Safe panel action buttons (schema v6)

The shared fixture `tests/fixtures/riceplate-actions-v6.json` demonstrates the
first **generic interactive panel layout leaf**. A wide layout places a real
**Terminal** button between the launcher and tasks and a separate **Settings**
button before the clock. The compact layout keeps only Settings; the native
renderer automatically changes geometry at the selected breakpoint, while
Waybar compiles for an explicitly selected width.

Use `{ "type": "action", "id": "settings", "label": "Settings" }` inside any
schema-v6 `panel.layout` or `responsive.compact_layout` region. Valid IDs are
`applications`, `terminal`, `settings`, `lock`. Labels must contain 1–16 safe
ASCII characters; one ID may occur once per layout and retains the same label
across wide/compact variants. Native buttons support pointer, keyboard and
AT-SPI actions. Waybar uses compiler-owned fixed commands; recipe-supplied
executable paths, flags or scripts are never accepted.

Inspect the contract with `ricebowl de catalog --json`, review the example
using `ricebowl de review --recipe "$PWD/tests/fixtures/riceplate-actions-v6.json"
--json`, or render it in a nested Wayland session using `ricebowl de render
--recipe "$PWD/tests/fixtures/riceplate-actions-v6.json" --output
"$PWD/action-preview.png" --json`. Rendering never changes an active desktop.

## Validate, inspect and render

From the RiceBowl repository root on Linux:

```sh
ricebowl de recipe-import --recipe "$PWD/examples/wayland/heritage-workstation.json"
ricebowl de recipe-import --recipe "$PWD/examples/wayland/orbit-atelier.json"
ricebowl de review --recipe heritage-workstation --json
ricebowl de review --recipe orbit-atelier --json

# Needs unprivileged labwc, wlr-randr, swaybg, grim and native riceplate-native.
ricebowl de render --recipe heritage-workstation --output "$PWD/heritage-preview.png" --width 1366 --height 768 --json
ricebowl de render --recipe orbit-atelier --output "$PWD/orbit-preview.png" --width 1366 --height 768 --json
```

`recipe-import` refuses existing IDs and does not apply anything. `de render`
refuses an existing output and runs an isolated headless compositor; it does
not change the logged-in desktop. CI renders **both recipes** at 1024×768,
1366×768, 1920×1080 and 1366×768 at 1.25 scale and archives the PNGs with
per-capture dimensions, hashes, recipe fingerprints and diagnostic regions.
Use `de visual-compare` to compare those captures with your own licensed
reference image; the comparator cannot certify aesthetic or functional parity.

To stage one of the imported rices for the **next opt-in Wayland session**,
copy the `semantic_sha256` from its `de review --json` result and explicitly
run `ricebowl de creator-stage --recipe orbit-atelier --expect-sha256 HASH`.
Check `de creator-status` and undo with `de creator-rollback`. The legacy XFCE
session is not changed.

## Verified behavior boundary

The same native implementation handles panel launcher, discovered Wayland
tasks, minute clock and the three desktop shortcut action IDs. The compositor
menu exposes the four declared, allowlisted actions. On smaller outputs,
RicePlate recomputes its panel layout and reflows shortcuts into the visible
area. No generated code runs. The static `label` nodes are just text—not
buttons; they intentionally have no click behavior.

**Still unsupported:** custom start-menu visuals, keyboard focus/navigation
for desktop shortcuts, drag/drop repositioning, independent app window
decorations, real multi-monitor ownership and hotplug acceptance, hardware
settings in RiceSpice, the full active-desktop transaction, and visually
accurate emulation of an entire historical OS. CI cannot substitute for a
user's physical Wayland login/device acceptance.

## An AI authoring exercise

1. Copy one JSON recipe to an owner-controlled private file; change its `id`
   and `name`, then map a screenshot's regions to known `launcher`, `tasks`,
   `clock`, `label`, `group` and `gap` primitives.
2. Use `de catalog --json` / `de creator-api --json` to discover limits and
   supported actions. Record each unsupported reference control rather than
   inventing an action handler.
3. Use `de review --recipe /absolute/draft.json --compare orbit-atelier --json`
   for semantic changes, followed by isolated `de render` previews at several
   sizes and `de visual-compare` with your reference capture.
4. If the draft passes review, import it under a new ID, inspect its hash and
   explicitly stage it; use rollback if the next Wayland login is unsuitable.

Everything after obtaining the original mockup can run without AI or network.

### Luna native places shelf · fidelity milestone

The `xp-luna-columns` Start menu now offers **My Documents** and **My Computer**
without removing Settings, Notifications, Lock or Log out. Both are fixed,
validated menu actions that dispatch to the existing Gio file handler (never
to a shell or a recipe-supplied command). Documents respects the user's XDG
Documents directory when it exists and falls back to `~/Documents` or Home;
Computer opens the filesystem root as a reliable Linux fallback rather than
pretending that a proprietary Windows device browser is available.

The native Rust menu uses six bounded, mouse-accessible right-column rows
with shared keyboard/AT-SPI action IDs. The plain labwc/Waybar root-menu
fallback still omits these native-only location actions. The headless CI must
validate the revised right shelf, including its bottom-row hit boxes, before
merge. The 1:1 fidelity target still requires a true drives/devices view,
actual high-resolution rendering, taskbar and desktop shell details, and
physical-device acceptance; no Windows assets are bundled.
