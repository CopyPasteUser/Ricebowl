#!/usr/bin/env bash
# Real previous-release -> current-release apt upgrade and downgrade in
# disposable Ubuntu 24.04. Never installs or removes packages on the host.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
packages=${1:-"$root/dist/riceplate-native-preview"}
baseline=b3d615a7cc508049050eb06c7952ef5a8d26e598
# Real previous session preview2, before the independently versioned preview3.
session_baseline=c8274dee78386124470cb5ff9a4d2768bb019126
if [[ ! "$packages" = /* || ! -d "$packages" ]]; then
    echo "Pass the absolute directory containing built current preview packages" >&2
    exit 2
fi
for tool in git docker dpkg-deb cargo rustc; do
    command -v "$tool" >/dev/null || { echo "$tool is required" >&2; exit 1; }
done
for revision in "$baseline" "$session_baseline"; do
    if ! git -C "$root" cat-file -e "$revision^{commit}" 2>/dev/null; then
        echo "Previous release commit unavailable; fetch the pinned base first: $revision" >&2
        exit 1
    fi
done
temp=$(mktemp -d -t ricebowl-upgrade-XXXXXXXX)
worktree="$temp/previous"
session_worktree="$temp/previous-session"
cleanup() {
    for checkout in "$worktree" "$session_worktree"; do
        if [[ -d "$checkout/.git" || -f "$checkout/.git" ]]; then
            git -C "$root" worktree remove --force "$checkout" >/dev/null 2>&1 || :
        fi
    done
    rm -rf -- "$temp"
}
trap cleanup EXIT
mkdir -m 0755 "$temp/old-packages"
git -C "$root" worktree add --detach "$worktree" "$baseline" >/dev/null
git -C "$root" worktree add --detach "$session_worktree" "$session_baseline" >/dev/null
old_core="$temp/old-packages/ricebowl-wayland-core_0.1.0~preview1_all.deb"
old_meta="$temp/old-packages/ricebowl-wayland-desktop_0.1.0~preview1_amd64.deb"
old_native="$temp/old-packages/ricebowl-riceplate-native_0.1.0~preview1_amd64.deb"
old_session2="$temp/old-packages/ricebowl-wayland-session_0.1.0~preview2_all.deb"
old_session3="$temp/old-packages/ricebowl-wayland-session_0.1.0~preview3_all.deb"
bash "$worktree/scripts/build_wayland_core_deb.sh" "$old_core" >/dev/null
sh "$worktree/scripts/build_wayland_desktop_deb.sh" "$old_meta" >/dev/null
sh "$session_worktree/scripts/build_wayland_session_deb.sh" "$old_session2" >/dev/null
sh "$worktree/scripts/build_wayland_session_deb.sh" "$old_session3" >/dev/null
# The previous native revision must be compiled from real immutable source;
# packaging the current ELF with a forged preview1 control is not evidence.
# Historical preview1 did not commit Cargo.lock: resolve its pinned manifest
# here and record that this is a historical-source rebuild, NOT a byte-for-byte
# attestation of the originally distributed preview1 binary.
old_native_target="$temp/old-native-target"
cargo generate-lockfile --manifest-path "$worktree/components/riceplate-wayland/Cargo.toml" >/dev/null
CARGO_TARGET_DIR="$old_native_target" cargo build --release --locked \
    --manifest-path "$worktree/components/riceplate-wayland/Cargo.toml" >/dev/null
sh "$worktree/scripts/build_riceplate_native_deb.sh" \
    "$old_native_target/release/riceplate-native" "$old_native" >/dev/null
new_core="$packages/ricebowl-wayland-core_0.1.0~preview2_all.deb"
new_meta="$packages/ricebowl-wayland-desktop_0.1.0~preview3_amd64.deb"
session="$packages/ricebowl-wayland-session_0.1.0~preview3_all.deb"
native="$packages/ricebowl-riceplate-native_0.1.0~preview2_amd64.deb"
for file in "$old_core" "$old_meta" "$old_native" "$old_session2" \
    "$old_session3" "$new_core" "$new_meta" "$session" "$native"; do
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
check_version "$old_native" ricebowl-riceplate-native '0.1.0~preview1'
check_version "$old_session2" ricebowl-wayland-session '0.1.0~preview2'
check_version "$old_session3" ricebowl-wayland-session '0.1.0~preview3'
check_version "$new_core" ricebowl-wayland-core '0.1.0~preview2'
check_version "$new_meta" ricebowl-wayland-desktop '0.1.0~preview3'
check_version "$native" ricebowl-riceplate-native '0.1.0~preview2'
check_version "$session" ricebowl-wayland-session '0.1.0~preview3'
if cmp -s "$old_native" "$native" || cmp -s "$old_session2" "$old_session3"; then
    echo "Old Native/Session builds unexpectedly identical to newer releases" >&2
    exit 1
fi
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
old_native=/before/ricebowl-riceplate-native_0.1.0~preview1_amd64.deb
old_session2=/before/ricebowl-wayland-session_0.1.0~preview2_all.deb
old_session3=/before/ricebowl-wayland-session_0.1.0~preview3_all.deb
new_core=/after/ricebowl-wayland-core_0.1.0~preview2_all.deb
new_meta=/after/ricebowl-wayland-desktop_0.1.0~preview3_amd64.deb
session=/after/ricebowl-wayland-session_0.1.0~preview3_all.deb
native=/after/ricebowl-riceplate-native_0.1.0~preview2_amd64.deb
version() { dpkg-query -W -f='${Version}' "$1"; }
check_version() { test "$(version "$1")" = "$2"; }
check_user_state() {
    sha256sum -c --status /tmp/ricebowl-user-before.sha256
    test "$(stat -c '%a:%u' /home/owner/.config/ricebowl/recipes/saved.json)" = 600:22001
    test ! -e /usr/bin/ricebowl
}
run_as_owner() {
    runuser -u owner -- env HOME=/home/owner XDG_CONFIG_HOME=/home/owner/.config \
        /usr/bin/ricebowl-wayland-app "$@"
}
assert_review() {
    local file=$1 identifier=$2 schema=$3
    run_as_owner de review --recipe "$file" --json | /usr/bin/python3 -c '
import json, sys
data = json.load(sys.stdin)
assert data["ok"] is True and data["applied"] is False, data
assert data["summary"]["id"] == sys.argv[1], data
assert data["summary"]["schema_version"] == int(sys.argv[2]), data
' "$identifier" "$schema"
}
assert_selected() {
    local identifier=$1
    run_as_owner de recipe-current --json | /usr/bin/python3 -c '
import json, sys
assert json.load(sys.stdin)["active"] == sys.argv[1]
' "$identifier"
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

echo 'PHASE 1a/5: genuine old Core/Native preview1 and Session preview2'
apt-get install -y --no-install-recommends \
    "$old_core" "$old_native" "$old_session2" >/dev/null
check_version ricebowl-wayland-core '0.1.0~preview1'
check_version ricebowl-riceplate-native '0.1.0~preview1'
check_version ricebowl-wayland-session '0.1.0~preview2'
if dpkg-query -W -f='${Status}' ricebowl-wayland-desktop 2>/dev/null | \
        grep -Fxq 'install ok installed'; then
    echo 'Metapackage must not be installed before its minimum session revision' >&2
    exit 1
fi
test ! -e /usr/lib/ricebowl-wayland/BUILDINFO
/usr/bin/ricebowl-wayland-app de --help >/dev/null
mkdir -p /tmp/ricebowl-native-old /tmp/ricebowl-native-new
dpkg-deb -x "$old_native" /tmp/ricebowl-native-old
dpkg-deb -x "$native" /tmp/ricebowl-native-new
sha256sum /tmp/ricebowl-native-old/usr/bin/riceplate-native \
    | cut -d ' ' -f 1 > /tmp/ricebowl-old-native.sha256
sha256sum /tmp/ricebowl-native-new/usr/bin/riceplate-native \
    | cut -d ' ' -f 1 > /tmp/ricebowl-new-native.sha256
if cmp -s /tmp/ricebowl-old-native.sha256 /tmp/ricebowl-new-native.sha256; then
    echo 'Native preview1 and preview2 payloads are indistinguishable' >&2; exit 1
fi
test "$(sha256sum /usr/bin/riceplate-native | cut -d ' ' -f 1)" = \
     "$(cat /tmp/ricebowl-old-native.sha256)"
old_session_payload=$(sha256sum /usr/bin/ricebowl-wayland-session | cut -d ' ' -f 1)
check_user_state

echo 'PHASE 1b/5: real Session preview2 -> preview3, then prior full metapackage'
# Old Meta preview1 genuinely requires Session >=preview3. Upgrade it first,
# rather than forcing an impossible dependency graph or relabeling metadata.
apt-get install -y --no-install-recommends "$old_session3" "$old_meta" >/dev/null
check_version ricebowl-wayland-session '0.1.0~preview3'
check_version ricebowl-wayland-desktop '0.1.0~preview1'
check_version ricebowl-riceplate-native '0.1.0~preview1'
test "$(sha256sum /usr/bin/ricebowl-wayland-session | cut -d ' ' -f 1)" != \
     "$old_session_payload"
test "$(sha256sum /usr/bin/riceplate-native | cut -d ' ' -f 1)" = \
     "$(cat /tmp/ricebowl-old-native.sha256)"
check_user_state

# A genuine schema-v10 rice from the OLD package must remain valid and
# selected across upgrades. Never replace the user's recipe with a fixture.
legacy=/home/owner/.config/ricebowl/recipes/heritage-modern-v10.json
install -m 0600 -o owner -g owner \
    /usr/lib/ricebowl-wayland/examples/wayland/heritage-modern-v10.json "$legacy"
assert_review "$legacy" heritage-modern-v10 10
run_as_owner de recipe-select --recipe heritage-modern-v10 >/dev/null
assert_selected heritage-modern-v10
sha256sum "$legacy" >> /tmp/ricebowl-user-before.sha256
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
assert_review "$legacy" heritage-modern-v10 10
assert_selected heritage-modern-v10
check_user_state

echo 'PHASE 3/5: real upgrade of Core1/Meta1/Native1 -> Core2/Meta3/Native2'
apt-get install -y --no-install-recommends \
    "$new_core" "$new_meta" "$native" "$session" >/dev/null
# Even if a previous and current Session have the same preview3 version,
# explicitly install the final source artifact; Session preview2 ->3 above
# was a real version change, this step binds installed bytes to final source.
dpkg -i "$session" >/dev/null
check_version ricebowl-wayland-core '0.1.0~preview2'
check_version ricebowl-wayland-desktop '0.1.0~preview3'
check_version ricebowl-riceplate-native '0.1.0~preview2'
check_version ricebowl-wayland-session '0.1.0~preview3'
test "$(sha256sum /usr/bin/riceplate-native | cut -d ' ' -f 1)" = \
     "$(cat /tmp/ricebowl-new-native.sha256)"
grep -Fxq 'version=0.1.0~preview2' /usr/lib/ricebowl-wayland/BUILDINFO
test -f /usr/lib/ricebowl-wayland/macrice/de/session.py
test -e /usr/share/wayland-sessions/ricebowl-native.desktop
/usr/bin/ricebowl-wayland-app de --help >/dev/null
assert_review "$legacy" heritage-modern-v10 10
assert_selected heritage-modern-v10
check_user_state

# Test newly-supported v12 Luna alongside the old selected v10 rice. A later
# downgrade must preserve this private file even though its parser rejects it.
luna=/home/owner/.config/ricebowl/recipes/xp-luna-columns.json
install -m 0600 -o owner -g owner \
    /usr/lib/ricebowl-wayland/examples/wayland/xp-luna-columns.json "$luna"
assert_review "$luna" xp-luna-columns 12
run_as_owner de recipe-select --recipe xp-luna-columns >/dev/null
assert_selected xp-luna-columns
sha256sum "$luna" > /tmp/ricebowl-v12-before.sha256
check_user_state

echo 'PHASE 3b/5: power-loss simulation during package configuration, then recovery'
# Disposable-container-only fault injection. The payload is the genuine
# release core package, except this one throwaway variant has a postinst that
# deliberately dies after unpacking. Never publish the faulty archive, never
# run this on the host and never alter user/XFCE canary files.
interruption=$(mktemp -d -t ricebowl-interrupted-dpkg-XXXXXXXX)
dpkg-deb --raw-extract "$new_core" "$interruption/unpacked"
cat > "$interruption/unpacked/DEBIAN/postinst" <<'INTERRUPTED_POSTINST'
#!/bin/sh
set -eu
[ "$1" = configure ] || exit 0
# Simulate abrupt termination of the actual postinst process, not just
# an ordinary nonzero shell exit. This must be observable in dpkg diagnostics.
kill -KILL "$$"
INTERRUPTED_POSTINST
chmod 0755 "$interruption/unpacked/DEBIAN/postinst"
dpkg-deb --build --root-owner-group \
    "$interruption/unpacked" "$interruption/interrupted-core.deb" >/dev/null
if dpkg -i "$interruption/interrupted-core.deb" \
        > /tmp/ricebowl-interrupted.log 2>&1; then
    echo 'Interrupted core unexpectedly configured successfully' >&2
    exit 1
fi
# Do not count a syntax error or an ordinary postinst exit(1) as a
# simulated crash: require dpkg to report a genuine fatal signal.
if ! grep -Eq 'post-installation script.*killed by signal' /tmp/ricebowl-interrupted.log; then
    echo 'Fault injection did not kill the package postinst' >&2
    sed -n '1,35p' /tmp/ricebowl-interrupted.log >&2
    exit 1
fi
# Unlike a corrupt archive rejected before unpack, dpkg must have entered
# a genuinely nonconfigured state. This proves the failing postinst ran.
if dpkg-query -W -f='${Status}' ricebowl-wayland-core | \
        grep -Fxq 'install ok installed'; then
    echo 'Fault injection did not interrupt package configuration' >&2
    exit 1
fi
# The installer can be broken while the user-selected rice and XFCE config
# remain intact. Do not execute an unconfigured package in this state.
sha256sum -c --status /tmp/ricebowl-v12-before.sha256
check_user_state

# Reinstall the exact source-built, original package; do not repair the test
# by deleting user config, purging other desktop packages or replacing XFCE.
dpkg -i "$new_core" >/tmp/ricebowl-interruption-recovery.log 2>&1
apt-get -f install -y --no-install-recommends >/dev/null
test -z "$(dpkg --audit)"
check_version ricebowl-wayland-core '0.1.0~preview2'
check_version ricebowl-wayland-desktop '0.1.0~preview3'
assert_review "$legacy" heritage-modern-v10 10
assert_review "$luna" xp-luna-columns 12
assert_selected xp-luna-columns
sha256sum -c --status /tmp/ricebowl-v12-before.sha256
check_user_state
echo 'PASS: interrupted postinst recovered from genuine core without user/XFCE mutation'

echo 'PHASE 3c/5: kill native and session configuration, repair from original archives'
# Both installed executable and opt-in login entry are individually upgrade-
# critical. Test a real SIGKILL of their maintainer transaction independently,
# then restore the genuine immutable package; do not touch XFCE or owner home.
for component in native session; do
    case "$component" in
        native) authentic="$native"; package=ricebowl-riceplate-native ;;
        session) authentic="$session"; package=ricebowl-wayland-session ;;
    esac
    injected=$(mktemp -d -t "ricebowl-interrupted-${component}-XXXXXXXX")
    dpkg-deb --raw-extract "$authentic" "$injected/unpacked"
    cat > "$injected/unpacked/DEBIAN/postinst" <<'SIGNAL_KILL'
#!/bin/sh
set -eu
[ "$1" = configure ] || exit 0
kill -KILL "$"
SIGNAL_KILL
    chmod 0755 "$injected/unpacked/DEBIAN/postinst"
    dpkg-deb --build --root-owner-group \
        "$injected/unpacked" "$injected/broken.deb" >/dev/null
    if dpkg -i "$injected/broken.deb" >"$injected/dpkg.log" 2>&1; then
        echo "Interrupted $component unexpectedly configured" >&2; exit 1
    fi
    if ! grep -Eq 'post-installation script.*killed by signal' "$injected/dpkg.log"; then
        echo "Failed to reproduce a signal-killed $component postinst" >&2; exit 1
    fi
    if dpkg-query -W -f='${Status}' "$package" | \
            grep -Fxq 'install ok installed'; then
        echo "$component remained configured after injected fatal signal" >&2; exit 1
    fi
    sha256sum -c --status /tmp/ricebowl-v12-before.sha256
    check_user_state
    dpkg -i "$authentic" >/dev/null
    apt-get -f install -y --no-install-recommends >/dev/null
    test -z "$(dpkg --audit)"
    if [ "$component" = native ]; then
        check_version "$package" '0.1.0~preview2'
        test "$(sha256sum /usr/bin/riceplate-native | cut -d ' ' -f 1)" = \
             "$(cat /tmp/ricebowl-new-native.sha256)"
    else
        check_version "$package" '0.1.0~preview3'
    fi
    assert_review "$legacy" heritage-modern-v10 10
    assert_review "$luna" xp-luna-columns 12
    assert_selected xp-luna-columns
    sha256sum -c --status /tmp/ricebowl-v12-before.sha256
    check_user_state
    rm -rf -- "$injected"
done
echo 'PASS: real native and session postinst interruptions repaired without user/XFCE mutation'

echo 'PHASE 4/5: explicit rollback of saved previous Core/Meta/Native'
apt-get install -y --no-install-recommends --allow-downgrades \
    "$old_core" "$old_meta" "$old_native" "$old_session3" >/dev/null
check_version ricebowl-wayland-core '0.1.0~preview1'
check_version ricebowl-wayland-desktop '0.1.0~preview1'
check_version ricebowl-riceplate-native '0.1.0~preview1'
check_version ricebowl-wayland-session '0.1.0~preview3'
test "$(sha256sum /usr/bin/riceplate-native | cut -d ' ' -f 1)" = \
     "$(cat /tmp/ricebowl-old-native.sha256)"
test ! -e /usr/lib/ricebowl-wayland/BUILDINFO
/usr/bin/ricebowl-wayland-app de --help >/dev/null
if run_as_owner de review --recipe "$luna" --json \
    >/tmp/ricebowl-downgraded-v12.json 2>&1; then
    echo 'Old preview incorrectly accepted the schema-v12 Luna recipe' >&2
    exit 1
fi
run_as_owner de recipe-restore >/dev/null
assert_review "$legacy" heritage-modern-v10 10
assert_selected heritage-modern-v10
sha256sum -c --status /tmp/ricebowl-v12-before.sha256
check_user_state

echo 'PHASE 5/5: re-upgrade every component, purge and preserve user data'
apt-get install -y --no-install-recommends \
    "$new_core" "$new_meta" "$native" "$session" >/dev/null
dpkg -i "$session" >/dev/null
check_version ricebowl-wayland-core '0.1.0~preview2'
check_version ricebowl-wayland-desktop '0.1.0~preview3'
check_version ricebowl-riceplate-native '0.1.0~preview2'
check_version ricebowl-wayland-session '0.1.0~preview3'
test "$(sha256sum /usr/bin/riceplate-native | cut -d ' ' -f 1)" = \
     "$(cat /tmp/ricebowl-new-native.sha256)"
assert_review "$legacy" heritage-modern-v10 10
assert_review "$luna" xp-luna-columns 12
run_as_owner de recipe-select --recipe xp-luna-columns >/dev/null
assert_selected xp-luna-columns
sha256sum -c --status /tmp/ricebowl-v12-before.sha256
apt-get purge -y ricebowl-wayland-desktop ricebowl-wayland-core \
    ricebowl-wayland-session ricebowl-riceplate-native >/dev/null
test ! -e /usr/bin/ricebowl-wayland-app
test ! -e /usr/lib/ricebowl-wayland/launcher.py
test ! -e /usr/lib/ricebowl-wayland/BUILDINFO
test ! -e /usr/share/wayland-sessions/ricebowl.desktop
test ! -e /usr/share/wayland-sessions/ricebowl-native.desktop
sha256sum -c --status /tmp/ricebowl-v12-before.sha256
check_user_state
echo 'PASS: real Session2->3 and Native1->2 transitions, core/meta upgrade, signal recovery, rollback, purge, user/XFCE preservation'
IN_CONTAINER
