# CX319 Q4 Lower-Side Restart-Path Stop

## Outcome

The authority in `23_Q4_LOWER_SIDE_RETRY_LIVE_AUTHORITY.md` was activated, but
no board restart or physical run occurred. A 180-second manual observation
window saw no USB disappearance. The fallback no-flash `picotool` application
reboot command then reported that the running Arduino device was not an
accessible RP-series target. The board remained enumerated at the same path
and with serial `503533748A919118`.

The syntactically valid restart command consumes the authority's single
restart-attempt allowance. No second reset method was tried.

## Preserved facts

- Activation content identity:
  `439c201d91d5e3e3a17dad28d3fcffcce55959768c2d9b83c42f366f3ed12958`.
- Activation file SHA-256:
  `74f5aab4436a085a0f08f70f5d10e47259bfb9f945137327603c87a51da62703`.
- Restart-attempt record SHA-256:
  `e06e59e266f2d96adceb9dd1bb67c2f8df7560a8a4ebfc3fbae1a5237a09c878`.
- Firmware flashes: zero.
- Observed restarts: zero.
- Serial opens and physical live runs: zero.
- Setup stimuli, DAC value writes, control arms and automatic corrections:
  zero.

This is a platform restart-path failure before hardware effect, not a Q4
scientific result and not evidence against the candidate firmware or control
policy.

## Reuse boundary and next decision

No operational input in candidate bundle
`9697652d963c0bcfe44800c1f3ff7c6cf032ca382c5479c8cec0edb1ddccbd56`
changed. Its preflight and accelerated rehearsal therefore remain applicable;
Q1--Q3 and Release remain applicable as well.

The non-effective replacement proposal is
`profiles/qualification/cx319_q4_lower_live_manual_restart_authority_proposal_v1.json`.
It permits only one physical reset-button press after an observer is already
waiting, followed by one exact candidate run. It prohibits software restart
commands, firmware flash, a second press or run, restore, and phase/hybrid
actuation. A separate operator decision is required before it can be made
effective.
