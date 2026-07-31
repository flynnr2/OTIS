# Phase 5 PPS-Gated Backend Bench Runbook

## Purpose and gate

This runbook first provides a short functional acceptance of the corrected
single-PIO-state-machine-owned count boundary. Longer independent-metrology and uncertainty
work may follow as a separate evidence package; it is not a prerequisite for
accepting that foreground and service load no longer define the aperture. This
runbook does not authorize DAC steering. Throughout this procedure:

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

- the conditioned 16 MHz ECS TCXO observation on `D8` / GPIO20;
- one authoritative conditioned PPS on `D14` / GPIO26;
- the PIO `WAIT`/`JMP PIN` cumulative snapshot backend; D14 GPIO IRQ remains
  an independent REF observer;
- a nominal one-second PPS interval, accepted over `0.8..1.2 s`;
- duplicate classification at `<=0.1 s`;
- a missing-PPS timeout of `2.5 s`;
- the repaired H1 oscillator/front-end topology;
- observe-only operation.

The fixed v1 acceptance thresholds are:

| Check | Threshold |
|---|---:|
| Stable measurement-eligible duration after warmup selection | at least 120 s |
| Measurement-eligible PPS-gated windows | at least 120 |
| Raw `CNT` boundaries traceable to adjacent authoritative `REF` rows | 100% |
| Candidate population jitter | no more than 1.5 Hz per one-second window |
| Baseline-to-service-load mean shift | no more than 0.05 Hz |
| Baseline and service-load segment size | at least 60 eligible windows in every declared segment |
| Required safe bench faults | all detected with the specified reason and inhibition |

The 1.5 Hz single-window jitter bound permits integer-edge aperture variation
while still detecting unexplained multi-edge service latency. The 0.05 Hz
quiet-to-load bound tests service-plane independence. These are architectural
qualification limits, not controller thresholds. The profile retains
independent-bias and uncertainty fields for a later metrology report; those are
not prerequisites for the focused ownership acceptance.

Full counter wrap is outside this applicability envelope: a one-second 16 MHz
gate is far below the 268.435456-second 32-bit wrap interval. Ambiguous-wrap
arithmetic, flagging, and reason typing remain synthetic-only checks. A
successful bench result is reported `qualified_with_limits`, with any retained
limitations explicit.

## Equipment and safe wiring

Required for focused architectural acceptance:

- Arduino Nano RP2040 Connect running the candidate build;
- ECS 16 MHz TCXO plus SN74LVC1G17 conditioning path;
- stable, 3.3 V-safe PPS source;

An independent counter, oscilloscope/logic-analyser marker, or second serial
path may be used for later metrology/latency evidence, but is not required to
accept the architectural correction.

Wire:

```text
PPS source -> candidate D14/GPIO26 (authoritative REF)
PPS source -> candidate D10/GPIO5  (diagnostic witness only)
ECS TCXO conditioned output -> candidate D8/GPIO20
ECS TCXO conditioned output -> independent counter input
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
git log -1 --oneline -- data_contracts/estimates_v2.csv.md
git log -1 --oneline -- \
  docs/50_SOFTWARE/PHASE_4_LIVE_OBSERVE_ONLY_ENGINEERING_NOTE.md
python3 -m pytest -q
python3 firmware/arduino/validation/scripts/run_no_hardware_checks.py
```

Confirm those paths resolve to the reviewed, merged deterministic Phase 4 host
replay and live-parity contracts, not only an unmerged feature stack.

The preflight suite must also prove:

- the diagnostic and reference configuration hashes bind their actual rule
  tables rather than the discipline profile;
- sealed native/host diagnostic and reference fixtures are semantic matches;
- output-backpressure loss raises and clears without feeding estimator or
  actuation state;
- `EST v2` live/replay uncertainty fields match for unavailable and incomplete
  budgets;
- the generated repository-wide measurement-semantics inventory is current.

Verify the pinned environment and compile the candidate profile:

```bash
python3 tools/firmware_matrix.py --check-environment
python3 tools/firmware_matrix.py --profile phase5_qualification
```

If using the Arduino IDE for interactive bench upload, generate the matching
local profile immediately before opening or compiling the sketch:

```bash
python3 tools/firmware_matrix.py \
  --prepare-ide \
  --profile phase5_qualification
```

Select the Philhower **Arduino Nano RP2040 Connect** target on core `6.0.0`.
Regenerate the ignored `otis_build_profile.generated.h` after any source,
profile, core, or toolchain change. IDE builds are suitable for interactive
bench bring-up; use the matrix-built artifact and
`firmware_build_manifest.json` when sealing qualification evidence.

Compile the independent PIO long-gate configuration if a second OTIS
instrument is the authorised comparison:

```bash
python3 tools/firmware_matrix.py --profile h1_characterization
```

Every compile must exit zero. Preserve each profile's ignored
`firmware_build_manifest.json`, which records the exact command inputs,
source/configuration hashes, generated board identity, Arduino
CLI/core/toolchain installed-byte hashes, output identity, and successful
binary artifact hashes.

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
  --input-dir build/firmware_matrix/phase5_qualification/artifacts
