# hybrid_preview_decisions_v1.csv

## Status and scope

Normative CX318 Stage 4 hybrid-preview decision contract. `HPR` v1 records
one candidate's coherent counterfactual phase/frequency preview. It is not a
DAC request and cannot grant authority.

## Fields

| Field | Meaning |
|---|---|
| `record_type`, `schema_version`, `preview_sequence` | Always `HPR`, `1`, and a strictly increasing preview record sequence. |
| `candidate_id`, `candidate_configuration_sha256` | Frozen candidate identity and immutable candidate configuration. |
| `phase_estimator_id`, `phase_estimator_configuration_sha256` | Exact source phase-estimator identity. |
| `frequency_estimator_id`, `frequency_estimator_configuration_sha256` | Exact source frequency-estimator identity. |
| `configuration_sha256` | Canonical combined preview configuration identity. |
| `phase_epoch`, `observation_sequence`, `dac_epoch` | Source phase observation and DAC-epoch identities. |
| `decision_timestamp_ticks`, `time_domain` | Native preview evaluation timestamp and domain. |
| `source_phase_estimate`, `source_frequency_estimate` | Exact current `PHE` record identifiers; frequency is explicitly `unavailable` until the current PHE carries authoritative frequency support. |
| `raw_relative_phase_cycles`, `modeled_relative_phase_cycles` | Observed raw phase and the candidate's modeled phase. |
| `observed_frequency_error_hz`, `modeled_frequency_error_hz` | Observed source frequency and candidate modeled frequency. |
| `frequency_term_hz`, `phase_bias_hz`, `combined_frequency_error_hz` | Separately visible components and their one combined counterfactual frequency error. |
| `actual_applied_code`, `shadow_code_before`, `shadow_code_after` | Evidence-backed static actual code and candidate shadow-code evolution. |
| `band_state_before`, `band_state_after` | Candidate band states: `INSIDE` or `OUTSIDE`. |
| `preview_state`, `decision_reason` | Frozen Stage 1/3 state and stable reason. No state claims actual lock. |
| `frequency_observation_event`, `counterfactual_decision`, `counterfactual_correction` | Whether fresh frequency evidence arrived and a model-only decision/correction was evaluated. |
| `raw_counterfactual_delta_codes`, `counterfactual_delta_codes`, `counterfactual_code` | Raw and bounded model-only code deltas and resulting shadow code, when a decision is made. |
| `step_limited`, `range_clamped`, `correction_count`, `cumulative_movement_codes`, `alternating_correction_count` | Counterfactual bounds and candidate-only correction counters. |
| `modeled_not_observed_after_divergence` | Must equal whether `shadow_code_after` differs from `actual_applied_code`. |
| `uncertainty_status` | `available`, `incomplete`, or `unavailable`. |
| `actionable`, `actuation_authorized`, `authorization_consumed` | Always `false`. |

Every `*_sha256` field is a lowercase SHA-256. The validator rejects any HPR
row that sets an authority field true. When present, `counterfactual_code`
equals `shadow_code_after`, and `counterfactual_delta_codes` equals
`shadow_code_after-shadow_code_before`; raw and bounded deltas are empty when
`counterfactual_decision=false`.
