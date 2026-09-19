# Nano RP2040 Connect capture baseline implementation prompt

Implement the current Arduino Nano RP2040 Connect baseline for OTIS, preserving
hardware-owned D14/D8 measurement and adding the service-latency observability
described below.

Work in `/Users/richardflynn/git/OTIS`. Follow the applicable `AGENTS.md`
instructions and read the relevant foundations before changing timing
semantics. Inspect the current working tree and preserve unrelated or
concurrent changes.

## Direction: move forward without backward compatibility

Backward compatibility is not a requirement. Build one coherent current
implementation.

You may replace interfaces, schemas, record formats, naming, internal queues
and host consumers where that produces a simpler, clearer design. Update all
affected current producers and consumers together.

Do not retain legacy adapters, alternate backends, dual-format emission,
compatibility switches or obsolete tests merely to support superseded
implementations. Delete replaced machinery once its replacement is verified.
Avoid maintaining parallel approaches indefinitely.

Preserve existing experimental evidence unchanged, with its original
provenance. Historical evidence can be interpreted using its recorded
repository revision; current code need not support retired formats.

This freedom does not waive measurement correctness, capture isolation,
control safety or verification. It also does not require replacing sound
components: retain the existing PIO counter where it remains the best
implementation.

## Context and scope

Read:

- `docs/50_SOFTWARE/D14_D8_EDGE_CAPTURE_PROPOSAL_2026_09_19.md`
- `docs/50_SOFTWARE/RP2040_CAPTURE_ARCHITECTURE.md`
- `docs/50_SOFTWARE/PPS_PIO_PROOF_AND_VERIFICATION.md`
- `docs/50_SOFTWARE/PPS_CAPTURE_LATENCY_JITTER_AUDIT_20260801.md`
- `docs/50_SOFTWARE/INSTRUMENT_OWNERSHIP.md`
- `docs/00_FOUNDATIONS/OTIS_REFERENCE_TERMINOLOGY.md`
- `docs/50_SOFTWARE/SINGLE_REFERENCE_OWNER_REPAIR.md`
- `data_contracts/pps_snapshots_v2.csv.md`

Publication baseline: PR #190, merged at
`6bf5dbcfdf12656f643736d527003398117371a7`, replaced the separate GPIO REF and
DMA paths with a bounded PIO FIFO-drain IRQ and one reference record owner.
Its per-record CPU service coordinate and recognition uncertainty are not an
edge-latched timestamp. Start from that implementation, or its current
successor. Source and current contracts take precedence over earlier narrative
descriptions. Do not restore a GPIO observer, DMA path or association queue
solely to recreate an endpoint listed in the earlier discussion.

If useful, consult these project tasks:

- Capture-design discussion: `01a0b8fd-3ecc-78b1-9945-deed590696ef`
- “was service latency implemented?”: `01a0a0b5-d14a-78c2-9b98-0cabe6b7c740`

The proposal discusses an FPGA, but **this implementation targets the existing
Nano RP2040 Connect only**. Do not introduce new hardware, substitute another
processor, or implement D10 capture in this task.

Complete the implementation, documentation and appropriate offline
verification. Do not stop after producing another proposal. Firmware upload
and physical acquisition are separate operations requiring explicit operator
authorization.

## Delegation and model selection

You are authorized to delegate bounded, independent subtasks to subagents and
to select available models and reasoning-effort levels appropriate to each
task.

Use more capable models and higher reasoning effort for capture architecture,
timing semantics, clock-domain relationships, concurrency, control-authority
boundaries and independent technical review. Use lighter models and lower
effort for straightforward searches, mechanical edits and well-specified
verification tasks.

Delegate where parallel work provides useful progress. Avoid overlapping
edits, duplicate investigations and unnecessary agent overhead. Give each
subagent a concrete scope, applicable constraints and expected deliverables.

The primary agent remains responsible for architectural coherence,
integration, reviewing delegated results and completing end-to-end
verification. Delegation does not expand hardware, campaign or control
authority.

## Measurement requirements

Maintain these roles:

- **D14/GPIO26:** sole authoritative GNSS PPS/reference input.
- **D8/GPIO20:** authoritative oscillator count and measurement numeraire.
- **D10/GPIO5:** future external-event input, excluded from current
  implementation and from PPS/control authority.

PPS and eventually D10 transitions are the events whose measurement records
matter. D8 supplies their continuous cycle-count coordinate. We do not require
an archival stream of individual oscillator edges.

The current single-state-machine PIO count/snapshot mechanism already excludes
CPU interrupt latency from the count aperture. Do not describe ISR
optimization as an improvement to oscillator-count accuracy.

Retain that mechanism unless a demonstrated requirement justifies a finite
replacement. If replacing it, prove the new timing semantics and update the
complete measurement path; do not preserve the old backend solely for
compatibility.

