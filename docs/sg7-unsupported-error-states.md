# Unsupported, denied, unavailable and error states (SG7 / WP7.3)

Snapshot: 26 November 2026, reviewed by grep of source and tests (not by running
every test). This is a **review list, not acceptance**: it closes no #417 box,
changes no coverage count and is fake-provider / unit evidence unless a row says
otherwise. Hardware, real polkit text and exact-head CI remain open in
[RELEASE_1_0_GATES.md](../RELEASE_1_0_GATES.md) and
[sg-remaining-work-packages.md](sg-remaining-work-packages.md).

How to read a row: **State** is what can go wrong, **Surfaced as** is what the
user (or the machine-readable CLI/health JSON) sees, **Proof** is the source plus
the test that exercises it. `unverified` means the behavior is in source but no
test was found; treat it as a to-do, not as accepted.

Paths: `tests/…` are Python `unittest` modules; `rs:` entries are Rust unit tests
under `components/riceplate-wayland/src/` (need `cargo`, run in the native CI job).

## RicePlate panels (native Rust shell)

| State | Surfaced as | Proof |
|---|---|---|
| Wi-Fi/network/audio/Bluetooth provider missing or unparseable | `N/A` label, never a guessed state; controls for that capability are disabled | `system_status.rs` (`Unavailable`, `enabled_for`); rs: `network_cli_states_do_not_fabricate_internet_connectivity`, `radio_capability_is_independent_from_connectivity_and_readback_is_verified`, `bluetooth_requires_explicit_controller_readback_and_verified_transition` |
| Radio/volume write fails or readback differs | Control shows *failed* (accessible label "failed"), then *pending/unavailable* are distinct | `main.rs` `failed_control_note`; rs: `luna_status_menu_shows_shared_failed_pending_and_unavailable_feedback`, `declarative_controls_render_unavailable_live_pending_and_failed_states`, `native_menu_pixels_follow_shared_control_worker_and_failure_state` |
| Hardware worker gone | Controls revoked (greyed); a merely full queue is not treated as dead | rs: `disconnected_hardware_worker_revokes_controls_but_full_queue_does_not`, `panel_paint_disables_controls_when_the_worker_is_missing` |
| Volume OSD with no audio provider / failed change | OSD "Unavailable" (German "Nicht verfügbar"); failure replaces the notice and resets expiry; no OSD for startup/error noise | `osd.rs`; rs: `repeated_mute_and_failure_replaces_notice_and_resets_expiry`, `external_audio_changes_show_once_without_startup_or_error_noise`, `german_osd_uses_real_readback_and_preserves_failure_and_expiry_states` |
| No battery / disconnected supply | No fabricated charge; battery item absent / `NotPresent` | `power.rs`; rs: `reads_real_kernel_contract_without_assuming_battery_exists`, `disconnected_supply_and_invalid_root_do_not_fabricate_charge` |
| Tray (SNI) bus missing / provider disconnects | Bounded retry without spinning; Luna tray icon shows a *disconnected* badge | rs (`sni_recovery.rs`): `missing_bus_retries_only_after_bounded_delay_and_never_spins`, `hot_disconnect_defers_reconnection_until_prior_deadline`; rs (`panel_chrome.rs`): `luna_tray_icons_are_distinct_and_expose_a_disconnected_badge` |
| Tray menu refused / provider changed menu | Previous provider actions revoked; stale hover/AT-SPI actions rejected; disabled parent closes submenu | rs (`tray.rs`): `refused_remote_reopen_revokes_previous_provider_actions`, `remote_menu_rejects_stale_off_page_accessibility_and_hover_actions`, `disabling_open_parent_closes_submenu_and_blocks_stale_child_dispatch` |
| Compositor refuses minimize/restore/close | Pending intent expires on next input (no polling); stale proxy ids dropped on manager reset | rs (`window_lifecycle.rs`): `refused_request_expires_on_input_without_polling`, `manager_reset_discards_all_stale_proxy_ids`, `closing_or_restarting_registry_drops_stale_intent` |
| Output unplugged | Start menu, tray popup and calendar hosted on the removed output are closed (a host that cannot be resolved fails closed); the same surfaces on a surviving output stay open; the Run dialog is re-homed by labwc and stays visible. Panel/desktop state falls back to the primary output without losing position; independent per-surface lost-output state | rs: `output_disconnection_falls_back_to_primary_without_losing_position` (`desktop_layout/file_state.rs`), `independent_surfaces_and_lost_output_have_independent_state` (`frame_scheduler.rs`); local compositor receipts: `smoke_sg1_interaction_labwc.sh` stage `outputs` (scale change, hot-unplug, hot-add, calendar, desktop context menu, Run dialog) |
| Glyph/script not covered by any font | Visible replacement glyph per grapheme, never blank; font probe never claims coverage | rs: `unsupported_glyphs_have_visible_bitmap_fallback_and_clipping` (`text_render.rs`), `missing_script_glyphs_paint_one_visible_replacement_per_grapheme` (`style_art.rs`), `script_font_probe_never_reports_coverage_for_missing_or_noncovering_fonts` (`native_shaping.rs`); local receipt: SG3 smoke Tifinagh step (`scripts/smoke_sg3_ricepop_native_labwc.sh`, not yet run in CI) |
| Rice recipe from an older/unsupported schema or with extra/executable keys | Rejected at validation; panel does not start from it | rs: `v12_luna_styles_are_data_driven_and_legacy_versions_fail_closed` (`recipe.rs`); py: `tests/test_de_recipes.py::test_schema_rejects_unsupported_executable_or_extra_keys` |

