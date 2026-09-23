# Autonomous instrument: short physical integration gate

The operator conditionally approved the fault mapping on 23 September 2026 and
authorized progression. This gate tests the merged autonomous instrument on the
bench before an extended run. Allow roughly two hours, plus preparation. It is
not a 72-hour qualification or unconditional approval of the fault mapping.

## Frozen inputs and preflight

Use the supplied source, firmware artifacts, verification logs and manifest as
one immutable bundle. Verify SHA256SUMS before use. The image was built from
firmware audit revision `82f60eae9cbbfc7f6695cc47e9484f9191c65609`:

- Firmware input SHA256: `e00d4d02522405321c16046f796127306a178d3d82d3d031f72fecde13ea1a39`.
- Configuration SHA256: `7b971d9a5c2fa63abd20037be23b94e117d0a73f092644b10b45abb08f407585`.
- UF2 SHA256: `60e94ea2cf4f43b4b7c0a14287940dbd6f4fd9c84f4d9bece0f965a7990d013d`.
- Target: Nano RP2040 Connect, RP2040 core 6.1.0, 133 MHz.

The later source snapshot includes documentation and a host regression; its
firmware input bytes must match the artifact manifest. Reuse the verified image;
do not silently substitute a rebuilt image. The supplied 394-test release result,
PIO proof and 15-test host-path regression establish their stated software
boundaries. Hash checking is preflight; the PTY/native-serializer checks are not
physical firmware, cross-core or analog qualification.

Before physical entry, identify the actual board and serial endpoint, confirm no
existing serial owner or active experiment, and record power arrangements. Do not
steal an active acquisition. Preserve D14 PPS, same-receiver GNSS serial, D8 input
and D9 forwarding. D10 is optional and cannot veto discipline. Upload the exact
UF2 using the installed board tooling, retaining the upload transcript and a
bounded upload timeout. A failed or ambiguous upload requires review, not an
unbounded retry loop.

## Recording and commands

Use Python 3.10 or newer with the supplied project's dependencies. Run from the
bundle's `source` directory, with local acquisition directories outside the
immutable bundle. Retain interpreter and dependency versions. Each segment has
one recorder and one read-only monitor, with stdout/stderr continuously drained
to files. For example, with PY, DEVICE and RUN explicitly set to observed paths:

```sh
mkdir -p "$RUN"
"$PY" -m host.otis_tools record --device "$DEVICE" --run-dir "$RUN" --duration-s 180 >"$RUN/record-result.json" 2>"$RUN/record-stderr.log" &
REC_PID=$!
"$PY" -m host.otis_tools monitor "$RUN" --poll-s 1 >"$RUN/monitor-result.json" 2>"$RUN/monitor-stderr.log" &
MON_PID=$!
"$PY" -m host.otis_tools status "$RUN"
```

Allow at most 30 seconds for fresh, complete status and progressing REF/SNP/CNT
observations. Compare `instrument.build_identity` to the input and configuration
hashes joined with a colon. Obtain SESSION from the current complete instrument
status; never reuse a boot session after restart. The first freshness observation
is only a baseline. Keep the controlling bench agent active, reading status and
monitor findings at intervals no longer than 10 seconds.

```sh
"$PY" -m host.otis_tools mode "$RUN" --session "$SESSION" --mode 1
"$PY" -m host.otis_tools mode "$RUN" --session "$SESSION" --mode 2 --code 43085
"$PY" -m host.otis_tools mode "$RUN" --session "$SESSION" --mode 3 --code 43086 --dwell-s 30
"$PY" -m host.otis_tools mode "$RUN" --session "$SESSION" --mode 0 --dwell-s 5400
```

These illustrate separate transitions, not a batch to issue without waiting.
`written_unconfirmed` proves only host submission. For each request retain the
exact command sequence, matching accepted ICM and a later complete status with
`completed_command_sequence` and the expected mode. For a physical write require
IAP with attempted/ok/accepted all 1, rejection 0, and matching boot/capture/request,
code and DAC epoch. Use one fixed 60-second host deadline per operation, including
retries for incomplete status. The firmware's independent released-write deadline
remains two seconds. Characterization's return to HOLD is a separate finite
transition: verify its deadline from the actual application, not host submission.

