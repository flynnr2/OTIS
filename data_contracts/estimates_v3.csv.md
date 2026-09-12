# estimates_v3.csv

`EST` version 3 is the current estimator contract. It retains the version 2
numeric, diagnostic, uncertainty, and zero-authority semantics while replacing
the ambiguous raw-adjacent source fields with an explicit accepted-span source.

A selected estimate binds one capture session and one acceptance epoch. Its
opening and closing accepted-boundary ordinals delimit exactly
`accepted_sample_count` APS rows; the selected estimator requires 600. The raw
snapshot and D14 source fields equal the first APS opening and last APS closing
endpoints. `estimator_timestamp_ticks` equals that closing APS timestamp.

`source_accepted_spans_ref` has the exact form
`live:APS:<capture_session>:<acceptance_epoch>:<opening>:<closing>`. It is a
source identity, not authority. EST remains derived evidence and cannot request
or perform actuation.

## Estimator roles and replay scope

`OTIS_PPS_GATED_FREQUENCY_ESTIMATOR_V1` is the selected estimator. Its rows
use non-overlapping 600-span apertures and are the only EST rows eligible to
supply selected-frequency or active-decision source identity.

`accepted_reference_frequency_diagnostic_60s_overlap_v1` is an explicit
zero-authority diagnostic. Each row reconstructs the same accepted-reference
frequency calculation over exactly 60 APS rows and declares
`preview_eligibility=false` with
`eligibility_reason_codes=diagnostic_non_authoritative`. Its apertures may
overlap. Missing or rejected diagnostic rows affect only diagnostic replay;
they do not change canonical D14/D8 replay, selected-estimator replay, control
eligibility, or actuation.

EST serialization integrity remains a dataset-wide property: `estimate_seq`
must be contiguous and `estimate_id` must be unique across selected and
diagnostic rows. Replay reports that separately from each estimator's semantic
result. An unrecognized `estimator_version` is an explicit semantic
contradiction rather than a selected source, and it cannot satisfy a selected
estimate or active-decision reference.

Replay also compares `frequency_observation_hz` with the same reconstructed
binary64 frequency used by `frequency_estimate_hz`, at the fixed twelve-place
serialization tolerance. `source_status_refs` names the current producer's
`live:STS:pps_gate` namespace; it is not a unique status-generation reference
and does not establish a causal status-snapshot join. `source_dac_ref` has the
canonical form `live:DAC:<uint32 epoch>`. A selected estimate consumed by an
AHY decision must name that decision's DAC epoch. Without such a consumer,
replay validates the reference's representation but does not claim independent
confirmation of the applied DAC code.