```

Abort before capture if boot shows `BOOT_FATAL`, repeated resets, resource
registry conflict/incompleteness, or a backend other than
`pps_gated_ratio`. Required boot/status evidence includes:

```text
capture/tcxo_counter_backend=pps_gated_ratio
capture/pps_gated_ratio_init=ok
firmware/config_id=phase5_qualification
firmware/git_commit=<the exact generated 40-hex Git commit>
firmware/source_state=<clean or dirty>
firmware/source_hash=<the generated 64-hex build-input hash>
firmware/config_hash=<the generated 64-hex profile hash>
system/fqbn=rp2040:rp2040:arduino_nano_connect
system/arduino_core_provider=rp2040
system/arduino_core_version=6.0.0
build/profile_id=phase5_qualification
build/toolchain=pqt-gcc@5.0.0-9576866
build/compiler=pqt-gcc@5.0.0-9576866/arm-none-eabi-g++@16.1.0
build/arduino_cli_version=1.4.1
build/invocation_id=<the generated 64-hex invocation hash>
pps_gate/backend=pps_gated_ratio
pps_gate/boundary_owner=pio_state_machine
pps_gate/aperture_backend=pio_wait_cumulative_snapshot_dma_v1
pps_gate/backend_qualified=false
pps_gate/counter_direction=down
pps_gate/counter_width_bits=32
pps_gate/declared_max_oscillator_hz=16000000
pps_gate/pio_system_clock_hz=133000000
pps_gate/pio_clock_divider=1.0
pps_gate/snapshot_rx_fifo_depth=8
pps_gate/snapshot_ring_capacity=128
pps_gate/boundary_ring_capacity=127
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
resource_registry/dma_claim_count=1
```

The two uncertainty status values remain `unavailable` until promoted from
measured/calibrated host evidence. They must never be emitted as zero.
`backend_qualified=false` is also required for this candidate: the run is the
evidence used to decide whether a later build may set that compile-time gate.

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

## Focused nominal and service-load capture

Before starting capture, close Arduino IDE Serial Monitor/Plotter and every
other process that may open the candidate serial device. `capture_device` must
be the sole serial-port owner for the run. Opening the IDE itself is harmless
only if it does not claim, monitor, reset, or upload through that port.

Start capture before the intended manual reset so the authoritative `BOOT` is
preserved. If another process contends for the port or malformed/interleaved
serial frames occur before that BOOT, preserve the disturbed directory as
diagnostic evidence and use a fresh run directory for a future sealable formal
attempt. A later clean BOOT may define a valid session-scoped engineering test,
but pre-BOOT corruption must never be silently deleted from the original run.

Start candidate capture with reconnect logging and a validated command FIFO:

```bash
python3 -m host.otis_tools.capture_device \
  --device "$OTIS_CANDIDATE_PORT" \
  --baud 115200 \
  --run-dir "$OTIS_CANDIDATE_RUN" \
  --command-fifo "$OTIS_CANDIDATE_RUN/commands.fifo"
```

If collecting the separate independent-metrology package, start the independent
capture in a second terminal at the same planned interval:

```bash
python3 -m host.otis_tools.capture_device \
  --device "$OTIS_INDEPENDENT_PORT" \
  --baud 115200 \
  --run-dir "$OTIS_INDEPENDENT_RUN"
```

Focused acceptance sequence:

1. Allow the 600 s startup inhibit to complete.
2. Confirm at least three subsequent measurement-valid windows. Control remains
   false while `backend_qualified=false`.
3. Capture at least 60 quiet, valid one-second candidate windows.
4. Capture at least 60 service-load windows while issuing repeated `CONFIG?`
   requests and allowing periodic status, sweep service (without actuation),
   and environment service where the build enables them.
5. During the load segment, send read-only `CONFIG?` requests once per second:

```bash
for request in {1..60}; do
  python3 -m host.otis_tools.send_command \
    --fifo "$OTIS_CANDIDATE_RUN/commands.fifo" 'CONFIG?'
  sleep 1
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
| Recovery | restore both inputs and wait for at least three clean windows | independent validity returns to `valid`; `control_eligible` remains false in the unqualified candidate |

Do not attempt a >4 GHz source or an overlong PPS gate to force 32-bit
saturation. That is outside the v1 hardware envelope and remains a
synthetic-only negative case.

For USB reconnect behavior, use a separate local run so a device reset and
sequence restart cannot be mistaken for one continuous metrology session.
Preserve reconnect markers, repeat startup qualification, and compare clean
pre/post-reconnect segments. Do not splice or renumber raw records.

## Focused acceptance contract

Accept the architectural correction when:

- every emitted `CNT` is traceable to adjacent, sequence-continuous atomic
  boundaries and authoritative `REF` timestamps;
- clean 16 MHz / 1 Hz windows remain inside the implementation-derived narrow
  integer-count envelope established by the quiet segment;
- the loaded segment is statistically and operationally equivalent to quiet
  operation, with no gross partial or zero count accepted;
- `CONFIG?`, status, DAC-sweep service, environment service, and foreground
  backlog do not alter the physical aperture;
- missing PPS, duplicate/extra PPS, sequence gaps, ring overflow, invalid
  snapshot, zero count, and saturation have explicit typed status or synthetic
  test evidence;
- no invalid or ambiguous aperture is control-eligible;
- restoration follows the documented re-anchor/recovery sequence.

GPIO/logic-analyser markers are optional diagnostics. They are not a
prerequisite for accepting this ownership correction.

## Separate metrology and uncertainty evidence

If later promoting the backend as quantified metrology, measure or otherwise
bound asynchronous edge quantisation and the real pad-level phase/duty timing
margin, and populate these manifest values only from evidence:

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
