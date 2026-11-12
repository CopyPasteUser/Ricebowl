# RiceBowl DE — Wayland/labwc transition

**Status (November 2026): opt-in labwc session preview implemented;
physical acceptance outstanding.** RiceBowl 0.9.x is still an XFCE/X11
rice manager. The separate Wayland login-session package requires explicit
installation and is not yet a finished desktop environment.

### Screenshot evidence integrity (12 November 2026, pending CI)\n\n- [ ] Require complete PNG decoding before the classic panel pixel probe; add synthetic complete/truncated/wrong-color/invalid-geometry unit cases. Local focused tests pass, but the native labwc compositor screenshot matrix and full CI remain mandatory before this is marked complete. The synthetic unit fixtures are **not** real desktop screenshots.\n\n### Wayland XP Luna recipe (10 November 2026, preview sprint)

- Added `examples/wayland/xp-luna.json` with RiceBowl-original `luna-hills`
  artwork, real native programs/session actions and a compact panel layout.
- Schema v12 adds *generic* launcher foreground/background/label/radius tokens
  and a native menu palette; both are bounded, data-only, and backwards
  compatible with existing v1–v11 recipes. Waybar provides a launcher CSS
  fallback; its labwc menu does not claim native palette support.
- XFCE/X11 configuration, SDDM autologin and installed preview packages remain
  unchanged. Separate scripts provide a local build and 120-second tty preview.
- [x] An independent `xp-luna-columns` recipe now offers a native two-column
  Start menu (programs, system, session) without migrating the original
  `xp-luna` ID; compiled Rust/Python CI passed for PR #227.
- [x] Capture both the Luna desktop and opened native Start menu from a real
  headless labwc compositor in the native smoke suite, with PNG/geometry checks
  and permanent screenshots after CI verifies the captures (run #42890753472).
- [x] Fit system and unavailable-session labels in the native two-column shelf
  without changing canonical actions, search, AT-SPI or narrow-screen behavior;
  verified by native regression/multi-resolution CI (run #42898859348) and
  a refreshed real-compositor menu capture.
- [x] Unify selected portable TTF painting across the native launcher, menu,
  shortcuts and widgets; add bounded on-demand Unicode glyph caching, readable
  missing-glyph fallback, UTF-8-aware cell measurements and a compositor proof
  comparing built-in versus owner-private fonts, without global font changes
  (green native run #42904147986; permanent `luna-font.webp` gallery crop).
- [x] Prove Luna's optional palette-derived labwc server-side titlebars with
  a real XWayland before/after compositor capture, isolated private
  `themerc-override` and transaction-safe live switch/restore tests;
  green native run #42907311728, both screenshots inspected and preserved.
- [x] Carry an explicitly selected private TrueType font into the native
  calendar and volume OSD without changing default bitmap pixels; verify
  a real headless labwc calendar comparison and capture a permanent preview
  (green native run #42909714051; `luna-calendar-default.webp` and