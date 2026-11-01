# Count-status timing service repair — 1 November 2026

The open-ended observation exposed a missed output path in the 31 October
repair. The count module formatted its own cross-core telemetry instead of
using the supplied status callback. That bypass omitted the proven-empty FIFO
observations added between fields. Remove the duplicate publisher and route
all timing-owner count calls through the existing Core 1 status context.
Reference acceptance, canonical SNP uncertainty, numerical steering, capture
ownership and IRQ-credit rules remain unchanged.

The operator requested investigation and a fix ready for test while leaving
the current run recording. No command, recorder replacement, reset or upload
is part of this preparation. The active acquisition remains on the earlier
image and its frozen host source.

## Retained evidence

Boot session `8410938672338229809`, capture session 1, acquisition
`open-ended-20261031T174911Z-817f6132`. The unchanged first raw segment is
134,219,162 bytes, SHA-256
`9203628605af8730459ff8f44af4fdf571dfd38429f6d2f00aa1c9ce24d6eada`.
The read-only evidence return has outer SHA-256
`0a10731f1d50efdd76199b443e5960b5a5c5a7165e46d7d78e90a2fa8642efe0`.

There are 130 wide snapshots from SNP27370 through SNP28670: one separation
of 20 source boundaries, then 128 separations of ten. The first bracket is
7,134 microseconds, the last 1,274. They produced 130 reference holds and phase
epoch changes. The adjacent point service intervals remain inside the existing
band; the first failing span retains exactly 10,000,000 D8 counts. This is
evidence of service-recognition ambiguity, not a measured physical PPS outage
or an independent judgement of receiver stability.

The retained [small fixture](../../tests/fixtures/timing_status/periodic_count_status_gap_20261101.json)
contains the original 1,326 SNP observations from 27360 through 28685, source
identity, columns and expected loss identities. Replaying the unchanged native
selector reproduces all 130 `observation_age_ambiguous` losses and ends at
acceptance epoch 131. Retained uncertainties are not reduced or relabelled to
make the historical trace qualify. The reference flag is the contract-defined
status-zero SNP derivative, not an additional PPS witness. The fixture's
initial anchor and ordinals are local replay support, not reconstructed
pre-attachment history.

Queued STS rows are re-timestamped by Core 0's `emit_status_direct` when
serialized. Their wire adjacency identifies the count-status envelope but does
not measure Core 1's individual field costs. The bracket itself comes from the
recorded FIFO-empty/service observations. Native reproduction supplies the
discriminating causal check of the bypass; no physical WCET claim is made.

## Repair and verification escape

`otis_count_observation.cpp` had two status routes. Its local `emit_status`
and `emit_status_u32` selected a private telemetry formatter on Core 1, ignoring
the status context. Periodic count status was therefore outside the callback
that refreshed the empty lower bound. Some boot, service, capture-fault and
boundary callers also passed the Core 0 context because the private route had
hidden that mismatch.

The repair deletes those private branches. Every Core 1 count caller now
supplies `dual_core_timing_status_context`; the common status emitter invokes
the already existing bounded callback. Deferred boundary reports retain this
same context. No measurement/controller service is inserted into status
formatting, so snapshot state stays coherent. No additional IRQ credit is
granted and no capture word is consumed by a status field.

The first repair's regression replaced the count producer with 50 calls to the
sketch callback. That substitute could not exercise the private branch and
therefore missed the defect. This is a firmware service-isolation defect under
the intended periodic workload, with a verification escape through the
substituted producer. The clean short physical gate remains valid for its
recorded interval; it did not cover every alignment of PPS and periodic work.

The revised collision test links the actual count producer and common status
emitter, the extracted sketch publisher/callback, real queue, active status
visitor, reference selector and first frequency consumer. Only hardware ports
and an explicit 80-microsecond-per-field cost model are substituted. At the
same forced arrival inside count status:

- refresh disabled gives a 3,001-microsecond bracket;
- the deployed first repair with its private count route gives 2,681
  microseconds and fails acceptance;
- the new route gives at most 81 microseconds and preserves the accepted span
  and continuous estimator support.

The test also forces arrival near the beginning, middle and end of every
actual field in the periodic capsule. Generation markers, code, DAC epoch and
fault state remain coherent. The existing boundary regression now links the
common emitter and tests the production boundary bridge through its first
phase/frequency consumers. Source guards cover all count entry points so a
caller cannot silently revert to the Core 0 context. Existing backend tests
retain the no-consumption, no-credit-renewal and fault-preservation checks.

## Frozen next test boundary

The candidate bundle binds its committed source, fixed-profile UF2, build
manifest/resource audit, source inventory, verification logs and finite plan.
Its file-only preflight is not a physical rehearsal. Reuse only host/PIO proofs
whose exact relevant inputs are unchanged. The native collision and boundary
checks cover the changed producer-to-consumer path; the existing detached
normal/review PTY rehearsals cover the host process and endpoint paths.

Keep the present observation running. A future deployment must first receive
an explicit instruction permitting that observation's endpoint; archive its
unchanged evidence before one bounded exact-image upload. Do not insert a
second serial owner or hot-update its frozen source.

After that separately selected endpoint, use the existing 90-minute finite
gate with fresh discovery, exact image/session/policy binding, one AUTO request
with dwell 5400, ordinary qualification and a firmware-owned HOLD endpoint.
Inspect actual SNP brackets, epoch changes, supported selected estimates/IDC,
application joins and closure. Do not require a nonzero correction. Do not
extend the run waiting for this particular rare alignment: forced arrival in
the actual producer is the deterministic stimulus, while the physical gate
checks the genuine image and scheduling boundary.

Preserve the frozen `1,000,000 ± 1,250` tick interval predicate, unknown
uncertainty handling, source identities and all raw observations. An observed
recurrence rejects repair sufficiency; a clean short interval does not prove
indefinite reliability or physical WCET. No controller retuning or uncertainty
subtraction is adopted here.
