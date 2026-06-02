# Count Observation Measurement Contract

## Scope

This document defines the measurement contract shared by OTIS firmware, host
validation, reports, and future analysis for `CNT` count-observation rows.

It covers the Arduino Nano RP2040 Connect count backends selected with
`OTIS_TCXO_COUNTER_BACKEND`:

- `OTIS_TCXO_COUNTER_BACKEND_FC0_GPIN0`
- `OTIS_TCXO_COUNTER_BACKEND_GPIO_IRQ`
- `OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE`
- `OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO`

## Stable `CNT` Meaning

Every `CNT` row means:

```text
Between gate_open_ticks and gate_close_ticks in gate_domain,
firmware counted counted_edges edges from source_domain/source_edge.
```

`CNT` does not mean:

- calibrated oscillator frequency;
- PPS-disciplined frequency;
- control-loop error;
- DAC correction;
- lock state;
- host-qualified fixture validity.

Host reports may derive frequency, ratio, ppm, stability, and control-readiness
summaries from `CNT`, `REF`, `STS`, manifest domains, and run metadata. Those
derived products must remain explicit and replayable.

## Backend Matrix

| Backend | Gate source | Count source | Native raw value | Required provenance |
|---|---|---|---|---|
| `FC0_GPIN0` | firmware gate over `rp2040_timer0` | RP2040 FC0/GPIN0 on `D8` / GPIO20 | accumulated FC0 frequency samples converted to counted edges over the emitted gate | `TIMESTAMP_RECONSTRUCTED`; `fc0` status for samples and validity |
| `GPIO_IRQ` | firmware `micros()` gate | divided, interrupt-safe oscillator test input | software IRQ edge count | divided-only warning; not valid for raw MHz oscillator input |
| `PIO_LONG_GATE` | firmware gate over `rp2040_timer0` | PIO oscillator edge counter on `D8` / GPIO20 | raw PIO-counted rising edges | `TIMESTAMP_RECONSTRUCTED`; long-gate status |
| `PPS_GATED_RATIO` | accepted PPS rising edges on `D14` / GPIO26 | PIO oscillator edge counter on `D8` / GPIO20 | raw oscillator rising edges between accepted PPS edges | PPS `REF` rows plus `pps_gate` status; `TIMESTAMP_RECONSTRUCTED` in the current implementation |

The backend changes how the gate and count are produced. It does not change the
column semantics of `count_observations_v1.csv`.

## Raw vs Derived

Firmware emits raw observation fields:

- `gate_open_ticks`
- `gate_close_ticks`
- `gate_domain`
- `counted_edges`
- `source_edge`
- `source_domain`
- `flags`

Host tooling derives:

- gate duration in seconds;
- observed frequency in hertz;
- PPS-gated oscillator ratio;
- ppm error versus nominal source frequency;
- warmup and clean-window summaries;
- H1 sweep and characterization metrics.

Host report fields such as `mean_observed_frequency_hz` are derived from raw
`CNT` windows and manifest domain metadata. They are not firmware-emitted
fields.

## Invalid Windows

Invalid count windows are preserved whenever a bounded gate exists. Firmware
emits the `CNT` row with flags and emits diagnostic `STS` rows.

Common invalid-window flags:

- `TIMESTAMP_RECONSTRUCTED`
- `REFERENCE_VALIDITY_SUSPECT`
- `SOURCE_HEALTH_SUSPECT`
- `INPUT_STUCK_LOW`
- `GATE_INCOMPLETE`
- `COUNT_SATURATED`

Startup inhibit is not a reason to suppress a raw row. During startup, rows stay
visible while `STS` telemetry reports that they are not control-eligible.

When no honest close boundary exists, firmware should not fabricate a clean
`CNT`. The PPS-gated backend reports a missing stop PPS with `STS` telemetry and
does not emit a clean count row for that incomplete gate.

## PPS-Gated Ratio Contract

For `OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO`:

- PPS on `CH1` remains visible as `REF` rows.
- Oscillator observation stays on `CH2` as `CNT` rows.
- `gate_open_ticks` and `gate_close_ticks` are accepted PPS edge timestamps in
  `rp2040_timer0`.
- `counted_edges` is the oscillator rising-edge count between those PPS edges.
- `ratio_available=true` means the bounded row is valid and has nonzero counted
  edges; the ratio itself is still host-derived.
- PPS interval anomalies are emitted as `pps_gate/pps_interval_anomaly_count`
  and flagged with `REFERENCE_VALIDITY_SUSPECT` plus `GATE_INCOMPLETE`.
- Missing stop PPS increments `pps_gate/missing_pps_count` and withholds a clean
  `CNT` row for that gate.
- Counter saturation increments `pps_gate/count_saturated_count` and flags the
  bounded row with `COUNT_SATURATED`.

The current firmware implementation qualifies PPS rising edges in foreground
while preserving the existing sparse PPS `REF` capture path. PPS-gated `CNT`
rows therefore carry reconstructed `rp2040_timer0` gate timestamps until a later
hardware-latched gate implementation proves a stronger timing contract.

## Compatibility Notes

Historical H0/H1 runs that report only `fc0` status remain valid. The `fc0_*`
status keys are retained for host compatibility:

- `fc0_observed_valid`
- `fc0_valid_for_control`
- `fc0_fault`

New PPS-gated runs additionally emit `pps_gate` status keys. Host tooling should
parse them as ordinary `STS` rows and should not require a schema revision.

Future cleanup may add backend-generic control-readiness names, but it must not
rename or reinterpret historical `fc0_*` fields without an explicit migration.
