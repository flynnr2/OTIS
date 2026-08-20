# CX320 Offline Replay and Policy Selection

## Decision

Select `p21600_cap1_tight_active_v1` and freeze it as
`CX320_BOUNDED_ACTIVE_HYBRID_TIGHT_V1`. It is the least aggressive candidate
tested: a 21,600-second pull-in horizon, `1/600 Hz` phase cap, current tight-band
semantics, one combined request path and the four-application/84-code global
budget.

The immutable local replay report is
`runs/cx320_active_hybrid/frozen_replay_20260820/active_hybrid_frozen_replay_v1.json`.
Its file SHA-256 is
`7138b10f43db35473295d2618836aeaf6ccffaf9942b56c426df4c470dcdad53` and
its semantic `report_sha256` is
`649cd9422f276dee09c6fbbacbc481a8529fed1a6cfbebd67fe5f49bd5c0825c`.
The selected policy SHA-256 is
`4c2642cb16335e724d2df669fa5afc188435d52f8023c388ea0a6fac3f9aba5d`.

## Frozen-evidence result

All four source streams exercised the progressive checkpoint and respected
step, range, count and cumulative budgets at nominal measured plant gain:

| Source | Applications | Frequency-only | Phase-material | Path (codes) | Terminal |
|---|---:|---:|---:|---:|---|
| Part A mapping | 4 | 1 | 3 | 22 | clean phase degradation to frequency-only |
| Part B lower | 4 | 1 | 3 | 36 | hybrid tracking |
| Part B original upper | 4 | 1 | 3 | 8 | hybrid tracking |
| Part B upper completion | 4 | 2 | 2 | 24 | hybrid tracking |

There were no modeled range clamps or fail-static terminals. The selected
candidate retained at least two material applications in every source stream.
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
