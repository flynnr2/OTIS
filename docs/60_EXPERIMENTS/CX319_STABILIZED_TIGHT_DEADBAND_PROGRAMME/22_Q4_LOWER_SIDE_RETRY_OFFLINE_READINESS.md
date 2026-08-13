# CX319 Q4 Lower-Side Retry Offline Readiness

## Result

The result is `q4_lower_retry_offline_ready_for_separate_authority`.

The failed-attempt retention defect is repaired, the changed path has focused
regression coverage, and a new exact candidate passed structural preflight and
the complete accelerated operational-path rehearsal. This is offline evidence
only. It grants no reset, serial, setup, DAC-write, arm, correction, or live-run
authority.

## Proportionate verification

The prior attempt changed no firmware, Q1--Q3 evidence, policy, estimator,
plant model, command envelope, control limits, or analyzer criteria. Those
passing identities were reused without repeating Release or the physical
sequence.

The only code change makes the outer live runner retain the primary
orchestration reason when its best-effort emergency-abort submission finds
that capture has already closed. The exact missing-reader case and programme
retirement state passed 13 focused tests. The repaired candidate then passed:

- the ten-check no-I/O structural preflight with zero hardware operations;
- the accelerated setup, arm, automatic transaction, obstruction, priority
  abort, same-owner rotation, analysis, seal, completed registration and
  interrupted registration path; and
- the non-authorizing and zero phase/hybrid authority checks.

## Exact candidate

The immutable local candidate is under
`runs/cx319_stabilized_tight_deadband/q4/q4_retry_offline_preparation_20260813T075000Z`.

- Source revision:
  `421501dc49d29eb91f6160a0b7965475c12c706b`.
- Proposal file SHA-256:
  `1c9e64cab6ca10d7d114927dcb378d75f350150633c188f73642f874c8b94a8d`.
- Canonical proposal bundle:
  `9697652d963c0bcfe44800c1f3ff7c6cf032ca382c5479c8cec0edb1ddccbd56`.
- Live runner SHA-256:
  `833bc0f3c07a2bb678cd7a863f8a1f44e947a5e5ae9772114cf54ac192d657c5`.
- Preflight file SHA-256:
  `07df6e2d08f1fbfa38978091d0174d2bbd020a6f55ee743fd9a4cbfe3ecab7a1`.
- Operational-rehearsal result file SHA-256:
  `413e64508bc1ae7dadffac816e157335ff4db899ec7bc01aadfb50018c232e6b`.
- Operational-rehearsal content identity:
  `89f8df3952218cb729f22d62acc5969ec2b30d447f21fedb8a4d178f2b755877`.
- Operational-rehearsal seal:
  `c56d402abd3ac208ca10b73f78863372ca4abb176c10c8d56c3c3d2845c84c6d`.
- Exact retained Q3 UF2:
  `50f863a2150d1b1391504553a1d20e1cb951daae5b450a83c90628265a522083`.

## Proposed physical boundary

The non-effective machine proposal is
`profiles/qualification/cx319_q4_lower_live_retry_authority_proposal_v1.json`.
It proposes exactly one board restart, zero firmware flashes, and one physical
Q4 lower-side entry using the new candidate. A restart is the discriminating
physical check for the prior non-responsive runtime and provides a bounded
fresh-attachment epoch for the existing 120-second entry gate.

After restart, the run must stop before setup unless the same board enumerates,
the exact qualified firmware identity and firmware records arrive, and the
complete nonce-bound snapshot and existing GNSS/PPS gates pass. A second
restart, upload, restore, automatic retry, second run, or phase/hybrid action
is outside the proposal.

## Decision boundary

The consumed activation and failed run cannot be reused. `g2_live_leg` remains
blocked. The next decision is whether to make the proposed one-restart,
one-run boundary effective in a new authority record. No unchanged gate needs
to be repeated for that decision.
