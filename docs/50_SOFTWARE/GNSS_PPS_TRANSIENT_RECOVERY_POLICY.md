# GNSS/PPS Transient Recovery Policy

## Scope and hardware binding

This policy applies to the established OTIS GNSS receiver, D14 PPS wiring and
ground return, input conditioning, and current RP2040 capture implementation.
Their accumulated bench and campaign evidence supports treating occasional
extra-edge cadence anomalies as recoverable reference-quality events. A new
receiver, conditioning circuit, wiring topology, or capture implementation
must be qualified before inheriting this policy.

The policy does not make D8 a replacement timing authority. D14 remains the
sole authoritative PPS/reference input. D8 supplies short-term oscillator
continuity evidence only; GNSS serial metadata qualifies the same receiver but
never replaces D14.

GNSS serial discovery and reacquisition are service-plane activities. They do
not gate boot or D14/D8 capture. `discovering`, `validating`, `degraded` or
`lost` serial state inhibits GNSS-dependent setup and control authority while
preserving raw timing acquisition. A recovered link must re-establish 115200
baud, PMTK identity and exact output configuration before metadata can
requalify; a prior producer acknowledgement is not sufficient.

## Required behavior

For a malformed, duplicate, short, long, or temporarily missing D14 cadence:

1. Preserve every canonical raw D14 observation and lifetime anomaly counter.
2. Mark the affected reference/count aperture invalid; never steer from it or
   rewrite it as clean evidence.
3. Enter `pps_gate/state=suspect`, inhibit actuation, and hold the last
   confirmed DAC code.
4. Invalidate the next boundary pair when its opening boundary was rejected.
5. Enter `pps_gate/state=requalifying` on clean observations and restore
   current eligibility only after the configured consecutive-clean-window
   requirement, eligible GNSS metadata, and fresh estimator support.
6. Enter active-control `REFERENCE_HOLD` rather than terminal `FAULT` whenever
   no actuator request/application handoff is unfinished. Consume any unused
   authorization. After requalification, require a fresh exact authorization
   before another correction.

Lifetime rejected-short, rejected-long, association-loss, missing-PPS, and
interval-anomaly counters remain scientific evidence. Their nonzero value does
not mean that the reference is currently unusable.

## Terminal boundaries

Latched fail-static behavior remains required for capture or boundary-ring
loss, snapshot-backend fault, unknown or mismatched applied DAC state,
partition/queue integrity failure, lost abort path, unstable receiver identity,
or reference loss during an unfinished actuator request/application handoff.
Those conditions prevent an exact in-place reconstruction of authority or
application ordering.

## Observed regression pattern

The 2026-08-15 event split one nominal period into approximately 747.525 ms,
185 us, and 252.289 ms. The three raw fragments remain rejected evidence. The
deterministic regression requires an explicit recovery-inhibit interval and
then the configured clean-window sequence before current eligibility returns;
no reset or erasure of the lifetime counters is required.
