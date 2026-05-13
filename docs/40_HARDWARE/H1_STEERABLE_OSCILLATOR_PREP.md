# H1 Steerable Oscillator Prep

H1 is hardware bring-up and open-loop characterization of a steerable oscillator
path. It does not require the SW2 GPSDO control loop to exist.

The purpose of H1 is to make the oscillator, DAC, conditioning, observation, and
run-artifact boundaries explicit before OTIS starts closed-loop disciplining. H1
should prove that the hardware can be powered, observed, and adjusted manually in
a repeatable way while preserving the H0 capture semantics.

SW2 should not begin until the oscillator output can be observed repeatably, the
DAC output can be commanded safely, and open-loop tuning sensitivity has been
characterized.

## Relationship To H0

H0 proves the capture architecture:

- RP2040 capture against explicit timing domains;
- GPS PPS and generic pulse observation;
- TCXO or oscillator-under-test count observations;
- host-side validation, replay, and reporting.

H1 keeps those capture contracts intact and adds the first steerable oscillator
hardware path:

- a precision DAC output that can be manually set within documented limits;
- an OCXO, VCOCXO, VCXO, or similar controllable oscillator module;
- conditioning that converts the oscillator output into RP2040-safe observation
  signals;
- metadata that records the measured control path instead of assuming it.

H1 is not a firmware-control stage. It should not change PIO, DMA, interrupt
priority, timestamp semantics, or host replay meaning merely because a better
oscillator has been connected.

## Entry Criteria

Before starting H1 bench work:

- H0/SW1 or SW1.5 capture paths can record PPS and oscillator/count observations
  with known channel and domain provenance;
- the RP2040 observation pin and conditioning assumptions are documented;
- the candidate oscillator module has a documented or measured pinout before it
  is powered;
- the candidate DAC board has documented supply, reference, bus, and output
  limits;
- safe bench power limits, grounding, and measurement points are written down;
- a run manifest can describe the oscillator, DAC, conditioning, and safety
  limits without requiring SW2 loop fields.

## Exit Criteria

H1 is complete enough to unblock SW2 planning when:

- oscillator power rails have been verified unloaded and loaded;
- oscillator output amplitude and output type are known at the measurement point;
- the oscillator output can be observed by OTIS repeatably through the intended
  conditioning path;
- the DAC is visible on its control bus and its unloaded output range has been
  measured;
- any connected DAC-to-control-input range has documented safe limits;
- one or more free-running observation runs have been captured;
- small manual DAC steps have been captured with settling notes;
- approximate tuning sensitivity has been estimated in Hz/V or ppm/V;
- warm-up behavior and short-term stability have at least one representative
  observation run;
- unknowns, anomalies, and unsafe operating regions are recorded in run notes.

## Candidate Hardware Roles

H1 should document roles rather than assume a fixed bill of materials.

| Role | Candidate examples | H1 requirement |
|---|---|---|
| DAC | AD5693R, AD5683R, or similar precision integrated-reference breakout | manual output command path with measured output range |
| Oscillator | surplus OCXO, VCOCXO, VCXO, XCXO module, or evaluation board | known pinout and control-input documentation before connection |
| Control network | resistor scaling, filtering, output protection, buffer if needed | measured voltage at the oscillator control input |
| Output conditioning | comparator, logic buffer, divider, squarer, or clock buffer | RP2040-safe logic at the observation pin |
| Observation path | RP2040 GPIO/PIO count path or CLOCK GPIN0 where appropriate | repeatable count or edge observations with domain provenance |

The module pinout, supply voltage, output type, control-voltage range, and tuning
slope must be treated as unknown until documented from the module source or
measured safely on the bench.

## DAC And Oscillator Interface Assumptions

H1 may assume only the following generic interface shape:

```text
manual DAC command
  -> measured DAC output voltage
  -> documented protection/scaling/filter network
  -> oscillator control input
  -> measured oscillator frequency/output behavior
  -> RP2040-safe observation path
```

Do not assume:

- a universal OCXO pinout;
- a universal control-voltage range;
- a linear tuning slope across the whole range;
- that the DAC full-scale range is safe for the oscillator control input;
- that the oscillator output is directly GPIO-compatible;
- that breadboard wiring is adequate for final noise or stability conclusions.

The first useful H1 measurements are the safe operating envelope and the
open-loop response, not closed-loop lock performance.

## Power, Grounding, And Decoupling

Document power as measured bench behavior:

- verify each rail unloaded before connecting the oscillator module;
- set bench-supply current limits before first power-up;
- record nominal and measured supply voltages;
- record whether analog and digital supplies are shared or separated;
- place local decoupling close to oscillator and DAC supply pins where the
  breakout/module documentation requires it;
