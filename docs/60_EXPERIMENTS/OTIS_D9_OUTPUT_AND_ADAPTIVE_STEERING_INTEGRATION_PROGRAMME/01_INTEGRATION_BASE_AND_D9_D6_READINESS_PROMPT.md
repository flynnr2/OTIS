# Prompt 01: Integration Base and D9/D6 Readiness

Execute this prompt only after applying the master prompt. Complete all
authorized offline implementation and verification, freeze one exact
non-effective physical bundle, and stop. Do not touch the bench.

## Outcome

Prepare the smallest robust firmware and host delta that:

- forwards the conditioned CX317 VCOCXO signal already observed on
  D8/GPIO20/GPIN0 to D9/GPIO21/GPOUT0 at integer divide by one;
- optionally observes that forwarded D9 signal on the programme-selected
  D6/GPIO18 diagnostic monitor path without granting D6 any authority;
- preserves D14/D8 capture, estimation, frequency-only FLL behavior, Core
  ownership, system clocks and service isolation;
- records exact configuration/readback and output-validity evidence; and
- can be physically qualified through the existing capture, supervisor,
  analyzer, sealing and registration platform.

The selected initial output has exactly one source, pin and divisor. Do not add
runtime source selection, runtime output-pin selection, arbitrary register
writes, fractional division or a serial divider command. A later divided-output
feature is outside this decision.

## Authority

Authorized:

- read-only inspection of completed local evidence and source history;
- creation of a clean worktree/branch after validating the required committed
  base;
- firmware, host, schema, profile, analyzer, test and documentation changes;
- firmware compilation and binary inspection;
- deterministic fixtures and no-hardware operational rehearsal; and
- creation of a non-effective physical candidate bundle.

Not authorized:

- opening a serial device or interacting with a live process;
- flashing or resetting the board;
- configuring the receiver or sending PMTK commands;
- wiring D9 to D6 or attaching measurement equipment;
- enabling D9 on physical hardware;
- a DAC write, setup transaction, FLL arm, hybrid arm or physical acquisition;
- creating a live run directory; or
- setting physical authority true.

## Phase 1 — establish the exact integration base

Before modifying code:

1. Verify the GNSS baud-envelope run is stopped, finalized, sealed and
   registered. Resolve the exact sealed package from the local evidence index;
   do not search unrelated `runs/` trees for a more convenient result.
2. Record its programme terminal, recommended operational baud, final confirmed
   receiver baud, firmware/build/profile identity, UART implementation files
   and source revision.
3. Verify the committed V2 adaptive study identities from the master prompt and
   its terminal `provisional_cx322_unchanged_pending_d9_gate`.
4. Establish a clean integration base containing both reviewed bodies of work.
   Produce a semantic change ledger for UART acquisition/service, D14/D8
   capture, resource ownership, telemetry, host orchestration and controller
   paths. A clean Git merge is not itself semantic compatibility.
5. Confirm the exact supported Arduino/Pico toolchain and installed clock API
   implementation. Inspect the actual source used by the build for GPIN/GPOUT
   configuration, divider/readback and GPIO-function behavior.
6. Record the existing PIO instruction/state-machine, DMA, SRAM, queue and GPIO
   budgets for the exact future frequency-only output profile.

If the sealed GNSS package or reviewed source identity is unavailable,
contradictory or not yet integrated, stop at
`integration_base_not_established`.

## Phase 2 — freeze the output and readiness contracts

Before implementation results, create versioned machine-readable contracts for:

- signal identity: conditioned CX317 VCOCXO nominal 10 MHz observed at D8;
- source: GPIO20 `CLOCK GPIN0` / `clksrc_gpin0`;
- destination: GPIO21 `CLOCK GPOUT0` / D9;
- divider: integer one, fractional zero, no inversion unless the physical
  contract prospectively selects and later measures it;
- D9 drive/slew configuration and conservative high-impedance instrument load,
  cable and connector envelope;
- D6/GPIO18 diagnostic monitor wiring and series-resistor requirement;
- D9 boot/reset/source-loss/reference-loss/control-fault behavior;
- an exact safe non-actuating procedure for the later D8-source-loss/return and
  D14-reference-loss/return segments, including wiring ownership, control
  disarm, last-confirmed-code preservation and causal requalification;
