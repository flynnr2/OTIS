# OTIS Canonical Instrument Completion Work Programme

## Status and authority

Status: current planning authority, audited against repository HEAD on
2026-09-10.

This is the canonical sequence for completing the present OTIS instrument and
for evaluating replacement GNSS receivers, oscillators, power arrangements and
the successor timing board. It supersedes earlier roadmap ordering where that
ordering conflicts with this document. Historical experiment contracts,
terminals and evidence remain unchanged and must still be interpreted with the
revision that created them.

This programme does not authorize serial access, reset, flash, rewiring, DAC
movement or physical acquisition. Each physical stage requires an exact frozen
bundle and explicit operator authority.

## Decision-bearing objective

Produce one reproducible OTIS instrument configuration that:

- autonomously disciplines the selected oscillator from the sole authoritative
  GNSS PPS input while preserving complete control provenance;
- captures the external D10 event input in hardware without allowing D10-local
  behavior to affect reference validity, regulation, actuation or a run
  terminal;
- provides a physically characterized disciplined-frequency output;
- can compare candidate GNSS receivers and oscillators on dedicated,
  zero-authority measurement inputs without disturbing the installed control
  path;
- uses a documented and measured power, grounding, input-conditioning and
  output-distribution arrangement;
- exposes useful serial products without changing canonical acquisition or
  multiplying firmware images; and
- retains only the verification needed to protect the current instrument and
  its operational path.

The unit of progress is a working, evidence-bearing instrument capability or a
component-selection decision. A new document, test, firmware option or fixture
is supporting work, not a programme outcome by itself.

## Audited disposition of the originating concerns

