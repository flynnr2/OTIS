# Phase 5 PPS-Gated Backend Bench Runbook

## Purpose and gate

This runbook produces the bench evidence needed to decide whether
`OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO` is qualified metrology. It does not
authorize DAC steering. Throughout this procedure:

```text
status.control_ready=false
status.actuation_enabled=false
PPS/count-derived DAC writes are prohibited
```

Do not start the qualification capture until the Phase 4 EST/CTL/diagnostic
contracts are merged into the target branch. Repository preparation and
synthetic checks may run earlier, but they cannot pass the Phase 5 exit gate.

## Applicability and fixed acceptance profile

The v1 profile is
`profiles/qualification/pps_gated_ratio_v1.json`. It applies to:

- a conditioned 10 MHz CX317 observation on `D8` / GPIO20;
- one authoritative conditioned PPS on `D14` / GPIO26;
- the IRQ reference-capture authority and PIO PPS-gated count backend;
- a nominal one-second PPS interval, accepted over `0.8..1.2 s`;
- duplicate classification at `<=0.1 s`;
- a missing-PPS timeout of `2.5 s`;
- the repaired H1 oscillator/front-end topology;
- observe-only operation.

The fixed v1 acceptance thresholds are:

| Check | Threshold |
|---|---:|
| Stable measurement-eligible duration after warmup selection | at least 3600 s |
| Measurement-eligible PPS-gated windows | at least 3600 |
| Raw `CNT` boundaries traceable to adjacent authoritative `REF` rows | 100% |
| Candidate population jitter | no more than 1.5 Hz per one-second window |
| Absolute mean bias against independent metrology | no more than 0.05 Hz |
| Baseline-to-service-load mean shift | no more than 0.05 Hz |
| Baseline and service-load segment size | at least 600 eligible windows in every declared segment |
| Required safe bench faults | all detected with the specified reason and inhibition |
| Required uncertainty components | all available and evidence-backed |

The 0.05 Hz comparison bound is 5 parts in \(10^9\) at 10 MHz and is below the
smallest Run 020 plant-response scale used for preview decisions. The 1.5 Hz
single-window jitter bound permits integer-edge aperture variation while still
detecting unexplained multi-edge service latency. These are qualification
limits, not controller thresholds.

Counter saturation is outside this applicability envelope: a one-second 10 MHz
gate is far below the 32-bit terminal count. Saturation arithmetic, flagging,
and reason typing are therefore synthetic-only v1 checks. A successful bench
result is reported `qualified_with_limits`, with this limitation retained.

## Equipment and safe wiring

Required:

- Arduino Nano RP2040 Connect running the candidate build;
- repaired H1 CX317 plus SN74LVC1G17 conditioning path;
- stable, 3.3 V-safe PPS source;
- independent, authorised counter path observing the same oscillator during
  the same stable interval;
- oscilloscope or time-interval capability for counter-aperture evidence;
- two USB serial paths if the independent path is a second OTIS instrument.

Wire:

```text
PPS source -> candidate D14/GPIO26 (authoritative REF)
PPS source -> candidate D10/GPIO5  (diagnostic witness only)
CX317 conditioned output -> candidate D8/GPIO20
CX317 conditioned output -> independent counter input
all instrument grounds -> common bench ground
```

Use a buffer or specified fan-out when one source drives multiple inputs. Never
tie two active PPS outputs together. The D10 witness does not become a second
PPS authority.

## Repository and compile preflight

From the repository root:

```bash
git status --short --branch
git log -8 --oneline --decorate
git log -1 --oneline -- data_contracts/estimates_v1.csv.md
git log -1 --oneline -- \
  docs/50_SOFTWARE/PHASE_4_LIVE_OBSERVE_ONLY_ENGINEERING_NOTE.md
python3 -m pytest -q
python3 firmware/arduino/validation/scripts/run_no_hardware_checks.py
```

Confirm those paths resolve to the reviewed, merged deterministic Phase 4 host
replay and live-parity contracts, not only an unmerged feature stack.

Compile the default and candidate configurations into separate build paths:

