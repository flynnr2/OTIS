# Measurement Uncertainty Semantic Inventory

## Decision

Current producers use `estimates_v2`. Historical `estimates_v1` remains
readable, but its `frequency_uncertainty_hz` field is explicitly a legacy
population-dispersion label and is not promoted into a version-2 uncertainty
claim.

## Repository meanings

The companion
`derived/measurement_semantics_usage_inventory.csv` is the exhaustive,
line-addressed inventory of every repository use of uncertainty, dispersion,
standard deviation, confidence, error-bound, and coverage-factor terminology.
It is generated and checked by `tools/audit_measurement_semantics.py`; a stale
inventory fails the test suite.

| Surface | Quantity | Classification | Policy |
|---|---|---|---|
| Phase 4 estimator window | `dispersion_hz` / population standard deviation | Sample dispersion | Retain as an estimator consistency statistic. |
| Phase 4 `maximum_dispersion_hz` | Configured spread limit | Qualification threshold | Retain name and behavior; do not call uncertainty. |
| H1 characterization `stddev_*`, MAD, IQR, span | Repeated-observation spread | Sample dispersion/repeatability | Retain descriptive statistical names. |
| Phase 5 count resolution | One oscillator edge | Quantization resolution | A standard uncertainty requires an explicit distribution model; otherwise unavailable. |
| Phase 5 counter aperture | Physical boundary/snapshot behavior | Systematic/aperture contribution | Unavailable until measured or calibrated. |
| GNSS/reference contribution | Reference frequency/timing authority | Reference contribution | Unavailable without evidence-backed receiver/reference qualification. |
| Independent counter/DMM evidence | Comparison/calibration contribution | Calibration/independent-instrument uncertainty | Use only within its declared interval and provenance. |
| Plant local-slope spread/range | Model/fit contribution | Model uncertainty or dispersion, according to named field | Do not copy into measurement uncertainty without a versioned propagation model. |
| `estimator_confidence` | Categorical estimator qualification | Confidence state | Distinct from statistical confidence and measurement uncertainty. |
| `diagnostic_confidence` | Confidence in a diagnostic conclusion | Diagnostic confidence | Distinct from measurement uncertainty. |

## Combination rule

`combined_standard_uncertainty_hz` is available only when the identified
uncertainty model declares its required components, each required component is
available, units and applicability agree, and correlation treatment is
explicit. Expanded uncertainty additionally requires an explicit positive
coverage factor.

Missing evidence produces `incomplete` or `unavailable`; it never produces
zero. No control threshold is derived from this migration.

The implemented policies are `single_component_no_correlation` and
`independent_root_sum_square`. The latter is valid only for components that the
identified model declares independent. Any missing required component produces
`not_combined_missing_components`; no correlated combination is silently
assumed. The model reference hashes its required-component list and combination
policy.
