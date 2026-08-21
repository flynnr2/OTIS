# CX321 Bounded Active-Hybrid Successor

Status: exact clean-source bundle, structural preflight and same-bundle
rehearsal passed; the operator-authorized single-use Stage 5 activation is
effective and physical entry is pending.

CX321 is the selected successor to the sealed CX320 bounded non-pass. Its
purpose is still to test the unchanged natural firmware hybrid control law, not
to replace it with an artificial large-step controller.

The v2 design adds one separately identified plant-sign transaction first. It
uses a dedicated 1,500-second estimator and a 21-code stimulus. Only after that
transaction demonstrates the predicted DAC sign may CX321 open a fresh phase-
comparison baseline and permit the unchanged natural control law, which
continues to use the selected 600-second estimator. Global authority accounting
includes the identification move, while natural-controller chatter history is
explicitly rebased at the post-identification code.

The implementation covers firmware, host replay, supervision, analysis and the
exact first natural consumer after identification. Physical authority is now
limited to the frozen bundle and progressive envelope recorded below; it does
not authorize criterion changes, live extension, automatic retry or automatic
restoration.

## Why v1 was superseded

The original offline v1 proposal used the first fresh 600-second response and
the existing two-count floor. Exhaustive timeline-faithful replay over the
43,227-second fixed-code record found 74 false signed detections among 9,564
eligible exact-stable-pre placements. Its predicted minimum 21-code response
cleared the gate by only `0.061` count.

The requested candidate exercise compared that gate with persistent 600-second
gates, longer-window estimators and a drift-cancelled two-direction bracket.
The complete methods, results and evidence limits are in
[`02_RESPONSE_OBSERVABILITY_CANDIDATE_COMPARISON.md`](02_RESPONSE_OBSERVABILITY_CANDIDATE_COMPARISON.md).

The selected 1,500-second candidate produced no three-count false detection in
18,219 eligible placements in either exact-deadline boundary phase and gives
`5.153..5.460` expected counts for the
same 21-code response. It also has direct parity to all nine retained 2,400-
second plant-characterization visits after their frozen 900-second exclusions.
This is finite-record separation, not a calibrated false-positive probability.

## Quantitative basis

The new identification estimator has:

```text
count increment = 1 / 1500 Hz
observed fixed-code range = 2 exact counts
identification floor = observed range + 1 count
                     = 3 / 1500
                     = 0.002 Hz
```

The conservative retained plant gain remains:

```text
G_min = 0.00016357422282453626 Hz/code
```

The smallest arithmetic floor-clearing step is now 13 codes:

```text
ceil(0.002 / G_min) = 13
```

Thirteen codes predict only `3.190` estimator counts at `G_min`, so CX321 does
not select that thin `0.190`-count margin. The already bounded 21-code step
predicts:

```text
21 G = 0.0034350586793152614 .. 0.003640142109361477 Hz
     = 5.152588018972892 .. 5.460213164042216 exact 1500 s counts
```

The 21-code stimulus therefore has more than two counts of modeled minimum
margin over the observed three-count floor. It remains within the established
`0xA800..0xAB00` range and the existing per-step maximum. It is no longer
described as the smallest floor-clearing step for the selected estimator.

CX320's natural six-code transaction predicted only
`0.0009814453369472176..0.0010400406026747078 Hz`, below even the new
identification floor. The natural controller is intentionally not scaled to 21
codes: doing so would change the controller science and phase materiality being
tested.

## Selected plant-sign gate

After exact setup application and propagation at `0xA83C`:

1. Exclude through the 900-exact-device-second deadline, then begin with the
   first interval whose opening D14 boundary is at or after that deadline.
   Require two contiguous, non-overlapping, same-epoch 1,500-second estimates
   with exactly equal total counts. Their
   signed error must be nonzero, no more than five 1,500-second counts from
   nominal, and the unchanged 600-second control state must also be
   `TIGHT_INSIDE`. No automatic application may precede this gate. The two
   estimate closes occur at or later than the 2,400- and 3,900-second lower
   bounds after setup. The second exact close is the identification decision
   and request boundary; response timing starts only at the later acknowledged
   application tick.
2. Apply exactly one identification stimulus:

   ```text
   delta_id = -21 * sign(pre_error_counts)
   ```

   A positive pre-error requests `0xA827`; a negative pre-error requests
   `0xA851`.
3. From the exact acknowledged identification application tick, exclude through
   the 900-second deadline and then construct the first wholly fresh 1,500-
   interval response estimate. Its recorded close is at or later than the
   2,400-second lower bound after application. Setup-to-response is therefore
   at least 6,300 seconds plus the recorded identification
   request/accept/application latency; it is not an exact 6,300-second promise.
4. Evaluate exact integer counts:

   ```text
   pre_total = second exact pre-stimulus 1500 s total
   post_total = first exact fresh post-stimulus 1500 s total
   r_counts = post_total - pre_total

   r_counts * delta_id > 0
   3 <= abs(r_counts) <= 14
   ```

   Fourteen counts is the largest integer 1,500-second response below the
   existing 21-code empirical classifier threshold. All support, session,
   identity, request, acknowledgement, applied epoch, health and host-replay
   identities must also be exact, and frequency must re-enter `TIGHT_INSIDE`.
5. Firmware's response evidence requires an exact host replay acknowledgement
   within 30 seconds. A passing acknowledgement opens only a fresh 1,800-second
   `PHASE_QUALIFY` comparison residence; it does not directly release a hybrid
   application. There is no automatic retry or restoration.

