#!/usr/bin/env bash
# Read-only release gate for the four optional Wayland preview .deb files.
# Never installs packages, changes the default session or touches user config.
set -euo pipefail

if (( $# != 4 )); then
    echo "Usage: $0 CORE.deb SESSION.deb NATIVE.deb DESKTOP.deb" >&2
    exit 2
fi
for command in dpkg-deb dpkg tar find sha256sum grep; do
    command -v "$command" >/dev/null || { echo "$command is required" >&2; exit 1; }
done

work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
names=(ricebowl-wayland-core ricebowl-wayland-session ricebowl-riceplate-native ricebowl-wayland-desktop)
architectures=(all all amd64 amd64)
files=("$@")
versions=()
source_commits=()

for i in "${!files[@]}"; do
    package=${files[$i]}
    if [[ ! -f "$package" || -L "$package" ]]; then
        echo "Missing or symlinked package: $package" >&2
        exit 1
    fi
    actual=$(dpkg-deb -f "$package" Package)
    architecture=$(dpkg-deb -f "$package" Architecture)
    version=$(dpkg-deb -f "$package" Version)
    if [[ "$actual" != "${names[$i]}" || "$architecture" != "${architectures[$i]}" || -z "$version" ]]; then
        echo "Wrong package identity, version or architecture: $package" >&2
        exit 1
    fi
    versions+=("$version")
    # Release-bundle provenance must be consistent across independently
    # reproducible packages, not just satisfy compatible version floors.
    source_commit=$(dpkg-deb -f "$package" X-RiceBowl-Source-Commit)
    if [[ ! "$source_commit" =~ ^[0-9a-f]{40}$ ]]; then
        echo "Missing or invalid package source commit: $package" >&2
        exit 1
    fi
    source_commits+=("$source_commit")

    # No maintainer script may alter the login manager, XFCE or a home folder.
    dpkg-deb --ctrl-tarfile "$package" | tar -tf - > "$work/control-$i"
    while IFS= read -r control_file; do
        case "$control_file" in
            ./|./control|./md5sums) ;;
            *) echo "Refusing maintainer scripts or unexpected control data in $package: $control_file" >&2
               exit 1 ;;
        esac
    done < "$work/control-$i"

    dpkg-deb --fsys-tarfile "$package" | tar -tf - > "$work/contents-$i"
    if grep -Eq '^/|(^|/)\.\.(/|$)' "$work/contents-$i"; then
        echo "Unsafe archive paths in $package" >&2
        exit 1
    fi
    extracted="$work/package-$i"
    dpkg-deb -x "$package" "$extracted"
    if find "$extracted" -type l -print -quit | grep -q .; then
        echo "Unexpected symlink in $package" >&2
        exit 1
    fi
    # Permit only package-specific, namespaced files AND directories. XFCE
    # and display-manager configuration must never be touched by an archive.
    while IFS= read -r -d '' installed; do
        relative=${installed#"$extracted"/}
        if [[ ! -f "$installed" && ! -d "$installed" ]]; then
            echo "Unexpected special filesystem entry in $package: $relative" >&2
            exit 1
        fi
        case "$i:$relative" in
            0:usr|0:usr/bin|0:usr/lib|0:usr/lib/ricebowl-wayland|\
            0:usr/bin/ricebowl-wayland-app|0:usr/lib/ricebowl-wayland/*|\
            1:usr|1:usr/bin|1:usr/share|1:usr/share/wayland-sessions|\
            1:usr/share/xdg-desktop-portal|1:usr/lib|1:usr/lib/systemd|1:usr/lib/systemd/user|\
            1:usr/bin/ricebowl-wayland-session|1:usr/share/wayland-sessions/ricebowl.desktop|\
            1:usr/share/wayland-sessions/ricebowl-native.desktop|\
            1:usr/share/xdg-desktop-portal/ricebowl-portals.conf|\
            1:usr/lib/systemd/user/ricebowl-session.target|\
            2:usr|2:usr/bin|2:usr/bin/riceplate-native) ;;
            *) echo "Unexpected installed path in $package: $relative" >&2; exit 1 ;;
        esac
    done < <(find "$extracted" -mindepth 1 -print0)
done

for i in 1 2 3; do
    if [[ "${source_commits[$i]}" != "${source_commits[0]}" ]]; then
        echo "Mixed source commits in Wayland package set: ${names[$i]}" >&2
        exit 1
    fi
done

depends=$(dpkg-deb -f "${files[3]}" Depends)
# Debian dependencies are comma-delimited relationship atoms. Substring
# matching could accept e.g. notricebowl-wayland-core (= VERSION) as the
# actual core dependency. Never trust an in-name-only package identifier,
# an alternate provider, a duplicate or a weaker version relation.
IFS=',' read -r -a dependency_atoms <<< "$depends"
dependency_fields=()
for entry in "${dependency_atoms[@]}"; do
    entry="${entry#"${entry%%[![:space:]]*}"}"
    entry="${entry%"${entry##*[![:space:]]}"}"
    dependency_fields+=("$entry")
done
core_matches=0
for entry in "${dependency_fields[@]}"; do
    if [[ "$entry" == "ricebowl-wayland-core (= ${versions[0]})" ]]; then
        core_matches=$((core_matches + 1))
    fi
done
if (( core_matches != 1 )); then
    echo "Desktop package does not pin exactly this core package/version" >&2
    exit 1
fi
for i in 1 2; do
    prefix="${names[$i]} (>= "
    minimum=
    matches=0
    for entry in "${dependency_fields[@]}"; do
        if [[ "$entry" == "$prefix"* && "$entry" == *")" ]]; then
            candidate=${entry#"$prefix"}
            candidate=${candidate%")"}
            # Reconstruct the atom exactly: no suffix, prefix tricks or
            # alternative dependencies may satisfy a mandatory package.
            if [[ -n "$candidate" && "$entry" == "$prefix$candidate)" ]]; then
                matches=$((matches + 1))
                minimum=$candidate
            fi
        fi
    done
    if (( matches != 1 )); then
        echo "Desktop package lacks one exact versioned dependency on ${names[$i]}" >&2
        exit 1
    fi
    if ! dpkg --compare-versions "${versions[$i]}" ge "$minimum"; then
        echo "Bundled ${names[$i]} is older than required $minimum" >&2
        exit 1
    fi
done

buildinfo="$work/package-0/usr/lib/ricebowl-wayland/BUILDINFO"
if [[ ! -f "$buildinfo" ]] || ! grep -Fxq "version=${versions[0]}" "$buildinfo" || \
   ! grep -Fxq "source_commit=${source_commits[0]}" "$buildinfo" || \
   ! grep -Eq '^source_date_epoch=[0-9]+$' "$buildinfo"; then
    echo "Core package is missing valid provenance data" >&2
    exit 1
fi
# Independently check the unpacked native ELF against the staged package's
# immutable payload digest. A self-reported digest is not build attestation:
# trustworthy release provenance additionally needs an externally verified
# build receipt tied to the source commit and Cargo.lock.
native_binary="$work/package-2/usr/bin/riceplate-native"
native_digest=$(dpkg-deb -f "${files[2]}" X-RiceBowl-Native-SHA256)
if [[ ! "$native_digest" =~ ^[0-9a-f]{64}$ ]]; then
    echo "Missing or invalid native binary SHA-256 metadata" >&2
    exit 1
fi
actual_digest=$(sha256sum -- "$native_binary")
actual_digest=${actual_digest%% *}
if [[ "$actual_digest" != "$native_digest" ]]; then
    echo "Native package binary integrity mismatch" >&2
    exit 1
fi

for required in \
    "$work/package-0/usr/lib/ricebowl-wayland/launcher.py" \
    "$work/package-0/usr/lib/ricebowl-wayland/macrice/de/session.py" \
    "$work/package-1/usr/share/wayland-sessions/ricebowl.desktop" \
    "$work/package-2/usr/bin/riceplate-native"; do
    if [[ ! -f "$required" ]]; then
        echo "Missing runtime or login entry: $required" >&2
        exit 1
    fi
done
if find "$work/package-3" -type f -print -quit | grep -q .; then
    echo "The desktop meta package must not install files" >&2
    exit 1
fi

echo "Verified four opt-in Wayland preview packages (no host installation)."
sha256sum -- "${files[@]}"
