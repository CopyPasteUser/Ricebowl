#!/bin/sh
# Package an already compiled native RicePlate; never install it on the builder.
set -eu

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 /absolute/path/to/riceplate-native /absolute/output.deb" >&2
    exit 1
fi
source_binary=$1
output=$2
project_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
if ! command -v dpkg-deb >/dev/null 2>&1 || \
   ! command -v dpkg-shlibdeps >/dev/null 2>&1 || \
   ! command -v readelf >/dev/null 2>&1; then
    echo "dpkg-deb, dpkg-shlibdeps and readelf are required." >&2
    exit 1
fi
if [ ! -f "$source_binary" ] || [ -L "$source_binary" ] || [ ! -x "$source_binary" ]; then
    echo "Source must be a real, executable native RicePlate binary." >&2
    exit 1
fi
if ! readelf -h "$source_binary" 2>/dev/null | grep -q 'Machine:.*Advanced Micro Devices X86-64'; then
    echo "Only x86-64 ELF binaries can enter this amd64 preview package." >&2
    exit 1
fi
if [ "$(dpkg --print-architecture)" != amd64 ]; then
    echo "Build the amd64 preview package on an amd64 Debian host." >&2
    exit 1
fi
if [ -e "$output" ] || [ -L "$output" ]; then
    echo "Refusing to overwrite an existing package: $output" >&2
    exit 1
fi
case "$output" in
    /*.deb) ;;
    *) echo "Output must be an absolute .deb file path." >&2; exit 1 ;;
esac

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
LC_ALL=C
export LC_ALL

mkdir -p -- "$(dirname -- "$output")"
stage=$(mktemp -d)
trap 'rm -r -- "$stage"' EXIT
install -D -m 0755 "$source_binary" "$stage/usr/bin/riceplate-native"

# dpkg-shlibdeps derives the actual versioned shared-library requirements
# from the supplied ELF on the build host; no guessed ABI floors.
mkdir -p "$stage/debian"
printf '%s\n' 'Source: ricebowl-riceplate-native' \
    'Section: x11' 'Priority: optional' 'Maintainer: CopyPasteUser' \
    '' 'Package: ricebowl-riceplate-native' 'Architecture: amd64' \
    'Description: Native RicePlate preview' > "$stage/debian/control"
dependencies=$(cd "$stage" && dpkg-shlibdeps -O -e"$stage/usr/bin/riceplate-native" |
    sed -n 's/^shlibs:Depends=//p')
if [ -z "$dependencies" ]; then
    echo "Could not derive dynamic dependencies for the native binary." >&2
    exit 1
fi
awk -v depends="$dependencies" \
    '/^Description:/ {print "Depends: " depends} {print}' \
    "$project_root/packaging/wayland/native-control.in" > "$stage/DEBIAN/control"
rm -r -- "$stage/debian"
find "$stage" -exec touch -h -d "@$package_epoch" -- {} +
dpkg-deb --build --root-owner-group "$stage" "$output"
echo "Built $output (not installed)"