| Concern                                        | Repository state through 2026-09-10                                                                                                                                                                                                                                                                                                    | Programme disposition                                                                                                                                                                                                                                                                                                |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Serial output modes                            | Design discussed; no current profile contract or switching implementation was found. The fixed image emits the canonical operating stream.                                                                                                                                                                                            | Define host-side `FULL`, `EVENTS`, `BENCH` and `SUMMARY` products after the event and candidate-input records exist. Add device-side filtering only for a measured transport or client requirement.                                                                                                                  |
| Autonomous operation                           | The fixed `adaptive_hybrid_regulation` image performs the estimator, policy and bounded actuation locally.                                                                                                                                                                                                                            | Treat autonomy as the production control architecture, not a serial mode or selectable firmware profile. Preserve explicit observe-only and hold-static authority states where benchmarking requires no actuation.                                                                                                   |
| Dedicated candidate GNSS and oscillator inputs | Not implemented. D10 is reserved for external events; its isolated firmware capture backend is also not implemented.                                                                                                                                                                                                                  | Allocate independent candidate-GNSS PPS/metadata and candidate-oscillator count paths in the successor-board resource and pin plan. D10 remains the external-event input.                                                                                                                                            |
| GNSS baud robustness                           | Completed multi-artifact characterization selected 115200 with zero recorded serial/ring/parser faults in 23,100 confirmed-online seconds at that rate. The fixed image implements a bounded 9600/115200 startup transaction and causal requalification.                                                                              | Closed for the installed PA1616S/Nano path. Re-run only a focused bootstrap and service-margin qualification after a board, UART, receiver, power or service-topology change. Do not repeat the full multi-baud programme by default.                                                                                |
| Too many compile states                        | The current branch has already removed the firmware matrix and retains one fixed image and manifest.                                                                                                                                                                                                                                  | Closed as a reduction task. Preserve one supported production image. A board or component replacement becomes the next fixed image after selection; historical revisions remain the compatibility mechanism.                                                                                                         |
| Too many regression tests                      | Historical programme and compatibility tests were materially removed. On 2026-09-10 the current Release tier completed 427 tests, including the current-process operational rehearsal, in 204 seconds; the subsequent exact fixed-image build and binary/resource audit passed. | Remove or consolidate only checks that duplicate a protected invariant, test retired behavior, or add no earlier detection. Do not optimize for an arbitrary test count. |
| Firmware/host contract mismatch fragility      | A current machine-readable contract now owns record tags/versions/layouts and all 418 field encodings, command forms, typed ACTIVE status vocabulary, queue frontiers and named cross-record relations. The fixed build embeds its exact digest; live and offline host admission require it. Production emitter, command and response-classifier checks cover the latest escaped cases. | Keep complete bidirectional parity as a Stage 0 outcome. Any unexplained mismatch is a review-required diagnostic hold, never plausible zero/default data or host-invented abort authority. Require a fresh exact Release, build, freeze and rehearsal after an operational contract change. |
| Better power supply                            | The current TPS62827 3.3 V rail has a documented DC budget and observed 3.292 V level, but ripple, transients, cold-start behavior and ground coupling remain unqualified.                                                                                                                                                            | Make the power/ground architecture part of successor-board selection and measure the current and proposed arrangements before attributing timing anomalies to power.                                                                                                                                                 |
| Rewire on a different board configuration      | The current fixed target remains the Nano RP2040 Connect. The hardware roadmap identifies Raspberry Pi Pico 2/RP2350 as the likely successor direction, but no exact board is selected here.                                                                                                                                          | Select one successor board from an explicit pin, timing-resource, toolchain, power and operational comparison; then replace the fixed target rather than supporting two production boards indefinitely.                                                                                                              |
| Breakbeam on D10                               | The D10 pin/channel/schema seam exists, but the fixed image explicitly records external-event capture as not implemented and not isolated.                                                                                                                                                                                            | Implement the hardware-owned D10 capture path, qualify its failure isolation, and build the exact sensor interface including emitter current limiting, receiver bias/pull-up, input protection/series resistance and declared output polarity.                                                                       |
| Disciplined output                             | D9 forwarding and D6 digital monitoring exist. Prior evidence corroborates digital forwarding, but voltage levels, duty cycle, edge behavior, ringing, propagation delay, jitter, load sensitivity and independently referenced frequency remain unqualified.                                                                         | Complete the electrical output/interface design and the external waveform, load and non-interference qualification. D6 remains corroborating diagnostic evidence only.                                                                                                                                               |
| Exact estimator windows for other oscillators  | The current 600-second policy is already exact: one count is represented as 36 units on the `1/21600 Hz` lattice. Current wide-integer and fixed-point arithmetic is deterministic and replayable.                                                                                                                                    | Freeze the current arithmetic. Choose a different window only from candidate oscillator noise/stability, plant response and control needs. Add a typed rational boundary only when the first real candidate cannot be represented cleanly by the current policy.                                                     |
| Measurement-aperture bias and variability      | The current hardware aperture removes CPU, USB and host scheduling from timing truth, but GPIO, input conditioning, synchronizer and capture-path bias and variability are not a calibrated end-to-end timing claim.                                                                                                                  | Add a differential PPS-path characterization using a dedicated calibration/candidate input plus an independent external witness. Separate constant path bias from state-, power- and temperature-dependent aperture variation. D10 must not be repurposed as a PPS witness.                                          |
| GNSS PPS corrections and timing modes          | Current GNSS metadata qualifies the receiver but does not yet define a general observation contract for receiver-reported PPS quantization/sawtooth correction, cable-delay configuration, survey state or fixed-position timing mode.                                                                                                | Preserve the raw electrical PPS observation and add separately identified, initially zero-authority receiver timing context. Characterize navigation, survey-in and fixed-position operation for receivers that support them. Never overwrite raw D14 evidence with a corrected value.                               |
| Accelerated closed-loop simulation             | Current replay and native/Python parity cover the selected policy, but the programme does not yet define one accelerated path for recorded and synthetic reference, oscillator, metadata and plant sequences through the real decision engine.                                                                                        | Add a bounded shared-engine replay/simulation lane before component promotion. It must exercise production policy code, not a separately reimplemented toy controller, and cannot substitute for firmware integration or physical qualification.                                                                     |

## Architectural invariants

Until an explicitly reviewed successor mapping replaces the Nano pin names:

- D14 is the sole authoritative PPS/reference input;
- D8 is the sole oscillator/count input used for regulation;
- D10 is the external event input and never a PPS witness or control input;
- D9 is the disciplined-oscillator output; and
- D6 is a fail-local, zero-authority diagnostic monitor.

On a successor board, the physical GPIO names may change but these logical
roles and authority relationships must remain explicit. A dedicated candidate
GNSS PPS input is comparison evidence, not a second authority. A dedicated
candidate oscillator counter is characterization evidence, not a second plant
input. Promotion of either candidate requires a later explicit role change,
new fixed-image binding and fresh qualification.

Canonical acquisition, serial product, host view, bench configuration and
control authority are separate dimensions:

```text
physical wiring and declared roles
              |
              v
canonical hardware acquisition  -----> immutable retained evidence
              |
              +----> host serial/view projections
              |
              +----> diagnostics and metrology
                             |
                             v
                 explicit runtime authority
                             |
                             v
                  autonomous bounded control
```

Changing a serial product must not change capture timing, queue servicing,
reference qualification, estimator behavior, actuator authority or the
physical output.

## Firmware/host contract parity

Firmware/host agreement is one end-to-end platform contract, not a collection
of approximately matching structs, format strings, parsers and fixtures. For
every current record, command, acknowledgement, status snapshot and manifest
binding, the contract must declare:

