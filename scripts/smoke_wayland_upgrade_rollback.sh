#!/usr/bin/env bash
# Real previous-release -> current-release apt upgrade and downgrade in
# disposable Ubuntu 24.04. Never installs or removes packages on the host.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
packages=${1:-"$root/dist/riceplate-native-preview"}
baseline=b3d615a7cc508049050eb06c7952ef5a8d26e598
if [[ ! "$packages" = /* || ! -d "$packages" ]]; then
    echo "Pass the absolute directory containing built current preview packages" >&2
    exit 2
fi
for tool in git docker dpkg-deb; do
    command -v "$tool" >/dev/null || { echo "$tool is required" >&2; exit 1; }
done
if ! git -C "$root" cat-file -e "$baseline^{commit}" 2>/dev/null; then
    echo "Previous release commit unavailable; fetch the pinned base first: $baseline" >&2
    exit 1
fi
temp=$(mktemp -d -t ricebowl-upgrade-XXXXXXXX)
worktree="$temp/previous"
cleanup() {
    if [[ -d "$worktree/.git" || -f "$worktree/.git" ]]; then
        git -C "$root" worktree remove --force "$worktree" >/dev/null 2>&1 || :
    fi
    rm -rf -- "$temp"
}
trap cleanup EXIT
mkdir -m 0755 "$temp/old-packages"
git -C "$root" worktree add --detach "$worktree" "$baseline" >/dev/null
old_core="$temp/old-packages/ricebowl-wayland-core_0.1.0~preview1_all.deb"
old_meta="$temp/old-packages/ricebowl-wayland-desktop_0.1.0~preview1_amd64.deb"
bash "$worktree/scripts/build_wayland_core_deb.sh" "$old_core" >/dev/null
sh "$worktree/scripts/build_wayland_desktop_deb.sh" "$old_meta" >/dev/null
new_core="$packages/ricebowl-wayland-core_0.1.0~preview2_all.deb"
new_meta="$packages/ricebowl-wayland-desktop_0.1.0~preview2_amd64.deb"
session="$packages/ricebowl-wayland-session_0.1.0~preview3_all.deb"
native="$packages/ricebowl-riceplate-native_0.1.0~preview1_amd64.deb"
for file in "$old_core" "$old_meta" "$new_core" "$new_meta" "$session" "$native"; do
    if [[ ! -f "$file" || -L "$file" ]]; then
        echo "Missing or unsafe package: $file" >&2; exit 1
    fi
done
check_version() {
    local file=$1 name=$2 version=$3
    [[ "$(dpkg-deb --field "$file" Package)" == "$name" ]] || {
        echo "Unexpected package name in $file" >&2; exit 1;
    }
    [[ "$(dpkg-deb --field "$file" Version)" == "$version" ]] || {
        echo "Unexpected package version in $file" >&2; exit 1;
    }
}
check_version "$old_core" ricebowl-wayland-core '0.1.0~preview1'
check_version "$old_meta" ricebowl-wayland-desktop '0.1.0~preview1'
check_version "$new_core" ricebowl-wayland-core '0.1.0~preview2'
check_version "$new_meta" ricebowl-wayland-desktop '0.1.0~preview2'
if cmp -s "$old_core" "$new_core"; then
    echo "Old and new core packages unexpectedly contain identical bytes" >&2
    exit 1
fi

# Mount only package archives read-only. The container owns its own apt/dpkg
# database, its own simulated home and its own XFCE configuration canaries.
docker run --rm -i --pull=missing \
    --volume "$temp/old-packages:/before:ro" \
    --volume "$packages:/after:ro" \
    ubuntu:24.04 bash -s <<'IN_CONTAINER'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
old_core=/before/ricebowl-wayland-core_0.1.0~preview1_all.deb
old_meta=/before/ricebowl-wayland-desktop_0.1.0~preview1_amd64.deb
new_core=/after/ricebowl-wayland-core_0.1.0~preview2_all.deb
new_meta=/after/ricebowl-wayland-desktop_0.1.0~preview2_amd64.deb
session=/after/ricebowl-wayland-session_0.1.0~preview3_all.deb
native=/after/ricebowl-riceplate-native_0.1.0~preview1_amd64.deb
version() { dpkg-query -W -f='${Version}' "$1"; }
check_version() { test "$(version "$1")" = "$2"; }
check_user_state() {
    sha256sum -c --status /tmp/ricebowl-user-before.sha256
    test "$(stat -c '%a:%u' /home/owner/.config/ricebowl/recipes/saved.json)" = 600:22001
    test ! -e /usr/bin/ricebowl
}
apt-get update -qq
useradd -m -u 22001 owner
install -d -m 0700 -o owner -g owner /home/owner/.config/ricebowl/recipes
install -d -m 0700 -o owner -g owner /home/owner/.config/xfce4
install -d -m 0700 -o owner -g owner /home/owner/.local/bin
printf '%s\n' '{"id":"owner-private-rice","revision":7}' \
    > /home/owner/.config/ricebowl/recipes/saved.json
printf '%s\n' 'XFCE_PANEL_DO_NOT_MODIFY=true' \
    > /home/owner/.config/xfce4/xfce4-panel.xml
printf '%s\n' '#!/bin/sh' 'echo user-local-ricebowl' \
    > /home/owner/.local/bin/ricebowl
chmod 0600 /home/owner/.config/ricebowl/recipes/saved.json
chmod 0700 /home/owner/.local/bin/ricebowl
chown -R owner:owner /home/owner
sha256sum /home/owner/.config/ricebowl/recipes/saved.json \
    /home/owner/.config/xfce4/xfce4-panel.xml \
    /home/owner/.local/bin/ricebowl > /tmp/ricebowl-user-before.sha256

echo 'PHASE 1/5: clean install of real previous Core/Meta versions'
apt-get install -y --no-install-recommends \
    "$old_core" "$old_meta" "$session" "$native" >/dev/null
check_version ricebowl-wayland-core '0.1.0~preview1'
check_version ricebowl-wayland-desktop '0.1.0~preview1'
test ! -e /usr/lib/ricebowl-wayland/BUILDINFO
/usr/bin/ricebowl-wayland-app de --help >/dev/null
check_user_state

echo 'PHASE 2/5: reject corrupt new package without altering old install'
cp "$new_core" /tmp/invalid-core.deb
truncate -s 41 /tmp/invalid-core.deb
if apt-get install -y /tmp/invalid-core.deb >/tmp/rejected-upgrade.log 2>&1; then
    echo 'Corrupt upgrade was unexpectedly accepted' >&2; exit 1
fi
check_version ricebowl-wayland-core '0.1.0~preview1'
check_version ricebowl-wayland-desktop '0.1.0~preview1'
/usr/bin/ricebowl-wayland-app de --help >/dev/null
check_user_state

echo 'PHASE 3/5: real apt upgrade to Core/Meta preview2'
apt-get install -y --no-install-recommends "$new_core" "$new_meta" >/dev/null
check_version ricebowl-wayland-core '0.1.0~preview2'
check_version ricebowl-wayland-desktop '0.1.0~preview2'
grep -Fxq 'version=0.1.0~preview2' /usr/lib/ricebowl-wayland/BUILDINFO
test -f /usr/lib/ricebowl-wayland/macrice/de/session.py
test -e /usr/share/wayland-sessions/ricebowl-native.desktop
/usr/bin/ricebowl-wayland-app de --help >/dev/null
check_user_state

echo 'PHASE 4/5: explicit rollback to saved previous Core/Meta'
apt-get install -y --no-install-recommends --allow-downgrades \
    "$old_core" "$old_meta" >/dev/null
check_version ricebowl-wayland-core '0.1.0~preview1'
check_version ricebowl-wayland-desktop '0.1.0~preview1'
test ! -e /usr/lib/ricebowl-wayland/BUILDINFO
/usr/bin/ricebowl-wayland-app de --help >/dev/null
check_user_state

echo 'PHASE 5/5: repeat upgrade, purge package-owned files, keep user data'
apt-get install -y --no-install-recommends "$new_core" "$new_meta" >/dev/null
check_version ricebowl-wayland-core '0.1.0~preview2'
check_version ricebowl-wayland-desktop '0.1.0~preview2'
apt-get purge -y ricebowl-wayland-desktop ricebowl-wayland-core \
    ricebowl-wayland-session ricebowl-riceplate-native >/dev/null
test ! -e /usr/bin/ricebowl-wayland-app
test ! -e /usr/lib/ricebowl-wayland/launcher.py
test ! -e /usr/lib/ricebowl-wayland/BUILDINFO
test ! -e /usr/share/wayland-sessions/ricebowl.desktop
test ! -e /usr/share/wayland-sessions/ricebowl-native.desktop
check_user_state
echo 'PASS: previous→new upgrade, failure rejection, downgrade, re-upgrade, purge and user/xfce preservation'
IN_CONTAINER
