# CX321 v2 Implementation and Rehearsal Contract

Status: implementation and release verification passed; exact clean-source
bundle rehearsal remains pending and no physical authority is claimed.

This contract converts the selected offline CX321 v2 design into explicit
producer-to-consumer invariants. A physical run must not be the first execution
of an ordinary firmware/host connection, timeout, boundary, evidence, analysis,
or finalization path.

## Unchanged scientific boundary

- D14 remains the sole PPS/reference input.
- D8 remains the sole oscillator/count input.
- D10 remains an independent event input and has no timing-authority or
  control role.
- The natural hybrid controller retains CX320's selected 600-second estimator,
  frequency and phase terms, gain, integer rounding, per-step limit, response
  classifier, phase-material counterfactual, and progressive checkpoint.
- The new 1,500-second estimator is identification-only. It never supplies a
  natural-controller frequency term or response classification.
- Total authority remains four applications, 84 absolute movement codes,
  1,800 seconds minimum applied cadence, and `0xA800..0xAB00`. The single
  identification move consumes one application and 21 codes.
- Automatic retry, extension, restoration, and a second actuator writer remain
  forbidden.

## Exact end-to-end propagation invariant

The rehearsal and deterministic regressions must prove this complete path:

```text
D14/D8 accepted adjacent count
  -> firmware 1,500-interval accumulator
  -> exact pre1/pre2 totals and identification decision
  -> active request on Core 1
  -> accepted request and sole DAC write on Core 0
  -> exact post-write application tick and DAC epoch acknowledgement
  -> all firmware estimator/phase/policy consumers
  -> first wholly fresh post-application 1,500-interval total
  -> firmware integer response verdict
  -> captured plant-sign and active-transaction evidence
  -> independent host integer replay and durable attestation
  -> exact evidence acknowledgement echoed to firmware
  -> firmware plant-sign attestation
  -> rebased natural-controller state
  -> first natural 600-second decision
  -> supervisor, analyzer, seal and registration
```

Each arrow must carry and compare the exact identities needed by its first
decision-bearing consumer. Producer acceptance alone is not proof of downstream
receipt.

## Firmware invariants

### Identification estimator

- Accumulate exact unsigned 64-bit totals over exactly 1,500 accepted adjacent
  D8 counts associated with contiguous D14 boundaries.
- Preserve first/last count sequence, opening/closing D14 device ticks,
  capture session and DAC epoch.
- Carry the lifecycle timestamps in the derived, strictly non-wrapping
  `rp2040_timer0_extended` domain. Reconstruct that coordinate from qualified
  adjacent D14 boundaries and project setup/application/acknowledgement ticks
  only through a bounded, unambiguous relation to a retained boundary. Keep
  the canonical raw `rp2040_timer0` observations unchanged and do not compare
  the two domains without that explicit projection.
- Admit an interval only when its opening D14 boundary is at or after
  `application_tick + 900 * 16,000,000` in `rp2040_timer0_extended`.
- Exercise both legal exclusion alignments: 900 accepted intervals when the
  application is exactly D14-aligned and 901 when it is not.
- Reset on invalid interval, sequence/session discontinuity, reference
  association failure, reset evidence, capture/queue fault, DAC epoch change,
  or declared exclusion. No 1,500-second span may cross one of those events.
- Run beside the existing 600-second estimator without resetting, rephasing,
  delaying, or replacing it.

### Pre-stimulus decision

The sole identification request is eligible only when:

```text
pre1_total == pre2_total
pre_error_counts = pre2_total - 15,000,000,000
1 <= abs(pre_error_counts) <= 5
latest natural 600-second state == TIGHT_INSIDE
current code/epoch == exact setup code/epoch
global automatic application count == 0
all measurement, health, identity and propagation gates are exact
```

The request is:

```text
delta_id = -21 * sign(pre_error_counts)
requested_code = 0xA83C + delta_id
```

It is tagged as identification, not natural frequency, phase, phase-material,
or phase-performance evidence.

### Application time and response

- Capture `application_timestamp_ticks` immediately after the sole Core 0 DAC
  write returns. A pre-write acknowledgement tick, host receipt time, rounded
  firmware second, or later status query is not an application timestamp.
- Preserve the exact tick through the cross-core acknowledgement, transaction
  record, plant-sign record, estimator exclusion origin and status.
- The first complete post-application 1,500-second estimate after the exact
  exclusion is the only identification response estimate.
- Compute the verdict in integer count space:

```text
response_counts = post_total - pre2_total
response_counts * delta_id > 0
3 <= abs(response_counts) <= 14
```

- A below-floor, wrong-sign, excessive, discontinuous, inexact or right-
  censored response cannot be promoted by floating-point frequency evidence.
- The firmware retains the response tuple immutably while awaiting one exact
  host replay acknowledgement for no more than 30 seconds.

### Handoff to the natural controller

An accepted response acknowledgement opens fresh `PHASE_QUALIFY`; it never
directly emits a natural request. The first natural decision must record and
verify:

```text
global application count             = 1
global cumulative movement            = 21 codes
global last-application origin        = exact ID application tick
natural chatter/path origin           = exact post-ID code and epoch
natural cumulative path               = 0
natural direction/reversal history    = empty
natural application/material counters = 0
plant-sign attestation                = exact and current
```

