# SG5 — Native Unicode, IME and AT-SPI acceptance ledger

Status: **OPEN**. Gate authority: [issue #417](https://github.com/CopyPasteUser/Ricebowl/issues/417). The mainline SG5 evidence index remains **2/4**: implemented portions and historical tests do not complete native text/IME/accessibility parity.
Source-audit baseline: `main@fdbdf26a4a90cb31be8efa222e527609ad447751` (23 November 2026). PR #551 (Rename AT-SPI) and PR #557 (Wayland Run/Rename clipboard) are **merged**. Their feature presence is independently visible in source, but final exact-main SG5 acceptance and physical-device checks remain open.

## Inventoried native text surfaces

| Surface | Actual input owner | Editing and rendering | text-input-v3 | AT-SPI |
| --- | --- | --- | --- | --- |
| XP Run | luna_dialog::State(Kind::Run); compositor keyboard events through Super+R | complete grapheme carets, text selection, delete, preedit paint | wired via enter/preedit/delete/commit/done | transient TextInput and TextRun named Command; black-box client smoke added |
| Desktop File Rename | luna_dialog::State(Kind::FileRename) | same editor, rename only after explicit confirmation | shared Luna adapter | transient TextInput and TextRun named File name; real Wayland pointer → Rename external AT-SPI client smoke PASSED at #551 head (Native 44673725266) |
| Start Menu Search / All Programs | native_menu::MenuState::search; wl_keyboard | Unicode-batch insertion and UAX #29 backspace; append/delete-at-end, **not a full cursor editor** | **NOT wired**: compositor v3 Enter/Done still targets Run/Rename only | **Transient TextInput/TextRun already exposed** in `main.rs`; external keyboard/AT-SPI **Search** smoke is present; **Programs** needs its own live check, neither proves IME-v3 composition |
| Context menus, tray, calendar, desktop icons, RicePop | navigation/selection handlers, no text editor | keyboard actions and labels only | n/a without actual editor | supported actions where implemented, not fully client-validated |
| External search application | fuzzel and other Wayland applications | external application responsibility | external application responsibility | external application responsibility |

Do not count menu-search keyboard navigation as full native IME and AT-SPI parity.

## Concrete Unicode and native rendering matrix

| Test domain | Fixture | Required observable behavior | Evidence |
| --- | --- | --- | --- |
| UTF-8 / UAX #29 | e + combining U+0301, German flag, woman-technologist ZWJ, thumbs-up with modifier | no split graphemes under caret, selection, delete, clipping | Rust tests in luna_dialog, native_menu, text_render |
| Clipboard | selected multi-grapheme Run / Rename text | Ctrl+C/Ctrl+X/Ctrl+V must preserve UTF-8, selection and focus without shell execution | **Merged #557** implements seat-scoped `wl_data_device` ownership/receive and atomic validation; `scripts/smoke_luna_atspi.sh` includes real external `wl-copy`/`wl-paste` round trips and negative invalid-text coverage. Revalidate on final exact-main source; do not infer physical acceptance |
| BiDi | abc + Hebrew, mixed Arabic ABC 42 | logical storage; visual caret and arrow movement via same visible substring | Rust bidi_layout/luna_dialog tests; real RTL client review open |
| Arabic/Indic | Arabic salaam, Hindi हिन्दी | OpenType GSUB/GPOS and nonzero bounded glyph positions only if real font covers glyphs | style_art/native_shaping Rust tests; positive Hindi font fixture acceptance open |
| CJK | 日本語, 中文, 한국어 | UTF-8 commits and clearly rendered fallback where coverage unavailable; never label '?' as CJK success | existing missing-cmap tests; positive CJK font-specific acceptance open |
| Missing fonts/glyphs | U+10FFFF and missing joined emoji | visible replacement metrics and pixels; no false font-coverage success | existing negative style_art tests |
| Live compositor editing | empty, AB, Left, Backspace, select-all, replacement, Escape, reopen | external wtype wl_keyboard delivery and public AT-SPI text/focus/selection queries | Run and separate XDG Rename AT-SPI smoke passed at #551 head (Native 44673725266) |
| Sanitized accessibility text | e + newline + combining mark + Z | resegment final exposed text, caret and selection never refer to phantom cluster | added positive and negative AccessKit Rust tests |
| Full IME transaction | Japanese preedit and commit, 3-byte CJK delete + replacement | actual input-method-v2 producer must traverse labwc into the native text-input-v3 consumer, then report public surrounding text | external Rust v2 IME producer -> native Run v3 path passed #551 exact-head Native 44673725266 |

## Reproducible checks

1. Run cargo test --locked --manifest-path components/riceplate-wayland/Cargo.toml.
2. Run cargo clippy --locked --manifest-path components/riceplate-wayland/Cargo.toml --all-targets -- -D clippy::correctness -D clippy::suspicious -D clippy::perf -D unused_must_use.
3. Build cargo build --locked --release --manifest-path components/riceplate-wayland/Cargo.toml and cargo build --locked --release --manifest-path components/riceplate-wayland/Cargo.toml --example wayland_ime_v2_client.
4. Run sh -n scripts/smoke_luna_atspi.sh and /usr/bin/python3 -m py_compile scripts/smoke_riceplate_atspi_client.py.
5. With a private DBus/headless labwc environment and Ubuntu packages python3-pyatspi, at-spi2-core, wtype: timeout -k 5s 140s sh scripts/smoke_luna_atspi.sh.
6. Until December 2026, **do not invoke GitHub Actions**. Run the equivalent suites locally in disposable private Linux/labwc sessions on the exact branch HEAD, then repeat affected checks on the merged main. Missing provider, missing glyph, timeout or failed AT-SPI query is FAIL, never SKIP-as-PASS. The later formal release gates still require trusted exact-source hosted evidence.

**Protocol separation:** wtype injects ordinary wl_keyboard events. Separately, the CI-only wayland_ime_v2_client uses real input-method-v2 requests and verifies a text-input-v3 Japanese preedit, commit and Unicode byte deletion through the compositor. The fixture validates only the exact checked transaction on Run when CI passes; it is not a production Fcitx/IBus engine or coverage for Rename/menu search.

## Remaining blockers before issue #417 SG5 can be checked

- The external IME v2 -> compositor -> v3 **Run** protocol smoke passed #551 head (Native 44673725266). Still independently cover **Rename**, focus leave/re-enter and real candidate selection/RTL flows. One scripted Japanese transaction is not full IME parity.
- Native Run/Rename clipboard shortcuts are already **merged in #557**, and the current source contains live `wl-copy` ↔ native editor ↔ `wl-paste` regression steps. Full cross-app selection transfer/focus/cleanup must still be confirmed on the exact final source in a private labwc session; the historical merge does not by itself certify the final SG5 matrix.
- Start Menu Search / All Programs **already exposes an AT-SPI TextInput/TextRun** in current `main.rs` and has an external keyboard/AT-SPI **Search** smoke (Programs remains unverified). It still lacks a real **v3 text-input focus target, preedit/commit/deletion routing and composition painting**; follow [SG5 issue #595](https://github.com/CopyPasteUser/Ricebowl/issues/595). Accessibility exposure alone is not IME support.
- Real XDG Rename AT-SPI focus/text/caret/selection/cancel client PASSED #551 exact-head CI (Native 44673725266); still missing independent Rename IME protocol, AT-SPI action invocation and wider dialog transition coverage.
- Positive Hindi/CJK installed-font coverage plus measured rendered glyph/caret positions; negative missing-font replacement tests do not prove script support.
- After software gates, **physical** Mint/ThinkPad Fcitx/IBus, Orca, mixed-DPI/GPU rendering and keyboard-layout switching. Physical acceptance is not claimed by CI.

No proprietary fonts, resident polling service, unsafe recipe execution or modification of XFCE/X11 defaults are introduced.
