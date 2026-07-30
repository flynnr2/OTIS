# Phase 5 PPS-Gated Backend Bench Run 001 Results

## Result and scope

**The authoritative post-reset candidate session passed the bench legs that
were exercised.**

This result covers boot acceptance, startup inhibition and recovery, sustained
candidate observation, quiet-versus-service-load capture, missing-PPS
detection, zero-count detection, and post-fault recovery. It does not claim
final backend qualification. Controlled duplicate, short, and long PPS
stimuli, independent-metrology comparison, jitter disposition, aperture
measurement, and combined uncertainty remain open.

The safety state remained:

```text
status.control_ready=false
status.actuation_enabled=false
no PPS/count-derived DAC write was authorized
```

## Authoritative session boundary

The rig and oscillator had been powered continuously for more than 24 hours.
The host capture tool was started, after which Arduino IDE serial-port
contention disturbed the initial capture session. The IDE was closed and the
Nano RP2040 Connect was then manually reset.

The resulting complete `BOOT` record defines the authoritative test session.
All declared startup, comparison, load, and fault ranges occur after that
reset. The earlier disturbed session remains preserved and is not silently
deleted, spliced, or treated as qualification data.

The generic run validator reports two sessions and malformed/interleaved CSV
rows in the first session. Its reported malformed `REF`, `CNT`, and `STS` row
positions all precede the second-session BOOT/sequence restart. Those findings
document the pre-test serial-ownership disturbance; they do not describe the
post-reset comparison interval.

## Boot and safety acceptance

The post-reset boot evidence reported:

```text
firmware/config_id=phase5_pps_gated_qualification_v1
firmware/git_commit=1095a16dc0c4e6f9ce875032fbe64209c2832b41
build/tcxo_counter_backend=pps_gated_ratio
build/enable_dac_ad5693r=0
build/enable_h1_dac_sweep=0
capture/pps_gated_ratio_init=ok
resource_registry/valid=true
resource_registry/complete=true
resource_registry/conflict_count=0
resource_registry/binding_failure_count=0
resource_registry/pio_sm_claim_count=1
resource_registry/dma_claim_count=0
```

No `BOOT_FATAL` occurred.

The board-reported firmware hash was `1095a16dc0c4e6f9ce875032fbe64209c2832b41`.
The host checkout used during the run reported
`0e35bbe525c3c839b40ce749a040183ec3c640e5`, the commit that checked in the
Phase 5 Arduino IDE defaults. The behavioural result remains valid, but the
operator must confirm the exact checkout/upload chronology and describe the
board hash as boot-reported provenance rather than silently assuming it names
the complete IDE build tree. Exact source/boot provenance reconciliation
remains required before formal sealing.

## Startup and stable comparison

The candidate count sequence advanced at the expected nominal one-window-per-
second cadence. Startup control eligibility remained false through the 600 s
inhibit and returned true at `count_seq=604`, with:

```text
reference_validity=valid
reference_reason=reference_valid
count_validity=valid
count_reason=count_valid
control_eligible=true
```

The declared stable candidate interval is:

| Field | Value |
|---|---:|
| Comparison start UTC | `2026-07-29T22:38:18Z` |
| Comparison end UTC | `2026-07-30T07:50:09Z` |
| First candidate `count_seq` | 728 |
| Last candidate `count_seq` | 33838 |
| Candidate windows | 33111 |
| Elapsed duration | 33111 s |

The exact agreement between elapsed seconds and inclusive sequence span is
positive continuity evidence. At the end of the stable interval:

```text
pps_gate/control_eligible=true
pps_gate/reference_validity=valid
pps_gate/count_validity=valid
pps_gate/rejected_window_count=0
pps_gate/missing_pps_count=0
pps_gate/pps_interval_anomaly_count=0
pps_gate/count_saturated_count=0
```

Firmware capture status ended with `dropped_count=0` and `error_flags=0`.

## Baseline and service-load legs

The declared service-plane ranges are:

| Label | Mode | First `count_seq` | Last `count_seq` | Windows |
|---|---|---:|---:|---:|
| baseline | baseline | 728 | 1413 | 686 |
| serial_status_load | load | 1443 | 2159 | 717 |

During the load leg, the host issued 300 read-only `CONFIG?` requests at
two-second intervals. Eligibility remained true. The 29 observations between
the declared ranges are intentionally outside both segments.

The final baseline-to-load mean-shift metric remains to be computed from the
authoritative session-scoped data.

## Exercised fault and recovery legs

### Missing PPS

Two physical missing-PPS events were exercised; the first was an unmarked
preliminary injection and the second was the primary marked test. Evidence
included:

```text
reference_validity=invalid
reference_reason=reference_missing_pps
control_eligible=false
missing_pps_count=2
```

After restoration, valid reference observations returned while eligibility
remained inhibited until the clean-window recovery requirement was satisfied.

### Zero oscillator count

The conditioned oscillator observation was disconnected at the candidate input.
Seven bounded zero-count windows were preserved with:

```text
count_validity=invalid
count_reason=count_zero
control_eligible=false
```

After restoration, two valid windows remained ineligible and the third clean
window restored `control_eligible=true`. The final
`rejected_window_count=12` is consistent with the five missing-PPS/re-anchoring
windows plus seven zero-count windows.

No invalid bounded count observation was suppressed.

## Pre-test capture disturbance and generic report findings

The original run directory intentionally preserves the disturbed first serial
session. Consequently, whole-directory generic validation fails on malformed
and interleaved first-session rows. The aggregate generic report must not be
used for frequency statistics across both sessions.

The generic report also flags periodic non-positive raw gate subtraction near
RP2040 timer rollover. The Phase 5 qualification analyser uses modular
`rp2040_timer0` interval arithmetic; rollover disposition must therefore be
made with the Phase 5 path rather than the aggregate generic subtraction.

Late short and long PPS intervals in the aggregate report occurred during
manual disconnect/reconnect fault work outside the declared stable comparison.
They are retained as raw evidence but are not promoted to the controlled
duplicate/short/long fault legs.

## Open work

The following items remain open and are not failures of the completed legs:

1. Derive or analyse the authoritative second session without altering the
   preserved raw capture, with explicit source hashes and session provenance.
2. Reconcile the boot-reported `1095a16...` identifier with the exact Arduino
   IDE checkout/upload state and record that relationship explicitly.
3. Compute candidate population jitter and baseline-to-load mean shift over
   the declared stable ranges.
4. Compare the same UTC interval against an authorised independent
   measurement path and compute mean bias.
5. Measure counter aperture and populate evidence-backed uncertainty.
6. Exercise controlled duplicate PPS, 0.625 s short PPS, and 1.5 s long PPS
   using an isolated programmable source.
7. Execute the separate reconnect run.
8. Seal complete candidate and independent evidence and run the deterministic
   qualification analyser.

Until those gates are complete, this run is correctly described as a
**successful scoped candidate bench test with open qualification work**, not as
final `qualified_with_limits` metrology.
