# Codex Prompt: Prepare the OTIS GNSS Baud-Envelope Characterization

You are working in the OTIS repository on the computer attached to the bench
rig. Prepare the complete
`OTIS_GNSS_BAUD_ENVELOPE_CHARACTERIZATION_V1` programme specified in
`docs/60_EXPERIMENTS/OTIS_GNSS_BAUD_ENVELOPE_CHARACTERIZATION_V1/README.md`.

The decision-bearing result is one continuous 12-hour, non-actuating multi-baud
characterization and soak programme that can identify the highest robust
operational GNSS baud and localize any failure to the receiver/electrical,
UART hardware, raw acquisition, software-ring, parser, USB/status, or shared-
platform layer.

Do not turn this into five unrelated baud attempts. Do not stop after writing a
plan or a parser unit test. Complete all authorized offline implementation,
verification, exact-profile build, campaign tooling, analysis, and a minimal
accelerated no-I/O operational check. Then freeze one non-effective candidate
bundle and stop for explicit physical authority.

## Authority boundary

This prompt authorizes:

- read-only inspection of repository source and retained local evidence;
- implementation of the bounded UART RX acquisition ring, hardware-error
  telemetry, segment telemetry, progressive baud transaction, and no-DAC
  firmware profile;
- implementation of the host runner, supervisor, monitor, analyzer, sealing,
  and registration integration needed by this programme;
- deterministic unit, native, parser, transaction, source-guard, binary,
  replay, and accelerated no-I/O operational checks of the new orchestration;
- firmware compilation without flashing;
- reviewed documentation, contracts, schemas, small fixtures, and non-
  effective candidate bundle creation; and
- proportionate campaign and release verification for the changed UART,
  protocol, build, and service-plane surfaces.

This prompt does **not** authorize:

- opening or owning a physical serial device;
- flashing or resetting the MCU;
- transmitting any byte to the physical GNSS receiver;
- changing the physical receiver baud;
- starting a physical acquisition or soak;
- wiring, power, or bench changes;
- a DAC write, setup transaction, sweep, control arm, phase influence, abort
  actuation, or restore;
- setting physical authority true in tracked or generated status; or
- treating a successful build, fixture, preflight, or operational check as
  physical evidence.

Do not access the bench even if an existing runner or guard would permit it.
At the end, present the exact candidate bundle identities, operational-check
result, remaining physical risks, estimated wall duration, and the precise
operator decision needed to begin the one live programme.

If the operator later explicitly authorizes that exact bundle, treat the live
run as a new authority decision. Keep the controlling Codex turn active with
bounded state/evidence polling until terminal, unless an independent recurring
monitor has been explicitly requested and verified.

## Read first

Read completely and apply at least:

- repository-root `AGENTS.md` and all applicable nested instructions;
- `docs/00_FOUNDATIONS/OTIS_REFERENCE_TERMINOLOGY.md`;
- `docs/00_FOUNDATIONS/OTIS_ARCHITECTURE_OVERVIEW.md`;
- `docs/00_FOUNDATIONS/OTIS_NON_GOALS.md`;
- `docs/10_REFERENCE_ARCHITECTURE/ADAPTIVE_FREQUENCY_STEERING.md`;
- `docs/50_SOFTWARE/CX317_RX_ONLY_GNSS_RECEIVER_CONTRACT.md`;
- `docs/50_SOFTWARE/KNOWN_LIMITATIONS.md`;
- `docs/60_EXPERIMENTS/OTIS_TARGETED_EQUILIBRIUM_CHARACTERIZATION_V1/README.md`;
- Attempt 3, Attempt 4, and Attempt 6 retained GNSS health evidence;
- `firmware/arduino/otis_nano_rp2040_connect/otis_gnss_receiver.h`;
- `firmware/arduino/otis_nano_rp2040_connect/otis_gnss_receiver.cpp`;
- `firmware/arduino/otis_nano_rp2040_connect/otis_status_emit.cpp`;
- the Core 0/Core 1 boot and loop service paths in
  `otis_nano_rp2040_connect.ino`;
- UART, IRQ, memory, transport, resource-registry, build-matrix, and profile
  configuration used by the current firmware;
- `tests/test_gnss_receiver.py` and `tests/cpp/gnss_receiver_harness.cpp`;
- current capture, sole-owner, obstruction, abort, rotation, analysis,
  sealing, and registration tools; and
