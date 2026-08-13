# PPS Backend Remediation Bench Handoff

This is the executable hardware handoff for
`pio_wait_cumulative_snapshot_dma_v1`. No step in this runbook authorizes
control. The required campaign was completed and deliberately reviewed on
2026-08-01; the backend is accepted for observe-only measurement with the
documented width-only and physical phase/duty limitations. Existing evidence
builds remain sealed with `backend_qualified=false`, and no actuation gate is
changed by this disposition.

## A. Preflight

Run from the repository root. A formal evidence build must use a clean,
committed tree; record the exact commit before doing anything else:

```bash
git status --short --branch
git rev-parse HEAD
test ! -e firmware/arduino/otis_nano_rp2040_connect/otis_build_profile.generated.h
python3 tools/verify_pio_snapshot.py --pioasm /Users/richardflynn/Library/Arduino15/packages/rp2040/tools/pqt-pioasm/5.0.0-9576866/pioasm
python3 -m pytest -q
python3 tools/firmware_matrix.py --check-environment
python3 tools/firmware_matrix.py --profile phase5_qualification
python3 tools/firmware_matrix.py --profile pseudo_pps_loopback
```

If the generated-profile-header check fails, preserve that stale local file
outside the repository before using the matrix builder. Do not build around it.
Both builds must say `outcome=pass verified=True`. The proof must report 7,936
cases, 55,552 intervals, error only `-1/0/+1`, a 15-word programme, a maximum
four clocks to the opposite `WAIT`, and the exact 133 MHz FQBN.

The real candidate must boot with at least:

```text
pps_gate/boundary_owner=pio_state_machine
pps_gate/aperture_backend=pio_wait_cumulative_snapshot_dma_v1
pps_gate/backend_qualified=false
pps_gate/counter_direction=down
pps_gate/counter_width_bits=32
pps_gate/pio_system_clock_hz=133000000
pps_gate/pio_clock_divider=1.0
pps_gate/snapshot_rx_fifo_depth=8
pps_gate/snapshot_ring_capacity=128
phase4_preview/actuation_authorized=false
resource_registry/valid=true
resource_registry/complete=true
resource_registry/dma_claim_count=1
```

Abort on a different owner/backend, `backend_qualified=true`, any boot fatal,
resource conflict, or reset loop.

Use ignored local run storage and prove that Git ignores it:

```bash
export OTIS_RUN_ID="pps_remediation_$(date -u +%Y%m%dT%H%M%SZ)"
export OTIS_RUN_DIR="runs/phase5_pps_backend/$OTIS_RUN_ID"
mkdir -p "$OTIS_RUN_DIR"
git check-ignore -v "$OTIS_RUN_DIR"
```

Bench equipment and cautions:

- conditioned ECS 16 MHz TCXO on D8/GPIO20; verify 3.3 V levels at the RP2040 pad;
- PPS on D14/GPIO26 only; D10/GPIO5 remains the independent external-event
  input and is not part of this backend test;
- oscilloscope or logic analyser capable of measuring duty, rise/fall time,
  and PPS-to-oscillator phase;
- approximately 1 kOhm series resistor for D3-to-D14 pseudo-PPS loopback;
- common ground; and
- never connect the D3 generator and a real GPS PPS output to D14 at the same
  time.

Measure the actual D8 pad waveform before acceptance. The digital proof covers
35–65% duty at 16 MHz, but it does not prove the assembled buffer, routing, or
pad waveform. Stop if duty leaves that envelope, edges ring through thresholds,
or setup margin cannot be demonstrated.

## B. Pseudo-GPS clean smoke, 10–20 minutes

Power down, disconnect real GPS PPS, connect D3/GPIO15 through approximately
1 kOhm to D14/GPIO26, flash the `pseudo_pps_loopback` artifact, and power up.
D3 must remain high impedance until explicitly armed.

Start capture in terminal 1:

```bash
export OTIS_PSEUDO_RUN="runs/phase5_pps_backend/${OTIS_RUN_ID}_pseudo_clean"
python3 -m host.otis_tools.capture_device \
  --auto-detect --baud 115200 --run-dir "$OTIS_PSEUDO_RUN" \
  --command-fifo "$OTIS_PSEUDO_RUN/commands.fifo"
```

