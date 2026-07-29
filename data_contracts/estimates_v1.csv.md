# estimates_v1.csv

## Status and scope

Normative Phase 4 estimator contract for deterministic host replay and live
observe-only firmware. `EST` records are replayable metrology products. They do
not replace `REF`, `CNT`, `STS`, `DAC`, manifests, or plant models, and they
cannot authorize or perform actuation.

## Schema

| Field | Type | Meaning |
|---|---|---|
| `record_type` | enum | Always `EST`. |
| `schema_version` | uint | Always `1`. |
| `estimate_seq` | uint64 | Strictly increasing derived-record sequence. |
| `estimate_id` | string | Stable run-local estimate identifier. |
| `estimator_timestamp_ticks` | uint64 | Replay evaluation timestamp. |
| `time_domain` | string | Native domain of the evaluation timestamp. |
| `source_count_seq` | uint64/unavailable | Latest source `CNT` sequence. |
| `source_count_ref` | string | Source file/row reference, or an explicit unavailable reference. |
| `source_reference_first_seq` | uint64/unavailable | First accepted `REF` sequence in the estimator window. |
| `source_reference_last_seq` | uint64/unavailable | Latest considered `REF` sequence. |
| `source_status_refs` | string | `STS` evidence references, or `unavailable`. |
| `source_dac_ref` | string | Latest `DAC` evidence reference, or `unavailable`. |
| `manifest_ref` | string | Manifest identity and content hash. |
| `estimator_version` | string | Estimator algorithm identity. |
| `config_hash` | string | SHA-256 of canonical replay configuration. |
| `observation_validity` | enum | `valid`, `invalid`, or `unavailable`. |
| `observation_reason_codes` | string | Semicolon-separated stable reason codes; `observation_valid` when clear. |
| `reference_validity` | enum | `valid`, `invalid`, `stale`, or `unavailable`. |
| `reference_age_s` | decimal/unavailable | Age of the latest reference evidence. |
| `reference_continuity` | bool | Whether reference cadence/continuity passed. |
| `count_validity` | enum | `valid`, `invalid`, `stale`, or `unavailable`. |
| `count_age_s` | decimal/unavailable | Age of the latest count observation. |
| `count_continuity` | bool | Whether count sequencing passed. |
| `diagnostic_health` | enum | `healthy`, `degraded`, `fault`, or `unknown`. |
| `diagnostic_reason_codes` | string | Diagnostic conclusions, distinct from observation validity. |
| `frequency_observation_hz` | decimal/unavailable | Frequency derived from the current valid `CNT`. |
| `accepted_sample_count` | uint | Number of accepted samples in the estimator window. |
| `estimator_confidence` | enum | `unavailable`, `low`, `medium`, or `high`. |
| `frequency_estimate_hz` | decimal/unavailable | Mean of the accepted deterministic window. |
| `frequency_error_hz` | decimal/unavailable | Estimate minus nominal oscillator frequency. |
| `frequency_uncertainty_hz` | decimal/unavailable | Population standard deviation of the accepted window. |
| `dispersion_hz` | decimal/unavailable | Same explicit window-dispersion statistic in v1. |
| `drift_enabled` | bool | Must be `false` in Phase 4 v1. |
| `drift_hz_per_s` | decimal/unavailable | Unavailable while drift is disabled. |
| `preview_eligibility` | bool | Estimator/measurement eligibility for preview-policy evaluation. |
| `eligibility_reason_codes` | string | Stable reasons for the eligibility result. |

## Semantics

Observation validity, diagnostic health, estimator confidence, and preview
eligibility are independent fields. A numerical estimate may remain visible
while a newer observation is stale or invalid, but that state is explicitly
ineligible. Unavailable values use an empty CSV field; they are never replaced
with zero.

The v1 estimator is deliberately simple: valid reference-qualified count
observations enter a bounded arithmetic-mean window. Confidence depends on
sample count, dispersion, continuity, age, and startup qualification. Drift
estimation is disabled.

## Provenance and safety

Every record cites the source count, reference range, status/DAC availability,
manifest hash, estimator version, and configuration hash. `EST` has no
hardware-write semantics.

Live firmware uses the same field order and semantics. Its source references
identify live canonical records or explicit unavailable evidence, and its
compiled configuration/model hashes bind the decision to versioned repository
inputs. Firmware telemetry loss does not change estimator state; it is reported
separately in `STS`.
