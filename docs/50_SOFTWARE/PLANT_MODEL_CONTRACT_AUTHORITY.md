# Plant-Model Contract Authority and Field Inventory

## Authority

`schemas/plant_model_v1.schema.json` is the only structural authority for
`schema_version: 1`. Every object boundary remains closed with
`additionalProperties: false`. Host code always runs that schema before
semantic validation.

The five decisions are deliberately separate:

1. **Structural validity**: field names, required fields, types, closed
   objects, formats, and schema version. JSON Schema decides this.
2. **Semantic validity**: cross-field range ordering, sign consistency,
   provenance completeness, estimator-contract internal consistency, and
   model-version requirements. `validate_plant_model_semantics()` decides this
   without redefining structure. It does not compare the artifact with the
   estimator in the currently installed software.
3. **Evidence availability**: whether every declared source artifact is
   present in the repository or evidence workspace. Missing evidence is
   reported separately and does not rewrite artifact validity.
4. **Applicability**: whether topology, backend, executed estimator, DAC input,
   source-run exclusions, gate, and temperature agree with the model's stated
   scope. A self-consistent artifact for a future estimator therefore remains
   valid but is not applicable to the current executable.
5. **Control eligibility**: a conservative final gate requiring control-ready
   and actuation-enabled status, available evidence, applicable and fully
   observed inputs, and no unresolved fields.

Therefore a valid model is not necessarily applicable, and an applicable model
is not necessarily eligible for control. The committed H1 models are valid but
not control-eligible.

## Field classification

The tables below inventory every v1 field. Braces enumerate actual child fields;
`[]` means array items. "Required" refers to JSON structure. A derived field is
still normative once recorded: the schema defines its representation and
semantic validation checks its relationships.

### Identity, status, oscillator, and topology

| Classification | Required | Field path |
|---|---:|---|
| normative | yes | `schema_version` |
| normative | yes | `model_id` |
| normative | yes | `model_version` |
| normative | yes | `status` |
| normative | yes | `status.{control_ready,actuation_enabled,readiness}` |
| normative | yes | `oscillator` |
| normative | yes | `oscillator.{part,type,nominal_frequency_hz,supply_voltage_v,pinout_source}` |
| normative | yes | `oscillator.control_voltage_range_v.{min_v,max_v}` |
| historical, deprecated | no | `oscillator.datasheet_tuning_range_ppm` |
| historical, derived, deprecated | with historical object | `oscillator.datasheet_tuning_range_ppm.{min_abs_ppm,max_abs_ppm,control_voltage_min_v,control_voltage_nominal_v,control_voltage_max_v,implied_hz_per_v_min,implied_hz_per_v_max}` |
| normative | yes | `hardware_topology` |
| normative | yes | `hardware_topology.{topology_id,board}` |
| normative | yes | `hardware_topology.power_path` |
| normative | yes | `hardware_topology.power_path.{description,dirty_supply_source,clean_supply_node,filtering,measured_dirty_voltage_v,measured_clean_voltage_v,measured_clean_ripple_mvpp}` |
| normative | yes | `hardware_topology.conditioning` |
| normative | yes | `hardware_topology.conditioning.{oscillator_output_conditioner,rp2040_pin,logic_voltage_v}` |
| historical, deprecated | no | `hardware_topology.pps_witness` |
| historical, derived, deprecated | with historical object | `hardware_topology.pps_witness.{primary_ref_pin,witness_pin,run_017_final_d14_raw_count,run_017_final_d10_raw_count,run_017_d14_minus_d10_delta,d10_short_rows,d10_buffer_overflow_rows,d10_burst_rows}` |

### DAC and control path

| Classification | Required | Field path |
|---|---:|---|
| normative | yes | `dac` |
| normative | yes | `dac.{part,resolution_bits,interface,i2c_address,reference_voltage_v,gain_mode,nominal_code,manual_preview_max_step_codes}` |
| normative | yes | `dac.manual_safe_range_codes.{min,max}` |
| normative policy candidate | yes | `dac.automatic_control_range_codes.{min,max}` |
| normative | yes | `control_path` |
| normative | yes | `control_path.{network,measured_control_voltage_at_nominal_v,estimated_v_per_code,voltage_model}` |
| normative | yes | `control_path.measured_connected_voltage_span_v.{min_v,max_v}` |

`automatic_control_range_codes` is a bounded candidate range, not permission to
actuate. Semantic validation requires it to remain inside both the manual-safe
and applicability ranges and to contain the crossing uncertainty band.

### Plant response

