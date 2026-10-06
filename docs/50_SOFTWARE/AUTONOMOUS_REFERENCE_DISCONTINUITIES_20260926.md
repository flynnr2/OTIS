# Retained-reference discontinuity investigation — 26 September 2026

## Finding and decision

The 72-hour recording contains two distinct phenomena. **216 of 217 reference
holds are reproduced exactly by conservative recognition-time uncertainty
rejecting otherwise near-nominal recorded boundaries.** One earlier isolated
hold has genuinely non-nominal raw intervals and counts. It is not explained by
the same mechanism.

The clustered losses establish a firmware service/observability limitation under
the intended workload. The leading specific cause is synchronous ten-second
Core1 timing-health publication postponing FIFO-empty polling. The source path,
cadence, raw uncertainty and report correlation support that attribution, but
retained telemetry does not directly measure that function's execution interval.
Do not report a measured Core1 burst duration or a proven receiver outage.

The selector correctly withheld qualification under its frozen policy. Do not
widen that policy, replace raw timestamps with expected one-second values, or
infer a narrower timing bracket from D8 counts. The next repair should bound the
periodic work on the timing core while retaining coherent status snapshots and
normal capture servicing, followed by a deterministic collision regression and
the shortest affected physical gate. This investigation changes no firmware.

The [finite observation result](AUTONOMOUS_72H_RESULT_20260926.md) remains valid
with its explicit qualification limitations. This finding is evidence against
unconditional long-term adoption of the present service arrangement, not a reason
to repeat the successful acquisition to repair its offline analysis. Fault-mapping
approval remains conditional.

## Confirmed clustered mechanism

The cluster spans source SNP ordinals **126928 through 129108**. In the firmware
`rp2040_timer_us64` experiment domain, its first hold begins 112519.215056 seconds
after AUTO acceptance; the last recovery is at 114708.203317 seconds after entry.
The 216 recorded hold intervals total **1942.768465 seconds** within that period.
The later metadata hold is a separate episode and is not part of this cluster.

Every affected SNP has status zero and continuous source identity. Its adjacent
FIFO-service interval is 999984–1000015 ticks in `rp2040_monotonic_us32`.
The D8 downcounter differences are 10000000 on 206 occasions, 9999999 on six,
and 10000001 on four. These are recorded counts, not an independent electrical
PPS timestamp or a calibration of the local microsecond clock.

Recognition uncertainty is **1287–12719 microseconds**, compared with the frozen
±1250-microsecond acceptance band. For service-coordinate difference `d`, opening
uncertainty `u0`, and closing uncertainty `u1`, the selector requires the complete
possible interval `[d-u1, d+u0]` to fit `[998750,1001250]`. It must reject a bracket
that straddles that boundary even when the point service interval is nominal.

For example, SNP126928 has service delta 1000001, current uncertainty 12719 and
previous uncertainty 177. The admissible recognition interval is therefore
`[987282,1000178]`, which fails the unchanged lower bound. At the tail of the
cluster SNP129108 has delta 1000013 and uncertainty 1287, giving a lower bound
998726: still outside the permitted range by 24 microseconds.

The firmware uncertainty is the interval from the last proven FIFO-empty
observation to FIFO-read service, including its one-microsecond allowance. It is
**not measured interrupt latency**. A long interval between empty polls can widen
it while the PIO word and count remain preserved. Neither a zero SNP status nor
zero delivery-drop counters guarantees a sufficiently narrow timing bracket.

## Exact replay and recovery cadence

The existing native `tests/cpp/reference_acceptance_harness.cpp` was compiled
against the unchanged frozen headers and run on all **259216** retained SNPs,
using the exact generated policy: nominal 1000000, tolerance 1250, acquisition 8,
maximum edge rate 133000000, reference flags 16, exclusion limit 8, maximum count
span 1200000. REF records were paired in retained order with SNPs and all service
timestamps matched exactly; every REF flag was 16. The REF presentation ordinal
is consistently 1000 above the internal SNP source ordinal, so those namespaces
were not conflated.

The real selector returns:

- 216 `qualification_lost:observation_age_ambiguous` outcomes.
- One `qualification_lost:late_boundary` outcome.
- Four acquisition restarts during the isolated disturbance.

**All 217 loss outcomes match the retained invalid RPH acceptance epoch and
closing source snapshot identity exactly, in order.** Sampled PPS-gate status
independently reaches loss_count 217 and retains the corresponding late-boundary
and observation-age reasons. This is replay of the real selector, not a synthetic
approximation of its decision rule.

Replay starts from a recording attached to an already tracking instrument. Its
cold initial state consumes nine recorded boundaries to seed and acquire, so its
accepted-span count is nine below the live recording's count. No claim is made
about reconstructing the missing pre-attachment state, CPU service polls, or
unrecorded physical edges. Those limitations do not affect the later exact loss
matches.