All later physical applications increment global and natural accounting.
Global budget/cadence gates use global state; reversal and path-efficiency
gates use natural history only.

## Durable record and replay invariants

CX321 uses a dedicated `plant_sign_qualification_v1` lifecycle record. Its
events are `pre1`, `pre2`, `request`, `application`, `response`,
`response_ack`, and `handoff`. The record must preserve the exact estimator
config identity, support boundaries, integer totals/errors, session, epoch,
request/application identity, exact application tick, response predicates,
host-acknowledgement tuple, global accounting and natural-history handoff.

The host must independently reconstruct the estimator and response from the
retained canonical `pps_snapshots_v1` observations. For each of `pre1`, `pre2`
and `response`, replay must use the 1,501 same-session contiguous snapshot
boundaries, require the frozen 0.8--1.2-second raw D14 interval acceptance and
snapshot backend/status, prove that the extended endpoints equal the cumulative
wrap-safe raw intervals, and reproduce the firmware total from the modulo-32
down-counter differences. An exactly nominal 1,500-second TIMER0 span is not
required. The host must durably write its replay attestation before sending the
response evidence acknowledgement. The phase-4 digest is the canonical hash
of the PSQ replay digest, the content-verified raw-SNP window-proof digest and
the exact PSQ-to-ACT application join. The acknowledgement command also carries
the plant-sign record, request/application, DAC epoch, response count and
response source close; firmware compares that tuple and echoes the complete-
chain digest in `response_ack` and `handoff`.

An acknowledgement mismatch, timeout, missing evidence, discontinuity, parser
loss, reset/session/build/profile/policy/config/topology change, D14/D8 fault,
unproven DAC epoch or first-consumer mismatch invalidates the same-run
attestation and enters fail-static. There is no identification retry.

## Deterministic regression matrix

The focused pre-build gate must cover:

| Surface | Required cases |
|---|---|
| 1,500 accumulator | exact 900 and 901 exclusion alignment; exact deadline; contiguous two-window output; unsigned 64-bit total; invalid interval; gap; session and epoch reset |
| Pre gate | equal and unequal totals; zero and counts 1/5/6; both signs; natural tight and non-tight; prior global application |
| ID request | exact `0xA827` and `0xA851`; role preservation through request, acceptance and application; no retry |
| Application origin | post-write tick captured on Core 0 and unchanged through Core 1, estimator, records and host |
| Response gate | signed responses `-15,-14,-3,-2,0,2,3,14,15`; both command directions; wrong sign; first eligible support only |
| Replay ACK | exact tuple/digest; mismatch in each identity; late/missing ACK; durable attestation before command |
| Handoff | global `1/21`; exact cadence origin; natural origin at post-ID code; zero path; empty directions; first downstream natural decision |
| Natural parity | identical post-handoff 600-second observations produce the same CX320 natural demand, integer delta, counterfactual, materiality and response classification |
| Invalidation | reset, session, build/profile/policy/config, D14/D8, epoch, capture owner, parser/transport and health faults |
| Terminal behavior | fail-static, independent bounded abort, no restoration, retained last confirmed code |

## Complete actual-process rehearsal

The evidence-bearing rehearsal must use the actual live process topology and
the exact candidate host tools:

1. start the real capture process as sole serial owner and confirm exact
   build/profile/run identity;
2. start the real live supervisor, command FIFOs, host abort FIFO and monitor;
3. establish setup and prove exact post-write tick and every setup consumer;
4. accelerate only scientific waiting while retaining the real serial,
   parsing, FIFO, acknowledgement, replay and storage paths;
5. traverse `pre1 -> pre2 -> ID request -> acceptance -> application ->
   response -> host replay -> response ACK -> handoff -> first natural
   request -> natural response`;
6. repeat deterministic rehearsal cases for response floor/ceiling/sign and
   evidence-ACK mismatch without consuming physical authority;
7. obstruct normal transport and prove independent bounded abort submission,
   delivery and durable capture before closing the serial owner;
8. rotate evidence without an ownerless interval;
9. run the production analyzer, finalizer, seal and registration commands on
   the retained rehearsal package;
10. validate every resulting file against the same frozen manifest and verify
    all transitive hashes.

The PTY carrier replaces the physical plant and firmware boundary. Therefore
the release gate must also retain the cheapest deterministic compiled firmware
and cross-core regressions for exact post-write tick propagation, accumulator
behavior, state-machine transitions and first-consumer handoff. The rehearsal
must not claim those replaced boundaries.

## Physical entry gate

Physical execution is permitted only after all of the following are true for
one immutable source revision:

- focused producer-to-first-consumer regressions pass;
- the affected exact firmware profile builds;
- current release tests and expected-failure matrix pass;
- one exact UF2 and complete build provenance are frozen;
- the bundle binds every firmware, policy, estimator, config, replay, host,
  command, timing, authority and stop-condition identity;
- structural no-I/O preflight passes;
- the complete actual-process rehearsal above passes with zero unexplained
  parser loss, ownerless serial interval, unacknowledged transition or
  transitive hash mismatch;
- the single-use activation binds the operator-authorized CX321 v2 programme,
  exact board serial, bundle, proposal and rehearsal.

Any failure before this point is a preparation failure. It must be corrected
and the shortest affected deterministic gate repeated before a physical run;
it must not be converted into bench evidence.
