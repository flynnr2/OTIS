# Plant Model v1

`plant_model_v1` is the host-side, machine-readable contract for an H1/SW2
oscillator control-path model. It records evidence-backed plant behavior and
safety envelopes without treating hand-coded firmware constants as an
independent authority.

The contract is intentionally conservative:

- unknown values are encoded as JSON `null`, not `0` or empty strings;
- the automatic-control range is a separate field from manual or
  characterization ranges;
- `actuation_enabled` must be `false` for H1-derived models until a later SW2
  control gate explicitly authorizes actuation;
- source runs, commits, tool versions, caveats, and invalidation conditions are
  part of the model, not report prose.

The machine-readable schema lives at:

```text
schemas/plant_model_v1.schema.json
```

That JSON Schema is the single structural authority. The exhaustive field
classification, historical-field policy, and pre-reconciliation validator
disagreements are recorded in
`docs/50_SOFTWARE/PLANT_MODEL_CONTRACT_AUTHORITY.md`. Host loading always runs
schema validation first. Cross-field semantic validation, evidence
availability, applicability, and control eligibility are separate decisions;
success at one layer does not imply success at a later layer.

Initial H1 plant models live under:

```text
profiles/plant_models/
```

## Required Top-Level Fields

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | integer | Contract version. Must be `1`. |
| `model_id` | string | Stable model identity. |
| `model_version` | integer | Monotonic semantic version for this model. |
| `status` | object | Readiness and actuation status. |
| `oscillator` | object | Oscillator identity and nominal frequency. |
| `hardware_topology` | object | Bench wiring, power path, and conditioning identity. |
| `dac` | object | DAC identity, reference, gain, nominal code, and ranges. |
| `control_path` | object | DAC-to-oscillator control-node wiring and voltage model. |
| `plant_response` | object | Measured local slope, uncertainty, validity neighborhood, settling evidence, and temperature span. |
| `source_evidence` | object | Runs, artifacts, commits, and tool versions used. |
| `invalidation_conditions` | array | Conditions that make the model invalid until reviewed. |
| `unresolved_fields` | array | Explicit list of fields that remain unknown or unresolved. |

## Safety Semantics

`dac.manual_safe_range_codes` records the manually checked bench range.
`dac.automatic_control_range_codes` records the range a future controller may
consider. These ranges are deliberately independent. Run 020 supports the
observe-only version-4 model's local applicability range `0xA800..0xB400`, crossing
band `0xA840..0xAA00`, and candidate automatic range `0xA800..0xAB00`.
The candidate range is recorded for deterministic preview and policy design;
it is not permission to actuate.

`status.control_ready` means the model is sufficient for automatic control.
`status.actuation_enabled` means software may apply DAC updates. The initial H1
CX317 models must keep both false because Phase 3 hands off to observe-only.
`cx317_h1_bench_v1.json` retains the earlier Run 017 range as historical model
evidence. `cx317_h1_bench_v2.json` preserves the pre-correction version-3
model. `cx317_h1_bench_v3.json` is the current Run 020-backed version-4 model
and adds the exact `LOCAL_PPS_BOUNDARY_INTERPOLATED_V1` applicability contract.

Optional `plant_response.crossing_estimate`,
`plant_response.repeatability_evidence`, and
`plant_response.applicability` fields make the model's evidence boundary
machine-readable. When present, host validation requires the candidate
automatic range to contain the crossing band and remain within the model's
manual-safe and applicability ranges.

Version-4 applicability also requires a complete estimator-method contract:
identity/version, measurement backend, count-window semantics, independent
boundary mapping, PPS acceptance rules, timing domain, extrapolation policy,
and a definition hash. Semantic validation verifies that the definition hash
matches the contract recorded in the artifact and that the nested and outer
measurement backends agree. It deliberately does not require equality with the
currently installed estimator: a self-consistent artifact describing an
evolved estimator is valid. Runtime applicability compares the artifact
contract with the compiled/executed estimator and reports such an artifact as
not applicable; a manifest string alone cannot make it applicable.

The Phase-4 firmware constants are generated from the exact validated current
artifact rather than copied by hand:

```text
tools/generate_plant_model_binding.py
firmware/arduino/otis_nano_rp2040_connect/otis_plant_model_v4_generated.h
```

The generated header records the artifact path, exact byte hash, schema/model
versions, topology, applicability mode, outer measurement backend, gate and
settling durations, temperature limits, source-run exclusions, estimator
constraints, gain, and DAC ranges. Generation fails unless structural and
semantic validation pass and separately refuses an artifact whose estimator
does not match the current firmware implementation. The live preview compares
those generated values with compiled and observed runtime values. Unknown
near-VCXO temperature remains an unverified applicability condition; it is not
invented as an in-range measurement. The generated `control_ready` and
`actuation_enabled` values remain false; a compiled binding does not authorize
actuation.

## Historical v1 Reader

The exact historical identity `(schema_version=1,
model_id=cx317_h1_bench, model_version=2)` includes measurement summaries that
predate the current field layout. They are retained as explicit closed schema
properties marked deprecated, including the legacy
`source_commits.model_updated_from_repo_commit` spelling. New artifacts must
not emit these fields, even if they choose model version 1 or 2. Unknown fields
remain rejected at every object boundary; `additionalProperties` is not
relaxed for historical compatibility.

## Unknown Values

Use JSON `null` for unknown values. Empty strings are invalid because they are
ambiguous in downstream validation and telemetry.
