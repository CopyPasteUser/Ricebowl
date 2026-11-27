#!/bin/bash
# local-ci step: sg5-labwc-pin
# Mirrors: riceplate-native.yml / native-layer-shell / Build source-locked IME-capable labwc for SG5 only
# Local adaptation: the pinned labwc 0.7.2 is prebuilt on this host at /opt/labwc-sg5
# (source /opt/labwc-sg5-src); this step verifies the pin instead of rebuilding it.
# Ubuntu's stock labwc (0.7.1) is never replaced.
set -eu
pinned=b41af54a1bd7d9270d19de4c9a2b77d882cf3ede
build=/opt/labwc-sg5
src=/opt/labwc-sg5-src
test -x "$build/labwc"
# The source checkout is a detached HEAD at the pinned commit; read it without git so
# a root-owned tree does not trip safe.directory for this unprivileged user.
head=$(cat "$src/.git/HEAD")
test "$head" = "$pinned"
grep -Fq "version: '0.7.2'" "$src/meson.build"
"$build/labwc" --version | grep -F 0.7.2
echo "sg5-labwc-pin: $build/labwc is 0.7.2 built from pinned $pinned"
