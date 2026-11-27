#!/bin/bash
# local-ci step: portal-pixman-repeat
# Mirrors: wayland-portal-strict.yml / portal-pixman-repeat / Repeat existing pixman acceptance and verify no runtime leftovers
# Local adaptation: runtime-leftover scan uses the private $TMPDIR, so concurrent runs on the host cannot disturb it
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
set -eu
before=$(find "$TMPDIR" -maxdepth 1 -type d -name 'ricebowl-portals.*' -print | sort)
timeout -k 5s 90s sh scripts/smoke_wayland_portals.sh
timeout -k 5s 90s sh scripts/smoke_wayland_portals.sh
after=$(find "$TMPDIR" -maxdepth 1 -type d -name 'ricebowl-portals.*' -print | sort)
[ "$before" = "$after" ] || {
  echo "PORTAL_CLEANUP_FAIL: private runtimes left behind" >&2
  printf 'Before:\n%s\nAfter:\n%s\n' "$before" "$after" >&2
  exit 1
}
echo "PORTAL_PIXMAN_REPEAT_OK: two isolated runs without runtime leftovers"
