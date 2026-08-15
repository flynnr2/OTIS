# OTIS Public-Readiness Programmes

## Purpose

This folder defines three descriptively named programmes intended to close the
remaining gap between the present OTIS evidence and a defensible public GPSDO
demonstration:

1. [`DISCIPLINED_10MHZ_OUTPUT_PROGRAMME.md`](DISCIPLINED_10MHZ_OUTPUT_PROGRAMME.md)
   exposes and qualifies the disciplined oscillator signal on a usable output;
2. [`HYBRID_PHASE_FREQUENCY_CONTROL_PROGRAMME.md`](HYBRID_PHASE_FREQUENCY_CONTROL_PROGRAMME.md)
   selects and physically qualifies one bounded coherent phase/frequency
   controller; and
3. [`BOARD_MOTION_TELEMETRY_PROGRAMME.md`](BOARD_MOTION_TELEMETRY_PROGRAMME.md)
   adds provenance-preserving onboard accelerometer and gyroscope telemetry
   without contaminating timing or control.

These are programme names, not oscillator or campaign serial numbers. New work
must use descriptive identities. Historical names such as CX317, CX318 and
CX319 may appear only when binding preserved source evidence, profiles, reports,
or wire identities that already use those names. Do not rename historical
artifacts or rewrite their provenance.

## Current boundary

The complete 30-point range-spanning survey has reached a healthy terminal at
`0xA800`, `OUTSIDE`, and bracketed all four state-dependent transitions at
survey resolution. The exact raw package and corrected host-only reanalysis
are separately content-addressed. There is no longer a preserved `0xA844`
continuation dependency.

The immediate physical gate is now the survey-derived one-code Part A fine
pass. Before bench entry, freeze its adaptive boundary-observation rule and
monotonic outbound/return point order, and revise the zero-authority hybrid
preview that reached its prospective low-net-path guard during the return leg.
The frequency programme must then complete the fine map and its prospectively
gated Part B automatic frequency-only traversal, or reach an explicit terminal
result that changes the plan. The survey does not establish fine hysteresis
intervals, matched controlled response, accelerated cadence, Part B viability,
or active-hybrid readiness.

Offline review, design, fixtures and source work for the new programmes may
proceed while the board state is preserved, provided they do not access the
serial device, flash, reset, command, rewire, or otherwise touch the bench.

## Programme ordering

| Order | Programme | Dependency | Why this order |
|---:|---|---|---|
| 0 | Complete the existing range-spanning frequency programme | current preserved `0xA844` state | supplies the missing bidirectional plant, hysteresis, controller and cadence evidence |
| 1 | Disciplined 10 MHz output | frequency programme terminal; board state released | qualifies the physical output and establishes a frequency-only sustained baseline |
| 2 | Hybrid phase/frequency control | frequency result plus terminal output qualification and its frequency-only soak | qualifies hybrid behavior while observing the exact output configuration already delivered and baselined |
| 3 | Board motion telemetry | may be developed offline independently; integrated only after isolated qualification | useful contextual provenance, but not allowed to delay or contaminate the timing/control result |

The output programme must complete its frequency-only output soak and reach a
terminal qualification result before the hybrid programme begins candidate
selection or physical work. That soak is the predeclared frequency-only output
baseline for later hybrid comparison. The sustained hybrid trial must reuse the
exact qualified output contract and load configuration and measure D9
throughout, but it is an integrated confirmation of an already qualified
output, not a deferred substitute for output qualification.

The motion programme is not automatically a public-release blocker. If it is
not ready, omit it from the first public firmware and say so. If it is included,
the final integrated rehearsal and sustained run must use that exact enabled
configuration so its I2C and telemetry load are exercised rather than inferred.

## Authority model

These documents are plans and Codex execution prompts. Their presence in the
repository grants no physical or actuation authority.

- An instruction to execute one of these programmes authorizes its offline
  preparation stages only unless the operator explicitly authorizes the exact
  physical bundle.
- Flashing, reset, serial-device access, wiring changes and physical acquisition
  require an exact frozen bundle and an explicit operator decision.
- Any phase-derived or hybrid-derived DAC influence requires its own bounded
  active-hybrid authority after a passing zero-authority preview gate.
- Authority is consumed by the first terminal attempt unless its exact record
  explicitly says otherwise.
- A failed physical or operational gate stops progression. Do not weaken a
  criterion after observing the result.

Each programme must preserve separate structural preflight, operational-path
rehearsal and physical qualification gates. Each physical programme must use
the stabilized capture, supervision, priority-abort, analysis, sealing and
registration path, and must retain exact source, build, configuration and
evidence identities.

## Public claim boundary

The target public statement, if the applicable programmes pass, is bounded:

> OTIS disciplines a 10 MHz oscillator against qualified GNSS PPS, exposes a
> characterized digital replica of that oscillator, and records enough raw and
> derived evidence to replay its measurements and control decisions.

An active-hybrid claim may be added only after the hybrid programme passes.
Motion telemetry may be described as contextual board-motion provenance only
after its programme passes.

These programmes do not by themselves establish:

- UTC or time-of-day output;
- calibrated absolute phase or cable-delay compensation;
- traceable absolute frequency accuracy;
- a 50-ohm laboratory output specification;
- a phase-aligned PPS output;
- predictive holdover;
- calibrated vibration metrology; or
- independence from the documented host/carrier lifecycle.

Any public report must distinguish observed facts, derived results, modeled
counterfactuals and unavailable uncertainty. A policy state such as
`TIGHT_INSIDE` or `HYBRID_TRACKING` is satisfaction of declared criteria, not
proof of correctness, traceability or universal performance.

## Shared completion discipline

Every programme must:

1. record one concrete decision-bearing objective;
2. freeze the exact operationally significant bundle before physical entry;
3. preserve canonical raw observations unchanged;
4. trace every critical handoff through its first decision-bearing consumer;
5. keep optional service telemetry outside timing and control authority;
6. use finite stop conditions and retain failed attempts;
7. compare the final implementation with a host replay where applicable;
8. seal and register every evidence-bearing terminal package; and
9. leave one concise tracked report stating the result, limitations, final
   hardware state and next decision.

Do not create a fourth umbrella campaign identifier. The three programme names
and descriptive timestamped run identities are sufficient.