- field name, presence and ordering;
- wire representation, width, signedness and legal range;
- unit, scale, clock/counter domain and rollover behavior;
- enum, flag and reason-code values;
- optional, unknown, unavailable and sentinel semantics;
- record/schema version and compatibility rule; and
- the producer acknowledgement and first decision-bearing host or firmware
  consumer.

Unknown, missing, truncated, extra or out-of-version data must never become a
plausible zero, stale value or default enum. A host-detected discrepancy enters
the repository-defined review-required diagnostic hold: retain capture and the
last confirmed DAC code, grant no new setup/arm authority, and preserve the
exact offending bytes, parsed form, schema identity and pending causal phase
for review.

Prefer one machine-readable authority that generates or mechanically validates
both firmware constants/layouts and host decoding. Where generation would hide
important firmware meaning or add disproportionate machinery, retain explicit
implementations but compare them exhaustively against that authority. The
fixed firmware binary must expose the exact contract/schema digest or version
set that the host validates at attachment.

Verification must cross the actual boundary in both directions:

1. firmware/native producer emits every legal record shape and boundary value;
2. the production host parser retains and interprets it exactly;
3. the host emits every legal command and boundary value;
4. the production firmware parser accepts or rejects it as declared; and
5. exact identity and ordering are checked through the first dependent
   decision, not merely through byte receipt or acknowledgement.

Exercise minimum, maximum, zero, negative where legal, rollover-adjacent,
unknown-enum, missing, duplicate, extra, truncated, reordered and version-
mismatched cases. Derive these cases from the contract so exhaustive parity
does not become another manually duplicated regression matrix.

### Current implementation status — 2026-09-10

`data_contracts/otis_firmware_host_contract_v1.json` is now the single current
authority for record tags, schema versions and ordered layouts; command forms
and argument bounds; the atomic ACTIVE status vocabulary; queue frontiers; and
named cross-record relations. It generates the checked-in firmware header and
is bound into the fixed build manifest, source identity and binary provenance.
Firmware emits the contract ID and digest, and host pre-write admission requires
an exact match.

The production host now rejects unknown record tags, mismatched headers, wrong
schema versions and incomplete or extra ACTIVE status fields before they can
become state. It preserves the offending line and parsed attempt and reports the
existing review-required diagnostic hold without granting host abort or teardown
authority. The shared authority separately declares the typed, zero-authority
boot-diagnostic envelopes and one bounded pre-protocol late-attach suffix; these
remain raw evidence rather than being misclassified as canonical records. Native
parity checks compile the production firmware command/setup parsers and response
transaction state machine and compare them with production host behavior.

The latest retained discrepancy is understood and deterministically covered.
The original 2026-09-09 attempt-3 offline replay classified response requests 2
and 4 from each request's immediate response only. Firmware correctly also used
the cumulative response from the first pre-response baseline. Host replay now
uses the same stateful operands and rule order; replay of the unchanged retained
ACT rows returns exact classifications for all four requests. The original seal
remains historical review-required evidence until the repository's explicit
provenance-linked superseding-analysis workflow is run; it is not rewritten in
place.

This closes the known recurring structural, field-encoding, command-grammar,
timestamp-relation and response-state mismatch paths. The contract-derived
matrix now covers all 418 fields in all 16 current record contracts, including
typed ACTIVE snapshot values, live admission, offline validation, production
raw-emitter boundaries and native derived-record formatter checks. The earlier
2026-09-10 baseline Release, current-process rehearsal and fixed build passed,
but changed contract bytes require a fresh exact Release, build and contingent-
bundle freeze/rehearsal before this revision may enter the bench.

The first physical entry after strict unknown-tag admission on 2026-09-10
correctly held before any command or DAC write because that authority had not
yet declared the existing boot-diagnostic side channel. The raw carrier showed
one late-attach `BOOT` suffix followed by complete `BOOT_WARN` and `BOOTDIAG`
records. The narrow repair types those envelopes, retains them as raw-only
evidence, and places the exact sequence at the start of the genuine process
rehearsal. It does not weaken unknown canonical-record handling.

## Measurement language and claim discipline

Use the following distinctions in contracts, reports and plots:

- **precision/repeatability** — the spread or reproducibility of repeated
  observations under declared conditions;
- **accuracy** — agreement with a named reference or timescale, supported by
  calibration and an uncertainty statement;
- **measurement-aperture bias** — repeatable displacement between the physical
  event and the captured timestamp;
- **measurement-aperture variability** — observation-to-observation movement
  of that displacement; and
- **receiver PPS quantization correction** — receiver-reported context about
  its intended PPS placement, not a replacement raw observation or automatic
  timing authority.

A constant common path delay may cancel in an adjacent frequency interval but
still matters to an absolute phase claim. A varying path delay contaminates
both phase and interval observations. Report these separately rather than
using `accurate`, `precise` or `jitter` without naming the reference, statistic,
aperture and observation conditions.

