# Current Contract and Policy Authority

Current HEAD supports one instrument path: `adaptive_hybrid_regulation`.
Historical profiles, campaign registries, compatibility readers, and
programme-specific authority records are not current authority.

## Bound identities

- firmware image: `adaptive_hybrid_regulation`;
- firmware/policy version: `OTIS_ADAPTIVE_HYBRID_REGULATION_V1`;
- frequency estimator: `OTIS_PPS_GATED_FREQUENCY_ESTIMATOR_V1`;
- relative-phase estimator: `OTIS_RELATIVE_PHASE_ESTIMATOR_V1`;
- plant model: `OTIS_PPS_GATED_OSCILLATOR_PLANT_V1`; and
- active status: `adaptive_hybrid_active_status_snapshot_v1`; and
- firmware/host protocol: `OTIS_FIRMWARE_HOST_CONTRACT_V1`.

The machine-readable sources are the five files retained under `profiles/`
and the seven current schemas under `schemas/`. The current wire authority is
`data_contracts/otis_firmware_host_contract_v1.json`; its generated firmware
projection is checked rather than maintained independently. The fixed firmware
build identity and resource contract are in
`firmware/arduino/firmware_build_manifest.json`.

## Firmware/host attachment authority

The wire contract is exact-current-only. It controls record tags, versions,
ordered layouts and field encodings; command forms and ranges; typed ACTIVE
snapshot values; raw-only boot-diagnostic envelopes; queue frontiers; and named
cross-record relations. The firmware binary carries the canonical contract
digest and emits it as `protocol.contract_id` and
`protocol.contract_sha256`. A host must observe an exact match before setup or
arm authority is available.

`BOOT`, `BOOT_WARN`, `BOOT_FATAL`, and `BOOTDIAG` are typed raw-only diagnostic
envelopes, not canonical measurement records. One bounded late-attachment
suffix from `BOOT` is admissible before the first recognized protocol line.
These lines remain preserved in raw serial evidence and cannot affect
measurement, setup, regulation, actuation, abort, or a run terminal.

Unknown, missing, extra, malformed or out-of-version protocol data is retained
as raw evidence and enters a review-required diagnostic hold. Capture and the
last confirmed DAC state are preserved; the discrepancy cannot silently become
zero/default data and has no automatic abort or teardown authority. Detailed
operation and generation instructions are in
`data_contracts/otis_firmware_host_contract_v1.md`.

## Measurement authority

D14 is the sole PPS/reference authority. D8 is the sole oscillator-count input
used for regulation. GNSS metadata may qualify the receiver that supplies D14,
but never replaces D14. A recoverable metadata anomaly holds new corrections
at the last confirmed code while capture continues.

D10/channel 0 is optional external-event evidence. D6 is diagnostic evidence.
Neither can enter setup authority, D14/D8 validity, regulation eligibility,
actuation, or a run terminal. The current firmware records that isolated D10
capture is not yet implemented.

## Actuation authority

The characterized DAC envelope is `0xA800..0xAB00`. Every requested and applied
code must be joined to exact observation, policy, estimator, diagnostic gate,
request sequence, acknowledgement, DAC epoch, and resulting state identities.
An acknowledgement establishes producer acceptance only; activation and
rehearsal must verify propagation through the first dependent decision.

Repository state and passing offline tests do not authorize hardware use. Live
operation additionally requires an exact frozen bundle, genuine operational-
path rehearsal, and explicit operator authority.

Current HEAD can create a live activation only from a separately sealed and
registered current-process rehearsal that binds the exact bundle and proposal.
The validator rejects the non-authorizing structural preflight and unverified
claims to a process-level rehearsal. Historical campaign rehearsal code is not
a compatibility fallback.

The only current closed-loop physical purpose is
`contingent_72_hour_hybrid_control`: 259,200 accepted D14/D8 apertures, at most
144 natural applications, at most 3,024 codes of cumulative absolute movement,
and a 280,800-second wall limit. Zero natural corrections is a valid endpoint
when the controller remains healthily within its deadband. Setup, a first
application, or an elapsed short prefix is not a success terminal.

## Compatibility boundary

Git history and preserved experimental evidence are the compatibility
mechanism. Current HEAD must not build, load, validate, or silently translate a
retired programme identity. A historical result is interpreted with the exact
revision and manifest that created it.
