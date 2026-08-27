# Prompt 02: D9 Waveform Qualification and Frequency-Only Output Soak

Execute this prompt only after Prompt 01 reaches
`d9_d6_candidate_bundle_ready_for_physical_authority` and an operator explicitly
authorizes the exact candidate-bundle identity and SHA-256.

If the initiating instruction does not name or unambiguously accept that exact
bundle, perform read-only validation and ask one concise yes/no authority
question. Do not flash, reset, open the serial device, change wiring or create a
live run directory before authority is explicit.

## Goal

Qualify or reject D9 as a direct forwarded 10 MHz CMOS output under its frozen
load envelope, qualify or locally reject D6 as its diagnostic monitor, prove
that the output path does not degrade authoritative D14/D8 measurement or the
frequency-only controller, and then establish a finite sustained D9/FLL-output
baseline.

Hybrid and phase-derived control authority are exactly zero throughout this
prompt. The only possible automatic steering is the already-qualified reactive
frequency-only FLL from the frozen bundle.

## Authority envelope

After exact authorization, this prompt permits:

- one exact firmware flash and normal reset/re-enumeration operations;
- the frozen D9-to-D6 series-resistor loopback and declared external
  instrument/load wiring;
- the bundle's exact bounded D8-source-loss/return and D14-reference-loss/return
  procedures, only in separately identified non-actuating segments;
- sole-owner serial capture and exact status queries;
- D9 activation only through the compile-time exact profile;
- the frozen frequency-only FLL envelope, including only those bounded
  automatic movements allowed by the bundle; and
- the finite waveform qualification and 24 qualified-hour output soak below.

It does not permit:

- a GNSS receiver command or baud change;
- a predetermined DAC setup/restore write not frozen in the bundle;
- hybrid/PLL authority, a phase-derived request or changed-controller trial;
- runtime GPOUT source, output pin or divider changes;
- fractional division;
- operation outside `0xA800..0xAB00`, a step above 21 codes or a cadence faster
  than 1800 seconds;
- a 50-ohm or arbitrary cable/load claim outside the frozen contract;
- extending the run to rescue an ambiguous or failed result; or
- the later 72-hour integrated hybrid trial.

## Stage 1 — exact-bundle and physical pre-actuation gate

Before flashing or wiring:

1. Revalidate every source, contract, tool, build, ELF/UF2, profile, output,
   D6, FLL, stop-condition and evidence-destination identity from Prompt 01.
2. Confirm the sealed GNSS result and current receiver baud agree with the
   bundle. Do not issue a receiver command to make them agree.
3. Establish one continuously known serial owner and continuously drained
   logging before enabling capture producers.
4. Confirm board identity, expected clean boot transcript, resource registry,
   PIO/DMA allocations, GPIO20/21/18 functions, GPOUT source/divider/readback,
   output disabled/invalid state and absence of hybrid authority.
5. Confirm the live applied DAC code and epoch through the authoritative query
   path. Treat a mismatch as provenance uncertainty; do not restore a guessed
   code.
6. Record oscilloscope, independently referenced frequency counter, probes,
   terminations, cable, D9 load, D6 resistor/jumper, bandwidth, sample-rate and
   measurement-floor identities.
7. Confirm the independent abort path and rehearse bounded delivery before the
   output is exposed.

Preflight establishes identity and authority only. It is not waveform evidence.

## Stage 2 — stratified physical activation

Use one run package and preserve distinct segments:

1. **D9-disabled baseline:** retain clean D14/D8 counts, selected estimates,
   resource/queue/service evidence and physical D8 observations where
   available.
2. **D9 enabled, external high-impedance instrument only:** reject the
   activation interval from steady-state comparison but retain it as transition
   evidence.
3. **Frozen nominal D9 load/cable attached:** measure the declared public
   direct-output condition.
4. **D9-to-D6 loopback attached, monitor disabled:** isolate electrical jumper
   and input loading.
5. **D6 monitor enabled:** isolate PIO, queue and telemetry effects.
6. **Frozen load/cable extremes:** exercise only the prospectively declared
   envelope.

Do not combine these strata into one before/after comparison. Confirm D14/D8
continuity and queue health at every boundary before advancing.

## Stage 3 — waveform, startup and fault qualification

Measure D8 and D9 simultaneously wherever practical. External scope and
independently referenced counter evidence is primary; D6 is corroborating
digital evidence only.

Exercise and retain raw captures/exports for:

- normal 10 MHz operation at nominal and permitted load/cable extremes;
- cold boot and firmware reset;
- the output activation/first-valid boundary;
- D8 disappearance and return;
- D14/reference loss while D8 continues;
- a static DAC interval and at least one naturally eligible bounded FLL
  movement, without forcing a correction merely to obtain it;
- representative USB/status, environment/I2C, capture, logging and control
  service load; and
- D6 absence, disconnect/reconnect and monitor enable/disable only where the
  frozen bundle declares those transitions safe.

Before either planned D8-source-loss or D14-reference-loss segment, clear all
control authority, prove no request/response is outstanding, retain the last
confirmed applied code and make physical DAC execution unreachable. Keep the
segments separate from steady-state waveform evidence. Re-enter frequency-only
authority only after the exact source/reference identity and a complete
causally later D14/D8 observation requalify. If the bundle lacks a safe
conflict-free procedure, do not improvise the fault and retain an explicit
incomplete qualification field.

Determine against frozen acceptance criteria:

- D8/D9 frequency and count agreement;
- D9 high/low levels, rise/fall behavior, duty cycle and load sensitivity;
- D8-to-D9 propagation delay, variation and startup repeatability;
- added period jitter or an explicitly stated instrument-floor bound;
- glitches, missing/extra edges and output interruptions;
- overshoot, ringing and suitability of the direct CMOS output;
- D8-to-D6 cumulative ratio, missing/extra-edge deficit and continuity;
- D14/D8 snapshot association, selected estimate and FLL-decision invariance;
  and
