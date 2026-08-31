# Hybrid 72-Hour Attempt 7 Evidence-Queue Terminal

## Verdict

Campaign19 Attempt 7 is a valid but incomplete physical acquisition. It
established healthy integrated D14/D8 timing, D9/D6 continuity, GNSS metadata,
and CX323 hybrid decision evidence from the qualified origin at
2026-08-31T19:43:11Z through the first actionable correction boundary at about
2026-08-31T22:43:11Z. It did not establish an applied controller transaction
or the required 72-hour duration.

The terminal was a deterministic firmware platform defect, not a scientific
controller rejection and not an acknowledgement-observation race. The
authoritative retained package is
`runs/d9_adaptive_steering_integration_20260828/long_runs/hybrid_72h_attempt7`.
Its capture retained 72,835,585 bytes and 604,856 parsed lines with zero parser
errors, telemetry drops, or reconnects before the terminal sequence.

## Causal evidence

The first actionable CX323 decision requested +1 code, from `0xA84D` to
`0xA84E`. On that same selected-600 boundary Core 1 synchronously produced:

1. diagnostic EST, selected EST, and tight-deadband evidence: three frames;
2. AHY, AH2, ACT request, AT2, and AHM: five frames;
3. the trailing CTL frame: one frame.

The configured evidence queue held eight frames. The three-frame prefix plus
the five-frame request lifecycle filled it. Publishing CTL then latched
`evidence_queue_exhausted`; the retained high-water changed from seven on
ordinary selected boundaries to eight at the request boundary, and no CTL
followed the five request records. Firmware was already fail-static before the
host submitted `ACTIVE EVIDENCE 1 1`. No correction was accepted or applied;
the last confirmed state remained `0xA84D`, DAC epoch 1.

The host subsequently reported firmware consumption as unconfirmed before it
examined the already-present partition fault. That diagnosis obscured the
firmware cause but did not cause it.

## Attempt 8 correction

The evidence capacity is now derived from complete legal selected-boundary
frontiers rather than an isolated active burst:

- normal request frontier: 3 + 5 + 1 = 9 frames;
- normal response frontier: 3 + 3 + 3 + 1 = 10 frames;
- request plus terminal native-fail evidence: 3 + 5 + 1 + 1 = 10 frames.

An AwaitingResponse boundary explicitly cannot create another request, and a
native-fail transition returns before response completion. The evidence queue
therefore has an exact capacity of ten. Active admission reserves the
guaranteed trailing CTL before committing any request, response, or fail
lifecycle. One unrelated retained frame beyond the derived frontier now causes
pre-lifecycle fail-static admission rather than a partial lifecycle.

The host retains an exact already-written acknowledgement as inflight while an
unchanged pre-submit firmware frontier persists. It observes one causally later
snapshot per supervisor pass, never resends the command, preserves record
order, and still fails immediately on contradictory request identity or phase
ordering. Firmware partition/fail-static health is checked before transaction
acknowledgement processing so a genuine firmware terminal cannot again be
misclassified as a host acknowledgement failure.

## Verification before refreeze

- 145 focused queue, active-firmware, transaction, and live-supervisor tests
  passed.
- 155 affected campaign, firmware-matrix, memory-budget, activation,
  operational-rehearsal, run, and CX323 controller/maintenance tests passed.
- The exact `cx323_d9_d6_72h_adaptive_hybrid` firmware profile compiled.
- Static dynamic memory is 157,120 bytes against a 157,286-byte maximum;
  runtime memory is 105,024 bytes against a 104,858-byte minimum reserve.

Attempt 8 still requires a clean exact build, a new immutable freeze, the full
operational-path rehearsal, auto-detected flash/readback, physical entry
qualification, and exact first request-through-response propagation before its
72-hour acquisition can be credited.
