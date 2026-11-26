# SG2 adapter state inventory (WP2.1)

Snapshot: `8f1398c` (read-only audit of existing tests; verified by grep). **Closes nothing**: it does
not check any #417 SG2 box, change coverage counts or replace the ledger in
[sg1-sg7-evidence-progress.md](sg1-sg7-evidence-progress.md). Fake-provider unit tests are not
real D-Bus/compositor acceptance. Scope: RiceSpice GUI adapters (notifications/RicePop = SG3, excluded).

Legend: `ok` covered by a cited test; `~` partial (see id); `gap` no test found; `n/a` not applicable.
Columns: **RB** verified readback after write; **AUTH** polkit/NotAuthorized denial surfaced;
**PROV** provider missing/disconnected/unavailable; **BUSY** stale/concurrent/busy request;
**RBK** rollback, or explicit no-rollback-by-design; **GUI** rendered widget state (not backend only).
Note: `_timedatectl`/`nmcli` refusals whose stderr carries a recognized polkit/NetworkManager marker
(`macrice/authorization.py`) now raise the typed `SettingsDenied` (one fixed message, no raw stderr) from the
first mutating call only; every other non-zero exit, and any denial text seen on a read-back after a write,
stays a generic fail-closed `SettingsError`. AUTH is `ok` only where a denial is exercised (DN/DT below).
Still `gap`: N5 enterprise create (`con add` is classified but untested) and the enterprise-connect denial
with real polkit text (SP1 exits 4 with no stderr, so it remains the generic "outcome unknown" path).

## Matrix

| Action | RB | AUTH | PROV | BUSY | RBK | GUI |
|---|---|---|---|---|---|---|
| N1 Wi-Fi radio on/off | ok S1 | ok DN1 | ~ U1 | ok S1,BZ1 | n/a no replay (U1) | gap |
| N2 Join visible open Wi-Fi | ok S2 | ok DN3 | ok W6 | ok W4,BZ1 | n/a no undo | ok G5 |
| N3 Join secured Wi-Fi (passphrase) | ok S2,S3 | ok DN3 | ok W6 | ok W4 | n/a no undo | ok G5 |
| N4 Saved profile activate/deactivate | ok NR1,NI1 | ok DN2 | ok NR2,NI2 | ok NR4 | n/a no replay (NR4) | gap |
| N5 Enterprise Wi-Fi create | ok EI2 | gap | ok EI5,EI6 | ~ EI2 | n/a single write | gap |
| N6 Enterprise connect (password) | ok EI1 | ~ SP1 (generic exit 4, not typed) | ok EI4 | ok EI2,EI3 | n/a single shot | gap |
| N7 VPN import (OpenVPN/WireGuard) | ok NE1 | ok DN4 | ok NE2 | ok NE3 | ~ NE4 (report only) | gap |
| N8 Wi-Fi scan/refresh (read) | n/a read-only | n/a read-only | ok S14,S19 | ok W7 | n/a read-only | gap |
| A1 Default sink/source | ok AD1,AI1 | n/a user-level pactl | ok AD2 | ok AD3,AJ3 | n/a reports (AD4) | gap |
| A2 Move app stream to output | ok AD5 | n/a user-level pactl | ok AD6,AD9 | ok AD7,AI3 | n/a no replay (AJ2) | ~ AD8 |
| A3 Per-app volume | ok AD5 | n/a user-level pactl | ok AD9 | ok AD7,AJ2 | n/a no replay (AJ2) | ~ AD8 |
| A4 Per-app mute | ok AD5 | n/a user-level pactl | ok AD9 | ok AD7 | n/a no replay (AJ2) | ~ AD8 |
| A5 MPRIS player control | gap | n/a user session | ok G4 | n/a stateless command | n/a no state | ok G4 |
| B1 Bluetooth power | ok S5,BS1 | gap | ok BD1,U2 | ok S5,S23,BS3 | n/a no undo (U2) | ~ S18 |
| B2 Bluetooth connect/disconnect | ok S6,BS4 | gap | ok S7,U3 | ok S17,S21 | n/a no undo (U3) | ~ S18 |
| B3 Bluetooth scan (backend only) | n/a bounded session | gap | ok BD3 | ok BD4 | ok BD2 | n/a no GUI |
| B4 Bluetooth pair (backend only) | ~ BD6 | gap | ok BD5 | ok BD5 | n/a no undo | n/a no GUI |
| P1 Power profile | ok S8,G3 | gap | ok S9,S10 | ok S8 | n/a no replay (U4) | ~ G3 |
| P2 Lock screen | ~ S15 | n/a user session | ok S16 | gap | n/a no state | gap |
| P3 Suspend | n/a no readback | gap | ok S16,S20 | gap | n/a no undo | gap |
| T1 Timezone | ok S11,TD3 | ok DT1 | ok TD3 | ok S11 | n/a no replay (TD3) | ok G6 |
| T2 NTP toggle | ok S12,TD2 | ok DT1 | ok TD2 | ok TD7 | n/a no replay (TD1) | gap |
| T3 Manual clock | ok S13,TD5 | ok DT1 | ok TD6 | ok TD5 | n/a no replay (TD4) | gap |
| D1 Display mode/scale/position trial | ok WM3 | n/a compositor-owned | ok WM1,WM6 | ok WM4,DG5 | ok WM2,WM5,DG2 | ~ G2 |
| D2 Keep / confirm display change | ok DJ1,WM3 | n/a compositor-owned | ok DG3 | ok DG4 | ok DG2,DG3 | ok G2 |
| D3 Save/forget monitor preset | ok RP6,MP1 | n/a user file | ok MP1 | ok RP6 | ok MP1 | gap |
| D4 Try saved full layout | ok DR3 | n/a compositor-owned | ok DR5 | ok DR4 | ok DR1,DR2 | ~ G2 |
| D5 Next-login monitor trial toggle | ok DR6 | n/a user file | ok DR7 | ok DR6 | n/a opt-in flag | gap |
| I1 Input prefs (pointer/keyboard, next login) | ok RP1,RP3 | n/a user file | ok RP2 | ok RP1 | ok PD2,PD3 | gap |
| I2 Accessibility prefs (cursor/GTK/contrast) | ok RP4 | n/a user file | ok RP2 | ok RP1 | ok PD2,PD3 | gap |
| I3 Orca on login | ~ RP5 | n/a user file | gap | ok RP1 | n/a next login only | gap |

