# active_hybrid_decisions_v3.csv

`AHY` schema version 3 is the sole current adaptive-hybrid decision record.
Each row carries the complete controller decision and its exact
`decision_timestamp_ticks` in `rp2040_monotonic_us64`; there is no separate
timing record or compatibility product.

The exact field order is `ACTIVE_HYBRID_DECISION_V3_FIELDS` in
`host/otis_tools/contracts.py`. `hybrid_record_sequence` is strictly increasing.
Run, build, image, estimator, policy, capture-session, accepted-span session, acceptance-epoch and accepted-boundary source,
phase, applied-code and DAC-epoch identities bind the complete decision.

`decision_timestamp_s` remains an explicit derived controller-policy input.
It must not replace the exact lifecycle timestamp in ordering or elapsed-time
checks.

The record preserves progressive state, frequency and phase terms, combined
demand, integer request, frequency-only counterfactual, limiting decisions,
transaction frontier and response identity. D14 is the sole PPS/reference
authority and D8 is the sole oscillator/count input. D10 never enters AHY
validity or authority.

AHY is evidence only and always `actionable=false`. Physical actuation requires
the separately recorded exact ACT transaction.

The source coordinate is explicit: `source_acceptance_epoch` plus opening and
closing accepted-boundary ordinals identify the same 600 APS window as the
selected EST. Accepted ordinals use uint32 modular order; an ordinal of zero is
valid after wrap and does not denote a missing source.
