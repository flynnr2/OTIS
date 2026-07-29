# run_020 Operator Checklist

## Before Arduino IDE Upload

- [ ] Open `firmware/arduino/otis_nano_rp2040_connect/otis_nano_rp2040_connect.ino`.
- [ ] Select **Arduino Nano RP2040 Connect** and the correct USB port.
- [ ] Confirm `otis_config.h` contains the complete Run 020 configuration
      shown in `command_checklist.md`; do not add build flags.
- [ ] Confirm D14 PPS, D10 witness, D8/GPIN0 oscillator input, DAC/CX317
      control path, enclosure, and airflow state.
- [ ] Use the Arduino IDE to **Verify**, then **Upload**.
- [ ] Close the IDE Serial Monitor and Serial Plotter before capture starts.

## Before Starting the Sweep

- [ ] `capture_device` is the sole serial owner and its raw log is growing.
- [ ] Start preflight after capture; it waits through the 600 s inhibit and
      clean 300 s windows while keeping the sweep stopped.
- [ ] The automated Run 020 preflight prints `RUN 020 PREFLIGHT PASSED`.
- [ ] It reports the exact profile:
      `AE00,B100,AE00,AB00,AE00,B400,AE00,A800,AE00`.
- [ ] Environmental telemetry is present.
- [ ] No capture, PPS, FC0, DAC, or observer fault is present.

Do not bypass a failed preflight. Diagnose the mismatch, upload again from the
IDE if necessary, and rerun preflight.

## Stop Conditions

Interrupt the sequence terminal. Its `finally` handler sends `SWEEP STOP` and
restores `0x8000`. Verify restoration manually if the process or USB link fails.
Stop for:

- missing, invalid, zero, or saturated count windows;
- D14/D10 disagreement or PPS cadence faults;
- capture reconnects, parser errors, dropped records, or overflow;
- unexpected firmware reboot;
- loss of oscillator output or abnormal control voltage/current/temperature;
- a raw log that stops growing.

## Handoff Values

Highest settled code below 10 MHz:

Lowest settled code above 10 MHz:

Interpolated crossing code and uncertainty:

Local slope and directionality:

Repeated-centre drift/hysteresis:

Settling conclusion:

Temperature range and drift:

Anomalies and excluded windows:

Final `0x8000` restoration confirmed:

Recommended plant-model applicability:
