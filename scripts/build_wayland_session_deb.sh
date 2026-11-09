#!/bin/sh
# Build an opt-in, removable login session package without touching the host.
set -eu

if ! command -v dpkg-deb >/dev/null 2>&1; then
    echo "dpkg-deb is required to build the Debian session package." >&2
    exit 1
fi
project_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
version='0.1.0~preview3'
output=${1:-"$project_root/dist/ricebowl-wayland-session_${version}_all.deb"}
if [ -e "$output" ] || [ -L "$output" ]; then
    echo "Refusing to overwrite an existing package: $output" >&2
    exit 1
fi
mkdir -p -- "$(dirname -- "$output")"
stage=$(mktemp -d)
trap 'rm -r -- "$stage"' EXIT

# The staged archive must not depend on the build time or mktemp directory.
# A reproducible source checkout supplies its commit time. Exported source
# trees without Git use a documented fixed fallback unless the packager sets
# SOURCE_DATE_EPOCH explicitly.
if [ -n "${SOURCE_DATE_EPOCH:-}" ]; then
    package_epoch=$SOURCE_DATE_EPOCH
elif command -v git >/dev/null 2>&1 && \
    git -C "$project_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    package_epoch=$(git -C "$project_root" log -1 --format=%ct HEAD)
else
    package_epoch=1704067200
fi
case "$package_epoch" in
    ''|*[!0-9]*) echo "Invalid SOURCE_DATE_EPOCH" >&2; exit 1 ;;
esac
SOURCE_DATE_EPOCH=$package_epoch
export SOURCE_DATE_EPOCH

install -D -m 0644 "$project_root/packaging/wayland/control" "$stage/DEBIAN/control"
install -D -m 0755 "$project_root/packaging/wayland/ricebowl-wayland-session" \
    "$stage/usr/bin/ricebowl-wayland-session"
install -D -m 0644 "$project_root/packaging/wayland/ricebowl.desktop" \
    "$stage/usr/share/wayland-sessions/ricebowl.desktop"
install -D -m 0644 "$project_root/packaging/wayland/ricebowl-native.desktop" \
    "$stage/usr/share/wayland-sessions/ricebowl-native.desktop"
install -D -m 0644 "$project_root/packaging/wayland/ricebowl-portals.conf" \
    "$stage/usr/share/xdg-desktop-portal/ricebowl-portals.conf"
install -D -m 0644 "$project_root/packaging/wayland/ricebowl-session.target" \
    "$stage/usr/lib/systemd/user/ricebowl-session.target"

# dpkg-deb honors SOURCE_DATE_EPOCH for its archive headers; normalize the
# filesystem metadata inside the staged tar members as well.
find "$stage" -exec touch -h -d "@$package_epoch" -- {} +

dpkg-deb --build --root-owner-group "$stage" "$output"
echo "Built $output (not installed)"
