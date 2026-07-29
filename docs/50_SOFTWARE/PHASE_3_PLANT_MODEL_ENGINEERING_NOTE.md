# Phase 3 Plant-Model Engineering Note

## Decision

Phase 3 promotes completed H1 evidence into
`profiles/plant_models/cx317_h1_bench_v2.json`, model version 3. The model is
validated for observe-only use and explicitly remains ineligible for
actuation:

```text
control_ready=false
actuation_enabled=false
```

The historical Run 017-era `cx317_h1_bench_v1.json` remains unchanged for
replay and provenance.

## Evidence basis

The model combines three distinct evidence roles:

- Run 018: connected DAC-code-to-CX317-control-voltage DMM fit
- Run 019: broad monotonicity, approximate linearity, and broad gain
- Run 020: direct local crossing bracket, drift-cancelled gain, repeatability,
  settling, diagnostic integrity, and final restore

Run 020 is sealed and validates without errors. Its only validator warning is
the intentionally header-only generic EVT stream.

## Envelope semantics

The model keeps three meanings separate:

| Range | Value | Meaning |
|---|---:|---|
| Crossing uncertainty | `0xA840..0xAA00` | Conservative within-run location of 10 MHz |
| Candidate automatic range | `0xA800..0xAB00` | Narrow range containing the crossing band; recorded for observe-only design, not enabled |
| Local applicability/manual range | `0xA800..0xB400` | Run 020 codes over which the local model was exercised |

The nominal model code is the rounded crossing estimate `0xA950`. The
historical `0x8000` restore code remains an operator fail-static/restoration
policy value, not the 10 MHz operating point.

Firmware characterization clamps such as `0x6000..0xFC00` are not automatic
control limits.

## Code and contract changes

The schema now optionally represents crossing, repeatability, and applicability
without changing `schema_version: 1` or invalidating historical models.

Host validation no longer hard-codes the obsolete `0x7000..0x9000` range.
Instead it deterministically enforces:

- H1 `control_ready` and `actuation_enabled` remain false
- nominal code is inside the candidate automatic range
- candidate automatic range is inside the manual-safe range
- candidate automatic range contains the crossing uncertainty band
- candidate automatic range is inside the explicit model applicability range
- applicability mode is `observe_only`
- slope sign and non-zero-gain rules remain intact

No telemetry, raw-evidence, capture, estimator, or firmware contract changes
are made.

## Evidence preservation and replay

- Phase 3 does not rewrite raw Run 018, Run 019, or Run 020 evidence.
- Run 020 count sequence 77 remains present and is explicitly excluded only
  from settled final-centre interpretation.
- Source run IDs, artifacts, commits, versions, limitations, and invalidation
  conditions are embedded in the model.
- Historical model v2 and the new model v3 can both be loaded by the same host
  API and CLI.

## Risk assessment

| Risk | Assessment and mitigation |
|---|---|
| Candidate range mistaken for permission to actuate | Both readiness Booleans remain false; validator rejects attempts to enable them |
| Run 020 voltage treated as directly measured | Model records `measured_control_voltage_at_nominal_v=null` and identifies the Run 018 fit |
| Crossing precision overstated | Model records `0xA950` plus the broader `0xA840..0xAA00` within-run band and its limited uncertainty scope |
| Final restore contaminates the last dwell | Count sequence 77 is preserved and explicitly excluded |
| Hysteresis overstated | Endpoint bidirectional hysteresis is recorded as unresolved |
| Settling used as a finely resolved time constant | Applicability records 300 s gate quantization and a conservative 900 s exclusion |
| Thermal compensation inferred from air temperature | Thermal model remains unresolved and is an invalid use |
| Historical replay changes | The v1 filename/model-version-2 artifact is preserved unchanged |
| Characterization limits leak into control policy | Firmware clamps, local applicability, and candidate automatic range remain separate |

## Handoff

Phase 3 is complete when the new model, validator tests, documentation, and
repository test suite pass. The handoff is ready for SW2 observe-only estimator
and correction-preview work. It is not a handoff to active DAC steering.
