#!/bin/sh
# SG4 WP4.2: real GTK Rice Creator apply/restore against a FULL (non-nested) RiceBowl Wayland
# session, started as the top-level session exactly the way a display manager starts it.
#
# Session entry: the packaged login script `packaging/wayland/ricebowl-wayland-session --native`
# (the file /usr/share/wayland-sessions/ricebowl-native.desktop executes) with no WAYLAND_DISPLAY /
# DISPLAY, which exports RICEBOWL_DM_SESSION=1 and execs `ricebowl de start --panel native` WITHOUT
# --nested. labwc is therefore the top compositor (headless backend), `session.shell()` runs in
# full-login mode (RICEBOWL_DE_NESTED=0: swayidle lock guard, Mako owned by the session, the
# live supervisor persists the next-login selection) and riceplate-native is the panel.
#
# What this script exercises: the unmodified login script, the real `de start` full-login path,
# real labwc 0.7.x, real riceplate-native, real swayidle/Mako/swaybg, the real GTK Creator
# (install / apply / restore through its real dialogs), the supervisor's persisted selection and a
# logout (`labwc --exit`) followed by a residue check. What it cannot exercise in this container
# (documented in docs/sg4-creator-export-review-qa.md): a display manager / greeter, logind seat
# and VT/DRM acquisition (the headless wlroots backend replaces them), systemd --user
# (the session's D-Bus is the disposable `dbus-run-session` bus), a polkit authentication agent
# (none installed) and a real display. The seams, all private and listed here:
#   * HOME/XDG_* are a disposable profile; `$HOME/.local/bin/ricebowl` is the user-local
#     application entry the login script falls back to when the system-wide package
#     (/usr/bin/ricebowl-wayland-app) is not installed;
#   * `labwc` on PATH is the real compositor with ONE extra window rule appended to the session's
#     private rc.xml (every window at 0,0 without server decoration, so AT-SPI coordinates map
#     onto output pixels); --exit/--reconfigure and every other call pass straight through.
#
# Exit 77 = tool missing. Disposable only; never touches a logged-in session.
set -eu
root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
release="$root/components/riceplate-wayland/target/release"
clicker="$release/examples/wayland_pointer_click"
for command in dbus-run-session labwc wlr-randr grim swaybg waybar swaylock swayidle mako \
    foot fuzzel wtype timeout; do
    command -v "$command" >/dev/null 2>&1 || { echo "Missing $command" >&2; exit 77; }
done
test -x "$clicker" && test -x "$release/riceplate-native" || {
    echo "Build riceplate-native and the wayland_pointer_click example first" >&2; exit 77; }
/usr/bin/python3 -c 'import PIL, pyatspi, gi' >/dev/null 2>&1 || exit 77
[ "$(id -u)" -ne 0 ] || { echo "Do not run the full-login smoke as root" >&2; exit 2; }
test -r "$root/packaging/wayland/ricebowl-wayland-session" || { echo "login script missing" >&2; exit 2; }

runtime=$(mktemp -d -t ricebowl-sg4-login-XXXXXXXX)
chmod 0700 "$runtime"
trap 'rm -rf -- "$runtime"' EXIT
mkdir -m 0700 "$runtime/run" "$runtime/packs" "$runtime/shots" "$runtime/bin" "$runtime/session"
mkdir -m 0700 "$runtime/session/home" "$runtime/session/config" "$runtime/session/state"
mkdir -p -m 0700 "$runtime/session/home/.local/bin" "$runtime/session/home/.local/share"
real_labwc=$(command -v labwc)
bin="$runtime/bin"
cat >"$runtime/session/home/.local/bin/ricebowl" <<APP
#!/bin/sh
exec /usr/bin/python3 "$root/launcher.py" "\$@"
APP
cat >"$bin/labwc" <<WRAP
#!/bin/sh
if [ "\${1:-}" = --config-dir ]; then
    sed -i 's#</labwc_config>#<windowRules><windowRule identifier="*" serverDecoration="no"><action name="MoveTo" x="0" y="0"/></windowRule></windowRules></labwc_config>#' "\$2/rc.xml"
fi
exec "$real_labwc" "\$@"
WRAP
chmod 0700 "$runtime/session/home/.local/bin/ricebowl" "$bin/labwc"

