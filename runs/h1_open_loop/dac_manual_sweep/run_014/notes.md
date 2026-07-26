# H1 Open-Loop Run Notes

Run ID: `run_014`

Purpose: characterize the CX317 while powered through the new dirty-to-clean
power path. This is an open-loop manual DAC sweep only; do not enable automatic
DAC steering or treat the result as closed-loop GPSDO behavior.

## Purpose

Capture manually commanded DAC steps and the CX317 frequency response with the
new supply path in place. Compare primarily against `run_013` for:

- CNT valid-window fraction after startup inhibit;
- dropped records and `error_flags`;
- PPS interval sanity;
- repeatable DAC response sign and magnitude;
- supply-related warmup, ripple, noise, or dropout behavior.

## Hardware Setup

Record oscillator identity, DAC part/address/reference, control network,
reference source, RP2040 observation pin, and whether the FC0 observation path
matches `run_013`.

Record the dirty-to-clean power path exactly:

- dirty supply source and voltage before filtering/regulation;
- clean CX317 supply node and voltage at the oscillator pins;
- filter/regulator/isolator parts and values;
- grounding and return-current path;
- measured ripple/noise on dirty and clean nodes, including scope bandwidth;
- startup sequencing and any visible supply dip during DAC commands;
- whether the wiring is temporary, soldered, breadboarded, or clip-leaded.

## Safety Limits

Keep the same conservative DAC range unless a bench measurement shows otherwise:

- minimum DAC code: `0x7000`;
- nominal DAC code: `0x8000`;
- maximum DAC code: `0x9000`;
- expected connected `Vc` range from prior runs: about 1.091 V to 1.401 V.

Before starting the sweep, verify:

- clean CX317 supply voltage is within the part's safe operating range;
- CX317 supply current and package temperature are sane after warmup;
- control voltage at CX317 pin 4 remains inside the measured safe range;
- RP2040 GPIN0 input remains within 0 V to 3.3 V with no unsafe overshoot.

## Capture Command

Record the exact host command used for capture and the sweep command sequence,
including `SWEEP LOAD`, `SWEEP START`, and any `SWEEP STOP` or manual
`SWEEP STEP` actions.

Planned capture command:

```text
caffeinate -dimsu python3 -m host.otis_tools.capture_device \
  --auto-detect \
  --baud 115200 \
  --run-dir runs/h1_open_loop/dac_manual_sweep/run_014 \
  --command-fifo runs/h1_open_loop/dac_manual_sweep/run_014/control/commands.fifo
```

Planned repeat command:

```text
caffeinate -dimsu python3 -m host.otis_tools.h1_endpoint_repeat \
  --fifo runs/h1_open_loop/dac_manual_sweep/run_014/control/commands.fifo \
  --raw-log runs/h1_open_loop/dac_manual_sweep/run_014/raw/serial.log \
  --profile SLOPE_CENTER_EDGE_300S \
  --passes 18
```

Suggested sequence:

1. Power the CX317 through the new dirty-to-clean path and let it reach the
   intended warmup point.
2. Start capture into this run directory.
3. Observe at `0x8000` long enough to confirm clean CNT, REF, and STS rows.
4. Step `0x8000 -> 0x7000 -> 0x8000 -> 0x9000 -> 0x8000`.
5. Stop early if CNT windows become invalid, supply behavior is unsafe, or the
   clean node shows dropout/ripple inconsistent with the experiment.
6. Leave all control open-loop.

## Observations

Record each DAC code, measured DAC output, measured control voltage, dwell time,
frequency estimate, and settling behavior. Cross-check `csv/dac_steps.csv` for
`dwell_start`, `fc0_window`, and `dwell_complete` attribution.

Also record supply observations at each major step:

- dirty supply voltage;
- clean CX317 supply voltage;
- clean-node ripple/noise;
- CX317 current or temperature if measured;
- visible coupling between DAC steps and the clean supply.

## Anomalies

Record unsafe voltages, non-monotonic response, output dropouts, conditioning
failures, dropped records, host-side interruptions, USB reconnects, or any
supply transient caused by the new dirty-to-clean path.

## Follow-up

If the new power path materially improves CNT validity or frequency stability,
use `run_014` as the first baseline for the revised CX317 supply topology. If it
does not improve the data, keep power-path effects separate from remaining
gate-formation, wiring, firmware timing, or oscillator-output assumptions before
deriving ppm/V or choosing later SW2 control limits.

## Closeout

The post-G17-fix capture is the clean plant-fit evidence for this run. The
pre-fix capture remains under `derived/pre_g17_fix_capture_2026-07-25/` as
separate negative hardware evidence and must not be merged into the clean fit.

`csv/ref.csv` contains 2719 short REF/PPS intervals. They are not startup-only:
capture begins around firmware uptime 691 s, while the anomalous interval span
runs from about 744.812 s to 1916.805 s elapsed. The anomalies are early
relative to the full capture and no short interval is seen after that span, but
current telemetry cannot distinguish reference-source behavior from GPIO,
capture hardware, IRQ/FIFO/DMA, or firmware-path extra-edge causes.

Conclusion: the PPS/reference anomaly is explicitly gated in `manifest.json` as
diagnostic-only unresolved evidence. Affected REF/PPS windows are not
control-eligible. The clean count path remains usable for open-loop plant
characterization, but this run does not authorize active SW2 DAC actuation.
