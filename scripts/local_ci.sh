#!/bin/sh
# RiceBowl local CI: clone one exact SHA, run every translated hosted-CI step
# as the unprivileged `rbdev` user and write a local CI receipt.
# See docs/evidence/local-ci/README.md.  Usage:
#   scripts/local_ci.sh [--sha SHA] [--repo PATH|URL] [--steps IDS|@tag] [--list] [--out DIR]
# Never run by hosted Actions; never touches the working tree it is started from
# except for writing the receipt under docs/evidence/local-ci/.
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
python=/usr/bin/python3
[ -x "$python" ] || python=$(command -v python3)
export LANG=C.UTF-8 LC_ALL=C.UTF-8
exec "$python" "$here/local_ci.py" "$@"
