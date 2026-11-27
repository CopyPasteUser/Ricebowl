#!/bin/bash
# Provision a disposable Ubuntu 24.04 cloud container for RiceBowl local CI
# (scripts/local_ci.sh). Idempotent; root only; never meant for a desktop host.
# Installs only what is missing. Safe to rerun.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "provision.sh: must run as root in a disposable container" >&2
  exit 1
fi
export DEBIAN_FRONTEND=noninteractive

# Everything the .github/workflows install, plus local helpers.
pkgs="at-spi2-core binutils clang dbus-user-session dbus-x11 dpkg-dev fonts-dejavu-core
fonts-lohit-deva fonts-wqy-microhei foot fuzzel gir1.2-glib-2.0 gir1.2-gstreamer-1.0
gir1.2-gtk-3.0 gir1.2-wnck-3.0 grim gstreamer1.0-pipewire gstreamer1.0-plugins-base labwc
libatk-adaptor libcairo2-dev libclang-dev libdbus-1-dev libdrm-dev libegl-mesa0 libegl1
libgl1-mesa-dri libgles2 libglib2.0-bin libglib2.0-dev libinput-dev libnotify-bin
libpango1.0-dev libpipewire-0.3-dev libpixman-1-dev libpng-dev librsvg2-common
libspa-0.2-dev libsystemd-dev libwayland-dev libwlroots-dev libxkbcommon-dev libxml2-dev
mako-notifier meson ninja-build pipewire pipewire-bin pkg-config procps pulseaudio
pulseaudio-utils python3-cairo python3-gi python3-gi-cairo python3-gst-1.0 python3-pil
python3-pyatspi swaybg swaylock thunar waybar wayland-protocols wayland-utils wireplumber
wl-clipboard wlr-randr wtype xclip xdg-desktop-portal xdg-desktop-portal-gtk
xdg-desktop-portal-wlr xdotool xfconf xfwm4 xterm xvfb xwayland
swayidle libgdk-pixbuf-2.0-dev scdoc git rsync python3.12-venv xfonts-base x11-utils gdb"
# shellcheck disable=SC2086
missing=$(dpkg-query -W -f='${Package} ${Status}\n' $pkgs 2>/dev/null \
  | awk '$NF != "installed" {print $1}'; for p in $pkgs; do
    dpkg-query -W "$p" >/dev/null 2>&1 || echo "$p"; done)
missing=$(printf '%s\n' $missing | sort -u | tr '\n' ' ')
if [ -n "${missing// /}" ]; then
  apt-get update -qq
  # shellcheck disable=SC2086
  apt-get install -y -qq --no-install-recommends $missing
fi

# GTK bindings belong to the system Python 3.12.
ln -sf python3.12 /usr/bin/python3

# RiceBowl refuses to run as root: an unprivileged user (docker group for packaging steps).
id rbdev >/dev/null 2>&1 || useradd -m -s /bin/bash rbdev
if getent group docker >/dev/null && ! id -nG rbdev | grep -qw docker; then
  usermod -aG docker rbdev
fi
if [ ! -x /opt/rbvenv/bin/pytest ]; then
  [ -x /opt/rbvenv/bin/python ] || /usr/bin/python3.12 -m venv --system-site-packages /opt/rbvenv
  /opt/rbvenv/bin/python -m pip install -q pytest
  chmod -R a+rX /opt/rbvenv
fi

# Workflows pin Rust 1.88.0; scripts/local_ci.sh uses it when installed.
export PATH="/root/.cargo/bin:$PATH"
if command -v rustup >/dev/null && ! rustup toolchain list | grep -q '^1\.88\.0-'; then
  rustup toolchain install 1.88.0 --profile minimal -c clippy,rustfmt >/dev/null
fi
[ -d /root/.rustup/toolchains ] && chmod -R o+rX /root/.rustup/toolchains
# Let rbdev traverse to the root-installed Rust toolchain.
chmod o+x /root

# Pinned private labwc 0.7.2 for the SG5 input-method-v2 smoke (stock 0.7.1 lacks it).
pin=b41af54a1bd7d9270d19de4c9a2b77d882cf3ede
if [ ! -x /opt/labwc-sg5/labwc ]; then
  rm -rf /opt/labwc-sg5-src /opt/labwc-sg5
  git init -q /opt/labwc-sg5-src
  git -C /opt/labwc-sg5-src remote add origin https://github.com/labwc/labwc.git
  git -C /opt/labwc-sg5-src fetch -q --no-tags --depth=1 origin "$pin"
  git -C /opt/labwc-sg5-src checkout -q --detach FETCH_HEAD
  meson setup /opt/labwc-sg5 /opt/labwc-sg5-src --wrap-mode=nofallback -Dxwayland=disabled \
    -Dnls=disabled -Dsvg=disabled -Dman-pages=disabled >/dev/null
  meson compile -C /opt/labwc-sg5 -j 4 >/dev/null
  chmod -R a+rX /opt/labwc-sg5
fi

# rb-sync: copy the checkout to the rbdev home (keeps target/ build cache).
cat > /usr/local/bin/rb-sync <<'SYNC'
#!/bin/sh
set -eu
src=${RB_REPO:-/home/user/Ricebowl}
mkdir -p /home/rbdev/Ricebowl
rsync -a --delete --exclude target/ "$src"/ /home/rbdev/Ricebowl/
chown -R rbdev:rbdev /home/rbdev/Ricebowl
SYNC
# rb-run CMD...: run CMD as rbdev in the synced checkout, with Rust, the proxy CA
# and a UTF-8 locale like CI runners.
cat > /usr/local/bin/rb-run <<'RUN'
#!/bin/sh
ca=/usr/local/share/rb-proxy-ca.crt
for f in "${SSL_CERT_FILE:-}" "${GIT_SSL_CAINFO:-}"; do
  [ -n "$f" ] && [ -r "$f" ] && { install -m 0644 "$f" "$ca"; break; }
done
cd /home/rbdev/Ricebowl && exec runuser -u rbdev -- env HOME=/home/rbdev LANG=C.UTF-8 LC_ALL=C.UTF-8 \
  PATH="${RB_PATH_PREFIX:+$RB_PATH_PREFIX:}/opt/rbvenv/bin:/root/.cargo/bin:$PATH" \
  RUSTUP_HOME=/root/.rustup CARGO_HOME=/home/rbdev/.cargo \
  SSL_CERT_FILE=$ca GIT_SSL_CAINFO=$ca CURL_CA_BUNDLE=$ca CARGO_HTTP_CAINFO=$ca REQUESTS_CA_BUNDLE=$ca "$@"
RUN
chmod 0755 /usr/local/bin/rb-sync /usr/local/bin/rb-run

# Pinned software-SHM portal backend for portal-strict-frame (writes /usr like
# the hosted disposable runner; only in this disposable container).
bash "$(dirname "$0")/provision_portal_backend.sh"

# Docker packaging steps need a daemon; start one if installed and not running.
if command -v dockerd >/dev/null && ! docker info >/dev/null 2>&1; then
  nohup dockerd >/var/log/rb-dockerd.log 2>&1 &
fi
echo "provision.sh: RiceBowl local-CI tooling ready"