## Evidence index

Paths are `tests/<file>::<Class>::<test>`; abbreviations below expand `<file>::<Class>` once per group.

- **S** `test_de_settings.py::RiceSpiceSettingsTests::` S1 `test_wifi_change_guards_stale_state_and_verifies_postcondition`, S2 `test_connect_wifi_requires_fresh_visible_selection_and_readback`, S3 `test_wpa_password_stays_with_stdin_adapter_and_rejects_unsupported_networks`, S5 `test_bluetooth_power_has_concurrency_guard_and_postcondition`, S6 `test_bluetooth_connection_uses_reviewed_adapter_and_verifies_postcondition`, S7 `test_bluez_postwrite_provider_loss_never_claims_definite_failure`, S8 `test_power_profile_change_requires_fresh_supported_state_and_readback`, S9 `test_power_provider_loss_is_typed_and_never_claims_success`, S10 `test_power_snapshot_shows_real_battery_and_missing_profile_service`, S11 `test_timezone_inventory_and_guarded_polkit_change`, S12 `test_ntp_is_explicit_system_wide_and_verified`, S13 `test_manual_system_clock_is_guarded_and_readback_verified`, S14 `test_wifi_scan_provider_loss_is_typed_and_not_a_false_empty_scan`, S15 `test_suspend_locks_before_requesting_logind_and_lock_reports_success`, S16 `test_suspend_refuses_failed_or_unavailable_screen_lock`, S17 `test_stale_bluetooth_adapter_from_ui_never_calls_bluez`, S18 `test_bluetooth_ui_buttons_pass_original_adapter_instead_of_current_guess` (mock UI callbacks, not rendered state), S19 `test_wifi_scan_real_adapter_distinguishes_outage_from_no_access_points`, S20 `test_suspend_refused_in_nested_preview_without_command`, S21 `test_bluetooth_unpaired_or_stale_devices_are_not_mutated`, S23 `test_bluetooth_power_cannot_report_success_for_replaced_adapter`
- **U** `test_de_settings_provider_uncertainty.py::DeviceMutationUncertaintyTests::` U1 `test_wifi_radio_write_timeout_is_indeterminate_and_not_replayed`, U2 `test_bluetooth_adapter_write_reply_loss_is_indeterminate`, U3 `test_bluetooth_device_write_reply_loss_is_indeterminate`, U4 `test_power_profile_write_reply_loss_is_indeterminate`
- **TD** `test_de_timedated_unknown_outcome.py::TimedatedUnknownOutcomeTests::` TD1 `test_ntp_timeout_after_preflight_is_indeterminate_and_not_retried`, TD2 `test_ntp_post_write_provider_loss_and_capability_change_fail_closed`, TD3 `test_timezone_timeout_and_readback_loss_do_not_repeat_mutation`, TD4 `test_manual_clock_timeout_remains_indeterminate_without_second_write`, TD5 `test_manual_clock_rejects_ntp_reenabled_after_write_without_retry`, TD6 `test_manual_clock_post_write_ntp_provider_loss_is_indeterminate`, TD7 `test_ntp_noop_and_stale_state_remain_write_free`
- **NR** `test_de_sg2_nm_profile_readback.py::NetworkProfileReadbackTests::` NR1 `test_success_needs_independent_provider_confirmation`, NR2 `test_lost_readback_is_uncertain_and_never_replayed`, NR4 `test_failed_write_and_stale_precondition_never_retry`
- **NI** `test_de_sg2_provider_identity.py::NetworkProfileIdentityTests::` NI1 `test_same_uuid_same_type_but_new_label_never_certifies_activation`, NI2 `test_stale_profile_or_readback_loss_is_not_a_retry_authorization`
- **EI** `test_de_sg2_provider_identity.py::EnterpriseEnrollmentIdentityTests::` EI1 `test_positive_requires_verified_profile_and_policy`, EI2 `test_post_write_stale_object_and_security_changes_fail_closed`, EI3 `test_timeout_after_write_is_unknown_and_single_shot`, EI4 `test_readback_provider_disconnect_is_indeterminate`, EI5 `test_enterprise_create_inventory_disappears_after_single_write`, EI6 `test_enterprise_create_lost_reply_never_suggests_safe_retry`
- **AI** `test_de_sg2_provider_identity.py::AudioDefaultIdentityTests::` AI1 `test_same_device_index_readback_succeeds_for_both_kinds`, AI3 `test_stream_move_rejects_replaced_output_with_recycled_index`
- **DT** `test_de_sg2_authorization_denial.py::TimedatedDenialTests::` DT1 `test_td_deny_ntp_timezone_and_clock_are_typed_and_not_replayed`, plus `test_td_generic_failures_stay_unknown_outcome_not_denial`, `test_td_exit_zero_with_refusal_text_is_never_success_or_denial`, `test_td_denial_during_post_write_readback_is_indeterminate_not_denied`, `test_td_unknown_or_empty_stderr_never_classifies_as_denial`, `test_td_success_still_verified_by_independent_readback` (fake private `timedatectl`)
- **DN** `test_de_sg2_authorization_denial.py::NetworkManagerDenialTests::` DN1 `test_nm_deny_wifi_radio_toggle`, DN2 `test_nm_deny_saved_profile_activation`, DN3 `test_nm_deny_wifi_join_open_and_secured`, DN4 `test_nm_deny_vpn_import`, plus `test_nm_marker_variants_all_typed_denials`, `test_nm_generic_failures_stay_unknown_outcome_not_denial`, `test_nm_vpn_import_generic_failure_and_success_controls`, `test_nm_success_controls_claim_only_after_readback`, `test_nm_join_success_control_requires_connected_readback`, `test_nm_denial_text_on_readback_after_write_is_indeterminate`; wording: `DenialWordingTests` and `test_de_settings_busy.py::RiceSpiceBusyActionTests::test_polkit_denial_and_generic_failure_have_distinct_visible_wording`
- **SP1** `test_de_sg2_provider_subprocess.py::EnterpriseSubprocessBoundaryTests::test_real_adapter_to_private_nmcli_success_and_denial` (fake private `nmcli` binary; only real denial case)
- **NE** `test_de_network_enrollment.py::NetworkEnrollmentTests::` NE1 `test_vpn_import_verifies_single_new_profile_and_disables_autoconnect`, NE2 `test_vpn_import_transport_loss_is_never_treated_as_safe_retry`, NE3 `test_vpn_import_rejects_wrong_type_and_concurrent_addition`, NE4 `test_vpn_import_reports_indeterminate_post_import_mutations`
- **W** `test_de_wifi_security_identity.py::WiFiIdentityGuardTests::` W4 `test_changed_or_disappeared_security_never_starts_join`, W6 `test_live_scan_provider_loss_remains_an_error_not_empty_or_safe`, W7 `test_ordinary_list_never_triggers_second_scan_or_mutation`
- **AD** `test_de_audio_devices.py::AudioDeviceTests::` AD1 `test_switch_one_validated_sink_and_verify_actual_default`, AD2 `test_default_readback_rejects_unplugged_output_even_when_server_echoes_name`, AD3 `test_noop_does_not_mutate_and_conflict_fails_before_switch`, AD4 `test_failed_verification_reports_possible_active_mutation`, AD5 `test_application_stream_routing_volume_and_mute_are_verified`, AD6 `test_stream_move_rejects_output_removed_before_provider_readback`, AD7 `test_recycled_stream_index_never_controls_a_different_audio_client`, AD8 `test_ricespice_stream_buttons_pass_displayed_client_identity` (callback identity, not rendered state), AD9 `test_application_streams_reject_malformed_and_unavailable`
- **AJ** `test_de_audio_json_identity.py::AudioJSONIdentityTests::` AJ2 `test_stream_write_timeout_does_not_repeat_or_claim_unchanged`, AJ3 `test_ambiguous_default_device_blocks_write_before_any_pactl_mutation`
- **BD** `test_bluetooth_dbus.py::BluetoothDbusTests::` BD1 `test_no_adapter_is_not_powered_off`, BD2 `test_scan_is_explicit_bounded_and_always_stopped`, BD3 `test_scan_never_starts_without_power`, BD4 `test_only_one_discovery_session_per_process`, BD5 `test_pair_rejects_missing_adapter_and_duplicate_same_adapter`, BD6 `test_pair_legacy_unique_device_and_idempotent_paired_state`
- **BS** `test_bluetooth_single_mutation.py::BluetoothSingleMutationTests::` BS1 `test_successful_cli_power_with_stale_cli_readback_uses_dbus_read_only`, BS3 `test_timeout_must_not_fall_back_to_second_mutation`, BS4 `test_successful_cli_connection_with_stale_cli_readback_is_read_only`
- **G** `test_de_settings_gui.py::SettingsGuiTests::` G2 `test_login_monitor_confirmation_is_visible_and_explicit`, G3 `test_power_page_offers_only_actual_profiles_and_applies_explicit_selection`, G4 `test_audio_page_controls_real_mpris_players_and_degrades_independently`, G5 `test_network_page_connects_selected_visible_wifi_without_password_leaks`, G6 `test_timezone_search_uses_supported_system_list_and_explicit_apply` (GTK tests skip without typelib/display)
- **BZ1** `test_de_settings_busy.py::RiceSpiceBusyActionTests::test_busy_click_explains_retry_without_delayed_unsafe_replay` (generic, all actions)
- **DG** `test_display_guard.py::GuardTests::` DG2 `test_unconfirmed_monitor_change_reverts_old_mode_and_position`, DG3 `test_rollback_failure_is_reported_not_claimed_successful`, DG4 `test_confirmation_arriving_after_deadline_does_not_skip_rollback`, DG5 `test_validation_refuses_disconnected_outputs_unlisted_modes_and_bad_coordinates`
- **DR** `test_de_display_restore.py::DisplayRestoreTests::` DR1 `test_independent_guard_rolls_back_both_outputs_at_timeout`, DR2 `test_guard_rolls_back_after_partial_second_output_failure`, DR3 `test_confirmed_full_layout_is_kept_and_sends_one_refresh`, DR4 `test_worker_rejects_stale_output_before_any_mutation`, DR5 `test_begin_never_starts_without_full_session_or_fresh_saved_data`, DR6 `test_explicit_login_trial_opt_in_migrates_v1_and_resets_on_layout_changes`, DR7 `test_session_autotrial_is_full_session_only_and_requires_gui`
- **DJ1** `test_de_display_request_json.py::DisplayTransactionJSONTests::test_confirmation_marker_must_be_exact_owner_private_true`
- **WM** `test_de_ricespice_native.py::WaylandMonitorTests::` WM1 `test_outside_ricebowl_no_monitor_query_or_write`, WM2 `test_worker_times_out_and_restores_original_mode`, WM3 `test_confirmation_keeps_trial_without_rollback`, WM4 `test_worker_rejects_stale_topology_before_changing_output`, WM5 `test_position_change_rolls_back_if_not_confirmed`, WM6 `test_rejects_incomplete_inventory_and_injection`
- **RP** `test_de_ricespice_native.py::RiceSpicePreferenceTests::` RP1 `test_private_save_roundtrip_and_stale_write`, RP2 `test_malformed_and_unsafe_file_never_changes_session`, RP3 `test_private_labwc_xml_and_session_environment`, RP4 `test_accessibility_only_does_not_change_keyboard_or_pointer`, RP5 `test_orca_preference_only_enters_full_session_environment`, RP6 `test_monitor_presets_are_private_and_stale_safe`
- **PD** `test_de_preferences_durability.py::RiceSpicePreferencesDurabilityTests::` PD2 `test_rename_failure_keeps_old_value_without_staging_files`, PD3 `test_failed_directory_sync_is_not_success_or_implicit_rollback`
- **MP1** `test_de_display_preset_durability.py::MonitorPresetDurabilityTests::test_failed_rename_keeps_existing_private_preset_and_cleans_temp`

