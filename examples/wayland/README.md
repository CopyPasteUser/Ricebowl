# Wayland Creator examples and Luna preview

## XP Luna for native Wayland (schema v12)

[`xp-luna.json`](xp-luna.json) is a **third, opt-in rice** inspired by RiceBowl's
existing X11 Luna presentation. It uses RiceBowl's own `luna-hills` wallpaper,
a cobalt bottom taskbar, **independently green rounded `start` launcher**,
separately blue active tasks, pale Start-menu body with cobalt heading,
an original **two-column Start menu** (ivory programs, pale-blue system links,
blue session-action footer), and responsive desktop shortcuts.
The green launcher and five-color native menu are reusable schema-v12 primitives,
not special-case code for this rice. Launcher hit testing, real task activation,
app discovery, lock and logout retain their normal shared behavior.

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

### Native two-column Start menu (source preview)

The generic schema-v12 `menu.presentation: "split"` displays the first two
validated action groups side by side, plus a separate third group with at most
two real session actions. It shares the existing app catalogue, search,
saved-action pinning, pointer geometry, keyboard navigation and AT-SPI action
dispatcher; no recipe can inject commands. Smaller outputs retain the readable
compact paged menu. Older tab/sidebar recipes remain unchanged. CI captures
`xp-luna.png` (desktop) and `xp-luna-menu.png` (opened native Start) directly
from headless labwc with `grim`, as actual Wayland framebuffer evidence.

The screen remains 320×304 logical pixels in this structural sprint.
Enlarging the menu, refining iconography and validating it with a physical
ThinkPad are separate visual-fidelity tasks.

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
icons use the current RicePlate pictograms, native fonts are not XP's fonts,
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