export XDG_RUNTIME_DIR="$runtime/run"
export HOME="$runtime/session/home" XDG_CONFIG_HOME="$runtime/session/config" \
    XDG_STATE_HOME="$runtime/session/state" XDG_DATA_HOME="$runtime/session/home/.local/share"
export WLR_BACKENDS=headless WLR_HEADLESS_OUTPUTS=1 WLR_RENDERER=pixman XDG_SESSION_TYPE=wayland
# A display manager exports neither: the login script must work without them.
unset WAYLAND_DISPLAY DISPLAY RICEBOWL_DE_NESTED RICEBOWL_DE_PRIVATE_BUS RICEBOWL_DM_SESSION GDK_BACKEND
export SG4G_RUNTIME="$runtime" SG4G_ROOT="$root" SG4G_CLICKER="$clicker"

set +e
timeout -k 5s "${SG4G_BUDGET_LOGIN:-720}s" dbus-run-session -- sh -eu -c '
    root=$1; runtime=$2; release=$3; bin=$4
    session=
    keeper=
    cleanup() {
        for pid in "$keeper" "$session"; do
            if [ -n "$pid" ]; then kill "$pid" 2>/dev/null || :; fi
        done
        for pid in "$keeper" "$session"; do
            if [ -n "$pid" ]; then wait "$pid" 2>/dev/null || :; fi
        done
    }
    trap cleanup EXIT
    # One login per phase on the SAME private profile and user bus (a user bus outlives logins):
    #   roundtrip  Creator install + apply + restore, logout, residue check
    #   persist    Creator apply, logout WITHOUT restoring (the choice persists)
    #   relogin    the next login comes up on the applied rice; Creator restore; logout; residue
    for phase in ${SG4G_PHASES:-roundtrip persist relogin}; do
        # The login entry, exactly as ricebowl-native.desktop runs it (Exec=... --native).
        PATH="$bin:$release:$PATH" sh "$root/packaging/wayland/ricebowl-wayland-session" --native \
            >"$runtime/session-$phase.log" 2>&1 &
        session=$!
        n=0
        while [ ! -S "$XDG_RUNTIME_DIR/wayland-0" ] || [ ! -S "$XDG_RUNTIME_DIR/ricebowl-live-wayland-0.sock" ]; do
            n=$((n + 1))
            if [ "$n" -ge 160 ] || ! kill -0 "$session" 2>/dev/null; then
                sed -n "1,60p" "$runtime/session-$phase.log" >&2
                echo "full-login session ($phase) did not come up" >&2; exit 1
            fi
            sleep 0.25
        done
        export WAYLAND_DISPLAY=wayland-0
        wtype -k F13 -s 1800000 -k F13 >"$runtime/keeper-$phase.log" 2>&1 &
        keeper=$!
        output=$(wlr-randr | sed -n "1s/[[:space:]].*//p")
        wlr-randr --output "$output" --custom-mode 1366x768@60Hz --scale 1
        sleep 2
        /usr/bin/python3 -c "import pyatspi; pyatspi.Registry.getDesktop(0).childCount" >/dev/null
        # Only the Creator (a client) needs GDK_BACKEND; the session itself never sets it.
        GDK_BACKEND=wayland SG4G_SESSION_PID=$session PATH="$bin:$release:$PATH" /usr/bin/python3 \
            "${SG4G_DRIVER:-$root/scripts/sg4_creator_gui_roundtrip_driver.py}" login "$phase"
        # The driver logged out (labwc --exit) and checked the session is gone; reap it.
        wait "$session" 2>/dev/null || :
        session=
        kill "$keeper" 2>/dev/null || :
        wait "$keeper" 2>/dev/null || :
        keeper=
        unset WAYLAND_DISPLAY
    done
' sh "$root" "$runtime" "$release" "$bin"
status=$?
set -e
if [ -n "${SG4G_KEEP_DIR:-}" ]; then
    cp "$runtime"/shots/*.png "$runtime"/*.log "$SG4G_KEEP_DIR"/ 2>/dev/null || :
fi
[ "$status" -eq 0 ] || { echo "FAIL: SG4 Creator full-login smoke exited $status" >&2; exit "$status"; }
echo "PASS: SG4 real GTK Creator apply/restore/next-login against the full (non-nested) login session"
