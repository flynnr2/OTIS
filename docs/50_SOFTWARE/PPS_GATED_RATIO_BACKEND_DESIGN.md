# PPS-Gated Ratio Backend Design

## Scope

This document defines the firmware and reporting contract for the PPS-gated
ratio count-observation backend. Firmware support exists behind
`OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO`; host analysis and active DAC
steering remain separate.

The backend must preserve the existing OTIS rule:

```text
raw observations first, host-side interpretation second
```

It must not silently reinterpret existing `CNT` rows as calibrated frequency
rows. A `CNT` row remains a raw counted-edge observation over an explicit gate.

## Physical Inputs

The PPS-gated ratio backend uses the current SW1/H1 pin convention:

| Signal | Arduino Nano RP2040 Connect pin | OTIS channel | Role |
|---|---:|---:|---|
| GNSS PPS/reference | `D14` / GPIO26 | `CH1` | reference edge and gate boundary |
| oscillator observation | `D8` / GPIO20 / `GPIN0` | `CH2` | counted oscillator edges |

Both inputs must be conditioned to RP2040-safe 3.3 V logic and share a common
ground with the Nano RP2040 Connect. Raw 10 MHz or 16 MHz oscillator edges must
not be routed into the sparse GPIO IRQ or current PIO FIFO edge-queue path.

## RP2040 Hardware Blocks

The current implementation uses:

- one sparse edge-capture path for PPS `REF` rows on `CH1`;
- one PIO-backed counter path that counts oscillator rising edges on `CH2`;
- the RP2040 timer domain, `rp2040_timer0`, for gate boundary timestamps;
- foreground firmware service for translating completed gate observations into
  `CNT` and `STS` rows.

The count path is PIO-backed rather than the current FC0 helper because the gate
is defined by external PPS edges, not by a firmware-selected fixed gate
duration. The current firmware qualifies PPS rising edges in foreground while
preserving the sparse PPS `REF` capture path. Bench validation must still prove
PPS edge ownership, counter start/stop latency, missing-PPS timeout behavior,
and counter saturation handling before the backend is hardware-clean.

The current sparse PIO FIFO backend is not this backend. It queues low-rate
edges and attaches CPU-drain timestamps; it must not be used as a raw MHz edge
transport.

## Gate Definition

A gate starts on an accepted PPS rising edge and stops on the next accepted PPS
rising edge. The stop edge may also become the start edge for the next gate.

PPS acceptance requires:

- monotonic PPS event order;
- an interval inside configured validity limits around the expected PPS period;
- no capture overflow, edge-order fault, or debounce/glitch rejection near the
  boundary;
- startup inhibit and clean-window bookkeeping preserved as telemetry rather
  than used to suppress raw rows.

If a PPS edge is missing, stale, nonmonotonic, or implausibly early/late,
firmware must reject the affected gate for control eligibility and emit
diagnostic `STS` rows. Firmware must not invent a clean gate close timestamp.

## Native Domains

The native count domain is the oscillator observation input on `CH2`. The raw
count is the number of oscillator rising edges observed while the PPS gate is
open.

The native gate boundary timestamp domain is `rp2040_timer0` unless a future
implementation explicitly introduces a different hardware-latched timer domain
and updates the record contract. The PPS itself is the physical reference used
to define the gate, but the emitted `gate_open_ticks` and `gate_close_ticks`
remain ticks in the declared gate domain.

The host may derive a PPS-normalized oscillator ratio or frequency from these
rows. That derived value is not the raw firmware observation.

## Raw Record Contract

The backend reuses the existing `CNT` schema. No schema extension is required
for the first implementation.

For each completed PPS-to-PPS gate, firmware emits:

