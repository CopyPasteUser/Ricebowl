# RiceBowl portal strict acceptance — Issue #304

This is a **disposable test-only** contract. It does not alter login sessions,
systemd user services, global portal configuration, GPU drivers or permanent
DRM devices. Regular pixman smoke retains its explicitly limited status.

## What the two lanes prove

- **pixman (existing):** private D-Bus/PipeWire startup, FileChooser interface,
  screenshot PNG and attempted ScreenCast session. A Start response=2 means
  the capture backend remains untested; it is *not* stream success.
- **strict GLES2 (new):** in addition, require CreateSession, SelectSources,
  Start streams with distinct positive PipeWire node IDs, a genuine Unix
  socket FD from OpenPipeWireRemote, and a non-empty raw video Gst.Sample
  from `pipewiresrc` + `appsink` on that inherited FD before closing the
  portal session. A log tag `PORTAL_STRICT_OK` is emitted only after a
  `PORTAL_FRAME_OK` tag from the receiver. This does not prove Flatpak
  consent UX, real GPU hardware, multiple monitors or sustained frame rates.

## Renderer environment and reproducibility

Ubuntu 24.04 hosted Actions previously failed on PR #357 at
[run 43466167206](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43466167206):
`labwc 0.7.1` / `wlroots 0.17.1` logged
`Failed to find any DRM render node` and
`Cannot create GLES2 renderer: no DRM FD available`.
Installing Mesa llvmpipe does *not* supply a DRM node. Strict mode checks
for readable/writable `/dev/dri/renderD*` character devices before making
a runtime and fails explicitly with `PORTAL_STRICT_BLOCKED` if absent.

A suitable runner must supply an **ephemeral VM** with a usable DRM render
node accessible to the test UID, the supported Mesa llvmpipe EGL/GLES2
stack, labwc/wlroots compatible with that node, and PipeWire +
GStreamer PipeWire source and appsink. The host may expose a render node
through virtual GPU hardware configured by the VM provider. Do not install
or load kernel DRM modules on shared Actions workers; `vkms` by itself is
not proof of a suitable render node. The strict CI is intentionally red
until such a runner is proven; no fallback to pixman is permitted.

Run only in a disposable VM:

```sh
RICEBOWL_PORTAL_RENDERER=gles2 RICEBOWL_PORTAL_STRICT_CI=1 \
LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe EGL_PLATFORM=surfaceless \
timeout -k 5s 160s sh scripts/smoke_wayland_portals.sh
```

The shell creates private `/tmp/ricebowl-portals.XXXXXXXX` mode-0700
runtime/config/cache/tmp, an isolated D-Bus session and PipeWire socket.
The portal client accepts only that runtime and the CI marker and checks
the compositor socket. All subprocesses are bounded; trap cleanup kills
the launched compositor/PipeWire processes and removes the temporary
runtime. Any failure prints bounded client/labwc/PipeWire diagnostics.

## Failure signatures

- `PORTAL_SETUP_FAIL`: invalid renderer/strict configuration.
- `PORTAL_STRICT_BLOCKED`: infrastructure missing DRM render node or
  strict renderer mismatch.
- `PORTAL_FAIL`: D-Bus activation or required interface absent.
- `PORTAL_CAPTURE_FAIL: category=...`: request cancellation/denial,
  timeout, invalid session, PipeWire/sample/protocol failure.
- `PORTAL_FD_OK`: PipeWire remote socket verified (not a video frame).
- `PORTAL_FRAME_OK`: first nonempty `video/x-raw` sample received.
- `PORTAL_STRICT_OK`: strict acceptance through actual sample.
  
Hardware login/logout, Flatpak consent, long-running streams and
multi-output remain **OPEN**. Do not close #304 based on unit tests alone.

## Regression and CI matrix (14 November 2026)

The screenshot implementation for Ubuntu 24.04's `xdg-desktop-portal-wlr`
requires the `grim` executable. The dedicated portal workflow now installs
and preflights it in both pixman and GLES2 jobs. Previously a missing screenshot
helper surfaced as a generic response=2 rather than a missing binary; do not
treat that denial as a pixman limitation.

The parent portal smoke **owns and reaps** the PipeWire core, labwc and an
isolated `setsid`-managed client process group. It does not depend on
compositor startup grandchildren surviving compositor failure. The crash CI
injects a stub labwc that deliberately exits before opening its Wayland socket;
the test asserts a unique crash marker and verifies the private runtime was
removed. This is *early compositor crash recovery*, not proof of recovery
during an already-running video stream.

Normal Python tests cover request handle/token mismatches, D-Bus timeout
cleanup, request denials, FD index/socket verification, false frame receipts
and failure-path session cleanup. Actual frame transport remains separately
required from a DRM-capable runner. `PORTAL_STRICT_OK` never denotes a
successful D-Bus Start response alone.

CI snapshot and exact-head evidence are tracked in Issue #360; do not treat
older green runs as acceptance of a newer PR head.
