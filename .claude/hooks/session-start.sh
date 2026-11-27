#!/bin/bash
# Claude Code cloud sessions only: provision RiceBowl local-CI tooling.
# Never runs on a developer machine (no CLAUDE_CODE_REMOTE) or as non-root.
set -euo pipefail
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ] || [ "$(id -u)" -ne 0 ]; then
  exit 0
fi
cd "${CLAUDE_PROJECT_DIR:-.}"
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
