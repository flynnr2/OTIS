# CX319 Q4 Lower-Side Retry Live Authority

## Operator decision

On 2026-08-13, after review of the retained zero-write transport stop and the
fresh repaired-runner candidate, the operator responded `authorized`.

That decision makes the proposal in
`profiles/qualification/cx319_q4_lower_live_retry_authority_proposal_v1.json`
effective for exactly one ordinary board restart and one Q4/G2 lower-side
physical run. It does not revive the consumed prior activation.

## Exact bindings

- Candidate source revision:
  `421501dc49d29eb91f6160a0b7965475c12c706b`.
- Candidate proposal file SHA-256:
  `1c9e64cab6ca10d7d114927dcb378d75f350150633c188f73642f874c8b94a8d`.
- Candidate bundle:
  `9697652d963c0bcfe44800c1f3ff7c6cf032ca382c5479c8cec0edb1ddccbd56`.
- Live runner SHA-256:
  `833bc0f3c07a2bb678cd7a863f8a1f44e947a5e5ae9772114cf54ac192d657c5`.
- Accelerated-rehearsal content identity:
  `89f8df3952218cb729f22d62acc5969ec2b30d447f21fedb8a4d178f2b755877`.
- Accelerated-rehearsal seal:
  `c56d402abd3ac208ca10b73f78863372ca4abb176c10c8d56c3c3d2845c84c6d`.
- Expected board serial: `503533748A919118`.
- Required installed UF2:
  `50f863a2150d1b1391504553a1d20e1cb951daae5b450a83c90628265a522083`.

The passing candidate and rehearsal are retained under
`runs/cx319_stabilized_tight_deadband/q4/q4_retry_offline_preparation_20260813T075000Z`.

## Physical scope

This authority permits:

1. one ordinary board restart, with zero firmware flashes;
2. immediate continuously drained attachment after USB re-enumeration;
3. proof of the expected board, exact installed firmware, firmware uptime no
   greater than 120 seconds, complete nonce-bound snapshot and all existing
   GNSS/PPS, transport, evidence, partition and zero-write gates;
4. one exact `0xA808` setup transaction only after that proof passes;
5. one control arm and at most four healthy positive automatic corrections,
   bounded to 21 codes each and 84 cumulative codes inside
   `0xA800..0xAB00`; and
6. the frozen finite supervisor, analyzer, seal and registration path.

The existing 1,800-second cadence, 900-second settling exclusion, 600-second
fresh support, 90-minute qualification deadline, four-hour endpoint,
one-request, no-restore and zero phase/hybrid authority limits remain exact.

## Consumption and stops

The authority is consumed by the single restart attempt or by the physical run
reaching any terminal, whichever boundary occurs first. If the board does not
re-enumerate, firmware records do not arrive, identity differs, or any prewrite
gate fails, stop without setup or another restart.

There is no firmware upload, second restart, retry, restoration, threshold
change, duration extension, second physical run, G3 progression, or
phase/hybrid actuation authority. Every terminal must retain and register the
available evidence and retire this authority.
