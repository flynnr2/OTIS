# estimates_v2.csv

## Status and scope

Normative Phase 4 estimator contract for deterministic host replay and live
observe-only firmware. Version 2 corrects the version-1 field that labelled
sample dispersion as frequency uncertainty. Historical version-1 rows retain
their documented meaning and are never silently reinterpreted.

`EST` records are derived metrology products. They cannot authorize or perform
actuation.

## Uncertainty semantics

`dispersion_hz` is the population standard deviation of the accepted estimator
window. It describes sample spread only.

The uncertainty component fields are standard uncertainties. A combined value
is emitted only when every component required by the identified uncertainty
model is available and the correlation policy is explicit. Otherwise
`uncertainty_status` is `incomplete` or `unavailable`, the combined and expanded
values are empty, and `uncertainty_reason_codes` explains why.

Zero dispersion does not imply zero uncertainty. Unknown contributions are
empty, never zero.

The implemented correlation policies are:

- `single_component_no_correlation`, for an identified model with exactly one
  required component;
- `independent_root_sum_square`, for two or more components explicitly
  declared independent by the identified model;
- `not_combined_missing_components`, when no combined value may be emitted.

Other correlation assumptions are rejected. For an available budget, the
validator recomputes the declared combination and, when present, checks that
expanded uncertainty equals combined uncertainty times the positive coverage
factor. `uncertainty_model_ref` includes the SHA-256 of the required-component
list and combination policy.

## Fields

Version 2 retains the version-1 provenance, validity, estimate, drift, and
eligibility fields except `frequency_uncertainty_hz`, and adds:

| Field | Meaning |
|---|---|
| `dispersion_hz` | Population dispersion of accepted samples; not uncertainty. |
| `uncertainty_status` | `available`, `incomplete`, or `unavailable`. |
| `uncertainty_reason_codes` | Stable explanation, or `uncertainty_complete`. |
| `count_quantization_standard_uncertainty_hz` | Count-quantization contribution when an explicit distribution model exists. |
| `counter_aperture_standard_uncertainty_hz` | Physical counter-aperture contribution. |
| `reference_standard_uncertainty_hz` | Reference contribution projected into frequency units. |
| `calibration_standard_uncertainty_hz` | Calibration or independent-instrument contribution. |
| `model_standard_uncertainty_hz` | Estimator/model contribution not already represented. |
| `combined_standard_uncertainty_hz` | Combined standard uncertainty when complete. |
| `coverage_factor` | Positive coverage factor when expanded uncertainty is emitted. |
| `expanded_uncertainty_hz` | Combined uncertainty multiplied by the declared coverage factor. |
| `correlation_policy` | Versioned treatment of component correlation. |
| `uncertainty_model_ref` | Exact uncertainty-model/configuration identity or explicit unavailable reference. |

All other fields retain their version-1 definitions. `drift_enabled=false`,
`preview_only=true`, and the observe-only control boundary remain unchanged.