## RicePlate launcher / Start menu

| State | Surfaced as | Proof |
|---|---|---|
| App launch helper fails to spawn or exits non-zero | Reported as a failed launch and withdrawn from *recent apps* only; the Start menu has already closed, so it is also shown on the shared transient notice surface ("Application: Could not start", pixels plus an AT-SPI alert, about 4 s or Escape from the focused panel; generic text, never a path, argv or app name) | rs: `failed_app_launch_helper_is_reported_and_successful_one_is_not` (`main.rs`), `failed_spawn_never_creates_false_busy_state` (`external_launcher.rs`), `failed_launch_is_withdrawn_from_recent_apps_only` (`native_menu.rs`), `failure_notices_are_generic_alerts_with_a_bounded_lifetime`, `escape_dismisses_only_a_failure_notice` (`osd.rs`); local compositor receipt: `smoke_sg1_interaction_labwc.sh` stage `notices` |
| External launcher (Chrome Fuzzel) cannot start | "Launcher: Not available" notice; never shown as busy, a repeat click retries | local compositor receipt: stage `notices` (Chrome, Fuzzel absent from `PATH`); `smoke_riceplate_native.sh` |
| Settings / terminal / lock helper cannot start or exits non-zero soon after start | "Settings: Could not open" / "Command: Could not run" notice; a helper still running after 5 s is handed to the silent reaper (no polling for a long-lived window) | rs: `failed_watched_helper_is_reported_once_and_successful_or_running_ones_are_not`, `a_finite_watched_operation_stays_watched_however_long_it_runs` (`main.rs`); local compositor receipt: stage `notices` (Luna clock menu: absent, failing) |
| Tray provider fails an Activate/ContextMenu/menu click the user just made | "Tray: App did not respond" notice; background property/layout errors stay log-only | local compositor receipt: stage `notices` (Luna and Chrome, `item-error` fixture mode) |
| Notice surface unavailable (nested design preview without the OSD layer) | Nothing is painted or exposed to AT-SPI; the failure stays a log line | n/a: nested previews are not a desktop session |
| Stale catalog index after a refresh | Never dispatches a different app | rs: `refreshed_program_catalog_never_dispatches_another_app_by_stale_index` (`native_menu.rs`) |
| Malformed/foreign pins and recents (traversal, symlink, FIFO, other rice) | Rejected whole; history untouched | rs: `refuses_cross_rice_unknown_duplicate_and_traversal` (`menu_pins.rs`), `invalid_history_is_rejected_without_partial_use`, `named_pipe_is_rejected_without_blocking` (`menu_recents.rs`) |
| Malformed `.desktop` localization | Falls back without rendering control characters | rs: `malformed_localization_falls_back_without_rendering_controls` (`installed_apps.rs`) |
| Hidden/missing default apps in the Luna menu | Not shown; no dead entries | rs: `luna_preview_never_uses_hidden_or_missing_default_app_ids` (`native_menu.rs`) |
| Run dialog input too large/invalid paste | Rejected, selection unchanged; arguments passed literally (no shell) | rs: `paste_rejects_invalid_or_oversize_transfers_without_changing_selection`, `quoted_args_are_passed_literally_without_shell` (`luna_dialog.rs`) |
| Typed system action the host cannot do (`lock`: `swaylock` absent, or a nested preview) | The menu/panel entry is always offered; it runs `ricebowl de lock`, which refuses with a reason on stderr and exits non-zero, and RicePlate then shows the generic "Command: Could not run" notice (see the helper row above). No lock is ever claimed. `logout` is `labwc --exit`, absent only outside labwc. There is no suspend entry in the launcher (suspend is RiceSpice only, see below) | `tests/test_de_sg7_surfaced_states.py::LockActionProviderAbsentTests`; `tests/test_de_lock.py::test_missing_locker_and_nested_preview_fail_before_side_effects`; rs: `failed_watched_helper_is_reported_once_and_successful_or_running_ones_are_not` (`main.rs`) |

