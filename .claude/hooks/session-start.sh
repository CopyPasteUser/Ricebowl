#!/bin/bash
# Claude Code cloud sessions only: provision RiceBowl local-CI tooling.
# Never runs on a developer machine (no CLAUDE_CODE_REMOTE) or as non-root.
set -euo pipefail
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ] || [ "$(id -u)" -ne 0 ]; then
  exit 0
fi
cd "${CLAUDE_PROJECT_DIR:-.}"
# scripts/local_ci/steps/pkg-upgrade-rollback.sh needs two pinned historical
# baselines; the session checkout is shallow, so keep them under local refs.
for sha in b3d615a7cc508049050eb06c7952ef5a8d26e598 c8274dee78386124470cb5ff9a4d2768bb019126; do
  if ! git cat-file -e "$sha^{commit}" 2>/dev/null; then
    git fetch -q --no-tags origin "$sha" >&2 || echo "session-start: could not fetch baseline $sha" >&2
  fi
  if git cat-file -e "$sha^{commit}" 2>/dev/null; then
    git update-ref "refs/ci-baseline/${sha:0:7}" "$sha"
  fi
done
# Skip when this hook and the provision script are unchanged since the last
# successful run in this container (the hash file lives in the container).
hashes=/var/cache/ricebowl-local-ci/.session-start.sha256
if sha256sum --check --status "$hashes" 2>/dev/null \
    && [ -x /opt/labwc-sg5/labwc ] && [ -x /usr/local/bin/rb-run ] && id rbdev >/dev/null 2>&1; then
  if command -v dockerd >/dev/null && ! docker info >/dev/null 2>&1; then
    nohup dockerd >/var/log/rb-dockerd.log 2>&1 &
  fi
  exit 0
fi
rm -f "$hashes"
bash scripts/local_ci/provision.sh >&2
mkdir -p "$(dirname "$hashes")"
sha256sum "$PWD/.claude/hooks/session-start.sh" "$PWD/scripts/local_ci/provision.sh" > "$hashes"