- the specification beside this prompt.

Read the local PA1616S and PMTK documents needed to validate the fixed baud and
command table. Preserve their exact identities. Do not use a filename or an
old summary as a substitute for the applicable source content.

## Reproduce the starting facts

Before changing code, produce a short evidence-backed audit that confirms or
corrects these starting facts:

1. The current parser waits for newline, synchronizes on `$`, treats a new `$`
   before newline as an incomplete prior line, validates checksum, and uses
   fixed 96/256-byte collectors.
2. The current live path polls UART0 with a 32-byte RX budget.
3. Core 0 services GNSS before its ordinary USB/service work and after each
   complete synchronous `STS` record, but maximum service gap and hardware UART
   errors are unrecorded.
4. The current link state machine can discover all documented rates but can
   select only 9600 or 115200 as the compile-time target.
5. Attempt 3 and Attempt 4 show sparse 115200 corruption while Attempt 6 is
   clean at 9600, without hardware evidence sufficient to classify the cause.
6. Attempt 6's configured receiver output is approximately one RMC, one GGA,
   and two GSA frames per second despite wording elsewhere that may imply only
   one GSA.
7. The receiver contract currently contains stale 115200 eligibility wording
   alongside the current frozen 9600 operational target.

Record discrepancies explicitly. Correct documentation when implementation or
contract meaning changes, but never rewrite historical evidence or terminals.

## Phase 1 — freeze the programme contract before implementation

Create a machine-readable V1 contract that binds:

- programme identity and authority false;
- exact five-baud allowlist and constant PMTK251 packets;
- fixed 11-segment order and confirmed-online durations;
- phase durations and workload definitions;
- ordinary, peak-load, transition, discovery, and recovery counter
  attribution;
- UART/ring/parser/metadata/capture telemetry schema;
- independent per-baud steady-online and transition classification rules;
- programme terminal and recovery rules;
- final confirmed-9600 state requirement;
- all source, profile, tool, firmware, host, analyzer, and environment
  identities needed for an exact bundle; and
- evidence output paths under
  `runs/otis_gnss_baud_envelope_characterization_v1/`.

Freeze the factor-of-two observed ring-headroom rule before evaluating any
candidate or live data. Do not change the segment order, workload durations,
repetitions, classification thresholds, or terminal rules after observing a
physical result.

## Phase 2 — harden and instrument raw UART acquisition

Implement the smallest bounded interrupt-backed raw RX ring described by the
specification.

Requirements:

- UART0 remains owned only by the GNSS service plane.
- The RX ISR drains the FIFO, decodes data-register error bits, and writes a
  fixed non-overwriting SPSC observation ring.
- Each retained entry preserves the byte and error flags. If the ring fills,
  record the dropped-byte count and mark the next retained entry as having a
  loss before it; the Core 0 consumer must close both collectors at that marker
  before delivering the post-gap byte.
- The ISR performs no parsing, formatting, logging, allocation, link-state
  transition, PMTK transmission, or timing/control work.
- Keep the ISR hot path to direct FIFO-status/data-register reads, minimal
  error/drop counters, and one lock-free SPSC enqueue. Permit at most one direct
  free-running-counter read at entry and one at exit; prohibit per-byte clock
  reads, locks, callbacks, snapshot copies, ring-high-water calculation, and
  unrelated interrupt clearing.
- The Core 0 consumer retains the existing link and metadata parser semantics.
- Every byte reaches link and metadata parsing in exact FIFO order.
- Wrong-baud discovery bytes remain outside canonical metadata parsing.
- Planned transitions explicitly close/reset partial collector state and open
  a new baud epoch.
- Counter wrap, ring wrap, overflow, and snapshot copying are deterministic.
- UART and ring work cannot backpressure or alter D14/D8 capture or Core 1.
- Memory use remains within the exact profile budget.

Instrument the complete telemetry set in the specification, using exact
domains and monotonic counters. Preserve a bounded sanitized fault capsule for
the first fault and a prospectively frozen number of subsequent distinct fault
classes or segments. Do not log coordinates or full NMEA payloads.

Do not add UART DMA unless the interrupt-backed design fails a deterministic
requirement and one discriminating check proves DMA is necessary. If that
happens, document the evidence and stop for an architecture decision rather
than silently broadening the implementation.