| `CNT` field | Value |
|---|---|
| `record_type` | `CNT` |
| `channel_id` | `2` |
| `gate_open_ticks` | accepted start PPS timestamp in `gate_domain` |
| `gate_close_ticks` | accepted stop PPS timestamp in `gate_domain` |
| `gate_domain` | `rp2040_timer0` unless revised by a later contract |
| `counted_edges` | oscillator rising-edge count during the gate |
| `source_edge` | `R` |
| `source_domain` | existing oscillator source domain, such as `h0_tcxo_16mhz` or `h1_ocxo_open_loop` |
| `flags` | raw validity/provenance flags for the count window |

The same physical PPS edges must remain visible as `REF` rows on `CH1` whenever
practical. Host analysis uses the `REF` stream to audit PPS cadence, gate
quality, startup artifacts, and any RP2040 timer-domain calibration. The `CNT`
row is not a replacement for the `REF` row.

Rows produced while startup inhibit is active are still emitted. They are raw
observations with status saying they are not control-eligible.

## Status Telemetry

The backend emits ordinary `STS` rows. New fields should use component
`pps_gate` or the existing count-observation component, while retaining current
compatibility fields where host tooling already expects them.

Required status keys:

| Component | Key | Meaning |
|---|---|---|
| `pps_gate` | `backend` | selected backend name, expected `pps_gated_ratio` |
| `pps_gate` | `state` | `idle`, `armed`, `open`, or `fault` |
| `pps_gate` | `valid` | latest bounded PPS-gated window validity |
| `pps_gate` | `last_reason` | most recent validity/fault reason |
| `pps_gate` | `ratio_available` | latest bounded window is valid and has nonzero counted edges |
| `pps_gate` | `last_interval_us` | latest accepted or rejected PPS interval in microseconds |
| `pps_gate` | `accepted_window_count` | total accepted PPS-gated windows |
| `pps_gate` | `rejected_window_count` | total rejected PPS-gated windows |
| `pps_gate` | `consecutive_bad_window_count` | consecutive invalid PPS-gated windows |
| `pps_gate` | `total_bad_window_count` | lifetime invalid PPS-gated windows in this boot |
| `pps_gate` | `missing_pps_count` | gates abandoned or withheld because no stop PPS arrived in time |
| `pps_gate` | `pps_interval_anomaly_count` | PPS intervals rejected as implausibly short, long, or nonmonotonic |
| `pps_gate` | `count_saturated_count` | oscillator counter saturation or overflow events |
| `pps_gate` | `startup_inhibit_active` | startup inhibit state for control eligibility |
| `pps_gate` | `control_eligible` | latest count/PPS gate has met control-readiness requirements |
| `fc0` | `fc0_observed_valid` | compatibility status for raw count-observation validity |
| `fc0` | `fc0_valid_for_control` | compatibility status for post-inhibit clean-window qualification |
| `fc0` | `fc0_fault` | compatibility status for post-inhibit invalid count windows |

The `fc0_*` names are historical and should not leak into the internal backend
abstraction. They remain in telemetry until host tooling and readiness docs can
be migrated to backend-generic names such as `count_observed_valid` and
`count_valid_for_control`.

## Fault Representation

Faults are represented with explicit `CNT` flags when a bounded count window can
be emitted, and with `STS` rows when no honest `CNT` row exists.

| Condition | `CNT` behavior | `STS` behavior |
|---|---|---|
| missing stop PPS | do not emit a clean `CNT`; current firmware reports `STS` only for the incomplete gate | increment `missing_pps_count`, reject the gate, set `last_reason=missing_pps` |
| PPS interval anomaly | emit affected bounded gate with `REFERENCE_VALIDITY_SUSPECT` and `GATE_INCOMPLETE` if both boundaries are known | increment `pps_interval_anomaly_count` and bad-window counters |
| count overflow or saturation | emit the row with `COUNT_SATURATED` and the best available saturated count value | increment `count_saturated_count`, reject for control |
| zero counted edges | emit `CNT` with `SOURCE_HEALTH_SUSPECT` and, when the input appears stuck low, `INPUT_STUCK_LOW` | increment bad-window counters, set `last_reason=counted_edges_zero` |
| startup inhibit active | emit `CNT` with normal raw validity flags; do not add fault flags solely because of startup | set `fc0_valid_for_control=0`, report inhibit state |
| post-inhibit invalid gate | emit raw `CNT` when bounded; flag the concrete invalidity | set `fc0_fault=1`, reset control eligibility |