```bash
export OTIS_PHASE5_GIT_COMMIT="$(git rev-parse HEAD)"

arduino-cli compile \
  --fqbn rp2040:rp2040:arduino_nano_connect \
  --build-path /private/tmp/otis-phase5-default \
  firmware/arduino/otis_nano_rp2040_connect

arduino-cli compile \
  --fqbn rp2040:rp2040:arduino_nano_connect \
  --build-path /private/tmp/otis-phase5-pps \
  --build-property "compiler.cpp.extra_flags=-DOTIS_SW1_BRINGUP_MODE=OTIS_SW1_MODE_H1_OCXO_OBSERVE -DOTIS_CAPTURE_BACKEND=OTIS_CAPTURE_BACKEND_IRQ -DOTIS_TCXO_COUNTER_BACKEND=OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO -DOTIS_ENABLE_PPS_DUAL_OBSERVER=1 -DOTIS_ENABLE_PHASE4_OBSERVE_PREVIEW=0 -DOTIS_ENABLE_DAC_AD5693R=0 -DOTIS_ENABLE_H1_DAC_SWEEP=0 -DOTIS_ENABLE_ENV_SENSORS=0 -DOTIS_FIRMWARE_CONFIG_ID=\\\"phase5_pps_gated_qualification_v1\\\" -DOTIS_FIRMWARE_GIT_COMMIT=\\\"${OTIS_PHASE5_GIT_COMMIT}\\\"" \
  firmware/arduino/otis_nano_rp2040_connect
```

Compile the independent PIO long-gate configuration if a second OTIS
instrument is the authorised comparison:

```bash
arduino-cli compile \
  --fqbn rp2040:rp2040:arduino_nano_connect \
  --build-path /private/tmp/otis-phase5-independent \
  --build-property "compiler.cpp.extra_flags=-DOTIS_SW1_BRINGUP_MODE=OTIS_SW1_MODE_H1_OCXO_OBSERVE -DOTIS_CAPTURE_BACKEND=OTIS_CAPTURE_BACKEND_IRQ -DOTIS_TCXO_COUNTER_BACKEND=OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE -DOTIS_ENABLE_PPS_DUAL_OBSERVER=0 -DOTIS_ENABLE_PHASE4_OBSERVE_PREVIEW=0 -DOTIS_ENABLE_DAC_AD5693R=0 -DOTIS_ENABLE_H1_DAC_SWEEP=0 -DOTIS_ENABLE_ENV_SENSORS=0 -DOTIS_FIRMWARE_CONFIG_ID=\\\"phase5_independent_long_gate_v1\\\" -DOTIS_FIRMWARE_GIT_COMMIT=\\\"${OTIS_PHASE5_GIT_COMMIT}\\\"" \
  firmware/arduino/otis_nano_rp2040_connect
```

Every compile must exit zero. Preserve the commands, Arduino CLI version,
RP2040 core version, and output sizes in local notes.

## Upload and boot acceptance

Set explicit device paths:

```bash
export OTIS_CANDIDATE_PORT=/dev/cu.usbmodemCANDIDATE
export OTIS_INDEPENDENT_PORT=/dev/cu.usbmodemINDEPENDENT
```

Upload the already compiled candidate:

```bash
arduino-cli upload \
  --port "$OTIS_CANDIDATE_PORT" \
  --fqbn rp2040:rp2040:arduino_nano_connect \
  --build-path /private/tmp/otis-phase5-pps \
  firmware/arduino/otis_nano_rp2040_connect
```

Abort before capture if boot shows `BOOT_FATAL`, repeated resets, resource
registry conflict/incompleteness, or a backend other than
`pps_gated_ratio`. Required boot/status evidence includes:

```text
capture/tcxo_counter_backend=pps_gated_ratio
capture/pps_gated_ratio_init=ok
firmware/config_id=phase5_pps_gated_qualification_v1
firmware/git_commit=<the exact 40-hex OTIS_PHASE5_GIT_COMMIT>
pps_gate/backend=pps_gated_ratio
pps_gate/duplicate_max_interval_us=100000
pps_gate/min_interval_us=800000
pps_gate/max_interval_us=1200000
pps_gate/missing_timeout_us=2500000
pps_gate/count_resolution_edges=1
pps_gate/counter_aperture_uncertainty_ns=unavailable
pps_gate/reference_frequency_uncertainty_ppb=unavailable
build/enable_dac_ad5693r=0
build/enable_h1_dac_sweep=0
build/enable_phase4_observe_preview=0
phase4_preview/actuation_authorized=false
resource_registry/valid=true
resource_registry/complete=true
resource_registry/dma_claim_count=0
```

