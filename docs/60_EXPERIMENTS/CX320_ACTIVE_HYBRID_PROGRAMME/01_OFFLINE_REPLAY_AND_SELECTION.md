# CX320 Offline Replay and Policy Selection

## Decision

Select `p21600_cap1_tight_active_v1` and freeze it as
`CX320_BOUNDED_ACTIVE_HYBRID_TIGHT_V1`. It is the least aggressive candidate
tested: a 21,600-second pull-in horizon, `1/600 Hz` phase cap, current tight-band
semantics, one combined request path and the four-application/84-code global
budget.

The corrected immutable local replay report is
`runs/cx320_active_hybrid/materiality_counterfactual_remediation_20260820/active_hybrid_frozen_replay_v2.json`.
Its file SHA-256 is
`aa8a1e35adc70ae3ee6e3b9c5e64587fe35f43331e5a64633e6d96038167c4cb`
and its semantic `report_sha256` is
`4213b70888f8091a7a399f40c17c271813b545d2c6350e3997ecc6c694a8b824`.
The selected policy SHA-256 is
`4c2642cb16335e724d2df669fa5afc188435d52f8023c388ea0a6fac3f9aba5d`.

The original v1 replay is retained as superseded evidence. Its implementation
set the frequency-only counterfactual to zero whenever phase authority was
present instead of replaying the same integer request with only the phase term
removed. That could overstate phase materiality. The v2 replay corrects that
decision-bearing predicate without changing the frozen policy, scientific
thresholds, source evidence or physical observations.

## Frozen-evidence result

All four source streams exercised the progressive checkpoint and respected
step, range, count and cumulative budgets at nominal measured plant gain:

| Source | Applications | Frequency-only | Phase-nonzero | Phase-material | Path (codes) | Terminal |
|---|---:|---:|---:|---:|---:|---|
| Part A mapping | 4 | 2 | 3 | 2 | 22 | clean phase degradation to frequency-only |
| Part B lower | 4 | 1 | 3 | 3 | 36 | hybrid tracking |
| Part B original upper | 4 | 1 | 3 | 3 | 8 | hybrid tracking |
| Part B upper completion | 4 | 3 | 2 | 1 | 24 | hybrid tracking |

There were no modeled range clamps or fail-static terminals. Three source
streams retained at least two material applications; the upper-completion
stream retained one. A phase-nonzero application is not counted as material
unless removing phase and replaying the same rounding and limiting rules
changes the final integer DAC request.
The 10,800-second and double-cap alternatives were retained only as finite
comparisons; neither supplied evidence sufficient to justify its greater
aggression. Sensitivity replay over the measured minimum, nominal and maximum
plant gains stayed within the same global budgets.

The primary modeled phase-slope magnitude improved in Part A, lower Part B and
the original upper stream. It worsened in the separate upper-completion stream.
That mixed counterfactual result is not hidden and is one reason the physical
programme retains a prospective phase-improvement criterion rather than
claiming offline success.

## Claims boundary

Once a modeled code diverges from the recorded physical code, replay projects
frequency and phase using the frozen measured plant-gain envelope. Those values
are modeled, not observed actuator response. The four sources are separate
finite acquisitions and cannot establish an uninterrupted 12-hour result.
Raw phase epochs remain separate; replay never joins them with a guessed
offset. Offline selection therefore supports a bounded physical proposal but
does not establish active phase steering.
