# Count Observation Measurement Contract

## Scope

Current HEAD has one D8 count path: the PPS-gated cumulative snapshot backend.
There is no FC0, GPIO-interrupt, long-gate, or runtime-selectable alternative.

Every canonical `CNT` row means that the D8 oscillator edges in the physical
aperture between two adjacent qualified D14-triggered PIO snapshots were
counted. It is a raw count observation, not calibrated frequency, control-loop
error, DAC correction, accuracy, or lock.

## Physical ownership

One PIO state machine continuously counts D8 rising edges in a wrapping 32-bit
down-counter. A D14 PPS condition snapshots the cumulative counter without
stopping or restarting it. DMA transports the captured word; neither DMA,
foreground service, the D14 GPIO interrupt, nor the host defines the aperture.

D14 is also captured independently as a canonical `REF` observation in the
RP2040 monotonic-microsecond domain. The associated D14 records qualify and
identify each boundary but do not replace the PIO-owned count boundary.

For adjacent snapshots in one qualified capture session:

```text
counted_edges = opening_down_counter - closing_down_counter modulo 2^32
```

The first snapshot is an anchor only. A session change, sequence gap,
association loss, ambiguous rollover, DMA/ring fault, or rearm requires a new
anchor and a later adjacent snapshot; no count may bridge the discontinuity.

## Canonical and derived evidence

Firmware preserves raw snapshot identity, cumulative counter value, D14
association, capture session, sequence, domain, flags, and the resulting raw
count interval. Derived frequency, oscillator ratio, phase, dispersion, or
regulation values are separate records and never overwrite these observations.

Host consumers must apply rollover rules from the declared counter/time domain
and must not pass decision-bearing deltas through rounded seconds or binary
floating point.

## Validity and loss

Reference validity, counter validity, boundary validity, aperture validity,
pairing validity, and FIFO continuity are distinct conclusions. A count is
eligible for regulation only when the fixed policy's complete D14/D8 and GNSS
qualification gates pass.

Invalid but bounded observations remain visible with their exact flags.
Firmware must not fabricate a clean `CNT` when no honest closing boundary
exists. Missing snapshots, malformed or missing D14 boundaries, count
saturation, transfer loss, and sequence discontinuity invalidate only the
affected frontier and require explicit re-anchoring and requalification.

D10 `EVT` evidence and the D6 diagnostic monitor are outside this contract and
can never qualify, invalidate, or replace a D14/D8 count observation.

## Claim boundary

The backend establishes deterministic digital count semantics. It does not by
itself establish calibrated absolute frequency, UTC accuracy, oscillator or
reference uncertainty, analog signal integrity, or end-to-end measurement
accuracy. Those claims require separately identified evidence and uncertainty
components. See `CURRENT_METROLOGY_CLAIM.md` and
`PPS_GATED_RATIO_BACKEND_DESIGN.md`.
