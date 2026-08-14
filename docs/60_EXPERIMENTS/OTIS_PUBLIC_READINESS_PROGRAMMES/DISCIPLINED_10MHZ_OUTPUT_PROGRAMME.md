# Codex Programme: Disciplined 10 MHz Output

## Status and authority

Status: draft programme; offline preparation only.

This document grants no authority to flash, reset, access the serial device,
rewire the bench, enable an output, or run a physical qualification. A later
operator decision must bind an exact bundle, installed-board identity, wiring
and load envelope, stop conditions, tools and evidence destinations.

Do not begin any physical step until the current state-preserving range survey
and its dependent frequency-control programme have reached their declared
terminal results. In particular, do not sacrifice the currently confirmed
`0xA844` hysteretic state to develop this output.

## Decision-bearing objective

Determine whether OTIS can expose the D8 disciplined-oscillator input on D9 as
a stable, characterized, provenance-declared 10 MHz digital reference output
without changing the RP2040 system clock, degrading D8/D14 measurement,
contaminating control, or claiming an electrical interface that the bare board
does not support.

The preferred first implementation is a divide-by-one RP2040 clock-output path:

```text
conditioned steerable-oscillator 10 MHz
    -> D8 / GPIO20 / CLOCK GPIN0
    -> RP2040 GPOUT0 source mux and divide-by-one output
    -> D9 / GPIO21 / CLOCK GPOUT0
```

This is a forwarded digital replica of the existing disciplined oscillator
signal. It is not an RP2040-synthesized replacement oscillator, does not make
the external oscillator the RP2040 system clock, and does not create UTC or a
phase-aligned time scale.

## Established factual basis

- The Nano RP2040 Connect pinout maps D8 to GPIO20/CLOCK GPIN0 and D9 to
  GPIO21/CLOCK GPOUT0.
- The RP2040 GPOUT auxiliary-source mux supports `clksrc_gpin0` directly and
  the output divider supports divide by one.
- RP2040 GPIO function selection does not make PIO input observation exclusive.
  The RP2040 datasheet states that the PIO inputs remain connected and can see
  every GPIO regardless of the selected GPIO function. Selecting
  `CLOCK GPIN0` on GPIO20 therefore permits the clock block and the existing
  D8 PIO counter to consume the same conditioned pad-level signal
  simultaneously.
- This silicon guarantee predicts no change in D8 PIO edge counting merely
  because GPIN0 also feeds GPOUT0. The required before/after count comparison
  is consequently a focused regression for initialization-order mistakes,
  unintended reconfiguration and physical switching or loading effects; it is
  not an unresolved architectural question about whether PIO and GPIN0 may
  observe GPIO20 concurrently.
- Current OTIS firmware reserves D9/GPOUT0 for `clock_visibility` and documents
  it as an internal-clock diagnostic output. Repurposing it is an explicit
  ownership and semantic change.
- D8 remains the authoritative oscillator/count input. D14 remains the sole
  authoritative PPS/reference input. D10 remains the independent external
  event input.
- The Nano header exposes a 3.3 V CMOS GPIO, not a presently qualified 50-ohm
  laboratory output driver.
- GPOUT source switching can glitch. Normal operation must therefore configure
  one frozen source during boot and avoid runtime source switching.
- The installed Pico SDK's `clock_configure_gpin()` selects `CLOCK GPIN0` as
  GPIO20's final function while configuring the requested clock generator.
  Conversely, `pio_gpio_init(..., GPIO20)` selects a PIO function. PIO input
  observation survives the former change, but GPIN0 forwarding does not
  survive a later function-selection write back to PIO. Initialization order
  and the absence of later GPIO20 function reconfiguration are therefore
  decision-bearing invariants.

Use the local sources in:

- `docs/datasheets/ABX00053-full-pinout.pdf`;
- `docs/datasheets/ABX00053-schematics.pdf`;
- `docs/datasheets/RP2040.datasheet.A700000007747462.pdf`;
- `docs/40_HARDWARE/NANO_RP2040_CLOCK_PIN_STRATEGY.md`; and
- `docs/50_SOFTWARE/HARDWARE_RESOURCE_OWNERSHIP.md`.

Do not strengthen any electrical or phase claim beyond those sources and the
new measurements.

## Required decisions before implementation

