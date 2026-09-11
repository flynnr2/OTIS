# relative_phase_observations_v2.csv

`RPH` version 2 is the current immutable relative-phase observation. Each
qualified row consumes exactly one APS and preserves that span's capture
session, acceptance epoch, accepted-boundary ordinal, raw SNP endpoints, raw
D14 source endpoints, and exact D8 edge count.

`source_accepted_span_ref` is exactly
`live:APS:<capture_session>:<acceptance_epoch>:<accepted_boundary_ordinal>`.
Excluded raw candidates do not independently advance or invalidate phase; an
acceptance loss opens a new phase and acceptance boundary and cannot be joined
to an earlier epoch.
