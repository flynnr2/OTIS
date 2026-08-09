# Machine-readable schema stubs

This directory is reserved for machine-readable OTIS schemas generated from, or kept in lock-step with, the normative contracts in `data_contracts/`.

At SW0 and SW1 the Markdown contracts remain authoritative except where a
contract explicitly promotes a machine-readable schema. Add JSON Schema, CSVW,
or generated firmware and host schema artifacts here only when they are wired
into validation tests.

`plant_model_v1.schema.json` is the sole structural authority for plant-model
schema version 1. `host.otis_tools.plant_model` executes it before applying
separate semantic, evidence-availability, applicability, and
control-eligibility checks. See
`docs/50_SOFTWARE/PLANT_MODEL_CONTRACT_AUTHORITY.md` for the complete field
inventory and historical-reader policy.

The PPS-gated ratio backend does not require a new raw-row schema: `CNT` rows
still use `count_observations_v1`, and `pps_gate` telemetry is ordinary
`health_v1` / `STS` status. The Phase 5 host qualification profile is separately
validated by `pps_backend_qualification_config_v2.schema.json`. Version 2
separates blocking digital-architecture screens from non-blocking metrology
characterization references. The v1 schema remains for reproduction of
historical reports. The
authoritative raw-contract notes live in
`data_contracts/count_observations_v1.csv.md`,
`data_contracts/health_v1.csv.md`, and
`docs/50_SOFTWARE/COUNT_OBSERVATION_MEASUREMENT_CONTRACT.md`.

`run_evidence_v1.schema.json` defines the immutable SHA-256 snapshot that binds
a completed run to its manifest, configuration, selected profile, raw evidence,
and manifest-declared artifacts. It is enforced by the host validator.

CX318's `RPH` and `HPR` v1 CSV contracts are executable field lists and
semantic validation in `host.otis_tools.contracts`; their normative field
documentation is `data_contracts/relative_phase_observations_v1.csv.md` and
`data_contracts/phase_estimator_outputs_v1.csv.md`, and
`data_contracts/hybrid_preview_decisions_v1.csv.md`. They do not use a JSON
Schema because CSV header and row validation is the repository convention for
serial products.
