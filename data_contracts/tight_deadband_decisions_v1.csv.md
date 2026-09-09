# tight_deadband_decisions_v1.csv

`TDB` records are zero-authority integer-count deadband decisions derived from
current D14-gated D8 count evidence. They preserve the exact estimate and policy
identities used by host replay and cannot request, authorize, or consume an
actuation.

The band-membership fields are ordered and defined as follows:

1. `three_count_band_inside` is `true` exactly when the absolute count error is
   no greater than three counts.
2. `two_count_band_inside` is `true` exactly when the absolute count error is
   no greater than two counts.

The host validator recomputes both predicates. Retired field names are not
aliases and are rejected by the exact header check.

Every row also binds the selected estimate, policy SHA-256, time domain,
decision sequence, eligibility, reason, and zero-authority booleans. Unknown or
cross-domain inputs must produce an inhibited decision rather than a fabricated
in-band result.