The two uncertainty status values remain `unavailable` until promoted from
measured/calibrated host evidence. They must never be emitted as zero.

## Local run preparation

Use local, ignored `runs/` storage. Never force-add it.

```bash
export OTIS_PHASE5_ROOT=runs/phase5_pps_backend
export OTIS_CANDIDATE_RUN="$OTIS_PHASE5_ROOT/candidate_run_001"
export OTIS_INDEPENDENT_RUN="$OTIS_PHASE5_ROOT/independent_run_001"

mkdir -p "$OTIS_CANDIDATE_RUN" "$OTIS_INDEPENDENT_RUN"
cp profiles/run_templates/phase5_pps_gated_candidate_v1/run_manifest.json \
  "$OTIS_CANDIDATE_RUN/run_manifest.json"
cp profiles/run_templates/phase5_independent_long_gate_v1/run_manifest.json \
  "$OTIS_INDEPENDENT_RUN/run_manifest.json"
git check-ignore -v "$OTIS_CANDIDATE_RUN" "$OTIS_INDEPENDENT_RUN"
```

Before capture, replace every `TEMPLATE` or `REPLACE_...` value in both local
manifests. The two manifests must use the same unique
`comparison_interval_id`. Record the exact firmware/host commits, instrument
identity, calibration identity, wiring, source domain, and UTC start plan.
`estimator_type`, `measurement_backend`, and `source_domain` must describe the
actual path; do not label an FC0 or PIO long-gate product as PPS-gated. The
independent estimator/backend pair must be one of the explicit
`allowed_independent_paths` in the qualification profile, and both runs must
name the same oscillator `source_domain`.

## Nominal, service-load, and simultaneous independent capture

Start candidate capture with reconnect logging and a validated command FIFO:

```bash
python3 -m host.otis_tools.capture_device \
  --device "$OTIS_CANDIDATE_PORT" \
  --baud 115200 \
  --run-dir "$OTIS_CANDIDATE_RUN" \
  --command-fifo "$OTIS_CANDIDATE_RUN/commands.fifo"
```

Start the independent capture in a second terminal at the same planned
interval. If it is a second OTIS instrument:

```bash
python3 -m host.otis_tools.capture_device \
  --device "$OTIS_INDEPENDENT_PORT" \
  --baud 115200 \
  --run-dir "$OTIS_INDEPENDENT_RUN"
```

Required sequence:

1. Allow the 600 s startup inhibit to complete.
2. Confirm at least three subsequent clean windows and
   `pps_gate/control_eligible=true`.
3. Capture at least 3600 stable, valid one-second candidate windows while the
   independent path observes the same oscillator and interval.
4. Within that stable hour, designate at least one 600-window baseline segment
   and one 600-window service-load segment.
5. During the load segment, send read-only `CONFIG?` requests every two seconds:

```bash
for request in {1..300}; do
  python3 -m host.otis_tools.send_command \
    --fifo "$OTIS_CANDIDATE_RUN/commands.fifo" 'CONFIG?'
  sleep 2
done
```

Do not send `DAC SET`, `DAC MID`, `DAC ZERO`, or any sweep command. Candidate
firmware is compiled without the DAC driver and sweep, but operator procedure
must still preserve the phase boundary.

Record the exact baseline/load `count_seq` ranges in the candidate manifest's
`service_plane_segments` before sealing. A load comparison without exact
sequence provenance is unavailable, not zero.

Also set `comparison_first_count_seq` and `comparison_last_count_seq` in both
manifests to the exact observations inside the shared UTC comparison interval.
Fault injection and recovery rows outside that interval remain raw evidence but
must not silently enter the bias, jitter, or stable-duration calculation.

## Safe fault and recovery sequence

Perform fault injection only after the stable interval. Preserve every raw
`REF`, bounded invalid `CNT`, and `STS` row.