- output configuration, readback, activation and validity boundaries;
- D6 raw snapshot/count semantics, expected D8:D6 ratio and tolerance;
- every deliberately unmade voltage, 50-ohm, absolute-accuracy, UTC, jitter,
  phase-noise or phase-alignment claim;
- exact waveform, count, non-interference and sustained-soak metrics;
- authority false, command absence and physical stop conditions; and
- all source, build, tool, firmware, host, instrument-placeholder and evidence
  identities required for the later bundle.

Use distinct state names:

- `qualified_10mhz_forwarded` only after physical qualification;
- `configured_10mhz_forwarded_unqualified` before physical evidence;
- `invalid_or_transitioning` around boot/configuration/source loss/readback
  contradiction; and
- `disabled` for profiles not selecting the output.

The D6 monitor uses a separate diagnostic state and never inherits D9 validity.
Its absence is explicit and does not become a clean D9 result.

## Phase 3 — implement D9/GPOUT0

Implement the smallest compile-time-selected output feature.

Required invariants:

1. The D8 PPS-gated PIO/DMA backend is initialized before output forwarding.
2. GPIO20 is then configured as `CLOCK GPIN0`. PIO continues to observe the
   always-connected pad input; no later source path may rewrite GPIO20's
   function selection while D9 is configured.
3. Configure GPOUT0 from `clksrc_gpin0`, integer divider one and fractional
   divider zero before exposing GPIO21 as `CLOCK GPOUT0`.
4. D9 remains disabled/high-impedance until configuration succeeds. Record the
   exact first-valid boundary; a register write alone is not proof of validity.
5. Never switch AUXSRC at runtime. Never route the external oscillator into
   `clk_sys`, `clk_ref`, USB, PIO or DMA clocks.
6. Profiles not selecting the output leave D9 disabled/high-impedance.
7. Rename generic `clock_visibility` ownership in the selected profile to an
   exact forwarded-output role while retaining explicit disabled-profile
   reservation semantics.
8. Add exact boot/status fields for contract identity, source, destination,
   requested/applied integer and fractional divider, source/destination GPIO
   function, inversion, drive/slew setting, configured state, readback state,
   nominal output frequency and validity reason.
9. D8/D14 measurement health and FLL eligibility must not depend on D9 status.
   A D9 fault may block the output claim or integrated profile but may not
   rewrite canonical measurement truth.

Add source guards against later GPIO20 mux writes, alternate AUXSRC values,
nonzero fractional division, hidden runtime output enable/source changes and
use of D9 as a timing input.

## Phase 4 — implement the D6 diagnostic monitor

Bind D6/GPIO18 as `forwarded_clock_monitor` only in the exact qualification
profile. D4 and D5 remain unassigned alternatives; D10 remains external-event
evidence.

Use a dedicated qualification counter based on the proved cumulative PIO
snapshot design where resource analysis permits it:

- one additional dynamically allocated PIO state machine and non-overlapping
  instruction range;
- D6 as `IN_BASE` and D14 as the shared read-only snapshot condition;
- one cumulative monitor snapshot per accepted D14 boundary, never per-edge
  telemetry;
- its own raw records, snapshot sequence, capture session, continuity, flags,
  backend and resource identity;
- exact expected source/output nominal frequency in the profile; and
- bounded queue and transport behavior that cannot backpressure D14/D8.

The D6 consumer must not feed D14/D8 validity, estimator selection, FLL/hybrid
eligibility, DAC requests, abort or run terminal. If the exact profile cannot
allocate the monitor without compromising the qualified D8 backend, preserve
that finding and use `d6_monitor_unavailable_due_to_resource_conflict`; do not
steal resources or make D6 a prerequisite for external D9 qualification.

## Phase 5 — host, analyzer and evidence path

Extend the existing platform rather than creating a D9-only runner.

The host path must:

- bind output/D6 status to the exact firmware, profile and contract;
- reject unknown source/divider/GPIO/readback identities;
- retain output state transitions and invalid intervals without treating them
  as steady output;
