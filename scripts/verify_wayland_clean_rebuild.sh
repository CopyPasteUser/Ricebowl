#!/usr/bin/env bash
# Rebuild all four opt-in Debian previews from a clean checkout at the claimed
# source commit. Never installs packages or modifies the active desktop.
set -euo pipefail

if (( $# != 4 )); then
    echo "Usage: $0 CORE.deb SESSION.deb NATIVE.deb DESKTOP.deb" >&2
    exit 2
fi
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
for tool in git dpkg-deb dpkg-shlibdeps readelf cmp sha256sum; do
    command -v "$tool" >/dev/null || { echo "Missing rebuild dependency: $tool" >&2; exit 1; }
done
for package in "$@"; do
    if [[ "$package" != /*.deb || ! -f "$package" || -L "$package" ]]; then
        echo "Rebuild requires existing absolute, non-symlinked .deb files: $package" >&2
        exit 2
    fi
done
source_commit=$(git -C "$root" rev-parse --verify 'HEAD^{commit}')
if [[ ! "$source_commit" =~ ^[0-9a-f]{40}$ ]]; then
    echo "Cannot pin an exact Git source commit" >&2
    exit 1
fi

# The existing read-only metadata, control.tar, file-tree and dependency
# verifier MUST run before extracting any supplied archive.
bash "$root/scripts/verify_wayland_package_set.sh" "$@" >/dev/null
for package in "$@"; do
    claimed=$(dpkg-deb --field "$package" X-RiceBowl-Source-Commit)
    if [[ "$claimed" != "$source_commit" ]]; then
        echo "Bundle does not match checked-out source commit: $package" >&2
        exit 1
    fi
done

scratch=$(mktemp -d -t ricebowl-clean-rebuild-XXXXXXXX)
clean="$scratch/checkout"
cleanup() {
    if [[ -d "$clean" ]]; then
        git -C "$root" worktree remove --force "$clean" >/dev/null 2>&1 || :
    fi
    rm -rf -- "$scratch"
}
trap cleanup EXIT
mkdir -p "$scratch/original" "$scratch/rebuilt"
dpkg-deb --extract "$1" "$scratch/original/core"
dpkg-deb --extract "$3" "$scratch/original/native"

# Match the recorded build epoch, not the runner's current clock. A package
# built with a different epoch from its peers must fail the byte comparison.
buildinfo="$scratch/original/core/usr/lib/ricebowl-wayland/BUILDINFO"
epoch=$(sed -n 's/^source_date_epoch=//p' "$buildinfo")
if [[ ! "$epoch" =~ ^[0-9]+$ ]]; then
    echo "Invalid package build epoch" >&2
    exit 1
fi
export SOURCE_DATE_EPOCH="$epoch"
export LC_ALL=C

# A separate, clean tracked-file tree tests independence from unstaged files,
# staged patches, cache outputs and the original checkout's directory layout.
# Both trees still share the SAME host/toolchain: this is not cross-host
# reproducibility or independent proof of how the supplied ELF was compiled.
git -C "$root" worktree add --detach "$clean" "$source_commit" >/dev/null
bash "$clean/scripts/build_wayland_core_deb.sh" "$scratch/rebuilt/core.deb" >/dev/null
sh "$clean/scripts/build_wayland_session_deb.sh" "$scratch/rebuilt/session.deb" >/dev/null
sh "$clean/scripts/build_riceplate_native_deb.sh" \
    "$scratch/original/native/usr/bin/riceplate-native" \
    "$scratch/rebuilt/native.deb" >/dev/null
sh "$clean/scripts/build_wayland_desktop_deb.sh" "$scratch/rebuilt/desktop.deb" >/dev/null

labels=(core session native desktop)
original=("$@")
for i in "${!labels[@]}"; do
    rebuilt="$scratch/rebuilt/${labels[$i]}.deb"
    if ! cmp -s -- "${original[$i]}" "$rebuilt"; then
        echo "Non-reproducible ${labels[$i]} package at $source_commit" >&2
        sha256sum -- "${original[$i]}" "$rebuilt" >&2
        exit 1
    fi
    echo "PASS: ${labels[$i]} matches clean tracked-source rebuild"
done
echo "PASS: all four packages reproduced at $source_commit on this build host"