## RicePlate desktop (icons, file menu)

| State | Surfaced as | Proof |
|---|---|---|
| RiceField helper missing | Exactly the Gio fallback, and only for a *missing* binary; a denied/broken helper is an error, not a fallback | rs: `missing_ricefield_uses_exactly_the_gio_fallback`, `spawn_fallback_only_for_missing_ricefield_and_reap_is_caller_owned` (`desktop_layout/actions.rs`); `luna_places.rs` comment/`location unavailable` stderr line |
| Desktop directory unreadable or foreign entries | Fails closed (no listing), no partial entries | rs: `unreadable_desktop_and_foreign_entries_fail_closed` (`desktop_layout/inventory.rs`) |
| Directory write denied / source swapped / `.desktop` gone | Recoverable error, contents untouched | rs: `denied_directory_write_fails_without_touching_contents`, `source_swap_and_missing_desktop_return_recoverable_errors`, `reject_traversal_empty_dot_control_nul_and_stale_source` (`desktop_layout/actions.rs`) |
| Desktop root removed | Watcher requires re-arm; no polling | rs: `removed_root_requires_rearm_no_polling_and_rejects_missing` (`desktop_layout/watcher.rs`) |
| Stale or cross-rice saved icon positions | Rejected without mutating the recipe | rs: `rejects_stale_or_cross_rice_positions_without_mutating_recipe`, `rejects_invalid_owner_and_unsupported_migration_without_partial_apply` (`icon_positions.rs`) |
| `gio trash` fails after the confirmation dialog closed | "Recycle Bin: Could not move item" notice (the file stays); no replay | local compositor receipt: `smoke_sg1_interaction_labwc.sh` stage `files` (failing `gio` shim) |
| Second confirmed Trash/Rename while a trash helper is still running | Refused with "Another file operation is running" in the open dialog; never queued or duplicated | rs: `a_finite_watched_operation_stays_watched_however_long_it_runs` (`main.rs`); `tests/test_sg1_interaction_smoke.py::test_trash_in_flight_refuses_a_second_confirmed_operation`; local compositor receipt: stage `files` (slow `gio` shim) |
| Two New Folder requests back to back | Served one after the other: exactly two distinct folders | local compositor receipt: stage `files` |
| Desktop file refused (unreadable) / New Folder denied | "Desktop: Could not open item" / "Desktop: Could not create folder" notice | local compositor receipt: stage `files` |
| Stale file selection / context menu intent | Items revoked, never retargeted; destructive actions need confirmation | rs: `file_and_folder_intents_are_validated_and_stale_items_are_revoked`, `typed_context_is_not_arbitrary_exec_or_destructive_without_confirmation` (`desktop_context.rs`), `bounded_range_selection_rejects_stale_entries_and_does_not_cross_visible_set` (`file_state.rs`) |

## RiceSpice settings pages (GTK, shared adapters)

The per-cell matrix (Wi-Fi, saved profiles, enterprise Wi-Fi, VPN import, audio,
MPRIS, Bluetooth, power/lock/suspend, time/NTP/timezone, displays, input,
accessibility) lives in [sg2-adapter-state-inventory.md](sg2-adapter-state-inventory.md)
with test ids; the user-visible wording is the part reviewed here.

