# Phase 5 short hardware campaign — 2026-07-31

## Decision

The completed short campaign supports progression to extended testing of the
PPS-gated firmware architecture with the installed ECS 16 MHz oscillator and
real GPS PPS. It does not establish absolute oscillator accuracy, ppb-level
load immunity, or pad-level phase/duty margin.

Subsequent extended and overnight evidence passed, and the combined
measurement-backend campaign was accepted on 2026-08-01 with the limitations
in this report retained.

The ECS is a fixed, unsteered stimulus for the backend. It is not the later
steered CX317 VCOCXO plant. Its mean and slow drift are nuisance observations
in this campaign; the decision is centred on firmware-owned boundary
correctness, total observed count spread under foreground load, exact
reconstruction, queue behaviour, and zero data-path loss.

The decision uses the criterion classes and datasheet basis in
`PHASE_5_CRITERIA_AND_TOLERANCE_RATIONALE.md`. Exact digital integrity and the
1.5 Hz firmware-architecture population-spread screen are blocking. Absolute
frequency bias and quiet/load mean differences are characterization.

## Evidence

### Pseudo-PPS clean smoke

Run:
`runs/phase5_pps_backend/pps_remediation_20260731T160928Z_pseudo_clean_strict`

- 600 raw `REF` observations and 600 cumulative `SNP` rows were captured.
- The first snapshot was used only as an anchor; 599 `CNT` rows followed.
- The clean sequence contained no capture, parser, DMA, ring, or session fault.
- Adjacent cumulative snapshots reconstructed the emitted counts without a
  gap or retroactive association.

Disposition: **pass — digital architecture**.

### Pseudo-PPS fault campaign

Run:
`runs/phase5_pps_backend/pps_remediation_20260731T162222Z_pseudo_faults_strict`

The strict scorer reported 30 correct detections from 31 scheduled fault
events, zero false detections, zero duplicate detections, and zero
classification mismatches. The single miss was the documented
`NARROW_GLITCH` case: a 10 microsecond high time whose next rising edge remained
on the nominal cadence. A rising-edge-only observer cannot distinguish that
width-only event. Closing it would require falling-edge/pulse-width capture and
delayed validity; changing an interval threshold cannot detect it.

Disposition: **30/31 strict; accepted known width-blind limitation for the
present GPS-PPS fault model**. It is not reported as a full strict pass.

### Real-GPS quiet run

Run:
`runs/phase5_pps_backend/pps_remediation_20260731T170231Z_real_gps_quiet`

The declared ten-minute interval, `count_seq 600..1199`, contains 600 eligible
windows. Raw counts ranged from 15,999,996 to 15,999,999 edges. The population
mean was 15,999,998.308 Hz and population standard deviation was 0.560 Hz.
There was no capture, parser, DMA, ring, physical-PPS, reset, or session fault.

Disposition: **pass — real-reference continuity and architecture spread**.
The mean is a characterization result, not an accuracy claim.

### Sequential quiet/load run

Run:
`runs/phase5_pps_backend/pps_remediation_20260731T191840Z_real_gps_quiet_load_v3`

| Segment | Eligible windows | Mean (Hz) | Population standard deviation (Hz) |
|---|---:|---:|---:|
| quiet 1 | 601 | 15,999,997.077 | 0.890 |
| `CONFIG?` load 1 | 602 | 15,999,996.817 | 0.926 |
| quiet 2 | 596 | 15,999,996.218 | 0.657 |
| `CONFIG?` load 2 | 601 | 15,999,996.088 | 0.469 |

The sequential load-minus-preceding-quiet differences were -0.259 Hz and
-0.130 Hz. All four segment spreads were below the 1.5 Hz architecture screen,
all declared windows were traceable to adjacent authoritative boundaries, and
capture/parser/FIFO/DMA/ring/session counters remained clean.

Disposition: **pass — digital/load integrity**. The mean differences are
retained only as nuisance characterization of this unsteered ECS setup. The
former 0.05 Hz reference is not a defensible firmware acceptance limit.

### Bracketed quiet-load-quiet diagnostic

Run:
`runs/phase5_pps_backend/pps_remediation_20260731T201514Z_real_gps_bracketed_load_diagnostic`

The three guarded segments each contain 599 eligible windows:

| Segment | Mean (Hz) | Population standard deviation (Hz) |
|---|---:|---:|
| quiet before | 15,999,998.023 | 0.775 |
| `CONFIG?` load | 15,999,997.778 | 0.831 |
| quiet after | 15,999,997.821 | 0.595 |

The load mean was 0.144 Hz below the value obtained by linearly interpolating
the preceding and following quiet means at the load-segment centre. This is a
better drift-aware estimate than a single sequential difference, but it still
does not identify cause. Approximate block analysis did not robustly resolve
the small effect from slow drift/autocorrelation. No oscillator-package
temperature, local TCXO rail, or simultaneous independent frequency was
recorded.

Disposition: **pass — digital/load integrity**. The mean result is retained
only as nuisance characterization and is not used to assess the later steered
VCOCXO control plant.

The standalone v2 qualification report for this diagnostic says `failed`
because that one run intentionally contains neither the separate fault
campaign nor all boot-only identity fields. Its relevant run-scoped checks do
pass: raw snapshot/CNT parity, traceability, duration, segment sample count,
population spread, zero capture/storage counters, and sealed evidence.

## Datasheet and firmware interpretation

- ECS frequency tolerance and environmental limits are tens of hertz at
  16 MHz; the datasheet does not specify one-second stability or a ppb-scale
  service-load step.
- GPS PPS is specified at 20 ns RMS, equal to 0.32 of a 62.5 ns oscillator
  cycle. RMS is not a maximum, and consecutive errors are not stated to be
  independent.
- The RP2040 PIO input synchronizer adds deterministic latency and prevents
  metastability from directly entering state-machine logic. The digital proof
  covers synchronized edge selection; the unavailable hardware phase/duty
  sweep remains explicitly not tested and non-blocking.
- PIO owns the cumulative counter and snapshot aperture. DMA, SRAM-ring,
  foreground, command, USB, and host latency occur after that snapshot. Their
  blocking criteria are exact reconstruction, sequence continuity, bounded
  backlog, and zero loss/error counters—not an invented nanosecond number.
- The independent GPIO-IRQ `REF` timestamp is an observer. Its software latency
  does not define the raw oscillator-count aperture, and no absolute IRQ-latency
  bound is claimed without an external timing measurement.
- The observed count spread combines the ECS, GPS PPS, input synchronization,
  boundary-edge selection, and reconstruction. This fixture cannot extract a
  standalone firmware-jitter number. The firmware-specific evidence is the
  digital `-1/0/+1` proof, exact SNP/CNT parity, zero loss/order counters,
  bounded backlog, and no load-correlated spread broadening.

## Subsequent sustained evidence

The several-hour alternating-load run and the newly sealed 16,798-window
overnight capture are complete. Both pass their sustained digital-architecture
and load-integrity gates, with exact raw SNP/CNT reconstruction and zero
capture, PIO/DMA/ring, parser, or session-continuity fault. Results, hashes, and
the 14-pair comparison are recorded in
`PHASE_5_REAL_GPS_EXTENDED_AND_OVERNIGHT_CAMPAIGN_20260801.md`.

Those runs complete the planned sustained evidence but do not remove the
documented physical phase/duty coverage limitation, close the accepted
width-only glitch case, or create an absolute metrology uncertainty budget.
