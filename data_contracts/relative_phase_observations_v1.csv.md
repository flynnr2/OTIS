# relative_phase_observations_v1.csv

## Status and scope

Normative CX318 Stage 4 raw relative-phase observation contract. `RPH` v1 is
immutable derived timing evidence: it records the frozen Stage 1 cumulative
edge-error boundary and does not imply UTC, absolute phase, phase lock, or
actuation authority.

`phase_epoch` and `observation_sequence` identify the phase stream. The
observation sequence may restart when a new phase epoch opens; readers must
not bridge epochs by guessing an offset.

## Fields

| Field | Meaning |
|---|---|
| `record_type`, `schema_version` | Always `RPH`, `1`. |
| `phase_epoch`, `observation_sequence` | Epoch-local immutable observation identity. |
| `capture_session` | Source snapshot capture session. |
| `opening_snapshot_sequence`, `closing_snapshot_sequence` | Exact cumulative-counter snapshots for the interval. |
| `opening_reference_sequence`, `closing_reference_sequence` | Exact reference associations for the interval. |
| `dac_epoch` | Evidence-backed DAC epoch; a healthy transition does not bridge or rewrite raw phase. |
| `source_backend`, `source_file_sha256` | Immutable source backend and raw-source file identity. |
| `method_id`, `configuration_sha256` | Frozen raw-estimator method and canonical configuration identity. |
| `interval_edges`, `edge_error_cycles` | Accepted interval count and signed error; empty for a non-qualified record. |
| `relative_phase_cycles`, `relative_phase_time_ns` | Cumulative raw phase in cycles and CX317 100 ns/cycle conversion. |
| `qualification_state`, `observation_age_s`, `discontinuity_reason` | Explicit acceptance or invalidation context; non-qualified rows require a reason. |
| `calibrated_uncertainty_status` | `unavailable` unless separately evidence-backed. |

`qualification_state=qualified` requires both interval fields. Other states
must leave those fields empty. All `*_sha256` values are lowercase SHA-256
identities.

On-wire live firmware cannot know the final hash of the append-only raw serial
capture. For that case alone, `source_file_sha256=live_stream_unsealed` is the
only permitted non-hash value. Capture sealing or replay must replace it with,
or bind it to, the final raw serial-file SHA-256 before treating the evidence as
sealed. Arbitrary placeholder text is invalid.