External receiver comparisons and SatPulse design ideas are inputs to candidate
selection and experiment design, not OTIS evidence. Verify the relevant
receiver documentation and primary measurement reports before freezing a
purchase, electrical interface, correction sign or performance expectation.
PTP/PHC and network-time distribution remain outside this programme unless a
later OTIS decision explicitly needs them as an external witness.

## Programme sequence

| Stage | Outcome                                                                                            | Physical work?                                       | Entry dependency                                          |
| ----: | -------------------------------------------------------------------------------------------------- | ---------------------------------------------------- | --------------------------------------------------------- |
|     0 | Restore and verify the current fixed-image operational path                                        | No                                                   | Current clean source                                      |
|     1 | Select and freeze the successor hardware architecture                                              | Design and measurement only under separate authority | Stage 0 platform contract                                 |
|     2 | Port one fixed image and add isolated measurement inputs                                           | Bench entry required for final qualification         | Selected board, power and pin/resource ledger             |
|     3 | Qualify power, signal interfaces, D10 breakbeam and D9 output                                      | Yes                                                  | Exact Stage 2 image and complete rehearsal                |
|     4 | Deliver serial products and accelerated shared-engine exercise without multiplying firmware states | No-hardware first; optional bench load check         | Stable record contracts from Stages 2-3                   |
|     5 | Run candidate GNSS and oscillator comparisons                                                      | Yes                                                  | Qualified dedicated inputs and frozen candidate contracts |
|     6 | Select the final components and complete the integrated qualification                              | Yes                                                  | Stage 5 decisions and final fixed configuration           |

Stages are ordered by dependency, not by document production. Offline design
for a later stage may proceed early when it does not touch the bench or freeze
an assumption that an earlier stage is meant to decide.

## Stage 0 — restore the current operational path

### Outcome

The one fixed Nano image and current host path can be built, structurally
checked and taken through the genuine process/FIFO/command/acknowledgement/
obstruction/abort/analysis/sealing rehearsal. Current live activation is
deliberately fail-closed until this exists.

### Work

1. Run and record the current Fast, Campaign and Release tiers, including
   elapsed time, discovered checks and fixed-image identity.
2. Inventory every current firmware/host wire boundary and close the contract
   parity requirements above. Replace duplicated authoritative field/width/
   value definitions with generation or mechanical comparison from one
   versioned contract, and bind its identity into the firmware/host attachment
   handshake.
3. Implement the current-only process-level rehearsal producer. Exercise the
   actual capture owner, normal and priority command paths, repeated requests,
   first dependent decisions, transport obstruction, bounded abort delivery,
   same-owner evidence rotation, analyzer and sealing path.
4. Verify the recovered metadata-hold state machine and current host diagnostic
   hold semantics through the first dependent decision after requalification.
5. Audit retained tests against current invariants and the rehearsal. Remove a
   test only when its protected behavior is retired, duplicated at a cheaper
   layer, or better covered by the end-to-end path.
6. Freeze and rehearse the current 72-hour contingent hybrid-control bundle.
   By operator decision on 2026-09-09, use the complete finite programme as the
   next decision-bearing current-platform gate; do not insert a separate short
   setup, one-application, passive, or elapsed-time prefix campaign. Physical
   entry remains a distinct explicitly authorized step after readiness.

### Gate

Pass when the exact current image builds, every current bidirectional contract
shape and boundary value has producer-to-first-consumer parity, and the genuine
operational rehearsal passes with exact identities and no ownerless serial
interval. Stop and repair only the failed current boundary otherwise.

Current status on 2026-09-10: the shared authority, complete record and ACTIVE
value matrix, runtime identity admission, strict mismatch hold, and regressions
for the known escapes are implemented. This revision still requires its fresh
exact Release, fixed-image build and contingent-bundle freeze/rehearsal before
Stage 0 can be closed for the prospective physical entry.

## Stage 1 — select the successor board, power and physical interface

### Outcome

One reviewed schematic-level architecture and wiring plan is selected before
firmware is ported or the existing bench is dismantled.

### Board decision

Use Raspberry Pi Pico 2/RP2350 as the default comparison candidate because the
existing hardware roadmap identifies it as the likely long-term direction and
the requested dedicated inputs need more exposed pins and timing resources.
This is a candidate, not a frozen selection.

Compare only the smallest credible set of boards against:

- sufficient exposed GPIO for primary reference, primary oscillator, D10
  external event, disciplined output, diagnostic loopback, candidate GNSS PPS,
  candidate oscillator count and GNSS/candidate metadata serial links;
- enough independent PIO state machines, DMA channels, IRQ routing and queue
  memory to keep optional inputs fail-local;
