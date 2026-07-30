# reference_observations_v1.csv

## Purpose

`reference_observations_v1.csv` stores interpreted or normalized reference observations derived from raw reference captures.

This contract exists because:

- raw `REF` captures are the primary scientific artifact;
- host tooling may later derive cleaner or normalized reference observations;
- PPS quality, survey state, sawtooth metadata, or reference validity may evolve independently from raw edge captures.

## Relationship to Raw Events

Raw PPS/reference edges belong in `raw_events_v1.csv` as `REF` records.

This contract is for higher-level interpreted reference products.

## Example Uses

- normalized PPS intervals;
- PPS quality classification;
- reference-domain continuity assessment;
- timing-GNSS metadata;
- reference-source substitution tracking.

## Record contract

The record type is `RFO` and schema version is `1`. Each row is an interpreted
reference-quality snapshot derived from preserved raw `REF` and receiver/status
evidence.

| Field | Meaning |
|---|---|
| `reference_observation_seq` | Strictly increasing derived sequence. |
| `reference_observation_id` | Stable run-local identifier. |
| `observation_timestamp_ticks` / `time_domain` | Evaluation time and native domain. |
| `source_identity_epoch` | Receiver/capture identity epoch; changes on reconnect or identity change. |
| `source_reference_first_seq` / `source_reference_last_seq` | Exact raw `REF` range considered. |
| `source_reference_refs` | Exact raw reference evidence references. |
| `source_metadata_refs` | Exact receiver/status evidence references, or explicit unavailable reference. |
| `receiver_identity` / `receiver_firmware` | Reported identity, or `unknown`. |
| `cadence_state` | `valid`, `duplicate`, `short`, `long`, `missing`, `invalid`, or `unavailable`. |
| `capture_path_state` | `valid`, `sequence_gap`, `overflow`, `resource_failure`, `invalid`, or `unavailable`. |
| `receiver_authority_state` | `qualified`, `holdover`, `fix_unavailable`, `antenna_fault`, `invalid`, `unknown`, or `unavailable`. |
| `utc_traceability_state` | `valid`, `invalid`, `unknown`, or `unavailable`. |
| `metadata_freshness` | `current`, `stale`, `missing`, or `unavailable`. |
| `timing_mode`, `fix_holdover_state`, `antenna_state`, `leap_state` | Receiver quality fields, or `unknown`. |
| `sawtooth_correction_ns`, `cable_delay_ns` | Numerical values when supported; otherwise empty. |
| `pulse_configuration`, `calibration_ref` | Exact configuration/provenance, or `unknown`. |
| `reference_standard_uncertainty_s` | Evidence-backed standard uncertainty, or empty. |
| `qualification_state` | Explicit interpreted state; never inferred from cadence alone. |
| `qualification_reason_codes` | Stable reasons for the state. |
| `algorithm_version` / `config_hash` | Reducer and configuration identity. |

## Qualification rule

Cadence plausibility, capture-path health, receiver authority, UTC
traceability, metadata freshness, and reference uncertainty are independent.
In particular, good one-second cadence with missing receiver metadata produces
`cadence_valid_authority_unknown`, not `qualified`.

Raw `REF` rows remain authoritative and unchanged.

When a receiver supplies no explicit identity epoch, deterministic replay may
derive `reference_source_epoch:N` from explicit receiver identity and firmware
evidence. A changed identity/firmware fingerprint starts a new epoch; missing
identity does not invent one. A producer-supplied epoch remains authoritative.

The current Nano RP2040 Connect live adapter has no configured receiver-status
decoder. It therefore emits explicit `unknown`/empty receiver fields,
`source_metadata_refs=unavailable:reference_receiver_metadata`, and can never
promote cadence to receiver authority. Host replay consumes
`reference_receiver` STS evidence when present. This unsupported live metadata
path is an explicit interface boundary, not an inferred healthy state.