In terminal 2, inspect the available immutable profiles, then run the continuous
10-minute clean schedule:

```bash
python3 -m host.otis_tools.send_command --fifo "$OTIS_PSEUDO_RUN/commands.fifo" 'PPSGEN PROFILES?'
python3 -m host.otis_tools.send_command --fifo "$OTIS_PSEUDO_RUN/commands.fifo" 'PPSGEN ARM CLEAN_SOAK_10M'
python3 -m host.otis_tools.send_command --fifo "$OTIS_PSEUDO_RUN/commands.fifo" 'PPSGEN START'
python3 -m host.otis_tools.send_command --fifo "$OTIS_PSEUDO_RUN/commands.fifo" 'PPSGEN?'
```

The 600-pulse schedule avoids artificial gaps and false outage/recovery events
caused by host re-arm latency between 30-pulse blocks. Stop capture after its
completion marker with Ctrl-C, then run:

```bash
python3 -m host.otis_tools.validate_run "$OTIS_PSEUDO_RUN"
```

Create a clean-alignment JSON v1 containing an explicit centre source and the
aligned interval evidence (use
`tests/fixtures/pseudo_pps/clean_acceptance_v1.json` as the field-shape
example), then run:

```bash
python3 -m host.otis_tools.pseudo_pps_acceptance \
  "$OTIS_PSEUDO_RUN/reports/pseudo_pps_clean_alignment_v1.json" \
  --output "$OTIS_PSEUDO_RUN/reports/pseudo_pps_clean_score_v1.json" --strict
```

The checked-in JSON is a test fixture, not a bench threshold. Replace its
`centre_evidence`, expected rate, and limits with pre-run evidence and reviewed
limits for the actual oscillator/source combination.

Hard pass criteria are: one physical REF and one raw SNP for every scheduled
clean pulse; first SNP is anchor-only; every later adjacent pair produces the
expected CNT; snapshot and REF sequences are continuous; and the fitted count
centre is consistent with an independently measured/reference oscillator
frequency, or with a documented nominal expectation and explicit frequency
tolerance. The pseudo-PPS generator defines the gate duration, not an exact
16 MHz oscillator frequency. Count residuals and adjacent differences must
stay inside the proved asynchronous `-1/0/+1` boundary model, with any other
explicit measurement noise separately bounded. No allowed centre offset may
waive excess jitter, a load-dependent mean/distribution shift, a count outlier,
sequence/snapshot loss, malformed PPS, or host/parser loss. There must also be
no false physical-missing transition, FIFO/DMA/ring error or overwrite; and
completion must return D3 to high impedance. Reporting delay and temporary
foreground backlog are allowed only when the official count mean and
distribution remain within the declared limits.

## C. Fault-injection acceptance

Use a fresh run directory with the same safe loopback wiring. Start capture as
above, then run the composite profile:

```bash
export OTIS_FAULT_RUN="runs/phase5_pps_backend/${OTIS_RUN_ID}_pseudo_faults"
python3 -m host.otis_tools.capture_device \
  --auto-detect --baud 115200 --run-dir "$OTIS_FAULT_RUN" \
  --command-fifo "$OTIS_FAULT_RUN/commands.fifo"
python3 -m host.otis_tools.send_command --fifo "$OTIS_FAULT_RUN/commands.fifo" 'PPSGEN ARM COMPOSITE'
python3 -m host.otis_tools.send_command --fifo "$OTIS_FAULT_RUN/commands.fifo" 'PPSGEN START'
```

After completion, exercise any ambiguous class individually with `ONE_SHORT`,
`ONE_LONG`, `ONE_OMIT`, `DOUBLE`, `BOUNCE`, `NARROW_GLITCH`,
`POSITIVE_PHASE_STEP`, `NEGATIVE_PHASE_STEP`,
`SUSTAINED_POSITIVE_OFFSET`, `SUSTAINED_NEGATIVE_OFFSET`,
`REPEATED_OMISSIONS`, and finally `RETURN_CLEAN`.

Preserve PGT generator intent, REF physical detection, SNP capture status, and
diagnostic policy as separate evidence. Create an aligned JSON v1 using
`tests/fixtures/pseudo_pps/scoring_v1.json` only as the field-shape example,
then score it exactly:

