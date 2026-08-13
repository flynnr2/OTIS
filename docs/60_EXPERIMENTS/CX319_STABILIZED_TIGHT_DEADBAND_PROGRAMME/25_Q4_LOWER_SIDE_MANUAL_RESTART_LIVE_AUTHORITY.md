# CX319 Q4 Lower-Side Manual-Restart Live Authority

## Operator decision

On 2026-08-13 the operator stated:

> I authorize the manual-reset proposal and I am at the bench.

This makes
`profiles/qualification/cx319_q4_lower_live_manual_restart_authority_proposal_v1.json`
effective for one observed physical reset-button press and one execution of
the repaired Q4/G2 lower-side candidate.

## Exact bindings

- Candidate source revision:
  `421501dc49d29eb91f6160a0b7965475c12c706b`.
- Candidate bundle:
  `9697652d963c0bcfe44800c1f3ff7c6cf032ca382c5479c8cec0edb1ddccbd56`.
- Candidate file SHA-256:
  `1c9e64cab6ca10d7d114927dcb378d75f350150633c188f73642f874c8b94a8d`.
- Rehearsal content identity:
  `89f8df3952218cb729f22d62acc5969ec2b30d447f21fedb8a4d178f2b755877`.
- Rehearsal seal:
  `c56d402abd3ac208ca10b73f78863372ca4abb176c10c8d56c3c3d2845c84c6d`.
- Expected board serial: `503533748A919118`.
- Required installed UF2:
  `50f863a2150d1b1391504553a1d20e1cb951daae5b450a83c90628265a522083`.

## Exact physical sequence

1. Freeze a fresh activation under this authority.
2. Start the USB disappearance/reappearance observer.
3. Instruct the physically present operator to press the board reset button
   once.
4. After the single reappearance, immediately start the continuously draining
   exact live runner.
5. Stop before setup unless board, firmware, uptime, snapshot, GNSS/PPS,
   transport, evidence, partition and zero-write gates all pass.
6. If they pass, permit one `0xA808` setup, one arm and at most four healthy
   positive automatic corrections inside the frozen envelope.
7. Analyze, seal, register and retire at the first terminal.

No software restart command, firmware flash, second button press, retry,
restore, threshold change, duration extension, second run, G3 progression, or
phase/hybrid actuation is authorized. The authority is consumed by the one
observed press or the run terminal, whichever occurs first.