Freeze an output contract that states:

- signal identity and nominal frequency;
- source and destination clock domains;
- pin, voltage convention and output-drive configuration;
- divider, inversion and duty-cycle semantics;
- intended load, cable and connector envelope;
- startup, reset, reference-loss, oscillator-loss and firmware-fault behavior;
- whether output continuity or forced disable is preferred for each fault;
- the meaning and transport of output-validity telemetry;
- measured propagation delay and whether it is informational or part of an
  accepted specification;
- what constitutes a glitch, interruption or invalid output interval; and
- every claim deliberately not made.

If the intended external load is unspecified, use a conservative high-impedance
instrument-input qualification envelope. Do not silently assume that D9 can
drive a terminated 50-ohm input or arbitrary cable. If the required public
interface exceeds the GPIO evidence, select and document a dedicated external
fan-out/line-buffer design rather than forcing the direct-D9 hypothesis.

## Stage 1: evidence and contract freeze

Codex must:

1. bind the final range-spanning Part A and Part B evidence and last confirmed
   DAC state;
2. audit the current board, clock, GPIO, resource and boot-profile ownership;
3. inspect the exact installed Arduino/Pico clock implementation used by the
   build rather than relying only on a generic SDK example;
4. define the output contract and a versioned machine-readable profile;
5. define a descriptive run identity such as
   `disciplined_output_qualification_<UTC>`;
6. define the measurement equipment, probes, loads, cable lengths and their
   relevant bandwidth or uncertainty; and
7. prepare an immutable programme ledger and non-effective physical authority
   proposal.

Preflight proves only identities, declarations and legal configuration. It is
not output qualification.

## Stage 2: bounded firmware and telemetry implementation

Implement the smallest explicit output feature that satisfies the frozen
contract.

Required properties:

- a compile-time profile selection; no hidden runtime mode switch;
- D9/GPOUT0 ownership renamed from generic internal visibility to the exact
  selected output role;
- GPOUT0 sourced directly from GPIN0 with the frozen divide-by-one setting;
- no rerouting of `clk_sys`, `clk_ref`, USB, PIO or the timing fabric;
- no software edge generation, interrupt forwarding or CPU-defined timestamps;
- no change to D8, D14 or D10 authority;
- an explicit initialization sequence in which the D8 PIO count backend is
  initialized first, GPOUT0 is then configured from GPIO20/GPIN0 at 10 MHz
  divide by one, and GPIO21 is finally exposed as `CLOCK GPOUT0` only after the
  clock-generator configuration succeeds;
- GPIO20's final function selection is `CLOCK GPIN0`; PIO continues to observe
  D8 through its always-connected input path, and no later
  `pio_gpio_init()`, `gpio_set_function()` or equivalent operation may change
  GPIO20's function selection while the output is declared configured;
- D9 remains disabled or high-impedance until the GPIN0 source, integer-one
  divider and output validity boundary have been configured; no live AUXSRC
  change is permitted;
- boot telemetry for source, destination, divider, inversion, drive setting,
  configured state, output contract identity and validity semantics;
- explicit behavior when D8 stops, D14/reference qualification is lost, control
  faults, the host disconnects, or the firmware resets;
- no runtime source change after output activation; and
- updated architecture, clock-pin, resource-ownership, firmware-profile and
  known-limitations documentation.

If output enable is not atomic and glitch-free, configure it before the output
is declared usable and record the exact validity boundary. Do not label D9
valid merely because the mux register was written.

## Stage 3: deterministic verification and operational rehearsal

Add focused checks for:

- exact D8/D9/GPOUT0 resource ownership;
- expected source and divider constants in every enabled profile;
- exclusion of alternate GPOUT sources and runtime switching;
- the required initialization ordering and final GPIO20/GPIO21 function
  selections, including a source guard against any later GPIO20 function-mux
  write that would silently stop GPIN0 forwarding while leaving PIO counting
  operational;
- readback or equivalent exact evidence that GPOUT0 is enabled from
  `clksrc_gpin0` with integer divider one and zero fractional divider before D9
  is declared valid;
- output disabled or high-impedance in profiles that do not select it;
- unchanged system/reference/peripheral clock configuration;
- unchanged D8 PPS-gated count and D14 reference ownership;
- boot/status schema and manifest identity;
- reset, stopped-D8 and reference-loss state reporting;
- supported and expected-failure build profiles; and
- host parsing, validation and evidence finalization of the new status surface.

