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
duration. The sparse PPS capture path is the single PPS authority: the same
captured event supplies the `REF` timestamp, PPS diagnostics, and count-gate
boundary. The count backend does not poll D14 or timestamp PPS independently.
See `PPS_OWNERSHIP_ARCHITECTURE.md`. Bench validation must still prove counter
start/stop latency, missing-PPS timeout behavior, and counter saturation
handling before the backend is hardware-clean.

The current sparse PIO FIFO backend is not this backend. It queues low-rate
edges and attaches CPU-drain timestamps; it must not be used as a raw MHz edge
transport.

## Gate Definition

A gate starts on an accepted PPS rising edge and stops on the next accepted PPS
rising edge. The stop edge may also become the start edge for the next gate.

PPS acceptance requires:

- monotonic PPS event order;
- an interval inside configured validity limits around the expected PPS period;
- a duplicate band distinct from other short intervals (currently
  `<=100000 us`);
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
| `pps_gate` | `reference_validity` | independent `valid`, `invalid`, or `unavailable` state for the authoritative PPS side |
| `pps_gate` | `reference_reason` | typed reference reason such as `reference_valid`, `reference_pps_duplicate`, `reference_pps_short_interval`, `reference_pps_long_interval`, `reference_missing_pps`, `reference_capture_flagged`, or `reference_previous_boundary_invalid` |
| `pps_gate` | `count_validity` | independent `valid`, `invalid`, or `unavailable` state for the oscillator-count side |
| `pps_gate` | `count_reason` | typed count reason such as `count_valid`, `count_zero`, `count_saturated`, or `count_unavailable` |
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
| `pps_gate` | `count_resolution_edges` | native integer count resolution; currently one edge |
| `pps_gate` | `counter_aperture_uncertainty_ns` | evidence-backed counter start/stop aperture uncertainty, or `unavailable` |
| `pps_gate` | `reference_frequency_uncertainty_ppb` | evidence-backed reference uncertainty, or `unavailable` |
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
| duplicate/short/long PPS interval | emit affected bounded gate with `REFERENCE_VALIDITY_SUSPECT` and `GATE_INCOMPLETE` if both boundaries are known | increment `pps_interval_anomaly_count`, emit the typed `reference_reason`, and increment bad-window counters |
| flagged PPS boundary | emit the bounded window when both boundaries exist, preserving the boundary flags and adding reference/gate invalidity | emit `reference_reason=reference_capture_flagged`; a flagged first boundary does not open a clean gate |
| gate following a rejected boundary | preserve the bounded `CNT`, but keep the reference side invalid for one re-anchoring window | emit `reference_reason=reference_previous_boundary_invalid`; the current clean boundary may anchor the next gate |
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

The independent `reference_validity` and `count_validity` fields are
authoritative for this distinction. `pps_gate.valid` remains a compatibility
summary and must not be used to erase either underlying conclusion.

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
- Current firmware uses a PIO oscillator counter and consumes authoritative
  foreground PPS capture events; bench validation still needs to prove
  hardware-clean counter stop/start timing.
- The PIO counter restarts immediately after the bounded stop/read operation
  and before arithmetic, diagnostics, or serial emission. This removes
  variable service-plane reporting time from the inter-gate aperture; the
  residual stop/read/restart aperture remains a bench uncertainty component.
- Counter width, rollover, saturation, and timeout behavior are explicit in
  firmware and status telemetry.
- A rollover-closing `CNT` preserves the raw authoritative `REF` timestamp as
  its close boundary; modular arithmetic is used only to compute the interval.
- A rejected duplicate/short/long/flagged boundary cannot silently become the
  accepted opening boundary of a clean ratio window. The next bounded window
  remains visible but reference-ineligible while the gate re-anchors.
- Absence of the first PPS after backend start is subject to the same explicit
  missing-PPS timeout as an incomplete open gate.
- Keep the sparse capture event authoritative for PPS `REF`, diagnostics, and
  gated counting; do not poll or timestamp D14 again in a consumer.
- Emit `CNT` rows only for bounded observations with honest gate boundaries.
- Emit `STS` rows for missing PPS, PPS interval anomalies, count saturation, startup
  inhibit, control qualification, and bad-window counters.
- Preserve existing `CNT` column meanings and avoid adding calibrated frequency
  fields to firmware rows.
- Update host validation only if ordinary `STS` keys are rejected.
- Compile the default backend and the PPS-gated backend selector.
- Capture a bench run with PPS wired and oscillator input wired before marking
  the backend hardware-clean.
- Populate aperture and reference uncertainty only from bench/calibration
  evidence; until then the components remain `unavailable`.

## Open Bench Questions

- Does foreground processing of the captured PPS event produce acceptable
  counter start/stop latency for the intended ratio run, or is a
  hardware-latched PPS gate needed?
- Should a later implementation emit a flagged partial `CNT` with a timeout
  close tick, or keep the current `STS`-only missing-stop-PPS policy?
- What PPS interval tolerances should be defaults for GPS PPS, and should they
  be compile-time constants or manifest-configured host expectations?
- How should host reports name the backend-generic replacements for historical
  `fc0_*` control-readiness fields?
