# OTIS Nano RP2040 Connect Firmware

This sketch builds one production image: `adaptive_hybrid_regulation`, version
`OTIS_ADAPTIVE_HYBRID_REGULATION_V1`. It is a fixed instrument configuration,
not a firmware profile matrix.

## Build

From the repository root:

```bash
.venv/bin/python tools/build_firmware.py
```

The builder consumes `firmware/arduino/firmware_build_manifest.json`, verifies
the pinned Arduino CLI, board core, compiler, installed-byte hashes, exact
source identity and Git state, required binary markers, and memory budget, then writes
ignored artifacts under `build/`.

There is no profile selector or compatibility build. Historical images must be
reproduced from their recorded Git revision.

## Fixed topology

| Signal | Pin/channel | Current role |
|---|---|---|
| D14 | GPIO26 / CH1 | sole authoritative PPS/reference input |
| D8 | GPIO20 / CH2 | oscillator count input; sole regulation measurement |
| D10 | GPIO5 / CH0 | reserved optional external-event evidence input |
| D9 | GPIO21 | forwarded oscillator clock output |
| D6 | GPIO18 / CH3 | fail-local forwarded-clock diagnostic monitor |
| GNSS RX/TX | GPIO1/GPIO0 | receiver metadata and bounded configuration |

D10 is never a PPS witness and cannot affect reference validity, setup
authority, regulation eligibility, actuation, or a run terminal. Its channel
and resource seams are preserved, but this image does not claim an implemented
or safely isolated D10 capture backend. The build manifest records
`status: not_implemented` and `isolation_claimed: false`.

## Timing path

D14 edges are timestamped from the RP2040 monotonic microsecond counter and
published as compact reference observations. The qualified PIO/DMA snapshot
backend continuously counts D8 oscillator edges and snapshots the cumulative
down-counter at D14 boundaries. Core1 services hardware capture and publishes
bounded messages; Core0 is the sole serial owner and emits canonical records.

The CPU does not define timestamps. Queueing, logging, USB, and host scheduling
remain outside timing truth.

## Regulation

The fixed image contains the current PPS-gated frequency estimator, adaptive
FLL/PLL policy, persistent tagged correction debt, exact transaction identity,
bounded AD5693R actuation, and post-application response tracking. The fixed
actuator envelope is `0xA800..0xAB00`.

The active policy ID is `OTIS_ADAPTIVE_HYBRID_REGULATION_V1`; the estimator ID
is `OTIS_PPS_GATED_FREQUENCY_ESTIMATOR_V1`; the active-status contract is
`adaptive_hybrid_active_status_snapshot_v1`. Run duration and campaign stop
conditions are supplied by the frozen host run manifest.

## GNSS behavior

The receiver uses the fixed bounded 115200-baud operational path. Serial
metadata qualifies the receiver that supplies D14 PPS; it never replaces D14.
A recoverable stale, missing, malformed, or checksum-unqualified metadata
condition holds new corrections at the last confirmed DAC code while D14/D8
capture and evidence continue. Fresh causal qualification is required before
regulation resumes.

## Diagnostics and evidence

D9 forwarding and D6 monitoring are always present in the fixed image. D6 is
diagnostic-only and fail-local. Canonical raw observations, derived estimates,
requested/applied controls, acknowledgements, policy and estimator identity,
and resulting state are emitted separately so host replay can reconstruct each
decision without overwriting source evidence.

## Verification

```bash
.venv/bin/python firmware/arduino/validation/scripts/run_no_hardware_checks.py --tier fast
.venv/bin/python firmware/arduino/validation/scripts/run_no_hardware_checks.py --tier campaign
.venv/bin/python firmware/arduino/validation/scripts/run_no_hardware_checks.py --tier release
```

All three tiers are no-hardware checks and build the same fixed image. See
`firmware/arduino/validation/END_TO_END_VALIDATION_PLAN.md` for the rehearsal
and bench boundary.
