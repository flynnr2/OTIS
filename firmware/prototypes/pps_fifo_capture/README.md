# FIFO drain implementation work branch

This prototype is not part of the Arduino sketch or build inputs. Keep this
branch unmerged until the complete replacement described in
`docs/50_SOFTWARE/SINGLE_REFERENCE_OWNER_REPAIR.md` is integrated and verified.
Move the tested implementation into the actual driver then delete this staging
location; do not retain parallel runtime transports.

`otis_pps_fifo_drain.h` implements a bounded drain of immutable FIFO words.
The port must supply nonblocking FIFO depth/read, sticky RXSTALL observation,
CPU us32 service time, and an ISR-safe stop that disables this source and SM
without clearing queued evidence. The caller reserves software-ring capacity
before entering, provides the current session/ordinal, and must retain every
returned word even when the result reports a fault. IRQ-entry count never
becomes record identity. There is no reference-acceptance or actuation decision
inside this component.

The native harness compiles this implementation and checks empty/singleton,
zero raw count, ordinal/timer rollover, depths two/eight, insufficient software
space, replenishment during drainage, latched and newly observed RXSTALL, and
uninitialized session. Every read word is returned with its own identity and
actual service coordinate. A multiword cohort is marked timestamp-ambiguous;
this flag never asserts singleton freshness or a hardware-latch timestamp.
The overload path stops after at most eight reads and retains unread FIFO data.

Validation: `python -m pytest -q tests/test_pps_fifo_drain.py` passes. The port
in that harness is a deterministic fake; this is not a tested RP2040 ISR.

Remaining integration is explicit:

1. Implement and audit the real PIO FIFO interrupt adapter, software ring,
   source dispatch and IRQ-safe session/rearm lifecycle. Verify ownership in
   the pinned linked image and remove authoritative DMA.
2. Prove aggregate CPU service bounds across repeated IRQ entries, not only
   the eight-read bound within one entry. A stream of repeated singleton IRQs
   is not covered by the per-entry test. Do not invent an additional scheduler
   or assume process liveness establishes the bound.
3. Replace mandatory GPIO/reference pairing with the single captured record;
   remove its old authoritative queues/guard. Bind GNSS/raw-PPS status to the
   new authoritative source while retaining metadata's separate role.
4. Update service-timestamp semantics and their native/host consumers together.
   Pass records through the actual common acceptance gate, phase/frequency and
   first control decision. Reject/hold ambiguous or insufficient timing evidence
   without manufacturing source timestamps or silently changing ±1.25 ms.
5. Run the exact-profile resource/build checks and required end-to-end rehearsal
   before any physical candidate. The prototype does not authorize a bench run.