```bash
python3 -m host.otis_tools.pps_fault_scoring \
  "$OTIS_FAULT_RUN/reports/pps_fault_alignment_v1.json" \
  --output "$OTIS_FAULT_RUN/reports/pps_fault_score_v1.json" --strict
```

Acceptance requires correct short/long, omission/outage, double-edge,
bounce/glitch, phase-step, sustained-offset, restoration, and recovery
classification; zero misses, false detections, duplicates, or classification
mismatches; exactly one outage and one restoration transition per continuous
outage; no duplicate outage transition from reminders; every malformed
reference period measurement-invalid; no retroactive late association; and two
fresh clean snapshots before CNT resumes. Any unexplained truth mismatch or
valid measurement spanning a fault is a hard failure.

The rising-edge-only D14 backend cannot distinguish the `NARROW_GLITCH`
profile's 10 microsecond high time when its next rising edge remains exactly on
the nominal cadence. Keep that strict-score miss visible as a known width-blind
limitation. Closing it requires falling-edge/pulse-width capture and delayed
validity, not a wider or narrower cadence threshold; defer that architecture
unless the real GPS-PPS fault model makes pulse-width qualification necessary.

For an electrically narrower pulse that produces REF but no SNP, the required
fail-closed outcome remains `association_state=lost`, `cnt_state=absent`, and
`reason=ref_without_snapshot`. Any valid CNT crossing it or retroactive late
association is a hard failure. Preserve a late word only as quarantined host
evidence; the next clean word is the new-session anchor and only its adjacent
successor may restore CNT.

## D. Real-GPS quiet smoke, 10–20 minutes

Power down. Remove the D3 loopback, restore the real GPS PPS connection, flash
the `phase5_qualification` build, and confirm D3 is not driven. Initialise the
candidate run from the tracked template:

```bash
export OTIS_REAL_RUN="runs/phase5_pps_backend/${OTIS_RUN_ID}_real_quiet"
mkdir -p "$OTIS_REAL_RUN"
cp profiles/run_templates/phase5_pps_gated_candidate_v1/run_manifest.json "$OTIS_REAL_RUN/run_manifest.json"
git check-ignore -v "$OTIS_REAL_RUN"
python3 -m host.otis_tools.capture_device \
  --auto-detect --baud 115200 --run-dir "$OTIS_REAL_RUN" \
  --command-fifo "$OTIS_REAL_RUN/commands.fifo"
```

Replace every template marker in the local manifest with observed provenance
and exact sequence/UTC bounds. Stop after 10–20 minutes and validate. There
must be no snapshot or REF gap, false watchdog event, overflow, parser loss,
reset, or implausible raw count. Examine `official_raw_frequency`; the
`diagnostic_timer_normalized_frequency` is explicitly non-authoritative and
cannot waive an official failure.

## E. Alternating quiet/load architectural test, 30–60 minutes

Use a fresh real-GPS candidate run. After startup qualification, label at least
four exact contiguous segments in the local manifest, for example:

```text
quiet_1  10 minutes
load_1   10 minutes
quiet_2  10 minutes
load_2   10 minutes
```

During load segments, generate bounded USB/serial and foreground work while the
capture process remains the sole serial owner:

```bash
for request in {1..600}; do
  python3 -m host.otis_tools.send_command --fifo "$OTIS_REAL_RUN/commands.fifo" 'CONFIG?'
  sleep 1
done
```

Record exact `count_seq` ranges as `service_plane_segments`, seal the run as
described in the Phase 5 runbook, and execute:

```bash
python3 -m host.otis_tools.validate_run "$OTIS_REAL_RUN"
touch "$OTIS_REAL_RUN/COMPLETE"
python3 -m host.otis_tools.evidence "$OTIS_REAL_RUN"
python3 -m host.otis_tools.pps_backend_qualification \
  "$OTIS_REAL_RUN" --independent-run "$OTIS_INDEPENDENT_RUN" \
  --config profiles/qualification/pps_gated_ratio_v2.json
```