| State | Surfaced as | Proof |
|---|---|---|
| Authorization denied (polkit/NM/BlueZ/logind/timedated/power-profiles) | One fixed message: "Permission denied: the system did not authorize this change; nothing was changed". No raw stderr; no replay | `macrice/authorization.py`; `tests/test_de_sg2_authorization_denial.py`, `tests/test_de_sg2_bluetooth_power_denial.py`, `tests/test_de_sg2_gap_fill.py` (power-profile denial was previously mislabelled "outcome unknown"; fixed in WP2.2), `tests/test_de_settings_busy.py::RiceSpiceBusyActionTests::test_polkit_denial_and_generic_failure_have_distinct_visible_wording` |
| Provider unavailable / generic failure | "Unavailable or denied: <fixed reason>" in the status line; the original control stays enabled | `settings.denial_or_error_text`; `tests/test_de_settings_gui_controls.py`, `tests/test_de_sg2_gap_gui.py` |
| Write outcome unknown (timeout/reply lost) | "may have changed; outcome unknown; refresh", never retried | `tests/test_de_settings_provider_uncertainty.py`, `tests/test_de_timedated_unknown_outcome.py`, `tests/test_de_sg2_nm_profile_readback.py` |
| Second click while a request runs | Refused with "retry this action" text; one backend call | `tests/test_de_settings_busy.py::test_busy_click_explains_retry_without_delayed_unsafe_replay`; GUI matrices in `test_de_settings_gui_controls.py` |
| Wi-Fi scan provider error | "Wi-Fi radio/scan unavailable: …", no radio toggle, no false empty list | `tests/test_de_settings_gui_controls.py::NetworkControlTests::test_wifi_scan_provider_error_is_not_an_empty_list` |
| No MPRIS player / media session unavailable | "No MPRIS-compatible media player is running." / "Media session unavailable: …"; unsupported commands disabled | `settings.py` `_audio`; `tests/test_riceware_media.py::test_unsupported_player_action_never_dispatches_command`, `test_missing_session_bus_reports_error_without_faking_a_player` |
| Orca not installed | Accessibility page states "Orca is not installed"; session logs it and starts nothing | `tests/test_de_sg2_gap_gui.py::PreferencePageTests::test_i3_missing_orca_is_stated_not_hidden`, `tests/test_de_sg2_gap_fill.py::OrcaProviderMissingTests` |
| Preference store unreadable / changed elsewhere | "Private RiceSpice preferences unavailable: …" with no Save control; stale save refused | `tests/test_de_sg2_gap_gui.py::PreferencePageTests`, `tests/test_de_ricespice_native.py::RiceSpicePreferenceTests::test_malformed_and_unsafe_file_never_changes_session` |
| Monitor change not confirmed / rollback fails | Original mode restored at the deadline; rollback failure is reported, not claimed | `tests/test_display_guard.py::GuardTests` (DG2-DG4), `tests/test_de_ricespice_native.py::WaylandMonitorTests`; GUI: `test_de_settings_gui.py::test_login_monitor_confirmation_is_visible_and_explicit` |
| Outside a RiceBowl Wayland session (XFCE, nested preview) | No monitor query/write; suspend refused in nested preview | `tests/test_de_ricespice_native.py::WaylandMonitorTests::test_outside_ricebowl_no_monitor_query_or_write`, `tests/test_de_settings.py::test_suspend_refused_in_nested_preview_without_command` |
| Real polkit/NetworkManager/BlueZ/logind text on hardware | Marker-based classification only | **open** (hardware): not provable with fakes |

## RicePop notifications

