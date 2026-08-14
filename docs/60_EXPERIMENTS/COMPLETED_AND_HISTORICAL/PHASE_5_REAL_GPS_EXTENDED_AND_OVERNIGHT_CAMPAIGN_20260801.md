# Phase 5 real-GPS extended and overnight campaign — 2026-08-01

## Decision status

Both the extended alternating-load run and the newly reset overnight run pass
their sustained digital-architecture gates. Together with the short campaign,
the evidence supports the accepted qualification of the PPS-gated
capture architecture with the documented width-blind and physical-test
limitations. The measurement-backend decision was accepted on 2026-08-01.
Actuation is a separate decision: the qualification build still
reports `backend_qualified=false`, and all DAC, sweep, Phase 4 preview, and
control writes remain disabled pending explicit review.

The ECS 16 MHz TCXO is a fixed, unsteered stimulus used to expose the RP2040
capture path. Oscillator mean and slow drift are characterization here, not
acceptance limits and not evidence about the later steered CX317 plant.

## Sealed extended evidence

Run:
`runs/phase5_pps_backend/pps_remediation_20260731T212402Z_real_gps_extended_alternating_load_v4`

Evidence snapshot digest:
`17e00143ce80ef93b2c069293be2fac8d39166e7a4000ea797bcc80a7c36adc8`

The exact declared interval is 2026-07-31 21:33:58 UTC through 2026-08-01
00:43:46 UTC, `count_seq 653..12040`: 11,388 consecutive eligible windows.
Nine guarded quiet/load pairs were captured. Each load scheduled 600
`CONFIG?` commands, for 5,400 load commands plus one provenance query and one
pre-campaign boundary marker. The capture process remained the sole serial
owner.

| Pair | Quiet windows | Quiet 1 s spread (Hz) | Load windows | Load 1 s spread (Hz) | Load 60 s spread (Hz) |
|---:|---:|---:|---:|---:|---:|
| 1 | 603 | 0.85 | 659 | 0.54 | 0.30 |
| 2 | 604 | 0.44 | 660 | 0.80 | 0.57 |
| 3 | 606 | 0.49 | 688 | 0.47 | 0.18 |
| 4 | 606 | 0.54 | 653 | 0.82 | 0.41 |
| 5 | 606 | 0.71 | 652 | 0.51 | 0.16 |
| 6 | 606 | 0.44 | 652 | 1.09 | 0.45 |
| 7 | 606 | 0.54 | 652 | 0.45 | 0.04 |
| 8 | 606 | 0.45 | 653 | 0.47 | 0.14 |
| 9 | 606 | 0.75 | 653 | 0.48 | 0.11 |

“Spread” is population standard deviation of the stated segment product. The
60-second values use non-overlapping, clean contiguous spans and never cross a
fault, sequence gap, or session boundary. Reported decimal places make the
sample calculations reproducible; they are not corresponding claims of
absolute physical accuracy.

The nine load-minus-preceding-quiet changes in one-second spread have mixed
sign (four positive, five negative); their median is approximately -0.01 Hz.
One load segment reached about 1.09 Hz while later load segments returned to
about 0.45–0.48 Hz. This is not repeatable load-correlated broadening. Every
segment remains below the deliberately coarse 1.5 Hz multi-edge architecture
screen.

Segment mean shifts also change sign, including after drift-aware bracketing.
That is expected to be confounded by the unmeasured ECS package temperature,
local supply, room conditions, and PPS/source behavior. The ECS datasheet does
not provide a one-second stability or service-load step limit, so these means
remain nuisance characterization and are not used as a firmware-latency test.

## Exact integrity results

- All 11,388 declared `CNT` rows reconstruct exactly from adjacent,
  same-session raw cumulative `SNP` endpoints.
- Snapshot continuity is complete; the first declared snapshot is correctly
  an anchor, with 11,388 valid reconstructed intervals and no retroactive
  association.
- Runtime backend, PIO boundary owner, count resolution, thresholds, firmware
  identity, source/config hashes, Arduino core, compiler, and disabled-control
  fields all match the flashed v4 artifact.
