# Machine-readable schemas

This directory contains schemas used by `CX319_EVIDENCE_EPOCH_1`. Executable
CSV field ordering and semantic validation live in
`host/otis_tools/contracts.py`; the matching Markdown contracts live in
`data_contracts/`.

`plant_model_v1.schema.json` remains the structural schema for the deployed
current plant-model document, while `host.otis_tools.plant_model` enforces the
single supported model identity, applicability, evidence, and eligibility.
Schema version 1 remains because it is current, not as a historical-reader
promise.

`run_evidence_v1.schema.json` defines the immutable evidence snapshot required
for every current non-template package. Current raw count, health, relative
phase, phase estimator, hybrid preview, and tight-deadband products continue to
use their deployed v1 wire contracts where applicable.

Retired Phase 4 replay and PPS qualification configuration schemas were
removed. Historical packages use the schemas in their recorded Git revision.
