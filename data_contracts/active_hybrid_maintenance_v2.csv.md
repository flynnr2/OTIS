# active_hybrid_maintenance_v2.csv

`AHM` schema version 2 is the decision-bearing adaptive-hybrid controller-state
chronology. It makes persistence, requalification, outstanding transactions,
and provenance-tagged FLL/PLL correction debt independently replayable.

Rows form one strictly ordered event stream beginning with policy activation.
Every row binds the run, build, image, policy, estimator, accepted-span source epoch and ordinal range,
exact event timestamp and time domain. Decision and transaction events bind
their complete exact `AHY` and `ACT` record sequences. Before/after fields preserve
the controller state, persistence count, correction debt, request/response
state, GNSS metadata hold, and causal requalification frontier.

Debt may be committed only after an exact application and its first dependent
consumer. A recoverable GNSS metadata anomaly holds authority while preserving
the confirmed DAC code and valid estimator/phase history; it is not a terminal
or an instruction to discard canonical observations.

The host replays the active policy across the entire `AHM` chronology. Missing,
duplicated, out-of-order, identity-mismatched, or numerically divergent rows
invalidate maintenance replay. Serialized `AHM` evidence is always
`actionable=false` and never grants actuation authority.

Maintenance observations use `source_acceptance_epoch` with explicit opening
and closing accepted-boundary ordinals. GNSS requalification records the
accepted-boundary ordinal at the event; two following contiguous windows must
remain in that acceptance epoch before authority resumes. Ordinal comparisons
follow uint32 modular order, including legal zero after wrap.
