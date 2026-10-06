# Autonomous 72-hour observation

The operator authorized preparation of this experiment after the
[short physical gate passed](AUTONOMOUS_SHORT_GATE_RESULT_20260923.md). Physical
execution belongs to the bench Mac, using one verified frozen bundle and its
entry prompt. The experiment does not impose campaign budgets or host leases
on ordinary instrument operation.

## Question and finite boundary

Observe sustained reference qualification, hybrid decisions, bounded
corrections and their response classifications, recoverable holds, and retained
evidence continuity over 259,200 firmware seconds of selected AUTO operation.
The existing frequency, phase, plant and hold policies remain unchanged. A
zero correction is a legitimate decision; no minimum number of nonzero writes
is required. Qualified measurement coverage and time spent steering are reported
separately from the operational duration.

Attach to the already powered instrument, discover its current state and require
fresh HOLD, known in-envelope code, no pending write, exact build/policy identity
and advancing D14/D8 capture before entry. Do not assume the short gate's final
code or boot session still applies. The experiment does not request a reset,
reflash, startup-code write or takeover of an existing operation.

Submit one AUTO request with dwell 259200 through the sole recorder. Require its
exact accepted ICM and a causally later complete status proving command completion
and the effective `operating_end_ticks`. Persist this identity before treating
entry as established. A newly sequenced retry would renew the deadline and is
forbidden. Host clocks never replace the exact firmware counter-domain deadline.

The firmware owns the transition to HOLD. A private correction may be cancelled;
an already released write must resolve under its independent two-second bound,
with its application identity retained. Observe the same session, exact stored
endpoint, HOLD, no pending write and known final code before normal recorder
closure. The recorder's endpoint alone never establishes a static actuator.
A latched firmware fault may inhibit writes while retaining the displayed AUTO
mode and rejecting HOLD; classify this as fault-inhibited and review-required,
not successful timed HOLD.

## Local unattended authority

The user authorized durable local supervision requiring no active Codex turn,
terminal or model/API budget. The firmware remains the only operating owner;
the recorder remains the only host serial owner. A finite experiment coordinator
selects the agreed mode, observes evidence and completes the local evidence
package. It is removable qualification tooling, not a required instrument service.

Poll authoritative local evidence every second in the frozen 72-hour plan.
Retain material transitions and unresolved escalations in durable local files.
Notifications are optional and silence never grants authority. Known reference
and metadata holds recover only under the existing firmware's fresh causal
qualification rules, without deadline renewal. Controller and integrity faults
are never cleared automatically.

The frozen review policy may submit at most one explicit HOLD for a demonstrated
unknown decision-bearing contradiction when fresh command identity is available.
It must retain the exact pending action, let a released write resolve, and require
exact completion evidence. It never automatically resumes AUTO. Stale or missing
identity cannot justify guessing a session or replaying a request. Preserve
capture and the retained escalation when a HOLD cannot be causally issued or
confirmed. Missing or stale output alone is a coverage escalation and does not
authorize HOLD, including after output returns. Restored delivery permits renewed
observation while retaining the gap for review; it does not clear a genuine
review HOLD. A counter showing delivery loss alone does not authorize HOLD.

A monitor failure cannot kill or restart the recorder or firmware. Retain its
failure independently, keep the coordinator's evidence checks running, and
preserve an unresolved review finding. No process-liveness-only success claim,
blind restart, reset, flash, abort, command replay or deadline extension is allowed.
The detached arrangement must survive invoking-terminal loss; it does not promise
recovery after computer power loss, reboot, storage loss or destruction of the
coordinator itself. The preloaded firmware endpoint remains independent of those
host failures. Prevent idle system sleep for the local acquisition without
changing global operating-system settings.

## Completion and evidence

On a proven normal endpoint, close the recorder through its bounded local request,
wait for clean writer/monitor closure, verify raw segments, analyze retained
identities and sequence continuity, and produce a checksummed ZIP automatically.
Keep acquisition local to `runs/`; publish only closed evidence to
`~/Documents/OTIS_DATA/`. Verify the copied ZIP and report local placement
separately from arrival on the development Mac.

The result separates entry, physical acquisition, endpoint, raw integrity,
analysis, sealing and exchange-copy outcomes. It reports applications, decisions,
responses, hold/recovery findings and all source/sequence gaps. Hash integrity
proves retained bytes, not completeness, causality or scientific acceptance.
Unresolved findings survive completion; a finished observation is not blanket
approval of the controller or fault mapping.

