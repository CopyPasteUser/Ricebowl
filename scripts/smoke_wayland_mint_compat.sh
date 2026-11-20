#!/bin/sh
# SG6: actual .deb lifecycle inside a disposable Linux Mint 22.1 build root.
# This script must only be mounted into an isolated CI container, never run
# on a user's desktop or an installed host. No login defaults are changed.
set -eu
export LC_ALL=C DEBIAN_FRONTEND=noninteractive

if [ "$(id -u)" -ne 0 ] || [ ! -d /packages ] || [ ! -n "$RICEBOWL_SOURCE_SHA" ]; then
    echo "Mint compatibility smoke requires root in a disposable package container" >&2
    exit 2
fi
printf '%s\n' "$RICEBOWL_SOURCE_SHA" | grep -Eq '^[0-9a-f]{40}$' || {
    echo "Expected a committed 40-character source SHA" >&2
    exit 2
}
test "$(dpkg --print-architecture)" = amd64
# Mint's CI build root can report its Ubuntu noble base in os-release.
# Check the actual Xia APT source and candidate Mint package instead of
# trusting a cosmetic /etc/os-release string or a Docker image tag.
if ! grep -REq 'packages[.]linuxmint[.]com[[:space:]]+xia[[:space:]]' \
       /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null; then
    echo "Not a Linux Mint 22.1 Xia package root (Mint APT source missing)" >&2
    exit 1
fi
apt-get -o Acquire::Retries=2 update -qq
mint_candidate=$(apt-cache policy mintsystem | awk '/Candidate:/ {print $2; exit}')
if [ -z "$mint_candidate" ] || [ "$mint_candidate" = '(none)' ]; then
    echo "Linux Mint package candidate not available; refusing Ubuntu-only evidence" >&2
    exit 1
fi
printf 'Mint Xia package source verified; mintsystem candidate: %s\n' "$mint_candidate"

core=/packages/ricebowl-wayland-core_0.1.0~preview2_all.deb
session=/packages/ricebowl-wayland-session_0.1.0~preview3_all.deb
native=/packages/ricebowl-riceplate-native_0.1.0~preview2_amd64.deb
desktop=/packages/ricebowl-wayland-desktop_0.1.0~preview3_amd64.deb
for archive in "$core" "$session" "$native" "$desktop"; do
    if [ ! -f "$archive" ] || [ -L "$archive" ]; then
        echo "Missing or symlinked tested artifact: $archive" >&2
        exit 1
    fi
    declared=$(dpkg-deb --field "$archive" X-RiceBowl-Source-Commit)
    if [ "$declared" != "$RICEBOWL_SOURCE_SHA" ]; then
        echo "Package was not built from the exact tested commit: $archive" >&2
        exit 1
    fi
done

owner=ricebowl-mint-qa
useradd --create-home --uid 23001 "$owner"
install -d -m 0700 -o "$owner" -g "$owner" "/home/$owner/.config/xfce4"
install -d -m 0700 -o "$owner" -g "$owner" "/home/$owner/.config/ricebowl/recipes"
install -d -m 0700 -o "$owner" -g "$owner" "/home/$owner/.local/share/applications"
printf 'XFCE_PANEL_MUST_SURVIVE=1\n' > "/home/$owner/.config/xfce4/xfce4-panel.xml"
printf '{"id":"private-mint-test","revision":13}\n' > "/home/$owner/.config/ricebowl/recipes/custom.json"
printf '[Desktop Entry]\nName=Personal\nType=Application\nExec=true\n' > "/home/$owner/.local/share/applications/personal.desktop"
chown -R "$owner:$owner" "/home/$owner"
chmod 0600 "/home/$owner/.config/ricebowl/recipes/custom.json"
sha256sum \
    "/home/$owner/.config/xfce4/xfce4-panel.xml" \
    "/home/$owner/.config/ricebowl/recipes/custom.json" \
    "/home/$owner/.local/share/applications/personal.desktop" \
    > /tmp/ricebowl-mint-canaries.sha256
check_private_data() {
    sha256sum --check --status /tmp/ricebowl-mint-canaries.sha256
    test "$(stat -c '%a:%u' "/home/$owner/.config/ricebowl/recipes/custom.json")" = 600:23001
}
check_package() {
    archive=$1
    name=$(dpkg-deb --field "$archive" Package)
    expected=$(dpkg-deb --field "$archive" Version)
    actual=$(dpkg-query -W "$name" | awk 'NR==1 {print $2}')
    test "$actual" = "$expected" || {
        echo "Expected $name at $expected; got $actual" >&2
        exit 1
    }
    dpkg -s "$name" | grep -Fxq 'Status: install ok installed'
}
check_clean_dpkg() {
    audit=$(dpkg --audit)
    test -z "$audit" || {
        printf 'dpkg still has broken state:\n%s\n' "$audit" >&2
        exit 1
    }
}
check_private_data

