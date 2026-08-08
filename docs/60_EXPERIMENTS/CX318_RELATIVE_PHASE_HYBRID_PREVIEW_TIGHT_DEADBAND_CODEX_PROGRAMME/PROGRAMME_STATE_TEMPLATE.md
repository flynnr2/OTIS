# CX318 Relative-Phase, Hybrid-Preview and Tight-Deadband Programme State

```text
campaign_id:
campaign_directory:
created_utc:
updated_utc:

repository_root:
repository_commit:
repository_branch:
repository_clean_at_start:
origin_main_commit:

active_stage:
stage_status:
last_completed_stage:
next_action:
blocking_condition:
pending_human_checkpoint:

serial_device:
board_usb_identity:
connected_oscillator:
pps_source:
gps_receiver_identity:
gps_metadata_state:
physical_waveform_status:

firmware_profile:
firmware_source_hash:
firmware_config_hash:
firmware_artifact_hash:
firmware_flash_utc:
measurement_backend:
snapshot_backend:
capture_owner:
capture_session:

frequency_estimator_profile:
frequency_estimator_hash:
phase_estimator_profile:
phase_estimator_hash:
phase_epoch:
phase_epoch_start_source:
phase_epoch_status:
latest_relative_phase_cycles:
latest_relative_phase_time_ns:
phase_uncertainty_status:

plant_model:
plant_model_hash:
tight_frequency_policy:
tight_frequency_policy_hash:
response_policy:
response_policy_hash:
hybrid_preview_profiles:
hybrid_preview_hashes:
selected_hybrid_preview:

phase_preview_actionable: false
phase_preview_actuation_authorized: false
phase_preview_authorization_consumed: false
phase_preview_dac_reachability: false

frequency_actuation_enabled:
frequency_actuation_authorized:
frequency_actionable:
armed_run_identity:
arm_expiry:
correction_count:
correction_limit:
cumulative_movement_codes:
cumulative_limit_codes:
last_requested_code:
last_accepted_code:
last_confirmed_applied_code:
last_applied_sequence:
last_applied_timestamp:
last_i2c_status:

abort_path:
abort_path_status:
capture_run_directory:
capture_health:

core_partition:
core0_health:
core1_health:
request_queue_health:
ack_queue_health:
phase_preview_queue_health:
telemetry_drop_count:

active_campaign_part:
active_campaign_leg:
leg_setup_code:
leg_started_utc:
leg_qualified_utc:
leg_completed_utc:
leg_stop_reason:
latest_transaction_capsule:

evidence_seals:
test_result:
firmware_matrix_result:
no_hardware_validation_result:
```

## Stage gates

```text
stage_1_gate:
stage_2_gate:
stage_3_gate:
stage_4_gate:
stage_5_lower_leg_gate:
stage_5_upper_leg_gate:
stage_5_gate:
stage_6_real_gps_gate:
stage_6_fault_gate:
stage_6_gate:
stage_7_gate:
```

## Immutable programme limits

```text
dac_min_code: 0xA800
dac_max_code: 0xAB00
lower_leg_setup_code: 0xA808
upper_leg_setup_code: 0xA848
maximum_automatic_update_codes: 21
minimum_automatic_update_cadence_s: 1800
settling_exclusion_s: 900
fresh_frequency_support_s: 600
tight_entry_absolute_600s_counts: 2
loose_release_absolute_600s_counts: 4
tight_entry_consecutive_estimates: 2
loose_release_consecutive_estimates: 2
initial_band_state: REQUALIFY_OUTSIDE
stage5_maximum_corrections_per_leg: 4
stage5_maximum_cumulative_codes_per_leg: 84
stage6_maximum_corrections: 8
stage6_maximum_cumulative_codes: 168
automatic_retry: false
automatic_restore_on_fault: false
phase_or_hybrid_actuation_authorized: false
gps_tx_to_nano_rx_required: true
nano_tx_to_gps_rx_enabled: false
```

## Transition and event log

Append one line for every material transition:

```text
- <UTC> | <event> | <identity/evidence/result> | <next safe action>
```
