#!/bin/sh
# CI-only, disposable real-Mako-1.11 integration. Never install, replace or
# modify the host notification daemon, login selection or system D-Bus config.
set -eu

project_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
workspace=$(mktemp -d)
trap 'rm -rf -- "$workspace"' EXIT

# Upstream signed v1.11.0 tag resolves to this exact source commit. A moved
# tag/ref or unexpected clone is a hard failure, not silent feature fallback.
expected=91c6b799855762ad1eb8b4498967c270a339be0c
GIT_TERMINAL_PROMPT=0 git clone --quiet --depth 1 --single-branch \
    --branch v1.11.0 https://github.com/emersion/mako.git "$workspace/source"
actual=$(git -C "$workspace/source" rev-parse HEAD)
if [ "$actual" != "$expected" ]; then
    echo "Unreviewed Mako v1.11.0 source commit: $actual" >&2
    exit 1
fi

meson setup "$workspace/build" "$workspace/source" \
    -Dsd-bus-provider=libsystemd -Dman-pages=disabled -Dicons=disabled \
    -Dbuildtype=release
ninja -C "$workspace/build" mako makoctl

mkdir -p "$workspace/bin"
ln -s "$workspace/build/mako" "$workspace/bin/mako"
ln -s "$workspace/build/makoctl" "$workspace/bin/makoctl"
echo "Real Mako 1.11.0 source checked: $actual"

# The RiceBowl session launches exactly one real notification daemon via the
# normal supervisor, but from this per-run PATH. The script creates a new
# labwc and private D-Bus and tears both down; it never accesses the login
# session, the XFCE notification owner, persistent files or system binaries.
PATH="$workspace/bin:$PATH" RICEBOWL_SMOKE_RICEPOP=1 \
    RICEBOWL_SMOKE_MAKO_MODERN=1 \
    timeout -k 5s 75s sh "$project_root/scripts/smoke_wayland_session.sh"
