#!/bin/bash
# local-ci step: creator-headless-render
# Mirrors: riceplate-native.yml / native-layer-shell / Render validated recipe in isolated Creator compositor
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
set -eu
private_recipe=$(mktemp -d -t riceplate-headless-recipe-XXXXXXXX)
trap 'rm -r -- "$private_recipe"' EXIT
chmod 0700 "$private_recipe"
cp tests/fixtures/riceplate-desktop-v5.json "$private_recipe/recipe.json"
chmod 0600 "$private_recipe/recipe.json"
export PATH="$PWD/components/riceplate-wayland/target/release:$PATH"
dbus-run-session -- /usr/bin/python3 launcher.py de render \
  --recipe "$private_recipe/recipe.json" \
  --output "$PWD/dist/riceplate-native-preview/isolated-v5.png" \
  --width 1024 --height 768 --json \
  > dist/riceplate-native-preview/isolated-v5.json
