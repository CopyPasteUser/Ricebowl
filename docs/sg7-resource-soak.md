# SG7 WP7.2 — headless resource/leak soak (local measurement)

**This is a headless local measurement, not a hardware benchmark.** It ran on a
4-vCPU Firecracker VM (kernel 6.18.44), labwc 0.7.1 with the pixman renderer and
one 1366x768 virtual output, on `main@c76beab` plus the WP4.3/7.2 scripts. It
says nothing about GPU, real displays, power, cold-login time or physical
devices, and it does not close SG7 (exact-main CI and hardware stay open).

## Tool

`scripts/soak_riceplate_resources.sh` (not wired into any workflow; unit-tested
arithmetic in `tests/test_soak_resource_sampler.py`). For each rice, one after
another, a fresh labwc + private D-Bus session with real Mako (shipped config),
swaybg, and `riceplate-native` started with `RICEBOWL_DE_NESTED=0` (full-session
paths). `scripts/soak_resource_sampler.py` records every 10 s PSS
(`/proc/PID/smaps_rollup`), RSS, utime+stime, threads and fds of riceplate-native,
labwc, mako, swaybg and the private dbus-daemon into a CSV, then summarises
start / settled / end PSS, least-squares and Theil-Sen slope per hour, the
slope of the late half, idle and interaction CPU %. Timeline: 60 s warm-up, 15 %
idle, 60 % interaction, 25 % idle. Every 15 s a real interaction cycle runs:
Chrome = tray popup (SNI fixture) open/Escape; XP Luna = Start menu + keys, clock
menu/calendar, clock context menu, tray popup; plus a real notification into
Mako and a real foot window opened/closed (taskbar add/remove). A GROWTH flag
needs whole-run LS, whole-run Theil-Sen **and** late-half Theil-Sen all above
2 MiB/h plus >256 KiB growth, so a one-time cache fill cannot flag.
`SOAK_CYCLE_PARTS` isolates a suspect (controls / notify / window).

```sh
SOAK_DURATION=660 SOAK_RICES="chrome luna" SOAK_OUT=/tmp/soak sh scripts/soak_riceplate_resources.sh
```

## Results (660 s per rice, 66 samples, accessibility bridge off)

riceplate-native, PSS in KiB:

| Rice | cycles | start | settled (60-120 s) | end | late slope | idle CPU | interaction CPU | threads / fds | flag |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Chrome | 19 | 5,971 | 5,999 | 7,533 | 540 KiB/h | 0.009 % | 0.034 % | 4 / 13 | ok |
| XP Luna | 16 | 17,465 | 17,502 | 21,331 | 97 KiB/h | 0.009 % | 0.274 % | 5 / 26 | ok |

Helpers (Chrome run / Luna run, end PSS KiB): labwc 25,203 / 28,019, mako 6,309 /
6,188, swaybg 2,934 / 2,986, dbus-daemon 1,417 / 1,436; idle CPU 0.000-0.005 %.

Both rices show a **one-time step at the first interaction** (Chrome +1.1 MB on
the first tray popup, Luna +3.7 MB for the first Start menu/calendar), then
flat PSS (Luna 21,324 KiB from 280 s to 440 s; idle phase flat). Mako's +3.4 MB
(first notification) is also one-time. labwc grows about 2 MB under window churn
in the Luna run (upstream process; allocator or buffer pool, not investigated).

Chrome showed a slow creep after the step (about 1 MiB/h at the 15 s cadence),
so it was isolated with 1 s cycles on Chrome: 38 foot window open/close cycles
(PSS flat, 5,780 KiB), 72 tray cycles (step then +0.13 MB) and **223 tray
cycles over 900 s**: 5,644 -> 7,139 (step) -> 7,226 KiB by 360 s and flat at
7,226-7,227 for the remaining 300 s of interaction (late slope 180 KiB/h,
fds 13 constant, threads 4). Conclusion: allocator settling, **no leak found**,
no product change. Residual caveats: ten-minute runs cannot show growth below
about 100 KiB/h; the AT-SPI bridge, Heritage/Orbit and two-output sessions were
not soaked (the script supports `SOAK_ATSPI=1` and `SOAK_RICES="heritage orbit"`).