An unproven endpoint retains capture and the unresolved escalation instead of
inventing a clean closure. A deterministic offline analysis or packaging failure
after confirmed closure can be repaired and replayed against unchanged evidence;
it does not by itself require another 72-hour acquisition. Preserve the failed
result and old/new tool identities.

## Verification boundary

Rehearse the actual detached coordinator, single recorder, independent monitor,
mode receipts, finite endpoint, rotation, analysis and archive-copy path using a
synthetic PTY instrument and accelerated dwell. Leave review requests unanswered
across a simulated decision and released-write boundary. Exercise metadata
recovery, explicit HOLD completion, monitor failure, missing or stale evidence,
parent-terminal loss and a fault-inhibited endpoint. Native firmware regressions
cover the actual owner/mailbox/executor transitions that the PTY cannot establish.

The short physical gate remains evidence for its exact firmware and claims. A
host-only coordinator does not require a rebuild when the complete firmware input
closure is unchanged. A demonstrated output-path repair does require its affected
firmware build and shortest relevant integration gate; do not silently label a
new image physically qualified by the prior image's result.

## Direct-output evidence contract

The short-gate review localized attached AUTO drops to optional BMP280 ENV
rows, with no observed attached timing/control sequence gaps. Reuse the same
firmware. Preserve all delivered ENV rows and classify gaps from actual neighboring
records; do not assume every future loss is environmental. Environmental gaps
limit correlation and replay claims but do not veto firmware control. Retain
aggregate firmware counters as summaries, alongside per-record sequence evidence.
Counters can lag their last observed loss and do not count sampling that never
occurred. Report unknown periods explicitly.

## Entry and offline commands

The handoff contains a plan template with fixed policy and timing fields. After
passive discovery, fill its device, local run directory, shared return directory
and freshly observed boot session. Paths are absolute; acquisition and output
locations are separate. Entry independently rechecks the discovered state.

```sh
python -m host.otis_tools.unattended start --plan /absolute/path/plan.json
python -m host.otis_tools.unattended status /absolute/path/run
```

The start operation returns after its bounded entry check. Require `running`
with confirmed command/deadline and healthy local capture, not just a process
identifier. A review-required entry retains evidence and is not permission to
repeat start or select another AUTO request. The frozen plan bytes and their
hash are retained in the run directory before command submission.

After recording has closed, local packaging can be retried without serial I/O:

```sh
python -m host.otis_tools.unattended finalize /absolute/path/closed-run
```

For a verified evidence copy relocated from another Mac, specify its new output
location explicitly; the original plan remains unchanged as provenance:

```sh
python -m host.otis_tools.unattended finalize /absolute/path/extracted-evidence --output-dir /absolute/path/reanalysis-output
```

The package carries raw integrity bindings, frozen coordinator chronology,
analysis identity and findings. A changed analysis produces a distinct artifact;
previous results remain available. Automatic packaging does not establish
qualified measurement coverage or scientific acceptance.

## Preparation verification — 23 September 2026

The full current suite passed **427 tests in 56.77 seconds**. The 38 focused
recorder, authority, coverage and analyzer tests include exact 72-hour integer
deadlines, causal receipts, no ambiguous replay, bounded known-not-written HOLD
admission retries, output-loss-only coverage warnings, and portable offline
reanalysis. The actual analyzer also reproduced the retained short-gate ENV gaps
and exact application joins without altering those raw files.

The final normal operational rehearsal exercised the actual detached CLI,
recorder, monitor, local command socket, Mac sleep-prevention process, bounded
cohort-complete closure, analysis and verified ZIP creation. The launcher exited
while the coordinator remained in a separate OS session. Its result was
`completed_observation` with no review findings.

The final review rehearsal introduced a contradictory deadline during a synthetic
released write, terminated the monitor, and left review unanswered. Exactly one
HOLD was submitted; the exact IWR/IAP pair joined; capture continued through review.
Explicit fixture-only cleanup then produced a package retaining monitor failure
and review findings, without claiming a normal timed endpoint. Deployment does
not inherit that test-cleanup authority.

Both operational rehearsals used a synthetic PTY instrument and modem-control
shim. Native tests exercise actual firmware owner/adapter/executor logic; the
unchanged image's short gate supplies its limited physical evidence. Neither
substitutes for the real 72-hour duration. Earlier fixture ordering failures and
the recorder's corrected cohort-closure defect are retained in the handoff's
verification directory. The closure defect was caught in rehearsal before this
physical run; no repeat of successful short-gate acquisition was required.

Firmware input closure remains exactly
`e00d4d02522405321c16046f796127306a178d3d82d3d031f72fecde13ea1a39`.
The existing audited image and resource/PIO results are reused; no firmware
rebuild or reflash is required by this host-only change.
