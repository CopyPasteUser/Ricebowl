# RiceBowl — contributor and agent instructions

These rules apply to changes in this repository. Follow existing behavior and
migration contracts unless a task explicitly authorizes changing them.

## Product north star

RiceBowl is becoming a lightweight, modular, **floating Wayland desktop
environment built around upstream labwc** and a practical **desktop-creation
framework**. It must be unusually easy to:

1. Re-create the visual identity, structure and interactions of another
   operating system as closely as Linux and its APIs reasonably allow.
2. Turn an AI-generated UI mockup, reference screenshot or original design
   into a **real, usable rice**, without implementing a new desktop shell each
   time.
3. Create and share entirely original desktop experiences through the same
   authoring system.

This is a core product requirement, not an optional cosmetic enhancement.
OS-inspired artwork must be original or appropriately licensed; do not copy
proprietary logos, icon sets or bundled system assets.

## Architecture: one engine, many genuinely distinct rices

- **RiceBowl core owns functionality:** session/recovery, windows, desktop,
  panels, launchers, settings, notifications, device integration, accessibility
  and the safe lifecycle of optional components.
- **A rice owns presentation and supported interaction policy:** component
  choice, layout and hierarchy, desktop/panel/menu structure, visual tokens,
  assets, motions and allowed user workflows. Do not reduce rices to palette
  swaps or force distinct historical UIs into one generic shared layout.
- **Use versioned, validated, data-first recipes** for common authoring needs.
  Make compositions, reusable UI primitives, bounded assets and explicitly
  supported action/state bindings declarative wherever feasible. Do not execute
  untrusted scripts or arbitrary AI-generated code from rice packs.
- **Shared backends, different frontends:** real Linux capabilities stay in
  shared adapters; a profile may render its own distinct controls. Controls
  must reflect real state, including loading, unavailable, denied and error
  states; never fake connectivity or working settings.
- **Keep lightness architectural:** load only the selected rice and required
  components, prefer event-driven state to resident polling, avoid duplicate
  daemons and measure startup, settled PSS/CPU and interaction latency before
  promising numerical savings.
- **Honor platform limits:** labwc owns window management/compositing; Wayland,
  toolkits and third-party client-side decorations have constraints. Support
  GTK/Qt theming where feasible without misrepresenting 100% cross-app visual
  control. Do not fork labwc solely for cosmetic fidelity.
- **Keep the existing XFCE/X11 path operational:** the new Wayland/labwc path
  is opt-in until tested and accepted. Do not silently replace desktop
  services, global defaults or user configuration. Provide rollback.

The eventual Wayland shell should use Rust for resident performance-sensitive
components where justified. Existing tested Python/X11 code is not to be
discarded or rewritten speculatively.

## Mockup-to-rice authoring contract

When implementing a rice from a reference, use this repeatable workflow:

1. Decompose the reference into shell regions, reusable components, layout
   constraints, typography, original/licensed assets, states and interactions.
2. Map those parts onto a versioned rice recipe and the common component
   library. If a genuinely necessary primitive is missing, implement it once
   in the core with tests, rather than embedding a duplicate shell in a rice.
3. Bind visible actions to supported real system capabilities, with honest
   unsupported/error behavior, keyboard access and sensible smaller-screen
   layout rules.
4. Provide a preview before applying; validate at more than one screen size,
   verify input/focus and app-window behavior, and preserve a safe restore
   path. Explicitly document unavoidable platform differences.
5. Package/export using validated data and assets with provenance. An AI
   assistant may help generate these files; running AI inference, a cloud
   account or a proprietary service must **not** be required to use RiceBowl.

The goal is a low-friction, documented **mockup → component mapping → rice
recipe/assets → preview → test → apply/restore** path. One-click conversion of
an arbitrary image is not a current implemented feature and must never be
claimed as such.

## Parallel Wayland DE integration

For concurrent work on the native DE, follow the [DE 1.0 integration contract](docs/de-integration-governance.md): owner lanes, shared-file handoffs, stacked PR dependencies, exact-head CI and guarded merges. Only the integration lane merges reviewed DE work into `main`; retain all existing XFCE/X11 and release-safety rules below.

## Delivery and verification

- Work from the active repo state; preserve user changes and working features.
- Prefer focused, reversible changes over broad rewrites or new background
  services. Distinguish existing XFCE functionality from future Wayland work.
- Add tests for schema validation/migration, malformed packs, genuine UI
  interactions, keyboard navigation, responsiveness and recovery whenever
  affected. Keep visual comparisons rooted in real captures, not a mockup
  labeled as a running desktop.
- Maintain the [Wayland DE roadmap](RICEBOWL_DE_ROADMAP.md) when completing or
  changing these contracts. Keep README status truthful and concise.
- A milestone is complete only when its stated tests and gates pass. Record
  physical-device checks that remain open; do not infer hardware success from CI.