- a deterministic clock tree and an auditable Arduino/Pico SDK toolchain;
- reliable USB identity, bootloader entry and unattended flashing;
- suitable power pins, grounding and physical connector arrangement; and
- long-term availability and a comprehensible schematic.

The migration must not create a permanent board matrix. Keep the Nano revision
reproducible through Git history, develop the successor behind an isolated
candidate boundary, and make the selected board the sole fixed production
target after qualification.

### Required logical I/O

| Logical signal          | Required hardware behavior                                                                                             | Authority                            |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------- | ------------------------------------ |
| `PRIMARY_PPS`           | hardware-captured installed GNSS PPS; successor mapping for D14                                                        | sole reference authority             |
| `PRIMARY_OSC_COUNT`     | continuous high-rate count and reference-aligned snapshot; successor mapping for D8                                    | sole regulation measurement          |
| `EXTERNAL_EVENT`        | hardware-captured edge/pulse input for the breakbeam and general events; successor mapping for D10                     | zero control and terminal authority  |
| `DISCIPLINED_OUTPUT`    | buffered or directly qualified output derived from the primary oscillator; successor mapping for D9                    | output only                          |
| `OUTPUT_MONITOR`        | optional independent diagnostic observation; successor mapping for D6                                                  | fail-local diagnostic                |
| `CANDIDATE_GNSS_PPS`    | dedicated hardware capture independent of D10; may also accept the same electrically split PPS during path calibration | comparison/calibration evidence only |
| `CANDIDATE_GNSS_SERIAL` | dedicated RX and, only if needed, bounded TX with exact receiver identity                                              | metadata context only                |
| `CANDIDATE_OSC_COUNT`   | independent high-rate count aligned to the same qualified primary PPS boundaries                                       | comparison evidence only             |

Freeze a complete PIO/DMA/IRQ/timer/clock/queue ownership ledger before
implementation. Candidate-input absence, noise, overflow or corruption must
never backpressure or invalidate `PRIMARY_PPS`/`PRIMARY_OSC_COUNT`.

### Power and grounding decision

Freeze requirements before choosing parts:

- measured cold-start and steady-state current for oscillator, MCU, GNSS,
  DAC, buffers and sensors;
- oscillator supply range and allowed ripple/transient envelope at its pins;
- whether oscillator/analogue, digital MCU and GNSS loads use separate rails
  or a shared rail with explicit filtering and star returns;
- USB shield/ground and external-instrument ground paths;
- regulator startup ordering, reverse-current/back-power behavior and reset
  behavior;
- test points for every rail and the DAC steering node; and
- the measurement floor and equipment used for ripple and transient claims.

The current TPS62827 arrangement is a comparison baseline, not a presumed
cause of earlier D14 disturbances. Run one discriminating power/signal
measurement before making a causal claim.

### Deliverables and gate

Retain the selected board identity, schematic, pin map, resource ledger, power
tree, grounding plan, connector/harness plan, preliminary BOM and a migration
test plan. The existing rig is not rewired until these are reviewed and the
operator approves the exact physical change.

## Stage 2 — port one fixed image and add isolated capture capability

### Outcome

The successor board runs one fixed adaptive-regulation image with the same
authority semantics and with hardware-owned D10, candidate-GNSS and
candidate-oscillator acquisition.

### Work

1. Port the fixed build manifest, board identity, firmware/host contract
   identity and resource ledger. Do not recreate selectable campaign profiles
   or fork the wire contract for the new board.
2. Re-establish the primary PPS/oscillator snapshot mechanism and repeat every
   proof invalidated by the MCU, pin, clock, PIO, DMA, synchronizer or toolchain
   change.
3. Implement D10 edge capture in timing hardware. Preserve raw rising/falling
   edges, capture domain, sequence, loss markers and overflow evidence.
4. Implement the candidate GNSS PPS and candidate oscillator count paths with
   separate queues and explicitly droppable/fail-local policies where needed.
5. Define a minimal GNSS timing-observation contract for the installed receiver
   and the first actual candidate. Preserve raw electrical PPS, receiver
   identity, receiver timescale, solution/timing mode, survey/fixed-position
   state, configured cable delay and receiver-reported PPS correction as
   distinct fields with explicit availability and units. Do not build a broad
   vendor framework before two concrete drivers demonstrate shared semantics.
6. Add a runtime authority contract with fail-closed `OBSERVE_ONLY`, explicit
   autonomous regulation, and `HOLD_STATIC` behavior. These are authority
   states of one image, not build variants.
7. Requalify the installed receiver's bounded 9600/115200 boot transaction and
   receive-service margin on the new UART/service topology. Do not repeat the
   five-rate study unless the new evidence contradicts its selected result.
