# Startup reference-selection service review

## Evidence and scope

The operator-reported inhibited observation retained two LAT stage-2 outliers:
sequence 0, `1944364 -> 1951675`, **7,311 us**, and sequence 1,
`2944390 -> 2952574`, **8,184 us**. Its `>4096 us` count remained two;
subsequent samples accumulated in the 257–1024 us bin. These values were
provided with the request; this review does not claim independent access to
that bench's complete raw log. The D14 and D8 channel labels repeat the same
snapshot's software endpoints, so they are two events, not four.

Both endpoints are in `rp2040_monotonic_us32`. Stage 2 begins after
`reference_acceptance.observe` returns and ends immediately **before**
`otis_phase_preview_live_on_reference_selection` is called. It excludes phase
estimator execution, frequency estimator execution, hardware capture delay and
USB delivery time. The final publication of its statistics occurs later but
uses the retained pre-call endpoint.

## Source-supported cause and remaining uncertainty

`setup1` calls `boot_phase_preview_init` before publishing normal timing-boot
completion and entering `loop1`. Phase initialization therefore does not occur
between these endpoints. The phase engine remains unbound until an exactly
confirmed applied code and DAC epoch are supplied. Its reference-selection
entry returns immediately while unbound; merely reaching that entry is not
proof of a qualified estimate or of control authority. Applied-code binding
initializes the engine in the separate applied-state propagation path (timing
input service or application-outcome service), rather than lazily inside this
measured interval.

Before this repair, the interval included these operations in order:

1. Two channel-labelled diagnostic statistics updates and a copy of reference
   acceptance state.
2. Raw count-boundary reconstruction, runtime-state updates and canonical CNT
   publication when a complete adjacent pair exists.
3. Synchronous formatting and queue publication of count-transition status.
4. APS formatting/publication when reference acquisition has produced an
   accepted span, followed by copying the actuator-provenance state.
5. The timer read immediately before phase consumption.

The third operation has a specific startup pattern. Sequence 0 establishes the
first raw boundary, has no complete count interval, and publishes the opening
`pps_gate` status generation. Sequence 1 establishes the first known window
and changes the opening recovery reason, publishing its window-transition
status plus another generation. The native regression executes the actual
count module and observes **64** and **71** telemetry-row publication attempts,
respectively, for this clean startup sequence. A following unchanged window
publishes CNT without either burst. Later reference acquisition may change
control eligibility and produce another transition; the first two bursts are
not a claim that only two status transitions can ever occur.

Each row on Core 1 creates an `OtisTelemetryMessage`, samples the timer, formats
its fields and attempts a bounded queue publication. This path does not call
USB/serial writes and does not wait for the consumer. A full diagnostic queue
increments its drop count without acquiring fault authority. Thus the code
provides a concrete explanation for extra work at exactly sequences 0 and 1,
independent of the Core 0 output stall. It does **not** establish that formatting
alone accounts for every one of the measured 7,311/8,184 microseconds: target
execution, shared-memory/flash effects and interrupt service within the interval
remain unseparated by the existing endpoints. There is no deliberate millisecond
startup wait in this path.

The finding is **avoidable placement of transition reporting before dependent
consumption**, not evidence of slow phase-estimator execution or damaged
canonical capture. The precise reduction on hardware remains to be measured.

## Repair and ordering

Raw count processing now retains one small descriptor for the pending
transition report. CNT and APS keep their existing publication order before
phase and frequency consumption. The normal integrated path formats the report
immediately after phase consumption and its LAT update, before health refresh
and frequency/control consumption. Only the first phase consumer moves ahead
of reporting; the later health/frequency order is preserved. No status rows,
reason codes, snapshot delimiters or generation identifiers are removed.

This descriptor is owned solely by Core 1 and references its existing runtime
and status context; it is not an asynchronous queue. Every public entry point
that changes count/reference state flushes an outstanding descriptor first.
Consequently, a second boundary cannot overwrite the preceding transition, and
APS failure, reference invalidation or capture loss cannot replace the state
before its original transition is reported. The fault path may therefore still
format status before a downstream consumer: preserving failure ordering takes
precedence over reducing a diagnostic elapsed value. Diagnostic publication
failures retain their existing local drop semantics. Canonical publication
failures and capture faults retain their existing control-inhibition semantics.

The `pps_gate` generation still describes one unchanged foreground count and
accepted-reference state. As before, capture backend counters are sampled by
the status formatter and can include interrupt progress through the instant of
that read; the generation is not an atomic snapshot of all hardware counters.
The descriptor is cleared before emission, and a repeated flush emits nothing.
No second timing owner, dynamic allocation, additional hardware timestamp,
actuation permission or new wire schema is introduced.

The repair advances the first phase consumer in the normal path; it
does not remove the bounded status work or establish a worst-case runtime
bound. The burst still lies between this boundary and the next boundary drained
by Core 1. LAT endpoint definitions remain unchanged. Stage 2 now normally
excludes this deferred reporting work, while still including CNT/APS processing
and other operations physically preceding its endpoint.

## Verification and physical limit

The focused development run passed **71 tests**, covering the actual count
module's native startup/fault/drop and boundary-bridge regression, count ownership,
PPS gate math, reference acceptance, phase binding/replay, hardware-resource
source guards and the startup-census capture replay.
The new native harness runs with AddressSanitizer and UndefinedBehaviorSanitizer.
It uses a deliberately slow mock telemetry sink to prove that the canonical
count is available before transition output begins, rather than trying to
predict RP2040 elapsed time from desktop speed. It also verifies exactly-once
flush, retained raw count coordinates and flags, rejected-window diagnostics,
old/new reference-state ordering and diagnostic-local queue refusal. An
native bridge regression executes the actual extracted production boundary
function with the real count module and observable phase, health and frequency
doubles. It verifies `CNT -> APS (when present) -> phase -> status -> health ->
frequency`, including the health bridge's reference-state refresh. A separate
source guard verifies that normal boot initializes the preview before `loop1`
is enabled.

These checks do not exercise RP2040 interrupts, USB or target execution costs.
The integrated build/resource audit and operational rehearsal belong to the
combined handoff. The existing finite inhibited bench observation should retain
startup sequences 0 and 1, the corresponding LAT generations and steady-state
samples; compare the same stage-2 endpoints and preserve their source identity.
No extra actuation or standalone startup campaign is required. A reduced
observed maximum will still not be a worst-case guarantee.

See [the service-latency baseline](SERVICE_LATENCY_BASELINE.md) for endpoint,
clock-domain and diagnostic-coverage contracts.
