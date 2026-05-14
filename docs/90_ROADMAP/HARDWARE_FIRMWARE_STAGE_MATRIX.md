# Hardware / Firmware / Host Stage Matrix

## Naming Rule

OTIS uses separate stage prefixes:

- `F`: foundations and documentation;
- `H`: hardware configurations;
- `SW`: software, firmware, and host tooling;
- `A`: analysis capability.

This avoids using `Stage 1` to mean different things in hardware, firmware, and roadmap documents.

## Current Matrix

| Stage  | Name                          | Description                                                                                     | Status          |
|--------|-------------------------------|-------------------------------------------------------------------------------------------------|-----------------|
| `F0`   | Foundation                    | architecture, terminology, contracts, design principles                                         | active          |
| `H0`   | Prototype capture hardware    | RP2040 + Adafruit Ultimate GPS PPS + ECS-TXO-5032-160-TR 16 MHz TCXO + conditioning experiments | complete enough |
| `SW0`  | Host scaffold/contracts       | validation, replay, examples, schema fixtures                                                   | healthy         |
| `SW1`  | First capture firmware        | emit `EVT`, `REF`, `CNT`, and `STS` from Arduino Nano RP2040 Connect via Arduino-Pico           | complete        |
| `SW1.5a` | PIO sparse-edge validation  | PIO FIFO observation for sparse event edges while high-rate oscillator observation remains on FC0 | complete enough |
| `A0`   | Basic replay/report           | validate runs and derive simple intervals/frequency estimates                                   | active/usable   |
| `H1`   | Steerable oscillator prep     | open-loop XCXO/OCXO + DAC steering-path bring-up before SW2 control-loop firmware               | unblocked       |
| `SW2`  | Control-loop firmware         | explicit GPSDO/discipline-loop telemetry and control                                            | not started; appropriately deferred |

## Validated H0/SW1 State

H0/SW1 is complete enough for the next hardware phase. The non-PIO H0/SW1 path
is healthy, and the SW1.5a PIO FIFO sparse-edge path has passed the pragmatic
TCXO-observe validation run.

Evidence:

- run path: `runs/h0_sw1_5a_pio/tcxo_observe/run_001`;
- manifest commit: `4cb0fc8088cbc36eeaa0e52e5c4661b86b738aca`;
- validation command: `python3 -m host.otis_tools.validate_run runs/h0_sw1_5a_pio/tcxo_observe/run_001`;
- validation output: `OK raw_events.csv: 141 rows`, `OK count_observations.csv: 141 rows`, `OK health.csv: 1128 rows`;
- `COMPLETE` marker: present.

The validated split is:

```text
Sparse event capture -> PIO FIFO path
High-rate oscillator observation -> GPIN0/FC0 gated-count path
```

The Arduino Nano RP2040 Connect firmware target for SW1 is the
Earle Philhower `arduino-pico` core, not Arduino Mbed OS Nano Boards. This keeps
the Arduino entrypoint while preserving access to Pico SDK, multicore, and PIO
facilities needed by the timing-fabric stages.

Observation boundary for H0/SW1.5a:

| Signal class | Backend |
|---|---|
| Sparse edges such as GPS PPS, slow GPIO loopback, and future low-rate events | PIO FIFO edge backend |
| Raw CXO on `D8` / `GPIO20` / `GPIN0`, including 10 MHz / 16 MHz TCXO/OCXO/XCXO inputs | RP2040 FC0 / gated-count backend |

PIO FIFO is for sparse event observation only: PPS, GPIO loopback, and future
low-rate event edges. Raw TCXO/OCXO input on `D8` / `GPIO20` / `GPIN0` must use
FC0/gated-count style observation, not PIO FIFO edge logging.

The standalone Pico SDK scaffold is deprecated and archived under
`firmware/deprecated/rp2040_pico_sdk/` for reference only. New SW1 firmware work
belongs in `firmware/arduino/otis_nano_rp2040_connect/`.

H1 remains a hardware-prep and open-loop characterization stage. Its preparation
package lives in `docs/40_HARDWARE/H1_STEERABLE_OSCILLATOR_PREP.md`; SW2 should
not begin until the oscillator output, manual DAC command path, and open-loop
tuning sensitivity have been characterized from real hardware.

The intended H1 sequence is:

1. Verify OCXO power, current, warmup, and output level.
2. Verify DAC I2C communication and output voltage range.
3. Connect OCXO output to `D8` / `GPIO20` / `GPIN0` through the appropriate conditioning path.
4. Capture free-running OCXO count observations via FC0/GPIN0.
5. Manually step DAC output.
6. Measure frequency/count response versus DAC setting.
7. Estimate Hz/V and ppm/V.
8. Characterize settling time and thermal behavior.
9. Only then design SW2 discipline/control-loop firmware.