After each recorder's scheduled close, wait for the monitor to exit, inspect both
exit statuses and `recording_error`, then run `verify "$RUN"`. Hash verification
alone does not establish a clean recording. Recorder duration never stops firmware
steering. Do not interrupt a recorder merely to obtain an earlier segment ending.

## Physical sequence

1. Cold-start the uploaded instrument with no serial reader for 60 seconds,
   preserving the documented power topology. Record segment `boot` for 240 seconds.
   Require AUTO, known code 43085 (`0xA84D`), DAC epoch 1 and one application in a
   fresh boot session. Request HOLD, then FIXED_CODE 43086 (`0xA84E`), confirming
   each before continuing. This establishes a non-startup code for the restart test.
2. After orderly recorder closure, keep power on with no reader for 60 seconds.
   Record `reattach-fixed` for 120 seconds. Require the same boot session, fixed
   mode, known 43086 and unchanged application identity, with advancing capture.
3. After closure, warm-restart the firmware once, retaining GNSS/oscillator power.
   Leave it without a reader for 60 seconds. Start `auto-a`, recording 3600 seconds.
   Require a new boot session, AUTO and known 43085 at epoch 1/application count 1.
   Within the first 300 seconds, complete HOLD, FIXED_CODE 43085, CHARACTERIZE
   43086 for 30 seconds, its automatic return to HOLD, then AUTO for 5400 seconds.
   Retain the exact accepted AUTO identity and `operating_end_ticks`.
4. Observe qualification, selected estimates and at least one qualified IDC in
   `auto-a`. Existing warmup is 1800 seconds, post-write settling 900 seconds and
   selected support 600 seconds; metadata recovery can require two fresh windows.
   A few minutes is insufficient. No nonzero automatic correction is required:
   the measured error may legitimately require none. Any natural correction must
   have its exact application and subsequent consumer/decision evidence retained.
5. At scheduled `auto-a` closure, confirm AUTO's stored deadline remains in the
   future. Leave the powered instrument without a reader for 60 seconds, then
   record `auto-b` for 2700 seconds. Require the same boot session, AUTO and unchanged
   operating deadline. The code can legitimately change during this evidence gap;
   retain the current known state without inventing missing transaction history.
6. Require firmware transition to HOLD at the stored counter-domain deadline,
   resolution of any already released write within its own two-second limit, and
   a fresh status confirmation within 30 seconds. Continue recording capture and
   retained code through the segment's scheduled close. End this gate in HOLD.

If the mode sequence cannot finish within the first 300 seconds, or qualification
has not produced a supported decision before the first AUTO segment closes,
report the gate incomplete and review rather than silently extending the plan.
Host deadlines diagnose delivery; compare firmware deadlines only in their
explicit counter domain. Preserve command, observation and application ordering.

## Evidence and review

Trace a recorded fixed/characterization application through both phase and
frequency consumers and the first dependent selected estimate/IDC, matching code,
DAC epoch and causal observation frontier. Startup applications precede host
attachment: later status proves retained startup state, not the missing startup
IAP timestamp. IAP proves successful driver completion, not an independent analog
DAC readback. D9's physical forwarding requires direct bench observation if that
claim is reported; firmware telemetry alone cannot establish its pin waveform.

Record actual qualification holds and fresh recovery if they occur. HOLD followed
by AUTO is not a metadata-fault recovery test. Do not introduce wiring faults or
claim a physical recovery case passed when it was not exercised. Distinguish
physical observations, software regressions and unexercised claims in the result.

A host discrepancy, missing acknowledgement, stale status or contradictory identity
inhibits further normal requests and requires review while capture remains alive.
It does not authorize automatic abort, reset or teardown. Retain exact pending
identity and let the firmware's independent bounded behavior apply. Do not silently
extend a finite segment; review any needed recording continuation before its end.
An operator-directed priority HOLD remains available using a fresh established
session. Firmware faults require diagnosis, not clearing by repeated mode requests.

Return closed recordings, manifests, checksums, command transcripts, monitor logs
and a concise result through the bundle's specified shared return directory.
Explicitly list intentional evidence gaps and unresolved fault-mapping findings.
Assess this gate before selecting the extended run; no extended run is started
by this procedure. Ordinary indefinite AUTO remains available by explicit mode
selection with dwell zero and has no campaign budget or host lease.
