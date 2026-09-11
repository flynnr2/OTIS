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
