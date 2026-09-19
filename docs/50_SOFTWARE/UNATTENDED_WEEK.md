# Seven-day unattended hybrid experiment

Preparation is offline on the development Mac. Physical launch is conditional on
satisfactory review of the latest bench experiment and explicit bench entry.
No firmware upload, reset, serial acquisition or DAC operation is performed here.
The current controller is retained; only its finite application/movement budget
is enlarged from 144/3,024 to 336/7,056. Its step, cadence, characterized envelope,
metadata requalification and transaction proof requirements are unchanged.

## Operating contract

- D14 is sole reference; D8 sole oscillator count. D10 is unimplemented and
  optional diagnostics have no control or terminal authority.
- Duration: 168 hours in host monotonic nanoseconds, starting after capture
  readiness. Setup and qualification consume that window. UTC cannot renew it.
- A 72-hour accepted-aperture checkpoint is nonterminal. Record aperture coverage,
  hold intervals, applications, responses and control state independently.
- New ARM admission closes 2,111 seconds before the endpoint to reserve response
  and downstream observation. No forced corrections, restore, automatic owner
  restart, session reset, retry, live extension or reflash is authorized.
- Healthy exact disarmed state permits normal closure. Missing/contradictory
  endpoint evidence retains a review hold and capture; the actuation deadline
  remains closed even if recording continues beyond seven days.
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
qualified-aperture checkpoints, review holds and low storage. It has no command
path. `heartbeat.json` exposes observer freshness; `status.json` and
`transitions.jsonl` retain meaningful changes. `owner.log` and `monitor.log`
retain process output. Monitor/publication errors do not kill/restart the owner.
Notifications are local files; there is no dependency on an email/cloud service.
The ordinary `monitor RUN_DIR` remains independently available if the observer
fails. The authoritative supervisor records full pending-phase/escalation details.

Physical launch requires at least 50 GiB free; a 10 GiB remaining threshold
produces a retained storage warning. No evidence is deleted to recover space.
At 115200 baud the raw serial bound alone is about 7 GB/week; CSV and replay
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
cover the changed budget and original policy paths. A PTY cannot establish real
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
