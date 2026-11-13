# RiceBowl shared shell component/action contract — v1

The native RicePlate action dispatcher, `ControlAction` hardware worker,
`ControlFeedback`, window handles, RiceSpice, RicePop and session recovery
remain the **only** owners of their respective Linux backends. This sprint
adds a typed, bounded action admission layer for panel/menu/desktop and
read-only Creator discovery; it does **not** execute new commands, add a
daemon or migrate schemas. Old v1–v12 recipe data and XFCE/X11 remain intact.

- Rust: `shell_actions::ShellAction::from_id / supports(Surface)`. The native
  dispatcher rejects unknown fixed IDs. Dynamically discovered `desktop:`
  IDs still pass through existing `MenuState.app_path` validation and Gio;
  they are not valid declarative action bindings.
- Python: `shell_contract.bind(action_id, Surface)` for Creator and
  `shell_contract.feedback` for *presenting state received from the owner*.
  It cannot perform system operations or claim a backend has succeeded.
- `catalog.describe()["action_contract"]` advertises contract version,
  per-surface IDs, logical owners and ready/applying/busy/unavailable/denied/
  failed display states. Existing Rust hardware readback and retry logic
  remain the live source of truth.
- Rust recipe v9+ component validation now accepts `show-desktop` in a
  panel, consistent with the Python parser's existing allowlist. Unknown
  capabilities/commands still fail before any mutation.

## Test Rices

`examples/wayland/test-taskbar-shell.json` uses the classic bottom start
button, tasks and end-aligned status. `test-dock-shell.json` uses a centered
launcher/task grouping, left-aligned clock, right status and a different
menu presentation and palette. Both use exactly the same NetworkManager/
WirePlumber status component bindings and native action backend.

**Limit:** the second test is a *dock-style panel composition* on the
existing full-width layer surface, not a real floating dock. A floating dock
needs independent layer surfaces and compositor acceptance, owned by the
core/window team. These fixtures are optional tests, not installed rices.

## Gates / collaboration

Run `python3 -m unittest tests.test_de_shell_contract tests.test_de_shell_live_fixtures -v`,
including guarded next-login selection/undo and a real `_LiveSwitch` supervisor
transaction against **mocked labwc/process operations**. This verifies
handoff and rollback logic but is not a live compositor proof. Also run
`cargo test shell_actions`, `cargo test recipe::tests`, and
`cargo clippy --all-targets -- -D warnings` from the Rust component.
Review real headless-labwc screenshots, pointer/keyboard/AT-SPI,
multi-output and live-switch/restore on a disposable session. Offline
parser tests **do not** prove a real compositor switch or rollback.

Chat 5 should integrate [PR #349](https://github.com/CopyPasteUser/Ricebowl/pull/349)
before its stacked hardening [PR #353](https://github.com/CopyPasteUser/Ricebowl/pull/353).
Independent GTK [PR #354](https://github.com/CopyPasteUser/Ricebowl/pull/354)
must pass native and GTK gates before integration. This branch does not
modify those features, system adapters, labwc focus, RiceField or Taskotto.
No autonomous merge. Further UI components must reuse these contracts
instead of directly calling `nmcli`, `wpctl`, `logind` or an ad-hoc Exec
command from a recipe.

**Pending:** current-PR CI, actual staged live switch and recovery,
hardware/Orca acceptance, screenshot comparison and performance evidence.
