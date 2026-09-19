# 72-hour unattended hybrid experiment

Preparation is offline on the development Mac. Physical launch is conditional on
satisfactory review of the latest bench experiment and explicit bench entry.
No firmware upload, reset, serial acquisition or DAC operation is performed here.
The current controller retains its budget of 144 applications and 3,024 codes
cumulative movement. Its step, cadence, characterized envelope,
metadata requalification and transaction proof requirements are unchanged.

## Operating contract

- D14 is sole reference; D8 sole oscillator count. D10 is unimplemented and
  optional diagnostics have no control or terminal authority.
- Duration: 72 hours in host monotonic nanoseconds, starting after capture
  readiness. Setup and qualification consume that window. UTC cannot renew it.
- Accepted-aperture checkpoints do not end the host observation window. Record aperture coverage,
  hold intervals, applications, responses and control state independently.
- New ARM admission closes 2,111 seconds before the endpoint to reserve response
  and downstream observation. No forced corrections, restore, automatic owner
  restart, session reset, retry, live extension or reflash is authorized.
- Healthy exact disarmed state permits normal closure. A retained review request does not veto scheduled closure when static/disarmed
  state is independently exact; it remains in the terminal for later review.
  Missing/contradictory actuator or transaction endpoint evidence retains a review hold and capture; the actuation deadline
  remains closed even if recording continues beyond 72 hours.
- The controller and admitted host transactions run without reviewer availability.
  Recoverable receiver metadata anomalies hold corrections and automatically
  requalify using existing causal firmware/host gates. Unknown decision-bearing
  discrepancies hold new authority and retain pending-phase evidence. An
  unanswered review never times out into approval, abort or capture teardown.
- Firmware independently applies its existing bounded fail-static rules.
  Loss of the host/USB/board is not promised to recover automatically. A dead
  capture owner is reported as an observed fact; no replacement owner is started.

## Local process arrangement

`python -m host.otis_tools.unattended` takes the same arguments as `otis run`.
It creates a one-use sibling `RUN_DIR.unattended` directory and starts a detached
local observer, which starts the ordinary production runner and capture worker.
The launcher can exit and its terminal can close. The Mac must remain powered
and logged in; `caffeinate -ims` prevents idle/system sleep during supervision.
This does not promise survival of logout, reboot, power failure, or disk failure.

The observer reads capture/supervisor snapshots every two seconds. It retains
state transitions, evidence staleness (15 seconds), completed responses,
qualified-aperture checkpoints, review holds and low storage. It also detects
stalled supervisor lease service independently of continuing raw capture; its
bound includes the existing snapshot, command-acknowledgement and lease budgets. It has no command
path. `heartbeat.json` exposes observer freshness; `status.json` and
`transitions.jsonl` retain meaningful changes. `owner.log` and `monitor.log`
retain process output. Monitor/publication errors do not kill/restart the owner.
Notifications are local files; there is no dependency on an email/cloud service.
The ordinary `monitor RUN_DIR` remains independently available if the observer
fails. The authoritative supervisor records full pending-phase/escalation details.

Physical launch requires at least 50 GiB free; a 10 GiB remaining threshold
produces a retained storage warning. No evidence is deleted to recover space.
At 115200 baud the raw serial bound alone is about 3 GB/72 hours; CSV and replay
products require additional space. Check actual growth during initial bench
entry. Filesystem/storage failure cannot guarantee continued recording.

## Preparation and verification

Freeze one current spec, Intel-compatible firmware image and host toolset.
Run full current tests, the fixed image/resource audit and assembled PIO proof.
The operational rehearsal uses the real host owner and capture process over a
PTY. It exercises two progressive transactions and first consumers, metadata
hold/requalification, an unanswered review beyond a real lease cycle with capture
and leases advancing and no new SETUP/ARM, normal FIFO obstruction, independent
priority abort, drainage, analysis, sealing and registration. Run it through the
same detached wrapper and let the launching process exit.

Accelerated host deadline tests establish endpoint and no-restart behavior;
they do not establish elapsed physical duration. Firmware native regressions
cover the unchanged budget and original policy paths. A PTY cannot establish real
USB, firmware cross-core service, reference quality, or plant response. Retain the
live pre-actuation gates. Scientific qualification comes from the bench evidence.

## Bench handoff

The archive README supplies exact revision, archive checksum, firmware identity,
spec, receipt and retained verification paths. Extract the single `.tar.gz` from
`~/Documents/OTIS_DATA/` to a local directory. Use its exact Git checkout, compile
once with the pinned Intel toolchain and validate the reproduced image. Run the
delivered entry command once after the latest-result gate has been reviewed.
Never regenerate a spec/receipt or change hashes on the bench. Return an identity
mismatch for review. Do not repeat the development release suite or rehearsals.

