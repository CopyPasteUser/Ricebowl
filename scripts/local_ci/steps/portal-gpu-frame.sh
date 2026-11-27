#!/bin/bash
# local-ci step: portal-gpu-frame
# Mirrors: wayland-portal-strict.yml / portal-gpu-frame / Strict ScreenCast and real frame acceptance (fail closed)
# Local adaptation: runs only where a DRM render node exists (catalog requirement); mirrors the manual self-hosted gpu input
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
echo '--- OS/kernel/DRM ---'
uname -a
labwc --version || true
ls -l /dev/dri 2>&1 || true
echo '--- Mesa configuration (CI-only environment) ---'
printf 'LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe EGL_PLATFORM=surfaceless\n'
export RICEBOWL_PORTAL_RENDERER=gles2 RICEBOWL_PORTAL_STRICT_CI=1 LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe EGL_PLATFORM=surfaceless
timeout -k 5s 160s sh scripts/smoke_wayland_portals.sh
