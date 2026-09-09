# control_previews_v1.csv

## Status and scope

Normative zero-authority frequency-regulation projection used for deterministic
host replay beside the active adaptive-hybrid path. `CTL` v1 has no direct
actuation authority:
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
| `plant_model_ref` | string | Exact `model:pps_gated_oscillator_plant_v1`. |
| `plant_model_id` | string | Exact `OTIS_PPS_GATED_OSCILLATOR_PLANT_V1`. |
| `plant_model_version` | uint | Exact semantic version `1`. |
| `plant_model_hash` | string | SHA-256 of the current plant-profile bytes. |
| `policy_version` | string | Preview-policy identity. |
| `config_hash` | string | SHA-256 of canonical replay configuration. |
| `control_state` | enum | Current frequency-regulation projection state. |
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
| `proposed_dac_code` | uint16/unavailable | Diagnostic projected code; unavailable when inhibited. |
| `step_limited` | bool | Maximum manual preview step changed the proposal. |
| `range_clamped` | bool | Disabled candidate envelope changed the proposal. |
| `preview_available` | bool | A bounded proposal is available for inspection. |
| `preview_only` | bool | Always `true`. |
| `actuation_authorized` | bool | Always `false`. |
| `actionable` | bool | Always `false`. |
| `decision_reason_code` | string | Primary explanation of proposal availability/inhibition. |

## Policy semantics

The policy consumes an eligible `EST`, the current validated plant
model, latest applied DAC evidence, and versioned configuration. It enforces:

- model topology/backend identity and explicit applicability;
- exclusion and invalidation conditions represented by available evidence;
- the current finite code and step envelope;
- exact model, DAC-epoch, estimator, and timing identities;
- zero-authority status regardless of projection availability.

An ineligible decision has no proposed DAC code. An eligible decision may have
a projection, but it remains non-actionable because physical authority belongs
only to the adaptive-hybrid transaction path.

The live firmware emits `EST` and `CTL` as one bounded telemetry pair. If the
derived queue is full, the pair is dropped and counted without feeding the loss
back into estimator state or changing raw capture/count truth.

## Stable initial reason codes

Current reason-code families include `startup_warmup`,
`dac_epoch_full_history_reset`, `fresh_estimator_support`,
`dac_epoch_fresh_history_complete`, `reference_invalid`,
`estimator_invalid_or_snapshot_gap`, `count_invalid`,
`authoritative_integer_edge_error_unavailable`, `decision_cadence_hold`,
`frequency_error_unavailable`, `plant_model_mismatch`,
`requested_applied_mismatch`, `i2c_failure`,
`current_code_outside_clamp`, `tight_deadband_evaluation_failed`,
`preview_available`, `explicit_recovery_fresh_support`, and
`operator_abort`.