8. Run the affected Release gate and the complete current operational-path
   rehearsal against the exact successor image.

### Gate

Pass when the primary path retains its required timing evidence and every
optional input can be absent, noisy, saturated and locally overflowing without
changing primary validity, authority, actuation or terminal state. Firmware
fixtures do not close the remaining physical electrical boundaries.

## Stage 3 — qualify the installed hardware interfaces

### Outcome

Power, primary inputs, the breakbeam event input and disciplined output have
bounded physical claims supported by retained measurements.

### 3A. Power and signal integrity

Measure the final assembled system during cold start, normal operation,
maximum declared serial load and bounded DAC movement:

- rail DC levels, ripple, transient extrema and startup sequence at the load;
- current draw and thermal settling;
- PPS and oscillator logic levels, rise/fall time, duty/pulse width, ringing
  and ground-reference behavior;
- correlation of any D14/D8 anomaly with rail, USB, load or output activity;
  and
- primary capture continuity, queue margin and control state.

If an anomaly appears, state one causal hypothesis and run one discriminating
check before changing the design.

### 3B. D10 breakbeam interface

Select the exact sensor or module before freezing resistor values. Record
whether the receiver output is push-pull, open-collector/open-drain or bare
phototransistor and whether the emitter module already contains current
limiting.

The final schematic and BOM must explicitly include, as applicable:

- emitter LED current-limiting resistance;
- a 3.3 V receiver pull-up/bias resistance;
- a series resistor into the MCU input;
- input clamping, level shifting or a Schmitt buffer when required by the
  sensor voltage/noise envelope;
- decoupling and ground return; and
- the declared asserted level, edge polarity and behavior for beam present,
  beam broken, disconnected and power-off states.

Qualify timestamp continuity, minimum/maximum pulse width, bounce/noise,
repetition rate, unplug/reconnect behavior and deliberate event-queue overflow.
All failures must remain D10-local. Retain a simple end-to-end demonstration in
which a physical beam interruption produces a raw `EVT` record and a derived
host observation without changing regulation.

### 3C. Disciplined output

Define the connector, buffer/driver, series or source termination, cable and
load envelope before measurement. Use an oscilloscope and independently
referenced counter appropriate to the claim. Measure D8 and the delivered
output together where practical:

- frequency/count agreement and continuity;
- logic levels, duty cycle, rise/fall time, overshoot and ringing;
- propagation delay and repeatability;
- startup, reset, source-loss and recovery behavior;
- load and cable sensitivity;
- measurement-floor-bounded jitter; and
- non-interference with primary capture, serial transport and regulation.

D6 may corroborate digital continuity but cannot qualify the delivered
waveform or load. If direct MCU drive is inadequate, select and requalify an
external output buffer rather than weakening the claim.

### 3D. Measurement-aperture and PPS-path characterization

Use the dedicated candidate/calibration capture input, never D10, for a bounded
measurement of the measurement system itself.

First feed one electrically split PPS edge through documented, preferably
matched distribution into the primary and calibration capture paths. Measure:

- fixed differential path bias and startup repeatability;
- observation-to-observation differential variation;
- dependence on edge slew, pulse width and input level inside the declared
  electrical envelope;
- dependence on power state, USB/serial load and temperature; and
- any path-specific missing, duplicate or reordered capture behavior.

Then compare the internal differential result with an oscilloscope, TIC or
other independent hardware witness whose channels, trigger, input settings,
cable delays and measurement floor are retained. Decompose the full path as
far as the evidence permits: source/output circuitry, distribution/cable,
input conditioning, pad/synchronizer and capture state machine. Do not infer
absolute calibration for an unobserved segment.

This experiment establishes bounds only for the exact board, pin, input
conditioning, clock, firmware and environmental envelope tested. Its constant
bias and variable component must be reported separately.

### Gate

Produce separate, provenance-linked results for power/input integrity,
breakbeam capture and disciplined output. A failure in an optional path does
not invalidate a healthy primary acquisition unless shared-resource evidence
demonstrates actual compromise.

## Stage 4 — deliver useful serial products and accelerated policy exercise

### Outcome

Clients can consume the data they need without changing what OTIS captures or
creating another firmware image.

### Initial products

| Product   | Content                                                                                                                                                   | Claim                                                          |
| --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| `FULL`    | all canonical observations, state transitions, diagnostics, estimates, control requests/applications/acknowledgements, identities and continuity counters | replayable canonical evidence                                  |
| `EVENTS`  | D10 event records plus coherent referenced quality/state snapshots                                                                                        | event evidence with declared scope                             |
| `BENCH`   | selected primary and candidate raw observations, configuration, environment and diagnostics for a frozen component comparison                             | replayable only when its declared completeness contract passes |
| `SUMMARY` | current state, recent derived statistics, warnings and transitions                                                                                        | explicitly non-replayable convenience product                  |

