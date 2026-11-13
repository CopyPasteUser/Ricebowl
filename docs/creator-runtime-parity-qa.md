# Creator → native RicePlate parity and QA (13 November 2026)

This document tracks **implemented** capabilities, not assumed screenshot fidelity.
The companion read-only inventory is `ricebowl de creator-parity --recipe RECIPE --json`
(or `python3 -m macrice.de.creator_runtime_parity RECIPE`) and uses the **same
validated semantic manifest** as Creator review and staging.
No new recipe schema, renderer, dynamic script runner or background daemon is added.

## Capability matrix

| Component | Python validation | Rust native parser | Native UI / interaction contract | Waybar fallback | Remaining QA |
|---|---|---|---|---|---|
| Panel launcher and tasks | v1+ sections / v3+ layout, unique IDs | `recipe::parse` + `layout` / `hit` | launcher menu; activate/minimize/page tasks | partial interactive | actual focus/window cycling on labwc |
| Clock and calendar | width + widget ID | native `Widget::Clock` | live clock, popup on demand | time indicator | keyboard focus from panel |
| Network, audio, battery | named allowlisted status IDs | native status variants | read-only real providers or unavailable | status modules | device/provider/error state |
| Tray | singleton widget | native `Widget::Tray` | experimental SNI and popup | host tray | DBusMenu and keyboard focus incomplete |
| Group / gap / divider / label | nested v3+, bounded children/depth | `expand_layout` | flattened native panel geometry, non-interactive | flattened / CSS | widths and overflow at fractional scale |
| Panel actions | v6+ fixed action IDs, safe label | `PanelAction` | permitted action, pointer/keyboard, named button | fixed allowlisted command | accessibility semantics under real AT |
| Panel controls | v7+ four permitted bindings | `PanelAction(control)` | provider-gated status + pending/success/failure | disabled/status only | unavailable/denied/timeout |
| Reusable component references | v9+ status/action bindings | `ComponentInput` expansion | common provider/action dispatcher | panel subset | conditional action state/focus |
| Menu (tabs / sidebar / columns) | v4+, v6+ presentations | `NativeMenu` | bounded groups, fixed actions | labwc root menu | actual menu focus and source lists |
| Desktop shortcut | v5+, fixed icon actions | `DesktopIcon` | native per-output layer surface, keyboard and pointer | unsupported | compositor focus, drag, hotplug |
| Desktop widget | v8+, v9+ component refs | `DesktopComposition` | read-only system state or named action | unsupported | real layout, AT-SPI and clipping |
| Appearance and artwork | v10+ tokens, v11+ content-addressed assets | parser + private assets | native palette/font/icons | partial/defaults | capture typography and icon scaling |
| Wide + compact modes | v4+ bounded breakpoint | `compact` switch in `layout` | native per-output layout reflow | regenerate config on output event | narrow screens, fractional scale, two outputs |

**Evidence levels are distinct.** The inventory verifies Python parsing, references
and allowlisted action contracts but explicitly marks Rust parser execution,
actual native rendering and interactive/AT testing as **not performed**.
The existing Rust test suite and native labwc screenshot runners supply separate
execution evidence. Neither proves physical monitor, keyboard or suspend behavior.

## Deterministic review matrix

The `creator_runtime_parity` report enumerates every declared panel node
(including independent compact mode), menu action, desktop shortcut and desktop
widget. Each row carries its JSON pointer, effective binding, label, interaction
role, expected accessibility role, native/fallback support and state contract.
No row may advertise arbitrary execution: only the parser's fixed IDs pass.
Decorative and read-only nodes cannot be presented as actionable buttons.
The report separately identifies **known keyboard-access gaps** on the
clock/popup entry and native SNI tray; an interactive pointer target alone
is not proof of keyboard accessibility.

Five *logical* output contracts are inspected: 640×480, 1366×768,
1920×1080, 1366×768 at 1.25 scale, and a second 1024×768 output.
Declared shortcuts/widgets outside a logical output or overlapping the panel
and overlapping icon/widget rectangles are warnings, **not proof that the compositor
ultimately clips them**: RicePlate
may reflow on hotplug or output resize. A real compositor capture is still
required to confirm the final position, visible pixels and interaction targets.

The existing `visual_qa.compare` now checks declared v8+ desktop-widget
rectangles too (200×96 logical px), reporting `widget_outside_output` and
`widget_overlaps_panel` alongside the established icon diagnostics. It does
not alter screenshot pixels, mutate a recipe or claim the screenshot proves
interactive focus/accessibility.

## Two non-duplicated demonstrators

Reuse the two independent **schema v10** recipes from PR #347:

- `examples/wayland/heritage-composer-v10.json`: bottom taskbar, familiar
  desktop shortcuts and text/status widgets, one shared Wi-Fi component plus
  real audio-mute control and different compact layout.
- `examples/wayland/orbit-composer-v10.json`: top grouped panel,
  alternate focus-workflow labels and sidebar menu, shared Wi-Fi component
  and a different wide/compact structure.

Both pass the same validated recipe/asset and activation contracts; neither
contains a custom command. No second copy of these recipes is maintained.
Screenshot smoke can select only the two composers using
`python3 scripts/verify_wayland_creator_examples.py --output-dir /ABSOLUTE/EMPTY/DIR --composers`.
This runs the **existing** native labwc renderer and reports hashed PNG
receipts, not a synthetic Creator canvas. It must run unprivileged with its
documented dependencies available.

## Verification boundaries and open gaps

Run Python regression discovery and `cargo test --locked --manifest-path
components/riceplate-wayland/Cargo.toml` in CI. Run the composer capture
runner in native headless labwc. Separately verify real pointer/keyboard
focus, AT-SPI, multiple physical monitors, display hotplug, input-method
integration, login/logout and rollback. Those remain **unverified** by
contract inspection or headless capture. Vertical/floating panels, arbitrary
widget script execution and generalized tree/layout composition remain
unsupported, not hidden in a cosmetic editor.
