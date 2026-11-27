#!/bin/bash
# Build and register the pinned third-party software-SHM portal backend that
# wayland-portal-strict.yml installs on its disposable runner. Root only, for a
# disposable container (it writes /usr like the hosted job). Idempotent.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "provision_portal_backend.sh: run as root" >&2; exit 1; }
repo_dir=$(cd "$(dirname "$0")/../.." && pwd)
rev=09fe2bd00dcb7139c34f3d437376af81a2fec96b
src=/var/cache/ricebowl-local-ci/portal/.ci-generic-portal
stamp=/usr/libexec/.xdg-desktop-portal-generic.rev
if [ -x /usr/libexec/xdg-desktop-portal-generic ] && [ "$(cat "$stamp" 2>/dev/null)" = "$rev" ]; then
  exit 0
fi
rm -rf "$src"; mkdir -p "$(dirname "$src")"
git init -q "$src"
git -C "$src" remote add origin https://github.com/lamco-admin/xdg-desktop-portal-generic.git
git -C "$src" fetch -q --no-tags --depth=1 origin "$rev"
git -C "$src" checkout -q --detach FETCH_HEAD
# Same CI-only private-remote repair the hosted job applies.
RICEBOWL_LOCAL_CI_DISPOSABLE=1 /usr/bin/python3 "$repo_dir/scripts/ci_portal_generic_remote.py" \
  "$src/src/pipewire/mod.rs" "$src/src/pipewire/stream.rs"
(cd "$src" && PATH="/root/.cargo/bin:$PATH" RUSTUP_TOOLCHAIN=stable cargo build -q --release --locked)
install -Dm755 "$src/target/release/xdg-desktop-portal-generic" /usr/libexec/xdg-desktop-portal-generic
install -Dm644 "$src/data/generic.portal" /usr/share/xdg-desktop-portal/portals/generic.portal
sed -i 's/^UseIn=.*/UseIn=ricebowl;RiceBowl;labwc;wlroots;/' /usr/share/xdg-desktop-portal/portals/generic.portal
install -Dm644 "$src/data/org.freedesktop.impl.portal.desktop.generic.service" \
  /usr/share/dbus-1/services/org.freedesktop.impl.portal.desktop.generic.service
echo "$rev" > "$stamp"
echo "provision_portal_backend.sh: backend $rev registered"