- Snapshot backlog high-water is one word, current depth returns to zero, and
  PIO RX-stall, DMA stopped/error, overwrite, continuity-loss, ring-drop,
  sequence-gap, and duplicate counters remain zero.
- Physical D14 and D10 PPS observers remain in agreement with no missing,
  rejected, or anomalous reference interval.
- Host capture records zero rejected commands, malformed UTF-8, parser errors,
  and reconnects.
- Two Arduino/RP2040 microsecond-timer rollover windows occur in the raw run
  and are handled without a false outage or count-continuity break.
- The immutable evidence snapshot validates after capture completion.

The standalone v2 analyser reports overall `failed` only because this nominal
real-GPS run deliberately contains no injected fault reason or post-fault
recovery sequence. Its other acceptance checks pass. Fault injection remains
separate evidence, including the accepted rising-edge-only width-blind
limitation documented in the short campaign report.

## Firmware interpretation

The evidence does not support foreground or USB latency as the oscillator
count-aperture limit. One 133 MHz PIO state machine owns oscillator rising-edge
counting and its cumulative PPS snapshot. DMA, SRAM ring, foreground status
generation, USB, and host handling occur after that value is immutable. Their
failure modes are therefore continuity or backlog failures, all absent here.

Passing the 1.5 Hz total-spread screen is not the endpoint of this work. It is
only a coarse guard against multi-edge or discontinuous capture. The design
objective remains the lowest defensible capture error: autonomous PIO aperture
ownership, a bounded boundary-edge assignment, exact cumulative reconstruction,
and no dependence of the captured value on ISR, foreground, USB, or host
latency. The stable ECS stimulus helps reveal the complete path's floor; it
does not impose a target that excuses avoidable firmware error.

The checked-in digital proof covers 7,936 modeled phase/duty cases and 55,552
adjacent intervals with no missed/double synchronized edge and only `-1/0/+1`
edge boundary error. It now also checks every contiguous span of one through
seven modeled intervals: total span error remains `-1/0/+1`, rather than
accumulating per second. This is the reason longer cumulative differences can
improve count-domain resolution while one-second records retain fault
localization.

The next likely firmware limit is downstream estimation. The present Phase 4
preview defaults to a five-sample mean, whose clean count-domain increment is
0.2 Hz (20 ppb at the future 10 MHz CX317). Before closed-loop work, estimator
span and bandwidth should be selected from measured reference/source noise and
plant dynamics. Longer or multi-rate cumulative spans must retain the same
fail-closed invalidation at malformed references, snapshot gaps, and session
boundaries.

## Overnight evidence

Run:
`runs/phase5_pps_backend/pps_remediation_20260801T004553Z_real_gps_overnight_alternating_load_v4`

Evidence snapshot digest:
`dc25634fe87cc1695be0abb53083fbd16c0701a0f494165f3208144bb8871f73`

Raw serial SHA-256:
`241f50137c18babb9d7f63cad52d7d8c93ed2a66852b857fb352e83cad27d832`

The exact declared interval is 2026-08-01 00:57:49 UTC through 05:37:47 UTC,
`count_seq 655..17452`: 16,798 consecutive eligible windows. Fourteen guarded,
deadline-timed quiet/load pairs were captured after startup inhibition. The
first quiet segment contains 599 windows, the other quiet segments contain 600
each, and every load segment contains 598. The load scheduler sent and the
capture command FIFO accepted 8,400 one-per-second `CONFIG?` requests, plus one
provenance query and one boundary marker; no command was rejected.

