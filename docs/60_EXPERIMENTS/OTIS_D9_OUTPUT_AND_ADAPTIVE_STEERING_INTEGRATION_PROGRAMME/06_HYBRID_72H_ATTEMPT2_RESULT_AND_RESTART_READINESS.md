# Hybrid 72-hour Attempt 2 result and restart readiness

## Verdict

Hybrid Attempt 2 is a **failed physical qualification with a correct bounded
stop and a recovered host-finalization escape**. It is not a 72-hour result and
must not be spliced into a successor run.

At `2026-08-30T14:19:29Z`, one anomalous short D14 edge divided an otherwise
one-second reference interval into approximately 0.138 s and 0.862 s. The
D14/D8 association correctly rejected the ambiguous aperture, opened capture
session 2 and requalified. The event's physical or receiver origin is unknown;
the retained evidence does not support calling it a wiring, receiver or
firmware fault.

The first fresh selected-600 decision in session 2 encountered the frozen
cross-session exact-timing guard and entered fail-static with
`exact_tick_timing_missing_or_backward`. The supervisor preserved the last
confirmed DAC code, delivered the independent priority abort and closed the
sole serial owner cleanly. Unexpected authoritative D14/D8 session
discontinuity is a universal programme stop condition, so no acceptance rule
is weakened and a successor must start a fresh qualified-duration clock.

## Acquisition result

- Run: `runs/d9_adaptive_steering_integration_20260828/long_runs/hybrid_72h_attempt2`
- Supervisor interval: `2026-08-30T10:05:21Z` through
  `2026-08-30T14:29:40Z`.
- Qualified origin: `2026-08-30T10:45:19Z`.
- Setup: exactly one application at `0xA83C`.
- Automatic steering: four exact applications (`+10`, `+7`, `+3`, `+3`),
  ending at `0xA853`, DAC epoch 5 and 23 cumulative codes.
- Hybrid authority was live: three applications were phase-material, the first
  phase checkpoint passed, later authority released, and all four completed
  response checkpoints were healthy.
- No arbitrary application or movement limit bound the run: 4 of 144 allowed
  automatic applications and 23 of 3,024 allowed cumulative codes were used.
- Before the discontinuity, D14/D8 capture, D9 configuration/readback, D6
  loopback evidence, GNSS metadata at 115200 baud, serial ownership and
  transport were healthy.
- The session-2 D14/D8 path recovered and retained more than 600 fresh clean
  intervals without another DAC write. D6 became locally unavailable after the
  session change; that zero-authority diagnostic did not contaminate D14/D8 or
  cause the terminal. A successor must nevertheless reconfirm D6 at its live
  pre-actuation gate.
- Priority abort delivery preceded serial closure. The terminal static code is
  exactly `0xA853`.

## Preserved finalization escape and correction

The retained AH2 row for capture session 2 used that session's lower exact
counter epoch. The Campaign18 relational join incorrectly compared its
timestamp with the final timestamp from capture session 1 and refused to seal
the already-failed run. Generic contract validation already scopes timestamp
progression by capture session.

The join now retains global timing-record ordering and exact V1/V2 identity,
while enforcing timestamp monotonicity independently within each declared
time-domain/session pair. It still rejects a backward timestamp inside one
session, a session identity mismatch, duplicate rows, missing rows, or orphan
rows. No raw record, timestamp, terminal or criterion was rewritten.

Offline recovery performed no device or actuator I/O and produced the failed
Campaign18 seal and registration:

- raw serial SHA-256:
  `6497967f7a7b7fc51ac836a403ca873ea93b7fafba86aac4d465bb7397599c0b`;
- run-manifest SHA-256:
  `0b9ed1910adf5a59eb2ac168c62e626a218804f7c49efa292553ab7a1d8a04d4`;
- evidence-manifest SHA-256:
  `1352885838d5c3ad090e6192276c04d8705b0343bd32262e3f2c387d4ddd2b96`;
- registered content SHA-256:
  `0a46ebb8ea6c89cbef74ca025943e950b75d32a06a6b8c8d13acf3a2729c11dd`;
- failed seal SHA-256:
  `6cf66e684b2aa7eb0a1092874718cfbee5f316966e73b1cc30f37e20db8346d0`;
- primary decision: `cx322_d9_d6_72h_identity_or_evidence_fault`.

## Successor readiness

A successor is authorized only as a new attempt with a fresh 72-qualified-hour
clock. It must bind this failed predecessor seal, retain the same no-challenge
hybrid policy, regenerate the host bundle because the finalizer changed, and
repeat the complete operational-path rehearsal. The firmware, electrical
topology and control policy did not cause the host-finalization escape and need
not change solely to repair it.

Live entry must again prove D14, D8, D9 readback, D6 loopback, GNSS 115200,
single serial ownership, exact setup/application identity and the independent
abort path. No D14 or GNSS fault is to be forced.