Among consecutive clustered failures, 213 source-ordinal separations are 10,
one is 20 and one is 30. Loss, a new seed and eight clean acquisition intervals
explain the repeated approximately ten-second qualification/recovery cycle.
Most resulting acceptance epochs emit no APS span. The five APS-emitting epoch
labels 1, 6, 7, 221, 222 do not mean only five epochs were instantiated.

## Timing-core work: supported attribution and limits

`publish_dual_core_timing_health()` runs every 10000 ms after snapshot drainage in
`loop1()`. It synchronously publishes capture, PPS-gate, forwarded-monitor and
instrument status. The chain formats and copies many fields before returning
to the next FIFO-empty poll. Queue admission is nonblocking; the source does
not establish a USB-backpressure wait inside this function. Environmental I/O
runs on Core0 and is not this ten-second Core1 operation.

All 216 wide-bracket snapshots align with the corresponding periodic health
report, with its captured boundary identity one source snapshot earlier. Each
FIFO-read coordinate falls inside that report's **Core0 delivery/formatting**
interval; the recognition lower bound precedes its first displayed timestamp
by 390–639µs. This is strong cadence and identity correlation, not a direct
measurement of Core1 execution.

The important limitation is explicit in the producer-to-consumer path:
`publish_dual_core_timing_status()` creates a producer timestamp, but
`drain_dual_core_timing_outputs()` passes only component/key/value/severity/flags
to `emit_status_direct()`. The producer timestamp is discarded. The STS record
therefore gets a new Core0 formatting timestamp. The observed 121–181ms complete
report delivery spans must **not** be described as Core1 publication durations.
Nearby narrow-bracket SNPs also overlap those delivery spans.

LAT stage 0 begins at FIFO read and ends at foreground consumption; it excludes
the earlier recognition bracket. Later in the same region, its retained maximum
reaches 12623µs at SNP129298. This supports the presence of millisecond-scale
foreground service gaps but does not identify a particular call site or convert
SNP uncertainty into physical edge-to-CPU latency. LAT summaries retain selected
samples and diagnostic drop counts; they are not exhaustive execution traces.

The cheapest next discriminating verification is a deterministic PPS arrival
inside the actual periodic publication path, asserting both the retained empty
bracket and the first dependent qualification result. A repair should separate
coherent snapshot capture from lengthy output preparation, or service the timing
owner between bounded publication steps. Preserve the current timing policy and
evidence; simply adding a more permissive acceptance threshold would hide the
problem.

## Earlier isolated disturbance

The first hold begins 51183.546293 seconds after AUTO and lasts 18.007176 seconds.
It begins with SNP65594; unlike the cluster, uncertainty remains narrow.
Representative adjacent raw observations are:

| Closing SNP | Service delta (µs32) | Uncertainty (µs) | D8 edges   |
| ----------- | -------------------- | ---------------- | ---------- |
| 65594       | 1189190              | 149              | 9430964    |
| 65595       | 2810777              | 112              | 6290275    |
| 65596       | 2000000              | 53               | 11195911   |
| 65601       | 108528               | 40               | 1085429    |
| 65602       | 891460               | 131              | 8914571    |

The selector correctly reproduces a late boundary and four acquisition restarts.
This evidence distinguishes the episode from the conservative-bracket cluster,
but cannot identify the electrical source: receiver PPS, oscillator/input path,
PIO recognition under abnormal D8, or an external intervention. No FIFO stall,
source-sequence gap, ring overflow or capture fault is recorded. Do not equate
intact records with proof of uninterrupted physical signals. Preserve this
unresolved episode for targeted review; no broad hardware campaign follows from
this offline finding alone.

## Reproduction and preserved artifacts

Original return ZIP SHA-256:
`66f5feb9bba972b294adc8c4eed403da3d583d30ad2d6f7a313bfb2d3affa2f1`.
Firmware acquisition source 7c083d7 uses unchanged input closure
`e00d4d02522405321c16046f796127306a178d3d82d3d031f72fecde13ea1a39`.
The original 34-file inventory remains
`884ad3aedc2560e00bfca5f03efd728fbb0e96e46730b406d4c0c6f3edd567b4`.

Derived work is under `runs/autonomous-72h-return-20260926/discontinuity-review/`:
`investigate.py` reassembles the raw segments and extracts SNP, phase, status and
LAT evidence; `replay.py` feeds the existing native selector; `correlate.py`
assesses periodic report delivery overlap. `FINDINGS.json`,
`selector-replay.json` and `burst-correlation.json` retain the exact findings.
The shared investigation archive includes the scripts, derived results, source
identities and this report, with its own checksum. Original raw files, original
summaries and the previously sealed reanalysis package remain unchanged.

This was a bounded offline investigation. No serial connection, reset, flash,
new physical acquisition or acceptance-policy modification occurred.