No second post-stimulus estimate is part of the identification statistic. The
comparison showed that persistence without the complete magnitude floor is not
protective, while the selected 1,500-second response already has the required
finite-record separation.

## Conditional hybrid continuation

The identification stimulus is not a frequency-control application, phase-
control application, phase-material application or phase-performance sample.
It never enters the natural controller demand or frequency-only
counterfactual. It does consume one of four application slots and 21 of 84
global movement codes, and it updates the global last-application cadence
timestamp. This leaves three applications and 63 codes—two required natural
material transactions plus one spare.

The identification direction does not enter natural-controller direction,
reversal, path-efficiency or net-displacement history. At handoff, that natural
history is empty and its origin is the exact post-identification code; the
global count remains one and global movement remains 21. This separation is a
required CX321 infrastructure change, not a change to the natural control law.
The exact state must propagate through the first natural decision.

After plant-sign pass, exact ACK and tight re-entry, CX321 retains the fresh
1,800-second frequency-only comparison segment ending at the first eligible
natural 600-second selected-estimator epoch. The 1,800-second residence can end
before an estimator boundary, so it cannot itself issue a request. The first
eligible selected epoch is at or later than the 4,500-second lower bound
after the acknowledged identification application. The setup-to-request lower
bound is therefore at least 8,400 seconds plus identification transaction
latency. Physical application follows the selected decision by its own recorded
request/accept/application latency.

Natural hybrid requests remain exactly the CX320 controller output:

```text
frequency demand = - authoritative 600 s frequency error
phase demand = clamp(- relative-phase movement / 21600 s)
combined demand -> existing gain -> clamp to 21 codes -> half-away-from-zero
```

Their response checkpoints also remain on the existing 600-second estimator
and classifier. A healthy sub-floor material response may remain unresolved; it
is never relabelled as signed merely because the separate identification gate
passed. The complete programme still requires two natural material
applications, phase improvement, frequency preservation and all frozen
identity, continuity, health and terminal criteria.

The same-run plant-sign attestation is invalidated by reset/reflash, session,
build, policy, estimator or topology change, D14/D8 discontinuity, common-
health fault, ownerless capture handoff, unproven DAC epoch, contradictory
response or replay/consumer propagation failure. It cannot be carried into a
later run.

## Alternatives

| Alternative | Disposition |
|---|---|
| First 600-second response at two counts | Rejected: 74 false signed detections and only `0.061` count minimum margin. |
| Two persistent 600-second responses at one count | Rejected: 289 false attributions. |
| Two persistent 600-second responses at two counts | Not selected: zero observed false attribution, but poor and direction-dependent sensitivity at an exactly two-count response. |
| 1,200-second estimator | Not selected: direct plant parity but less response margin than 1,500 seconds. |
| 1,800-second estimator | Not selected: no complete settled window in the retained plant dwells. |
| Two-direction 21-code bracket | Reserved redesign: cancels exact linear drift, but needs a new multi-transaction classifier and chatter semantics and leaves no authority spare. |
| Scale a natural hybrid request to 21 codes | Rejected: changes the controller and counterfactual materiality. |

## Frozen artifacts and next gate

The active offline v2 artifacts are:

- `profiles/estimators/cx321_plant_sign_1500_config_v1.json`;
- `profiles/estimators/cx321_plant_sign_1500_v1.json`;
- `profiles/qualification/cx321_plant_parity_1500_reconstruction_v1.json`;
- `profiles/qualification/cx321_response_observability_comparison_v1.json`;
- `profiles/qualification/cx321_bounded_response_observability_v2.json`;
- `profiles/discipline/cx321_bounded_active_hybrid_plant_sign_v2.json`.

The compact exact-count replay fixture is
`tests/fixtures/cx321_stage3_stable_interval_counts_v1.json`; it is derived from
and binds the ignored raw CNT evidence rather than replacing that source.

The v1 gate and policy remain immutable provenance for the superseded decision;
they are not effective designs.

Implementation and deterministic producer-to-first-natural-consumer proof are
complete. Fast and Campaign gates passed; Release passed 985 current tests with
27 historical tests excluded, all eight supported firmware profiles and all
eight expected-failure guards. A disposable actual-process PTY rehearsal also
passed the identification and natural response paths, obstruction, abort,
rotation, analysis, sealing and registration with zero parser errors.

The exact clean-source entry bundle is
`f83d78d5213716c3c21e4823cf0fb533946c11206ec81a3f96223a392bcb3641`,
the proposal is
`6de6d81ce6cb49ad47fa5b746a03821ba0404c55ccd3c1ca66c575111eccfa30`,
and the frozen UF2 is
`c5fb2887c291f640543c3d27bb03dafea9cb5d77fd65c0c47a97b2edb38a2ef9`.
Structural preflight and the complete same-bundle actual-process rehearsal
passed with zero parser errors. The operator authorized that exact bundle and
proposal on 2026-08-21. Initial activation
`7046a9ca58eb2a764b2da799acf89b5b649ebd044d88f0f4bad1b83cd72442ea`
reached a prewrite platform terminal because the runner was invoked outside
the rehearsed Python environment: the UF2 flashed, but capture never opened and
there was no setup request, DAC write or control arm. That terminal is sealed
as `f8e3bb8a1b887ed10c303e93d871eeb369cb19e05700d149708d38b370edadc5`.
The operator's expanded remediation authority permits the exact predecessor-
bound attempt-2 activation
`9013d24a92c35f5af65d5b7124915ab885ca8beda2862e3d4ef12bc72adf96ac`;
the firmware, bundle and scientific criteria remain unchanged.