## Phase 3 — implement the characterization-only transition path

Extend the existing discovery/configuration state machine; do not build a
second receiver stack.

Provide one bounded host request surface that accepts only:

- exact campaign/contract identity;
- progressive request sequence;
- expected source baud and baud epoch; and
- one target from `9600, 19200, 38400, 57600, 115200`.

The host never supplies PMTK bytes. Firmware selects one compile-time constant
packet from the source-guarded table. Bind request acceptance, physical
transmission completion, UART rate change, fresh PMTK705 target identity,
output confirmation, fresh configured NMEA evidence, baud epoch, and first
dependent host snapshot.

Implement idempotent duplicate handling and fail closed on contradictory
sequence/source/target identity. Implement exactly one bounded five-rate
recovery scan after target failure. A recovered target failure is a segment
result and permits later scheduled segments; a five-rate unrecoverable link is
a programme terminal.

The recovery scan must cover exactly the same five-rate characterization set.
Do not scan or target 4800; the installed receiver defaults to the already-
proven 9600 rate, which is the recovery anchor for this programme.
Do not scan or target 14400; it is outside this programme's frozen operating
candidate set.

The transition surface must compile only in the new no-DAC characterization
profile. Every existing production, measurement, preview, and active-control
profile must reject or omit it.

## Phase 4 — implement segment-local workload and continuation

Implement the declared ordinary and peak-status workload phases with exact
counters and acknowledgements.

- A peak status challenge cannot overlap another challenge, a transition, a
  discovery scan, or a prior metadata requalification.
- Every workload phase records its identity, exact start/end frontier,
  response bytes/duration, raw acquisition and consumer gaps, ring high water,
  parser result, and metadata state.
- Rate-local UART, ring, parser, and metadata faults never stop the programme.
- Segment progress continues after fresh ordinary RMC/GGA/GSA requalification.

Do not inject artificial UART-acquisition or parser-consumer gaps in V1. The
overnight run is a quick ordinary/peak-load screen because prior 115200 faults
appeared quickly. Retain the instrumentation needed to justify a later focused
margin test only if the observed evidence is clean but inconclusive.

Use the existing D14/D8 capture and health path to prove non-interference. D10
is not part of this programme and must not enter any baud classification or
terminal.

## Phase 5 — host runner, monitor, analyzer, and evidence

Reuse the existing sole-owner capture and finalization platform. Do not create
a parallel serial bridge or evidence format.

The host runner must:

1. bind the exact bundle and expected device identity before any transition;
2. establish one continuous capture owner and D14/D8 capture session;
3. execute S01 through S11 progressively, counting only confirmed-online time;
4. advance only after exact transition completion and the first fresh dependent
   segment snapshot;
5. preserve ordinary, peak-load, transition, discovery, and recovery phases
   separately;
6. treat local GNSS faults as observations and continue;
7. monitor authoritative supervisor state and evidence freshness more often
   than the shortest material transition or fault interval;
8. preserve exact final state and never issue a blind restore;
9. stop only on a frozen programme condition or operator request; and
10. close, analyze, seal, snapshot, and register through the existing path.

Use state-transition and milestone monitoring, not process-existence polling.
The monitor must report segment/phase changes, transition results, first new
fault class, stale evidence, unrecoverable link, D14/D8 non-interference fault,
and programme terminal without flooding the operator with every repeated local
fault.

The analyzer must independently reconstruct segment counter deltas from raw
records, reject mixed phases or impossible ordering, calculate per-baud
denominators and finite `3/N` zero-event bounds, apply the independent frozen
steady-online and transition classification rules, and recommend the highest
baud with both observed margin and reliable transitions or retain 9600.

## Phase 6 — deterministic verification

Add focused regressions covering at least:

- all fixed PMTK251 checksums and binary presence/absence guards;
- UART DR data/error extraction and error-counter attribution;
- ISR source/call-graph guards for the forbidden work above, plus bounded batch
  and maximum-residence instrumentation in the exact firmware profile;
- raw-ring empty/full/wrap/high-water/overflow behavior;
- exact byte ordering through ISR ring, link collector, and metadata collector;
- CR, LF, CRLF, `$` resynchronization, checksum, field-shape, oversize, and
  sanitized fault-capsule behavior;
