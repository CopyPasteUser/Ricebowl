# RiceBowl DE — Wayland/labwc transition

**Status (November 2026): opt-in labwc session preview implemented;
physical acceptance outstanding.** RiceBowl 0.9.x is still an XFCE/X11
rice manager. The separate Wayland login-session package requires explicit
installation and is not yet a finished desktop environment.

### Hard stop: shared software BEFORE XP Luna polish and hardware sign-off (15 November 2026)

[Issue #417](https://github.com/CopyPasteUser/Ricebowl/issues/417) is the
single, binary acceptance checklist for **all seven shared DE software gates**
(SG1–SG7): shell/input, RiceSpice, RicePop, Creator/RicePack, text/IME,
distribution/recovery and exact-main acceptance. The software is **not
complete** just because Sprint 9 and its CI are green. Close individual gates
only with real implementation + negative tests + exact-head and post-merge
evidence; no invented progress percentage. Existing native features documented
below remain valuable incremental evidence, not blanket release acceptance.

After all shared software gates pass, polish XP Luna's OS-specific visual and
interaction fidelity through the shared engine. Only then perform the physical
Mint/ThinkPad/GPU/Orca/multi-monitor sign-off in `RELEASE_1_0_GATES.md`.
Optional RiceClip/RiceShot P1 features remain outside the core release block.

### SG2 BlueZ multi-adapter identity and recovery readback (17 November 2026; CI candidate)

- The existing RiceSpice Bluetooth workflow now binds the requested
  Connect/Disconnect operation to its **reviewed BlueZ adapter** as well as the
  device address. The shared system D-Bus transport rejects a missing or
  changed adapter and ambiguous matches; legacy address-only consumers may
  proceed only if exactly one live device matches across all adapters.
- On adapter replacement/hot-unplug, neither power nor connection readback
  may report success solely because a *different* adapter happens to have the
  requested state. All operations retain BlueZ ownership, bounded D-Bus
  calls, explicit user action and no automatic pairing/trusting.
- Negative tests cover duplicate addresses on distinct and same adapters,
  invalid/missing adapter paths, normal scoped device connect and changed
  adapter during both verified readbacks. This is incremental **SG2
  disconnected-provider safety**, not comprehensive Bluetooth pairing/Orca
  UX, automatic recovery or physical device acceptance.

### Sprint 2 – SG3 stale RicePop inbox selection guard (17 November 2026; CI candidate)

- A deliberate RiceSpice inbox snapshot now carries the verified Mako owner PID
  and immutable on-screen notification metadata only in the transient UI.
  Dismiss/Invoke on that UI checks the same live owner **before re-reading**
  private messages, then verifies the fresh ID still belongs to the shown
  summary, body, application and urgency before the fixed Mako action.
- A restarted notification owner, replaced message with the same numeric ID,
  malformed expected snapshot or vanished action fails closed with an explicit
  error. Existing CLI calls still validate live IDs/actions and remain
  backward compatible without the optional UI-only snapshot constraint.
- Negative tests exercise owner replacement, ID reuse, safe current actions
  and missing metadata. An additional deliberate **Refresh RicePop inbox**
  button now replaces the old GTK notification widgets rather than appending
  duplicate stale rows. Successful Dismiss/Invoke actions also refresh the
  same inbox in place, rather than closing the user's context; page navigation
  frees the private widget references.
  No read occurs until requested, no resident timer/poller and no second owner.
- These are **partial SG3 software gate improvements**, not complete
  push-based live updates, Orca/AT-SPI or hardware sign-off; never
  expose the private inbox automatically or persist its contents.

### Sprint 2 – SG3 optional event-driven RicePop inbox (17 November 2026; CI candidate)

- After the user explicitly opens an **owner-verified inbox**, RiceSpice may
  subscribe to Mako's existing session D-Bus signals. Mako 1.11+ emits the
  `Notifications` property change for additions/replacements; older Mako
  versions only offer standard closed-notification signals, so manual refresh
  remains the honest fallback for new arrivals. No polling, daemon or
  eager notification disclosure is introduced.
- The signal payload triggers only a fresh `inspect_owned()` read; host PID,
  config and bus ownership are rechecked by the existing secured bridge.
  Restart/foreign-owner changes discard stale private rows immediately while
  retaining the manual refresh button. A busy GTK worker coalesces subsequent
  change events rather than dropping the last update.
- Subscriptions are released on page navigation/window close; partial
  subscription failures unwind cleanly and leave manual refresh available.
  Deterministic tests cover event classification, teardown, lost owners,
  coalescing and no events on unrelated pages. This is incremental SG3
  software progress, **not** full translated/Orca/native notification OSD
  acceptance or physical Mint sign-off.

### Sprint 2 – SG2 verified audio stream ownership (17 November 2026; CI candidate)

- RiceSpice's on-demand per-application audio controls now require a genuine
  PulseAudio/PipeWire `client` identity, not just a possibly reused sink-input
  index, sink, volume or mute value. Streams without a verifiable client remain
  visible as read-only with an explicit unavailable state.
- Output/volume/mute mutations compare the displayed client before issuing
  fixed pactl commands and again after readback. Stale clients fail closed;
  a client switch after an attempted change reports an uncertain mutation.
  The existing optional CLI-style calls retain their previous parameter
  contract and stale state checks.
- Native Python tests cover replaced clients, invalid IDs, post-write
  uncertainty, normal verified changes and the read-only GTK presentation.
  This is **incremental SG2 progress**, not completion of all providers,
  real PipeWire hardware behavior, recovery or full software signoff.

### SG1 desktop Unicode prefix selection (17 November 2026; CI candidate)

- Native XP Luna shortcut **and** XDG file type-to-select now use one
  case-insensitive prefix matcher that requires a complete extended grapheme
  boundary. A single person emoji cannot accidentally select a ZWJ profession
  emoji, and a plain Latin base cannot prematurely match half of a combining
  accent. Hidden/other-output peer filtering and focus leases remain unchanged.
- Deterministic Rust tests cover combining sequences, ZWJ emoji, case folding,
  candidate order, control input and out-of-bounds prefixes. No new dependency,
  background work, XFCE/X11 change, or locale-specific search claim.
- This is incremental **SG1/SG5** correctness evidence only, not completion
  of the Unicode normalization, external IME, Orca, keyboard or hardware gates.

### SG1 cross-output context placement integration (16 November 2026; CI candidate)

- The keyboard focus and file/shortcut context paths now share the same output
  precedence: actual compositor **bound output**, then explicitly associated
  Wayland surface output, and only then the primary fallback. A secondary
  monitor must not be overridden by a primary-output shortcut during menu
  positioning, desktop file reflow, or icon output hotplug/recovery.
- Both XDG file and XP shortcut context menus use the common output resolver;
  layout, drag and reflow callsites consistently retain surface-over-primary
  precedence. No new compositor, monitor override or persistent configuration.
- Pure Rust regression proves missing-bound secondary-output choice, valid bound
  precedence and absent-output fail-closed behavior. Require exact stacked-head
  Native Rust/Clippy, labwc multi-output and Python tests, followed by both
  ordered integration merges and post-merge main verification.

This does **not** substitute for physical multi-monitor, mixed-DPI, IME or
Orca/AT-SPI acceptance, and SG1/SG5 remain open.

### SG1 cross-output desktop keyboard and context-menu isolation (16 November 2026; pending CI)

- **File contexts:** The native Menu and Shift+F10 actions now resolve a file
  target exclusively among compositor-placed icons on the confirmed keyboard
  focus output. Duplicate file keys on another monitor are never used for a
  context action, even when that monitor's layer appears first.
- **XP Luna shortcuts:** Before invoking actions, opening context menus, or
  navigating, the existing compositor-granted keyboard lease must still
  match the shortcut's real current output. Displaced/hidden icons revoke
  stale focus. Tab, arrow, type-to-select and Ctrl+A operate on peers on the
  same resolved output; an explicit secondary output cannot be incorrectly
  shadowed by the primary-output fallback.
- Deterministic Rust regressions check duplicate keys, missing/hidden
  targets, output precedence and missing leases. Native Rust/Clippy, real
  headless labwc and package tests plus exact-main CI must pass before merge.
- The conservative IME Return echo guard is **unchanged**: without external
  IME timing evidence, relaxing it could accidentally execute a Run command.
  External IME, keyboard/Orca AT-SPI interaction and hardware multi-display
  testing remain separate SG1/SG5 release gates; neither is signed off.

### SG1/SG5 input, focus and AccessKit correctness (16 November 2026; gated)

- **IME echo:** The 80 ms text-input-v3 keyboard echo guard now records the
  actual bounded committed UTF-8 text. It consumes only the exact duplicate
  text or a candidate-confirming Return. A different freshly typed character
  immediately after IME Done is never eaten; the mismatch disarms the guard.
  Escape, Backspace, pointer and ordinary navigation retain precedence.
  Composing preedits still own editor keys; all text is transient and unlogged.
- **Desktop focus:** An active modal/menu receives keyboard events ahead of a
  stale desktop focus lease. File arrows and type-to-select now consider only
  compositor-placed icons on the exact focus-lease output, not hidden inventory
  or another monitor. Hotplug, file disappearance or output movement revokes
  the invalid target without launching or deleting an unrelated file.
- **Accessibility:** Native AccessKit editor and label snapshots preserve full
  extended grapheme boundaries under the scalar cap. A sanitized control or
  truncated multi-scalar cluster cannot leave its caret/selection pointing
  inside a missing character. Temporary user text remains only in the active
  semantic editor model and is never copied into the node label.
- Deterministic Rust regressions cover unmatched/matching IME echoes, expiry,
  preedit ownership, same-output navigation, stale focus output, Unicode
  text sanitization and caret projection. Require exact-head Rust/Clippy,
  true compositor smoke and post-merge main tests before acceptance.

**Scope:** This is a focused SG1/SG5 correctness improvement, **not** a
claim of complete software gate closure. External real IME client injection,
multi-device IME/Orca and full AT-SPI interaction acceptance are still pending;
the separate hardware sign-off remains mandatory.

### SG3 explicit RicePop inbox in RiceSpice (16 November 2026; CI candidate)

- RiceSpice now offers a session-scoped **Show RicePop inbox** action. It loads active
  notifications and bounded Mako history only after deliberate activation, never
  automatically during settings navigation. The GTK inbox uses normal selectable
  text and keyboard-focusable, individually labelled buttons; history is read-only.
- The backend revalidates the owned Mako D-Bus PID/config **before and after**
  both inventory reads. Foreign XFCE buses and owner switches fail closed; active
  Dismiss/Invoke use the existing independent live ID/action and owner checks.
  No second notification daemon, resident poller, persistence or global desktop
  change is introduced. A page refresh removes the transient inbox.
- Software regression tests cover unverified/restarted hosts, lazy privacy,
  button bindings, stale-action delegation and history immutability. This is a
  **partial** SG3 UX improvement, not live push updates, complete AT-SPI,
  translated interface, accessible OSD or physical Mint/Orca sign-off.

### SG3 active RicePop host ownership (16 November 2026; CI pending)

- Active notification **Dismiss** and **Invoke** now validate the exact active Mako D-Bus owner PID and owner-private Mako configuration both before the fresh active-ID/action inventory and again just before mutation. A different host, unexpected owner, stale ID, unsupported action, or D-Bus failure stops with an explicit error rather than invoking a notification in a different session.
- Normal XFCE and a nested labwc preview inheriting XFCE's user bus cannot mutate an unrelated notification owner. A nested RiceBowl session with an explicitly new private `dbus-run-session` may still dismiss its **own** Mako messages, preserving the disposable real-host CI smoke. The existing Do Not Disturb action remains full-login-only.
- Tests cover foreign/inherited sessions, private nested ownership, host changes between read and write, and non-mutating failure. This is partial SG3 correctness, not notification history, action accessibility or physical hardware release sign-off. Exact PR-head CI required before merging.

### SG5 text-input-v3 post-commit keyboard recovery (16 November 2026; gated)

- The native Run/Rename IME handler no longer retains a permanent `received_commit` latch after a successful compositor `Done` event. That state previously blocked subsequent printable input and Run Enter/Escape until the dialog lost/reacquired focus.
- A recent IME commit can suppress **at most one** eligible compositor key event within an 80 ms echo window; an unrelated modifier/navigation key does not consume the allowance. Later keyboard input, Return and Escape resume their normal handling without changing the compositor-owned IME focus policy.
- Pure Rust regressions cover the transient duplicate echo, expiry, out-of-order events and active preedit ownership. Exact-head Native Rust/Clippy and labwc CI plus post-merge main verification are required. No physical IME keyboard/Orca sign-off or SG5 completion is claimed by these tests.

### SG5 IME selected-text preview correctness (16 November 2026; CI gate)

- Native Run and file-rename text-input-v3 preedit now renders at the **start of the selected range** rather than at the old caret byte offset. Previously a short IME preedit after Ctrl+A / Shift-selection could index past the shortened preview string and crash the native renderer.
- The 192-scalar input budget counts the **post-replacement** text, so a 192-character filename can be entirely selected and preview-replaced by a short Japanese/Arabic IME composition. Invalid over-budget partial replacements still fail atomically; neither noncommitted preedit nor a rejected edit changes the real command or filename.
- Rust tests cover selection replacement, Unicode graphemes, full-capacity and over-budget cases. Require exact-head Rust/Clippy and real native labwc CI and post-merge `main` verification. **SG5 is still open:** external compositor/IME end-to-end, font fallback, selection/Orca behavior and physical hardware remain separate checks.

### SG1 repeated real compositor focus handoff (16 November 2026; CI candidate)

The native labwc integration smoke now performs three additional genuine
pointer-selection → compositor keyboard Enter → typed shortcut prefix →
Escape/revoke cycles using the same seat, then continues the existing
context-menu and XWayland checks. Every round requires fresh focus and input
receipts in the RicePlate log. No mock keyboard-enter events, elevated host
privileges or XFCE mutations are involved.

This tests a previously intermittent handshake under repeated activation.
It does **not** establish the historical race's root cause is fully fixed,
does not include physical input/IME/Orca acceptance and does not close
parent SG1/SG7 or issue #417. Only a successful exact-head native workflow
and a successful post-merge main run can accept this regression gate.

### SG1 focus stress + SG5 atomic native compose events (16 November 2026)

- **SG1:** The pure DesktopFocusLease CI test now explores 4,096
  deterministic six-event sequences (compositor Enter, wrong seat, Leave,
  deadline), then verifies fresh-surface reacquisition, rejection of stale
  tickets and fail-closed late Enter. This supplements, but never replaces,
  the separate real headless labwc keyboard/seat acceptance.
- **SG5:** Native Luna Run and Desktop file-rename editors now accept one
  complete compositor-provided UTF-8 commit event containing multiple
  grapheme clusters. The editor checks the complete input and scalar limit
  *before* insertion, atomically rejects invalid commits and recalculates
  the cursor at grapheme boundaries. Existing individual-key semantics
  and the no-shell Run execution contract are preserved.
- **Not yet covered:** Real Wayland text-input-v3 IME preedit/surrounding
  text, HarfBuzz/OpenType complex-script shaping, BiDi layout, keyboard-only
  assistive technology and physical Mint/GPU release sign-off. All parent
  SG1–SG7 acceptance gates remain open until separately evidenced.

### Shared software mega-sprint – SG1/SG3/SG4/SG5 correctness slice (15 November 2026)

- **SG1 / native desktop stability:** Owner-private 48px icon paints clip to
  the actual pixel buffer rather than indexing beyond a short, hotplugged or
  partially offscreen output; malformed bitmap buffers and u32-max drag
  coordinates cannot crash native RicePlate.
- **SG3 + SG5 / Unicode:** Native bitmap label layout now measures and paints
  exactly one fallback cell per extended grapheme, with unchanged single-scalar
  Latin/Greek/Hiragana sprites. RicePop's body wrapping and paging run in a
  bounded linear pass over grapheme clusters and do not split combining marks,
  flags, modifiers or ZWJ sequences.
- **SG4 + SG6 / Creator evidence:** The two-rice native gallery uses an
  owner-scoped staging directory on the destination filesystem and publishes
  PNGs with collision-safe hardlinks, the manifest last. Any failed native
  render, format/geometry/IDAT validation or atomic publication rejects the
  whole result without leaving an incomplete gallery. Focused tests exercise
  successful full-matrix publication and second-render failure rollback.
- These are **shared software regressions**, not completion of SG1–SG7.
  Multi-script shaping and RTL, IME composition, full interactive two-rice
  acceptance, comprehensive settings/notification feature parity and signed
  final 1.0 packaging remain open. Require exact-head Tests and Native CI,
  followed by post-merge `main` CI before calling this slice accepted.

### Sprint 9+ – Native Creator capture decode gate (15 November 2026; CI candidate)

The isolated two-rice Creator handoff now checks both valid PNG chunk CRCs
and fully decoded IDAT pixels for every `grim` capture before trusting the
render receipt SHA-256. A CRC-clean but zlib-corrupted image, missing PNG IEND
and wrong geometry are rejected by regression tests in
`tests/test_wayland_creator_handoff.py`. No host session or rice selection is
modified. Mark the new implementation accepted only after exact-head Tests and
Native RicePlate CI plus post-merge `main` checks.

### Sprint 9 – bounded native font fallback for private recipes (15 November 2026; candidate)

Private Creator-selected fonts now resolve each extended grapheme cluster to
**one complete face**: the selected font first, then the bundled, OFL-licensed
Liberation Sans face. Measurement, clipping and painting use the same resolved
font/character pairs and font-specific kerning. The dynamically rasterized
glyph cache distinguishes primary and fallback faces and keeps its existing
512-entry cap. The bundled fallback parses at most once per RicePlate process;
no host font discovery, network, resident worker, new crate or changed default
Luna/bitmap font rendering is required. Rust tests verify a real missing
primary glyph renders through the secondary face (not '?'), that glyph pixels
and cached face identity agree, and that the default Luna font is untouched.

**Limits:** This is a portable fallback for glyphs contained in Liberation Sans,
not a CJK/emoji font stack or automatic arbitrary-font fallback. Per-codepoint
fontdue rasterization still cannot claim HarfBuzz/OpenType shaping, Unicode
bidirectional layout or IME support. All of those remain mandatory separate
software gates. Do not mark the typography or RiceBowl 1.0 release as complete
from this slice alone.

### Sprint 9 – portable Creator fonts in native two-rice acceptance (15 November 2026; candidate)

The isolated two-rice Creator export/import → native labwc screenshot matrix
now imports a real bundled, OFL-licensed TrueType font as a private asset.
Both distinct Creator drafts reference it; both RicePacks preserve identical
font bytes, content IDs and attribution across separate author and importer
`XDG_CONFIG_HOME` trees. The QA path validates the imported IDs and
licensing before capturing each installed rice at two output geometries and
testing selection rollback. It never mutates a live user session or relies on
whatever fonts happen to be installed on the CI host.

This is a real portable-asset/render round trip, not a GTK file-picker,
physical interactive authoring, universal font fallback or complete 1.0
Creator parity claim. Exact-head native CI and post-merge `main` checks
remain mandatory.

### Sprint 8b – single-revision Wayland package provenance (15 November 2026; CI-gated)

The four optional Wayland Debian packages now stamp the committed Git source
revision in `X-RiceBowl-Source-Commit` metadata. The read-only set verifier
requires every stamp to be the same 40-character lowercase commit ID and
requires it to match the core application's embedded `BUILDINFO`. Mixing
native/session/meta binaries from different source commits is rejected even
when their Debian dependency versions remain compatible. Release-bundle
verification fails closed for source exports without a verifiable Git commit;
such exports may still build standalone preview packages.

Tests cover unchanged-commit rebuilds, a mixed native package and an unverified
package. This is **package-source consistency**, not a proof that a supplied
native ELF was compiled from that source, binary bit-reproducibility across
hosts, cryptographic signatures or a public 1.0 distribution. The CI assembly
must still build the native ELF from the matching commit and verify its
checksum, and clean-install/real-hardware signoff remains open.

### Sprint 8b – Unicode grapheme-aware native missing-glyph fallback (15 November 2026; CI-gated)

The native TrueType path now maps any **unsupported extended grapheme**
(combining sequences, flags or ZWJ emoji) to one visible replacement glyph
instead of a misleading series of question marks for individual scalars.
The same allocation-free grapheme iterator drives drawing, width measurement
and ellipsis-fitting, including fixed-cell custom TrueType recipes; supported
Latin text and kerning are unchanged. Regressions compare actual painted
pixels and widths for flags, joined emoji and modifier sequences.

This is a readable, bounded missing-glyph fallback **within the selected
font**, not multi-font fallback, HarfBuzz shaping, RTL/BiDi, glyph
substitution or IME support. Those are still separate open typography and
hardware gates, not accepted by this slice.

### Sprint 8b – compositor-delivered composed shortcut input (15 November 2026; CI-gated)

The native Luna and XDG desktop Type-to-Select paths now accept **one complete
Unicode extended grapheme** from an existing compositor-authorized Wayland
keyboard event, rather than requiring exactly one Unicode scalar. This allows
a correctly delivered combining sequence, joined emoji or modifier sequence
to participate in the same bounded prefix search as plain Latin input.
Control sequences, multiple graphemes and overlong input remain rejected.
Appending a multi-scalar grapheme cannot exceed the existing 48-scalar
prefix limit; overflow resets the old prefix first. Selection still requires
the real same-seat `wl_keyboard.enter` lease, never synthetic keyboard focus.

Pure Rust tests cover composed characters, flags, ZWJ emoji, invalid control
input, capped prefix accumulation and selection. This is **not** a completed
Wayland text-input-v3/IME integration, canonical Unicode normalization or
physical keyboard/Orca acceptance.

### Sprint 8b – preserve compositor keyboard focus on unchanged output layout (15 November 2026; CI-gated)

The native Luna desktop previously tore down an active or pending keyboard
focus lease on **every** output reflow, including redundant compositor output
notifications where the selected shortcut did not move. The reflow path now
compares the selected shortcut's actual output identity and logical position
before/after layout. An unchanged target retains its existing
compositor-confirmed lease; moved/removed targets and output replacement
still revoke it. This preserves genuine user-initiated compositor
`wl_keyboard.enter` requirements, never fabricates focus and never expands
the 8px temporary focus surface or background input-grab lifetime.

A pure Rust regression covers no-op, moved, replaced-output and removed
icons, while native CI exercises the existing real labwc shortcut focus,
Escape, app handoff and multi-output contract. Issue #328 remains open until
a repeated-focus stress test and actual Mint/ThinkPad keyboard/IME/Orca
acceptance confirm that the intermittent failure has disappeared.

### Sprint 8 release-source and CI provenance (15 November 2026; integrated)

- [#401](https://github.com/CopyPasteUser/Ricebowl/pull/401) binds a stable
  1.0 hardware sign-off to the **actual tested ancestor commit**, rejecting
  source changes after the physical test (except the sign-off JSON).
- [#403](https://github.com/CopyPasteUser/Ricebowl/pull/403) blocks release
  source artifact assembly unless the exact code revision has completed,
  successful Tests, Native RicePlate and Wayland session workflows on
  `main`. Native/session CI may be manually dispatched on that exact commit
  because their ordinary triggers are path-filtered.
- A 1.0 release remains blocked by the pending
  `.github/release-signoff-1.0.json` and all real-device gates. These
  software checks do not certify physical Mint/ThinkPad hardware, IME/Orca,
  real GPU ScreenCast or a finished release.
- CI reliability follow-up: [#328](https://github.com/CopyPasteUser/Ricebowl/issues/328)
  records one transient failure to obtain compositor-confirmed desktop shortcut
  focus on `main@91b1276` (Native CI attempt 1). The identical run passed
  on retry without relaxing assertions; stress and physical acceptance remain
  open.

Integration: [#400](https://github.com/CopyPasteUser/Ricebowl/pull/400),
[#401](https://github.com/CopyPasteUser/Ricebowl/pull/401),
[#402](https://github.com/CopyPasteUser/Ricebowl/pull/402) and
[#403](https://github.com/CopyPasteUser/Ricebowl/pull/403) are merged.
Final-head tests passed for all four changes; the exact merged-main run of
`#403` is evaluated separately under
[CI run history](https://github.com/CopyPasteUser/Ricebowl/actions).

### Sprint 8 native TrueType missing-glyph consistency (15 November 2026; merged, CI-gated)

The native font rasterizer now resolves unmapped Unicode codepoints to
the **same visible '?' glyph for advance, kerning and painting**. Its eager
ASCII/Latin cache no longer preloads a font's missing-glyph `.notdef` raster
as though it were a supported character. A regression verifies actual painted
pixels and measured width against the fallback for a valid missing Unicode
noncharacter. This improves honest unavailable-glyph behavior without a new
font worker, host font changes or extra dependencies. It is **not** a complete
font fallback stack, bidirectional layout or OpenType shaping implementation;
native PR and post-merge compositor CI passed; physical device and mixed-script rendering remain separate release gates.

### Sprint 8 native proportional label fit (15 November 2026; merged, CI-gated)

Native text fitting now considers the **whole grapheme prefix together with
its ellipsis**. Independent per-grapheme width sums ignored TrueType kerning
between neighboring graphemes and at the suffix. The new linear-time font
path uses the same `fontdue` advances/kerning as measurement and painting,
including a bounded fixed-cell path, and preserves the original bitmap
rendering and UAX #29 boundaries. Regression coverage compares results
against a complete-prefix reference across Latin kerning, combining marks,
joined emoji and flags. This is **not** bidirectional layout, OpenType
shaping or fallback-font acceptance. Final-head and post-merge native CI passed, including the compositor smoke;
physical device and complex-script acceptance remain separate.

### Sprint 7 native Unicode grapheme-safe labels (15 November 2026; CI-gated)

Native task/menu label ellipsizing now iterates Unicode **extended grapheme
clusters (UAX #29)** using one pinned, dependency-light Rust crate, instead
of splitting at scalar/codepoint boundaries. Combining accents, emoji skin
tone modifiers, ZWJ emoji sequences and regional flag pairs cannot be cut
in half. The measured fitting width and existing bitmap/TrueType drawing
paths remain unchanged for ordinary text, avoiding changes to classic/XP
pixel baselines and preserving existing font choice/face support.

This closes **label truncation correctness**, not full HarfBuzz/OpenType
shaping, Unicode bidirectional layout or fallback-font selection; those
remain tracked as separate 1.0 typography gates.

### Sprint 7 Creator historical schema migration (15 November 2026; pending CI)

Creator can open installed schema-v1–v9 recipes and previously imported legacy
RicePacks through a **one-way, data-only migration to a new schema-v11 draft**.
The installed source is pinned by its parsed semantic hash and never modified.
Pre-v3 sections become equivalent widget nodes. Existing menu, wallpaper,
shortcuts, colors, responsive layout, widgets and v9 components are retained
where they existed; absent newer UI features use validated defaults.
For v1–v4, which never defined desktop icons, the mandatory v11 icon
contract adds exactly **one clearly disclosed Applications shortcut**
(instead of copying the template's two demo icons). No composition widgets
are injected. A new immutable
`migrate` root history receipt preserves verified RicePack author/wallpaper
provenance for private edit, fork and export. Invalid assets, a stale installed
hash and an untrusted source fail before publishing a draft. The GUI displays
the migration before installation and never applies or selects it.

Migration does **not** claim visual pixel parity between historical backend
versions or full arbitrary-font shaping. Physical Creator/picker tests,
complete mixed-script typography and signed public distribution remain
separate release gates.

### Sprint 6 system services: early lock guard and polkit failover (15 November 2026)

The full labwc login now checks that its freshly spawned swayidle pre-suspend
lock guard has not already exited **before** starting the panel, wallpaper,
notifications or authorization agent. Its existing continuous monitoring still
fails closed when swayidle dies later. A nested preview remains unprivileged and
does not start or own an idle guard.

For an opt-in full session, a failed polkit authentication agent can now hand
over **once** to a different allowlisted installed provider. A healthy agent
is never duplicated; clean exits remain non-restarting, and failed alternatives
are bounded. Normal RicePop/Orca restarts preserve their prior one-retry
contract. No systemd, XFCE autostart or global polkit configuration changes.

Automated software gates cover immediate guard exit, a running guard, crashed
polkit handover, all-alternatives-fail and no restart storm. Real login,
logind suspend, password prompts and physical Mint acceptance remain open
release gates, not approved by mocked child processes.

### Sprint 6 system integration: non-activating D-Bus owner diagnostics (15 November 2026)

`ricebowl de integration-health --json` provides an explicitly on-demand,
read-only inventory of six allowlisted service owners: the existing
desktop portal, notifications, logind, PolicyKit authority, NetworkManager and
BlueZ. It calls only the D-Bus daemon's `NameHasOwner` method with a fixed
argument list, 1s bus-reply limit and 2s process timeout. It never starts a
service, changes device state or returns private bus endpoints or raw output.

The command requires markers and an owned Wayland socket from a **full**
RiceBowl login; when invoked under XFCE, another desktop, a nested preview or
a missing/unsafe Wayland socket, every provider remains `not-run`.
`not-owned` means no current name owner, **not** that a package is missing
or its functionality broken. PipeWire, hardware, GPU portal consent,
application behavior and physical suspend remain separate release tests.

### Sprint 5 disconnected control-owner recovery (15 November 2026, CI-gated candidate)

The existing bounded zero-capacity radio/audio control channel now distinguishes
a busy `Full` rendezvous from `Disconnected`. On a confirmed receiver
disconnect, RicePlate drops its stale control sender, invalidates the last
status and shows verified operations as unavailable on menu, panel, desktop
and AT-SPI surfaces. A worker-exit guard additionally signals the event loop even while a
separate audio observer keeps the status channel alive; channel closure also
invalidates pending operations and readback. No new polling thread, retry
daemon, privileged service or unsafe command is introduced. A native
regression verifies busy-vs-disconnected behavior and capability revocation.

This is a fail-closed software-recovery increment, not automatic backend
reconnection or physical device acceptance. A crashed control worker can
require restarting the opt-in RicePlate session; CI and release gates stay
open until exact-head and post-merge checks succeed.

### Sprint 5 visual menu control feedback (15 November 2026, CI-gated candidate)

Native and compact launcher menus now use the same bounded verified hardware
control snapshot as the panel, desktop widgets, and AT-SPI actions. The visible
radio/audio labels indicate current state or Wait/Busy/N/A/Retry; unavailable
controls use the existing disabled color and failure permits an explicit retry.
XDG app launchers, static actions, accessibility targets, keyboard ordering,
existing Luna menus and Waybar fallback remain unchanged. A Rust pixel-level
regression exercises both menu sizes and the worker-absence transition.
This is software-only runtime consistency, not physical Bluetooth/audio,
screen-reader or final RiceBowl 1.0 signoff. Exact-head plus post-merge native
CI must be successful before treating the candidate as accepted.

### Sprint 5 control availability and Creator contract integration (15 November 2026)

The native primary and mirror panel painters now read the same actual control
worker availability as their AT-SPI buttons, desktop action widgets and menu.
If the bounded owner worker disappears, panel controls must paint disabled
rather than visually advertise a clickable radio/audio action. The common
ControlFeedback state machine remains the authority; native pixel regression
tests inject a healthy hardware snapshot with an absent worker. Unrelated
static actions, fallback menus and legacy rices keep their prior behavior.

The Creator's read-only runtime inventory now announces the native
ready/applying/busy/unavailable/failed contract for both panel and menu
verified controls. It also handles schema-v3 grouped panels with no schema-v4
compact layout without inventing responsive behavior. Neither inventory nor
this software regression is a live backend or hardware proof.

These fixes are an incremental Sprint 5 integration, **not** a completed
RicePlate/RiceSpice/RicePop 1.0 or physical release sign-off. Exact-head and
post-merge native/Tests CI must pass before calling them accepted.

### Sprint 5 native menu AT-SPI control state parity (15 November 2026, CI-gated candidate)

The shared native menu now exposes the **same** verified Wi-Fi/Bluetooth/audio
readback, pending/busy/unavailable/failed labels and safe retry policy as its
panel and desktop control counterparts. AT-SPI targets for unavailable or
in-flight hardware are removed until the current owner worker confirms its
state; recipe-provided app actions retain their labels and existing launch
policy. The existing explicit logout guard also announces unavailability.
No duplicate backend or untrusted command execution is introduced. Unit and
real compositor CI must pass on the final PR head; physical Orca interaction
is deferred to the hardware acceptance phase. This is an incremental Sprint 5
step, **not** blanket shell parity acceptance.

### Sprint 5 shared-shell status parity (15 November 2026, CI-gated candidate)

The schema-v9 shared status component vocabulary is extended with a
read-only `bluetooth` binding for the existing BlueZ default-controller
power readback. The same source resolves into a native panel indicator,
desktop status widget, and Waybar's native Bluetooth module in fallback mode.
The native verified `bluetooth-toggle` control remains a separate explicit
action; tapping a status indicator never changes radio power, and unavailable
controllers are labeled N/A rather than assumed off. Headless Rust parser,
framebuffer-difference and noninteractive hit tests plus Python catalog,
compact-layout/Waybar and unsafe binding regressions are required. A real
labwc compositor smoke renders the opt-in quick-controls sample. Physical
Bluetooth hardware, Orca and mixed-DPI signoff remain explicitly pending.

This is one Sprint 5 component-parity increment, **not** completion of every
RicePlate/RiceSpice/RicePop 1.0 feature gate.

### Step 4 functional desktop integration checkpoint (15 November 2026)

**Scope: opt-in labwc/RicePlate Wayland desktop software, not Mint hardware or
the separate 1.0 release certificate.**

- The real compositor-native file desktop, keyboard/focus return, app taskbar
  lifecycle, Wayland/XWayland clipboard, multi-output layout, actual Start/Run
  dialogs and RiceField file intents already have successful merged-native
  integration evidence from Step 3 on
  [main Tests #43678051131](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43678051131)
  and [Native RicePlate #43678051154](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43678051154).
- The shared Rice engine has compositor-frame-confirmed
  Classic → Chrome → XP Luna → Chrome live apply and safe restore/recovery.
  RiceSpice uses shared Linux settings backends; RicePop uses the validated
  Mako bridge rather than claiming a second notification daemon.
- The remaining opt-in **session boundary** is addressed by
  [#386](https://github.com/CopyPasteUser/Ricebowl/pull/386): a nested preview
  with an **inherited** parent user's D-Bus must not spawn a competing Mako,
  polkit authentication agent or Orca. An **explicitly isolated private**
  nested D-Bus may run its own Mako for genuine RicePop CI acceptance, without
  registering polkit or changing the parent's user bus. A full login owns
  the optional user integrations and mandatory idle lock guard. The live
  supervisor exposes an owner-scoped, PII-free service health snapshot through
  its existing read-only status endpoint (not a same-UID process guess).
- The session change requires exact-head Python/XFCE regression, real Wayland
  session preview and native compositor/packaging CI, followed by **new main**
  post-merge checks. Do not treat a branch or this roadmap entry as evidence
  of successful execution.
- Remaining 1.0 acceptance: physical Mint login, real input/IME/Orca,
  polkit, notification and suspend UX, GPU-backed production portal frames,
  Flatpak consent, actual devices/monitors, per-component feature parity,
  performance and reproducible distribution. These stay explicitly open in
  `RELEASE_1_0_GATES.md`.

### Step 3 software-integration closeout (15 November 2026)

**Status: software-only acceptance completed on `main@fca6910d5a885d0bfd0f37d757f199775f821983`; physical 1.0 release gates remain open.**
- **Post-merge, exact-SHA checks:** [Tests #43678051131](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43678051131)
  and [Native RicePlate #43678051154](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43678051154)
  both passed on `main` after the guarded squash of #383, rather than only on
  the PR branch.
- **Desktop/input (#383, issue #328):** one short-lived, compositor-confirmed
  same-seat keyboard focus lease supports native Bottom-layer shortcuts and
  XDG file surfaces. The lease downgrades its temporary Exclusive focus after
  genuine `wl_keyboard.enter`, retires on external app mapping, and preserves
  desktop double-click. Actual headless labwc checks confirm shortcut Unicode
  prefix/Escape and real GTK Wayland text + Return after desktop selection.
  This is not a permanent global input grab.
- **Desktop actions:** the same native run verifies real XDG context, safe
  rename, Trash confirmation, a visible newly-created folder, drag/persisted
  icon position, two-output file drop and hotplug restoration; ordinary
  Wayland/XWayland taskbar and clipboard checks also passed.
- **Shared Rice engine (#381):** native readiness now requires a genuine first
  compositor frame before committing guarded multi-component live apply.
  Headless integration verifies Classic -> Chrome -> XP Luna -> Chrome with
  restore, failure injection, supervisor restart recovery, package upgrade,
  downgrade and preserved XFCE test-user configuration. This does **not**
  establish atomic presentation across third-party clients.
- **Portals (#382, #384, issue #304):** a CI-private generic/pixman backend,
  isolated D-Bus/PipeWire/WirePlumber and real animated GTK compositor witness
  delivered a nonempty `video/x-raw` GStreamer buffer **without a DRM render
  node**. The installed production selection remains
  `xdg-desktop-portal-wlr`; the strict GPU-backed wlr/GLES2 lane was
  prepared but not actually run on a DRM-capable runner.
- **Not covered:** physical Mint login/input/IME/Orca, GPU-backed production
  ScreenCast, Flatpak consent and per-stream sandbox permissions, real
  multi-monitor hardware and final distribution/performance signoff.
  Issues #328 and #304 stay open for these remaining acceptance criteria.

### Shared native Rice engine / compositor-frame transaction gate (14 November 2026)

- The existing single recipe schema, shared system backends and owner-private
  native supervisor already implement reviewed live apply/restore across
  RicePlate, wallpaper, private labwc menu/chrome/hotkeys and optional
  RiceField/Taskotto profiles. Do **not** build per-rice copies of those services.
- Replace the old 500-ms *process-alive* criterion for native RicePlate with
  one inherited, bounded FD handshake. Only a genuine first primary
  `wl_surface.frame` callback sends `RICEPLATE_READY_V1`; timeout, EOF,
  malformed acknowledgement or compositor crash preserve the previous rice.
  The Waybar fallback remains an explicitly weaker liveness-only contract.
- CI requires real headless labwc frame acknowledgements from Classic,
  Chrome and the structurally distinct XP Luna recipe, plus isolated
  Classic → Chrome → Luna → Chrome live-switch/restore screenshot comparison.
  Failure-injection tests retain existing Creator error and rollback contracts.
- This does **not** constitute atomic visual synchronization across unrelated
  third-party clients, full hardware/IME/Orca acceptance, or a stable 1.0
  release. Keep the original XFCE login and session recovery unchanged.

### Screenshot evidence integrity (15 November 2026; software accepted)

- [x] Require complete PNG decoding before the classic panel pixel probe. The
  two-pass `scripts/check_wayland_panel_outputs.py` check validates both PNG
  chunk integrity/CRC (`verify()`) and the full decoded raster (`load()`).
  `tests/test_de_panel_outputs.py` covers valid, truncated, missing-IEND,
  wrong-color and invalid-geometry captures. Real labwc/grim checks passed on
  final `main@c30825b09a81` in [Native #43735151946](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43735151946),
  with [Tests #43735151911](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43735151911).
  Synthetic fixtures alone do **not** establish physical-screen quality.

### Native XP Luna Run text-editing gate (15 November 2026; software accepted)

- [x] The actual native Run dialog supports Unicode scalar-safe insertion,
  in-place Backspace/Delete, Left/Right/Home/End, proportional/bitmap-font
  scrolling and a composited caret. It preserves shell-free argv execution
  and the existing 192-character/16-argument limits.
  `scripts/smoke_riceplate_native.sh` injects real labwc/`wtype` editing
  events and checks compositor-generated typed/edited/cleared PNG differences
  and caret pixels; Rust tests cover cursor, multibyte and command bounds.
  See `WAYLAND_XP_LUNA_PARITY.md` and exact-main [Tests #43735151911](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43735151911)
  / [Native #43735151946](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43735151946).
  Physical keyboard, IME and screen-reader acceptance remain open.

### Luna recent-app privacy and write-efficiency (13 November 2026)

- [x] Reject a multiply hard-linked private recent-app history inode for restore,
  save and explicit privacy clear. A single owner-private regular file remains
  supported; the regression preserves both links and unrelated data when
  refusing an unsafe file. Tests and Native RicePlate CI passed on PR #319,
  merged as `ccb6d16d`. This does not imply physical session acceptance or
  that a privacy clear securely erases storage blocks.
- [x] Skip rewriting byte-identical, owner-private, bounded recent-app JSON,
  preserving its inode and modification time. The current native Rust
  `menu_recents.rs` implementation compares bounded canonical bytes before
  its atomic rename and directory-fsync path, and includes the
  `unchanged_recent_history_save_preserves_inode_and_mtime` regression.
  Malformed or unmanaged files retain their rejection rules. This is an
  I/O reduction by design, not a measured performance claim.

### Wayland XP Luna recipe (10 November 2026, preview sprint)

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
  `luna-calendar-font.webp`).
- [x] Verify the opt-in volume OSD on an actual headless compositor using a
  read-only simulated 68% preview: bitmap and private-font captures, confirmed
  native blue OSD background, input-transparent surface, true 125%-scale
  geometry and 880 different pixels in the full overlay region (native run
  #42914562690; permanent `luna-osd-default.webp` and `luna-osd-font.webp`).
  Real mixer/volume-key hardware behavior is a separate acceptance gate.
- [x] Add original 48px Luna desktop pictograms for Programs, Terminal and Lock
  as a schema-v12 `builtin-luna` icon choice; validate and expose it in Creator,
  export it without extra RicePack assets, and retain older recipes unchanged.
  Real native compositor icon comparison passed in run #42960890682.
- [x] Exercise a **single running** Luna/RicePlate process across 1024×768,
  1366×768, 1920×1080 and 1366×768 at 125% scale, restoring the compositor
  to 100% after the earlier scale-specific smoke scenario and after the matrix.
  Capture closed/open menus at each geometry and validate framebuffer size,
  wallpaper, panel and menu delta in native CI (green run #42963768429).
  Preserve 1024, Full HD and 125% real screenshot previews in the gallery.
- [x] Add a **reviewable Luna menu visual-diff artifact** without another
  rendering or comparison engine: run the existing offline Creator visual-QA
  algorithm on all four actual closed/open native compositor PNG pairs;
  archive 24-threshold pixel heatmaps and one provenance-rich JSON report with
  per-region results, capture SHA-256s, output sizes and layout diagnostics.
  Preserve 1024×768 and 125%-scale heatmap previews. This detects a visibly
  painted menu state, not physical input correctness or pixel-perfect fidelity.
- [x] Exercise **actual compositor virtual-pointer input** on the native Luna
  Start button (not `--preview-menu`) after live output changes at 1024×768,
  Full HD and 125% scale. Archive six real opened/closed framebuffer PNGs,
  enforce visible menu change and desktop restoration, and preserve a reviewed
  screenshot pair (native run #42968039762; PR #247). Physical device focus,
  keyboard/touch and session signoff are still separate gates.
- [x] Implement the **next original Luna visual-fidelity pass** for the
  opt-in two-column rice: cobalt gradient account bar, original user tile,
  beveled search/saved buttons, pale-blue system shelf, per-action glyphs,
  a visible functional Close footer and richer green taskbar launcher.
  Increase the actual native menu surface to 400×380 at 1280+ logical width
  and 480×456 at 1600+ width when sufficient height exists; share the
  inverse pointer transform and preserve 1024/small-output behavior.
  Treat this as visual implementation, **not** Windows XP pixel-perfect
  acceptance: the enlarged surface still upscales 320×304 bitmap text.
- [ ] Review Full-HD Start-menu physical sizing and accessibility in a real
  session after the new scalable-surface implementation. Historical face
  metrics, genuine full-resolution text/9-slice art, physical mixed-DPI,
  monitor hotplug and focus remain open.
- [ ] Still open before any 1.0 claim: physical ThinkPad input/focus/power and
  display acceptance, third-party client decoration fidelity and final
  distribution/upgrade signoff for schema v12.

### Native font-system checkpoint (10 November 2026)

- [x] Discover local, importable TrueType faces through a bounded read-only
  Fontconfig inventory (`de fonts --json`), and choose one in Creator's native
  installed-font dialog. An explicit name/provenance declaration remains
  mandatory before copying a font into the existing owner-private SHA-256
  asset collection. Public distribution font directories are accepted only
  for unmodified, non-symlink, read-only font files; unrelated root-owned files
  are never accepted. No global GTK/Qt or system font setting is changed.
- [x] Keep the common Latin TrueType glyphs prewarmed while bounding the
  additional on-demand Unicode cache to 512 codepoints. The selected private
  font can draw supported extra Unicode glyphs without a per-rice resident
  worker; unsupported characters retain a visible fallback. The existing
  fixed-cell text geometry and RicePack v4 verification stay compatible.
- [x] Reuse the optional owner-private font for native RicePop active/history
  lists and message details, including compact-layout surfaces. Paginate at
  the real 8px/16px glyph width and retain original bitmap pixels without a
  selected private font. Validate both states against actual labwc captures
  (green native run #42970768749, PR #250). Refresh-time page clamping now
  follows the active popup viewport, preserving compact-page reading position.
- [ ] Full script shaping, bidirectional text, variable font metrics, large
  CJK font packages, global toolkit font choices and physical visual/Orca
  verification are distinct follow-up work, not claimed by the glyph cache.

### Standalone desktop packaging checkpoint (November 2026)

- [x] Align `de check` with the real labwc launcher prerequisites: distinguish
  nested preview, protected full login (`swayidle`) and native RicePlate login
  (additional binary). Missing mandatory tools now produce a failing preflight
  instead of false success from finding only labwc. It remains read-only and
  explicitly does not certify the D-Bus connection, portal or physical login.

- [x] Add a reproducible, tracked-source, read-only `ricebowl-wayland-core`
  Debian package with independent CLI and bundled Wayland resources/Creator.
  The login package prefers it while remaining backward compatible with the
  existing user-local RiceBowl installation.
- [x] Add a dependency-only `ricebowl-wayland-desktop` meta package that
  resolves core, session and native RicePlate together. No postinst or
  session-default/desktop mutation. CI runs isolated Ubuntu clean install,
  reinstall and purge and checks user state preservation.
- [x] Prove genuine **Ubuntu 24.04** Core/Meta Debian transitions from
  the pinned previous-release commit (preview1) to preview2, including a
  corrupt package rejection, explicit downgrade, re-upgrade, purge and
  test-user recipe/XFCE-data checksums. Store deterministic source/version
  BUILDINFO in the new core package; preserve backwards-compatible session.
- [x] Extend the isolated apt transition with an actual selected **schema-v10**
  imported recipe from the previous package, plus the upgraded **schema-v12**
  Luna recipe. Recheck both through the packaged CLI, prove the old parser
  rejects v12 on downgrade, restore v10, reselect v12 on re-upgrade and keep
  both private recipe files unmodified through the final package purge.
- [x] Add a disposable **installed-package Wayland boot gate**: after apt
  installs all four preview `.deb`s, invoke the packaged native login wrapper
  as an unprivileged user with headless labwc and private D-Bus/XDG state;
  require live Wayland protocol discovery, native RicePlate, `swayidle` and
  a real PNG framebuffer. This is not display-manager or physical-device QA.
- [ ] Test Mint 22 dependency resolution, changed native/session packages,
  longer real-world version chains, actual display-manager login and
  selected-rice migrations on physical hardware. The v10/v12 Ubuntu container
  exercise above is not a user-device release signoff.


## The product

RiceBowl will be a lightweight, modular **floating** desktop environment on
Wayland. We use upstream [labwc](https://labwc.github.io/) as the compositor,
not a RiceBowl compositor fork. Each rice may substantially change the layout,
controls, wallpaper, icons, window chrome and behavior of our own components.
Running third-party GTK/Qt apps cannot be forced into arbitrary client-side
window decorations; use supported platform theming and preserve functionality.

## Desktop creation as a first-class workflow

**North star:** the same lightweight functional desktop core must make it easy
to build both a convincing OS-inspired rice and a completely new rice from an
AI-generated UI mockup. Authors should spend most of their time defining the
experience, not writing another shell, panel, device backend or window manager.

A rice is **more than a color theme**: it can choose and arrange shell
components, navigation, menus, panels, desktop behavior, widgets, typography,
artwork, transitions and available interactions. Shared RiceBowl components
supply the real Linux behavior, state and recovery underneath.

The intended authoring path is:

1. Analyze a screenshot/mockup into regions, components, visual tokens,
   responsive rules, interactive states and required Linux capabilities.
2. Map it to reusable primitives and a **versioned declarative rice recipe**
   with original or properly licensed assets. Extend the shared primitives
   when necessary, rather than cloning the entire shell.
3. Preview the full shell at multiple sizes, inspect differences and test
   keyboard/focus, accessibility, live controls and real application windows.
4. Validate and import the rice safely, then apply/switch/restore without
   overwriting personal desktop settings.

An AI agent may assist with steps 1–2, but **RiceBowl itself must not require
AI inference or an online service**. Arbitrary images are not promised to
become fully functional one-click conversions; unfamiliar controls require
explicitly implemented behavior. Packs must never execute arbitrary generated
scripts. Third-party GTK/Qt application decorations and Wayland protocol
limits remain real constraints on cross-app fidelity.

### Implementation priority (8 November 2026)

**First finish the shared Wayland desktop foundation.** Prioritize (1) safe,
reusable layout components with actual state/action/focus bindings,
(2) a transaction-safe live multi-component rice switch and rollback,
(3) Creator editing, structured design tokens and offline pack integration,
then (4) physical hardware/keyboard/AT acceptance. Work on individual skins
must not displace these foundations.

**Deferred until that core is functional:** historically exact Windows XP,
Windows 7 and Windows 10 menu/icon/chrome reproductions, pixel-level asset
matching, and per-rice cosmetic redesigns. Keep the existing rices working and
recognizable, but build missing behavior as shared primitives first. Detailed
historical fidelity has a separate acceptance gate after the foundation;
no per-OS fork of the native shell is permitted.

**Parallel integration discipline:** The [DE 1.0 integration contract](docs/de-integration-governance.md) assigns core, desktop, system and shell ownership, records stacked PR dependencies and requires exact-head CI plus post-merge verification. This coordination document is not evidence of new runtime functionality, and does not close any 1.0 gate.

### Runtime and Creator boundary (partially implemented; 1.0 gates open)

- **RiceBowl Runtime** owns the lightweight Wayland session, rendering,
  shared Linux capability adapters, application integration and safe rice
  switching. A completed rice must run offline without an AI model, Creator
  process, cloud dependency or per-rice interpreter left resident.
- **RiceBowl Creator** is an optional, on-demand authoring/tooling layer for
  editable recipes, asset inspection, component discovery, previews, visual
  comparisons and safe export. It uses the **same renderer and schemas** as
  Runtime; preview-only implementations must not diverge from real-shell
  behavior. Creator does not require its own repository or daemon.
- **One source of truth:** the validated versioned RicePack schema defines
  structural composition, responsive rules, visual tokens, supported states
  and explicit action bindings. Neither human editors nor AI agents may write
  arbitrary executable hooks into a pack.
- Runtime remains independently installable and efficient; Creator is not
  automatically launched at login. Reuse existing Linux services and the
  upstream labwc compositor rather than creating replacement daemons.

### Repository and process ownership

| Owner | Responsibility | Boundary |
| --- | --- | --- |
| RiceBowl / RiceSession | Login session, startup, shutdown, recovery | A Wayland path separate from the current XFCE session |
| RiceBowl / RicePlate | Desktop icons, wallpaper, panels, menus, taskbar | One active shell; no competing XFDesktop process under Wayland |
| RiceBowl / RiceSpice | Settings, quick actions, hardware state | Reuse NetworkManager, BlueZ, PipeWire, UPower and logind |
| RiceBowl / RicePop | Notifications, OSD and optional history | One notification owner, no redundant daemon |
| RiceBowl / RiceClip | Optional clipboard history and quick paste | Internal utility; event-driven, privacy-first, no separate repository |
| RiceBowl / RiceShot | Screenshots, selection and lightweight annotations | Internal on-demand utility; reuse Wayland portals, no capture daemon |
| RiceBowl / RicePack | Appearance profiles and UI layout contracts | Validated config, no arbitrary third-party code execution |
| [RiceField](https://github.com/CopyPasteUser/Ricefield) | Independent Rust file manager | 1.0 hardware sign-off before replacing Thunar by choice |
| [Taskotto](https://github.com/CopyPasteUser/Taskotto) | Independent Rust process manager | Separate optional app, currently planning only |
| labwc, XWayland, portals | Compositing, legacy apps and sandbox integration | Upstream dependencies, not new RiceBowl repositories |

The current `macrice/` namespace and commands remain for upgrade/rollback
compatibility. New desktop-environment code starts in an isolated `macrice/de/`
namespace and must not silently call XFCE-specific paths.

## Delivery gates

**Software-first sprint policy (11 November 2026):** complete functional
RicePlate/RiceSpice/RicePop parity, text/layout, two-rice Creator flows and
reproducible installation/recovery in CI before returning to physical-device
acceptance. Hardware checks are temporarily **excluded from software-progress
percentages**, not marked done. The protected public 1.0 release gate still
requires separate real-device sign-off. Track the two independently in
`WAYLAND_PROGRESS.md` and `RELEASE_1_0_GATES.md`.

### 0 — Prep and non-invasive diagnostics

- [x] Choose labwc as the Wayland floating compositor without forking.
- [x] Retain RicePlate, RiceSpice and RicePop in the main repo.
- [x] Keep RiceField and Taskotto as independent applications.
- [x] Add an environment-only `ricebowl de check` preflight.
- [x] Keep the historical XFCE path working with existing automated tests.
- [ ] Establish measured X11 baseline on real hardware; no guessed RAM claims.

**Done when:** the preflight detects missing prerequisites without starting,
installing, replacing or disabling anything; unit and installer tests pass.

### 1 — Optional labwc login session

- [x] Add a versioned RiceSession lifecycle with a supervised temporary native
  Waybar shell, explicit exit, crash termination and ordinary session logs.
- [x] Provide a separately built **opt-in** Debian session entry package.
- [x] Add a **second opt-in native RicePlate login choice** alongside the
  Waybar-backed preview: install only another small `.desktop` entry, hide
  native selection via `TryExec` until `/usr/bin/riceplate-native` exists,
  route only `--native` through the established session supervisor with
  Waybar crash recovery, and reject unknown launcher arguments. The versioned
  preview2 package is reproducible and removable; no default-session or XFCE
  changes. Real display-manager discovery and physical login/rollback QA
  remain open.
- [x] Launch labwc through bundled `--config-dir`, preserving the user's
  own labwc files and XFCE preferences.
- [x] Add Mint 22 / labwc 0.7.1-compatible D-Bus activation import and a
  RiceBowl-specific systemd user target; nested sessions do neither.
- [x] Package RiceBowl-specific wlroots/GTK portal selection, XWayland
  dependency recommendation, lock/launcher keybindings and optional agents.
- [x] Keep the XFCE/X11 login path independently available and provide
  explicit package removal and failure recovery instructions.
- [x] Require the idle-lock listener for a real Wayland login and supervise
  it as an essential child; lock before a RiceSpice-requested suspend and
  reject failures/timeouts instead of claiming a secured suspend. Preview3
  installs swayidle as a dependency; real lid/resume locking acceptance is
  still outstanding.
- [x] Detect resume without an extra daemon by comparing Linux BOOTTIME and
  MONOTONIC; re-evaluate Waybar output-specific layouts once after output
  settlement and preserve the old panel if reconfigure fails. Keep native
  RicePlate's wl_output listener and nested preview unchanged.
- [x] Extend essential idle-lock watcher failure handling to non-live and
  live-RPC-unavailable session modes. Native fallback cannot start Waybar
  after an unsafe idle-watcher failure; it exits the opt-in session instead.
  Regression tests inject synthetic clock gaps and dead watchers.
  **Actual suspend/lock/dock hardware sign-off remains open.**
- [ ] Validate actual login-manager discovery, compositor boot, XWayland,
  portal screencast/file picker, polkit, input methods, clipboard, lock and
  multi-monitor behavior on physical Mint hardware.

**Done when:** the [device acceptance checklist](WAYLAND_SESSION.md) proves
that users can enter and leave the opt-in RiceBowl labwc session without
affecting XFCE, including a failed-session recovery. **Not yet signed off.**

### 2 — RicePlate Wayland shell

- [x] Establish a non-executable versioned panel-layout recipe and an isolated,
  temporary Waybar adapter with two distinct compositional layouts; validate
  custom manifests and clean up generated session files. This is a stepping
  stone, **not** the native RicePlate renderer.
- [x] Introduce an **opt-in native Rust layer-shell surface prototype** with
  software rendering, a visible fixed-action launcher and event-driven idle.
  It is independently testable and does not replace Waybar until parity.
- [x] Add experimental protocol-backed native window discovery and activation
  with bounded task labels and click hit-testing; full taskbar parity remains
  open (tray, outputs, keyboard interactions).
- [x] Consume the two bundled schema-v1 panel recipes from native Rust for
  geometry, placement and visual tokens, without pretending unimplemented
  system indicators are functional native widgets.
- [x] Add a real local-time clock with minute-boundary event-loop wakeups,
  plus activate/minimize task clicks. Tray and full interactions remain open.
- [x] Add a **functional first native calendar** to the primary Wayland clock:
  a focusable, rice-token-themed popup with actual local month/day geometry,
  leap years, month/today buttons, selection and Escape/arrow/PageUp/PageDown
  navigation. It lives in RicePlate without a new process or online service;
  pure Rust date/hit/paint tests and a real labwc calendar capture gate are
  included. A later native milestone added output-bound popups for the
  secondary clocks; event creation, localization, assistive-tech and
  physical-device QA remain open.
- [x] Support owner-private, bounded custom schema-v1 JSON recipes in native
  RicePlate, and position implemented widgets from ordered start/center/end
  sections with matching hit testing and small-display overflow behavior.
  Full arbitrary mockup conversion and missing widget backends remain open.
- [x] Provide a CLI-only opt-in to run native RicePlate as the single panel in
  an isolated labwc session, and restore Waybar on failed native start/crash.
  Explicit shutdown does not restart the fallback. The login-manager default
  remains Waybar while native functional parity is incomplete.
- [x] Page through tracked Wayland windows when the native taskbar overflows,
  with actual clickable previous/next regions, bounded labels, and automatic
  reveal of the active window. Keyboard access remains open.
- [x] Group native Wayland windows with the same nonempty app ID, show bounded
  window counts, cycle active grouped windows and page/reveal by group; unknown
  IDs are always independent.
- [x] Add **keyboard navigation for the native multi-output taskbar**:
  focus on demand, accessible launcher and window-group selection with a
  visible frame, Left/Right/Tab navigation, Enter/Space activation and
  automatic reveal of offscreen groups. Preserve each output's independent
  task paging and share the existing safe pointer activation path. Pure Rust
  navigation and painter tests cover wrap/reveal/focus; physical keyboard,
  focus transfer and screen-reader QA remain open.
- [x] Implement a first **real recipe-driven native start menu** as another
  bounded Wayland layer-shell surface inside RicePlate: grouped actions, mouse
  tabs/rows, keyboard group/row navigation with visible selection, Enter and
  Escape, guarded labwc logout, on-demand keyboard focus, headless open-menu
  screenshot and pure state/painting tests. The labwc fallback root menu
  remains available. Search, pins, desktop-icon keyboard navigation and
  multi-output menu ownership arrived in a later slice.
- [x] Add a **two-output labwc/Waybar fallback acceptance smoke** that captures
  genuine panel pixels separately on both headless monitors, disconnects one
  output, verifies the remaining panel, re-enables it and verifies panel
  recovery. Includes unit-tested screenshot validation. This exercises the
  default Waybar-compatible session, **not** native Rust per-output surfaces
  or mixed-DPI device signoff; both still need implementation/QA.
- [x] Extend the **single native RicePlate process** with an independently
  configured layer-shell taskbar on every non-primary Wayland output. Reuse one
  window/task model, clock and renderer; keep per-panel page offsets and
  event-driven redraws. Test a real two-output compositor and secondary
  disconnect/reconnect. Native popup menus and desktop-icon ownership remain
  primary-output-only for this first slice, and primary-monitor removal still
  follows the conservative session recovery path. Both native output captures,
  unplug and replug were verified in headless labwc CI; genuine hardware/mixed
  DPI acceptance remains separate.
- [x] Make the **secondary native clocks interactive** with their own
  output-bound calendar layers. Keep a single active popup and shared local
  date state inside RicePlate; remove the popup on output loss and recreate
  its hidden surface on reconnect. Real two-output labwc CI proves the popup
  appears on exactly one output and the shell survives unplug/replug, with
  screenshot evidence. Physical mixed-DPI/input/accessibility QA stays open.
- [x] Make **native schema-v4/v5 start menus output-aware**: each panel opens
  its own output-bound layer-shell popup with the same safe grouped actions
  and keyboard controls. Keep one active popup, close it when its monitor
  disappears and recreate the hidden surface on reconnect. A genuine
  two-output labwc smoke captures exactly one visible menu and verifies
  unplug/replug; physical mouse/keyboard and assistive QA remain open.
- [x] Add **bounded native Start-menu action search and per-rice favorites**:
  type-to-filter validated fixed action labels (up to 32 Unicode characters),
  F2 pin/unpin, F3 saved-action view, four-row keyboard/pointer paging, and
  at most eight pins stored in a private atomic file separate from the recipe.
  Reject symlinks, foreign permissions, unknown/duplicate actions and stale
  rice IDs; nested Creator previews do not load or save preferences.
- [x] **Search installed applications inside the native RicePlate menu**:
  read a bounded, deduplicated XDG desktop-entry catalog on opening the menu
  (at most every 30 seconds), including valid nested desktop IDs, user-level
  hidden-entry masking and `OnlyShowIn`/`NotShowIn`/`TryExec` rules. Search
  visible app names, generic names and keywords without interpreting `Exec`;
  start a selected app through `gio launch` with the verified desktop-file
  path. Keep recipe-action pins separate, show no unfiltered app flood, and
  preserve external fuzzel as the `applications` shortcut/fallback. Real
  installed-app, desktop-localization, assistive-technology and physical
  keyboard acceptance remain open; personalized OS-specific menu structures
  are not yet complete.
- [x] **Localize native XDG installed-app discovery** without another daemon:
  prefer `LC_ALL` / `LC_MESSAGES` / `LANG` and POSIX desktop-key locale
  fallback order for translated app names, generic labels and search keywords;
  retain English/untranslated search terms. Decode bounded desktop-file text
  escapes, reject ambiguous duplicate keys, require executable `TryExec`
  targets and preserve user-level hidden-entry masking. Add Rust unit fixtures
  for German fallback, malformed translations and non-executable launchers.
  Real desktop-language, accessibility and physical keyboard QA remains open.
- [x] **Rank native installed-app search by relevance**: exact displayed-name
  hits precede name prefixes, unordered name-word prefixes and generic-name/
  keyword hits. Accept multiword queries in any order, match Unicode names
  case-insensitively, and keep stable catalog ordering for ties. Search the
  existing bounded index without another process or new dependencies; preserve
  built-in action precedence, keyboard/pointer selection, and private pins.
  Rust tests cover ranking, mixed-language terms and menu selection. Physical
  multilingual input and accessibility acceptance still remain open.
- [x] Introduce **schema-v6 native menu presentation variants**: retain
  horizontal tabs by default, allow validated `menu.presentation: sidebar`
  with a separate left navigation rail and right action/search column. Share
  navigation, fixed actions, installed-app search, keyboard handling and
  private pins; expose the variant in Creator catalog, draft-edit, semantic
  review and Rust/Python tests. The native headless smoke captures both
  presentations. Pixel-perfect OS menus, icon-rich grids, responsive menu sizing
  and on-device keyboard/AT acceptance remain open.
- [x] Add **schema-v6 composable native menu content**: group-local optional
  sections for fixed actions, private favorites and installed XDG launchers
  as a list or two-column initial-letter tile grid. Strictly validate section
  titles, source kinds, 1–2 sections and at most four visible items in both
  Python Creator and Rust RicePlate; one geometry model drives paint, pointer
  hits and flattened keyboard/accessibility actions. Keep existing groups,
  search, pins and Waybar fallback unchanged when no `content` is present.
  Document Creator edits/semantic review and capture a native composed-menu
  screenshot in CI. Historical OS iconography, larger responsive content
  layouts and physical keyboard/Orca QA remain separate release gates.
- [x] **Foundation Sprint 1: native menu interaction hardening** — keep the
  existing recipe-bound menus but make pointer hover update action selection,
  add Shift+Tab, Home/End and bounded PageUp/PageDown keyboard navigation,
  and give an empty saved-action menu a real accessible Close focus target.
  Rust regression tests cover search paging, edge selection and empty states.
  Full popup resizing and physical-device/Orca validation remain open.
- [x] **Foundation Sprint 2: discoverable native menu search/saved controls** —
  every schema-supported menu presentation now paints real `Find` and `Saved`
  header buttons, with `Clear`/`Back` semantics once a mode is active.
  Full-size and compact painting, pointer hits and AT-SPI activation use the
  same fixed geometry and native state machine; slash/F3 and the original
  menu action dispatcher remain available. Rust tests cover empty/query,
  return, boundary, closed-popup and compact-size cases. Richer proportional
  text shaping and device-level Orca QA remain open.
- [x] **Foundation Sprint 3: native menu wheel/trackpad paging** — long
  installed-app search and saved-action results now accept Wayland vertical
  axis events using one bounded page at a time. Continuous touchpad deltas
  accumulate before advancing; horizontal/stop and non-finite input do not
  move a selection, while fully visible composed menus remain stationary.
  Compact rows, reopen/reset, limits and empty lists have Rust regressions;
  native labwc CI captures wheel-down versus hover-only pixels and verifies
  that wheel-up restores the visible action page without reopening the menu.
  Physical mouse/touchpad acceptance remains open.
- [x] Show a **real, read-only native battery percentage** in RicePlate from
  Linux's fixed `/sys/class/power_supply`, with charging state, explicit
  no-battery/unknown labels, multi-battery handling and bounded once-per-minute
  refresh. The indicator is a validated recipe widget on each native panel;
  it yields layout width to task groups instead of silently reducing task
  capacity. No fake battery on desktops, new daemon, UPower power action or
  claims of hardware QA. Network, audio, SNI tray and power controls remain open.
- [x] Add **truthful native network/audio status labels** backed by
  NetworkManager's `nmcli` overall state and WirePlumber's `wpctl` default
  sink volume/mute state, with bounded subprocess runtimes on one lazy worker
  thread. Wake the Wayland event loop only when data changes, sample at most
  once every 30 seconds, report missing services as unavailable, and hide
  lower-priority status slots before sacrificing task groups on small screens.
  They are intentionally non-clickable until real RiceSpice quick actions
  exist. The SNI tray and actual network/audio device controls remain open.
- [x] Replicate **native desktop shortcut surfaces on all known outputs** in
  one RicePlate process with fixed secondary-output ownership; reflow each
  output independently against its logical dimensions and panel reservation,
  recover the shortcut layers after hot-unplug/replug, and keep private saved
  coordinates under the selected rice, initially shared across monitors.
  Keyboard `Tab`/`Shift-Tab` cycles only visible icons on the focused output;
  Enter launches and arrows move the selected shortcut. The two-output
  labwc CI now checks original rendered icon pixels before/after hotplug.
  Physical mixed-DPI, compositor-dependent initial output ownership and
  assistive-technology acceptance remain separate.
- [x] Add **independent owner-private desktop-icon positions for named Wayland
  outputs**: a validated v2 state file stores at most eight per-output layouts,
  preserves all existing schema-v1 saved positions, and keeps shortcuts on
  monitor A from moving merely because their counterparts on monitor B moved.
  Output names are supplied by the compositor; absent/unsafe names fall back
  to the original shared layout rather than guessing a stable identity.
  Reconnect restores the last named layout without writing into source
  recipes. Rust tests cover independent displays, migration, malformed
  locations and atomic private persistence. Real cross-monitor drag and
  mixed-DPI physical-device behavior remain unverified.
- [x] **Foundation Sprint 2: assign a desktop shortcut to a named output** —
  add private icon-position schema v3, preserving v1/v2 coordinates and recipe
  immutability. Focus a native desktop icon and press `F6` to assign it to the
  next connected named display (deterministic alphabetical cycle); `F7`
  restores the original mirrored behavior. Unassigned icons remain visible on
  every output, while assigned icons occupy layout and collision space only
  on their selected output. If the target disconnects, the icon appears on
  the primary desktop until its named display returns. Invalid display IDs,
  stale recipes and malformed state fail closed without partial restore;
  screen readers receive action hints. This is keyboard-based output
  ownership, **not cross-monitor pointer dragging**. Physical mixed-DPI,
  hotplug, keyboard focus and Orca acceptance remain pending.
- [x] **Foundation Sprint 3: native pointer drops between outputs** — use the
  source icon surface's implicit Wayland grab and known xdg-output logical
  rectangles to identify a different connected named display when the left
  mouse button is released. Validate and commit destination coordinates plus
  ownership together, preserve the original source layout, and reject invalid
  or unplaceable destinations without hiding the shortcut. Keep `F6`/`F7` as
  the non-drag alternative; no new daemon or schema migration. Rust geometry
  and private-state tests cover negative origins, gaps, malformed values and
  rollback. Real compositor pointer grabs, hotplug and mixed-DPI hardware
  sign-off remain open; the dragged icon does not float across the monitor
  boundary before release.
- [x] **Foundation Sprint 4: interactive shared desktop action components** —
  reuse schema-v9's validated `role: action` bindings on native desktop widget
  surfaces: fixed Apps/Terminal/Settings/Lock actions and verified Wi-Fi/audio
  controls use the existing action dispatcher, bounded worker and real device
  readback. Only action-bound 200×96 surfaces receive pointer input and
  on-demand keyboard focus; status/text widgets stay input-transparent.
  Handle press/release cancellation, same-output Tab/Shift-Tab navigation,
  Enter/Space, visible focus/unavailable/busy/failed states and native AT-SPI
  button actions. Creator canvas, draft/review/RicePack and catalog share the
  unchanged versioned contract. Rust parsing/painting tests and a real
  headless labwc capture exercise an interactive demonstrator. True physical
  click/focus/Orca/accessibility verification still gates 1.0.
- [ ] Build a Wayland-native panel through `wlr-layer-shell`.
- [ ] Populate tasks/windows through a supported foreign-toplevel protocol.
- [ ] Implement launchers, task groups, tray, calendar, menus and keyboard
  navigation; avoid invisible or fake controls. Native task/menu keyboard
  controls, output-aware calendars and menus are partially implemented;
  native DBusMenu and panel tray keyboard focus are implemented experimentally;
  event localization, screen-reader semantics,
  global accessibility and interaction parity are still missing.
- [x] Establish an opt-in **real native SNI host/watcher** in RicePlate for
  recipes with a tray: share the Wayland event loop via the D-Bus fd, honor
  existing watchers, show bounded active/attention icon pixmaps with validated
  ARGB dimensions, dispatch actual item activation/context-menu requests and
  degrade safely when D-Bus is absent. The fourth slot becomes an actual +N
  overflow selector when needed: a bounded output-local layer-shell popup
  offers mouse selection, keyboard Up/Down, paging, Enter and Escape, without
  a helper daemon. Mouse action coordinates are mapped from output-local
  surfaces to compositor-reported global output geometry. Native DBusMenu
  presentation now uses the same per-output layer-shell popup, with bounded
  visible rows/submenus, disabled/separator/toggle indicators, live property
  synchronization, paged mouse/keyboard navigation and protocol-correct
  opened/closed/clicked signals. The panel keyboard focus cycle also reaches
  visible SNI slots and overflow. The app-owned ContextMenu fallback remains
  for items with no DBusMenu tree. No third-party hardware/AT signoff is claimed.
  Requires Rust 1.88 and libdbus-1 for the host library.
- [ ] Expose reusable, composable shell primitives and stable interaction/state
  bindings so substantially different rice layouts share core behavior.
  - [x] Deliver the first **schema-v9 shared component registry**: up to eight
    strictly validated status/action definitions (`id`, `role`, `binding`,
    `label`) may be referenced by panel groups and compact variants; status
    definitions also appear in native desktop widgets. Each reference resolves
    to existing real network/audio/battery/clock backends or the existing
    allowlisted native action/verified control, with no per-rice shell code.
    Python/Rust parsers, Waybar's honest panel-only fallback, Creator review,
    draft editing, catalog v12 and real headless v9 fixtures share the same
    contract. Interactive action-bound desktop surfaces now use those same
    validated bindings; richer state families and physical input/AT acceptance
    remain open.
  - [x] Add **schema-v9 static desktop text primitives** with safe bounded
    ASCII labels (22 characters), preserved by Creator review/draft/RicePack
    and rendered by native RicePlate. Read-only desktop widget layers on
    initial and hotplug outputs have empty Wayland input regions, letting
    pointer events reach underlying windows. Real interactive widget surfaces
    and hardware input/accessibility signoff remain separate work.
  - [x] Add a **real declarative schema-v6 panel action button** (`type: action`,
    `id`, `label`) with fixed allowlisted Apps/Terminal/Settings/Lock IDs;
    one validated recipe controls native drawing, per-output geometry, click,
    keyboard focus, AT-SPI actions and Waybar's fixed-command fallback. Creator
    catalog v7, semantic review, draft edit, shared fixture and headless native
    screenshot smoke cover the contract. No recipe-defined process commands,
    arguments, privileged actions or daemon were introduced.
  - [x] Implement **schema-v7 stateful native panel controls** (`type: control`)
    with four fixed Wi-Fi/mute/volume IDs, shared menu/panel worker and
    readback-checked state transitions. Poll genuine Wi-Fi radio capability
    independently of connection status; keep the Wayland thread free of
    subprocesses and suppress competing writes. Native painted controls have
    stable hit geometry, current values, unavailable/pending/error states,
    keyboard focus and AT-SPI names/disabled activation. Creator catalog v8,
    edit/review/pack tooling, native fixture, Python/Rust unit tests, headless
    compositor capture and honest disabled Waybar fallback cover the same
    bounded contract. Existing XFCE path, schemas 1–6 and static panel actions
    are unchanged. Broader cross-component constraints, more Linux adapters,
    rich visual tokens and physical acceptance remain independent future work.
- [ ] Render wallpapers and desktop icons with correct layer, focus, hit tests,
  drag/drop, multimonitor geometry and hotplug behavior.
- [ ] Support one selected rice at a time and restore the previous shell if a
  switch fails.

**Done when:** the desktop remains functional without xfdesktop or xfce4-panel.

### 3 — RiceSpice and RicePop

- [x] Complete the **RicePop 1.0 software-capability candidate** with a bounded
  native Mako inbox refresh *only while open* (3 s), backoff on unavailable
  host, stale-action suppression, numeric ID reuse and changed action-key
  guards. Word-wrap and page long message bodies with keyboard/pointer/AT-SPI
  access; render Latin/Greek/Hiragana 8×8 glyphs and visible substitutions for
  unsupported scripts. Detect a dead `pactl subscribe` child and reconnect
  with a five-second liveness bound; offer real sysfs-backed brightness OSD
  with optional private labwc hardware keys. No second notification owner,
  persistent private message store or unnecessary resident daemon is added.
  **Remaining release gate:** actual Mako/app-action, keyboard/Orca, brightness,
  audio-server restart and RAM/CPU acceptance on physical hardware. Mako is a
  supported **1.0 provider**; optional native D-Bus ownership and wider script
  rasterization are separate post-1.0 roadmap enhancements, not prerequisites.

- [x] Add a **first native RicePop audio OSD** to the existing resident
  RicePlate layer-shell process. An opt-in recipe with native volume/mute
  quick actions uses the verified WirePlumber post-action state (or an honest
  failure/unavailable message), a bounded progress bar and a single transient
  Overlay layer with an explicitly **empty pointer/touch input region**.
  The existing Wayland event loop owns the 1.8-second timeout; no separate
  helper, notification owner, periodic animation or private state store is
  introduced. This does **not** intercept external multimedia keys or
  third-party volume changes; accessibility/device QA is still open.

- [x] Extend the **native RicePop audio OSD to external default-sink changes**:
  a full native labwc login binds XF86Audio volume/mute keys inside its private
  `rc.xml`; an opt-in `pactl subscribe` child forwards only sink/server events
  to a bounded coalescing mailbox, which reads the actual `wpctl` result away
  from the Wayland event thread. Show changes from hardware keys and external
  mixers without double-display after a native RicePlate action. Missing
  `pactl` and unavailable audio degrade safely; nested previews do not start
  this monitor. The same 1.8 s input-transparent OSD remains the sole visual
  owner. Subsequent milestones added subscriber restart recovery, backlight
  OSD and active app actions; real hardware acceptance and optional
  independent notification hosting remain open.

- [x] Add **actionable native RicePop notification details** without taking over
  notification delivery: selecting a row opens a bounded details view with
  verified source/body information and explicit keyboard, pointer and AT-SPI
  action buttons. Only active notifications expose their current Mako action
  keys (up to eight, paginated); the past tab remains read-only. The on-demand
  `de notification-invoke` adapter re-reads Mako's current active list, refuses
  stale/duplicate IDs or unknown keys and dispatches one explicitly selected
  action without a shell, recipe-supplied command or notification store. Enter
  never dismisses an alert by accident; Delete remains an independent action.
  A later 1.0 candidate adds open-only refresh and paged text, plus Latin/
  Greek/Hiragana glyph tables. Independent native notification ownership,
  extra backends and full Unicode fallback are post-1.0 possibilities;
  physical keyboard/AT-SPI/action acceptance is still required.

- [x] Give **native RicePop genuine Wayland wheel/trackpad paging** in Luna:
  active/history notification rows, paginated message bodies and long action
  lists now each scroll in their own bounded hit region (including 168×144
  compact layouts). Discrete ticks advance visible pages; continuous deltas
  accumulate and reset on mode/region transitions. Header/footer events cannot
  scroll or trigger actions. Rust tests cover page boundaries, touchpads and
  reverse scrolling; headless labwc CI now captures real pointer-axis scroll
  down/up with a deterministic seven-notice offline preview and asserts the
  original framebuffer page is restored. Physical device acceptance remains
  deferred.
- [x] Show a **RicePop visible-range indicator** only when native active/past
  notifications exceed the viewport. Full and compact Luna headers use a
  bounded range, with short page notation for 2× portable fonts; AT-SPI
  announces the same first/last/total rows. Rust tests cover pages, compact
  output, the empty history tab and detail/close transitions.

- [x] Add **RicePop Do Not Disturb to the native RiceSpice Notifications page**
  and the machine-readable `de notification-dnd --json` API. A fixed
  RiceBowl-specific Mako configuration hides banners in
  `ricebowl-do-not-disturb` mode while preserving active/history entries;
  this is neither a second daemon nor a private notification database.
  Explicit on/off writes require the previously observed state, verify the
  live D-Bus owner's PID and exact RiceBowl Mako command, and check the result.
  Other desktops, nested Wayland previews and an unverifiable notification
  owner refuse writes. The full session exports its nested/full distinction to
  D-Bus activation for settings clients. On-hardware Mako version, D-Bus
  ownership, race and assistive-technology acceptance are still open.

- [x] Introduce the **on-demand RiceSpice settings window**, launched through
  a validated `settings` menu action or `ricebowl de settings`. It presents nine
  clearly separated settings categories (now ten including Notifications).
  Real native controls cover reviewed
  audio default sink/source selection, NetworkManager Wi-Fi radio with stale
  state protection, BlueZ adapter power/paired device connections and explicit
  lock or confirmed logind suspend (disabled in nested previews). Reviewed
  next-login rice selection is also available with an explicit commit action.
  Service operations run off the GTK thread with bounded concurrency; missing
  services and denied/indeterminate outcomes are visible. Displays, input,
  accessibility and timezone explicitly delegate to **installed** supported
  system settings tools, with honest unavailable state. No privileged daemon,
  raw command injection, unconfirmed live rice apply or duplicate system owner.
  Fully native editors and actual hardware/keyboard/AT acceptance remain open.
- [x] Extend RiceSpice's **on-demand power page** with the existing bounded
  power-profiles-daemon adapter and read-only kernel battery inventory: show
  only reported profiles, require an explicit selection with a stale-state
  check, verify the changed profile and expose an honest unavailable state.
  The existing lock/confirmed suspend controls remain separate. No daemon or
  privileged helper is added; real battery, polkit and sleep/wake QA remains open.
- [x] Expand the **on-demand RiceSpice Network page** beyond the Wi-Fi radio:
  show a bounded list of actual NetworkManager SSIDs, signal/security and
  connection state; provide an explicit rescan and verified connection to a
  still-visible network using existing credentials or an open network. Ask
  before replacing an active Wi-Fi connection and report missing credentials
  or an unavailable scan instead of claiming success. Password/enterprise
  onboarding, VPN/Ethernet editors and real roaming/hardware QA remain open.
- [x] Add an **explicit masked WPA-Personal password dialog** for visible
  networks, reusing RiceBowl's existing fixed-argument NetworkManager stdin
  adapter. Reject invalid passphrases, stale/hidden SSIDs and unsupported
  EAP/802.1X types before invoking a connection; clear the entry after the
  dialog, do not log/store credentials or put them in process arguments, and
  preserve the confirmation when switching an active network. Actual WPA2/3
  authentication, policy/permissions and reconnect QA are still hardware gates.
- [x] Add **on-demand MPRIS media controls** to RiceSpice's Sound page, reusing
  the existing bounded session-bus adapter: show actual player/title/artist/
  playback state, offer only permitted Previous/Play-Pause/Next actions, and
  re-read after each command. Audio-device inventory and MPRIS discovery have
  independent failure states so one missing service does not suppress the
  other. No new polling process, player owner, persistence or recipe command.
  Real player/browser compatibility and keyboard/AT hardware QA remain open.
- [x] Replace RiceSpice's timezone-only external handoff with a **native
  searchable timezone selector** using the installed `timedatectl`/timedated
  service. Read only genuine system-supported names; changes require a selected
  listed timezone, stale-state check, polkit authorization and post-action
  readback. Keep an installed external date-settings editor as optional
  fallback. Clock/NTP configuration, cross-platform time services, real
  authorization prompts and hardware QA remain open.
- [x] Expose **native read-only Mako history** in RicePlate's opt-in RicePop
  view as a second Active/Past tab with pointer and Left/Right keyboard access,
  bounded three-row navigation, on-demand refresh and explicit empty/error
  states. History entries can never be dismissed or replayed; both snapshots
  are cleared on close and validated before rendering. Mako remains the sole
  notification owner, and no private message store or polling daemon is added.
  OSD, rich actions, accessible announcements and real-device QA remain open.
- [x] Add a **first interactive native RicePop active-notification view** to
  the existing RicePlate schema-v4/v5 menu. A deliberately selected
  `notifications` action asynchronously reads the already-validated Mako
  bridge; a bounded three-row viewport offers keyboard/pointer selection,
  refresh, and explicit single-ID dismissal through the same CLI. Loading,
  empty, unreachable, stale and denial states are visible. Closing the view
  discards message content; there is no resident poller, second D-Bus owner,
  history replay or arbitrary recipe-supplied command. This is an incremental
  **active-alert inbox**, not full RicePop history, OSD, rich notification
  actions, accessibility signoff or independent native notification hosting.
- [x] Add an **on-demand RicePop/Mako notification inventory** for the opt-in
  Wayland session: `de notifications --json` reads bounded active and past
  notifications from the session's existing Mako host, strips embedded action
  identifiers and rejects malformed/oversized replies. It never claims its
  own D-Bus notification name, spawns another daemon, persists private
  content or replays third-party actions. This supplies data for a future
  native notification center; visual center, OSD and native history controls
  remain open.
- [x] Add **explicit one-notification RicePop dismissal** for the existing
  Mako host: `de notification-dismiss --notification-id UINT32 --json`
  accepts only a currently active ID from a fresh bounded inventory and
  invokes `makoctl dismiss -n ID` with fixed arguments. It never dismisses
  everything, replays an application's action, stores private notification
  content, or starts another notification owner. Missing Mako, stale IDs,
  timeouts and truncated lists return machine-readable failures. This is a
  safe control adapter, **not** the still-missing native RicePop history UI,
  notification-center panel or OSD.
- [x] Deliver the first **real native RiceSpice quick actions** in the bounded
  schema-v4 menu vocabulary: Wi-Fi radio toggle through NetworkManager,
  default-sink mute/unmute and 5% volume steps through WirePlumber. Run only
  after explicit pointer/keyboard selection on the existing worker thread;
  show pending/success/failure feedback, never run a recipe-defined shell
  command or create a privileged daemon. An opt-in example demonstrates the
  controls; the Waybar/labwc fallback omits them. The status labels themselves
  stay non-clickable. Device choosers, settings pages and notification ownership
  remain open; hardware permission/device acceptance is still needed.
- [x] Add an **on-demand RiceSpice playback/recording device adapter** to the
  installed CLI. `de audio-devices --json` reads and validates real device
  identities, descriptions and current defaults through the existing
  PulseAudio-compatible server (`pactl`, including pipewire-pulse).
  `de audio-default --device-kind sink|source --device-name NAME --json`
  requires explicit validated selection; an optional `--expect-current`
  prevents stale reviewed changes. Calls are fixed-argument, bounded and
  unprivileged, report missing/invalid data and distinguish unverified
  post-mutation state. The adapter neither starts a daemon nor pretends a
  settings GUI exists. Existing streams may retain their previous routing;
  native visual selection, accessibility, permissions and hardware QA remain
  independent gates.
- [ ] Implement usable native settings for screens, input, network, audio,
  Bluetooth, accessibility, power, timezone and user preferences.
  **Progress (8 Nov):** Native displays now have guarded mode, scale and
  position trials plus owner-private manually restored layout presets.
  **11 Nov milestone:** RiceSpice can now trial the *entire* saved arrangement
  as one transaction. The independent 18-second guard validates the complete
  connected topology, applies only advertised settings, and restores every
  touched display in reverse order on timeout, partial failure or interruption.
  One explicit confirmation commits the batch; a compositor-owned panel
  refresh follows. **11 Nov login-trial follow-up:** RiceSpice now offers a
  *disabled-by-default* option to attempt the saved layout on the next full
  Wayland login (never XFCE or a nested preview). A dedicated GTK confirmation
  window must be accepted within 18 seconds; a missing dialog, user decline,
  crash or logout leaves the independent monitor rollback in charge. Changing
  the saved layout disables the previous opt-in. This is an opt-in trial,
  **not** unconditional unattended persistent monitor configuration.
  Session-only labwc input, GTK cursor/text/high-contrast settings and an
  opt-in, supervised full-session Orca launcher are wired. Saved NetworkManager
  Ethernet/Wi-Fi/VPN profiles can be activated/deactivated after confirmation;
  active PulseAudio/PipeWire application streams support verified output
  routing, volume and mute. NTP changes have timedated readback. Remaining:
  durable unattended layout policy (if wanted) plus
  mixed-DPI/device/audio/assistive-technology hardware acceptance and specialized
  client-certificate EAP-TLS or provider-specific VPN editors. **8 Nov extension:**
  PEAP/MSCHAPv2 and TTLS/PAP/MSCHAPv2 profiles can be created natively with
  mandatory RADIUS domain pinning and OS/custom CA trust. 802.1X secrets go
  through `nmcli con up ... passwd-file /dev/stdin` without application storage;
  OpenVPN/WireGuard configurations can be imported with explicit non-autoconnect.
  The native Rust RicePlate panel now provides opt-in AccessKit/AT-SPI nodes
  for shell/task/menu/shortcut/calendar/notifications/tray surfaces, verified
  focus snapshots and bounded action requests routed through the existing
  Wayland event loop (not another service). Physical Orca, focus-transfer and
  assistive-technology device QA is still mandatory. The checkbox stays open.
- [ ] Delegate privileged actions to polkit/system services; never add a
  privileged always-on RiceBowl daemon by default.
- [ ] Complete live notification updates, native delivery and history owner,
  assistive-technology acceptance, alternate notification backends, richer
  text layout and consistent permissions/errors across settings/quick actions.
  The Mako-backed active/past inbox, detail actions and verified dismissal
  are implemented, but do not yet replace Mako. **11 Nov RicePop/RiceSpice
  milestone:** owner-private, versioned next-login Mako banner preferences now
  offer a safe installed-font selection (family plus bounded size), default
  timeout and visible-banner count. A disposable, owner-only config is generated
  solely for the full Wayland session; nested previews and XFCE keep their
  existing notification setup. DND ownership verification accepts this
  explicitly bounded private config. Active Mako is never restarted for edits.
  **11 Nov compatibility fix:** notification inventories now read the stable
  Mako `ListNotifications`/`ListHistory` D-Bus interface and validate typed
  `aa{sv}` replies. Ubuntu 24.04 ships Mako 1.8, which has no `makoctl -j`;
  later Mako 1.10 changed the command's output to human-readable text before
  1.11 added its own JSON mode. CI now tests delivery, inspection and exact-ID
  dismissal against a real Mako 1.8 daemon under an isolated headless labwc
  session. Physical Wayland/Orca and native delivery remain open gates.
- [ ] Integrate a secure lock screen, idle policy and suspend/resume.

**Done when:** common desktop settings and recovery workflows no longer
depend on the XFCE session.

### 3a — RiceClip and RiceShot (P1 suite utilities; not core 1.0 blockers)

Both tools live **inside the RiceBowl repository**, share RicePlate/RicePack
presentation tokens and existing Wayland integration, and have **no independent
repository or mandatory always-on service**. Complete the session, clipboard
and portal interoperability gates first. Their unfinished optional features
must not be represented as blockers for the Wayland DE 1.0 core release.

**RiceClip — opt-in clipboard history**

- [x] Add the **explicitly launched, foreground-only text watcher and bounded
  session-memory history** as an initial RiceClip 0.1 core. Use native
  `wl-paste --type text --watch` (which requires wlroots data-control) and a
  0600, same-UID local runtime socket; do not own the selection, persist
  clipboard bytes, install autostart or duplicate the screenshot tool.
  CLI status/list/copy-back/pause/resume/clear, size/item caps, UTF-8 validation,
  deduplication and failure reporting have deterministic Python tests. The
  cloud runner disallows new AF_UNIX sockets; GitHub CI should exercise the
  real socket round-trip, while physical text clipboard use remains unaccepted.
- [x] Exercise the opt-in RiceClip watcher in the existing disposable real
  labwc/XWayland clipboard smoke: synthetic Unicode text selection,
  event-driven ingestion, private socket CLI, explicit copy-back, clear and
  SIGTERM teardown. This tests the compositor data-control path in native CI,
  not user-device focus, sensitive-app detection or live desktop acceptance.
- [ ] Verify the actual clipboard/data-control capabilities of the supported
  labwc session on hardware; extend event-driven collection to URI and supported
  image formats with separate bounded limits. Do not start a polling loop or
  a second clipboard owner.
- [ ] Add a RicePlate-invoked searchable history UI with keyboard navigation,
  copy-back, pins and configurable retention; preserve focus/selection and
  support cross-rice token changes without a duplicate UI implementation.
  **12 Nov software candidate:** an explicit, nonresident GTK3 browser is
  available through `de clip --clip-op gui`: local preview-only search, keyboard
  row selection, manual refresh, guarded revision-based copy-back and confirmed
  clearing, with no clipboard persistence or implicit watcher. The indexed
  history race is handled by a backwards-compatible per-watcher revision in
  the socket protocol. **12 Nov native-action candidate:** the allowlisted
  `clip-history` action now opens this GTK client from RicePlate menus,
  native panel action components and the optional Waybar/labwc fallback,
  without starting the watcher. The normal XP-Luna sidebar and the distinct
  Heritage demo expose it; the size-constrained Luna-Columns six-row shelf
  remains unchanged. An isolated compositor pointer test must still pass CI.
  **12 Nov follow-up candidate:** the existing on-demand GTK client now
  supports up to five volatile session pins via the same bounded watcher IPC.
  Pinned entries form a stable, non-evictable prefix of the 20-item ring; pin
  and unpin require both the current history revision and watcher identity,
  and never run an external process. The pins disappear on clear/logout.
  Tests cover limits, deduplication, eviction, stale/restarted watchers and a
  real synthetic-content labwc clipboard round trip. This is CI-gated and
  not physical acceptance. Native in-menu history rendering, configurable
  retention, cross-rice presentation and device QA remain unfinished;
  the parent checkbox stays open.
- [ ] Keep history **off until explicitly enabled**; default to session-only
  memory, clear on logout/lock or user action, and never log clipboard contents.
  The watcher remains opt-in and volatile. **12 Nov lock integration candidate:**
  a shared full-session `de lock` helper now waits for `swaylock -f` to confirm
  the compositor lock before sending bounded `pause` and `clear` requests to
  the existing watcher; recording remains paused until manually resumed,
  preventing immediate clipboard re-ingestion during lock. The native RicePlate Lock action, generated Waybar panel/labwc
  menus, labwc Win+L binding, swayidle timeout, before-sleep and logind lock
  events all use this same path. A failed or absent
  watcher never prevents locking; cleanup failures are reported without content
  disclosure. The real labwc smoke verifies IPC against synthetic text with a
  fake lock acknowledgement, **not a physical locked screen**. Third-party
  direct locks, external compositor protocols and hardware suspend/unlock
  acceptance remain open. **12 Nov GTK privacy candidate:** the already-open
  RiceClip browser subscribes to a bounded, same-UID, event-only socket
  stream; pause/clear/resume and watcher teardown revoke visible previews
  and search text without polling or a second daemon. Paused snapshots
  are hidden even in the pause-before-clear interval; in-flight GTK
  refreshes may not resurrect stale rows. Unit and real headless-labwc
  screenshot-difference tests are required before the candidate is
  merged; no physical locked-screen or third-party locker QA is claimed.
  Keep the parent gate open.
  Offer pause and app exclusions as best-effort protections, without claiming
  that password/sensitive content can always be detected. Persistent history
  is a separately reviewed opt-in feature, not a minimum requirement.
- [ ] Test plain text, Unicode, large payload limits, image/URI handling,
  owner exits, app switching, focus, lock/logout cleanup, unavailable
  protocol support and keyboard/accessibility behavior on actual Wayland.

**RiceShot — on-demand screenshots and annotation**

- [x] Start an **on-demand compositor capture CLI** (`de shot`), reusing the
  existing private, no-overwrite `grim` PNG capture contract for full-desktop,
  `--monitor` output and user-selected `slurp` region screenshots. Validated
  modes/geometry, bounded image dimensions, owner-private file creation,
  cancellation cleanup and stable JSON errors have Python regression tests.
  It creates no daemon, global keyboard binding or XFCE change. Portal-based
  fallback, real multi-output/fractional-scale selection tests and explicit
  window capture remain open; direct compositor capture requires a supported
  Wayland screencopy backend and the user's invocation.
- [ ] Provide a lightweight crop/arrow/text/blur annotation flow, then
  integrate RicePlate shortcuts and RiceBowl visual tokens. Explicit
  **clipboard copy** is already available via `de shot --clipboard`, using
  `wl-copy` and a temporary 0600 PNG that is removed on success or failure;
  saving uses the existing exclusive-link no-overwrite path. Clipboard
  ownership is delegated to the ordinary Wayland selection helper; no RiceShot
  recorder, scraper or resident history daemon is started.
- [x] Route the opt-in labwc **Print** (full desktop) and **Shift+Print**
  (interactive region) keybindings through the same guarded RiceShot clipboard
  command. The packaged session PATH resolves the RiceBowl Wayland app;
  nested sessions use the existing opt-in user installation. No XFCE/X11 or
  global system shortcut is modified. XML/argument tests pass; real physical
  shortcut/focus and unavailable-tool feedback remain open.
- [ ] Test cancellation/denial, missing portal backend, multi-monitor,
  fractional scaling, cursor choice where supported, focus recovery,
  annotation output and copy/save errors; verify captures on physical Wayland
  hardware. Video recording is a later, independently scoped enhancement.

**Acceptance:** each tool can be absent or disabled without breaking the
desktop, has bounded memory/CPU overhead and honest error states, and passes
real labwc device checks plus targeted integration tests. No new repo, shared
daemon or duplication of RicePlate/RiceSpice/RicePop responsibilities.

### 4 — The Rice ecosystem

- [x] Provide an initial safe author entrypoint for bundled-to-private recipe
  creation and read-only custom validation through `ricebowl de recipe-init`
  and `de recipes --recipe`.
- [x] Extend the strictly validated **panel-only** recipe contract with opt-in
  schema-v2 launcher/task/clock widths; apply the widths to native RicePlate
  geometry and hit testing, and expose minimum widths in the Waybar adapter.
  Keep schema v1 as the unchanged default; a complete RicePack v2 is pending.
- [x] Add **schema-v3 hierarchical panel composition** to the shared contract:
  bounded horizontal `group` trees, `gap`, static safe-ASCII `label`, and known
  `widget` leaves; native Rust geometry/drawing/hit testing and the temporary
  Waybar adapter interpret the same data-only recipe. Expose primitives, exact
  property limits, draft-edit paths and semantic review in the AI Creator catalog.
  Cover both renderers with a common fixture and real headless labwc smoke.
  This milestone is **panel-only**: full desktop regions, responsive layout
  constraints, tokenized visual states and source-image conversion remain open.
- [x] Extend schema-v3–v6 panel composition with a **bounded, noninteractive
  divider** (`type: divider`, width 6–32px). Python validation, Rust native
  geometry/painting, the Waybar CSS fallback and Creator discovery/review share
  this same data-only primitive. Reject unknown properties and keep the divider
  out of clickable hit regions. This does not yet cover portable icons/fonts,
  rich desktop components or full mockup-to-rice conversion.
- [x] Introduce **opt-in schema-v4 shell composition** as a vertical slice:
  validated grouped root-menu actions compiled to a private labwc menu,
  allowlisted bundled wallpaper applied through swaybg, actual native task
  radius/label padding tokens, and a live compact panel breakpoint (Waybar
  supports offline width-specific compilation, not live reflow yet). Extend
  read-only Creator discovery/review and safe draft edits across these fields.
  Never permit arbitrary generated commands, image paths or XML fragments.
- [x] Add **opt-in schema-v5 native desktop shortcuts** as a bounded first slice:
  1–8 clickable icons at validated, non-overlapping fixed coordinates, each
  bound to one of three safe action IDs. RicePlate draws small transparent
  Bottom-layer surfaces inside its existing Rust process; the rest of the
  desktop remains clickable by labwc. Native headless CI captures the result.
  Schema v1–v4 and the Waybar fallback remain valid; the fallback does not
  display desktop icons. This is not yet a full desktop widget/input engine.
- [x] Add **single-output native shortcut reflow**: use compositor logical
  dimensions (including fractional scale where advertised), reserve the panel
  workarea, preserve valid positions and park icons outside the output when no
  safe hit region fits (without destroying their layer-shell role). Rust
  geometry tests cover normal, compact and insufficient workspaces.
  True multi-output ownership remains open.
- [x] Implement the first **native schema-v8 Layout Engine foundation**:
  preserve nested panel/menu compositions; add strictly validated, bounded
  clock/date/system desktop widgets; jointly place shortcuts and widget surfaces
  around a percentage-based reserved window workspace; and hide selected
  widgets at the existing live compact breakpoint. Reflow per logical output
  and secondary-output hotplug without a new helper or executable recipes.
  Share a Python/Rust fixture, Creator pointers and component-catalog contract.
  The reserved workspace is **not** labwc window placement or tiling; Waybar
  does not render the native widgets, and rich widget composition, authoring UI
  and real-device acceptance remain separate release gates.
- [x] **Foundation Sprint 1: full-output collision recovery** — when a saved
  desktop shortcut or widget collides with a reserved window region, inspect
  free cells throughout the supported logical coordinate range rather than
  only the first few columns. Preserve nearest-first deterministic placement
  with bounded work and no candidate list. Regression tests cover wide-output
  reserved regions, mode changes, giant invalid modes and collision safety. No
  window-manager control or cross-monitor dragging is implied.
- [x] Add **first native shortcut editing interactions**: distinguish click
  from pointer drag, expose an on-demand keyboard focus frame and 16-pixel
  arrow-key moves, and persist positions separately for each selected rice in
  an owner-private bounded JSON file. Reject stale actions/labels and symlinks;
  never write back to source rice recipes. Skip saved overrides in deterministic
  nested Creator captures. Pointer/focus geometry and persistence have Rust
  tests; real input-device/drag QA is still required.
- [x] Start a **real Wayland screenshot QA path**: capture headless native
  labwc output with grim into CI artifacts, allow no-overwrite manual captures
  and report deterministic pixel-difference metrics for an offline reference.
  Extended with real 1024×768, 1366×768, 1920×1080 and 1.25-scale CI capture
  evidence, manifest hashes, panel/icon-region differences, clipping checks,
  private overlay and heatmap diagnostics. This is diagnostic tooling, not a
  validated perceptual/functional accuracy score. Real mixed-DPI/multi-output
  device acceptance, approved image baselines and interaction checks remain open.
- [ ] Complete native desktop interaction and accessibility: basic
  move/focus/key controls, independent named-monitor saved positions,
  hotplug/reflow, bounded v8 desktop status widgets, v9 validated interactive
  action widgets with keyboard/pointer/AT-SPI semantics, and AT-SPI status
  labels are implemented; cross-monitor drop logic has software coverage but
  needs hardware interaction QA. Richer configurable widgets and physical
  keyboard/Orca QA remain open.
- [ ] Implement visually configurable, truly interactive native start menus
  (beyond the initial functional labwc fallback menu), including navigation,
  searching, pinning and reusable layout variants. Action search and pins,
  v6 tab/sidebar navigation and bounded group content composition work. A
  bounded, aspect-preserving small-output fit prevents full-size menu and
  notification surfaces from clipping on rotated/tiny monitors. Native menus
  now use a compact, full-resolution paged action list at supported small
  sizes (at least 168×144 logical pixels), including composed actions, search,
  pointer hits, keyboard paging and matching accessibility rows. RicePop lists
  and details also use full-resolution compact rows with per-width body wrapping,
  action/page navigation and matching hit/AT-SPI targets. Extreme outputs below
  168×144, richer
  icon layouts and device QA remain open.
  - [x] Give opt-in XP Luna Columns a native **All Programs** page over the
    already bounded XDG app index, with pointer/keyboard paging, real Gio
    launches, accessible empty-state/counter and visible Back navigation.
    The external launcher remains the default for other rices. Rust state
    tests and a headless-compositor click/restore regression cover this path;
    physical app-launch/input QA remains open.
  - [ ] Finish Luna's in-menu app filter: keep typing/Backspace inside the
    bounded XDG-only list, clear the query without leaving the page, and
    expose truthful no-match/results state to the painter and AT-SPI. Rank
    filtered apps by name relevance without reordering the base list. Rust
    regression is added in the stacked PR; native CI remains the merge gate.
  - [ ] Prioritize actually launched desktop entries in Luna's short
    in-menu app preview, keeping history bounded to eight, session-local and
    isolated from other rices. Regression is added; native compositor
    verification is still required before merging.
  - [ ] Harden the optional XP Luna recent-app file contract against
    parent-directory replacement races. The Directory-FD candidate walks
    absolute XDG path components with no-follow directory opens, pins the
    owned private history directory and uses relative open/rename/unlink
    operations with durable sync. Rust regressions substitute directories,
    ancestor symlinks and non-regular FIFO entries; full CI is a merge gate.
    This protects against path redirection, not arbitrary same-UID processes
    racing entries inside the private directory. Explicit privacy clear and
    physical-device acceptance require separate validation.
  - [ ] XP Luna native places shelf: add fixed Gio-backed My Documents and
    My Computer actions with existing Settings/Notifications/Session entries
    preserved; compact six-row right column and Rust pointer/keyboard bounds.
    Implemented on an isolated PR branch; native CI and device QA are pending.
  - [ ] XP Luna native taskbar pointer fidelity: distinct Start/task
    hover and pressed paints from real per-output Wayland pointer events,
    cached task-group hit lookup and legacy visual regression tests.
    Implemented on an isolated PR branch; headless CI and real-device
    acceptance are pending. Native high-DPI typography remains open.
  - [ ] XP Luna Recycle Bin desktop link: allowlisted `trash` icon action,
    original native raster art, safe `gio open trash:///` navigation only,
    current Creator and per-output icon layout preserved. This code is a
    CI-gated candidate; GVfs availability and real-device icon input remain
    pending. Trash deletion/emptying is deliberately out of scope.
  - [ ] XP Luna native Start footer: introduce separate Lock, Log off and
    Close pointer actions (no shell evaluation), gated to opt-in themed columns;
    draw original bevelled iconography and a genuinely unavailable logout state.
    Preserve other rices and the small-output single-Close fallback. Rust hit/
    pixel tests plus real compositor pointer-hover capture are in PR; CI and
    physical-device acceptance are required before checking this off.
  **Exact XP/7/10 menu reconstructions are deferred to the post-framework
  fidelity gate above**, not blocking this foundational milestone.
- [ ] Make responsive shell layouts live across every backend and surface,
  including Waybar fallback and multi-monitor hotplug; expand reusable design
  tokens to typography, states, iconography, spacing and motion.
  - [x] Add **schema-v10 bounded appearance tokens**: 1×/2× native bitmap
    type scale, regular/bold weight, inter-item spacing and shared focus/hover/
    disabled colors across native panel/menu/desktop status surfaces and Waybar
    CSS. Creator draft/review, catalog v11, RicePack and parser regressions
    share one versioned contract; v1–v9 remain byte-compatible.
  - [x] Compile **per-output Waybar compact/full layouts** from an optional,
    bounded `wlr-randr --json` inventory at session start, live apply and
    Waybar rescue; missing inventory degrades to the safe original layout.
    Waybar config has output-scoped bar/CSS variants without extra polling.
  - [x] Make **previously unknown hotplug outputs receive a compact Waybar**:
    append a validated catch-all bar with exclusions for every known output,
    avoiding duplicate bars on existing outputs. On a confirmed RiceSpice
    mode/scale change, ask only the owner-private live supervisor to rebuild
    the current recipe's Waybar process; retain the old bar if the new one
    exits on startup. No global process signals or polling.
  - [x] Expose explicit `de display-refresh` for **externally changed** output
    modes/scales, using the same private supervisor and failure-safe replacement
    as guarded RiceSpice changes; do not secretly poll or signal other Waybars.
  - [x] Observe external compositor output changes **automatically** when the
    optional native RicePlate binary and `wlr-randr` are installed: a surface-
    free, event-driven Rust `wl_output` watcher notifies only the owner-private
    Waybar supervisor; it debounces bursts and restarts Waybar only if the
    validated output configuration changed. Watcher failure leaves the explicit
    `display-refresh` recovery command available. No output polling, global
    signals or service outside the opt-in session.
  - [x] Reflow RicePop notifications at native pixel resolution for supported
    small outputs, including paged list/action rows, detail body wrapping and
    compact pointer/keyboard/AT-SPI parity; regular output layout is unchanged.
  - [ ] Finish extreme-size surfaces below 168×144 logical pixels and add
    portable font families, fluid type sizes, richer icons and reduced-motion
    semantics. Physical hotplug and mixed-DPI acceptance remain outstanding.
- [x] Allow safe offline import/export of validated, non-executable, panel-only
  JSON recipes into a private per-user collection; preview by imported ID.
  Full multi-component RicePacks with artwork, screenshot conversion and a
  transactional apply/restore pipeline remain open.
- [x] Persist the next opt-in Wayland panel recipe selection in owner-private
  state with one-level rollback and classic fallback on invalid/missing state.
  Live shell switching and cross-component transactions remain open.
- [x] Define a small versioned profile contract between RiceBowl, RiceField
  and Taskotto. External applications work without RiceBowl installed.
  - [x] RicePlate recipe → Taskotto v1 data-only TOML export and fixture,
    with validated color/theme mapping and no-overwrite private output.
  - [x] Add optional client auto-discovery with real CLI schema preflight,
    private RiceField RiceProfile v1 / Taskotto RicePack v1 live files and
    coordinated preflight, apply and restore inside the opt-in labwc session.
    Failed commits and later selection failures recover previous app files;
    missing/incompatible clients are excluded without changing defaults.
    App watchers eventually adopt valid updates (~2–3 seconds), but frame-level
    acknowledgement and crash/power-loss atomicity are still open QA gates.
- [ ] Support rice-specific structure, spacing, colors and components with
  validated settings, not an unsafe arbitrary runtime plugin mechanism.
- [ ] Specify a versioned, schema-validated rice recipe format for composable
  panel, menu, desktop, widget and settings layouts, visual tokens, assets,
  responsive behavior and explicit supported system-action bindings.
- [ ] Provide a documented mockup-to-rice authoring workflow, editable
  templates, isolated preview and safe pack import/export. An AI-generated
  reference must be usable without any required AI/cloud runtime.
- [ ] Define an **agent-readable component catalog**: stable IDs, capabilities,
  configurable properties, allowed actions, accessibility semantics, examples,
  schema versions and explicitly reported unsupported components/states.
- [x] Publish the first **read-only, versioned panel-component inventory**
  (`ricebowl de catalog --json`), with stable IDs, true native/Waybar support,
  strict recipe limits and known fixed behaviors. The original inventory was
  panel-only; an additive catalog-v6 contract now reports actual native
  launcher/task keyboard support, output-bound menu/calendar behavior and
  desktop icon drag/move/persistence alongside explicit missing capabilities.
  Full menu/desktop/settings component discovery, richer accessibility semantics,
  Creator draft commands and examples remain open under the catalog gate above.
- [x] Add an on-demand, **read-only semantic recipe review** (`ricebowl de
  review --recipe ... [--compare ...] --json`) with a v1 response, canonical
  SHA-256 fingerprint, fixed JSON Pointer field diffs, honest native/fallback
  inventory and safe structured errors. It uses the existing restricted recipe
  loader and never changes selected rices. This is not a graphical preview,
  transactional draft editor, asset-manifest validator or full Creator API.
- [x] Add the first **agent-authored component edit** contract to the catalog:
  allowlisted JSON Pointer `set` operations, bounded input, immutable recipe
  identity/schema, revalidation through the Runtime's panel parser, private
  no-overwrite draft creation (`ricebowl de draft-edit`), stable JSON error
  response and reviewable semantic changes. This supplies no executable
  plugin hooks or resident Creator process. Full multi-region editing,
  responsive rules, visual QA and live transaction/rollback are still open.
- [x] Expose the **real offline visual comparator through RiceBowl's installed
  Creator CLI** (`de visual-compare --reference ... --actual ... [--recipe ...]
  --json`), sharing the standalone script's engine with stable versioned
  results, path-free machine errors, explicit artifact flags and honest
  unsupported fidelity semantics. This is comparison of supplied captures,
  not an automated screenshot capture, active desktop mutation or GUI preview.
- [x] Expose an explicit **real Wayland Creator capture** endpoint (`de capture
  --output /absolute/new.png [--json]`), reusing `grim` only on user invocation
  inside the current Wayland session. Require new owner-private output with
  no overwrite of files or symlinks, bound size and runtime, report content hash
  and stable machine errors. Never automatically capture private windows or
  claim that this creates/isolates a nested compositor session.
- [x] Provide a **first isolated, native headless Creator render** endpoint
  (`de render --recipe ... --output /absolute/new.png [--width ... --height ...
  --scale ...] --json`): validate the recipe, start a private labwc/pixman
  compositor, render original bundled wallpaper and native RicePlate surfaces,
  capture via the existing Creator CLI, publish a verified PNG without
  overwriting, then terminate all render children. Its CI uses real native
  pixels and content hashes. Not yet an editable preview GUI, Waybar render,
  perceptual test, active apply/rollback, or complete multi-output harness.
- [x] Harden headless Creator renderer teardown: track one private render
  session, terminate descendants after a wrapper exits, never signal unrelated
  reused PIDs, validate staged PNG bytes and receipt before publication, and
  test real failure/timeout/fork cases with native CI. No lingering renderer
  is allowed to keep the session alive after successful capture.
- [x] Add an on-demand **Creator API v1 command inventory** (`de creator-api
  --json`) with stable implemented command names, true side-effect boundaries,
  version/flag/exit-code discovery and an explicit limitations list. No
  resident Creator service or invented live apply endpoint.
  - [x] Upgrade discovery to **Creator API v2**, including enumerated
    schema-v10 feature negotiation, supported/unsupported capabilities,
    an ordered offline-authoring workflow and explicit machine-readable
    mutation scopes for all advertised commands. This is a read-only
    capability contract; it does not introduce a resident editor or automate
    active-session changes.
  - [x] **Creator API v3: review-before-create** adds read-only `de draft-check`
    through the same full recipe parser and semantic diff as `draft-edit`.
    Agents can pin both source and proposed draft SHA-256 on private creation;
    changed input is rejected without publishing or activating a rice.
    Filesystem-level immutable source snapshots remain open.
  - [x] **Creator property-schema discovery** publishes a standalone JSON
    Schema 2020-12 per actual recipe version
    (`de creator-schema --recipe ID --json`). It covers every allowlisted edit path, supported schema-version
    boundaries, typed panel/desktop/menu/layout components, colors, content-
    addressed assets and bounded values. A deterministic schema fingerprint
    accompanies the source recipe fingerprint. Cross-property invariants and
    duplicate references still require the full parser and `de draft-check`;
    no schema-only result is treated as safe to apply.
  - [x] **Creator reproducible source snapshots** add `de creator-snapshot`
    for offline, content-addressed recipe copies with a canonical byte-level
    SHA-256 filename, 0400 mode, 0700 storage, atomic no-overwrite creation
    and idempotent reuse. Every `recipes.load()` verifies snapshot bytes before
    parsing, including review/preflight/draft-edit/preview. Existing tampered
    or symlinked targets are refused, and full semantic fingerprints remain
    available for checked edits. No active session or XFCE settings change.
    This is an owner-private sealed snapshot, **not** a privileged Linux
    `chattr +i` immutable file; the same user can intentionally change it.
  - [x] **Creator interruption recovery** publishes each draft's durable
    fingerprint/parent receipt **before** making the corresponding JSON file
    visible. Crashes between those steps leave a recoverable orphan intent,
    never an apparently valid new draft without its history. The read-only
    `de creator-recovery --json` lists bounded incomplete versions; with
    `--recipe` it verifies the last intact ancestor even across damaged
    intermediate revisions. A separate,
    explicitly hash-guarded `de creator-recover` copies only the last verified
    parent into a **new** private version; neither the failed target nor any
    active Wayland/XFCE session is modified. Legacy drafts without receipts
    cannot claim authenticated ancestry. Live recovery and real hardware
    acceptance have separate contracts below.
  - [x] **Creator GTK reviewed publication gate** connects the on-demand UI to
    that preflight: scrollable complete before/after values and both semantic
    fingerprints appear before the user authorizes a new private version.
    Save/render/export cancel without publishing when approval is withheld;
    the eventual write rechecks both hashes, including changes made after
    preflight. Existing saved versions and active session remain untouched.
  - [x] **Creator persistent draft lineage** stores a private, no-overwrite
    version receipt for every new template, save, fork and schema upgrade.
    Each receipt binds the parsed recipe fingerprint and the exact predecessor
    filename/fingerprint, with bounded, no-symlink traversal and corruption
    detection. GTK Previous version now works after restarting the app; a
    Version history dialog opens verified ancestors without selecting a live
    rice; the read-only `de creator-history --json` exposes the same chain to
    agents. Legacy drafts remain readable but have no authenticated ancestors.
    A same-user adversary can still edit/delete owner-writable files; this is
    corruption detection, not filesystem-level immutable snapshots.
- [x] Ship the first **on-demand GTK3 Rice Creator 0.1 workspace** on top of
  the actual schema-v10 recipe parser and API: four real templates, labeled
  style/structure controls, reordering and bounded addition/removal of existing
  panel primitives, owner-private immutable draft versions, semantic diffs,
  previous-version recovery, SHA-256 conflict detection and safe RicePack export.
  An explicit preview uses the already-supervised isolated native headless
  renderer and four screen geometries in a background worker. A user-local
  application entry and CI GTK/Xvfb creation/edit/save/undo screenshot smoke
  are included. There is no active-session apply button, new daemon or AI
  inference requirement. Richer tree editing, asset UI, visual overlays,
  interactive mockup conversion and physical hardware acceptance were deferred.
- [x] Deliver **Rice Creator 0.2 desktop-composition canvas**: a separate,
  accurately letterboxed logical-coordinate GTK authoring view with selectable
  schema-v10 desktop widgets, status components, shortcuts and reserved window
  area. Native GTK layer inspector edits positions, bounded text, shortcut
  actions and compact visibility; pointer drag and focusable arrow-key nudging
  use the existing strict parser. Adding/removing layers and saving/undoing
  write only private immutable versions. Real native screenshots remain a
  separate on-demand tab, never a fabricated canvas; GTK/Xvfb smoke and pure
  input/validation tests cover the workflow. Custom icon/font import,
  nested panel-group child editing and physical keyboard/AT acceptance remain
  future Creator milestones; wallpaper import arrives in 0.3.
- [x] Deliver **Rice Creator 0.3 local wallpaper library and attribution**:
  list verified existing owner-private SHA-256 PNG assets alongside bundled
  artwork; add GTK file-picker import, bounded import name, author, license,
  origin, optional public source reference, local preview and missing-image
  feedback. Preserve no-symlink/2 MiB/4096 px/PNG integrity checks from the
  existing asset core, with immutable owner-only provenance sidecars. The
  draft editor now allows schema-v6+ content-addressed asset IDs, and Creator
  export attaches declared per-wallpaper attribution to deterministic RicePack
  v3 (without applying, importing or running code). Add unit security/roundtrip
  checks, native GTK import/save/revert checks and isolated CI Xvfb smoke.
  Custom icon themes, fonts, multiple image assets per pack, nested component
  children, visual reference overlays and physical hardware acceptance remain
  separate milestones with new renderer/pack/schema contracts as needed.
- [x] Deliver **Rice Creator 0.4 component and nested panel editor**:
  native GTK inspector now allows schema-v9+ declarative component ID creation,
  label/binding edits and safe removal only when unreferenced by wide/compact
  panel or desktop widgets. A bounded recursive panel tree supports group /
  ungroup, child insertion, sibling reordering, known leaf editing, and
  independent wide and compact modes; every proposed structure passes the
  exact runtime recipe parser. Fix atomic `draft-edit` validation to resolve a
  newly proposed component registry before checking layout references, so a
  component and its first use can be committed together irrespective of edit
  operation order. Preserve immutable versions, no active apply, portable
  RicePack exports and the XFCE path; add pure malformed/depth/reference tests
  plus GTK Xvfb scenario coverage. Custom icon themes/fonts, visual-reference
  overlays, finer-grained component skins and actual hardware acceptance remain
  future milestones requiring their own renderer/schema/pack contracts.
- [x] Implement **Rice Creator 0.5 native visual asset authoring**:
  schema-v11 `artwork` selectors for one TrueType face and three 48×48 RGBA
  shortcut icons, bounded owner-private SHA-256 storage with immutable declared
  attribution, GTK import/selection and backward-compatible v10 upgrades.
  Native Rust reads only verified assets, rasterizes text once, and composites
  shortcut art; deterministic RicePack v4 includes verified selected assets.
  Real Wayland display, DPI, font legibility and accessibility require physical
  acceptance; Waybar custom faces, complete icon themes and AI image-to-rice
  conversion remain separate future work.
- [x] Make **Creator/RicePack v4 font and icon imports restartable after an
  interrupted write**: commit immutable attribution before publishing a
  content-addressed image or TrueType file. A missing image can only be
  completed by exactly the originally declared attribution; unmatched or
  unattributed files fail closed. Regression tests simulate a process exit
  between the two writes and repeat a full offline RicePack import. No files
  are replaced and the live desktop stays untouched; sudden power-loss
  durability and cross-asset atomicity are not claimed.
- [x] Add a **GTK Creator import-to-edit handoff** for schema-v10/v11/v12
  recipes: inspect a local RicePack v4 (or supported older pack), explicitly
  confirm its non-overwriting private installation, then fork its verified
  installed recipe under a new Creator ID. Installed recipes can also be
  reopened as editable copies without importing another archive. The source
  SHA is pinned across the chooser and creation, referenced assets are checked,
  and each immutable draft has a durable root history receipt. No active rice,
  next-login selection or XFCE settings change. Python roundtrip, stale-file,
  symlink and Luna-columns v12 tests pass; GTK picker smoke remains a CI gate.
  Editing legacy schemas v1–v9 still requires a versioned conversion workflow,
  and real Wayland GUI/Orca acceptance is pending.
- [x] Preserve **RicePack author/license/origin attribution through Creator
  import-derived drafts**, even after saved revisions, restarts and forks.
  The validated import receipt is bound to the immutable root draft history;
  any corrupt, untrusted or excessively deep ancestry blocks export instead
  of silently erasing credit. A changed wallpaper uses its own verified
  attribution, never the previous artist's. No new daemon or schema migration.
  Derivative authors must still review and update attribution before public
  redistribution; this does not license third-party artwork automatically.
- [x] Preflight **all referenced RicePack v4 font/icon identities and
  attribution collisions** before creating or installing files. A conflict in
  the second asset must not strand the first as an unreferenced new asset;
  two separate action icons referencing identical content are required to
  declare exactly the same author/license/label. Malformed archives fail
  during read-only inspect, and local existing-asset conflicts fail before
  mutations. Other filesystem failures and interprocess races are still
  fail-closed rather than a cross-file atomic transaction.
- [x] Extend **RicePack installation preflight to every known private
  destination**: recipe ID, existing exact import provenance, referenced
  private wallpaper bytes and all font/icon identities. Before creating the
  first asset, reject a stale or symlinked receipt, corrupt same-ID wallpaper
  or reserved recipe destination. The preflight receipt comes from the
  archive's validated byte fingerprints, so an interrupted *identical*
  receipt can resume even if no wallpaper was yet installed. Tests verify
  that predictable later conflicts create no earlier orphan assets; unexpected
  disk failures and concurrent writers are not a cross-file atomic commit.
- [x] Add **resumable, commit-last multi-asset RicePack imports**: retain one
  bounded validated archive inside the owner-private recipe collection and
  fsync its directory before any other asset write. A private five-second
  advisory lock serializes cooperating pack importers; verified wallpapers, font/icon
  attribution and their directory links are synced before publishing the
  recipe. An interrupted install can be resumed through `de pack-recover`
  or the next pack import, including after a real abrupt child-process exit
  and after successful recipe publication but before journal cleanup.
  Existing shared assets are never deleted or overwritten; a corrupt pending
  archive or changed installed recipe blocks recovery. This guarantees a
  recoverable private transaction path on supported local filesystems, **not**
  global atomicity against unrelated asset writers or failed hardware fsync.
- [x] Implement **Rice Creator 0.6 private visual reference comparison**:
  owner-controlled, bounded PNG references are SHA-256-copied into a private
  per-draft selection that survives immutable revision changes without
  entering the recipe schema or RicePack. A real isolated RicePlate render is
  compared at matching pixel geometry using the existing offline visual QA
  engine; the GTK view selector shows reference, native, half-width wipe,
  50/50 overlay and tolerant red difference heatmap. Configurable 0–255 pixel
  cutoff and 0/1/2 px raster tolerance accompany explicit raw/tolerated
  changed-pixel ratios, RGB error and layout warnings, **never** an invented
  perceptual or functional similarity score. Comparisons invalidate on edits,
  output changes or policy changes; damaged/symlinked files fail closed. Pure
  comparison/permissions tests and GTK smoke cover the authoring boundary.
  Real Wayland graphics, input/focus and multi-DPI QA remain open; screenshot
  decomposition and suggested component mappings are separate later work.
- [x] Implement **Rice Creator 0.7 reference-to-recipe review**: on-demand
  offline PNG sampling conservatively suggests detected top/bottom panel bounds,
  position, bounded height and visually distinct palette colors. Flat,
  decorative-band or ambiguous images yield no invented panel; menu identity, layout lanes and
  spacing remain explicitly unknown. A versioned 24 KiB JSON format binds
  optional human/AI-proposed safe menu/panel-layout/color/spacing edits to the
  exact private reference SHA-256, dimensions and saved recipe fingerprint.
  The existing bounded draft parser and full recipe validator reject unsafe
  actions, malformed structure, duplicate or stale proposals. Imported JSON
  can never claim trusted offline origin: even forged confidence values remain
  unchecked, and the current private reference is reverified before use. GTK shows
  evidence/confidence, requires individual checkbox approval and transfers
  only selected validated hints to an **unsaved** working copy; persistence
  still requires Review & save…, and no live session changes. JSON exports
  contain no screenshot pixels; external AI requires a separately consented
  user share. Unit and GTK smoke cover the review boundary. Full semantic
  automatic object/menus recognition, reliably faithful screenshot-to-rice
  compilation and real Wayland hardware QA remain open.
- [x] Implement **Rice Creator 0.8 manually annotated region QA**: author up to
  eight bounded, typed reference-pixel rectangles (panel, menu, desktop or
  unknown), remove/review each region and render numbered, colored outlines
  on a verified local screenshot copy. An explicit owner action can seed the
  list from untrusted 0.7 geometry, but never auto-accepts a semantic meaning
  or edits a recipe. Measure each region's raw/tolerated changed-pixel ratio
  and mean RGB error against identical-resolution **real native RicePlate**
  captures; tolerance includes neighboring pixels beyond rectangle edges.
  Versioned read-only JSON diagnostics pin the reference, render and saved
  recipe digests without exporting screenshots. The GTK controls are
  keyboard-accessible and invalidated on draft/reference/geometry/policy
  changes. No resident worker, active apply or AI service. These are pixel
  measurements, not perceptual or functional compatibility scores; real
  hardware QA remains future work.
- [x] Implement **Rice Creator 0.9 interactive region selection and correction
  QA**: an owner-activated GTK mouse drag draws live rubber-band feedback over
  the actual reference PNG, maps fitted preview coordinates back into bounded
  source-pixel rectangles, supports reverse drags, clamped release, Esc cancel
  and the existing keyboard-driven coordinate form. The 0.8 region validator
  remains the sole geometry gate. Region annotations persist across immutable
  versions *of the same draft with the same reference digest*, so the owner
  can correct fields in the existing schema-validated inspector, save a new
  revision, render a fresh native RicePlate capture and re-measure. A bounded
  12-capture, read-only correction journal compares only identical reference,
  region and pixel-policy identities, showing per-region percentage-point
  changes with recipe/capture SHA receipts, and can be exported privately as
  versioned JSON without screenshot bytes. Replacing references, changing
  rectangles, or changing comparison policy clears the history. This does not
  infer UI semantics, generate edits or mutate the live desktop. Real Wayland
  hardware/interaction/fractional-scale acceptance is still a 1.0 gate.
- [x] Provide a **Creator multi-geometry QA archive** using the existing real
  isolated labwc/native RicePlate renderer: four exact 1024×768, 1366×768,
  1920×1080 and fractional 1366×768@1.25 captures in one owner-private
  no-overwrite ZIP, each bound to the same recipe fingerprint and a verified
  PNG SHA-256 receipt. Publish the entire archive only after all four real
  renders succeed; a separate read-only offline inspector rejects missing,
  altered or unexpected entries, malformed receipts and mismatched dimensions.
  Versioned agent discovery, CLI JSON contracts and failure-injection tests
  cover the path. This is reviewable real-capture evidence, **not** automatic
  visual correction, human reference similarity, keyboard/input acceptance or
  physical monitor signoff.
- [x] Implement **Wayland RicePack v1 recipe exchange** (`de pack-export`,
  `de pack-inspect`, `de pack-import`): reproducible owner-private `.ricepack`
  archives, canonical schema-v1–v5 recipe, SHA-256 byte/semantic validation,
  optional user-declared provenance, strict two-entry ZIP allowlist, safe
  no-overwrite import and stable JSON errors. Imported recipes are not
  selected or applied. This **recipe-only** format references bundled assets;
  full visual asset manifests, preview evidence and multi-component apply
  transactions remain open.
- [x] Upgrade **RicePack export to v2 with a real bundled wallpaper asset
  receipt**: pin the wallpaper's installed bytes by SHA-256 and record separate
  user-declared per-asset license, author, origin and source reference. Reject
  corrupt/mismatched asset receipts at inspect/import and continue accepting
  validated legacy v1 packs. The archive still contains only known recipe JSON,
  **not** an external image or arbitrary code. Portable third-party asset
  packaging, full cross-component apply and live rollback remain open.
- [x] **Preserve imported RicePack authorship and license declarations across
  re-export**: a v1 owner-private data-only sidecar is written before a
  validated recipe becomes visible, bound to its semantic hash and the exact
  original bundled-wallpaper bytes. Re-exporting
  the installed recipe automatically carries both rice and wallpaper
  attribution forward. A modified recipe, missing privacy permissions,
  incompatible existing receipt or symlink fails closed; an interrupted
  import can safely retry with the exact same archive. The portable archive
  schema remains v2; third-party images and live apply are not introduced.
- [x] Extend **RicePack v3 / recipe schema v6 with one portable private PNG**:
  explicit owner-controlled `de asset-import`, strict PNG chunk checksums,
  dimensions and 2 MiB bound, content-addressed `asset-<sha256>` references,
  owner-private immutable files and no recipe-supplied filesystem paths.
  Deterministic v3 exports embed exactly `assets/wallpaper.png`; imports check
  identity and image bytes before installing the recipe, never activating it.
  Existing v1/v2 archive readers and bundled-only v2 export remain intact.
  This is **wallpaper-only**, not a complete multi-asset pack: fonts, icons,
  licenses verified by third parties, runtime live apply and full desktop
  transactions remain open. Physical PNG rendering/CI acceptance is required.
- [x] Add **explicit Creator next-login staging** (`de creator-status`,
  `de creator-stage`, `de creator-rollback`) with a required reviewed semantic
  SHA-256, optional compare-and-swap current-selection guard, one-level undo,
  private v2 selection-state fingerprint and fail-safe classic fallback when a
  staged recipe changes before login. Migrate old v1 state without breaking
  existing commands. This does not switch live Wayland/XFCE or provide a
  transaction across the desktop's future settings, windows and components.
- [x] Add a **review-gated live shell transaction** for the opt-in labwc
  session (`creator-live-status/apply/restore`): an owner-only per-display Unix
  socket in the existing supervisor, recipe/fingerprint/asset preflight, new
  panel and wallpaper startup before old-process shutdown, atomic private
  labwc menu replacement, CAS-protected next-login persistence and rollback
  on failed activation. Native-to-Waybar rescue uses the active recipe.
  Initial child survival is checked, **not** complete frame/input readiness.
  RiceProfile v1 cross-application coordination now covers compatible clients
  with guarded private-file swaps and rollback. Physical multi-app QA, suspend
  recovery and power-failure tests remain open; the full 1.0 gate is not met.
- [x] Harden **software failure recovery for live shell transactions**:
  preserve exact prior selection/undo state if a durable selection commit fails
  after rename, compare the expected v2 write under the original lock before
  compensating, and never clobber another Creator stage. Preflight/compensate
  all managed RiceProfile restores instead of leaving partial appearance files;
  attempt independent menu/selection recovery despite one client failure.
  Cancel a pending apply on session shutdown and bound crash recovery to one
  previous-rice restore and one fingerprint-verified Waybar rescue. Tests inject
  I/O, concurrent selection and panel crashes; no claim of power-cut atomicity,
  compositor-frame synchronization or physical suspend/relogin acceptance.
- [x] Persist a **Wayland live-switch recovery journal** before mutating a
  full session's panel, wallpaper, menu, optional app profiles or next-login
  selection. Each private, bounded no-overwrite journal pins the exact prior
  selection, reviewed target hash and Linux process identity (boot ID/PID/
  process-start tick). Successful changes and complete in-process rollbacks
  clear it durably; incomplete rollback retains evidence. On next full Wayland
  login, a dead owner's journal triggers compare-and-swap restoration of only
  that switch's next-login selection. Concurrent Creator staging wins; a
  still-live owner cannot be mistaken for a crash. Unsafe journals fail closed
  to an ephemeral `classic` login without erasing saved user configuration.
  `de creator-live-recovery --json` reports journal status outside the active
  session. Nested previews and XFCE are unaffected. Automated tests include
  simulated SIGKILL windows, stale fingerprints, symlinks and concurrent
  sessions; actual power cuts and multi-app hardware recovery remain untested.
- [x] Connect **GTK Creator 0.9 to the opt-in live Wayland transaction**:
  saved private revisions can be installed explicitly and idempotently with
  a SHA-256 guard on the *actual* imported bytes; an existing differing ID is
  never replaced, but an immutable revision can be forked to a new ID while
  retaining its full composition. Separate confirmed live apply/restore reviews the running
  supervisor, requires a matching installed recipe, passes active-selection
  CAS and semantic fingerprint to the established rollback-capable controller.
  X11 has no live activation, unsaved edits block handoff and uncertain socket
  completion is reported as unconfirmed. Unit tests cover stale files, races,
  ID collisions and live conflicts; device-level operation remains unaccepted.
- [x] Add an **interactive Creator try-before-apply window** for immutable
  saved drafts using the existing nested labwc/native RicePlate session path.
  Its GTK start/close action owns one subprocess, rejects stale drafts,
  missing binaries and unsafe runtimes before spawn, and tears down gracefully
  with bounded emergency termination if it hangs. Editing, static rendering,
  live install/apply/restore and next-login selection stay independent; the
  live apply button is disabled until a concurrent nested test is closed.
  Real desktop widgets inside the nested session can still operate real Linux
  devices. The full GUI-to-compositor input/focus test on physical hardware
  remains an explicit acceptance gate, not claimed by mocked GTK smoke.
- [x] Exercise the **complete Creator-to-Wayland software handoff** in CI:
  create two structurally different private drafts, install them without
  changing the login selection, apply and restore through the owner-private
  live supervisor socket, reject stale reviews and missing compositor helpers,
  and recover a prior rice after a simulated supervisor restart. An additional
  native labwc/RicePlate CI gate renders the **installed** Creator recipe IDs
  at two real headless output geometries (including fractional scale), checks
  captured pixels against semantic recipe and PNG hashes, and archives a
  source-commit-pinned manifest. These are isolated software tests: they do
  **not** yet prove real monitor, focus, application-window input, suspend or
  power-loss recovery, and are not physical 1.0 acceptance.
- [x] **Prove transactional Creator activation and explicit restore under injected
  failures** through the real owner-private supervisor protocol in CI. After
  a late next-login write failure, verify byte-exact restoration of the selected
  recipe and undo history, private labwc menu/chrome, optional RiceField/Taskotto
  profiles and previous live processes; confirm the next apply/restore succeeds.
  If labwc fails again while undoing a partial switch, report `rollback_failed`,
  retain the durable recovery journal and block further switching until a
  supervised next-login reconciliation. A failed explicit restore must similarly
  leave the current rice live and recoverable. Mocked child processes do not
  establish physical-frame or device acceptance.
- [x] **Harden the next-login CAS boundary and damaged-selection fallback**:
  match the entire previously reviewed private selection snapshot under its
  existing lock (active, previous, fingerprints), not only the active ID.
  Parallel Creator `A → B → A` changes must remain intact and cause an explicit
  review conflict, with transient components rolled back and no stale journal.
  A malformed selection must not prevent the safe Classic live supervisor
  from starting, while any new mutation remains blocked until the file is
  safely repaired. Tests cover controller and Creator-protocol flows; this
  remains software validation rather than physical multi-login acceptance.
- [x] **Serialize full Wayland next-login recovery after a supervisor crash**:
  concurrent logins now take an owner-private, persistent advisory recovery
  lock and re-read the pending record *after* obtaining it. Only one login can
  compensate a dead owner's selection and clear its journal; the next sees a
  clean state instead of a stale-record false `unsafe` result. Reject unsafe
  lock paths without modifying saved state. Automated tests reproduce the
  previous double-recovery race, simulate a real SIGKILL after selection
  publication, then confirm a clean follow-up login. This does not substitute
  for physical display-manager, power-loss or suspend/relogin acceptance.
- [x] Add **real Wayland taskbar lifecycle acceptance** in the isolated native
  labwc job: launch a real `foot` toplevel with a controlled app ID, assert
  that the existing foreign-toplevel handler receives the completed window,
  verify the native task region visibly changes, then close that app and
  verify both the protocol removal and restored empty panel pixels. Track
  minimized state explicitly so activating a previously minimized task first
  sends `unset_minimized` to the compositor. Rust unit tests cover protocol
  state decoding and malformed trailing bytes. Window trace logs are disabled
  by default and omit titles. Actual pointer/keyboard focus transfer, login
  hardware, XWayland and long-running app behavior remain open.
- [x] Add an **isolated real-pointer taskbar action gate**: a CI-only Rust
  virtual-pointer example sends an actual Wayland motion/press/release to the
  labwc screen; the existing RicePlate panel must minimize a live `foot`
  window on the first click and restore/activate it on the second. The test
  waits for independently reported foreign-toplevel state transitions and
  preserves the older open/paint/close checks. The helper is not installed
  and cannot inject input into a user session. Physical pointer, keyboard,
  screen-reader and mixed-DPI testing remain independent 1.0 gates.
- [x] Extend the **headless application compatibility gate** to launch a real
  X11 `xterm` through labwc's XWayland-aware startup environment, then require
  the same native RicePlate task lifecycle and pointer minimize/restore as a
  Wayland-native terminal. Keep the startup probe confined to isolated CI and
  fix `de check` to report whether the optional RicePlate binary is actually
  installed instead of calling the implemented shell planned. Neither check
  establishes clipboard/portal compatibility or physical GPU/session QA.
- [x] Add **bidirectional native Wayland/XWayland text clipboard CI** using
  compositor-owned `DISPLAY`/`WAYLAND_DISPLAY`, a live `wl-copy` owner,
  `xclip`, and `wl-paste`. Test both transfer directions with isolated marker
  data and bounded timeouts, without touching the user's login clipboard.
  This is not sign-off for rich MIME, drag-and-drop, sandboxed Flatpaks,
  portals, password managers or physical-device clipboard interaction.
- [x] Exercise real headless **Screenshot and ScreenCast portal requests** on
  the disposable labwc D-Bus/PipeWire session. Verify an actual PNG and
  ScreenCast CreateSession/SelectSources. On this pixman CI runner, Start
  rejects with response 2 (known wlroots renderer limitation); it is logged
  as unsupported, **not** a passing remote FD or stream. The unattended
  chooser override never touches the installed desktop. GPU-backed ScreenCast,
  Flatpak permission UX, frames and physical multi-monitor portal QA stay open.
- [x] Add an installed-bundle **crash/fail-closed/relogin acceptance** to the
  disposable unprivileged labwc login smoke: force-kill native RicePlate,
  require the live Waybar rescue and a second framebuffer capture; then kill
  the required idle/lock guard, require compositor shutdown, and boot a fresh
  native session in the same private runtime. No real login or XFCE state is
  touched; hardware suspend/relogin and compositor-crash recovery remain open.
  PR #219 native package CI passed.
- [x] Publish two **honest schema-v5 Creator demonstrators** under
  `examples/wayland/`: a classic-OS-inspired workstation and a structurally
  distinct original Orbit concept. They use only shared native primitives,
  original bundled wallpapers and known allowlisted actions. Native CI renders
  both at three resolutions plus fractional scaling, verifies exact recipe
  receipts and screenshot hashes, and archives reproducible visual diagnostics.
  This proves the limited current contract supports two styles, **not**
  high-fidelity OS cloning or the complete 1.0 authoring acceptance below.
- [x] Add a **second acceptance pair using schema v10**,
  `heritage-modern-v10` and `orbit-studio-v10`, with distinct component
  hierarchies, responsive panel variants, native status/action bindings,
  tabbed/sidebar menus and contrasting typography, state colors and spacing.
  Validate both as
  Python/Rust recipes and safe RicePacks; extend the same actual headless
  capture matrix to both (four resolutions/scales each). This is reproducible
  framework evidence, **not** functional physical keyboard/network or
  pixel-fidelity signoff.
- [x] Publish a **versioned, machine-readable Creator contract** (CLI JSON
  output first; optional local IPC only if justified) for discovering
  components, creating/editing drafts, validating recipes, previewing the
  real shell, capturing screenshots, comparing to references, exporting packs,
  and explicitly requested apply/restore. API v3 now publishes stable feature
  negotiation, supported/unsupported capabilities, mutation scopes and the
  existing on-demand CLI JSON commands, including read-only checked edit diffs
  and two optional reviewed fingerprints on private draft creation.
  Per-operation structured errors and explicit activation/restore contracts
  exist; the experimental GTK Creator has no general plugin runtime or
  automatic screenshot-to-rice conversion. Full
  per-property formal JSON Schema and physical interaction signoff are still
  separate follow-up work.
- [ ] Make agent-driven changes reviewable and reproducible: immutable source
  references, local/private draft workspace, deterministic validation,
  per-asset license/provenance metadata, clear diff/preview before apply,
  explicit user authorization for active desktop changes and transactional
  rollback. No arbitrary generated scripts, remote asset execution or
  privileged Creator daemon. Read-only CLI preflight and checked source/proposal
  fingerprints are implemented; immutable authoring snapshots and complete
  approval UX remain separate work.
- [ ] Implement an **isolated visual QA loop** using real nested labwc /
  RicePlate rendering (not synthetic mockup-only previews): capture
  deterministic multi-resolution and scaling screenshots, compare them
  with reference images via region/geometry and perceptual differences,
  emit machine-readable diagnostics and artifacts, then support iterative
  recipe correction. Separate anti-aliasing/font tolerance from actual
  layout regressions and require functional tests alongside similarity.
  Per-region RGB geometry diagnostics, capture provenance, bidirectional
  1–2 px rasterization tolerance with original metrics, and explicit SHA-256-
  pinned reference/recipe baseline approval with deterministic CLI regression
  exit codes are implemented. Full perceptual/font-aware similarity, automated
  corrective iteration and functional/multi-device QA remain outstanding.
- [ ] Validate malformed/oversized recipes, missing assets, unsupported
  widgets/actions, keyboard/focus semantics and rollback before applying.
- [ ] Port all seven styles individually while preserving names, legacy
  backup IDs and original assets.
- [ ] Coordinate RiceField default-file-manager integration after its 1.0
  acceptance. No forced global default application change.

**Done when:** switching a rice consistently updates every supported desktop
component, and incompatible clients degrade gracefully.

**Authoring acceptance (not yet implemented):**

- [ ] Build one high-fidelity existing-OS-inspired rice **through the shared
  recipe/component contract**, without a parallel bespoke shell or duplicate
  hardware backend.
- [ ] Build a second, visually distinct rice from an AI-generated or original
  static mockup using documented steps; record unsupported interactions and
  the code needed for any new reusable primitive.
- [ ] Show install, preview, multi-resolution real-shell captures,
  application-window interaction, keyboard navigation, live system actions,
  switch and rollback for both rices.
- [ ] Confirm the authoring and daily-use path works entirely offline once
  the required packages/assets are present and does not load unused rices.

**Creator / agent / visual QA acceptance (not yet implemented):**

- [ ] Using only the published catalog, schemas and documented interface,
  create two distinctly structured draft rices from (a) an OS-inspired
  screenshot and (b) an original or AI-generated mockup. The agent may
  request a new reusable primitive when needed, but may not silently
  invent working actions or bypass validation.
- [ ] Produce actual nested-shell captures at 1024x768, 1366x768 and
  1920x1080, plus a fractional-scaling case where supported; store recipe
  version, render inputs and capture environment for reproduction.
- [ ] Report visual differences with a reviewable image overlay/heatmap and
  structured per-region diagnostics. Establish tolerances on a stable
  reference baseline, flag unsupported/unknown elements honestly and do not
  advertise pixel-perfect fidelity from a similarity score alone.
- [ ] Prove every interactive control in both example rices has a supported,
  tested Linux action or an explicit disabled/unsupported state. Cover focus,
  keyboard navigation, window interactions, permission/error states and
  multi-monitor behavior; screenshot similarity alone never passes QA.
- [ ] Demonstrate offline Runtime startup, profile switching and rollback
  after Creator exits; confirm no AI service, authoring process, duplicate
  panel or unused rice remains resident. Record PSS/CPU measurements.

### 5 — Efficient, testable 1.0

- [x] Extend the existing opt-in PSS/CPU inventory to recognize labwc,
  Waybar, native RicePlate and selected session helpers, without a resident
  monitor or duplicate shell process. Scope is explicitly all matching
  user-owned processes, not one isolated Wayland login benchmark.
- [x] Add **opt-in current-Wayland-login process attribution** for the
  read-only `performance desktop --wayland-session --json` report. Filter known
  components by the exact private session-config marker inherited by labwc and
  its children, excluding nested previews, other concurrent sessions and
  unreadable `/proc` environments. This preserves the legacy all-user inventory
  and does not claim an exhaustive session process tree or measured device RAM
  targets; cold starts, mixed-DPI and long-running real-hardware sampling are
  still open.
- [x] Add a read-only package/CLI version consistency check and a candidate
  source-artifact gate; do not publish stable 1.0 without explicit device QA
  evidence (see `RELEASE_1_0_GATES.md`). Binary packaging remains open.
- [x] Make the isolated *preview login-session* Debian package byte-for-byte
  reproducible across wall-clock build times; 1.0 application/binary packaging
  remains an independent release gate.
- [x] Build a separate **amd64 native RicePlate preview `.deb`** from the CI
  Rust executable with versioned dependencies derived by `dpkg-shlibdeps`,
  deterministic archive metadata, exact extracted-binary comparison and no
  install scripts. It does not replace XFCE or provide the complete desktop
  distribution; real install/upgrade/uninstall QA and reproducible Rust inputs
  still gate 1.0.
- [x] Harden the standalone Wayland **package provenance**: build Core,
  Session and Desktop file payloads from the immutable committed Git tree
  rather than dirty/staged checkout contents; build the native package's
  control template from the same committed tree. Add a read-only four-package
  gate for package identities, architecture, dependency floors, Core BUILDINFO,
  file path ownership and forbidden maintainer scripts. Test staged source
  changes, untracked imports, provenance tampering, an injected XFCE file and
  an injected `postinst` in isolated scratch packages. The Rust ELF still
  requires independent reviewed build-input provenance; the gate does not
  install or sign artifacts.
- [x] Add a **negative installed-session recovery gate**: after an actual
  apt-installed native login, forced RicePlate crash, protected idle-guard
  shutdown and successful relogin, deliberately corrupt the owner's private
  next-login recipe selection and RiceSpice preferences *inside the disposable
  container*. Require another real labwc/native/swayidle login, a fresh Wayland
  screenshot, explicit safe-fallback diagnostics, no invalid recipe in the
  native process environment and byte-for-byte preservation of the damaged
  files for owner inspection. No host, XFCE or live user settings are touched;
  device-level restart and actual power-loss remain unaccepted.
- [ ] Measure cold start, settled PSS/RSS, CPU wakeups, relogin, long-running
  memory and mixed-DPI behavior for X11 and Wayland on actual devices.
- [x] Add a **read-only native on-device acceptance preflight** (`de acceptance`
  and `--json`): verify opt-in full RiceBowl labwc session markers and owned
  Wayland socket, required native/lock tools, and bounded `wlr-randr` output
  count/fractional-scale readiness. Never report hardware certification from
  executable availability or simulated CI. Keep a structured all-pending
  operator checklist for actual app launch, keyboard/focus, Orca, display
  hotplug, portals, suspend/lock, XFCE recovery and resource measurements;
  include fail-closed, privacy/redaction and CLI unit tests. Human execution
  and hardware signoff remain open.
- [ ] Remove redundant processes only after their responsibilities have been
  replaced, with comparison and rollback evidence.
- [ ] Port performance-critical resident components to Rust where profiling
  demonstrates benefit; no speculative full rewrite.
- [ ] Ship reproducible packages, uninstall/rollback, docs, CI and device QA.
- [ ] Test fresh login, corrupted config, missing backend, locked screen,
  sleeping/waking, low-memory and disconnected network cases.
- [ ] Gate 1.0 authoring claims on the two demonstrator rices, the published
  Creator/agent contract, reproducible visual QA evidence and validated
  recipe migration, recovery, responsiveness and runtime resource measurements.

**Done when:** RiceBowl is independently installable, fully usable and
recoverable as a desktop environment. RAM targets are measured, not promised.

## Phase 0–1 interface contract

- `macrice de check [--json]` probes installed tools and the current session
  without starting processes, reading private network data or changing files.
- `macrice de acceptance [--json]` is an explicit, read-only physical-session
  readiness check with a bounded display query; every operator acceptance item
  remains pending until verified by a real user on their own device.
- The existing `ricebowl` launcher will forward `de` directly to this CLI
  without changing its default Hub action.
- A successful **tool** preflight does **not** certify a working RiceBowl
  Wayland desktop. The result distinguishes the optional preview login session
  from the unfinished RicePlate/RiceSpice/RicePop environment.
- The Wayland session installer is opt-in, preserves user configuration,
  and has a reversible uninstall and independent XFCE fallback.

## References

- [labwc getting started](https://labwc.github.io/getting-started.html)
- [labwc desktop integration and protocols](https://labwc.github.io/integration.html)
- [XDG Desktop Portal documentation](https://flatpak.github.io/xdg-desktop-portal/docs/)
- [Current XFCE service ownership](XFCE_RESOURCE_BOUNDARIES.md)
- [RicePlate X11 preview and gates](RICEPLATE_DESKTOP_ROADMAP.md)

### XP Luna native desktop input fidelity (12 November 2026)

Opt-in mouse single-selection, blue shortcut highlighting, bounded timed
double-click activation and drag cancellation are implemented in RicePlate.
The CI test uses real compositor pointer events and a private Gio spy;
keyboard and accessibility actions remain one-step. Physical Wayland QA,
per-shortcut context menus and desktop-wide selection outside the small
non-input-stealing icon surfaces remain open.

### Native Luna shortcut context actions (12 November 2026)

The selected XP Luna profile gains a bounded, output-local, event-driven
right-click menu for shortcut Open, Next display and All displays. Pointer
and keyboard actions use fixed, validated native handlers. No full-screen
desktop input capture, custom labwc behavior or automatic filesystem writes.
Physical mouse, multi-output hotplug and focus QA still gate the release;
desktop background right-click and file-properties remain open work.

### Native XP Luna X11 parity sprint (12 November 2026)

- [x] XP-style Run and Help link semantics in the opt-in native Start menu;
  preserve existing Places, Session and footer, use compact ten-row hitbox.
- [x] Rust/Python/Creator schema parity for safe bounded menu action bindings.
- [x] Native Run/Help dialog surfaces, input validation, direct process argv,
  real error states, on-demand allocation, pointer/keyboard access.
- [x] Add compositor-backed screenshot regression for Start/Help/Run/error.
- [ ] Complete X11-style category Control Panel and Help Center depth.
- [ ] Match X11 pinned Internet/mail/recents and recent file submenu.
- [ ] Integrate RiceField Explorer navigation and device/volume views.
- [ ] Complete accessibility/input-method/hardware sign-off on Mint laptop.

[Full X11-versus-Wayland XP feature matrix](WAYLAND_XP_LUNA_PARITY.md).

### XP Luna / RiceField 1.0 integration (12 November 2026)

The native Luna shell now delegates real local drive and XDG user-folder
navigation to separately installed RiceField via its documented XP theme
and secondary-window CLI, with ordinary Gio fallback when RiceField is
absent. Non-Luna profiles, global MIME defaults and network/trash GVfs
navigation remain untouched. Validate actual file manager launch, window
focus and SMB behavior on the physical ThinkPad before release.

### SG5 — native single-line BiDi label ordering (16 November 2026; CI candidate)

The native shared text paint path now uses pinned unicode-bidi 0.3.18
(UAX #9 resolved embedding levels) to reorder **complete extended graphemes**
(UAX #29) in mixed Hebrew/Latin single-line shell labels. The same visual
order is used by the existing bitmap painter and TrueType measurement and
painting; proportional RTL clipping measures complete candidate plus ellipsis.
Ordinary LTR labels take a borrowed/allocation-free path. Tests cover mixed
RTL/Latin, combined accents, emoji, bitmap pixel receipts and legacy LTR.

This is intentionally not a full international text-engine acceptance:
fontdue does **not** support HarfBuzz/OpenType GSUB/GPOS contextual shaping,
mirrored glyph substitution, multi-line paragraph layout, complex-script
font coverage or Wayland text-input-v3 IME preedit.
Keep SG5 and SG7 open pending those independently implemented and tested
capabilities, and preserve all classic/XP LTR screenshot baselines.

### SG5 — native OpenType shaping and measured glyph advances (16 November 2026; CI candidate)

The built-in native TrueType renderer adds source-pinned pure-Rust rustybuzz
(0.20.1, reviewed Cargo.lock) and uses glyph-index rasterization through
the existing fontdue cache. It performs UAX #9 visual run ordering *without
reversing the logical input* before GSUB/GPOS; script shaping and combining
mark positions come from rustybuzz while glyph pixels remain clipped to the
actual native surface. The old allocation-free ASCII path and the classic
8x8 bitmap profiles are unchanged. Missing font clusters continue to render
one visible fallback glyph; shaped glyph and layout caches are bounded.
Native regression tests check Arabic contextual substitution, mixed LTR/RTL
layout, pixel paint and malformed/overflowing canvas bounds.

This step deliberately does not claim full font coverage (particularly CJK
on installations without a suitable font), an independent fontconfig family
selection, dual-affinity bidi caret/hit testing or a real IME client/browser
hardware sign-off. Exact-head Rust/Clippy/Wayland compositor tests and
screenshot baseline checks must pass before integration. SG5 and SG7 remain
blocked by issue #417 until the complete software text/input matrix passes.

### SG5 — AT-SPI native editor text/caret exposure (16 November 2026; CI candidate)

The composited Luna Run and Desktop Rename dialogs now publish a real
AccessKit TextInput with a single UTF-8 TextRun child and a grapheme-aligned
TextSelection caret. Character lengths use UTF-8 bytes per *extended
grapheme* where representable in AccessKit u8 units; exceptionally long
clusters use explicit scalar lengths rather than overflowing. The text is
attached to the AT-SPI snapshot only while the editable native modal is
open, never inserted into the action labels or persisted in logs. Model
removal discards text and stale focus. The actual compositor keyboard Enter
determines whether the node is focused; accessibility cannot fabricate input
ownership or execute Run commands. Unicode, empty-buffer, caret and teardown
regressions are tested. XFCE/X11 and non-Luna menus are unchanged.

This provides live text/caret metadata, not validated Orca speech feedback,
text-selection editing, AT-SPI programmatic text replacement or real IME
hardware acceptance. Leave SG5 incomplete until those software checks,
complex-script font coverage and exact-main CI are evidenced.

### SG5 — native Luna editable text selection (16 November 2026; CI candidate)

The actual Run and Desktop Rename modal editors now use bounded extended
grapheme selection: Shift+Left/Right/Home/End extends an anchor, Ctrl+A selects
all, regular arrows collapse a selection towards the visual edge, and typing,
Backspace or Delete atomically replace/remove the selected text. Selections
cannot split Unicode emoji, joined sequences or combined accents; replacement
at the 192-scalar limit is validated against the post-replacement size, with
rejected edits leaving the selection intact. Pointer caret placement cancels
selection without mutating the stored buffer.

Native painting highlights the selected visual grapheme spans, including
separate spans across BiDi runs rather than painting a false intermediate
range. The existing text-input-v3 surrounding-text transaction sends distinct
cursor and anchor UTF-8 byte offsets to the compositor. The transient AccessKit
TextInput now publishes a selection anchor separate from its caret; no key,
file name or command string is logged or persisted by this UI state.
Ctrl/Alt combinations cannot accidentally insert printable characters.
All of this is opt-in Luna native UI; XFCE/X11 and other rice engines are
unchanged. Unit regressions cover emoji/combining/RTL, selection replacement,
overflow, keyboard collapse, pointer cancellation and AccessKit metadata.

This patch does not establish full Unicode shaping/font coverage, discontiguous
BiDi dual-affinity, selection-by-pointer-drag, clipboard integration or real
external IME/Orca device acceptance. Keep SG5 and SG7 open until the
end-to-end software matrix and physical checks are separately evidenced.

### SG5 — RTL bitmap punctuation mirroring (16 November 2026; CI candidate)

Native 8x8 and unshaped text labels now apply Unicode BiDi L4 mirrored
display glyphs for a bounded set of common brackets in odd-level runs.
This uses the same UAX #9 grapheme-level reordering map as the existing
label painter; all logical text, caret positions, editable Run argv and
file names remain unchanged. LTR labels retain the borrowed zero-allocation
path and byte-identical classic screenshot layout. Regression coverage
includes bracket pairs, Hebrew run ordering, Unicode cluster handling
and the explicit non-mirrored ornate-parenthesis exception.

This is a scoped bitmap/unshaped display correction, not Unicode's complete
Bidi_Mirroring_Glyph database, shaped-font/hardware validation or dual-affinity
editor selection. SG5 and SG7 remain open until their complete gates pass.

### SG5 — compositor text-input-v3 IME transport (16 November 2026; CI candidate)

Native Luna Run and Desktop Rename now bind the compositor-advertised
zwp_text_input_manager_v3 to the actual keyboard seat. Only a real text-input
Enter for an editable, live modal surface enables the protocol. Surfaces,
capability loss and dismissal revoke the IME. Non-Luna, help, shell and
XFCE/X11 sessions do not acquire an IME editor or change global input settings.

The receiver buffers preedit_string, commit_string and
delete_surrounding_text until Done; the bounded editor validates complete
UTF-8/grapheme deletion, scalar caps and preedit cursor byte offsets before
applying edits atomically. The preedit is drawn underlined and remains outside
Run argv and filesystem rename storage until committed. Surrounding text uses
byte-offset cursor/anchor and is only sent to the focused compositor input
method. The direct-keyboard fallback is retained until an IME begins
delivering text events. Transport and editor tests cover malformed byte offsets,
partial failures, deletion/commit ordering, preedit visual state and Unicode.

**Not yet SG5 complete:** independently run a real external input-method
client (e.g. Fcitx5/IBus) against the compositor under headless CI, verify
IME real keyboard focus and multiple sessions, guard simultaneous physical
key/IME duplicate delivery, and implement full HarfBuzz-grade complex-script
shaping, mirrored punctuation, bidirectional selections/affinity and
accessibility metadata. Keep original SG5/SG7 issue #417 unchecked until
software-only acceptance is traceable on the exact final main commit.

### SG5 — keyboard visual-arrow navigation in Luna editors (16 November 2026; CI candidate)

Native Run and Desktop Rename now resolve Left/Right caret movement against
UAX #9 *visual grapheme boundaries* when a single-line input contains RTL
text, rather than moving in the opposite on-screen direction. Mixed Latin
and Hebrew run crossings follow the same visual caret map already used for
pointer hit-testing; logical Unicode input, Home/End policy, Backspace/Delete
and shell-free execution remain unchanged. Common LTR input keeps the
old allocation-free shortcut. Unit regressions cover pure RTL, mixed run
transitions, joined emoji and malformed multiline fallback; a movement
cancels stale IME preedit only when the caret actually changes.

This is one SG5 correctness increment, not full dual-affinity BiDi
selection, rendering/shaping parity, accessibility or real external IME
acceptance. Gate it on exact-head Rust/Clippy/native labwc CI plus post-merge
main; leave issue #417's SG5 checkbox open.

### SG5 — native RTL caret and pointer hit mapping (16 November 2026; CI candidate)

The shared single-line BiDi cluster permutation now also exposes the painted
edge for each **logical** grapheme caret position. XP Luna Run and Desktop
rename use this map to place the caret and reverse-map actual pointer clicks
without modifying logical input storage, clipping or the shell-free Run
execution contract. For proportional native fonts the pointer path measures
the already-reordered visual prefix directly, avoiding a second UAX #9 pass;
bitmap fonts retain one cell per grapheme. Mixed LTR/RTL runs, fully RTL
strings, horizontal scrolling, combined text and joined emoji have Rust
regression cases. Ordinary LTR interactions retain their existing path.

The BiDi run-boundary caret uses a documented, deterministic leading-edge
affinity; full dual-affinity selection, text highlighting, mirrored glyphs,
complex shaping, external IME protocol and device/Orca acceptance remain open.
The software-wide SG5 gate must **not** be marked complete by this slice.

