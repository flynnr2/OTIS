# Hybrid 72-Hour Attempt 8 Status-Serialization Terminal

## Verdict

Campaign19 Attempt 8 is a valid but incomplete physical acquisition. The
authoritative retained package is
`runs/d9_adaptive_steering_integration_20260828/long_runs/hybrid_72h_attempt8`.
It established its qualified origin at 2026-08-31T23:57:07Z and retained
8,707.306673 exact counter-domain qualified seconds before the supervisor
terminal at 2026-09-01T02:22:20Z. It did not establish the required 72-hour
endpoint.

The acquisition did establish the first complete CX323 physical control
transaction. The controller requested +1 code, Core 0 accepted and applied
`0xA84D` to `0xA84E`, and the applied DAC epoch advanced from 1 to 2. The
response was observed at the exact 1,500-second horizon as 0.000000000 Hz and
classified `healthy_indeterminate_near_resolution`. The ACT/AT2/AHM/AH2
identity and ordering joins, the first-consumer checkpoint, and the response
replay attestation were exact. This single quantization-limited response is
valid evidence that the transaction path worked; it is not enough to judge
long-term frequency or phase discipline.

Capture closed cleanly with exactly one serial owner after 60,312,450 bytes,
507,389 parsed lines, zero parser errors, zero reconnects, and one independently
delivered emergency abort. The device remained fail-static at `0xA84E`.

## Causal evidence

After the response completed, firmware published complete V3 status snapshots
2056, 2057, and 2058 with a contradictory combination:

- `hybrid_state=HYBRID_TRACKING` and `hybrid_reason=response_completed`;
- correction count 1, applied code `0xA84E`, and DAC epoch 2;
- `first_phase_checkpoint_passed=false`; and
- all hybrid application counters zero.

The CX323 status branch had correctly projected the maintenance controller's
application counters and first checkpoint. A later, unconditional legacy
hybrid-engine assignment then overwrote those fields. The legacy engine is
intentionally inactive and zero-valued in the CX323 profile, while the already
projected CX323 state string remained unchanged. This was a deterministic
firmware status-serialization defect, not a torn cross-core snapshot, a host
observation race, or a scientific controller rejection.

The host supervisor correctly rejected the impossible state with `CX320
HYBRID_TRACKING lacks the first checkpoint`. It submitted the independent
abort at 2026-09-01T02:22:20Z; firmware recorded the accepted abort and
fail-static terminal before capture closed at 2026-09-01T02:22:23Z. Offline
replay independently recovered one automatic and phase-material application,
one complete response, and a passed first checkpoint from the retained
canonical transaction and maintenance records. The sealed acquisition gate
therefore passed, while finalization remained an incomplete physical result
that is replayable without repeating this acquisition.

## Correction

The legacy status projection is now compiled only for profiles that do not use
CX323 phase-priority maintenance. The CX323 projection remains authoritative
for its counters and first checkpoint, and its deliberately unused challenge
fields are assigned explicit zero values. The host invariant is intentionally
unchanged: a future `HYBRID_TRACKING` snapshot without the first checkpoint
must still be rejected.

A native host regression compiles the production active-live translation unit
under the exact `cx323_d9_d6_72h_adaptive_hybrid` matrix defines and executes
the real status getter. It covers application pending, the Attempt 8
response-complete/evidence-pending boundary, and the evidence-clear successor
while the legacy engine remains inactive. The activation path admits only this
exact sealed Attempt 8 terminal as the identified predecessor of a possible
later attempt; it does not reclassify Attempt 8 as a completed run or authorize
an automatic retry.

## Verification and stop boundary

- 143 focused status-getter, source-guard, activation, and supervisor tests
  passed.
- 205 affected status, activation, supervisor, monitor, analyzer, campaign
  replay, and operational-path rehearsal tests passed.
- The exact `cx323_d9_d6_72h_adaptive_hybrid` firmware profile compiled from
  the committed correction.

Per the operator's stop instruction, this work does not flash hardware, create
a new live freeze, or launch Attempt 9. Any later physical run requires a new
explicit start and the usual exact-bundle identity, operational-path
rehearsal, auto-detected flash/readback, and live entry qualification.
