#!/bin/bash
# local-ci step: shell-syntax
# Mirrors: riceplate-native.yml / native-layer-shell / Build and test native RicePlate [harness syntax checks]
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
sh -n scripts/smoke_riceplate_native.sh
sh -n scripts/smoke_sg1_sni_labwc.sh
sh -n scripts/smoke_sg1_window_recovery_labwc.sh
sh -n scripts/smoke_sg1_status_labwc.sh
sh -n scripts/smoke_sg3_ricepop_native_labwc.sh
/usr/bin/python3 -m py_compile scripts/smoke_sg3_ricepop_native_driver.py scripts/gtk_keyboard.py
sh -n scripts/smoke_sg4_creator_full_login_labwc.sh
sh -n scripts/smoke_sg1_interaction_labwc.sh
sh -n scripts/smoke_sg4_imported_rices_labwc.sh
/usr/bin/python3 -m py_compile scripts/sg4_imported_rices_setup.py scripts/sg4_atspi_probe.py
/usr/bin/python3 -m py_compile scripts/fixtures/sg1_sni_provider.py scripts/sg1_notice_probe.py
sh -n scripts/smoke_luna_window_chrome.sh
sh -n scripts/smoke_luna_hotkeys.sh
sh -n scripts/smoke_luna_atspi.sh
/usr/bin/python3 -m py_compile scripts/smoke_riceplate_atspi_client.py
sh -n scripts/wayland_luna_chrome_client.sh
sh -n scripts/smoke_riceplate_windows.sh
sh -n scripts/smoke_riceplate_luna_autohide.sh
sh -n scripts/wayland_xwayland_smoke_client.sh
sh -n scripts/smoke_wayland_clipboard.sh
sh -n scripts/wayland_clipboard_smoke_client.sh
sh -n scripts/smoke_riceplate_multioutput.sh
sh -n scripts/smoke_wayland_shared_rice_engine.sh