| Pair | Quiet 1 s spread (Hz) | Load 1 s spread (Hz) | Quiet 60 s spread (Hz) | Load 60 s spread (Hz) |
|---:|---:|---:|---:|---:|
| 1 | 0.911 | 0.380 | 0.346 | 0.048 |
| 2 | 0.439 | 0.498 | 0.078 | 0.080 |
| 3 | 0.403 | 0.416 | 0.106 | 0.075 |
| 4 | 0.497 | 0.897 | 0.036 | 0.406 |
| 5 | 0.721 | 0.478 | 0.248 | 0.055 |
| 6 | 0.497 | 0.391 | 0.074 | 0.074 |
| 7 | 0.323 | 0.472 | 0.072 | 0.046 |
| 8 | 0.482 | 0.327 | 0.089 | 0.060 |
| 9 | 0.549 | 1.003 | 0.100 | 0.328 |
| 10 | 1.011 | 0.600 | 0.226 | 0.106 |
| 11 | 0.498 | 0.958 | 0.022 | 0.417 |
| 12 | 0.932 | 0.625 | 0.359 | 0.098 |
| 13 | 0.471 | 0.320 | 0.075 | 0.048 |
| 14 | 0.343 | 0.481 | 0.065 | 0.055 |

The load-minus-preceding-quiet change in one-second population spread is
positive for seven pairs and negative for seven. Its median is -0.047 Hz; the
sign balance and time sequence provide no evidence of systematic load
broadening. In particular, elevated load spread in pair 9 is followed by an
elevated quiet segment in pair 10, and the same pattern recurs across pairs 11
and 12. All 28 declared segment spreads remain below the 1.5 Hz coarse
architecture screen.

Across the complete declared interval, official one-second counts have mean
15,999,996.927 Hz, population standard deviation 0.777 Hz, and range
15,999,995 to 15,999,999 edges. The corresponding non-overlapping 10-second
and 60-second population spreads are 0.548 Hz and 0.517 Hz. These reproducible
statistics describe the end-to-end ECS/GPS/capture observation; they do not
isolate firmware jitter or establish absolute frequency accuracy.

### Overnight integrity result

- Every one of the 16,798 declared `CNT` rows is traceable and reconstructs
  exactly from 16,799 adjacent, same-session raw cumulative `SNP` boundaries.
- The first snapshot is used only as an anchor; no snapshot is paired late or
  retroactively, and there is one continuous session.
- All runtime identity/configuration fields match the freshly flashed v4
  artifact. `backend_qualified=false`, observe-only mode, and disabled
  actuation remain proven in the recorded status.
- The run contains 17,646 rows each of `REF`, `CNT`, and `SNP`, and 339,040
  status rows. Snapshot high-water is one word and final depth is zero.
- Capture drop, PPS-boundary drop/gap/duplicate/overflow, invalid-snapshot,
  overwrite, continuity-loss, RX-stall, DMA error/stopped, FIFO, ring, parser,
  malformed-input, and reconnect counters remain zero.
- Four Arduino/RP2040 microsecond-timer rollovers are crossed without a false
  outage or count-continuity break. No PPS missing/restored transition occurs.
- Capture stopped cleanly after the scheduler completed. The `COMPLETE` marker,
  sealed snapshot, hashes, and post-seal validation all pass.

The standalone v2 analyser reports `failed` because this nominal overnight run
contains neither an injected fault reason nor a post-fault recovery sequence:
those are the only two failed acceptance checks. All 14 applicable nominal-run
acceptance checks pass, including raw SNP/CNT parity, exact traceability,
sealed evidence, duration, segment sizes, the architecture-spread screen, zero
capture/storage counters, startup inhibition, and runtime identity. Fault
classification and two-snapshot recovery are supplied by the separate
pseudo-PPS campaign; they are not falsely inferred from a quiet run.

Disposition: **pass — sustained digital architecture and load integrity;
accepted observe-only measurement-backend qualification, with actuation still
disabled**.

## Remaining limitations

The installed ECS fixture cannot control PPS phase or oscillator duty, so the
physical phase/duty sweep is **not tested: source capability unavailable**. It
is non-blocking for progression but is not converted into a pass. The modeled
PIO sweep does not substitute for pad-level threshold and metastability
measurement on a capable future fixture.

The strict pseudo-PPS campaign also retains its accepted 10 microsecond
width-only narrow-glitch miss. A rising-edge-only observer cannot detect a
short high pulse when the next rising edge remains on cadence; pulse-width
capture would be required to close that case. Neither limitation changes the
zero-loss and exact-reconstruction result established by the real-GPS runs.
