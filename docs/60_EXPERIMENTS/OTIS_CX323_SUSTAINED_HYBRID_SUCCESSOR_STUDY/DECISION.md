# CX323 successor selection

The selected successor is
`cx323_phase_priority_persistent_cap_tagged_debt_v1`. Selection is based on
`OTIS_CX323_SUSTAINED_HYBRID_SUCCESSOR_STUDY_V2` at semantic SHA-256
`20b729dce477349704ce09e7cacf14047525450d50230c8f114f75959289d707`
and the immutable comparison report at semantic SHA-256
`8096abbee3ee8295fc6cb53a6d0c6ca9af876bf529d464521e55776e105fb982`.
The later native maximum-input review found that V2's stated combined-centre
bound omitted the independent `+36` clamped phase term at `INT64_MIN`. The
prospective V3 boundary correction at semantic SHA-256
`32a7f47330404e1cf7ea724517643deff078e74d3e1aa50127c378bced5f4d53`
raises only the checked conversion bound to `332041393326771929124` units. It
does not change candidate behavior, the retained replay, or this selection.

## Options

The unchanged CX322 baseline retained its immediate one-window maintenance
response. On the Attempt 4 post-divergence source frontier it applied
`[-5, -5, +5, -5]`, moved 20 cumulative codes, reversed twice, and reached
`prospective_repeated_alternation`.

The no-debt candidate preserved the unchanged acquisition and phase-material
paths, but required two fresh, contiguous, same-sign maintenance windows and
bounded the request by the conservative no-zero-cross cap. It produced no
application, movement, reversal, or terminal on that same retained frontier.

The tagged-debt candidate used the same persistence and cap while retaining a
bounded signed picocode residual after an exactly propagated application. The
residual carries FLL and PLL provenance, cannot accrue during a hold, and loses
only its PLL component when phase evidence is lost. It also produced no
application, movement, reversal, or terminal on the retained frontier.

## Reason for selection

Both changed candidates passed every common source, deterministic, gain,
identity, fault, chatter, and actuator-cost gate. The discriminating fixture
required two transactions for each. After the first `+5` application, tagged
debt retained `341671780415` picocodes. On the next persistent demand, no-debt
requested `+5` and remained `475213574925` picocodes from the demand; tagged
debt requested `+6` and remained `183114644660` picocodes away. The tagged
candidate therefore retained more accurate sustained correction with no added
transaction or actuator cost in the frozen comparison.

This is a policy-selection result, not physical evidence after divergence.
The standalone native engine is bit-exact with the Python oracle, including
the corrected signed-64 boundary. Exact live-profile integration/build,
operational-path rehearsal, and bench entry remain required before authority.
