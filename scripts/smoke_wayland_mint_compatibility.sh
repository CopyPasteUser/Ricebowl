#!/usr/bin/env bash
# SG6: isolated Linux Mint 22.1 Xia amd64 package resolver and purge smoke.
# Imports a hash-pinned Linux Containers-generated Mint root filesystem into
# the disposable Docker daemon; it never installs any .deb on the runner,
# host, laptop, XFCE session or existing user directory.
set -euo pipefail

if [[ ${RICEBOWL_CI_MINT:-} != 1 || $(id -u) == 0 ]]; then
    echo "Mint CI requires an explicitly opted-in, unprivileged Docker caller" >&2
    exit 2
fi
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
packages=${1:-"$root/dist/riceplate-native-preview"}
if [[ "$packages" != /* || ! -d "$packages" || -L "$packages" ]]; then
    echo "Provide an absolute, real directory with the four built Debian packages" >&2
    exit 2
fi
for tool in curl docker dpkg-deb sha256sum xz; do
    command -v "$tool" >/dev/null || { echo "Missing $tool" >&2; exit 1; }
done

# Linux Containers built this Mint Xia rootfs from its image infrastructure.
# Fixed dated URL + externally recorded SHA prevent a mutable latest tag from
# silently changing our test environment. This is NOT an official Mint ISO or
# independently signed package/host attestation.
mint_rootfs_url="https://images.linuxcontainers.org/images/mint/xia/amd64/default/20261114_08:51/rootfs.tar.xz"
mint_rootfs_sha256="e50db5d5624bcb8f2150845031f062312de346a029ef743eae63f34e9d197ca3"
work=$(mktemp -d -t ricebowl-mint-xia-XXXXXXXX)
tag="ricebowl-mint-xia-sg6:${GITHUB_RUN_ID:-manual}-${GITHUB_RUN_ATTEMPT:-0}"
cleanup() {
    docker image rm "$tag" >/dev/null 2>&1 || :
    rm -rf -- "$work"
}
trap cleanup EXIT
archive="$work/mint-xia-rootfs.tar.xz"
curl --fail --silent --show-error --location --retry 3 \
    --proto '=https' --proto-redir '=https' --max-time 180 \
    --output "$archive" "$mint_rootfs_url"
printf '%s  %s\n' "$mint_rootfs_sha256" "$archive" | sha256sum --check --status || {
    echo "Mint rootfs digest mismatch: refusing unverified image" >&2; exit 1;
}
xz --decompress --stdout "$archive" | docker import - "$tag" >/dev/null

# Check the source-built package identities before handing the four archives
# into an isolated container as a strictly read-only bind mount.
for spec in \
    ricebowl-wayland-core_0.1.0~preview2_all.deb:ricebowl-wayland-core:0.1.0~preview2 \
    ricebowl-wayland-session_0.1.0~preview3_all.deb:ricebowl-wayland-session:0.1.0~preview3 \
    ricebowl-riceplate-native_0.1.0~preview2_amd64.deb:ricebowl-riceplate-native:0.1.0~preview2 \
    ricebowl-wayland-desktop_0.1.0~preview3_amd64.deb:ricebowl-wayland-desktop:0.1.0~preview3; do
    IFS=: read -r filename name version <<< "$spec"
    file="$packages/$filename"
    [[ -f "$file" && ! -L "$file" ]] || { echo "Missing/unsafe $filename" >&2; exit 1; }
    [[ $(dpkg-deb --field "$file" Package) == "$name" ]] || exit 1
    [[ $(dpkg-deb --field "$file" Version) == "$version" ]] || exit 1
done

docker run --rm --pull=never --network=bridge -i \
    --volume "$packages:/ricebowl-packages:ro" \
    "$tag" /bin/bash -s <<'IN_MINT'
set -euo pipefail
. /etc/os-release
test "$ID" = linuxmint
test "$VERSION_ID" = '22.1'
test "$(dpkg --print-architecture)" = amd64
grep -Fqi 'xia' /etc/apt/sources.list.d/official-package-repositories.list
export DEBIAN_FRONTEND=noninteractive

# The image may not contain the full XFCE desktop. Preserve explicit private
# XFCE/recipe state and any pre-existing default display-manager selection.
useradd -m -u 22021 owner
install -d -m 0700 -o owner -g owner /home/owner/.config/xfce4
install -d -m 0700 -o owner -g owner /home/owner/.config/ricebowl/recipes
printf '%s\n' 'XFCE_LIVE_PROFILE_MUST_NOT_CHANGE=true' \
    > /home/owner/.config/xfce4/xfce4-panel.xml
printf '%s\n' '{"id":"mint-xia-existing-rice","revision":4}' \
    > /home/owner/.config/ricebowl/recipes/owned.json
chmod 0600 /home/owner/.config/xfce4/xfce4-panel.xml \
    /home/owner/.config/ricebowl/recipes/owned.json
chown -R owner:owner /home/owner/.config
sha256sum /home/owner/.config/xfce4/xfce4-panel.xml \
    /home/owner/.config/ricebowl/recipes/owned.json >/tmp/owner-before.sha256
if test -f /etc/X11/default-display-manager; then
    sha256sum /etc/X11/default-display-manager >/tmp/default-dm-before.sha256
fi
check_owner() {
    sha256sum --check --status /tmp/owner-before.sha256
    test "$(stat -c '%a:%u' /home/owner/.config/ricebowl/recipes/owned.json)" = 600:22021
    if test -f /tmp/default-dm-before.sha256; then
        sha256sum --check --status /tmp/default-dm-before.sha256
    fi
}

apt-get update -qq
apt-get install -y --no-install-recommends \
    /ricebowl-packages/ricebowl-wayland-core_0.1.0~preview2_all.deb \
    /ricebowl-packages/ricebowl-wayland-session_0.1.0~preview3_all.deb \
    /ricebowl-packages/ricebowl-riceplate-native_0.1.0~preview2_amd64.deb \
    /ricebowl-packages/ricebowl-wayland-desktop_0.1.0~preview3_amd64.deb >/dev/null
version() { dpkg-query -W -f='${Version}' "$1"; }
test "$(version ricebowl-wayland-core)" = '0.1.0~preview2'
test "$(version ricebowl-wayland-session)" = '0.1.0~preview3'
test "$(version ricebowl-riceplate-native)" = '0.1.0~preview2'
test "$(version ricebowl-wayland-desktop)" = '0.1.0~preview3'
test -z "$(dpkg --audit)"
test -x /usr/bin/riceplate-native
test -x /usr/bin/ricebowl-wayland-session
test -x /usr/bin/ricebowl-wayland-app
test -e /usr/share/wayland-sessions/ricebowl-native.desktop
runuser -u owner -- env HOME=/home/owner XDG_CONFIG_HOME=/home/owner/.config \
    /usr/bin/ricebowl-wayland-app de --help >/dev/null
/usr/bin/riceplate-native --version >/dev/null
check_owner
echo 'PASS: Mint Xia 22.1 resolved and installed all four real .deb packages'

apt-get purge -y ricebowl-wayland-desktop ricebowl-wayland-core \
    ricebowl-wayland-session ricebowl-riceplate-native >/dev/null
test ! -e /usr/bin/riceplate-native
test ! -e /usr/bin/ricebowl-wayland-app
test ! -e /usr/bin/ricebowl-wayland-session
test ! -e /usr/share/wayland-sessions/ricebowl-native.desktop
test ! -e /usr/share/wayland-sessions/ricebowl.desktop
test -z "$(dpkg --audit)"
check_owner
echo 'PASS: Mint Xia 22.1 purge preserved user XFCE and RiceBowl data'
echo 'SCOPE: Linux Containers Mint Xia rootfs, not a running XFCE login, hardware or release sign-off'
IN_MINT
