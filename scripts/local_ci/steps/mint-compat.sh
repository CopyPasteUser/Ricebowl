#!/bin/bash
# local-ci step: mint-compat
# Mirrors: riceplate-native.yml / sg6-mint221-compat / Install and recover four exact-source packages in isolated Mint 22.1
# Local adaptation: uses the packages produced by the pkg-* steps in the same clone instead of a downloaded artifact
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
set -euo pipefail
test "$(git rev-parse HEAD)" = "$GITHUB_SHA"
(cd dist/riceplate-native-preview && sha256sum -c SHA256SUMS)
/usr/bin/python3 -m unittest tests.test_sg6_mint_compat -v
sh -n scripts/smoke_wayland_mint_compat.sh
# Resolve the mutable Docker Hub tag once, record the immutable
# digest, then execute ONLY that downloaded digest. Nothing is
# installed on the Ubuntu runner or the user's desktop.
# Local adaptation: a registry refusal (e.g. Docker Hub 429 rate limit) falls
# back to the already-pulled local image, whose digest is still pinned and
# logged below; with no local image the step is BLOCKED, never faked.
if ! docker pull linuxmintd/mint22.1-amd64:latest; then
  if docker image inspect linuxmintd/mint22.1-amd64:latest >/dev/null 2>&1; then
    echo "LOCAL_CI_NOTE: registry pull failed; using the cached local image"
  else
    echo "LOCAL_CI_BLOCKED: Mint 22.1 image unavailable (registry pull failed, no cached image)"
    exit 77
  fi
fi
image=$(docker image inspect --format '{{index .RepoDigests 0}}' linuxmintd/mint22.1-amd64:latest)
case "$image" in
  linuxmintd/mint22.1-amd64@sha256:*|docker.io/linuxmintd/mint22.1-amd64@sha256:*) ;;
  *) echo "Unexpected Mint image identity: $image" >&2; exit 1 ;;
esac
printf 'Mint build-root digest: %s\n' "$image"
docker run --rm --pull=never \
  --volume "$PWD/dist/riceplate-native-preview:/packages:ro" \
  --volume "$PWD/scripts/smoke_wayland_mint_compat.sh:/tests/mint-compat.sh:ro" \
  --env RICEBOWL_SOURCE_SHA="$GITHUB_SHA" \
  "$image" sh /tests/mint-compat.sh