Inspect the detached status and authoritative `monitor RUN_DIR` output at entry
until startup census and initial qualification/authority are proved. Confirm raw
and parsed evidence growth, sole serial ownership, and monitor heartbeat. Then
leave local supervision running without Codex. Explicit abort remains
`python -m host.otis_tools abort RUN_DIR`; submission and delivery are separate.
Retain failed analysis/finalization artifacts and replay complete immutable
acquisition later rather than repeating successful physical collection.
Return the closed evidence package and monitor logs as a single `.tar.gz` through
`~/Documents/OTIS_DATA/`. A local copy is not proof of arrival on the other Mac.

## Pre-write telemetry binding correction (19 September 2026)

The v2 host pre-write contract uses Core 1's emitted `capture.error_flags`,
`snapshot_ring_full_count` and `irq_budget_exhausted_count`, each exactly zero.
Receiver `metadata_control_eligible` qualifies metadata only; the exact ACTIVE
`setup_gnss_eligible`, `setup_reference_eligible` and `setup_partition_healthy`
gates remain mandatory, along with the existing authoritative D14/D8 capture
cohort gate before SETUP. Retired GPIO drop counters and receiver-owned raw PPS
eligibility fields are not part of the snapshot firmware's telemetry. Missing
current fields continue to inhibit authority. The fixed firmware is unchanged.

The original rehearsal manufactured absent keys from host expectations. A
producer-source regression now checks every required non-ACTIVE integrity and
GNSS key against firmware status emitters, independently of that fixture. This
checks source coverage, not physical publication or freshness; exact live gates
remain necessary. The detached launcher also creates the run parent before its
free-space check, without creating the acquisition directory or opening hardware.

The held bench attempt remains immutable evidence of a platform escape into a
campaign. This correction does not clear its hold, hot-reload its supervisor,
authorize teardown, extend its deadline or authorize a replacement launch. A
new frozen host spec and operational rehearsal are required. Preserve the
existing owner until an explicit operator disposition.

## Reference loss before the first qualified origin

A post-SETUP D14 reacquisition may wait without creating an irrevocable verifier
hold only before any qualified origin or ARM submission. The exact session,
confirmed setup code, DAC epoch 1, zero corrections/movement, clear transaction
and PHASE_QUALIFY state are required. Only acquiring/tracking and current-anchor
qualification differences are tolerated; missing/cohort/freshness, FIFO, capture,
partition, identity and actuator discrepancies remain review-required. Reference
loss/incomplete-aperture counters remain raw evidence, never reset or hidden.

The host records a startup reference wait and inhibits ARM until a complete fresh
600-accepted-sample estimate, coherent with both current acceptance epochs and the
retained session/DAC epoch, establishes the first qualified origin. Its closing
coordinate must be at least a full estimator interval after the retained loss
frontier in the declared wrapping counter domain. No interval from another epoch
is added, and no existing verifier hold is cleared. The original host deadline
and ARM closure reserve remain fixed. A subsequent discontinuity after the origin
still requires review; this is deliberately a startup repair, not general
mid-transaction recovery or permission to join qualified epochs.

The actual host PTY rehearsal now injects a startup reference qualification loss,
then requires recovery before its first ARM and two completed transactions.
A provenance-linked small fixture from the 19 September bench record separately
checks epoch changes and rejection of non-reference faults. The PTY models status
loss, not physical D14 loss; retained real telemetry covers the observed event.

## Host exception containment and ownership service

The supervisor catches ordinary Python exceptions at the diagnostic-cycle
boundary, preserves their traceback, inhibits new SETUP/ARM, and returns to
ownership service. Explicit abort remains a separate BaseException path. The
fallback foreground hold also calls the same admitted-lease service operation;
retaining a capture process alone does not prove lease service.

During review, lease renewal has its own bounded command operation. It neither
renews nor clears an expired evidence-acknowledgement deadline. An unresolved
normal command write still blocks subsequent normal commands, including leases;
firmware retains its independent bounded fail-static response to real transport
obstruction. No timeout authorizes replay or completion of ambiguous evidence.

The retired post-origin aperture-extension helper has been removed from the
live decision path; such discrepancies retain review rather than inventing
recovery authority. Rehearsal raises an actual AttributeError while the second
response is pending, then requires exact response completion, continuing lease
and capture service through unanswered review, and explicit orderly closure.

This repair is an interim containment boundary, not a new 72-hour launch claim.
The next architectural boundary is one host lifecycle service for ownership,
abort and closure, with scientific/transaction checks producing decisions and
holds without displacing that service. Preserve working capture/protocol/evidence
components; do not rebuild them without evidence of a defect.
