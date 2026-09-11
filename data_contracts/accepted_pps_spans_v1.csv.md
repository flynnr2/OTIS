# accepted_pps_spans_v1.csv

## Status and scope

`APS` version 1 is the current derived D14/D8 accepted-span record. It never
replaces the canonical `REF`, `SNP`, or adjacent `CNT` rows. Each row binds one
accepted D14 interval to its exact cumulative D8 endpoints and to every raw
adjacent count row retained between them.

The immutable span identity is
`(capture_session, acceptance_epoch, accepted_boundary_ordinal)`. The ordinal
names the closing accepted boundary; its opening accepted-boundary ordinal is
the preceding uint32 value. Acceptance epochs never wrap and qualification
must not combine them.

`source_count_record_count` equals `excluded_candidate_count + 1` and names the
inclusive `source_count_first_sequence` through
`source_count_last_sequence` raw range. Every raw association and count in
that range must be present, exact, sequence-continuous, and in the declared
capture session. `counted_edges` equals both the cumulative endpoint delta and
the sum of the retained adjacent counts. `nominal_interval_count` is exactly
one.

The admission coordinate is `rp2040_monotonic_us32`. It selects the closing
endpoint under the policy named by `acceptance_policy_sha256`; it is not a
frequency denominator. An APS row is emitted only for an accepted span.
Excluded candidates remain visible in the raw rows and in
`excluded_candidate_count`.

A recorder that attaches after acquisition may treat the opening endpoint of
its first fully retained APS as a producer-declared evidence horizon. This
does not claim that the recorder retained the epoch's original acquisition.
Only complete APS rows whose entire raw source range is retained may enter a
600-span estimator source.
