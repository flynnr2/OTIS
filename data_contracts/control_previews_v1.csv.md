# control_previews_v1.csv

## Status and scope

Normative Phase 4 correction-preview contract for deterministic host replay and
live observe-only firmware. `CTL` v1 is observe-only:
`preview_only=true`, `actuation_authorized=false`, and `actionable=false` are
mandatory. No field in this contract is permission to write a DAC.

## Schema

| Field | Type | Meaning |
|---|---|---|
| `record_type` | enum | Always `CTL`. |
| `schema_version` | uint | Always `1`. |
| `control_seq` | uint64 | Strictly increasing decision sequence. |
| `decision_id` | string | Stable run-local decision identifier. |
| `decision_timestamp_ticks` | uint64 | Policy evaluation timestamp. |
| `time_domain` | string | Native evaluation timestamp domain. |
| `est_input_ref` | string | Exact `EST` input identifier. |
| `plant_model_ref` | string | Plant-model content identity or explicit unavailable/invalid reference. |
| `plant_model_id` | string/unavailable | Validated model identity. |
| `plant_model_version` | uint/unavailable | Validated semantic model version. |
| `plant_model_hash` | string/unavailable | SHA-256 of model bytes. |
| `policy_version` | string | Preview-policy identity. |
| `config_hash` | string | SHA-256 of canonical replay configuration. |
| `control_state` | enum | Roadmap-aligned observe-only operating state. |
| `previous_control_state` | enum | State before this evaluation. |
| `state_transition` | bool | Whether the state changed. |
| `transition_reason_code` | string | Stable reason for the retained or new state. |
| `preview_eligibility` | bool | Full estimate, diagnostic, DAC, and model eligibility. |
| `eligibility_reason_codes` | string | Stable reasons for the eligibility result. |
| `diagnostic_health` | enum | Health copied from the referenced estimator decision context. |
| `model_applicability` | enum | `applicable`, `not_applicable`, `unavailable`, or `invalid`. |
| `model_reason_codes` | string | Model-version/applicability/invalidation conclusions. |
| `current_dac_code` | uint16/unavailable | Latest evidence-backed applied DAC code. |
| `frequency_error_hz` | decimal/unavailable | Error from the referenced `EST`. |
| `hz_per_code` | decimal/unavailable | Evidence-backed local plant gain. |
| `raw_delta_codes` | decimal/unavailable | Unclamped model inversion result. |
| `limited_delta_codes` | int/unavailable | Signed delta after maximum preview-step and range limits. |
| `proposed_dac_code` | uint16/unavailable | Observe-only proposal; unavailable when inhibited. |
| `step_limited` | bool | Maximum manual preview step changed the proposal. |
| `range_clamped` | bool | Disabled candidate envelope changed the proposal. |
| `preview_available` | bool | A bounded proposal is available for inspection. |
| `preview_only` | bool | Always `true`. |
| `actuation_authorized` | bool | Always `false`. |
| `actionable` | bool | Always `false`. |
| `decision_reason_code` | string | Primary explanation of proposal availability/inhibition. |

## Policy semantics

The policy consumes an eligible `EST`, a validated model-version-4 plant
model, latest applied DAC evidence, and versioned configuration. It enforces:

- model topology/backend identity and explicit applicability;
- exclusion and invalidation conditions represented by available evidence;
- the disabled candidate automatic range;
- `manual_preview_max_step_codes`;
- observe-only status regardless of proposal availability.

An ineligible decision has no proposed DAC code. An eligible decision may have
a proposal, but it remains non-actionable because Phase 4 contains no write
path and model status remains `control_ready=false` and
`actuation_enabled=false`.

The live firmware emits `EST` and `CTL` as one bounded telemetry pair. If the
derived queue is full, the pair is dropped and counted without feeding the loss
back into estimator state or changing raw capture/count truth.

## Stable initial reason codes

Reason-code families include `startup_inhibit_active`,
`clean_window_qualification_incomplete`, `reference_unavailable`,
`reference_stale`, `reference_interval_outlier`, `count_unavailable`,
`count_stale`, `count_zero`, `count_saturated`,
`count_sequence_discontinuity`, `count_flagged_invalid`,
`post_qualification_measurement_fault`,
`plant_model_unavailable`, `plant_model_invalid`,
`plant_model_version_not_4`, `plant_model_topology_mismatch`,
`plant_model_backend_mismatch`, `plant_model_estimator_method_mismatch`,
`input_outside_model_applicability`, `dac_settling_state_unverified`,
`count_window_inside_model_settling_exclusion`, `temperature_not_observed`,
`temperature_observation_stale`,
`input_outside_model_temperature_range`,
`plant_model_excluded_count_sequence`, `dac_state_unavailable`,
`estimator_underqualified_sample_count`, `estimator_dispersion_exceeded`,
`preview_step_limited`, `preview_range_clamped`,
`preview_available_observe_only`, and `preview_inhibited`.