- queue, transport, Core 0/Core 1 and service-plane non-interference.

A counter reporting 10 MHz or a D6 count match cannot qualify voltage, edge,
load, delay, jitter or ringing. Do not call a scope-floor result a phase-noise
specification.

If D8 continuity changes when output is enabled, treat it as an
initialization/resource/electrical isolation defect. Do not normalize it as an
expected consequence of shared GPIN0/PIO observation.

## Waveform gate

Choose exactly one D9 terminal before the soak:

- `direct_d9_output_qualified_within_declared_cmos_load_envelope`;
- `direct_d9_output_requires_external_buffer_or_interface_revision`;
- `output_function_correct_but_waveform_evidence_incomplete`;
- `output_degrades_measurement_or_control`;
- `output_implementation_or_platform_fault`; or
- `operator_abort`.

Choose independently one D6 terminal:

- `d6_forwarded_clock_monitor_qualified_as_diagnostic_only`;
- `d6_monitor_unavailable_without_d9_claim_impact`;
- `d6_monitor_platform_defect`; or
- `d6_monitor_degrades_authoritative_path`.

Only `direct_d9_output_qualified_within_declared_cmos_load_envelope` permits the
frequency-only output soak. A D6-unavailable result may proceed when external
D9 evidence is sufficient and D14/D8 is unaffected. A D6 shared-path defect
must be removed or isolated before the soak; never make D6 a health veto.

## Stage 4 — finite sustained frequency-only output soak

Freeze and record the exact start frontier before arming.

Required envelope:

- 24 hours of measurement-qualified observation;
- 90-minute initial qualification deadline;
- 30-hour absolute wall-clock ceiling;
- D9 continuously configured at integer divisor one and loaded inside the
  exact qualified envelope;
- unchanged frequency-only FLL as the sole controller;
- hybrid/PLL request and authority paths absent or provably non-actionable;
- the exact retained FLL DAC range, step, cadence, movement and transaction
  budgets from the bundle, with no widening after start;
- no forced correction and no automatic retry or nominal restoration; and
- continuous authoritative supervisor/evidence monitoring at a cadence shorter
  than the smallest material fault interval.

Retain throughout:

- D14/D8 canonical capture and selected frequency estimates;
- D9 configured/readback/validity and external frequency evidence;
- D6 monitor observations and local faults when enabled;
- every FLL observation, suppression, request, acceptance, application,
  first-dependent consumer and response;
- applied code, DAC epoch, path, net movement, reversals and settling;
- output interruptions/invalid intervals, load identity and instrument state;
- GNSS metadata, hold/ineligibility, receiver identity and selected baud;
- resource, queue, transport, memory, USB/status and environmental evidence;
  and
- abort submission/delivery, stop, analysis, seal, snapshot and registration.

Keep the controlling Codex turn active with bounded polling until terminal.
Process existence and a quiet terminal are not evidence of scientific progress.
Report meaningful milestones from authoritative records, including initial
qualification, each FLL transaction boundary, 6/12/18/24 qualified hours,
output invalidity, stale evidence and terminal transitions.

## Soak acceptance and terminal

The soak passes only if it reaches 24 qualified hours with:

- exact identity and output/load configuration;
- no D9 interruption or invalid interval outside declared boot/transition
  boundaries;
- D9 frequency continuity and external evidence inside the frozen contract;
- no output-correlated D14/D8 validity, estimator, queue, service or FLL
  degradation;
- exact replay of every FLL decision and actuator transaction;
- all bounds respected and no hybrid/phase influence; and
- successful acquisition finalization, analysis, seal, content snapshot and
  registration.

Choose exactly one soak terminal:

- `frequency_only_d9_output_soak_passed`;
- `frequency_only_d9_output_soak_incomplete`;
- `frequency_only_d9_output_noninterference_failed`;
- `frequency_only_controller_or_transaction_fault`;
- `soak_invalid_due_to_identity_or_evidence_failure`; or
- `operator_abort`.

Do not repeat a successful acquisition because an offline finalizer fails. Do
not extend an incomplete soak merely to get a preferred answer.

## Stage 5 — close the provisional controller gate

Without refitting or replaying a changed candidate, record exactly one:

- `cx322_unchanged_confirmed_by_d9_fll_output_gate` only when the D9 waveform
  terminal is qualified and the frequency-only soak passes;
- `cx322_integration_blocked_by_d9_output_gate` for any other scientifically
  valid D9/soak terminal; or
- `controller_decision_invalid_due_to_identity_or_evidence_failure`.

This decision says whether the retained unchanged coherent FLL/PLL law may move
to integration. It does not claim that D9 proves hybrid performance, phase
lock, UTC or superiority over the non-selectable debt candidates.

## Deliverables and stop

Produce:

- immutable waveform and soak run packages;
- exact wiring/load/instrument ledger and raw exports;
- D9, D6, acquisition, FLL, analysis, sealing and registration terminals;
- before/after/load/monitor comparisons and non-interference result;
- exact FLL replay and actuator-cost report;
- tracked D9 qualification and frequency-only soak report;
- updated output contract, resource ledger, use guidance and known limitations;
- controller-decision closure with the unchanged frozen selection rule; and
- exact final applied code, DAC epoch, receiver baud and output state.

Stop with D9 disabled or in the bundle's declared safe final output state and
the last confirmed DAC code unchanged by any restoration. Do not begin Prompt
03 in the same uncontrolled live turn; finalize and seal first.
