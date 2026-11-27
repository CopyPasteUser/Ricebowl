#!/bin/bash
# local-ci step: portal-crash-recovery
# Mirrors: wayland-portal-strict.yml / portal-pixman-repeat / Crash labwc before socket creation and verify runtime recovery
# Local adaptation: runtime-leftover scan uses the private $TMPDIR
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
set -eu
fake_bin=$(mktemp -d)
trap 'rm -rf -- "$fake_bin"' EXIT
printf '%s\n' '#!/bin/sh' 'echo PORTAL_TEST_COMPOSITOR_CRASH >&2' 'exit 17' >"$fake_bin/labwc"
chmod 0700 "$fake_bin/labwc"
before=$(find "$TMPDIR" -maxdepth 1 -type d -name 'ricebowl-portals.*' -print | sort)
if PATH="$fake_bin:$PATH" timeout -k 5s 30s sh scripts/smoke_wayland_portals.sh >"$fake_bin/crash.log" 2>&1; then
  echo "PORTAL_CRASH_FAIL: compositor crash was accepted as success" >&2
  exit 1
fi
if ! grep -q 'PORTAL_TEST_COMPOSITOR_CRASH' "$fake_bin/crash.log" || \
   ! grep -q 'PORTAL_SETUP_FAIL: labwc never created' "$fake_bin/crash.log"; then
  echo "PORTAL_CRASH_FAIL: test did not reach intended compositor failure" >&2
  sed -n '1,75p' "$fake_bin/crash.log" >&2
  exit 1
fi
after=$(find "$TMPDIR" -maxdepth 1 -type d -name 'ricebowl-portals.*' -print | sort)
[ "$before" = "$after" ] || {
  echo "PORTAL_CRASH_FAIL: runtime survived compositor exit" >&2
  exit 1
}
echo "PORTAL_CRASH_CLEANUP_OK: failed compositor left no private runtime"