- preserve D8/D14 and D6 count streams separately;
- compare D8 and D6 only through their declared D14-gated count domains;
- ingest external instrument exports without rewriting them;
- retain wiring, load, probe, cable, instrument, bandwidth and uncertainty
  identities;
- compute enabled/disabled/load/monitor strata and exclude activation windows
  from steady-state comparisons;
- separate D9 output, D6 monitor, authoritative measurement, frequency-control,
  acquisition, analysis, sealing and registration terminals; and
- finalize through the current analyzer, sealer, content snapshot and evidence
  index.

The later runner must keep one continuously known serial owner, drain every
producer, monitor evidence more frequently than the shortest material fault
interval and preserve abort submission separately from delivery.

## Phase 6 — deterministic verification

Add focused tests for at least:

- exact D8/D9/D6 GPIO, GPOUT, PIO, DMA and queue ownership;
- initialization order and final GPIO20/GPIO21 functions;
- GPOUT0 AUXSRC/divider/fractional/readback identity before validity;
- source guards against every later GPIO20 mux write;
- D9 disabled in all unselected profiles;
- unchanged system/reference/peripheral clocks and D14/D8 owners;
- stopped-D8, D14 metadata/reference degradation, reset and configuration-fault
  output states;
- status/schema/parser/manifest/analyzer exactness and unavailable states;
- D6 snapshot continuity, missing/extra-edge fixtures, wrap and invalid flags;
- D6 kill/stall/overflow/corruption invariance of D14/D8 and controller state;
- D10 absence/noise/overflow invariance;
- queue saturation and transport obstruction without timing backpressure;
- output-profile and expected-failure build guards; and
- artifact finalization, seal and registration failure/replay behavior.

Run the affected current firmware profiles and the proportionate Release gate
because clock/GPIO ownership and the shared firmware profile are architectural
surfaces. Do not use a fixture to claim waveform or physical propagation.

## Phase 7 — complete no-hardware operational rehearsal

Exercise the actual runner, sole-owner capture process, supervisor, monitor,
logging, status queries, analyzer, rotation, abort, sealing and registration
topology using deterministic pseudo-I/O and accelerated time.

The rehearsal must cover:

- cold start and expected output configuration/readback;
- repeated status queries and the first dependent snapshot;
- output configuration failure before validity;
- D8 disappearance/return, D14 reference degradation and reset states;
- D6 absent, stalled, overflowing and contradictory while D14/D8 remains
  healthy;
- representative frequency-only decisions without any phase/hybrid authority;
- transport obstruction and independent bounded abort delivery;
- atomic serial-owner transfer/rotation with no ownerless interval;
- clean stop, analysis, seal, content snapshot and temporary registration; and
- replay of exact output and controller chronology.

State which boundaries are real and which are fixtures. This rehearsal proves
host/firmware contract and operational topology only. It does not prove D9
voltage, waveform, propagation, load behavior, physical D8-to-D9 forwarding or
real D6 loopback.

## Phase 8 — freeze and hand off

Freeze one immutable non-effective candidate bundle containing:

- source revision and clean/dirty identity;
- finalized GNSS/UART dependency and V2 study identities;
- exact firmware profile, compile configuration, toolchain, ELF and UF2;
- output/D6 contracts, source guards, host/analyzer/sealer/registration tools;
- expected boot/configuration/readback/query transcript;
- D9/D6 wiring diagram, resistor, loads, cable and instrument requirements;
- the exact non-actuating D8-source-loss and D14-reference-loss procedures, or
  an explicit statement that they cannot be physically exercised safely and
  will leave the waveform claim incomplete;
- frequency-only FLL policy, DAC envelope, cadence and stop conditions;
- physical stage sequence and evidence destinations;
- preflight, focused/release tests and operational-rehearsal result; and
- independent abort and finalization procedure.

Set physical authority false. Do not create a live acquisition directory.

Deliver exactly one readiness terminal:

- `d9_d6_candidate_bundle_ready_for_physical_authority`;
- `integration_base_not_established`;
- `d9_output_implementation_not_ready`;
- `d6_monitor_unavailable_due_to_resource_conflict` only when D9 remains
  independently ready; or
- `readiness_invalid_due_to_identity_or_verification_failure`.

Provide one concise yes/no request to authorize the exact bundle under Prompt
02. Stop after that request.
