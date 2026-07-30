# Phase 4 Live Observe-Only Firmware Engineering Note

## Decision

The minimum live Phase 4 estimator, state, and correction-preview
implementation is complete and passes deterministic host/firmware fixture
parity. The firmware implementation is still opt-in and structurally
non-actuating.

The Stage SW2-2 exit gate is not yet passed because no Nano RP2040 Connect was
attached for upload, deliberate USB-load testing, reconnect testing, or a long
live observe-only run.

The authoritative boundary remains:

```text
plant model status.control_ready=false
plant model status.actuation_enabled=false
EST drift_enabled=false
CTL preview_only=true
CTL actuation_authorized=false
CTL actionable=false
```

## Implementation boundary

`otis_phase4_engine.*` is a pure C++ discipline engine with no Arduino,
transport, command, I2C, or DAC-driver dependency. It implements:

- a bounded arithmetic-mean frequency estimator with population dispersion;
- startup and clean-window qualification;
- roadmap-aligned `BOOT`, `WARMUP_INHIBIT`, `QUALIFYING`,
  `ACQUIRE_PREVIEW`, `HOLDOVER_PREVIEW`, `RECOVER_PREVIEW`, and latched
  `FAULT` behavior;
- distinct observation validity, diagnostic health, estimator confidence,
  model applicability, and preview eligibility;
- model-gain inversion with deterministic half-away-from-zero rounding;
- the disabled `0xA800..0xAB00` candidate clamp and `0x0300` maximum preview
  step.

`otis_phase4_observe_preview.*` is the live adapter. It consumes immutable
reference/count/DAC status supplied by existing owners, checks age,
continuity, flags, count zero/saturation, and capture drops, and emits the same
normative `EST v1` and `CTL v1` field ordering used by host replay.

`otis_phase4_boundary_estimator.*` is the allocation-free metrology component
used by the live adapter. It retains a fixed 384-point accepted-PPS support
array: enough for the 300 s H1 gate at the minimum accepted 0.8 s cadence plus
explicit margin. Each count boundary is interpolated independently. A
non-PPS-aligned close is retained in one fixed pending-count slot until the
following accepted PPS supplies its closing bracket. A second count cannot
silently overwrite it; overwrite, support-capacity loss, stale/missing
following support, and every invalidation reason are counted or emitted.

The adapter embeds and reports the exact SHA-256 of plant-model version 4 and
the default discipline configuration. Tests fail if the model hash, gain,
applicability range, disabled candidate range, or manual preview step diverges
from `profiles/plant_models/cx317_h1_bench_v3.json`. Model applicability also
requires the compiled
`LOCAL_PPS_BOUNDARY_INTERPOLATED_V1` definition hash; backend or method
mismatch inhibits every correction preview.

Run 020 count sequence 77 is excluded only when replaying Run 020 source
evidence. It is not interpreted as a globally invalid live sequence number.

## Structural actuation prohibition

The preview translation unit does not include the DAC driver and exposes no
write callback. It receives only:

```text
dac state available
latest evidence-backed applied code
```

The engine returns a proposal only to the telemetry adapter. No proposal is
returned to the sketch's manual command owner. Static tests reject DAC-driver,
I2C, or write-and-update symbols in the engine/adapter, and all live/host parity
fixtures require authorization and actionability to remain false.

Manual `DAC` and explicitly started `SWEEP` commands remain in the existing H1
open-loop command path. Preview cannot start, stop, step, restore, or otherwise
interact with a sweep.

## Bounded derived telemetry

Every estimate and its corresponding preview are formatted into one fixed-size
pair and enqueued in a fixed-capacity ring. Queue insertion happens after
estimator/state evaluation. If the queue is full, both derived rows are dropped
together and `phase4_preview.dropped_telemetry_pair_count` increments; the loss
cannot alter estimator state or raw `REF`/`CNT` capture.

Derived frames are transmitted in bounded chunks after capture service. While
a pair is partially transmitted, other record producers do not interleave
bytes into it; IRQ/PIO capture continues into the separate capture ring.
Periodic `STS` reports queue depth, high-water mark, drops, state, and the false
authorization flags. It also reports estimator method/hash, last boundary
reason, PPS-support overwrite count, and pending-count overwrite count.

This architecture is compile- and synthetic-load checked. A live service-plane
load/reconnect run is still required to quantify whether a prolonged host stall
can pressure the capture ring on the target USB implementation.

## Host parity

`tests/cpp/phase4_engine_harness.cpp` builds the exact firmware engine on the
host. `tests/test_phase4_firmware_parity.py` feeds it normalized observations
produced by deterministic host replay and compares:

- state, previous state, and transition reason;
- sample count, confidence, and estimator eligibility;
- frequency error and dispersion;
- full preview eligibility and availability;
- proposed code/delta and step/range limit results.

The matrix covers nominal acquisition, startup inhibit/qualification,
post-qualification zero-count fault, reference loss/return, model identity
mismatch, input outside applicability, and combined step/range clamping.
A second native harness emits live adapter rows and passes them through the
repository's strict `EST v1` and `CTL v1` validators.