| Classification | Required | Field path |
|---|---:|---|
| normative | yes | `plant_response` |
| derived | yes | `plant_response.local_slope.{hz_per_v,ppm_per_v,hz_per_code,ppm_per_code,sign,sample_count}` |
| derived | yes | `plant_response.local_slope.uncertainty.{method,hz_per_v_min,hz_per_v_max}` |
| derived | for model version 3+ | `plant_response.local_slope.uncertainty.{hz_per_v_stdev,hz_per_v_iqr}` |
| historical, derived, deprecated | no | `plant_response.local_slope.uncertainty.{hz_per_v_span,positive_0x0800_hz_per_v,negative_0x0800_hz_per_v,positive_0x1000_hz_per_v,negative_0x1000_hz_per_v}` |
| normative evidence boundary | yes | `plant_response.valid_neighborhood.{basis,center_code,target_codes[]}` |
| normative evidence boundary | yes | `plant_response.valid_neighborhood.voltage_span_v.{min_v,max_v}` |
| normative evidence boundary | yes | `plant_response.settling_evidence.{characterized,method,settling_discard_s,t95_s_min,t95_s_max,selected_control_cadence_s}` |
| normative evidence boundary | yes | `plant_response.temperature_range_c.{min_c,max_c}` |
| normative evidence boundary | yes | `plant_response.warmup_drift.{warmup_s,drift_after_warmup_ppm_per_hour}` |
| optional, derived | no; required semantically for model version 3+ | `plant_response.crossing_estimate` |
| optional, derived | with crossing object | `plant_response.crossing_estimate.{target_frequency_hz,code,code_min,code_max,estimated_voltage_v,estimated_voltage_min_v,estimated_voltage_max_v,method,uncertainty_scope}` |
| optional, derived | with crossing object | `plant_response.crossing_estimate.observed_bracket.{below_code,below_frequency_hz,above_code,above_frequency_hz}` |
| optional, derived | no; required semantically for model version 3+ | `plant_response.repeatability_evidence` |
| optional, derived | with repeatability object | `plant_response.repeatability_evidence.{center_code,clean_center_dwell_count,center_median_min_hz,center_median_max_hz,center_span_hz,center_stdev_hz,up_down_center_delta_hz,endpoint_bidirectional_hysteresis_measured}` |
| optional normative applicability | no; required semantically for model version 3+ | `plant_response.applicability` |
| optional normative applicability | with applicability object | `plant_response.applicability.{mode,measurement_backend,gate_duration_s,settling_exclusion_s,excluded_count_sequences[],limitations[]}` |
| optional normative applicability | with applicability object | `plant_response.applicability.dac_code_range.{min,max}` |
| optional normative applicability | with applicability object | `plant_response.applicability.temperature_range_c.{min_c,max_c}` |
| optional normative applicability | no; required semantically for model version 4+ | `plant_response.applicability.estimator_method_contract` |
| optional normative applicability | with estimator contract | `plant_response.applicability.estimator_method_contract.{boundary_interpolation,count_window_semantics,estimator_method_id,extrapolation_policy,measurement_backend,method_definition_hash,reference_acceptance,reference_interval_max_s,reference_interval_min_s,reference_invalid_flag_mask,reference_time_mapping,required_timing_domain}` |

### Explicit historical Run 017 fields

These fields preserve the original Run 017 record. They are structurally
declared rather than admitted by an open-object escape hatch. New model
versions must not emit them, and control eligibility never depends on them.

| Classification | Required | Field path |
|---|---:|---|
| historical, derived, deprecated | no | `plant_response.observed_frequency_range` |
| historical, derived, deprecated | with historical object | `plant_response.observed_frequency_range.{min_code,min_output_mhz,max_code,max_output_mhz,span_hz}` |
| historical, derived, deprecated | no | `plant_response.run_017_settled_outputs_mhz[]` |
| historical, derived, deprecated | with historical item | `plant_response.run_017_settled_outputs_mhz[].{dac_code_hex,dac_code,output_mhz}` |
| historical, derived, deprecated | no | `plant_response.reference_integrity` |
| historical, derived, deprecated | with historical object | `plant_response.reference_integrity.{ref_rows,ref_raw_duration_s,timestamp_wrap_count,raw_timestamp_monotonic,unwrapped_timestamp_monotonic,host_pps_anomalies,d14_rejected_long_count,d14_rejected_long_count_interpretation}` |
| historical, derived, deprecated | no | `plant_response.startup_control_eligibility` |
| historical, derived, deprecated | with historical object | `plant_response.startup_control_eligibility.{fc0_valid_for_control,fc0_fault,count_windows,invalid_count_windows,first_control_eligible_elapsed_s}` |

