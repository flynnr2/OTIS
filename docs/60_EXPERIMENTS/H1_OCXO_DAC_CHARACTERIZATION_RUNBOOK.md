# H1 OCXO/DAC Characterization Runbook

H1 is open-loop bench characterization of the OCXO, DAC, control path, and
observation path. It is not SW2, and it must not enable automatic DAC steering,
PI/PID control, holdover, or closed-loop GPSDO behavior.

## Bench Preconditions

- Use observation-only firmware with the existing OTIS capture semantics.
- Confirm the oscillator pinout from a datasheet, module marking source, or
  measured continuity notes before power is applied.
- Set bench-supply voltage and current limits before connecting the OCXO.
- Keep the DAC output disconnected from the OCXO tune input until the DAC output
  range and safe tune range are both documented.
- Record unknown values as explicit nulls or empty fields in the run manifest;
  do not infer safety from missing data.

## 1. OCXO Power, Current, And Warm-Up

1. Verify each power rail unloaded.
2. Set current limits for first power-up.
3. Power the OCXO and record initial current, warm current, supply voltage, and
   qualitative thermal behavior.
4. Confirm the oscillator output exists at the measurement point before routing
   it toward OTIS.
5. Initialize a run from `ocxo_power_warmup/_template` and record warm-up notes.

## 2. DAC I2C And Voltage Verification

1. Verify DAC supply and reference voltage.
2. Confirm the AD5693R appears at I2C address `0x4C`.
3. Measure DAC output at minimum, midpoint, and maximum intended codes while
   unloaded.
4. Record gain mode, reference voltage, measured output minimum, and measured
   output maximum.
5. Stop if the measured output can exceed the intended OCXO tune range.

## 3. Safe DAC-To-OCXO Tune Connection

1. Define `dac_min_code`, `dac_max_code`, `control_voltage_min_v`, and
   `control_voltage_max_v` before connection.
2. Add any required divider, resistor isolation, RC filter, clamp, or buffer.
3. Connect the DAC to the OCXO tune input only after the connected control
   voltage is measured inside the safe range.
4. Record the control network and measured control voltage in the manifest.

## 4. OCXO Output Conditioning Into GPIN0/FC0

1. Do not connect raw sine, high-voltage logic, or unknown oscillator outputs to
   the RP2040.
2. Use a divider, comparator, squarer, clock buffer, or other documented
   conditioner to produce RP2040-safe logic.
3. Verify logic high/low levels before connecting `D8/GPIO20/GPIN0`.
4. Record conditioner type, logic voltage, inversion, division ratio, and the
   observed domain name.

## 5. Free-Run Capture

1. Allow the OCXO to warm up for the recorded duration.
2. Keep the tune voltage fixed or disconnected, and record which state is used.
3. Initialize an `ocxo_free_run` run and capture count/reference observations.
4. Report frequency offset, missing reference data, dropouts, and anomalies.

## 6. Manual DAC Sweep

1. Use only the documented safe DAC code range.
2. Step manually in small increments with a recorded dwell time.
3. For each step, record DAC code, measured DAC output, measured control voltage,
   timestamp, and observed frequency estimate.
4. Stop the sweep immediately if the output disappears, clips, or approaches a
   safety limit.

## 7. ppm/V Derivation

1. Use measured control voltage at the OCXO tune input, not only requested DAC
   code.
2. Derive Hz/V from settled frequency observations over the local sweep range.
3. Convert to ppm/V using the measured or nominal oscillator frequency.
4. Record the valid voltage interval and do not assume the slope applies outside
   that interval.

## 8. Settling And Thermal Runs

1. Use `settling_thermal` runs for long dwell, step-settling, warm-up, or
   deliberate thermal observations.
2. Record ambient notes, airflow changes, enclosure state, power changes, and
   manual DAC events with timestamps.
3. Keep the run open-loop: frequency is observed and documented, not corrected
   automatically.

## Closeout

- Commit representative run artifacts only after validation and summary reports
  have been generated.
- Keep large raw logs and plots only when they explain behavior that cannot be
  reconstructed.
- Record unsafe regions and unresolved hardware questions in `notes.md`.
- Do not add closed-loop control concepts, firmware steering, PI/PID state, or
  holdover behavior as part of H1 characterization.
