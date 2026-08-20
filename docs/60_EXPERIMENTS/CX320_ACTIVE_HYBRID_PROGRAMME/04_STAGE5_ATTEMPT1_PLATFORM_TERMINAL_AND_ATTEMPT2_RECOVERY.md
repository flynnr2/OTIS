# CX320 Stage 5 Attempt 1 Platform Terminal and Attempt 2 Recovery

## Attempt 1 terminal

Attempt 1 (`stage5_live_attempt1_20260820T1045Z`) flashed the exact authorized
UF2 once and revalidated board serial `503533748A919118`. Capture became the
sole serial owner and retained six real D14/D8 intervals. Before setup, the
firmware reported transaction state `FAULT` with reason
`active_integrity_or_capture_lease_lost`. The host submitted exactly one
priority abort, capture recorded its delivery, and capture then closed. No
setup application, DAC value write, arm, automatic application or scientific
control transaction occurred.

The terminal is a platform escape into the campaign, not a scientific
rejection. The failed physical seal has semantic SHA-256
`ae6e6a1c5a38682241a414e21b3001f746a8eb2d1a86be706a1095c0998e7ae9`
and file SHA-256
`2ef52f619bf3e04345b79ac99b58fe7b5a27d3c9dc811c03e712dee8a0e62b88`.
The registered package content SHA-256 is
`2a68a1d2d215f1854a9464163ab7c00a0e1d121caca9969985e06365c21cb623`.

## Cause and correction

The physical timestamps discriminate the cause. Firmware bound the capture
session before setup and correctly began in an unqualified reference state.
It transitioned that pre-setup state into `ReferenceHold`, then applied the
post-setup active-integrity predicate. That predicate requires both a live host
lease and a confirmed applied DAC code; the latter cannot exist before the
one-shot setup acknowledgement. The result was an unrecoverable fault about
seven seconds after boot even though the later snapshot showed a live lease,
healthy partition, no queue drops and correctly captured D14/D8 records.

The correction leaves a bound but not-yet-set-up session in `SETUP_PENDING`.
Strict reference, lease, abort-path and applied-code integrity enforcement
begins after the authoritative setup acknowledgement. A direct source guard
covers this integration condition, and the existing transaction regression
covers pre-setup session acquisition without a false fault. Forty-one focused
active-control, hybrid parity, runner and supervisor checks pass. The affected
exact firmware profile also rebuilds cleanly.

## Attempt 2 identity and gate

Attempt 2 is explicitly a new identified attempt under the operator's expanded
recovery authority; it is not an automatic controller retry. Its activation
must bind the failed attempt-1 seal and registered evidence identity.

- firmware source/configuration identity:
  `495601d286cbe6c53730407d09a6dcd7d8c685b8f336514105ae7b32b12eb57b:f800a4b7725992b01682e6d2c9e2be6fa15c956e23662622a928cdd4abe40990`;
- exact UF2 SHA-256:
  `b10cc09df783ef9e9f39383cff18d4600d9c2021910457d856ae0d8e10ae69fd`;
- bundle semantic SHA-256:
  `eb849af779b5b5db6448b51433c17fca5220102be5a916d60c6adb3fc132057d`;
- successor proposal semantic SHA-256:
  `4c66c07d6b7631cdc001f861a62e089f711f8ac16e11be9dcd94770295d45e60`;
- operational rehearsal semantic SHA-256:
  `a310fb6fed84fd1baa0c972cdfc6269990fcedcf227b4511512148652ac22648`.

The rebound rehearsal passed the real capture/supervisor/FIFO topology and the
accelerated progressive, response, degradation, fail-static, analysis, seal
and registration boundaries. It performed zero physical actions. The shortest
remaining affected gate is the exact finite physical Stage 5 attempt. All
scientific thresholds, criteria, limits and duration are unchanged.