## Top gaps (ranked by user impact/safety)

1. ~~**Polkit/NotAuthorized denial for timezone, NTP, clock** (T1-T3)~~ **Closed at the adapter level (DT1)**: typed `SettingsDenied`, shown by the GUI as the same wording as NetworkManager. Remaining: GUI widget state after denial and a disposable system-bus polkit denial. Original gap: `_timedatectl` returned one generic "denied" error for any non-zero exit. Add a fake-`timedatectl` subprocess test (pattern of SP1) exiting 1 with an "Access denied" stderr, asserting a typed, non-retrying message and an untouched GUI state; then a disposable system-bus polkit denial.
2. **GUI never driven for NTP/clock/saved-profile/Bluetooth/Wi-Fi radio** (N1, N4, B1, B2, T2, T3): only callback or backend tests exist. Add headless GTK tests (pattern of G3/G6) that click the button and assert the label/sensitivity after success, indeterminate and unavailable outcomes.
3. ~~**NetworkManager authorization denial on Wi-Fi radio, join, saved profile and VPN import** (N1-N4, N7)~~ **Closed at the adapter level (DN1-DN4)** with the private-`nmcli` harness; real-polkit denial text from a live NetworkManager is still unverified. Original gap: only the enterprise-connect denial (SP1) existed. Extend the private-`nmcli` subprocess harness with `deny` for `radio wifi`, `connection up` and `connection import`, asserting error class, no replay and no credential leak.
4. **Bluetooth power/connect denial and radio-rfkill block** (B1, B2): add fake-BlueZ D-Bus tests (disposable bus) returning `org.bluez.Error.NotAuthorized` and `Failed` rfkill-blocked, asserting typed errors and no fallback second mutation (BS3 pattern).
5. **Suspend/lock GUI and logind denial** (P2, P3): no GUI test for the confirm dialog or the busy path; add a fake-`loginctl`/logind refusal unit test plus a headless GUI test that the dialog cancels cleanly and failure text is visible.
6. **Display preset forget/save and next-login trial toggle GUI** (D3, D5): add headless GUI tests for these buttons asserting visible state after stale-preset and write-failure paths (G2 pattern).
7. **Input/accessibility GUI, Orca provider missing** (I1-I3): add a headless GTK test that saves preferences, shows the next-login-only notice and surfaces `PreferenceError`; add a unit test that `orca` absent yields an honest "not installed/unavailable" status instead of a silent enable.
8. **Wi-Fi scan error/empty rendering** (N8): add a headless GUI test with `wifi_snapshot` raising `SettingsError` asserting an error label (not an empty list), mirroring the audio unavailable test in G4.
9. **VPN import and enterprise Wi-Fi dialogs in GUI** (N5-N7): add a headless GUI test driving `_import_vpn`/`_new_enterprise_wifi` with fake file chooser and adapter outcomes (verified, indeterminate, concurrent addition) asserting visible messages.
10. **MPRIS readback and Bluetooth pair surface** (A5, B4): add a fake-bus test that a `PlayPause` to a vanished player reports unavailable; decide whether pair gets a GUI action, otherwise record it as intentionally backend-only.