echo 'MINT PHASE 1/5: exact-source four-package install'
apt-get install -y --no-install-recommends \
    "$core" "$session" "$native" "$desktop" >/dev/null
for archive in "$core" "$session" "$native" "$desktop"; do
    check_package "$archive"
done
test -x /usr/bin/riceplate-native
test -x /usr/bin/ricebowl-wayland-app
test -x /usr/bin/ricebowl-wayland-session
test -f /usr/share/wayland-sessions/ricebowl-native.desktop
runuser -u "$owner" -- env HOME="/home/$owner" \
    XDG_CONFIG_HOME="/home/$owner/.config" \
    /usr/bin/ricebowl-wayland-app de --help >/dev/null
check_private_data
check_clean_dpkg

echo 'MINT PHASE 2/5: damaged archive must not replace the installed package'
cp "$native" /tmp/ricebowl-mint-corrupt-native.deb
truncate -s 37 /tmp/ricebowl-mint-corrupt-native.deb
before=$(sha256sum /usr/bin/riceplate-native | awk '{print $1}')
if apt-get install -y /tmp/ricebowl-mint-corrupt-native.deb \
    >/tmp/ricebowl-mint-reject.log 2>&1; then
    echo 'Corrupted native package unexpectedly accepted' >&2
    exit 1
fi
test "$(sha256sum /usr/bin/riceplate-native | awk '{print $1}')" = "$before"
check_package "$native"
check_private_data
check_clean_dpkg

echo 'MINT PHASE 3/5: reinstall all components and check user/XFCE preservation'
apt-get install -y --no-install-recommends --reinstall \
    "$core" "$session" "$native" "$desktop" >/dev/null
for archive in "$core" "$session" "$native" "$desktop"; do
    check_package "$archive"
done
check_private_data
check_clean_dpkg

echo 'MINT PHASE 4/5: simulated interrupted core configure and repair'
# Fault injection is inside this disposable container only. Published .deb
# files and the user's actual dpkg database never contain this script.
scratch=$(mktemp -d -t ricebowl-mint-interrupted-XXXXXXXX)
trap 'rm -rf -- "$scratch"' EXIT
dpkg-deb --raw-extract "$core" "$scratch/unpacked"
cat > "$scratch/unpacked/DEBIAN/postinst" <<'KILL_POSTINST'
#!/bin/sh
set -eu
[ "$1" = configure ] || exit 0
kill -KILL "$$"
KILL_POSTINST
chmod 0755 "$scratch/unpacked/DEBIAN/postinst"
dpkg-deb --build --root-owner-group \
    "$scratch/unpacked" "$scratch/interrupted-core.deb" >/dev/null
if dpkg -i "$scratch/interrupted-core.deb" >"$scratch/dpkg.log" 2>&1; then
    echo 'Injected SIGKILL did not interrupt package configuration' >&2
    exit 1
fi
if ! grep -Eq 'post-installation script.*killed by signal' "$scratch/dpkg.log"; then
    echo 'Failed to prove an actual SIGKILL during dpkg configuration' >&2
    sed -n '1,30p' "$scratch/dpkg.log" >&2
    exit 1
fi
if dpkg -s ricebowl-wayland-core | grep -Fxq 'Status: install ok installed'; then
    echo 'dpkg did not enter an interrupted state' >&2
    exit 1
fi
check_private_data
dpkg -i "$core" >/dev/null
apt-get -f install -y --no-install-recommends >/dev/null
for archive in "$core" "$session" "$native" "$desktop"; do
    check_package "$archive"
done
check_private_data
check_clean_dpkg

echo 'MINT PHASE 5/5: purge only RiceBowl packages, preserve owner data'
apt-get purge -y \
    ricebowl-wayland-desktop ricebowl-wayland-core \
    ricebowl-wayland-session ricebowl-riceplate-native >/dev/null
test ! -e /usr/bin/riceplate-native
test ! -e /usr/bin/ricebowl-wayland-app
test ! -e /usr/bin/ricebowl-wayland-session
test ! -e /usr/share/wayland-sessions/ricebowl-native.desktop
check_private_data
check_clean_dpkg
echo 'PASS: Mint 22.1 Xia software package lifecycle; no Mint hardware login/GPU claim'
