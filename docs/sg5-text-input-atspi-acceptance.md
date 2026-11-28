# SG5 — Native Unicode, IME and AT-SPI acceptance ledger

Status: **OPEN**. Gate authority: [issue #417](https://github.com/CopyPasteUser/Ricebowl/issues/417). The mainline SG5 evidence index remains **2/4**: implemented portions and historical tests do not complete native text/IME/accessibility parity.
Source-audit baseline: `main@fdbdf26a4a90cb31be8efa222e527609ad447751` (23 November 2026). PR #551 (Rename AT-SPI) and PR #557 (Wayland Run/Rename clipboard) are **merged**. Their feature presence is independently visible in source, but final exact-main SG5 acceptance and physical-device checks remain open.

## Inventoried native text surfaces

| Surface | Actual input owner | Editing and rendering | text-input-v3 | AT-SPI |
| --- | --- | --- | --- | --- |
| XP Run | luna_dialog::State(Kind::Run); compositor keyboard events through Super+R | complete grapheme carets, text selection, delete, preedit paint | wired via enter/preedit/delete/commit/done | transient TextInput and TextRun named Command; black-box client smoke added |
| Desktop File Rename | luna_dialog::State(Kind::FileRename) | same editor, rename only after explicit confirmation | shared Luna adapter (same `Kind::Run \| Kind::FileRename` Enter/preedit/delete/commit/done path); external v2 IME + focus leave/re-enter smoke PASSED locally (26 November 2026, labwc 0.7.2, base `c66fe0a` + this change) | transient TextInput and TextRun named File name; real Wayland pointer → Rename external AT-SPI client smoke PASSED at #551 head (Native 44673725266) |
| Start Menu Search / All Programs | native_menu::MenuState::search; wl_keyboard | Unicode-batch insertion and UAX #29 backspace with the caret at the end | **NOT wired**: compositor v3 Enter/Done still targets Run/Rename only | Transient TextInput/TextRun for both fields, verified by the external keyboard/AT-SPI smoke |
| Context menus, tray, calendar, desktop icons, RicePop | navigation/selection handlers, no text editor | keyboard actions and labels only | n/a without actual editor | supported actions where implemented, not fully client-validated |
| External search application | fuzzel and other Wayland applications | external application responsibility | external application responsibility | external application responsibility |

Do not count menu-search keyboard navigation as full native IME and AT-SPI parity.

## Concrete Unicode and native rendering matrix

| Test domain | Fixture | Required observable behavior | Evidence |
| --- | --- | --- | --- |
| UTF-8 / UAX #29 | e + combining U+0301, German flag, woman-technologist ZWJ, thumbs-up with modifier | no split graphemes under caret, selection, delete, clipping | Rust tests in luna_dialog, native_menu, text_render |
| Clipboard | selected multi-grapheme Run / Rename text | Ctrl+C/Ctrl+X/Ctrl+V must preserve UTF-8, selection and focus without shell execution | **Merged #557** implements seat-scoped `wl_data_device` ownership/receive and atomic validation; `scripts/smoke_luna_atspi.sh` includes real external `wl-copy`/`wl-paste` round trips and negative invalid-text coverage; the Rename field also has an external `wl-copy` paste-in and copy-out receipt (27 Nov, local, WP5.3). Revalidate on final exact-main source; do not infer physical acceptance |
| BiDi | abc + Hebrew, mixed Arabic ABC 42, مرحبا, שלום, abc שלום 123 | logical storage and AT-SPI offsets; UAX #9 P2/P3 paragraph direction; RTL paragraphs right-aligned; caret from the bidi visual map (outer-run affinity), visual Left/Right, logical Home/End, multi-rectangle selection, preedit at the logical caret | Rust `bidi_layout`/`luna_dialog`/`style_art`/`text_render` tests; real-labwc Run field typed Arabic, Hebrew and mixed text with `grim` ink/caret pixels (28 November section) |
| Arabic/Indic | Arabic salaam, Hindi हिन्दी | OpenType GSUB/GPOS and nonzero bounded glyph positions only if real font covers glyphs | style_art/native_shaping Rust tests; **positive Hindi GSUB/GPOS + grapheme caret tests pass locally with installed `fonts-lohit-deva`** (see 27 November section); native compositor rendering of shaped Indic text now works through the trusted system font fallback (28 November section) |
| CJK | 日本語, 中文, 한국어 | UTF-8 commits and clearly rendered fallback where coverage unavailable; never label '?' as CJK success | existing missing-cmap tests; **positive CJK advance/caret/pixel tests pass locally with installed `fonts-wqy-microhei`**; native compositor positive CJK/Hangul rendering through the system font fallback passes locally (28 November section) |
| Missing fonts/glyphs | U+10FFFF and missing joined emoji | visible replacement metrics and pixels; no false font-coverage success | existing negative style_art tests plus the 27 November Hindi/CJK/Hangul replacement-pixel Rust and real-labwc (AT-SPI + `grim`) matrix |
| Live compositor editing | empty, AB, Left, Backspace, select-all, replacement, Escape, reopen | external wtype wl_keyboard delivery and public AT-SPI text/focus/selection queries | Run and separate XDG Rename AT-SPI smoke passed at #551 head (Native 44673725266) |
| Sanitized accessibility text | e + newline + combining mark + Z | resegment final exposed text, caret and selection never refer to phantom cluster | added positive and negative AccessKit Rust tests |
| Full IME transaction | Japanese preedit and commit, 3-byte CJK delete + replacement | actual input-method-v2 producer must traverse labwc into the native text-input-v3 consumer, then report public surrounding text | external Rust v2 IME producer -> native Run v3 path passed #551 exact-head Native 44673725266; same producer -> labwc -> native **Rename** v3 path (preedit, commit, 3-byte delete, replacement) passed locally 26 November 2026 (labwc 0.7.2, 3/3 consecutive `scripts/smoke_luna_atspi.sh` runs, about 14 s each) |

## Reproducible checks

1. Run cargo test --locked --manifest-path components/riceplate-wayland/Cargo.toml.
2. Run cargo clippy --locked --manifest-path components/riceplate-wayland/Cargo.toml --all-targets -- -D clippy::correctness -D clippy::suspicious -D clippy::perf -D unused_must_use.
3. Build cargo build --locked --release --manifest-path components/riceplate-wayland/Cargo.toml and cargo build --locked --release --manifest-path components/riceplate-wayland/Cargo.toml --example wayland_ime_v2_client.
4. Run sh -n scripts/smoke_luna_atspi.sh and /usr/bin/python3 -m py_compile scripts/smoke_riceplate_atspi_client.py.
5. With a private DBus/headless labwc environment and Ubuntu packages python3-pyatspi, at-spi2-core, wtype: timeout -k 5s 140s sh scripts/smoke_luna_atspi.sh.
6. Until December 2026, **do not invoke GitHub Actions**. Run the equivalent suites locally in disposable private Linux/labwc sessions on the exact branch HEAD, then repeat affected checks on the merged main. Missing provider, missing glyph, timeout or failed AT-SPI query is FAIL, never SKIP-as-PASS. The later formal release gates still require trusted exact-source hosted evidence.

**Protocol separation:** wtype injects ordinary wl_keyboard events. Separately, the CI-only wayland_ime_v2_client uses real input-method-v2 requests and verifies a text-input-v3 Japanese preedit, commit and Unicode byte deletion through the compositor. The fixture validates only the exact checked transaction on Run when CI passes; it is not a production Fcitx/IBus engine or coverage for menu search beyond the existing menu step. Rename now has the same transaction plus a focus cycle (below).

## Independent AT-SPI evidence-probe reliability (23 November 2026)

The public `scripts/smoke_riceplate_atspi_client.py` now requires **three
consecutive absent samples** before reporting a dismissed editor absent.
Intermittent provider errors or a still-visible entry reset confirmation.
If diagnostic inventory fails after a timeout, the probe returns a clean
failure and logs the error *type only*, never command content. Eleven
standard-library, fake-provider unit tests run successfully against the
exact committed source and test blobs in an isolated Python 3.13 sandbox.
The shared public-desktop preflight rejects absent registries, invalid
child counts and inaccessible AT-SPI metadata without leaking provider
error text or falsely treating a dialog as closed.
In addition to the original probe cases, they now reject incomplete,
truncated or temporarily unreadable AT-SPI trees or an entirely empty registry as false dismissal receipts.
The existing private `scripts/smoke_luna_atspi.sh` now also includes
a **separate real-pointer All Programs** flow: geometry is read from the
native 1366×768 menu trace, the actual XP All Programs tile is clicked,
and `Filter installed apps` is checked for keyboard input, backspace,
AT-SPI focus/caret and Escape teardown. The complete script passed in a
private labwc 0.8.3 session at `d4aba0d8`, including real pointer and
keyboard input, public AT-SPI queries, dialog clipboard exchange and the
Run IME protocol fixture. [Offline evidence for #597](https://github.com/CopyPasteUser/Ricebowl/pull/597#issuecomment-7156062454)

Repeat the external AT-SPI smoke on the final integration head. Menu IME
composition, real Orca and hardware acceptance remain open.

## Rename IME and focus leave/re-enter (local evidence, 26 November 2026)

`scripts/smoke_luna_atspi.sh`, private labwc 0.7.2 (`/opt/labwc-sg5`), base
`c66fe0a` plus the WP5.1 change; 3 consecutive passes, about 14 s each. The
Rename dialog is opened with real virtual-pointer input (secondary click, then
the Rename item) on the private XDG Desktop fixture. The external
`wayland_ime_v2_client --base 00-sg5.txt --focus-cycle` (a separate process,
input-method-v2 only; nothing is injected in-process) then drives:

1. preedit, commit and a UTF-8 surrounding-text delete (3-byte CJK) + replacement,
   asserted through the public AT-SPI probe as `00-sg5.txt日本界`, caret 13, focused,
   no preedit in the accessible text (native receipt lines carry sizes only);
2. a second uncommitted preedit, then a **real focus leave**: a separate
   `riceplate_focus_probe overlay exclusive` client takes Exclusive keyboard
   focus. The IME client observes `deactivate`, RicePlate observes
   `wl_keyboard.leave` + text-input `leave` (dialog retained, preedit
   dropped, not committed), and the probe client receives the Escape that the
   script sends (so it did not reach Rename);
3. the probe exits, labwc returns focus: the IME sees `activate` with fresh
   surrounding text exactly `00-sg5.txt日本界` (preedit not replayed or
   committed anywhere); AT-SPI confirms the same text, caret 13, focused;
4. one more commit (`文`) lands on Rename (`00-sg5.txt日本界文`, caret 14);
5. Escape cancels: the AT-SPI editor is absent, `00-sg5.txt` still exists and
   is the only Desktop entry (nothing renamed). The existing clipboard/edit
   Rename steps then run unchanged on a re-opened dialog.

Fixture changes: `riceplate_focus_probe` gained an optional `exclusive`
argument (exit on Escape) and now claims the already-announced seat (it never
saw a seat before, which is the likely cause of the deferred WP0.4 failure
of the opt-in `smoke_riceplate_desktop_focus`; not re-run here). The only
product change is trace-only (`RICEBOWL_DE_TRACE_MENU`): sizes of the dialog
IME `done` and preedit dropped on text-input leave. Not covered: candidate
selection, RTL composition, menu-surface focus cycles, real Fcitx/IBus.

## Hindi/CJK fonts, missing-font matrix and AT-SPI actions (local evidence, 27 November 2026)

Environment: private labwc 0.7.2 (`/opt/labwc-sg5`), `scripts/smoke_luna_atspi.sh`
3/3 consecutive passes (about 26 s each, CI budget 140 s), Rust 515 tests,
clippy (`-D clippy::correctness -D clippy::suspicious -D clippy::perf -D unused_must_use`)
and `cargo fmt --check` clean, Python `unittest discover` 2003 OK (4 skipped).

**Positive script fonts (WP5.4, Rust only).** No font binary is committed;
tests read freely licensed packages installed by apt (`fonts-lohit-deva`,
OFL; `fonts-wqy-microhei`, Apache-2.0/GPLv3 with font exception). CI's
`native-layer-shell` apt line now installs both. The positive tests
(`native_shaping::tests::devanagari_*`, `cjk_*`, `style_art::tests::installed_devanagari_*`,
`installed_cjk_*`) call `script_fonts::require`, which **fails the test with an
explicit `FONT UNAVAILABLE: install ...; script coverage ... NOT verified`**
when the font is missing or lacks any scalar (verified by temporarily moving
the file). They never skip and never pass as support. The always-run
`script_font_probe_never_reports_coverage_for_missing_or_noncovering_fonts`
proves a missing path or a Latin-only font is classified `Unavailable` /
`LacksGlyphs`, never `Covered`. Asserted: हि (matra U+093F) shapes with the
matra glyph first and different glyph IDs than the naive cmap order; न्द is
GSUB-substituted; हिन्दी differs from cmap, has no `.notdef`, nonzero bounded
advances; editor caret x (real `luna_dialog::State::input_view_bidi` with the
native `measure_text`/`measure_visual_text` callbacks) is strictly increasing
per UAX #29 grapheme (हिन्दी is 2 clusters, so no caret falls inside the
matra/conjunct) and the end caret equals the painted shaped width; 日本語,
中文 and 한국어 get one full-width (8-16 px) bounded step per character,
real glyph IDs, ink within the measured width, and pixels different from the
Latin-face replacement run.

**Missing-font matrix (WP5.6).** Rust (`missing_script_glyphs_paint_one_visible_replacement_per_grapheme`,
no installed font needed): with the bundled Latin face, हिन्दी, 日本語, 中文 and
한국어 each paint exactly one `?` per grapheme, pixel-identical to a literal `?`
run, never invisible, with one caret step per grapheme. Compositor: in the real
Run editor under labwc, `wtype` types हिन्दी / 日本語 / 한국어; the public AT-SPI
probe reads back the **real text and caret** (6/3/3), and a `grim` crop of the
input field is pixel-identical to the same dialog showing `??`/`???`/`???`
(`scripts/sg5_png_compare.py`) and different from the empty field. This proves
visible replacement with real accessible text and never a coverage claim.

**Product limit found, then removed (see the 28 November section).** The native
Run/Rename face is the bundled Latin Liberation Sans or a private recipe font
(non-proportional, no GSUB/GPOS, 1 MiB cap), so on 27 November there was no
product path that rendered shaped Devanagari or CJK; the 27 November
compositor matrix therefore proved the visible `?` replacement only.

**AT-SPI actions and dialog transitions (WP5.5, product change).** The native
dialog and the XDG file context menu were not action-capable in AT-SPI. Added
accessible controls bound to the same handlers as the pointer: dialog buttons
(`OK` / `Rename` / `Trash` / `Close` and `Cancel`, `Target::DialogAccept/Cancel(kind)`)
and the XDG file menu (`Target::FileContextAction { key, item }`, disabled items
expose no action). Stale snapshots are rejected by kind and file identity
(Rust test). `scripts/smoke_riceplate_atspi_client.py --do-action LABEL --role
button|menu-item` calls the public `doAction(0)`; three unit tests cover
success, no-action, refused and missing control. Smoke receipts, all by
action, with the file system as evidence: Rename menu item -> Rename with the
unchanged name is refused (dialog stays open, Desktop unchanged); changed name
-> Cancel (dialog gone, `00-sg5.txt` untouched); Run Cancel (marker file not
created) and Run OK (marker created); Rename menu item -> new name -> Rename
(dialog gone, Desktop is exactly `renamed.txt` with the original content).

**Menu IME (#600) and #595 (WP5.2).** The same 3/3 runs print
`real menu IME preedit/commit/delete and AT-SPI teardown for search PASS` and
`... for programs PASS` (external input-method-v2 producer -> labwc ->
text-input-v3 -> Start search and All Programs, AT-SPI text `日本界`, caret 3,
Escape teardown). That covers #600's preedit/commit/delete. #595 stays **open**
for: menu-surface focus leave/re-enter, real candidate selection, RTL
composition, and painted composition (underline) pixels, none covered by the
smoke.

## Trusted system font fallback (local evidence, 28 November 2026)

**Design as implemented.** `system_fallback.rs` holds a compile-time, ordered
table of absolute candidates under `/usr/share/fonts` only: Devanagari
(`Lohit-Devanagari.ttf`, `NotoSansDevanagari-Regular.ttf`), Han/Kana and Hangul
(`wqy-microhei.ttc`, `NotoSansCJK-Regular.ttc`, face 0) and Arabic/Hebrew
(`DejaVuSans.ttf`). No fontconfig, no new crate, no user/recipe/pack path; pack
fonts keep their 1 MiB cap and rules and never use the fallback (only the
shaped proportional Luna face does). A candidate loads lazily on the first
grapheme cluster that the bundled faces lack and whose script maps to a group,
once per process; the result, including failure, is cached (no retry, no
polling). Open is `O_NOFOLLOW|O_NONBLOCK`, `fstat` must say a regular file of
at most 32 MiB, and rustybuzz must parse it; anything else is "unavailable".
Text layout splits a line into per-face runs at cluster granularity (primary
face, then the first candidate whose cmap covers the whole cluster), shapes
each run with rustybuzz and paints by glyph index. Caret, selection and
click-to-caret use the shaped advances through the existing `measure_text`;
logical text, AT-SPI text/caret and IME are unchanged and the BiDi path is
reused (RTL visual-prefix measurement shapes system runs too). A cluster no
candidate covers keeps the existing single visible `?` (never claimed as
coverage). ASCII text returns before any of this runs; Latin/Greek/Cyrillic/
emoji clusters have no script group, so they never consult or load a font
(unit-tested with a per-thread consult counter).

**Deviation from the first design: no fontdue for system fonts.** The first
implementation rasterized with fontdue (`rasterize_indexed`). Measured in the
real plate, fontdue's eager per-glyph geometry made the 5 MB WenQuanYi
collection cost **+182 MB RSS** (212 MB after typing 日本語 vs 27 MB) and a
347 ms load. System fonts are therefore parsed with rustybuzz only
(`ttf_parser` outlines) and rasterized by a small signed-area coverage
rasterizer (`system_fallback::rasterize`), cross-checked against fontdue
coverage/bounds in a unit test and visually (matra reorder and conjunct in हिन्दी
are correct). Bundled and recipe faces still use fontdue unchanged. Font bytes
are intentionally leaked into the process-lifetime cache. Unhinted grayscale
only; no kerning outside shaping.

**Kill switch.** `RICEBOWL_SYSTEM_FONT_FALLBACK=0` disables the fallback (it can
never add a path); it exists for rollback and for the negative compositor
test.

**Memory (fresh `riceplate-native`, `/proc/<pid>/status` VmRSS, three
`scripts/smoke_luna_atspi.sh` runs, Run editor, nothing non-ASCII shown before).**
Fallback enabled: ASCII `abc` 25.7/27.1/25.9 MB; after typing हिन्दी +0.54 to
+0.62 MB (Lohit); after 日本語 a further +5.1 MB (the 5 MB wqy file); 한국어 adds
nothing more. Fallback disabled: no change (27.5 MB flat). No startup or
interaction-latency measurement beyond the above was taken for the final
design.

**Tests.** Rust (525 total, clippy/fmt clean): candidate table is absolute
`/usr/share/fonts` only; missing, symlink, directory, FIFO, oversized (sparse
32 MiB + 1) and non-font files are `unavailable`; script-group mapping and
Latin never consulting a font; run segmentation (`ab हिन्दी cd 日本語 \u{10FFFF}` ->
primary / system / primary / system / one primary `?`); shaped carets for
हिन्दी/日本語/한국어 (distinct step per grapheme, end caret = painted width, ink
inside the measured width, pixels differ from the `?` run and are non-blank,
matra reordering, no `.notdef`) with explicit `FONT UNAVAILABLE` failures when
`fonts-lohit-deva`/`fonts-wqy-microhei` are absent; private recipe faces never
use the fallback; the earlier replacement-pixel tests now disable the fallback
explicitly. Compositor (`scripts/smoke_luna_atspi.sh`, labwc 0.7.2, 11/11
consecutive passes after the final change, about 43 s, CI budget 140 s):
`wtype` types हिन्दी, 日本語 and 한국어 into Run; the public AT-SPI probe reads
the real text and caret (6/3/3); the `grim` crop is non-blank and **not** equal
to the `??`/`???` crop. A second plate started with the kill switch shows the
crops equal to the `?` crops again (one visible replacement per grapheme) and
different from the fallback-on crops.

**Regression runs.** `scripts/smoke_riceplate_native.sh` and
`scripts/smoke_wayland_shared_rice_engine.sh` both fail in this environment
**identically on the unmodified base commit** (Luna Recycle Bin Gio open
assertion; "Luna Escape left menu visible: 2740 pixels"), before and after this
change; no text-rendering assertion regressed, but those smokes cannot confirm
the rendering paths after those points. Python `unittest discover`: 2003 OK
(4 skipped). Not claimed: SG5 closure, exact-head CI, physical Fcitx/IBus/Orca,
RTL Arabic/Hebrew compositor review, non-Luna (cell-metric) faces.

## RTL paragraph direction, alignment and bidi caret (28 November 2026; local evidence)

One core model, `bidi_layout::LineLayout`, now drives every single-line native
text surface that shows user or app text: the paragraph direction is UAX #9
P2/P3 (first strong letter, isolates skipped, LTR default) unless the widget
forces one (`BaseDirection`); display order is the bidi reordering at that
base level. The layout carries the painted x of every visual cluster edge,
taken from the same glyph advances the painter uses (OpenType-shaped
per-grapheme advances, a ligature such as lam-alef split between its
graphemes; per-letter advances for unshaped text; one cell per grapheme for
the bitmap face).

- **Alignment.** RTL paragraphs align to the trailing (right) edge in the
  RicePop inbox rows/detail/actions, Start-menu tiles and action rows, tray
  popup and tray menu labels, and the Run/Rename editor. A label keeps the
  direction of its complete text after fitting; fitting cuts the logical end,
  so the ellipsis paints at the visual left of an RTL label. LTR labels keep
  their exact historical pixels (byte-identical regression test).
- **Caret.** The caret x of a logical index is the edge of the bidi visual map;
  at a level boundary it takes the affinity of the *outer* run (lower
  embedding level, ties to the preceding grapheme; start/end of paragraph
  count as base level). Home/End stay logical, so in an RTL paragraph Home is
  the right edge and End the left edge. Left/Right move **visually** (one
  painted cluster per key); AT-SPI text, caret and selection offsets and
  text-input-v3 surrounding text stay logical and unchanged.
- **Selection / IME.** A logical selection or preedit crossing a level boundary
  paints as several rectangles. The preedit is inserted at the logical caret
  and the paragraph direction includes it.

Rust tests: base direction (Arabic, Hebrew, neutral-first, digits-first,
isolates, mixed), forced direction, alignment, ellipsis side, caret x across
LTR/RTL boundaries, arrow walks in LTR and RTL paragraphs, selection
rectangles, shaped Arabic/Hebrew carets with the installed DejaVu face, RTL
IME preedit. Compositor (`scripts/smoke_luna_atspi.sh`, labwc 0.7.2 under
`/opt/labwc-sg5`): `wtype` types مرحبا, שלום and `abc שלום 123` into Run; the
AT-SPI probe reads the logical text and caret after each key; the `grim` field
crop (`scripts/sg5_field_geometry.py`) shows the RTL ink ending at the text box
right edge (x 288 of 290, left half empty), the End caret at the ink's left
edge, Home at x 290, Left/Right moving the painted caret one cluster; the mixed
LTR paragraph stays left-aligned with End at the ink's right edge and the first
Left landing on logical caret 5 (crossing the visually rightmost shin).
`SG5_KEEP_DIR` keeps the crops. The SG3 `luna`/`luna-nofonts` smoke shows an
RTL notification summary ending at the row's right inset (without system
fonts the Arabic row is one `?` per grapheme, still right-aligned). Not claimed: UI
chrome mirroring for RTL locales, multi-line bidi paragraphs, exact-head CI,
physical Fcitx/IBus/Orca review.

## Remaining blockers before issue #417 SG5 can be checked

- The external IME v2 -> compositor -> v3 **Run** protocol smoke passed #551 head (Native 44673725266). **Rename** and its dialog focus leave/re-enter now pass locally (labwc 0.7.2, 26 November 2026, see above; not yet on exact-head CI). Still open: menu-surface focus leave/re-enter and real candidate selection/RTL flows. One scripted Japanese transaction is not full IME parity.
- Native Run/Rename clipboard shortcuts are already **merged in #557**, and the current source contains live `wl-copy` ↔ native editor ↔ `wl-paste` regression steps. Full cross-app selection transfer/focus/cleanup must still be confirmed on the exact final source in a private labwc session; the historical merge does not by itself certify the final SG5 matrix.
- Start Menu Search and All Programs both pass the external keyboard/AT-SPI editing smoke. The menu v3 focus target, preedit and commit handling, deletion and composition painting remain open. [SG5 issue #595](https://github.com/CopyPasteUser/Ricebowl/issues/595)
- Real XDG Rename AT-SPI focus/text/caret/selection/cancel client PASSED #551 exact-head CI (Native 44673725266); Rename IME protocol and focus cycle covered locally; AT-SPI action invocation for the Rename menu item and OK/Rename/Cancel dialog buttons, plus refused/cancelled/confirmed transitions, now pass locally (27 November, not yet on exact-head CI). Trash and Properties actions are not driven by the smoke.
- Positive Hindi/CJK/Hangul: shaping, caret metrics and real compositor glyphs are proven locally with the trusted system font fallback (28 November); private recipe fonts remain unshaped and 1 MiB-capped by design and do not use it. Arabic/Hebrew RTL paragraphs (direction, right alignment, caret, arrows) now have local compositor evidence (28 November section). Still open: exact-head CI and physical-device review.
- After software gates, **physical** Mint/ThinkPad Fcitx/IBus, Orca, mixed-DPI/GPU rendering and keyboard-layout switching. Physical acceptance is not claimed by CI.

No proprietary fonts, resident polling service, unsafe recipe execution or modification of XFCE/X11 defaults are introduced.