The principal firmware gate is that load may change reporting latency and
backlog but must not cause an invalid boundary, reconstruction mismatch,
sequence loss, capture/transport fault, or population standard deviation above
the 1.5 Hz architecture screen. Every quiet and load segment needs at least 60
eligible windows. Report quiet/load means and a bracketed or otherwise
drift-aware load estimate as characterization; the historical 0.05 Hz
reference is not a pass/fail limit. A quieter timer-normalised diagnostic does
not override an official raw-count or integrity failure.

As a separate waveform characterization, sweep PPS relative to the 16 MHz oscillator over
at least one complete 62.5 ns period, including threshold-adjacent phase points.
Test the observed nominal duty and controlled 35%, 40%, 50%, 60%, and 65% duty
conditions where the bench source permits. At each point require no missed or
double-counted synchronized oscillator edge and boundary error confined to
`-1/0/+1`. The current ECS fixture/source cannot perform this controlled phase
and duty sweep. Record it as not tested and non-blocking; do not report a pass.

## F. Extended and overnight sequence

Campaign disposition: **complete and accepted for observe-only measurement**.
The extended run contains 11,388 exact windows; the newly sealed overnight run
contains 16,798 exact windows across 14 guarded quiet/load pairs, with zero
capture, PIO, DMA, ring, parser, or session-continuity fault. See
`PHASE_5_REAL_GPS_EXTENDED_AND_OVERNIGHT_CAMPAIGN_20260801.md` for hashes and
statistics. The procedure below is retained as the reproducible runbook.

Only after A–E pass, run several hours with alternating service load. Inspect
counter/sequence/timer wrap handling, DMA and ring high-water marks, physical
PPS transitions, reset/session changes, and parser integrity. Any reset starts
a new run; do not splice sessions.

Only after the extended run passes, repeat an overnight run in a form directly
comparable to `candidate_20260730T192721Z`, but using this PIO identity, raw SNP
contract, 16 MHz source typing, and exact quiet/load segment provenance. Seal
the candidate and any available authorised independent evidence with
`COMPLETE`, validate, and generate evidence snapshots before qualification
analysis. Independent absolute metrology is a separate characterization
package and is not required to accept the digital ownership/integrity result.

An overnight run never changes firmware qualification automatically. Review
the proof, the documented not-tested phase/duty item, fault score, raw snapshot
continuity, official jitter, characterized mean load shift, independent comparison,
uncertainty, resets, and all integrity counters. Only an explicit reviewed
source change may set a future qualification gate. That review was completed
and the observe-only measurement backend was accepted on 2026-08-01; changing
an operational compile-time gate remains separate from actuation authority.

## Troubleshooting decision tree

- **No SNP:** preserve the run; check exact backend/133 MHz boot status, D8 pad
  activity, PIO/DMA claims, RXSTALL/DMA fault counters. Do not replace PIO
  ownership with ISR or polling.
- **Snapshot/REF sequence gap:** stop; preserve raw log and session; inspect
  overwrite/backlog/association status; rearm and require two new snapshots in
  a new run or session. Never renumber or pair late data.
- **False physical missing-PPS:** confirm raw REF production continued. If only
  foreground/telemetry lagged, repair the reporting path; backlog must not
  alter physical presence state.
- **Pseudo truth mismatch:** stop the generator; retain PGT and raw serial;
  inspect wiring, D3 high-Z transitions, PIO underflow/resource faults, and
  D14 waveform before rerunning an individual profile.
- **FIFO/DMA/ring overflow:** invalidate the session and stop. Reduce service or
  correct transport; do not accept later words from the damaged session.
- **Load-sensitive raw counts:** fail the architecture and preserve both
  segments. Do not tune a timer normalisation to conceal it.
- **Clean raw counts, bad timer-normalised diagnostic:** keep the official raw
  result; investigate the timer diagnostic separately.
- **Parser/transport fault:** preserve the directory as engineering evidence,
  fix the sole-owner serial path, then use a fresh run for formal evidence.
- **Reset:** end the run, preserve reset provenance, and restart acquisition.
  Never bridge counters or sequence numbers across reset.

At every failure, prefer a clean stop and preserved evidence over an improvised
live patch. If the single-state-machine timing proof fails on hardware, stop
this programme and recommend the documented external counter/capture latch or
CPLD fallback. ISR, DMA, or a second PIO state machine may not substitute as
the aperture owner.