Preserve raw cumulative counts, source identities, sessions and continuity
evidence. Derive incremental intervals from valid endpoints. DAC adjustments
must not reset the capture counter or rewrite observations.

Preserve the substantive PPS-to-estimator-to-bounded-DAC control requirements
and authority separation. Existing interfaces and record layouts may change.

## Implement service-latency observability

First establish which endpoints actually exist in current code. Implement one
consistent diagnostic record model with explicitly named stages and domains.

Where supported, measure:

1. Per-record FIFO-service coordinate → foreground reference/boundary service
   on the current single-owner path. Preserve D14 GPIO ISR-to-service only if
   that diagnostic observer actually exists in the implementation being worked
   on; otherwise mark that endpoint unavailable rather than reintroducing it.
2. First software consumption → associated observation ready.
3. Observation ready → first estimator/control consumption.
4. Successful cross-core queue publication → consumption of that same message.
5. Output queue entry → the precisely identified firmware transport-service
   endpoint.

For D8, measure service of each hardware count snapshot at a D14 boundary.
There is no requirement for software service or latency records for every
oscillator edge.

Identify each sample by capture session, channel, source sequence and stage
pair. Preserve raw endpoint coordinates, clock domains, status and any
uncertainty. Do not assume that similarly named sequence counters are
interchangeable.

Distinguish callback entry, first polling observation, queue publication,
completed parsing, serial-buffer acceptance and actual transport completion.
Name each metric according to the endpoint truly observed.

Provide bounded per-channel/per-stage:

- Eligible, missing and ambiguous sample counts.
- Minimum and maximum, with source identities for extrema.
- A small, versioned histogram.
- Threshold-exceedance counts.
- Diagnostic-drop counters.
- A bounded selection of individual samples explaining unusually slow service.

Use fixed-size storage and bounded operations. Defer formatting and
publication. Diagnostic congestion must not obstruct capture, alter canonical
validity, trigger new control actions or acquire abort authority. Thresholds
are initially observational.

Keep GNSS serial-processing diagnostics separate from D14 PPS latency.

Existing diagnostic formats may be replaced outright. Prefer a single
consistent model over layering another format onto obsolete machinery.

## Hardware start markers and fine timing

The CPU FIFO-service timestamp is not a hardware edge-latch timestamp. The PIO
word captures the D8 count, not the RP2040 microsecond timer. Preserve existing
recognition uncertainty and batch ambiguity; neither an empty-FIFO bracket nor
a singleton read supplies an exact hardware-to-service latency.

Make a bounded, concrete assessment of whether an additional RP2040 hardware
marker can be implemented cleanly within the current instruction,
state-machine, DMA, memory and service budgets.

Any proposed hardware-to-service metric must have:

- A real hardware start marker.
- An exact relationship to the relevant event or count snapshot.
- A common clock domain or an explicit bounded cross-domain mapping.
- Defined rollover, restart, loss and ambiguity semantics.

A DMA-triggered timer read measures a later bus transaction; it is not an edge
latch. A second PIO state machine cannot simply read the first state machine’s
scratch counter. Nominal unit conversion does not synchronize independent
clocks.

Likewise, do not claim fractional D8-cycle capture without preserving and
proving the required edge-neighbourhood relationship.

If a sound addition or replacement is feasible, implement it and verify the
complete producer-to-consumer path. If it is not, complete the useful
software-stage baseline, expose hardware-to-service measurement as explicitly
unavailable, and document the precise remaining limitation.

Do not create an open-ended PIO framework or weaken the memory budget to obtain
a nominal result. Remove obsolete machinery where this safely frees resources;
do not spend resources on backward compatibility.

Future D10 must remain possible without sharing diagnostic congestion or
backpressure with D14/D8.

## Verification and delivery

Choose verification proportionate to the changed risk surface, following
repository rules. Cover the actual operational path and relevant failure
modes, including:

- Exact event identity across processing and queue boundaries.
- Counter rollover and session changes.
- Missing, delayed, duplicated or ambiguous observations.
- Queue congestion and diagnostic overflow.
- Histogram boundaries, extrema and threshold reporting.
- Instrumentation overhead and memory/resource limits.
- Preservation or renewed proof of the hardware capture aperture.
- Control-authority and diagnostic-isolation boundaries.

Replace tests tied to retired interfaces with tests of the new contract.
Preserve meaningful invariant coverage; do not retain obsolete implementation
expectations as compatibility requirements.

Use deterministic fixtures or injection for rare conditions. Offline
verification must not be presented as physical timing qualification.

Update affected contracts, schemas, firmware and host consumers, resource
documentation, methodology and known limitations together. Remove obsolete
current-use documentation and entry points. Historical records remain
identifiable as historical evidence.

Finish with a concise account of:

- What was implemented, replaced and removed.
- The exact start/end definitions of each available latency metric.
- Which measurements remain unavailable and why.
- Memory, processing and telemetry costs.
- Verification performed and its limits.
- The shortest remaining physical qualification gate.