- keep control-voltage wiring short and referenced to the same ground as the
  oscillator control input;
- record warm-up current and thermal behavior qualitatively unless proper
  instrumentation is available.

Do not make safety-critical claims about surplus modules or power supplies.
Document the observed setup and the limits used for that setup.

## Buffer And Conditioning Considerations

The RP2040 observation input must see GPIO-safe logic:

- 3.3 V-compatible logic at the RP2040 pin;
- no raw sine, high-voltage logic, or unspecified module output directly into
  GPIO;
- explicit divider, comparator, squarer, or buffer choice when the oscillator
  output is not already compatible;
- documented inversion, division ratio, and threshold assumptions;
- common ground between oscillator hardware and the RP2040 capture board.

For early H1 bring-up, a divided or buffered oscillator output is acceptable if
it makes observation safer and more repeatable. Record the observed domain name
and nominal frequency in the manifest.

## Open-Loop Characterization Checklist

- [ ] Verify power rails unloaded.
- [ ] Verify DAC I2C presence.
- [ ] Verify DAC output range unloaded.
- [ ] Verify DAC output range connected to oscillator control input, if safe.
- [ ] Verify oscillator output amplitude and logic conditioning.
- [ ] Verify RP2040 can observe oscillator output.
- [ ] Capture free-running oscillator observation run.
- [ ] Step DAC manually through small safe increments.
- [ ] Capture frequency response after each step.
- [ ] Estimate Hz/V or ppm/V sensitivity.
- [ ] Check warm-up behavior.
- [ ] Check short-term stability.
- [ ] Document module pinout and measured voltages.

## Run Artifacts

Future H1 runs should follow the existing `runs/` artifact pattern: raw serial
logs, parsed CSVs, manifest, notes, validation output, summaries, plots when
useful, and regeneratable derived files.

Suggested future run categories:

```text
runs/h1_open_loop/free_run/run_001
runs/h1_open_loop/dac_step/run_001
runs/h1_open_loop/warmup/run_001
runs/h1_open_loop/holdover_observe/run_001
```

Expected notes for each H1 run:

- oscillator module identity and pinout source;
- supply voltages and current limits;
- DAC part, reference, bus address, and measured output voltage;
- control-network description and measured control-input voltage;
- conditioning path and logic level at the RP2040 pin;
- capture firmware mode and whether it is SW1/SW1.5 observation-only firmware;
- manual DAC command sequence, if any;
- warm-up duration before capture;
- anomalies, dropouts, unlocks, clipping, or unsafe regions.

## Suggested Manifest Fields

Adapt these fields to the existing `manifest.json` conventions when real H1
templates are created. Null and empty values mean "unknown or not yet measured",
not "safe by default".

```json
{
  "h_phase": "H1",
  "stage": "open_loop",
  "oscillator": {
    "part": "",
    "nominal_frequency_hz": 10000000,
    "output_type": "",
    "supply_voltage_v": null,
    "control_voltage_range_v": null,
    "known_pinout_source": ""
  },
  "dac": {
    "part": "",
    "resolution_bits": null,
    "reference_voltage_v": null,
    "i2c_address": ""
  },
  "conditioning": {
    "buffer": "",
    "logic_voltage_v": null,
    "notes": ""
  },
  "safety_limits": {
    "dac_min_code": null,
    "dac_max_code": null,
    "control_voltage_min_v": null,
    "control_voltage_max_v": null
  }
}
```

Recommended additional H1 run fields when useful:

```json
{
  "capture_type": "free_run",
  "control_mode": "manual_open_loop",
  "control_sequence": "",
  "warmup_seconds_before_capture": null,
  "measured_tuning_sensitivity_hz_per_v": null,
  "measured_tuning_sensitivity_ppm_per_v": null,
  "observation_domain": {
    "name": "",
    "nominal_hz": null,
    "division_ratio": null
  }
}
```

## Deferred To SW2

The following remain out of scope for H1:

- GPSDO discipline loop firmware;
- automatic DAC steering;
- lock-state machinery;
- holdover policy;
- loop filter implementation;
- gain scheduling;
- oscillator-control telemetry beyond manual command and measurement records;
- firmware changes that imply tested DAC or oscillator support before hardware
  exists.

H1 may create documentation, run templates, and manifest guidance. It should not
add production DAC drivers or control-loop code unless a later task has real
hardware, isolated hardware-abstraction tests, and explicit scope for that work.

## Future Codex Tasks

These are future prompts, not H1 implementation requirements:

- DAC driver bring-up against the selected breakout;
- DAC manual set command with safety limits and logging;
- oscillator frequency observation report for H1 runs;
- DAC step-response analyzer for open-loop captures;
- SW2 control-loop telemetry design.