| Injection | Safe method | Required reason/status |
|---|---|---|
| Duplicate PPS | isolated programmable source adds a second rising edge within 50 ms | `reference_reason=reference_pps_duplicate`; `control_eligible=false` |
| Short PPS | isolated programmable interval of 0.625 s | `reference_reason=reference_pps_short_interval`; invalid bounded `CNT` |
| Long PPS | isolated programmable interval of 1.5 s, below missing timeout | `reference_reason=reference_pps_long_interval`; invalid bounded `CNT` |
| Missing PPS | remove the reference for more than 2.5 s | `reference_reason=reference_missing_pps`; no fabricated clean close `CNT` |
| Invalid count | safely disconnect only the conditioned oscillator observation for one bounded gate | `count_reason=count_zero`; `SOURCE_HEALTH_SUSPECT` and `INPUT_STUCK_LOW` |
| Recovery | restore both inputs and wait for at least three clean windows | independent validity returns to `valid`; `control_eligible=true` |

Do not attempt a >4 GHz source or an overlong PPS gate to force 32-bit
saturation. That is outside the v1 hardware envelope and remains a
synthetic-only negative case.

For USB reconnect behavior, use a separate local run so a device reset and
sequence restart cannot be mistaken for one continuous metrology session.
Preserve reconnect markers, repeat startup qualification, and compare clean
pre/post-reconnect segments. Do not splice or renumber raw records.

## Aperture and uncertainty evidence

Measure the delay from each authoritative PPS edge to PIO counter disable and
re-enable under baseline and service load. Record sample count, instrument
calibration, mean, standard deviation, extrema, and whether start/stop latency
is correlated. Populate these manifest values only from evidence:

- `count_quantization_standard_uncertainty_hz`;
- `counter_aperture_s_1sigma`;
- `reference_fractional_1sigma`;
- independent run `independent_frequency_hz_1sigma`.

Leave any unsupported component `null`. The qualification tool refuses to
compute a combined uncertainty when any required component is unavailable.

## Stop, validate, seal, and analyse

Stop both capture processes cleanly with `Ctrl-C`. Complete local manifests,
including UTC end, exact sequence segments, uncertainty sources, fault notes,
and commits. Then:

```bash
python3 -m host.otis_tools.validate_run "$OTIS_CANDIDATE_RUN"
python3 -m host.otis_tools.validate_run "$OTIS_INDEPENDENT_RUN"

touch "$OTIS_CANDIDATE_RUN/COMPLETE"
touch "$OTIS_INDEPENDENT_RUN/COMPLETE"
python3 -m host.otis_tools.evidence "$OTIS_CANDIDATE_RUN"
python3 -m host.otis_tools.evidence "$OTIS_INDEPENDENT_RUN"

python3 -m host.otis_tools.validate_run "$OTIS_CANDIDATE_RUN"
python3 -m host.otis_tools.validate_run "$OTIS_INDEPENDENT_RUN"

python3 -m host.otis_tools.pps_backend_qualification \
  "$OTIS_CANDIDATE_RUN" \
  --independent-run "$OTIS_INDEPENDENT_RUN" \
  --config profiles/qualification/pps_gated_ratio_v1.json
```

The derived product is written only to:

```text
<candidate-run>/derived/phase5_pps_backend_qualification_v1/qualification_report_v1.json
```

The tool refuses to replace different existing output and verifies that
candidate and independent source hashes did not change.

## Abort and disposition

Abort, preserve, and mark the bench gate failed for:

- boot fatal, reset loop, resource conflict, or wrong backend;
- any `CNT` boundary not traceable to adjacent authoritative `REF` rows;
- unflagged zero/saturated count or suppressed bounded invalid observation;
- loss of independent reference/count validity semantics;
- capture/parser drops or malformed serial frames;
- unexplained baseline/load shift over 0.05 Hz;
- bias over 0.05 Hz;
- jitter over 1.5 Hz;
- missing fault reason or missing inhibition;
- incomplete evidence seal or unavailable required uncertainty.

Promote only the reviewed compact conclusion to tracked documentation. Keep raw
and derived run evidence local under `runs/`.
