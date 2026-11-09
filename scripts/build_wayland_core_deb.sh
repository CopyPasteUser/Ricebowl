#!/usr/bin/env bash
# Reproducible, no-install core package from tracked project files.
# Restrict the source manifest to git-tracked Wayland runtime files.
set -euo pipefail
project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
version='0.1.0~preview2'
output=${1:-"$project_root/dist/ricebowl-wayland-core_${version}_all.deb"}
if [[ "$output" != /*.deb ]]; then
    echo "Output must be an absolute .deb path" >&2; exit 2
fi
if [[ -e "$output" || -L "$output" ]]; then
    echo "Refusing to overwrite existing package: $output" >&2; exit 1
fi
for binary in git dpkg-deb; do
    command -v "$binary" >/dev/null || { echo "$binary is required" >&2; exit 1; }
done
if ! git -C "$project_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Wayland core packaging requires a tracked Git checkout" >&2; exit 1
fi
if [[ -n ${SOURCE_DATE_EPOCH:-} ]]; then
    package_epoch=$SOURCE_DATE_EPOCH
else
    package_epoch=$(git -C "$project_root" log -1 --format=%ct HEAD)
fi
if [[ ! "$package_epoch" =~ ^[0-9]+$ ]]; then
    echo "Invalid SOURCE_DATE_EPOCH" >&2; exit 1
fi
export SOURCE_DATE_EPOCH="$package_epoch"
export LC_ALL=C
mkdir -p -- "$(dirname -- "$output")"
stage=$(mktemp -d)
trap 'rm -rf -- "$stage"' EXIT
payload="$stage/usr/lib/ricebowl-wayland"
install -D -m 0644 "$project_root/packaging/wayland/core-control" "$stage/DEBIAN/control"
install -D -m 0755 "$project_root/packaging/wayland/ricebowl-wayland-app" \
    "$stage/usr/bin/ricebowl-wayland-app"
install -D -m 0755 "$project_root/packaging/wayland/ricebowl-wayland-command" \
    "$stage/usr/lib/ricebowl-wayland/bin/ricebowl"

# Copy only tracked files. Never package local edits, caches, bytecode, a
# checkout's .git, or unexpected symlinks. Python __file__ paths still point
# to a real filesystem tree, so recipes, wallpapers and Creator work.
manifest="$stage/tracked-files"
git -C "$project_root" ls-files -z -- \
    launcher.py macrice assets/wallpapers \
    assets/ricebowl-symbolic.svg assets/macrice-symbolic.svg \
    assets/ricehub-symbolic.svg examples/wayland > "$manifest"
count=0
while IFS= read -r -d '' relative; do
    source="$project_root/$relative"
    if [[ ! -f "$source" || -L "$source" ]]; then
        echo "Tracked application source is missing or a symlink: $relative" >&2
        exit 1
    fi
    case "$relative" in
        *.pyc|*.pyo|*/__pycache__/*)
            echo "Refusing tracked bytecode in core package: $relative" >&2
            exit 1 ;;
    esac
    mode=0644
    [[ -x "$source" ]] && mode=0755
    install -D -m "$mode" "$source" "$payload/$relative"
    count=$((count + 1))
done < "$manifest"
rm -f -- "$manifest"
if (( count < 40 )) || [[ ! -f "$payload/macrice/de/session.py" ||
    ! -f "$payload/macrice/de/resources/labwc/rc.xml" ||
    ! -f "$payload/macrice/creator_gui.py" ||
    ! -f "$payload/examples/wayland/heritage-modern-v10.json" ||
    ! -f "$payload/launcher.py" ]]; then
    echo "Incomplete tracked Wayland application payload" >&2
    exit 1
fi
# Preview2 records package/source provenance inside the installed package.
# The former preview1 omitted this immutable file. Upgrade/downgrade QA
# checks both its addition and removal, not just dpkg's version string.
source_commit=$(git -C "$project_root" rev-parse --verify HEAD)
case "$source_commit" in
    ????????????????????????????????????????) ;;
    *) echo "Invalid package source commit" >&2; exit 1 ;;
esac
buildinfo="$stage/usr/share/doc/ricebowl-wayland-core/BUILDINFO"
install -d -m 0755 "$(dirname -- "$buildinfo")"
printf 'format=1\nversion=%s\nsource_commit=%s\nsource_date_epoch=%s\n' \
    "$version" "$source_commit" "$package_epoch" > "$buildinfo"
chmod 0644 "$buildinfo"

find "$stage" -exec touch -h -d "@$package_epoch" -- {} +
dpkg-deb --build --root-owner-group "$stage" "$output"
echo "Built $output from $count tracked runtime files (not installed)"
