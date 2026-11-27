#!/bin/bash
# local-ci step: pkg-tamper
# Mirrors: riceplate-native.yml / native-layer-shell / Reject source-stamped but payload-tampered core package
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
set -eu
artifact="$PWD/dist/riceplate-native-preview"
source_core="$artifact/ricebowl-wayland-core_0.1.0~preview2_all.deb"
session="$artifact/ricebowl-wayland-session_0.1.0~preview3_all.deb"
native="$artifact/ricebowl-riceplate-native_0.1.0~preview2_amd64.deb"
desktop="$artifact/ricebowl-wayland-desktop_0.1.0~preview3_amd64.deb"
isolated=$(mktemp -d -t ricebowl-core-tamper-XXXXXXXX)
trap 'rm -rf -- "$isolated"' EXIT
dpkg-deb --raw-extract "$source_core" "$isolated/stage"
printf '\n# isolated CI tampering; never shipped\n' >> \
  "$isolated/stage/usr/lib/ricebowl-wayland/launcher.py"
# Rebuild control checksums rather than fail merely on stale md5sums.
rm -f -- "$isolated/stage/DEBIAN/md5sums"
dpkg-deb --build --root-owner-group "$isolated/stage" \
  "$isolated/tampered-core.deb" >/dev/null
# The tamper is *within* the allowed core payload namespace; our
# standalone safety gate should accept its metadata/path structure.
bash scripts/verify_wayland_package_set.sh \
  "$isolated/tampered-core.deb" "$session" "$native" "$desktop" >/dev/null
if bash scripts/verify_wayland_clean_rebuild.sh \
    "$isolated/tampered-core.deb" "$session" "$native" "$desktop" \
    >"$isolated/result.out" 2>"$isolated/result.err"; then
  echo "Clean-source rebuild accepted a modified core payload" >&2
  exit 1
fi
grep -Fq 'Non-reproducible core package' "$isolated/result.err" || {
  cat "$isolated/result.err" >&2
  echo "Core tamper was not rejected by the reproducibility comparison" >&2
  exit 1
}
echo "PASS: source-stamped but mutated core package fails clean rebuild"