- actual configured RMC/GGA/two-GSA cadence and line-length accounting;
- consumer drain byte/time budgets and maximum-gap telemetry;
- every legal baud transition in both directions;
- same-target, duplicate, stale, skipped, contradictory, and out-of-allowlist
  requests;
- target timeout recovered at a different frozen candidate rate;
- complete five-rate recovery failure;
- phase-local counter attribution and exclusion of discovery and transition
  effects from ordinary and peak-load metrics;
- rate-local continuation through repeated faults;
- D14/D8 non-interference terminal behavior;
- final confirmed-9600 state; and
- analyzer terminals, per-baud classes, and highest-feasible selection.

Run focused tests during development. Because UART acquisition, protocol,
profile/build guards, service-plane behavior, and evidence semantics change,
complete the applicable current release verification before bench entry.
Reuse successful results only when all decision-relevant inputs are identical.

## Phase 7 — exact profile, preflight, and minimal operational check

Create one descriptive no-DAC firmware/profile identity. Prove from source,
configuration, build output, and emitted binary that:

- DAC and control write authority are absent;
- all five and only five operational baud packets are present;
- no generic GNSS UART write surface exists;
- the characterization transition surface is enabled;
- every other firmware profile keeps them disabled;
- D14 remains PPS authority and D8 remains oscillator/count input;
- Core 1 timing behavior and queue limits are unchanged or explicitly rebound;
  and
- all required telemetry fields compile and propagate through the first host
  decision.

Preflight is structural only. Follow it with one short accelerated no-I/O
operational check of the newly added runner, supervisor, transition,
monitoring, analysis, sealing, and registration topology.

The check must complete all eleven scheduled segments, progressive and
repeated transition ordering, rate-local fault continuation,
recovery-at-other-baud, five-rate unrecoverable terminal, peak status-load
phase, stale evidence detection, atomic capture rotation, analysis, seal,
snapshot, and temporary registration.

Do not construct a programmable serial-source HIL programme or claim to
requalify the already demonstrated GNSS-to-RP2040 communication, PMTK exchange,
or NMEA parser. State precisely that the check exercises the new scheduling,
transaction, evidence-attribution, and finalization logic only. Real UART IRQ
timing, PA1616S electrical behavior, physical multi-baud transitions, and USB
workload coupling remain live-run boundaries.

## Phase 8 — freeze and hand off

Freeze one immutable non-effective candidate bundle containing:

- source revision and dirty-state identity;
- exact build profile, invocation, ELF, and UF2;
- command-table, firmware, host, analyzer, sealer, monitor, and registration
  identities;
- campaign contract and full schedule;
- command/acknowledgement envelope and transition timeouts;
- per-segment and programme terminals;
- expected receiver and host query transcript;
- raw and derived evidence destinations;
- accelerated operational-check procedure and immutable result; and
- the planned final confirmed-9600 state.

Set physical authority false. Do not create a live run directory or contact the
device.

Provide the operator a concise readiness report containing:

- what changed and why;
- focused and release verification results;
- exact profile and artifact hashes;
- exact operational-check result and real boundaries exercised;
- remaining physical risks;
- expected duration of 12 confirmed-online hours plus transitions;
- disk and monitoring requirements;
- final-state behavior; and
- one explicit yes/no request to authorize that exact bundle.

## Later live-run conduct after separate authority

These instructions describe required conduct but grant no present authority.

If the operator later authorizes the exact bundle:

- flash once and establish the sole serial owner before capture producers can
  overflow;
- verify exact identity and the complete no-DAC pre-transition gate;
- run the same operationally significant artifact and semantics checked;
- keep the Codex turn active with bounded polling for the full unattended run;
- answer intervening operator questions in commentary and continue monitoring;
- never stop because one baud accumulates faults;
- stop only for a frozen programme terminal or operator request;
- preserve abort submission and delivery separately;
- execute S11 as the planned final return to 9600 only when the current state is
  known; and
- finalize acquisition, analysis, seal, snapshot, registration, and a reviewed
  per-baud decision report before declaring completion.

Do not promote the recommended baud into ordinary firmware merely because this
programme selects it. Update the receiver contract and production profiles only
under a separate reviewed implementation/promotion change that binds the
characterization result and retains 9600 recovery support.
