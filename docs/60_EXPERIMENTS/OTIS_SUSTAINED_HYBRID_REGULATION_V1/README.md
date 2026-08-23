# OTIS sustained hybrid regulation programme V1

## Decision

This finite programme asks whether the unchanged CX322 natural hybrid control
law can sustain D14-referenced phase and frequency regulation for 86,400
qualified seconds with bounded bidirectional authority, an observed reversal,
and at least 21,600 qualified seconds of post-reversal recovery evidence.

D14 remains the sole authoritative PPS/reference input, D8 remains the sole
oscillator/count input, and D10 remains an external event input only. GNSS
serial is receive-only qualification metadata. The programme sends no receiver
configuration or PMTK commands.

The predecessor evidence is CX322 Attempt 7 at
`runs/cx322_bounded_hybrid_fact_gathering/stage5_live_attempt7_20260822T1921Z`.
Its sealed acquisition is retained unchanged. It motivates the longer run but
is not reclassified as a sustained-regulation result.

## Frozen finite authority

- Setup code: `0xA83C`.
- Allowed DAC range: `0xA800..0xAB00`.
- At most 12 natural automatic applications.
- At most one separately accounted 21-code deliberate reversal challenge.
- At most 13 physical control applications including that challenge.
- At most 84 codes cumulative absolute movement.
- At most 21 codes per application and at least 1,800 seconds between applied
  actions.
- One outstanding transaction, no automatic retry, no restoration, and no
  duration extension.
- Qualified duration: 86,400 seconds; absolute wall limit: 108,000 seconds.

If no natural applied reversal is present by 43,200 qualified seconds, the
first eligible challenge is due no later than 50,400 qualified seconds while
preserving at least 36,000 seconds of remaining authority. A prior natural
reversal cancels it. The challenge uses the same direction as all prior
same-sign natural applications, or negative when no natural direction exists.
Its first later opposite-direction natural application is the challenge
recovery.

## Characterization is allowed

Descriptive response magnitude, empirical gain comparison, detection
materiality, synthetic sensitivity cases, and an unfavorable modeled final
slope are characterization. They are retained with their provenance and do
not inhibit entry, abort the physical run, or create a failed verdict.

A non-pass or failure requires real retained evidence to violate a criterion
that was frozen before the run. Those criteria are: no required reversal or
recovery, persistent wrong-direction response across two complete same-epoch
response windows, authority/accounting breach, absolute raw relative phase
escape beyond 36 cycles, final 21,600-second absolute phase OLS slope above
`1/3600` cycle/s, material frequency degradation beyond the frozen comparison,
hybrid chatter/path exhaustion, incomplete duration, or loss of exact
measurement/provenance authority. Observation latency alone is retried or held
within its bounded deadline; it is not a contradiction.

## Exact operational-path entry invariant

Entry requires one clean immutable source revision, the exact sustained
firmware profile and UF2 identity, and the actual host tools used for the run.
The operational rehearsal must propagate, in order:

1. setup code and DAC epoch through every named consumer;
2. a first natural request through request, acceptance, application, response,
   durable replay acknowledgement, and the first released decision;
3. a repeated natural transaction through the same complete path;
4. the deliberate challenge and its separate automatic/physical accounting;
5. the opposite-direction recovery and the first decision after its response;
6. obstruction, independent priority abort delivery, fail-static status,
   atomic evidence rotation, analysis, sealing, and registration.

The sustained status snapshot contract makes the automatic count, natural
reversal disposition, challenge disposition, direction, code, DAC epoch,
application timestamp, and recovery disposition mandatory fields. A producer
acknowledgement without the exact first dependent consumer is insufficient.

## Attempt milestones

A physical attempt is not created until build, bundle, structural preflight,
and complete operational rehearsal all pass. When it is created, its report
publishes absolute UTC targets derived from the actual start and the qualified
device-time origin. The relative milestones are:

- capture, sole serial ownership, flash, exact identity, setup propagation;
- qualified origin and first eligible natural decision;
- each complete application/response transaction and its first dependent
  decision;
- 43,200-second natural-reversal boundary;
- challenge application by 50,400 seconds when required;
- reversal recovery and 21,600 seconds of post-reversal support;
- 86,400-second qualified endpoint, bounded by 108,000 wall seconds;
- terminal abort delivery where applicable, analysis, seal, and registration.

Only state transitions, these milestones, faults, and actions are reported.
The authoritative supervisor state and retained records are monitored more
frequently than the shortest material interval throughout an active attempt.

## Attempt 1 result

Attempt 1 terminated fail-static on 2026-08-23 with an actual platform
identity/integrity failure. It did not fail because of response magnitude,
phase materiality, or any other allowed characterization. The response ACKs
were durable and healthy-characterization records, but the exact completed
response identity did not reach the first later controller decision before
wider authority was released.

The activation was consumed by that first physical terminal. There is no
remaining live, flash, reset, serial, DAC, setup, or control authority under
Attempt 1. Offline repair and preparation remain allowed; any later physical
attempt requires a new exact bundle, a complete multi-transaction rehearsal,
and explicit operator authority.

The terminal timeline, exact evidence identities, superseding analysis, and
narrow repair are recorded in
[`01_ATTEMPT1_RESPONSE_IDENTITY_PROPAGATION_TERMINAL.md`](01_ATTEMPT1_RESPONSE_IDENTITY_PROPAGATION_TERMINAL.md).