Run the affected current firmware profiles and the proportionate Release gate
because clock and GPIO resource ownership are shared architectural surfaces.

The operational-path rehearsal must use the actual capture, supervisor,
logging, stop, analyzer, sealing and registration path. It must inject output
configuration failure and transport obstruction without pretending that a
software fixture measures waveform quality.

## Stage 4: physical waveform and non-interference qualification

This stage requires separate explicit operator authority and suitable physical
measurement equipment.

Measure D8 and D9 simultaneously wherever practical. Preserve raw captures or
instrument exports plus instrument identity and settings. Exercise at least:

- normal 10 MHz operation at the frozen nominal load;
- the permitted load and cable extremes;
- cold boot and firmware reset;
- output activation boundary;
- D8 disappearance and return;
- D14/reference loss while D8 continues;
- a static DAC code and at least one bounded frequency-control movement; and
- sustained output during representative USB, telemetry, environmental I2C and
  control-service load.

Determine:

- D8 and D9 frequency/count agreement;
- output high/low levels, rise/fall behavior and duty cycle;
- D8-to-D9 propagation delay, variation and startup repeatability;
- added period jitter or measurement-floor limit;
- glitches, missing or extra edges and interruptions;
- load sensitivity and ringing;
- effect on D8/D14 snapshot association, selected estimates, queue health,
  transport and control decisions; and
- whether direct D9 remains suitable or an external output buffer is required.

Interpret the enabled-versus-disabled D8 comparison narrowly. The documented
RP2040 input topology predicts unchanged PIO counts because enabling the
GPIN0-to-GPOUT0 branch does not remove or replace the PIO input branch. A
change in D8 count continuity, validity or distribution is therefore evidence
of an implementation-order defect, unintended register/resource interaction,
or a physical electrical effect such as supply, ground, edge or loading
coupling. It must not be normalized as an expected consequence of shared
observation. Reject the activation-boundary window from steady-state
comparison, preserve it as transition evidence, and compare clean bounded
segments before and after output activation.

Use the cheapest test capable of supporting each claim. A frequency counter
alone cannot establish edge integrity, delay or duty cycle; an ordinary scope
without a stated floor cannot establish low phase-noise performance.

## Stage 5: integrated public-configuration soak

After the waveform gate passes, run a finite sustained observation with the
output continuously enabled and externally loaded inside its qualified
envelope while frequency-only control remains authoritative and all hybrid
output remains non-actionable. This frequency-only output soak must complete
before hybrid candidate selection or physical hybrid work begins. Preserve it
as the predeclared output and frequency-control baseline for later hybrid
comparison; do not defer it into, or replace it with, the active-hybrid
programme.

The later sustained hybrid trial must reuse the exact qualified output contract
and load configuration and measure D9 throughout. That later evidence is an
integrated confirmation of the already qualified output configuration, not a
retroactive part of this output qualification gate.

The soak must retain:

- continuous D8/D14 measurement and D9 output status;
- exact firmware, output-contract and load identities;
- count/phase/control replay;
- transport and queue evidence;
- all output interruptions or invalid intervals; and
- final static DAC and output state.

## Terminal decisions

Choose exactly one:

- `direct_d9_output_qualified_within_declared_cmos_load_envelope`;
- `direct_d9_output_requires_external_buffer_or_interface_revision`;
- `output_function_correct_but_waveform_evidence_incomplete`;
- `output_degrades_measurement_or_control`;
- `output_implementation_or_platform_fault`; or
- `operator_abort`.

Do not call the output qualified merely because D9 toggles or a counter reports
10 MHz.

## Required deliverables

- versioned output contract and profile;
- firmware implementation and resource ledger;
- host status parsing and validators;
- deterministic focused tests and affected build results;
- operational rehearsal report and seal;
- physical waveform evidence and analysis;
- integrated soak package, seal and registration;
- tracked `docs/60_EXPERIMENTS/` qualification report; and
- concise wiring/use guidance with explicit electrical and metrological limits.

Stop after offline preparation and present the exact non-effective physical
authority proposal. Do not touch the bench until the operator explicitly
authorizes that bundle.
