# CX317 Bounded Closed-Loop Programme State

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
gps_uart_wiring:
gps_uart_rx_only:
gps_receiver_identity:
gps_metadata_state:
conditioner_topology:
physical_waveform_status:

firmware_profile:
firmware_source_hash:
firmware_config_hash:
firmware_artifact_hash:
firmware_flash_utc:
measurement_backend:
snapshot_backend:

estimator_profile:
estimator_hash:
plant_model:
plant_model_hash:
control_policy:
control_policy_hash:
response_policy:
response_policy_hash:

actuation_enabled:
actuation_authorized:
actionable:
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
capture_owner:
capture_session:
capture_run_directory:
capture_health:

core_partition:
core0_health:
core1_health:
request_queue_health:
ack_queue_health:
telemetry_drop_count:

active_campaign_leg:
leg_start_code:
leg_started_utc:
leg_completed_utc:
leg_stop_reason:
latest_step_capsule:

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
stage_5_gate:
stage_6_gate:
stage_7_gate:
stage_8_gate:
```

## Immutable live limits

```text
dac_min_code: 0xA800
dac_max_code: 0xAB00
initial_maximum_update_codes: 21
initial_minimum_update_cadence_s: 1800
settling_exclusion_s: 900
fresh_estimator_support_s: 600
campaign_a_start_code: 0xA950
campaign_a_maximum_corrections: 16
campaign_a_maximum_cumulative_codes: 336
campaign_b_start_code: 0xA800
campaign_b_maximum_corrections: 8
campaign_b_maximum_cumulative_codes: 168
automatic_restore_on_fault: false
gps_tx_to_nano_rx_required: true
nano_tx_to_gps_rx_enabled: false
```

## Transition and event log

Append one line for every material transition:

```text
- <UTC> | <event> | <evidence/result> | <next safe action>
```
