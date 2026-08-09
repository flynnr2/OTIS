# phase_estimator_outputs_v1.csv

## Status and scope

Normative CX318 Stage 4 phase-estimator output contract. `PHE` v1 is a
derived, non-actionable estimate sourced from one immutable `RPH` observation.
It keeps raw and filtered phase fields distinct even where the selected raw
estimator deliberately makes their values equal.

## Fields

| Field | Meaning |
|---|---|
| `record_type`, `schema_version` | Always `PHE`, `1`. |
| `phase_epoch`, `observation_sequence` | Source phase-observation identity; observation sequence can restart in a new epoch. |
| `source_relative_phase_observation` | Exact `RPH` record identity. |
| `raw_relative_phase_cycles`, `raw_relative_phase_time_ns` | Preserved raw cumulative phase. |
| `filtered_relative_phase_cycles` | Candidate-estimator phase output; never silently replaces the raw field. |
| `estimated_frequency_error_hz` | Last authoritative non-overlapping 600-interval frequency estimate, retained between fresh events and empty while unavailable. It is not the continuously rolling diagnostic value. |
| `estimator_id`, `configuration_sha256` | Frozen estimator and canonical configuration identity. |
| `estimate_age_s`, `qualification_state` | Age of the last authoritative frequency event and explicit qualification state. Both frequency and age are empty until that support exists. |
| `uncertainty_status` | `available`, `incomplete`, or `unavailable`; calibrated uncertainty defaults to unavailable. |
| `reason_codes` | Stable explanation of initialization, qualification, or inhibition. |

`PHE` carries no authority field and is never an actuator request. No reader
may join phase epochs using a guessed offset. `configuration_sha256` must be a
lowercase SHA-256. `source_relative_phase_observation` must equal the current
`RPH:<phase_epoch>:<observation_sequence>` identity. Once frequency support is
qualified, the same held non-overlapping estimate is emitted with increasing
age until the next fresh 600-interval event replaces it.