Implement these first as host-side projections from retained `FULL` evidence.
Each reduced event or benchmark row must bind to a coherent quality generation
covering primary reference/count state, regulation state, applied DAC
code/epoch, continuity counters, firmware/configuration/session identity and
the source frontier it summarizes.

Only add firmware-side `STREAM SET ...` selection if retained measurements
show that the full carrier cannot meet a required client or bandwidth envelope.
If added, the transition must acknowledge old/new product, stream epoch and
effective sequence; intentional suppression must be distinct from accidental
loss; faults, authority transitions, control actions and stream transitions
remain non-suppressible.

Do not add `AUTONOMOUS` as a serial profile. Autonomous regulation is the fixed
control architecture and continues independently of which host product is
being viewed.

### Gate

Given one retained `FULL` fixture, every projection is deterministic and its
scope is explicit. Switching or generating a view has no effect on firmware
decisions, raw evidence, capture throughput or physical output.

### Shared-engine replay and simulation

Provide one accelerated observation-source seam that accepts either retained
canonical observations or prospectively declared synthetic observations and
feeds the same portable estimator/policy/transaction code used by firmware.
Python may orchestrate scenarios and act as an independent exact oracle, but it
must not become a second authoritative controller implementation.

Begin with the smallest decision-bearing scenario set:

- ordinary acquisition, convergence, tracking and bounded correction;
- PPS absence, one bad interval, a bounded phase step and recovery;
- GNSS metadata loss, late correction metadata and causal requalification;
- oscillator frequency step, slow drift/ageing and temperature-correlated
  curvature;
- actuator gain variation, saturation and delayed or contradictory
  acknowledgement; and
- serial delivery delay or obstruction after the hardware observation has
  already been captured.

Map these stimuli onto OTIS's existing explicit policy states and reasons; do
not rename the current state machine merely to imitate another system. A
scenario passes only when firmware-native and host replay decisions, exact
request/application identity and the first dependent result agree. Synthetic
coherence proves decision logic, not physical capture, electrical response or
the fidelity of the noise/plant model.

## Stage 5 — benchmark candidate components

Run each comparison as a finite experiment with one concrete selection
decision. Do not turn the benchmarking interfaces into new timing authorities.

### Candidate GNSS receiver

Keep the installed primary receiver on the authoritative PPS input. Capture the
candidate PPS on its dedicated zero-authority input and its serial metadata on
the separately identified candidate link.

Select candidates by timing architecture and observable evidence rather than a
simple consumer/timing-grade/price hierarchy. Review at least:

- availability of receiver-reported PPS quantization/sawtooth correction;
- navigation, survey-in and fixed-position timing support;
- cable-delay configuration and documented correction sign/convention;
- time-mark/external-event capability;
- raw measurement and solution-quality reporting;
- protocol openness, configuration persistence and recovery behavior;
- electrical PPS/serial interfaces and supply requirements; and
- availability, cost and long-term support.

The initial documentation-review shortlist may include the installed
PA1616S/MT3339 baseline, u-blox M8T and M8F architectures, u-blox F9P/F9T, and
a Septentrio mosaic timing-family receiver. This is an architecture-diverse
comparison list, not a performance ranking or purchase decision. Reconfirm
exact product availability, documentation and independently reported results
before selecting hardware.

Freeze antenna arrangement, splitter/amplifier behavior where used, cable
identity/delay, supply, ground, receiver configuration, output polarity,
warm-up and environmental context. Compare offset, jitter, wander, interval
anomalies, outages, reacquisition and metadata/PPS causal association. State
whether the result is a same-antenna common-view comparison or a less
controlled two-antenna observation. Do not infer UTC accuracy or calibrated
absolute phase without the missing delay and reference calibration.

Where the receiver supports them, treat navigation/mobile operation,
survey-in, fixed-position timing operation and later loss/reacquisition as
separate phases with explicit transitions. Retain the raw electrical PPS and
the receiver-reported quantization/sawtooth correction separately; derive a
corrected comparison series only after the correction's sign, units, epoch and
causal association are verified. The corrected series is a derived metrology
product and has no automatic control authority.

For a receiver with a documented time-mark/external-event input, a reciprocal
test may feed a bounded OTIS-generated event into the receiver and compare its
reported GNSS event time with OTIS's observation of receiver PPS. Treat this as
an optional independent witness for path delay and phase, not a prerequisite
and not proof of UTC accuracy by itself.

### Candidate oscillator

Keep the installed primary oscillator on the regulation input while the
candidate is counted on its dedicated zero-authority high-rate path. Record
nominal frequency/division, supply, warm-up, temperature, control voltage or
DAC setting, edge conditioning and exact reference support.

