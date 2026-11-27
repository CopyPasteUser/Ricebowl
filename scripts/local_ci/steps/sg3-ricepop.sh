#!/bin/bash
# local-ci step: sg3-ricepop
# Mirrors: riceplate-native.yml / native-layer-shell / Prove native RicePop inbox against real Mako 1.11 under labwc
# Local adaptation: source-locked Mako 1.11 comes from the local-ci cache (mako-build)
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
export PATH="$LCI_MAKO_BUILD:$PATH"
for mode in luna luna-de luna-nofonts chrome; do
  timeout -k 5s 200s sh scripts/smoke_sg3_ricepop_native_labwc.sh "$mode"
done