`tests/cpp/phase4_boundary_estimator_harness.cpp` compiles the exact production
boundary estimator. Host/C++ comparisons cover valid and invalid mappings,
reason codes, boundary provenance, non-uniform intervals, missing support, and
the semantic counterexample where one-interval scaling gives a measurably
different answer. The live-adapter harness also exercises the pending
non-aligned-close path.

Numeric parity tolerance is `1e-9 Hz` for the synthetic fixture arithmetic.
Real target comparisons must use a documented tolerance based on emitted
decimal precision and count/reference quantization.

## Build validation

Revalidated on 30 July 2026 with FQBN
`rp2040:rp2040:arduino_nano_connect`:

| Build | Result |
|---|---|
| checked-in default H1 | pass |
| H1 long-gate with observe preview | pass |
| H1 PPS-gated ratio with observe preview | pass; model backend mismatch inhibits preview |
| H1 PIO sparse capture with observe preview and D10 witness disabled | pass; topology mismatch inhibits preview |
| TCXO FC0 with observe preview | pass; H1 model mismatch inhibits preview |
| divided-signal GPIO IRQ count with observe preview | pass; H1 model mismatch inhibits preview |

The checked-in default remains `OTIS_ENABLE_PHASE4_OBSERVE_PREVIEW=0`. An
observe-only build uses:

```bash
arduino-cli compile --fqbn rp2040:rp2040:arduino_nano_connect \
  --build-property compiler.cpp.extra_flags="-DOTIS_ENABLE_PHASE4_OBSERVE_PREVIEW=1" \
  firmware/arduino/otis_nano_rp2040_connect
```

The corrected H1 PIO-long-gate preview build used 93,504 bytes of program
storage and 33,716 bytes of global RAM in the local toolchain. The checked-in
default build used 82,848 bytes and 21,420 bytes respectively. The fixed PPS
support array accounts for the intentional bounded RAM increase.

## Verification results

Focused results:

```text
python3 -m pytest -q tests/test_phase4_boundary_estimator.py \
  tests/test_phase4_firmware_parity.py tests/test_phase4_replay.py
61 passed

python3 -m pytest -q
238 passed, 2 skipped
```

The two skips are the existing locally retained Run 020 preflight hooks.

`arduino-cli board list` found no attached OTIS target; only host serial
endpoints were present. No upload or hardware claim is made.

## Residual risks and gate effect

| Risk | Status and required evidence |
|---|---|
| Preview reaches a DAC write | Structurally prohibited and statically tested; retain this module boundary in review. |
| Compiled model constants become stale | Hash/value binding test fails on model change; rebuild and review are required. |
| Target floating-point differs from host | Synthetic C++ parity passes; compare captured live rows within documented quantization tolerance. |
| Derived USB traffic disturbs capture | Queueing and chunking are bounded; deliberate target load/reconnect testing remains required. |
| Long-run reference/count recovery differs on hardware | Fault/recovery fixtures pass; a long live run remains required. |
| Alternative backend or estimator semantics are mistaken for model applicability | Backend and full method-contract mismatch explicitly inhibit preview; string identity alone is insufficient. |
| Foreground latency extends a PIO gate | Artifact/configured duration identity remains exact; observed aperture has a configured 50 ms quality tolerance and larger deviations invalidate the observation. Target load evidence must confirm that bound. |
| A gate straddles DAC settling | Successful write timestamps are captured at both manual and sweep owners; applicability requires gate-open at or after the generated settling cutoff. Pre-boot DAC history remains unattested. |
| Primary temperature is missing or old | Failed SHT4x reads invalidate immediately and samples expire after three configured sample periods; `temperature_not_observed` blocks applicability. Physical sensor placement still requires bench evidence. |
| Candidate range is mistaken for permission | CTL and model flags remain false/non-actionable; no actuation callback exists. |

This change completes the implementation and deterministic-parity portion of
roadmap Stage SW2-2. It does not pass the Stage SW2-2 long-live-run exit gate,
qualify the PPS-gated measurement backend, or authorize any active-control
milestone.

Correct estimator semantics and physical aperture qualification are separate.
This implementation does not establish PPS-gated capture aperture, target
latency bounds under hardware load, traceable uncertainty, or a control-grade
measurement backend.

## Phase 5 compatibility correction

The Phase 5 PPS audit found two narrow cross-phase defects in the checked-in
adapter semantics. Live frequency derivation now uses the shared modular
`rp2040_timer0` interval helper when raw PPS-gated `CNT` boundaries cross
rollover. Live and host replay also keep a `REFERENCE_VALIDITY_SUSPECT` count
row on the reference side instead of marking an otherwise nonzero,
unsaturated oscillator count invalid solely because the same row carries
`GATE_INCOMPLETE`.

Regression tests bind both behaviors. They do not change estimator state,
preview policy, model applicability, or any actuation flag. The Phase 4 live
bench exit gate therefore remains open exactly as stated above.
