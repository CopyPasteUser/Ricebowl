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
| Clipboard | selected multi-grapheme Run / Rename text | Ctrl+C/Ctrl+X/Ctrl+V must preserve UTF-8, selection and focus without shell execution | **Merged #557** implements seat-scoped `wl_data_device` ownership/receive and atomic validation; `scripts/smoke_luna_atspi.sh` includes real external `wl-copy`/`wl-paste` round trips and negative invalid-text coverage. Revalidate on final exact-main source; do not infer physical acceptance |
| BiDi | abc + Hebrew, mixed Arabic ABC 42 | logical storage; visual caret and arrow movement via same visible substring | Rust bidi_layout/luna_dialog tests; real RTL client review open |
| Arabic/Indic | Arabic salaam, Hindi हिन्दी | OpenType GSUB/GPOS and nonzero bounded glyph positions only if real font covers glyphs | style_art/native_shaping Rust tests; positive Hindi font fixture acceptance open |
| CJK | 日本語, 中文, 한국어 | UTF-8 commits and clearly rendered fallback where coverage unavailable; never label '?' as CJK success | existing missing-cmap tests; positive CJK font-specific acceptance open |
| Missing fonts/glyphs | U+10FFFF and missing joined emoji | visible replacement metrics and pixels; no false font-coverage success | existing negative style_art tests |
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

## Remaining blockers before issue #417 SG5 can be checked

- The external IME v2 -> compositor -> v3 **Run** protocol smoke passed #551 head (Native 44673725266). **Rename** and its dialog focus leave/re-enter now pass locally (labwc 0.7.2, 26 November 2026, see above; not yet on exact-head CI). Still open: menu-surface focus leave/re-enter and real candidate selection/RTL flows. One scripted Japanese transaction is not full IME parity.
- Native Run/Rename clipboard shortcuts are already **merged in #557**, and the current source contains live `wl-copy` ↔ native editor ↔ `wl-paste` regression steps. Full cross-app selection transfer/focus/cleanup must still be confirmed on the exact final source in a private labwc session; the historical merge does not by itself certify the final SG5 matrix.
- Start Menu Search and All Programs both pass the external keyboard/AT-SPI editing smoke. The menu v3 focus target, preedit and commit handling, deletion and composition painting remain open. [SG5 issue #595](https://github.com/CopyPasteUser/Ricebowl/issues/595)
- Real XDG Rename AT-SPI focus/text/caret/selection/cancel client PASSED #551 exact-head CI (Native 44673725266); Rename IME protocol and focus cycle now covered locally; still missing AT-SPI action invocation and wider dialog transition coverage.
- Positive Hindi/CJK installed-font coverage plus measured rendered glyph/caret positions; negative missing-font replacement tests do not prove script support.
- After software gates, **physical** Mint/ThinkPad Fcitx/IBus, Orca, mixed-DPI/GPU rendering and keyboard-layout switching. Physical acceptance is not claimed by CI.

No proprietary fonts, resident polling service, unsafe recipe execution or modification of XFCE/X11 defaults are introduced.
