# Declarative Wayland Creator — implemented contract (13 November 2026)

This document describes **implemented** authoring operations on recipe schema v1–v12.
It is not a claim that every GTK, Qt or compositor window can be themed or laid out.

## Architecture

- **Core parser:** `macrice/de/recipes.py` is the authoritative data-only validator.
  The current Rust RicePlate runtime consumes the existing recipe contract; no new
  schema version or second renderer was introduced by this sprint.
- **Discovery:** `ricebowl de catalog --json` (catalog v14) exposes a
  `authoring_palette` of bounded panel/desktop primitives, allowed IDs,
  required native/fallback capabilities and accessibility intent.
  `ricebowl de creator-schema --recipe ID --json` supplies the per-recipe
  edit JSON Schema. The parser must still validate cross-field uniqueness.
- **Structure:** `creator_structure.edit_layout` supports `add` with
  `target_index`, `duplicate` for valid nodes, wrap/ungroup, reorder and
  replace. `transfer_layout` atomically moves nodes between lanes.
  `clone_layout_mode` copies wide/compact layouts without changing a source.
  All proposals remain detached until an explicit versioned save.
- **Desktop:** `creator_layout.add_layer` can author all seven fixed
  desktop shortcut actions; output dimensions are optional inputs to collision-
  free placement. Widgets and shortcut actions are bounded by the parser.
- **Responsive:** three panel lanes for **each** independent wide/compact mode,
  one width breakpoint (480–1440 logical px), optional compact hiding for
  desktop widgets. Arbitrary nested grids, vertical panels, CSS, scripts and
  runtime-selectable custom layouts are **not** in this schema.
- **Versioning:** `preview_revision` produces a read-only semantic preflight.
  `save_revision` checks source/draft fingerprints before publishing a new
  private version. `version_history`, restore/fork and recovery are separate
  explicit operations; editing never changes the active Wayland session.
- **RicePacks:** export/inspection/import remain script-free, strict-entry,
  checksum-verified, owner-private and non-activating. `inspect_pack` now
  reports embedded assets and whether native desktop layers are needed.
  It **does not** claim the target host has labwc, RicePlate or providers.

## Two runnable recipes

- `examples/wayland/heritage-modern-v10.json`: bottom panel, classic task
  hierarchy, centered WORKSTATION caption, audio-mute native control and a
  compact layout distinct from its wide layout.
- `examples/wayland/orbit-studio-v10.json`: top panel, grouped launcher,
  centered FOCUS MODE caption with tasks, sidebar menu, large bold typography,
  separately authored compact layout.

Both examples use schema **v10** and are parsed and exported by the same native
recipe and RicePack paths. Waybar is only a partial fallback for native-only
controls. Screenshots from a genuine compositor are required for visual sign-off.

## Validation and handoff

Run `python3 -m unittest tests.test_creator_layout tests.test_creator_structure
tests.test_de_catalog tests.test_de_creator_examples` and the full project
test suite. For real visual acceptance, run `ricebowl de render-matrix` on
each edited recipe in an environment with labwc, RicePlate and capture tools,
then inspect the archive and compare real captures. Do not label a schematic
Creator canvas as native screenshot evidence.

**Rust handoff (not implemented here):** a future schema revision must first
specify and implement native support for vertical/floating panels, per-output
breakpoints, reusable component templates beyond status/action bindings,
container alignment/overflow and popup/menu trees. Keep bindings allowlisted,
focus/AT-SPI semantics explicit and monitor the memory budget before bumping
the recipe schema. This sprint intentionally did not modify Rust, session
management, global roadmaps or README files.
