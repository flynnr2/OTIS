# CX317 bounded active transaction contract

Status: Stage 3 frozen candidate. Hardware arming is not authorized by this
document alone.

## Scope

This contract converts the existing 600 s CX317 I-only preview into two
dedicated bounded programme profiles. It does not add phase control,
proportional or derivative control, adaptation, thermal compensation, Kalman
estimation, predictive holdover, automatic retry, or automatic restoration.

The three owners remain separate:

1. `otis_cx317_preview_live` and `otis_cx317_i_only_engine` produce the
   immutable numerical decision;
2. `otis_cx317_active_transaction` owns identity, eligibility, authorization,
   budgets, sequence ordering, request consumption, acknowledgement, and
   response state;
3. `otis_cx317_active_actuator` is the sole controller-to-DAC call site and
   makes exactly one I2C attempt for one accepted request.

A request is never treated as an applied code. The controller always uses the
last exactly acknowledged applied code.

## Dedicated profiles and immutable envelope

| Profile | Run identity | Start | Corrections | Cumulative movement |
|---|---|---:|---:|---:|
| `cx317_bounded_active_campaign_a` | `cx317_bounded_campaign_a:3170001` | `0xA950` | 16 | 336 codes |
| `cx317_bounded_active_campaign_b` | `cx317_bounded_campaign_b:3170002` | `0xA800` | 8 | 168 codes |

Both profiles freeze:

- DAC range `0xA800..0xAB00`;
- maximum step 21 codes absolute;
- minimum applied-to-applied cadence 1800 s;
- 900 s post-application exclusion and 600 s wholly fresh authoritative
  support;
- asynchronous GNSS serial discovery across the documented MT3339 baud set,
  frozen 115200-baud operation, exact PMTK identity/output readback, and
  runtime RX-only service after bounded fixed-command configuration;
- the qualified PPS-gated snapshot/count backend;
- one outstanding request and one I2C attempt;
- no automatic retry and no restoration write on any stop.

All supported non-programme profiles compile
`OTIS_ENABLE_CX317_BOUNDED_ACTIVE=0`. The matrix builder refuses a supported
active profile outside the two identities above.

## Exact identity binding

The authority layer compares complete strings, not shortened hash tags. Every
arm binds:

- fixed campaign run identity;
- build identity
  `<OTIS_BUILD_SOURCE_SHA256>:<OTIS_BUILD_CONFIG_SHA256>`;
- exact generated firmware profile ID;
- snapshot session ID;
- estimator SHA-256
  `5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c`;
- plant-model SHA-256
  `d8fbc3539759be1de60d6b4507a50f029b3eaf830952b65ddb4c9849992ef8dd`;
- numerical-policy SHA-256
  `19cddd7cb169c4c733b7cfd69085f9ecc087ad77a874f265c4c7c0f053aced43`;
- active-policy SHA-256
  `657df688c8e6b1bce1ac8280b46e5388ee1d6dfbe31e34735611c933ca4f261e`;
- response-policy SHA-256
  `0a7ec7b8f569da4a233c03e56c42bd7bd522ca1c27e97d4028b6c52a2ecfe963`;
- exact start, range, maximum step, correction count and cumulative budgets.

The first live snapshot session binds the transaction. A later session change
latches a fault. Reboot clears all volatile arming and capture leases.

## GNSS and reference eligibility

GGA fix quality, GSA fix dimension, and the 1PPS pin are separate evidence:

- GNSS serial discovery does not gate boot, D14/D8 capture, telemetry or host
  attachment; it independently inhibits setup/control authority until the link
  is online at 115200 with exact PMTK identity and output configuration;
- RMC and GGA must be checksum-valid, mutually fresh, fix-valid, dated, and
  UTC-bearing under the frozen metadata policy;
- the receiver identity epoch must remain 1 for the run;
- a fresh checksum-qualified GSA Mode 2 value of 3 is required as explicit 3D
  evidence;
- GGA quality 1 or 2 may be valid; quality 2 means a differential position
  solution and does not itself encode 2D/3D;
- the raw D14 1PPS/reference path remains the sole timing authority. Its
  accepted interval bounds, snapshot continuity, count validity, and all
  authoritative capture/boundary/backend fault counters must remain clean;
- D10 is the external event/edge input and is outside this PPS/oscillator
  control transaction. It is neither configured nor interpreted as a PPS
  witness and never enters setup authority, control eligibility, response
  validity, or actuation.

## Arming, capture lease, and abort

The active serial surface is deliberately code-free:

- `ACTIVE LEASE <monotonic_sequence>` renews the capture-owner lease for at
  most 30 s;
- `ACTIVE ARM <authorization_sequence> <nonce> <absolute_expiry_s>` requests
  one short-lived authorization; expiry must be no more than 120 s away;
- `ACTIVE ABORT` latches the device-side abort without consulting estimator
  health and without writing the DAC;
- `ACTIVE EVIDENCE <request_sequence> <phase_sequence>` acknowledges receipt
  of non-droppable transaction evidence, where phase 1 is
  `request_accepted`, phase 2 is `application`/`application_fault`, and phase
  3 is `response`;
- `ACTIVE?` reports the current read-only state.

No active command accepts a DAC code, error, delta, or `actionable` value.
`actionable=true` exists only in the immutable request returned by the
authority layer. Acceptance immediately copies the request into the actuator
transaction and clears the stored actionable flag.

The capture lease and USB abort path must be live at arm and request time. Loss
while armed or awaiting a response latches a fault. The independent host abort
FIFO remains a Stage 4 capture-owner responsibility.

## Start-code establishment

Because the AD5693R path cannot prove a retained register value after a new
firmware session, the independent manual path may make one exact write to the
profile's frozen start code before the first correction. It does not count as
an automatic correction. Any other manual code, a duplicate start write, or a
manual write after control begins is rejected before I2C and latches abort.

## Transaction states

The only ordinary path is:

`DISARMED -> ARMED -> REQUEST_PENDING -> ACCEPTED_AWAITING_APPLICATION -> AWAITING_RESPONSE -> DISARMED`

For each step:

1. a selected 600 s estimate supplies decision and source sequence references;
2. every identity, health, applied-code, lease, evidence, range, step, cadence,
   count and cumulative gate is evaluated;
3. one request becomes actionable;
4. exact acceptance consumes it and clears actionability;
5. the firmware emits `request_accepted` with the immutable decision/source
   capsule and waits for exact phase-1 evidence acknowledgement;
6. only that acknowledgement lets the actuator owner validate the accepted
   identity and attempt one write;
7. exact requested/accepted/applied agreement increments correction count,
   cumulative movement and DAC epoch;
8. estimator and controller history are reset before the application record
   is emitted;
9. the next authoritative estimate after exclusion plus fresh support is used
   only to classify the response;
10. a fresh authorization is required for a later correction.

The ACT `request_accepted`, application, and response records are independently
evidence-gated. Duplicate or out-of-phase acknowledgements cannot advance the
transaction. A phase-1 acknowledgement is rejected unless the complete
request frame has left the firmware transport and every critical continuity
gate is still healthy. Missing acknowledgement for any phase faults after 30
s. Until the capture owner acknowledges the current phase, a new arm fails
eligibility.

The host capture owner writes every `ACT` row to
`active_transactions_v1.csv` and flushes it before issuing the matching
evidence acknowledgement. The serialized row is always `actionable=false`.
The phase-1 row contains the decision and source ranges, pre-error, current
confirmed code, requested delta/code, exact identities, authorization, and
budgets. The application row adds accepted/applied codes, timestamp, single
I2C outcome, DAC epoch, and explicit estimator-history reset. The response row
ties post-error and observed/cumulative response classification back to the
same immutable request.

## Fail-static behavior

Duplicate, stale, reordered, expired, mismatched, clamped, ambiguous, missing,
or failed transactions latch `FAULT`. Capture, GNSS, session, estimator,
model, temperature, count, PPS, applied-code, evidence, lease, or abort-path
loss also latches locally. `ABORTED` is a separate latched operator/device
state.

Neither state exposes a retry function or restoration target. The last exactly
confirmed applied code remains the controller state; recovery requires a new
run as defined by the programme.

## Stage 7 dual-core evidence extension

Stage 7 adds a fourth durable phase before physical application:

`request_created -> core0_accepted -> application -> response`

The authority layer's private request is `actionable=true` only between its
creation on Core 1 and exact acceptance on Core 0. The ACT CSV row is an
observational copy and remains `actionable=false` in every phase, including
`request_created`; it cannot be replayed as an actuator command. After the
host has fsynced that row, `ACTIVE EVIDENCE <request_sequence> 1` releases the
private request already held by firmware. Core 0 acceptance clears the private
actionable flag before `core0_accepted` is emitted. Phases 2, 3 and 4 then
durably gate acceptance, application and response respectively.

This distinction is intentional: internal request actionability is exercised
and checked by the firmware transaction/queue guards, while durable host
evidence records the exact request identity without carrying authority.
