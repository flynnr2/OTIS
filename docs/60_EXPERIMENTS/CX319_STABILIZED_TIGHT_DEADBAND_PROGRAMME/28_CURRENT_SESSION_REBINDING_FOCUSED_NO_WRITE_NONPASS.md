# CX319 Current Session-Rebinding Focused No-Write Non-Pass

## Outcome

The one authorized focused physical attempt completed safely on 2026-08-13.
The exact current lower-profile firmware flash passed, but the run did not
observe the frozen required reason `pre_setup_session_rebound` within the
120-second bound. The result is a non-pass and the authority is consumed.

No setup stimulus, DAC value write, control arm or automatic correction
occurred. Q2 and Q3 were not repeated. This is not a Q4 result and grants no
live authority.

## Exact retained evidence

- Run: `focused_session_rebinding_20260813T085754Z`.
- Bundle identity:
  `4666041ff61ab23df2c0e4c10af5f4bf6afef526c5f3bb425ddd9d7856cd3dc9`.
- UF2 SHA-256:
  `e62cfb7c5df58a4471425a2045cc7d7fba03ed57d35eccb8cdd45ad34c7bf510`.
- Flash record SHA-256:
  `9c204517b022778c0473c2244f4a93b8ab84481a42e4cd75689dbe216791b0ea`.
- Run-manifest SHA-256:
  `76aaf9395635f76ac2bcb1865b3033b671abf7c185d0fe8e112b7d7e3393ff37`.
- Raw-serial SHA-256:
  `6eab1196f98c87263bbed2c190d558d125c8b920b6bef35f4bf06978439f7f83`.
- Health CSV SHA-256:
  `6ba824ac34bfacaa2acfe894b59db9f725f5ffe0501885d179891366d966498d`.
- Result file SHA-256:
  `f151d2fe670ef7d36b27a4a568c1431734d5e0fee94a8068c98ddb474fb4a32d`.
- Evidence manifest SHA-256:
  `bbdf0f7f531adbac6d2f56f0652da1686c1388fc91666186f19bf1a3b72da2d8`.
- Registered content identity:
  `3bb16918e2db573d76546832cae6363fe121824dbae88f486def6abbdd1119c1`.

The flash used one attempt, returned exit status zero, preserved board serial
`503533748A919118`, and attached the continuous carrier 218.2 ms after upload
readiness. The boot path performed only the declared I2C address probe.

## What was observed

Across 403 emitted active-status generations:

- every observed state was `DISARMED`;
- every observed reason was `initialized_disarmed`;
- every observed `fail_static` value was `false`;
- every observed nonzero session was session `1`;
- manual start remained false; and
- correction count, cumulative movement and DAC epoch remained zero.

There were 394 complete generations, zero serial reconnects, zero parser
errors, zero active-transaction rows and zero DAC-step rows. The older failed
Q4 image had changed to `FAULT/session_change_clears_arming` while its emitted
session remained `1`, so the historical fault was consistent with a transient
zero-session observation rather than a different nonzero rebound. The current
image remained healthy, but the frozen focused criterion required the explicit
nonzero-rebound reason and therefore was not satisfied. That criterion is not
being changed after examining the evidence.

## Process failure

The focused orchestration requested 395 snapshots rather than using a low
fixed cadence. It produced nine incomplete generations and drove ordinary
dual-core telemetry drops from zero to 48. The independent capture remained
complete and the no-actuation conclusion is valid, but this avoidable command
load makes the attempt unsuitable as a clean current-image qualification.

This is classified as a platform escape into a focused physical
qualification, not a firmware or scientific rejection. The next proposal must
reuse the now-confirmed installed image without flashing, use a low fixed
snapshot cadence, and freeze the actual discriminating criterion before any
new reset or capture. No physical action is currently authorized.

