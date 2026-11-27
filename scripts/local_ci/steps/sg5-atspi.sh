#!/bin/bash
# local-ci step: sg5-atspi
# Mirrors: riceplate-native.yml / native-layer-shell / Verify real input-method-v2 transactions and AT-SPI against native Run
# Local adaptation: PATH prefix is the prebuilt pinned labwc 0.7.2 at /opt/labwc-sg5.
# Only the SG5 E2E uses the private 0.7.2 compositor; all other
# native/XWayland/package tests still exercise Ubuntu's stock labwc.
export PATH="/opt/labwc-sg5:$PATH"
test "$(command -v labwc)" = "/opt/labwc-sg5/labwc"
timeout -k 5s 140s sh scripts/smoke_luna_atspi.sh
