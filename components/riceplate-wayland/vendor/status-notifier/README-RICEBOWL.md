# RiceBowl compatibility patch: status-notifier 0.1.1

Upstream: https://github.com/AustinJ235/status-notifier (MIT; original
copyright and license retained in LICENSE). This contains the original 0.1.1
single-file crate plus a narrowly scoped signal-origin mapping fix.

## Reason for temporary vendoring

The upstream host indexes StatusNotifierItem registrations by the name
supplied to StatusNotifierWatcher (often well-known, for example
`org.example.Provider`), but D-Bus always delivers the corresponding
`LayoutUpdated`, `ItemsPropertiesUpdated` and Item status signals from
the **unique bus sender** (for example `:1.42`). Without correlating these
identities, a live disabled/removed menu row can remain executable after
the provider changes state.

The patch stores the unique sender of the successful initial GetAll reply
for each registered item. It resolves subsequent signals against that owner,
and for DBusMenu also matches the object path. Ambiguous sender/path matches
fail closed rather than modifying an unrelated item's menu. The externally
visible registered bus-name API stays unchanged.

Scope: session bus only; no extra runtime dependencies, additional daemon,
privileged D-Bus method or system-wide configuration mutation. The original
Rust 1.88 / dbus 0.9 dependency remains unchanged.

Regression: `scripts/smoke_sg1_sni_labwc.sh` with the private provider
registered under a well-known name, then real labwc keyboard interaction
after live `LayoutUpdated` and disabled/empty/denied/slow changes. Keep the
negative tests in place. Prefer returning to the registry dependency after an
equivalent upstream fix is published and independently validated.