| State | Surfaced as | Proof |
|---|---|---|
| Notification host (Mako) lost or replaced | Inbox shows "RicePop notification host disconnected." (German localized), never an empty-inbox claim; rows and actions removed | `tests/test_de_ricepop_i18n.py::test_disconnected_owner_is_not_rendered_as_empty_or_actionable`; local smoke receipt (host SIGKILL while the inbox is open) in `scripts/smoke_sg3_ricepop_native_labwc.sh` (local only) |
| Notifications daemon not running / not installed in session | Services health `unavailable`; `ricebowl de` reports "Mako notification inventory is unavailable"; nothing is faked | `macrice/de/notifications.py`; `tests/test_de_notifications.py::test_missing_backend_invalid_reply_and_overlong_history_fail_closed`, `tests/test_de_integration_health.py::test_missing_dbus_tool_and_session_bus_never_invent_owners` |
| Foreign or restarted bus owner | Dismiss/invoke refused before private data is read | `tests/test_de_notifications.py::test_owner_verified_inbox_fail_closed_on_foreign_or_restarted_bus`, `test_inbox_buttons_reject_mako_restart_before_reading_private_messages`; `tests/test_de_native_ricepop_guard.py` |
| Recycled / duplicate / changed-meaning notification id | Action or dismiss rejected; duplicate ids refuse disclosure | `tests/test_de_notifications.py::test_inbox_actions_reject_recycled_id_after_notification_replacement`, `test_invoke_rejects_reused_id_and_key_with_changed_action_meaning`; `tests/test_de_notification_inbox_identity.py` |
| Action/dismiss reply lost or timed out | "RicePop action unconfirmed; refresh before retry" (never a "denied"); no silent replay | rs: `cli_transport_loss_is_indeterminate_only_after_an_action_was_launched` (`ricepop.rs`); `tests/test_de_ricepop_write_uncertainty.py` |
| Do Not Disturb write unconfirmed | "may have changed; verification unavailable; refresh"; no retry | `tests/test_de_ricepop_dnd_uncertainty.py` |
| Read failure (CLI or list) | "Notification host unavailable" / "Notification list unavailable" | rs: `cli_transport_loss_…` (above); `selection_and_stale_response_are_bounded`, `active_only_malformed_or_ambiguous_data_fails_closed` (`ricepop.rs`) |
| History row | Read-only: stale/history actions non-invokable | rs: `details_keep_history_read_only_and_stale_actions_non_invokable` |
| Mako older than 1.11 | `ActionInvoked` is never emitted for `makoctl invoke`; native action smoke needs 1.11 | `scripts/smoke_real_mako_111.sh`; WP3.4/3.5 (CI run pending); RiceBowl does not detect the Mako version and shows no notice: a zero `makoctl invoke` exit is the only success signal, and a non-zero exit or timeout is the "unconfirmed" text above | `tests/test_de_sg7_surfaced_states.py::MakoVersionHasNoInAppNoticeTests` (no version probe, exactly one `makoctl invoke`) |
| Chrome rice | No native Notifications entry in the panel or a menu (the bundled recipe has no menu and no notifications token); the inbox stays reachable through RiceSpice | `tests/test_de_sg7_surfaced_states.py::ChromeRiceHasNoNativeNotificationsEntryTests`; WP3.1 "still open" |

## Creator / RicePack

| State | Surfaced as | Proof |
|---|---|---|
| Malformed, executable, oversized or unsupported-version recipe/pack | Rejected with a validation error before any file is written | `tests/test_creator_schema.py::test_schema_rejects_unsupported_versions`, `test_standard_jsonschema_rejects_malformed_and_executable_edits`; `tests/test_de_ricepack.py::test_invalid_manifest_and_archive_entries_are_always_rejected`; `tests/test_de_recipes.py::test_duplicates_invalid_types_and_oversized_recipe_fail_closed` |
| Import/export over an existing file, symlink, reserved id | Refused; never overwritten or followed | `tests/test_de_ricepack.py::test_rejects_overwrite_symlinks_unowned_modes_and_reserved_ids`, `tests/test_de_ricepack_export_durability.py::test_existing_export_is_never_overwritten_or_retried` |
| Modified recipe or asset after provenance was recorded | Provenance fails closed; redistribution rights are not asserted | `tests/test_de_ricepack.py::test_imported_provenance_fails_closed_when_recipe_is_modified`, `test_inspection_reports_missing_license_evidence_without_claiming_rights` |
| Export durability not confirmed | Reported as not durable, no rollback claimed | `tests/test_de_ricepack_export_durability.py::test_failed_directory_durability_does_not_claim_safe_rollback` |
| Stale draft or concurrent edit before install/apply | Refused ("Not installed or applied" wording in GUI) | `tests/test_creator_activation.py::test_reject_stale_draft_before_install`, `test_apply_rejects_concurrent_installed_edit`, `test_apply_checks_expected_active_and_digest` |
| Apply needs a live RiceBowl session | Refused outside it; conflicts/uncertain completion are not shown as success | `tests/test_creator_activation.py::test_apply_requires_prior_install_and_live_supervisor`, `test_live_conflict_and_uncertain_completion_are_not_reported_success` |
| Damaged draft versions | Recovery only to the last verified ancestor; unsafe receipts reported, not followed | `tests/test_creator_recovery.py` |
| Interactive test preview without display/dependencies or with a stale draft | Fails before spawning anything | `tests/test_creator_interactive.py::test_missing_display_and_dependencies_fail_before_spawn`, `test_stale_draft_and_unsafe_runtime_never_start` |
| GUI wording ("Live change unavailable: …", "Interactive test unavailable: …", "Native preview unavailable. Draft editing still works.", "Reference unavailable: …") | Status line / caption in the Creator window | `macrice/creator_gui.py`; `tests/test_de_creator_gui_wording.py` builds the real `CreatorWindow` (real Gtk, only `Gtk.Application.run` replaced) and asserts each of the four strings, the error style class, cleared busy state and that no session/preview is started |
| One-click conversion of an arbitrary image to a rice | Not implemented; must not be claimed | AGENTS.md mockup-to-rice contract |

