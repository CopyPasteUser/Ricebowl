# SG4 WP4.5 — asset rights audit (prepared for owner sign-off)

**Status: PREPARED, NOT SIGNED.** This is an inventory plus a red-flag review
done from the repository, not legal advice and not a rights verification.
`rights_independently_verified` stays `False` everywhere until the repository
owner signs off (see [Owner sign-off](#owner-sign-off)). Nothing in this change
sets it to `True`.

- Baseline: `main@e1be418`. All 772 inventoried files share one first-add commit
  (`3d6b5fd`, 2026-11-19, a squashed import), so `git log` carries **no per-asset
  authorship history**. Authorship therefore rests on the declarations below.
- Machine-readable inventory: [`evidence/sg4/asset-inventory.json`](evidence/sg4/asset-inventory.json)
  (path, sha256, size, category, rices, users, declared licence, origin,
  generator, flags, first commit).
- Generator reproduction evidence:
  [`evidence/sg4/generator-reproduction.json`](evidence/sg4/generator-reproduction.json).
- Regenerate: `python3 scripts/sg4_asset_inventory.py` (`--check` exits 1 if stale).
  Guard: `tests/test_sg4_asset_inventory.py` fails if an asset is added, removed
  or its sha256 changes without a re-run and re-review of this document.

## Method

1. **Discovery.** Walk the whole tree (excluding build output and `.claude`) for
   image, font, audio, video and cursor extensions, plus theme files
   (`index.theme`, `themerc`, `gtk.css`, `dock.theme`, waybar `style.css`), the
   font licence text, and every bundled recipe/example pack JSON. **No cursor, sound,
   bitmap-font, `.xpm` or audio files exist in the repository.** Fonts embedded in the
   native shell are the single bundled TTF below (`include_bytes!`); the 8x8 bitmap face
   is a crates.io dependency, not a file (see [External references](#external-references)).
2. **Facts.** sha256 and size per file; users from static references in
   `py/rs/json/sh/css/md` (dynamic f-string names, e.g. `xfwm4` buttons, are
   attributed by directory and rice instead); declared origin from
   `CONTRIBUTORS.md`, `RICEHUB.md`, SVG `<title>`/comments, generator docstrings and
   `LICENSE`.
3. **Generator reproduction.** On a scratch copy, each `scripts/build_*_assets.py`
   (and `build_heritage_assets.main(classic_only=True)`) was run with Pillow 13.0.0
   and every written file compared by sha256: **441 files written, 336 identical,
   105 differ** (Classic and Frutiger chrome and GTK, five `index.theme`, one
   Classic icon). `_save()` in `build_heritage_assets.py` deliberately never
   overwrites wallpapers, and 42 curated SVGs are protected by
   `scripts/ricebowl_artwork.py`; those files are hand-curated, not generated.
4. **Visual spot check (author of this audit, not a legal review).** Contact
   sheets of all ten wallpapers and the 15 logo/mark SVGs were inspected. Other icon
   sets and chrome were reviewed from source/generators only and need an owner
   eyeball (see checklist). Source for icons is hand-written SVG paths with
   generic names.
5. **Flags** (RF01-RF14) classify risk; severity is a triage hint, not a verdict.

**Universal observations.** (a) The only licence in the repository is the
repo-wide MIT `LICENSE`; no asset carries its own SPDX/licence/author field, so
`declared_licence` is "MIT (repo-wide)" except the font. (b) The bundled recipes
carry no `provenance` block; RicePack provenance (`macrice/de/pack.py`) exists only
for exported packs and defaults to `unspecified`. (c) `CONTRIBUTORS.md` and
`RICEHUB.md` state RiceBowl bundles no Microsoft or Apple artwork and that the
penguin orb, GTK/XFWM chrome, icon set and Plank-style themes are original; they
also state four wallpapers were generated with OpenAI image tools. Those
statements are the whole declared provenance.

## Summary counts

772 files, 9.1 MB; **237 carry at least one flag** (95 of these are documentation
captures, 105 are generator-drift files).

| Category | Files | Notes |
| --- | ---: | --- |
| window-chrome (xfwm4 PNG) | 336 | 7 themes x 48; 240 reproduced by generators, 96 Classic/Frutiger differ |
| icon (scalable SVG) | 197 | 6 icon themes; 117 hand-curated, 80 generator-reproduced (1 differs) |
| status-icon | 66 | 6 rices x 11; hand-authored, no generator |
| documentation-capture | 95 | 42 X11 + 47 Wayland + 6 component screenshots |
| theme-config | 15 | `index.theme`, `themerc`, waybar CSS |
| logo-or-mark | 11 | start buttons, avatars, marks, one wallpaper SVG |
| recipe-pack | 11 | 9 examples + 2 bundled recipes |
| wallpaper | 10 | 4 generated (one flat colour), 4 AI-declared, 2 undocumented |
| gtk-theme | 7 | `gtk.css`, one per theme |
| dock-theme / icon-theme-config / preview-image | 6 / 6 / 6 | |
| component-icon | 4 | macmenu, control-center |
| font / font-licence | 1 / 1 | Liberation Sans Regular, OFL-1.1 |

Flag counts: RF01 3, RF02 3, RF03 1, RF04 2, RF05 4, RF06 1, RF07 1, RF08 1,
RF09 105, RF10 101, RF11 9, RF12 1, RF13 1, RF14 11 (a file may carry several).

## Per-category tables

Full per-file data (including every sha256) is in the JSON; tables below list
all single-purpose files and group the bulk sets.

### Fonts

| Path | sha256 (12) | Size | Used by | Declared | Flags |
| --- | --- | ---: | --- | --- | --- |
| `assets/fonts/LiberationSans-Regular.ttf` | `bade59d82265` | 410820 | `riceplate-wayland` (`native_shaping.rs`, `style_art.rs`, `system_fallback.rs`) via `include_bytes!`; every native rice's builtin Luna UI font | OFL-1.1, Liberation Sans 2.1.5, (c) 2010 Google / 2012 Red Hat, reserved font name "Liberation"; text in `assets/fonts/LiberationSans-LICENSE.txt` | RF07, RF08 |
| `assets/fonts/LiberationSans-LICENSE.txt` | `-` | 5756 | licence text | Debian copyright format, SIL OFL 1.1 | - |

The 8x8 bitmap face used by `text_render.rs` is the `font8x8` crate, not a tracked
file. Proprietary font names (Tahoma, Segoe UI, Trebuchet...) appear only as CSS/GTK
fallbacks (RF13), never as files.

### Wallpapers

| Path | sha256 (12) | Size | Rice | Origin / generator | Flags |
| --- | --- | ---: | --- | --- | --- |
| `assets/wallpapers/aurora-day.jpg` | `6aae309ab633` | 176849 | macOS Aurora | AI-generated, OpenAI image tools (CONTRIBUTORS.md) | RF05 |
| `assets/wallpapers/aurora-night.jpg` | `69fbbd1595ca` | 159853 | macOS Aurora | same | RF05 |
| `assets/wallpapers/aero-seven-blue.jpg` | `6704b2bb592e` | 144418 | Aero | same ("Frutiger Aero-inspired Windows 7") | RF05 |
| `assets/wallpapers/aero-seven-night.jpg` | `46616a5cfaa6` | 148484 | Aero | same | RF05 |
| `assets/wallpapers/luna-hills.jpg` | `bb843f5783c2` | 423426 | XP Luna (also used by every Luna smoke/native recipe) | undocumented photographic raster; evokes XP "Bliss" | RF03, RF04 |
| `assets/wallpapers/frutiger-future.jpg` | `74a48991233e` | 417646 | Frutiger | undocumented raster | RF04 |
| `assets/wallpapers/ten-blue.jpg` | `a8db650a14a3` | 69028 | Windows 10 | `build_ten_assets.py` (reproduced) | RF01, RF02 |
| `assets/wallpapers/ten-midnight.jpg` | `c04c25c87b7e` | 61912 | Windows 10 | `build_ten_assets.py` (reproduced) | RF01, RF02 |
| `assets/wallpapers/chrome-pastel.jpg` | `4ad3dc13c974` | 64252 | ChromeOS | `build_chrome_assets.py` (reproduced) | - |
| `assets/wallpapers/classic-teal.jpg` | `6ecc5e45ad56` | 24588 | Windows 98 | flat `#008080` via `build_heritage_assets.py` (reproduced) | - |

### Logos, marks, avatars (`assets/*.svg`, component icons)

| Path | Rice | Declared / observed | Flags |
| --- | --- | --- | --- |
| `assets/ten-start.svg` | Windows 10 | "Original four-pane light icon ... A Windows-10-shaped desktop affordance" (its own comment); renders as the Windows logo with a penguin in one pane | RF01, RF11 |
| `assets/windows10-bloom.svg` | Windows 10 prototype | light-beam composition modelled on the Windows 10 hero wallpaper | RF02, RF11 |
| `assets/ricebowl-chrome-start.svg` | ChromeOS | four rounded squares in Google brand hexes | RF06 |
| `assets/aero-penguin.svg`, `ricebowl-classic-start.svg`, `ricebowl-xp-user.svg`, `macrice-symbolic.svg` | Aero / Win98 / XP / MacRice | declared original penguin art | RF11 |
| `assets/ricebowl-xp-start.svg`, `ricebowl-frutiger-start.svg`, `ricebowl-symbolic.svg`, `ricehub-symbolic.svg` | XP / Frutiger / core | original orb/bowl marks; no flag | - |
| `components/macmenu/assets/macmenu-{app,penguin,penguin-ink}.svg` | macOS | declared original single-ink penguin | RF11 |
| `components/control-center/assets/macos-control-center.svg` | macOS | blue rounded tile with toggle glyph in Apple system blue | RF12 |

### Themes and icons (grouped; per-file data in JSON)

| Set | Files | Rice | Generator and reproduction | Flags |
| --- | ---: | --- | --- | --- |
| `assets/themes/RiceHub-Aero` (xfwm4 48 + gtk + 2 config) | 51 | aero | `build_aero_assets.py`, reproduced (gtk hand-curated) | - |
| `assets/themes/RiceHub-Chrome` | 51 | chromeos | `build_chrome_assets.py`, reproduced | - |
| `assets/themes/RiceHub-Luna` | 51 | winxp | `build_heritage_assets.py`, chrome reproduced | - |
| `assets/themes/RiceHub-Classic` | 51 | winclassic | `build_heritage_assets.py`, **differs** | RF09 |
| `assets/themes/RiceHub-Frutiger` | 51 | frutiger | `build_heritage_assets.py`, **differs** | RF09, RF13 (gtk.css) |
| `assets/themes/RiceHub-Ten-Dark`, `-Light` | 51 x 2 | windows10 | `build_ten_assets.py`, reproduced | - |
| `assets/icons/RiceHub-Aero` | 45 | aero | 11 generated, 33 curated | - |
| `assets/icons/RiceHub-Luna-Icons` | 62 | winxp | 30 `build_luna_control_icons.py`, 8 heritage, rest curated; `index.theme` differs | RF09 (index only) |
| `assets/icons/RiceHub-Classic-Icons` | 30 | winclassic | heritage; `applications-other.svg` and `index.theme` differ | RF09 |
| `assets/icons/RiceHub-Chrome-Icons`, `-Frutiger-Icons` | 25 / 26 | chromeos / frutiger | heritage + curated; `index.theme` differs | RF09 (index only) |
| `assets/icons/RiceHub-Ten-Penguin` | 15 | windows10 | `build_ten_assets.py` + curated | - |
| `assets/status/{winxp,windows10,winclassic,frutiger,chromeos,aero}` | 66 | per rice | hand-authored, "RiceBowl <name>" titles | - |
| `assets/plank-themes/*` (6 `dock.theme`) | 6 | macOS, Aero, Windows 10 | key-file values for external GPL-3.0 Plank | - |
| `macrice/de/resources/waybar/style.css` | 1 | legacy session | project CSS | - |

Not visually compared by this audit: the icon sets (XP "Control Panel" style, Aero
"Control Panel" style) and window chrome. They are generic hand-written shapes with
OS-era styling; an owner visual pass is on the checklist.

### Previews and screenshots (documentation, not runtime)

| Set | Files | Origin | Flags |
| --- | ---: | --- | --- |
| `assets/hub-previews/*.jpg` | 6 | downscaled from `screenshots/current/<rice>-start.webp` by `scripts/refresh_hub_previews.sh` (used by the Hub) | RF10 |
| `screenshots/current/*.webp` | 42 | real GTK/X11 captures of the six rices | RF10 |
| `screenshots/wayland/*.webp` | 47 | real labwc + native RicePlate captures | RF10 |
| `components/{macmenu,macbar,control-center}/screenshots/*.png` | 6 | component captures | RF10 |

### Recipes and example packs

All 11 (`examples/wayland/*.json` x9, `macrice/de/resources/recipes/{chrome,classic}.json`)
are project-authored data, reference only bundled wallpapers by name and the
builtin font, and carry no author/licence provenance (RF14). Their users are the
native shell tests, `panel_chrome.rs` (`include_str!`), and Creator fixtures.

## External references (not tracked assets)

| Item | Licence | Position |
| --- | --- | --- |
| `font8x8` 0.3.1 (bitmap glyph data in `riceplate-native`) | crate MIT; data credited as IBM VGA public domain | fetched by Cargo; confirm credit |
| `fontdue` 0.9.4 / `rustybuzz` 0.20.1 | MIT OR Apache-2.0 OR Zlib / MIT | code only |
| DejaVu, WenQuanYi Micro Hei, Lohit Devanagari | distribution licences | read from `/usr/share/fonts` at runtime if installed; not redistributed |
| `status-notifier` 0.1.1 (vendored patch) | MIT | code only |
| Plank | GPL-3.0 | external program, not vendored |

## Red flags and recommended actions

Ordered by severity. "Owner decision" means a change or an explicit, recorded
risk acceptance.

| ID | Sev | Assets | Problem | Recommended action |
| --- | --- | --- | --- | --- |
| RF01 | **high** | `assets/ten-start.svg`, `assets/wallpapers/ten-blue.jpg`, `assets/wallpapers/ten-midnight.jpg` | Four-pane perspective window mark (the Start icon renders as the Windows logo with a penguin pane; the wallpapers draw the same panes). AGENTS.md forbids copying proprietary logos. | Replace with a clearly original mark (penguin or bowl only, no four-pane grid) and regenerate; or owner records risk acceptance. |
| RF03 | **high** | `assets/wallpapers/luna-hills.jpg` | Green hill, blue sky and clouds in the XP "Bliss" composition; photographic raster with no recorded author, tool or prompt. Also the capture background of the Luna smokes and native recipes. | Confirm provenance and generation records or replace with a distinct original scene. |
| RF02 | medium | `assets/windows10-bloom.svg`, ten wallpapers | Light-beam hero composition modelled on the Windows 10 default wallpaper. | Owner visual comparison; redraw beams. |
| RF04 | medium | `luna-hills.jpg`, `frutiger-future.jpg` | Hand-reviewed rasters not produced by any generator and not named in `CONTRIBUTORS.md`. | Record author/tool/prompt/terms. |
| RF05 | medium | `aurora-day`, `aurora-night`, `aero-seven-blue`, `aero-seven-night` (`.jpg`) | AI-generated (declared). No prompts, dates or terms recorded; AI output may not be copyrightable; "Aero Seven" imitates Windows 7 artwork names/looks. | Archive generation records, confirm tool terms allow MIT redistribution, confirm no proprietary reference image was used. |
| RF06 | medium | `assets/ricebowl-chrome-start.svg` | Google brand colours in a 2x2 mark. | Recolour or replace. |
| RF07 | medium | `assets/fonts/LiberationSans-Regular.ttf` | Name table says Liberation Sans 2.1.5 (OFL-1.1) but sha256 `bade59d8...` differs from Debian `fonts-liberation`'s 2.1.5 file (`4659bc0c...`). If modified, OFL forbids the reserved name "Liberation". | Compare with upstream release tarball; replace with the exact upstream file or rename. |
| RF08 | medium | same font | Embedded in the binary, but the Debian build scripts (`scripts/build_wayland_*_deb.sh`, `build_riceplate_native_deb.sh`) install no copyright/licence file for it. | Install `LiberationSans-LICENSE.txt` (e.g. `/usr/share/doc/<pkg>/copyright`) in every package embedding it. |
| RF10 | medium | 101 captures and previews | Screenshots show the assets above plus third-party UI (Thunar, GTK widgets, system fonts). | Resolve the artwork flags; decide whether captures stay public. |
| RF09 | low | 105 files: Classic and Frutiger `xfwm4`, both `gtk.css`, 5 `index.theme`, Classic `applications-other.svg` | Generator output no longer matches tracked bytes, so those files are edited by hand or by an older generator and not reproducible. | Accept as hand-authored or re-commit generator output. |
| RF11 | low | 9 penguin SVGs | Tux-like penguin; Tux (Larry Ewing) is a licensed work. | Confirm independent drawing or add attribution. |
| RF12 | low | `components/control-center/assets/macos-control-center.svg` | Apple-style tile and system blue; filename names macOS. | Owner visual comparison; rename. |
| RF14 | low | 11 recipes | No provenance block. | Attach when published as RicePacks. |
| RF13 | info | `RiceHub-Frutiger` `gtk.css` | Names proprietary families as fallbacks only. | None. |

Nothing found: no embedded cursors, sounds, proprietary icon sets, Microsoft or
Apple bitmap files, or Material/Roboto/Inter files. `CONTRIBUTORS.md` also states
no WhiteSur, Bibata, Inter or Plank files are bundled (consistent with this scan).

## Owner sign-off

**What the field is.** `rights_independently_verified` is a per-review report field
computed in `macrice/de/pack.py::_attribution_review` (hard-coded `False`, returned
with `external_rights_review_required: True`) and in the publish receipt written
by `macrice/de/creator_release.py::publish_export` (hard-coded `False`). It tells
anyone who inspects or imports a RicePack that no human has independently
verified rights; user-supplied SPDX labels and hashes do not prove ownership.
Tests that pin it: `tests/test_de_ricepack.py`, `tests/test_sg4_creator_release.py`,
`tests/test_wayland_creator_handoff.py`; documented in
`docs/sg4-creator-export-review-qa.md`.

**What flipping it would mean.** Changing it to `true` would assert, in every
exported review and receipt, that a human independently verified the rights of
the pack's artwork, fonts, icons, wallpaper and attribution chain. It is a claim
about the **specific pack and its assets**, not about this repository's audit;
making it a constant `true` would overstate every third-party pack. This audit
therefore does not touch it. A correct change, if the owner wants one, is a
separate code change that derives the value from a recorded sign-off covering
the exact asset hashes in the inventory, with updated tests. Until then the
field stays `False`.

**Checklist (owner).**

- [ ] Reviewed RF01 and RF03 artwork; each replaced or risk accepted in writing
  (assets: `ten-start.svg`, `ten-blue.jpg`, `ten-midnight.jpg`, `luna-hills.jpg`).
- [ ] RF02, RF04, RF05, RF06, RF12: decision recorded (replace / accept /
  documents attached). For AI wallpapers, generation records and tool terms
  stored with a link here.
- [ ] RF07: font compared against the upstream Liberation 2.1.5 tarball (record
  the upstream sha256); RF08: licence file installed in packages.
- [ ] RF09, RF11, RF14: accepted or tracked as follow-ups.
- [ ] Visual spot check of icon sets (`RiceHub-Aero`, `-Luna-Icons`) and window
  chrome against the reference OS artwork they imitate.
- [ ] Declared licences confirmed (MIT for project assets; OFL-1.1 for the font;
  `CONTRIBUTORS.md` statements still true).
- [ ] `python3 scripts/sg4_asset_inventory.py --check` clean at the commit being
  signed, so the reviewed hashes are the shipped hashes.
- [ ] Sign-off recorded (name, date, commit) here; WP4.5 row in
  `docs/sg-remaining-work-packages.md` moved from PREPARED to DONE.

Sign-off: _unsigned_