### Provenance, invalidation, and unresolved references

| Classification | Required | Field path |
|---|---:|---|
| normative provenance | yes | `source_evidence` |
| normative provenance | yes | `source_evidence.source_run_ids[]` |
| normative provenance | yes | `source_evidence.source_artifacts[]` |
| normative provenance | yes | `source_evidence.source_commits` |
| normative provenance | yes | `source_evidence.source_commits.{run_manifest_host_git_commit,run_manifest_firmware_git_commit}` |
| normative provenance | exactly one creation field | `source_evidence.source_commits.model_created_from_repo_commit` |
| historical, deprecated provenance alias | exactly one creation field | `source_evidence.source_commits.model_updated_from_repo_commit` |
| normative provenance | yes | `source_evidence.source_versions.{run_manifest_host_tool_version,run_manifest_firmware_version}` |
| normative | yes, at least one item | `invalidation_conditions[]` |
| normative unresolved-reference list | yes, may be empty | `unresolved_fields[]` |

Commit identifiers are lowercase, full 40-hex object names or `null`. Artifact
references are non-empty repository-relative paths and may not traverse above
the repository. At least one commit and one version must be known for semantic
validity.

Paths named only as strings in `unresolved_fields[]` are not model fields.
For example, `plant_response.thermal_model` and
`control_policy.maximum_update_codes` remain unsupported in schema v1.
Every field not listed above is unsupported and rejected; adding a future field
requires a new schema version or an explicit, closed schema extension.

## Historical policy

The repository retains `cx317_h1_bench_v1.json` as the exact historical reader
case `(schema_version=1, model_id=cx317_h1_bench, model_version=2)`. Its seven
historical structures and
`model_updated_from_repo_commit` spelling are now explicit, closed, deprecated
schema properties. This preserves the committed evidence without pretending
those fields are current control inputs. `additionalProperties` was not
relaxed. The model-version 3 and 4 artifacts use current fields. Reusing those
deprecated properties or the legacy provenance alias in any other identity,
including a newly created model-version 1 or 2 artifact, is a semantic error.

No historical field is copied into the firmware binding. New artifacts must
use `model_created_from_repo_commit`; the legacy spelling exists only for the
committed Run 017 model.

## Validation-path reconciliation

Before this reconciliation:

| Artifact | JSON Schema path | Python loader | Phase-4 replay | Firmware binding |
|---|---|---|---|---|
| file `v1`, model version 2 | rejected: undeclared historical fields, legacy commit-name disagreement, current uncertainty requirements | accepted | accepted as valid, then not applicable because it was not model version 4 | not bound |
| file `v2`, model version 3 | accepted | accepted | accepted as valid, then not applicable because it was not model version 4 | not bound |
| file `v3`, model version 4 | accepted | accepted | accepted and context-checked | constants were hand-copied and tested by text search |

The Python path previously did not execute JSON Schema, so unknown fields could
pass Python even though schema rejected them. It also compared only the
estimator definition hash rather than the complete executed-method contract.

After reconciliation, all three committed files pass the same JSON Schema and
semantic validator. Semantic validation verifies that the estimator definition
hash describes the contract stored in that artifact and that its nested
measurement backend equals the outer applicability backend. Replay uses the
shared applicability assessor to compare that valid contract with the
currently executed estimator.

The firmware generator first requires a structurally and semantically valid
artifact, then separately refuses to bind it unless its estimator contract
exactly matches the estimator compiled by the current source. The generated
header embeds the artifact's exact byte hash plus topology, mode, outer
measurement backend, gate duration, settling exclusion, temperature limits,
source-run count exclusions, estimator constraints, and DAC ranges. It is
checked byte-for-byte by tests:

```sh
python3 tools/generate_plant_model_binding.py --check
```

At runtime the observe-only preview compares the generated topology, mode,
backend, configured and observed gate duration, estimator constraints, DAC
range, settling time after an observed DAC change, and available near-VCXO
temperature with compiled or observed values. Source-run count exclusions are
only meaningful when replaying the declared source evidence; an unrelated live
count sequence with the same integer is not excluded.

The runtime has no persistent provenance attestation for the physical topology,
sensor placement, source evidence, or DAC state before boot, and the current
temperature input has no freshness timestamp or stale-age bound. An unavailable
near-VCXO temperature is explicitly unverified rather than silently considered
measured; this is acceptable for the disabled observe-only preview but remains
a control-eligibility blocker. The generated binding does not make evidence
available, make the model applicable to arbitrary inputs, or authorize control.
