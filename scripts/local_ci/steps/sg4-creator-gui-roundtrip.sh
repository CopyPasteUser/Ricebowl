#!/bin/bash
# local-ci step: sg4-creator-gui-roundtrip
# Mirrors: riceplate-native.yml / native-layer-shell / Prove the real GTK Creator export/import and install/apply/restore dialogs against a supervised session under labwc
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
timeout -k 5s 900s sh scripts/smoke_sg4_creator_gui_roundtrip_labwc.sh
# Second workflow step of this local step: the same Creator against a full (non-nested) login session.
timeout -k 5s 900s sh scripts/smoke_sg4_creator_full_login_labwc.sh
