#!/bin/bash
# local-ci step: mako-build
# Mirrors: riceplate-native.yml / native-layer-shell / Build source-locked real Mako 1.11 for SG3 only
# Local adaptation: builds into the persistent local-ci cache ($LCI_CACHE) and reuses
# a previous build of the same pinned commit; no apt installs (checked by preflight).
# Exit 77 = BLOCKED (e.g. no network to fetch the pinned source), never PASS.
# Environment (set by scripts/local_ci.py): LCI_CACHE, LCI_MAKO_BUILD, RUNNER_TEMP ; cwd = fresh clone.
set -eu
src="$LCI_CACHE/mako-1.11.0-src"
build="$LCI_MAKO_BUILD"
expected=91c6b799855762ad1eb8b4498967c270a339be0c
if [ -x "$build/mako" ] && [ -x "$build/makoctl" ] && [ -d "$src/.git" ] \
    && [ "$(git -C "$src" rev-parse HEAD)" = "$expected" ]; then
  echo "mako-build: reusing cached source-locked Mako 1.11.0 at $expected"
  exit 0
fi
work="$LCI_CACHE/mako-build-work.$$"
rm -rf -- "$work"
mkdir -p "$work"
trap 'rm -rf -- "$work"' EXIT
if ! GIT_TERMINAL_PROMPT=0 git clone --quiet --depth 1 --single-branch \
    --branch v1.11.0 https://github.com/emersion/mako.git "$work/src"; then
  echo "LOCAL_CI_BLOCKED: cannot fetch https://github.com/emersion/mako.git v1.11.0 (no network or proxy denial)"
  exit 77
fi
test "$(git -C "$work/src" rev-parse HEAD)" = "$expected"
meson setup "$work/build" "$work/src" \
  -Dsd-bus-provider=libsystemd -Dman-pages=disabled -Dicons=disabled \
  -Dbuildtype=release
ninja -C "$work/build" mako makoctl
test -x "$work/build/mako" && test -x "$work/build/makoctl"
# Publish atomically; the build tree is only read afterwards (binaries on PATH).
rm -rf -- "$src" "$build"
mv "$work/src" "$src"
mv "$work/build" "$build"
test -x "$build/mako" && test -x "$build/makoctl"
echo "mako-build: built source-locked Mako 1.11.0 at $expected"
