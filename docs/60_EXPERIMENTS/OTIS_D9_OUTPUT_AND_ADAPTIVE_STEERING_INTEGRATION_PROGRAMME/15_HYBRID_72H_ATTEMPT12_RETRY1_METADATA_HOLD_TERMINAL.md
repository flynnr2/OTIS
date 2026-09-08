# Hybrid 72-Hour Attempt 12 Retry 1 Metadata-Hold Terminal

## Verdict

Campaign19 Attempt 12 retry 1 retained a valid, incomplete physical
acquisition. The supervisor admitted 74,741 qualified D14/D8 apertures and
completed fifteen applications before a short D14 disturbance produced two
rejected windows and one interval anomaly. Firmware correctly entered a
zero-authority `GNSS_METADATA_HOLD`, but a firmware control-flow defect then
converted the recoverable hold into a terminal transaction fault. The emitted
status masked that terminal state as a continuing metadata hold. Independently,
the host treated the two lifetime capture counters as a permanent fault after
the instantaneous capture gates had recovered. These are firmware and host
platform defects, not a scientific rejection of the CX323 controller.

The immutable retained package is
`runs/d9_adaptive_steering_integration_20260828/long_runs/hybrid_72h_attempt12_retry1`.
It ended at the last confirmed DAC code 43,076 (`0xA844`), DAC epoch 16, after
15 phase-material applications and 25 codes of cumulative absolute movement.
The required 259,200-qualified-aperture endpoint and clean disarmed terminal
were not reached. Attempt 12 retry 1 therefore fails both its acquisition and
offline-finalization gates and cannot be continued in place or reclassified as
the original single-session pass. Its validated prefix may instead be bound as
the first provenance stratum of a separately contracted composite corrected
extension; that claim must expose the firmware/session boundary and excluded
gap rather than manufacture continuity.

## Observed prefix and holds

Qualification began in capture session 1 at accepted-window and D14-reference
sequence 2,399. At 2026-09-08T09:47:20Z, after 74,741 supervisor-qualified
apertures, the supervisor observed `rejected_window_count` change from 0 to 2
and `pps_interval_anomaly_count` change from 0 to 1. All other retained
authoritative capture counters remained at their qualified baselines. It
entered a host verification hold, issued no new authority and retained the
sole serial owner and code 43,076/epoch 16.

Firmware maintenance record 134 independently records
`gnss_metadata_hold_enter` at 1,234,318,028,816
`rp2040_timer0_extended` ticks, with controller state `READY -> METADATA_HOLD`,
no request or response pending, and the same code and epoch. Later records
remain in `METADATA_HOLD`; the metadata requalification sequence and causal
D14/D8 frontier remain zero even after same-receiver metadata and current PPS
eligibility became healthy. D14/D8 observations and raw capture continued.

The host hold was also permanent in the frozen implementation. It compared
lifetime capture counters with their qualification-start values on every
poll, so recovered current health could not clear the already-incremented
counters. The final state records 61,826 observations of the same retained
discrepancy. This behavior preserved fail-static operation, but confused
historical anomaly evidence with current capture eligibility and prevented a
provenance-bound continuation of accepted-aperture accounting.

## Firmware causal defect and status masking

The causal defect is deterministic in the frozen firmware source. Once fresh
metadata and a later D14/D8 observation made requalification eligible, the
ordinary service loop could call the requalification function without a
timestamped health event. The implementation grouped “no event timestamp is
available on this poll” with session/code/epoch contradictions and latched
`cx323_metadata_requalification_identity_or_tick_contradiction`. Absence of an
event timestamp required deferral until the next timestamped health update; it
was not evidence of contradictory identity.

The live status getter then gave the stale `gnss_metadata_hold_active` flag
precedence over the terminal transaction state and reason. Consequently it
continued to publish `GNSS_METADATA_HOLD` and
`gnss_metadata_unqualified_hold`, although `fail_static=true` while
`setup_partition_healthy=true` proves a transaction-local `FAULT` or
`ABORTED`, not a dual-core partition failure. No device-abort event preceded
the condition, and the source reconstruction identifies `FAULT`. The masked
reason is a telemetry limitation: the exact source-path diagnosis is derived
from the retained state invariants and frozen implementation, not from a
directly emitted terminal-reason record.

No normal live command could repair that transaction. `ARM` rejects terminal
states, setup is one-shot, lease and snapshot commands only observe or retain
the existing session, and `ABORT` can only latch `ABORTED`. Preserving the sole
owner and the last confirmed code until an explicit stop was therefore the
only valid in-place behavior.

## Stop and abort-delivery boundary

An operator-authorized independent abort was submitted at
2026-09-08T14:55:37Z. The sole-owner capture state records one priority abort
as sent and remained open through the bounded delivery wait. A complete
resulting firmware `ABORTED`/fail-static snapshot was not observed before the
15-second deadline. The carrier then closed the physical serial connection at
2026-09-08T14:55:53Z with zero reconnects, parser errors, malformed UTF-8 or
rejected commands.

The stop evidence therefore proves abort submission and one carrier write, but
does not prove firmware consumption or its resulting state before close. The
physical code remains exactly last-confirmed at 43,076; treating that as an
observed post-abort acknowledgement would exceed the evidence.

## Acquisition, replay and correction boundaries

The sealed package keeps the gates distinct:

- acquisition failed because the exact endpoint and disarmed,
  evidence-clear, no-outstanding-static-code terminal are absent;
- offline finalization failed and is not replayable into a physical pass;
- all 15 retained response attestations and classifiers reproduce exactly,
  and the active-hybrid maintenance stream is exact over its retained prefix;
- raw measurement/estimator and tight-deadband replay do not pass in the
  original seal, so no broader performance or scientific acceptance claim is
  available; and
- later deterministic source or host corrections do not alter any observed
  command, application, response, counter, terminal or retained file.

The same-session host correction described as a “corrected extension” is
narrowly an accepted-aperture accounting continuation for a future valid
transaction. It
may rebase only the two recoverable lifetime counters after same-session
instantaneous gates are clean, exact actuator identity is unchanged, and the
number of excluded D14 boundaries equals the rejected-window delta. Rejected
boundaries remain excluded from qualified duration and all other counter,
session or identity changes remain fail-closed. It is not a duration extension,
does not move the frozen endpoint, grants no new control authority, and cannot
resume or qualify Attempt 12 retry 1 after its firmware transaction fault.

The agreed recovery path is instead a provenance-linked composite: bind this
74,741-aperture supervisor prefix, start a separately frozen continuation with
a fresh run/session identity and corrected firmware, exclude the reset/setup
gap, and require enough source-local qualified apertures to bring the composite
total to 259,200. That is a corrected-extension result across two explicitly
different strata, not an uninterrupted unchanged-firmware qualification.

Any continuation still requires the direct deterministic regressions, the
affected exact build and the complete operational-path rehearsal. This report
itself grants no flash, retry, restoration or bench authority.
