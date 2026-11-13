# RiceBowl standalone Wayland — reliability / Mint 22 acceptance

Scope: **opt-in labwc** on Linux Mint 22, with existing XFCE fully intact.
This document complements `AGENTS.md` and the existing CI/Debian acceptance
smokes. It does not certify a complete desktop environment or physical device.

## Verified startup chain (from the code)

1. An explicitly chosen Wayland session entry runs
   `/usr/bin/ricebowl-wayland-session` (optionally `--native`).
   The wrapper selects the packaged versioned Wayland core when installed;
   it never sets an XFCE or display-manager default.
2. `ricebowl ... de start` refuses root, checks a private runtime directory,
   requires labwc, Waybar rescue, foot/fuzzel/swaylock and (for full logins)
   swayidle. Native selection separately requires RicePlate. An absent user
   bus may trigger **one** bounded `dbus-run-session` reexec.
3. A full login reconciles the private live-switch journal and validates the
   saved recipe; a bad implicit selection falls back to classic without
   modifying its file. An explicit invalid recipe fails instead.
4. RiceBowl prepares a temporary marked labwc configuration and starts
   upstream labwc with its `--startup` command, which launches the Python
   shell supervisor. Exiting that supervisor requests a compositor exit.
5. The supervisor starts a panel and manages a Waybar rescue, wallpaper,
   Mako/RicePop notification owner, optional Orca and a Polkit agent.
   The full-session swayidle/swaylock guard must remain active: its unexpected
   exit ends the opt-in session. Live panel failure attempts one reviewed
   restore then one Waybar rescue, not an infinite loop.

**Parallel-work boundary:** [PR #346](https://github.com/CopyPasteUser/Ricebowl/pull/346)
changes optional-service ordering/restart and output refresh under
`macrice/de/session.py`. This branch does not implement or duplicate those
changes. The *currently merged main* starts some optional clients before
the lock guard; the PR proposes tightening this. Review the final merged
startup chain before taking hardware acceptance.

## Read-only diagnostics

```bash
ricebowl de check --json
ricebowl de acceptance --json
ricebowl de reliability --json
```

The new reliability snapshot reports fixed, allowlisted process roles,
required executables, a bounded read-only Ping of the declared user D-Bus
address (no service activation), protocol advertisements (queried by `wayland-info` **only** when an owned Wayland
socket is detected), and the safe state of the pending live-switch journal.
It does not show argv, full environment, monitor identifiers, recipe paths,
notification contents, window titles or journal file contents.

Critical contracts:

- `swayidle` and `swaylock` are mandatory for a full login. Mako,
  wallpaper, Orca and authentication-agent availability is reported without
  treating those integrations as prerequisites for login.
- An unreachable or timed-out D-Bus Ping is reported separately from an\n  undeclared bus; neither state triggers automatic restarts.\n- Process counts cover only **same-UID kernel process names**. Without
  session-specific cgroup membership they can contain another session's
  processes. An absent entry does not prove an optional service crashed.
- Protocol probing is bounded, has a three-second deadline, and reports
  **unknown**, not "absent", when probing is unavailable.
- Only the **pending** recovery journal is available as structured state;
  recent supervisor recovery events are *not persisted*. Do not invent a
  history from the current journal.
- No command in this report repairs a journal, changes a display mode, starts
  services, changes XFCE or authorizes a Rice switch.

## Reproducible resource comparison

Run from this Git checkout. The sampler does not start services or run as root.

In a **native RiceBowl** login, after a stable idle period:

```bash
python3 scripts/measure_wayland_resources.py --profile native --seconds 30 > "$HOME/native-resource.json"
```

In the separately selected **Waybar RiceBowl** login:

```bash
python3 scripts/measure_wayland_resources.py --profile waybar --seconds 30 > "$HOME/waybar-resource.json"
```

In the unchanged **XFCE/X11** login:

```bash
python3 scripts/measure_wayland_resources.py --profile xfce --seconds 30 > "$HOME/xfce-resource.json"
```

Then, from this checkout, generate the read-only Mint report:

```bash
python3 scripts/wayland_acceptance_report.py \
  --native-sample "$HOME/native-resource.json" \
  --waybar-sample "$HOME/waybar-resource.json" \
  --xfce-sample "$HOME/xfce-resource.json" \
  > "$HOME/ricebowl-mint22-acceptance.json"
```

The profiler reports **CPU% of one logical core**, snapshot RSS/PSS KiB,
matched process count, context switches per second and the kernel's
`nr_wakeups` delta only when exposed by `/proc/PID/sched`.
Context switches are **not** CPU wakeups. No `nr_wakeups` data means
`kernel_wakeups_per_s: null`, not zero. A restarted PID is excluded from
the stable CPU delta and flagged, not counted as free CPU. The tool reports
`idle_confirmed: false`, because software cannot prove the user stayed
idle. Values are per named process groups, **not total desktop memory or
a system-wide energy figure**.

Use the **same physical device**, power profile, display configuration, open
apps, measurement interval and ambient workload. Prefer 3+ runs, report
median/spread, and do not infer savings from one run. **Cold login start**
is currently uninstrumented; measure explicitly from greeter selection
to the first *usable* panel using a local timestamp/recording and record
three attempts. Headless CI startup is not a hardware-login benchmark.

## Fail-closed failure-injection and packaging gates

Automated/offline tests under `tests/test_de_reliability*.py` inject missing
binaries, socket absence, broken and timed-out protocol discovery, unreadable
PSS/wakeup files, corrupt /proc entries, PID reuse, unsafe journal state,
mislabeled measurement reports and absent samples. No live desktop is killed.

Existing isolated CI verifies real labwc startup and Waybar/native rescue.
`scripts/smoke_wayland_packaged_login.sh` exercises a disposable installed
native session: forced panel crash -> Waybar recovery; forced idle-guard
exit -> protected session termination; clean relogin; invalid saved recipe
fallback. These **destructive crash injections must remain inside the
disposable test user/runtime**, never on the active Mint/XFCE desktop.

`scripts/verify_wayland_package_set.sh` validates four .deb identities,
version constraints, namespaced paths, absence of maintainer scripts,
reproducible BUILDINFO and opt-in sessions. The existing disposable-Ubuntu
upgrade/downgrade/purge smoke checks that private recipes and XFCE canaries
survive. The new static packaging tests guard mandatory lock dependencies,
the native session entry and the exact version pinning. No package gets
installed by the diagnostic or measurement tools.

## Unfinished device acceptance

`ricebowl de acceptance --json` and the generated Mint report **always**
say `hardware_accepted: false`. A human still must verify physical login,
XFCE return, native and XWayland apps, all hardware keys, accessibility focus,
real portals/screencast consent, display hotplug/scale rollback, lock,
suspend/resume/lid and full uninstall/reinstall with retained private data.
PR #346's behavior must be merged and revalidated before treating optional
service recovery as stable.

This sprint adds no resident daemon, hidden poll loop, login-manager switch,
system-wide change, recipe migration or speculative performance optimization.