Firmware should prefer explicit bad-window telemetry over suppressing rows. The
only exception is an incomplete gate with no defensible close boundary; in that
case a status fault is more honest than a fake `CNT`.

## Host-Derived Values

Host analysis derives:

- PPS interval quality from `REF` cadence and `pps_gate` status rows;
- gate duration assumptions from accepted PPS intervals and run metadata;
- oscillator ratio as counted oscillator edges per accepted PPS interval;
- oscillator frequency and ppm error from the ratio plus explicit nominal
  source metadata;
- run summaries, anomaly reports, and control-readiness summaries.

Derived frequency, ratio, phase, ppm, or calibration products must be written as
host-derived artifacts or status summaries. They must not overwrite `CNT`
fields or imply the firmware emitted calibrated frequency.

## Control-Gate Interaction

The backend may provide the raw evidence needed by a future control loop, but it
must not actuate the DAC or change control state by itself.

For compatibility with current H1 readiness logic:

- `fc0_observed_valid` maps to "the latest count observation is bounded and
  internally coherent";
- `fc0_valid_for_control` maps to "startup inhibit has expired and the required
  number of consecutive clean PPS-gated count windows has been observed";
- `fc0_fault` maps to "a post-inhibit PPS-gated count window was invalid".

Future control gates must require both PPS/reference health and oscillator-count
health. A clean count with a suspect PPS gate is not control-eligible. A clean
PPS interval with zero, saturated, or missing oscillator count is not
control-eligible.

## Compile-Time Selection

The selector is:

```cpp
#define OTIS_TCXO_COUNTER_BACKEND OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
```

This selector belongs beside the current count-observation backend choices:

- `OTIS_TCXO_COUNTER_BACKEND_FC0_GPIN0`
- `OTIS_TCXO_COUNTER_BACKEND_GPIO_IRQ`
- `OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE`
- `OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO`

It applies to count-observation modes such as `SW1_TCXO_OBSERVE` and
`H1_OCXO_OBSERVE_OPEN_LOOP`. It also requires a valid PPS input on `D14` /
GPIO26. Without PPS, firmware reports `pps_gate/missing_pps_count` and withholds
clean PPS-gated `CNT` rows.

## Implementation Checklist

- Backend selector and compile-time validation exist in `otis_config.h`.
- Count-observation logic lives in the extracted count-observation module, not
  in the `.ino` sketch.
- Current firmware uses a PIO oscillator counter and foreground PPS edge
  qualification; bench validation still needs to prove hardware-clean timing.
- Counter width, rollover, saturation, and timeout behavior are explicit in
  firmware and status telemetry.
- Keep PPS `REF` row ownership single and explicit; do not double-emit or race
  the existing capture backend.
- Emit `CNT` rows only for bounded observations with honest gate boundaries.
- Emit `STS` rows for missing PPS, PPS interval anomalies, count saturation, startup
  inhibit, control qualification, and bad-window counters.
- Preserve existing `CNT` column meanings and avoid adding calibrated frequency
  fields to firmware rows.
- Update host validation only if ordinary `STS` keys are rejected.
- Compile the default backend and the PPS-gated backend selector.
- Capture a bench run with PPS wired and oscillator input wired before marking
  the backend hardware-clean.

## Open Bench Questions

- Does foreground PPS edge qualification produce acceptable start/stop latency
  for the intended PPS-gated ratio run, or is a hardware-latched PPS gate needed?
- Should a later implementation emit a flagged partial `CNT` with a timeout
  close tick, or keep the current `STS`-only missing-stop-PPS policy?
- What PPS interval tolerances should be defaults for GPS PPS, and should they
  be compile-time constants or manifest-configured host expectations?
- How should host reports name the backend-generic replacements for historical
  `fc0_*` control-readiness fields?