## Session / supervisor

| State | Surfaced as | Proof |
|---|---|---|
| Required tool missing (labwc, foot, swayidle for a full login) | `SessionError` before the compositor starts | `tests/test_de_session.py::test_missing_tool_fails_before_starting_compositor`, `test_full_login_requires_idle_lock_but_nested_preview_does_not` |
| Root, wrong or symlinked runtime dir, bad recipe | Refused before starting labwc | `tests/test_de_session.py::test_no_root_session`, `test_wrong_runtime_directory_is_rejected`, `test_symlinked_runtime_is_rejected_by_preflight`, `test_bad_recipe_fails_before_labwc_exec` |
| Existing desktop (XFCE) without nested/login wrapper | Refused; XFCE path untouched | `tests/test_de_session.py::test_existing_desktop_requires_nested_or_login_wrapper` |
| Interrupted rice switch / corrupt selection | Next login uses the classic rice; owner data untouched | `tests/test_de_session.py::test_unsafe_interrupted_switch_uses_classic_for_next_login`, `test_corrupt_selection_and_ricespice_preferences_keep_owner_data_untouched` |
| Optional service (Mako, Orca, polkit agent) fails to start or crashes | One bounded retry, next polkit provider, no restart storm; session survives | `tests/test_de_optional_services.py` (initial/crash retry, failover, all-fail, retry-spawn-failure) |
| Orca requested but not installed | stderr "Orca screen reader requested but not installed", nothing spawned | `tests/test_de_sg2_gap_fill.py::OrcaProviderMissingTests` |
| Idle-lock guard fails | Live session stops instead of running unlocked; no insecure rescue | `tests/test_de_session.py::test_idle_lock_watcher_crash_stops_live_session_instead_of_rescuing`, `test_native_idle_guard_failure_never_starts_insecure_waybar_rescue`; `tests/test_de_optional_services.py::test_security_critical_idle_guard_failure_still_aborts_full_session` |
| Native panel crash or launch failure | One Waybar rescue, not repeated; user shutdown never restarts it | `tests/test_de_session.py::test_native_crash_restores_waybar_instead_of_exiting_the_session`, `test_failed_waybar_rescue_does_not_restart_forever`, `test_native_launch_failure_restores_waybar`, `test_native_user_shutdown_never_restarts_waybar` |
| Integration health when D-Bus/tools/lock are missing | `ricebowl de` health JSON says `tool-missing`/`not-owned`/not ready; read-only | `tests/test_de_integration_health.py`, `tests/test_de_reliability.py::test_missing_lock_and_backend_never_claim_ready`, `test_disconnected_dbus_is_reported_without_service_mutation` |
| Resource receipts that are stale, restarted or ambiguous | Rejected as evidence, not zero | `tests/test_de_reliability.py` (counter regression, restarted panel, missing wakeups) |
| Physical Mint/ThinkPad/GPU/Orca/multi-monitor behavior | Not covered by any state above | **open**: `RELEASE_1_0_GATES.md` |

## Known gaps in this list

- Real polkit/NM/BlueZ/logind refusal text is classified by markers only.
- Rust rows were checked by grepping the test names, not by running `cargo test`
  in this session (no Rust toolchain was used). No row remains `unverified`;
  the previous `unverified` Rust-only candidates turned out to be Python-side
  behavior and are now tested above. Nothing here needs a compositor beyond the
  local smoke receipts already cited.
- There is still no in-app Mako-version notice (not implemented, by design of
  the current code).
