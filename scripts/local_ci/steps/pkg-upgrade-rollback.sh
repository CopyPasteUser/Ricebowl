#!/bin/bash
# local-ci step: pkg-upgrade-rollback
# Mirrors: riceplate-native.yml / native-layer-shell / Upgrade all historical Debian components, inject failures and recover
# Local adaptation: the clone already holds full history; fetch only if a pinned baseline commit is absent
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
set -eu
bash -n scripts/smoke_wayland_upgrade_rollback.sh
git cat-file -e b3d615a7cc508049050eb06c7952ef5a8d26e598^{commit} 2>/dev/null || git fetch --no-tags origin b3d615a7cc508049050eb06c7952ef5a8d26e598
git cat-file -e c8274dee78386124470cb5ff9a4d2768bb019126^{commit} 2>/dev/null || git fetch --no-tags origin c8274dee78386124470cb5ff9a4d2768bb019126
bash scripts/smoke_wayland_upgrade_rollback.sh "$PWD/dist/riceplate-native-preview"
