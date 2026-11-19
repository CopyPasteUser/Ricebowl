# SG5 — Native Unicode, IME and AT-SPI acceptance ledger

Status: **OPEN**. Gate authority: [issue #417](https://github.com/CopyPasteUser/Ricebowl/issues/417). The mainline SG5 evidence index remains **2/4**, not completed by this draft.
Baseline: main at 019f255fbc3fc07fddb68283f632e628f5226649 (19 November 2026).

## Inventoried native text surfaces

| Surface | Actual input owner | Editing and rendering | text-input-v3 | AT-SPI |
| --- | --- | --- | --- | --- |
| XP Run | luna_dialog::State(Kind::Run); compositor keyboard events through Super+R | complete grapheme carets, text selection, delete, preedit paint | wired via enter/preedit/delete/commit/done | transient TextInput and TextRun named Command; black-box client smoke added |
| Desktop File Rename | luna_dialog::State(Kind::FileRename) | same editor, rename only after explicit confirmation | shared Luna adapter | transient TextInput and TextRun named File name; external client acceptance pending |
| Start Menu Search / All Programs | native_menu::MenuState::search; wl_keyboard | Unicode-batch insertion and UAX #29 backspace; append/delete-at-end, **not a full cursor editor** | **NOT wired** | actionable search button and text summary; **not an editable TextInput** |
| Context menus, tray, calendar, desktop icons, RicePop | navigation/selection handlers, no text editor | keyboard actions and labels only | n/a without actual editor | supported actions where implemented, not fully client-validated |
| External search application | fuzzel and other Wayland applications | external application responsibility | external application responsibility | external application responsibility |

Do not count menu-search keyboard navigation as full native IME and AT-SPI parity.

## Concrete Unicode and native rendering matrix

| Test domain | Fixture | Required observable behavior | Evidence |
| --- | --- | --- | --- |
| UTF-8 / UAX #29 | e + combining U+0301, German flag, woman-technologist ZWJ, thumbs-up with modifier | no split graphemes under caret, selection, delete, clipping | Rust tests in luna_dialog, native_menu, text_render |
| Clipboard | selected multi-grapheme Run / Rename text | Ctrl+C/Ctrl+V copy/paste must preserve UTF-8, selection and focus without shell execution | **NOT implemented in the native Luna editor; blocking** |
| BiDi | abc + Hebrew, mixed Arabic ABC 42 | logical storage; visual caret and arrow movement via same visible substring | Rust bidi_layout/luna_dialog tests; real RTL client review open |
| Arabic/Indic | Arabic salaam, Hindi हिन्दी | OpenType GSUB/GPOS and nonzero bounded glyph positions only if real font covers glyphs | style_art/native_shaping Rust tests; positive Hindi font fixture acceptance open |
| CJK | 日本語, 中文, 한국어 | UTF-8 commits and clearly rendered fallback where coverage unavailable; never label '?' as CJK success | existing missing-cmap tests; positive CJK font-specific acceptance open |
| Missing fonts/glyphs | U+10FFFF and missing joined emoji | visible replacement metrics and pixels; no false font-coverage success | existing negative style_art tests |
| Live compositor editing | empty, AB, Left, Backspace, select-all, replacement, Escape, reopen | external wtype wl_keyboard delivery and public AT-SPI text/focus/selection queries | newly introduced native CI smoke; **pending workflow conclusion** |
| Sanitized accessibility text | e + newline + combining mark + Z | resegment final exposed text, caret and selection never refer to phantom cluster | added positive and negative AccessKit Rust tests |
| Full IME transaction | preedit, delete, commit, Done with valid byte offsets | atomic mutation, focus handoff, candidate commits on real compositor | Rust batch tests exist; **external IME producer protocol acceptance open** |

## Reproducible checks

1. Run cargo test --locked --manifest-path components/riceplate-wayland/Cargo.toml.
2. Run cargo clippy --locked --manifest-path components/riceplate-wayland/Cargo.toml --all-targets -- -D clippy::correctness -D clippy::suspicious -D clippy::perf -D unused_must_use.
3. Build cargo build --locked --release --manifest-path components/riceplate-wayland/Cargo.toml.
4. Run sh -n scripts/smoke_luna_atspi.sh and /usr/bin/python3 -m py_compile scripts/smoke_riceplate_atspi_client.py.
5. With a private DBus/headless labwc environment and Ubuntu packages python3-pyatspi, at-spi2-core, wtype: timeout -k 5s 140s sh scripts/smoke_luna_atspi.sh.
6. Accept only a green exact-PR-head Native RicePlate workflow. Missing provider, missing glyph, timeout or failed AT-SPI query is FAIL, never SKIP-as-PASS.

**Important limitation:** wtype injects wl_keyboard events, not input-method-v2 preedit/commit. This black-box AT-SPI test does not independently prove the Wayland text-input-v3 external IME path.

## Remaining blockers before issue #417 SG5 can be checked

- Real external IME text-input-v3 composition, cursor and surrounding-text deletion for both Run and Rename, including leave/re-enter and CJK/RTL flows.
- Native Run/Rename clipboard shortcuts need actual focused Wayland selection transfer and grapheme-safe pasting. Existing cross-application clipboard CI does not exercise the Luna editor.
- Start Menu Search / All Programs needs a real v3 text-input focus target, composition rendering and AT-SPI TextInput semantics, or explicitly scoped-out product contract approval.
- Real AT-SPI client test of Rename, bounded ranges, action invocations and transitions across supported native dialog surfaces.
- Positive Hindi/CJK installed-font coverage plus measured rendered glyph/caret positions; negative missing-font replacement tests do not prove script support.
- After software gates, **physical** Mint/ThinkPad Fcitx/IBus, Orca, mixed-DPI/GPU rendering and keyboard-layout switching. Physical acceptance is not claimed by CI.

No proprietary fonts, resident polling service, unsafe recipe execution or modification of XFCE/X11 defaults are introduced.
