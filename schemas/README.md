# Machine-readable schema stubs

This directory is reserved for machine-readable OTIS schemas generated from, or kept in lock-step with, the normative contracts in `data_contracts/`.

At SW0 and SW1 the Markdown contracts remain authoritative. Add JSON Schema, CSVW, or generated firmware and host schema artifacts here only when they are wired into validation tests.

The PPS-gated ratio backend does not require a new machine-readable schema:
`CNT` rows still use `count_observations_v1`, and `pps_gate` telemetry is
ordinary `health_v1` / `STS` status. The authoritative notes live in
`data_contracts/count_observations_v1.csv.md`,
`data_contracts/health_v1.csv.md`, and
`docs/50_SOFTWARE/COUNT_OBSERVATION_MEASUREMENT_CONTRACT.md`.
