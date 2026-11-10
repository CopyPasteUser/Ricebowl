#!/bin/sh
# The aggregate Wayland package is dependency-only: apt/dpkg own all removals.
set -eu
root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
output=${1:-"$root/dist/ricebowl-wayland-desktop_0.1.0~preview2_amd64.deb"}
case "$output" in /*.deb) ;; *) echo "Output must be absolute .deb" >&2; exit 2;; esac
if [ -e "$output" ] || [ -L "$output" ]; then
    echo "Refusing to overwrite existing package: $output" >&2; exit 1
fi
if ! command -v dpkg-deb >/dev/null 2>&1; then
    echo "dpkg-deb is required" >&2; exit 1
fi
if [ "$(dpkg --print-architecture)" != amd64 ]; then
    echo "The native RicePlate bundle currently supports amd64 only" >&2; exit 1
fi
if [ -n "${SOURCE_DATE_EPOCH:-}" ]; then
    epoch=$SOURCE_DATE_EPOCH
elif command -v git >/dev/null 2>&1 && \
    git -C "$root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    epoch=$(git -C "$root" log -1 --format=%ct HEAD)
else
    epoch=1704067200
fi
case "$epoch" in ''|*[!0-9]*) echo "Invalid SOURCE_DATE_EPOCH" >&2; exit 1;; esac
export SOURCE_DATE_EPOCH="$epoch"
export LC_ALL=C
mkdir -p -- "$(dirname -- "$output")"
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
stage="$work/package"
mkdir -p -- "$stage"
control="$root/packaging/wayland/desktop-control"
if command -v git >/dev/null 2>&1 && \
   git -C "$root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    command -v tar >/dev/null 2>&1 || { echo "tar is required" >&2; exit 1; }
    git -C "$root" archive -o "$work/control.tar" HEAD -- packaging/wayland/desktop-control
    mkdir -p -- "$work/source"
    tar -xf "$work/control.tar" -C "$work/source"
    control="$work/source/packaging/wayland/desktop-control"
fi
if [ ! -f "$control" ] || [ -L "$control" ]; then
    echo "Desktop control source is missing or a symlink" >&2; exit 1
fi
install -D -m 0644 "$control" "$stage/DEBIAN/control"
# No maintainer scripts or postinst side effects: the default DM session is
# unchanged and all user settings remain in XDG directories.
find "$stage" -exec touch -h -d "@$epoch" -- {} +
dpkg-deb --build --root-owner-group "$stage" "$output"
echo "Built $output (not installed)"