Compare frequency error, drift, warm-up, repeatability, environmental response,
stability metrics at prospectively selected averaging times and, for a
controllable candidate, plant sensitivity and monotonicity. A divided/PPS
output may supplement this evidence but cannot substitute for raw high-rate
count characterization.

### Exact window decision

For any candidate observation window `T`, retain exact counted edges, exact
reference-boundary/tick support, nominal-frequency identity and source
frontiers. Choose `T` from observed noise/Allan behavior, plant response,
required control speed, actuator resolution and authority limits—not from a
convenient decimal rendering.

Preserve the current 600-second, `1/21600 Hz` implementation unchanged while it
fits the selected plant. For the first selected oscillator/window that does not
fit, introduce a small typed rational layer using checked wide arithmetic and
cross-product comparisons. Decimal Hz/ppm/ppb values remain display products.
Any lossy conversion or actuator rounding boundary must be named, versioned
and replayed independently.

### Gate

Select, reject or explicitly retain uncertainty for each candidate. Promotion
requires a new fixed plant/reference binding and the shortest affected
electrical, metrology, control and sustained-operation qualification. A clean
candidate comparison alone does not authorize substitution into the control
path.

## Stage 6 — final fixed configuration and integrated qualification

### Outcome

One final board, power arrangement, primary GNSS, primary oscillator, output
interface, D10 breakbeam interface, firmware image and host operational path
are frozen and qualified together.

### Work and terminal

1. Update the architecture, hardware ownership, telemetry, methodology,
   limitations and terminology documents for the selected physical mapping.
2. Freeze one immutable bundle containing source, exact binary, toolchain,
   hardware/BOM/harness revisions, policies/models, authority envelope,
   serial products, rehearsal, analyzer, stop conditions and evidence paths.
3. Pass the affected Release gate and the complete operational-path rehearsal.
4. Under explicit authority, run a finite integrated qualification long enough
   to exercise autonomous regulation, GNSS metadata hold/requalification,
   disciplined output under declared load, D10 breakbeam events, candidate
   inputs absent or deliberately local-degraded, evidence rotation and clean
   finalization.
5. Seal and register the evidence and publish one concise result separating
   observed facts, raw and receiver-corrected PPS products, precision,
   reference-bound accuracy, aperture bias/variability, derived results,
   modeled quantities, equipment floors and unavailable uncertainty.

The programme completes at either:

- `final_fixed_instrument_qualified` with a bounded claim and documented
  limitations; or
- `final_selection_or_qualification_blocked` with the exact failed gate and
  the next decision identified.

Do not redefine acceptance after seeing the result and do not repeat healthy
unaffected gates merely to obtain a clean narrative.

## Verification growth policy

Every new check must name:

- the current invariant or escaped defect it protects;
- the earliest practical tier that can catch it;
- whether a cheaper unit/contract check or the operational rehearsal already
  covers the same failure; and
- its retirement condition.

Prefer one producer-to-first-consumer regression for a handoff over several
source-shape assertions. Keep exact arithmetic boundary/parity tests, resource
isolation guards, fixed-image identity checks and the complete operational
rehearsal. Do not retain tests solely to make historical programmes executable
on current HEAD.

After Stage 0, record tier duration and failure-localization value. Continue a
test-reduction subtask only if the suite still materially delays routine work
or contains identified duplication; otherwise regard the fixed-surface reset
as sufficient and return to the instrument programme.

## Operator decisions

Only the first decision is needed before Stage 1 can close; none blocks Stage
0 offline work.

1. Confirm the intended successor-board candidate. The repository currently
   points toward Raspberry Pi Pico 2/RP2350, but the exact product is not
   selected.
2. Identify the exact breakbeam sensor/module so its electrical output and
   resistor values can be frozen from evidence rather than guessed.
3. Clarify whether “breakbeam sensor on D10 (don't forget the resistors) &
   output” means only the sensor's electrical output into D10, or also a
   separate OTIS trigger/pass-through output in addition to the disciplined
   D9 frequency output.
4. State any required connector, cable/load or electrical standard for the
   disciplined output. Without one, the first claim will be a bounded 3.3 V
   digital bench output, not a 50-ohm laboratory reference interface.
5. Identify the first GNSS and oscillator candidates when Stage 5 is near;
   their exact interfaces determine the final candidate-UART, counter and
   supply requirements.

## Immediate next action

Execute Stage 0 only: establish exhaustive current firmware/host contract
parity, establish the genuine current operational rehearsal, run the fixed-
image Release gate once, and record whether any further test reduction is
decision-bearing. In parallel, the operator decisions above can be resolved
without touching the bench.
