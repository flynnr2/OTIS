# Plant Model v1

`plant_model_v1` is the host-side, machine-readable contract for an H1/SW2
oscillator control-path model. It records evidence-backed plant behavior and
safety envelopes without putting plant constants in firmware.

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
consider. For the first CX317 H1 bench model, host validation requires the
automatic range to be no wider than `0x7000..0x9000`.

`status.control_ready` means the model is sufficient for automatic control.
`status.actuation_enabled` means software may apply DAC updates. The initial H1
CX317 model must keep both false because the readiness documents do not
authorize closed-loop actuation from `run_014`.

## Unknown Values

Use JSON `null` for unknown values. Empty strings are invalid because they are
ambiguous in downstream validation and telemetry.
