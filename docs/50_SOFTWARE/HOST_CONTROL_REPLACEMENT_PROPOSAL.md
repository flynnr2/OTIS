# Proposal: firmware-owned operation and a recording host

Consolidated 20 September 2026; accepted for implementation. The 23 September
working implementation makes this the default firmware policy, with optional
recording and explicit serial modes. Backward compatibility is deliberately
not retained. The running bench has not been flashed or physically qualified by
this work. Detailed [fault mapping](AUTONOMOUS_INSTRUMENT_FAULT_MAPPING.md)
remains subject to the operator's reserved long-term review.

Implementation choices: CHARACTERIZE is a single step of at most 21 codes and
1..86,400-second dwell ending in HOLD. Timed AUTO permits up to seven days;
ordinary AUTO has no duration limit. Command sessions use a 64-bit randomized
boot identity separate from capture session. See the current
[wire contract](../../data_contracts/otis_firmware_host_contract_v1.md) and
[host architecture](HOST_ARCHITECTURE.md) for executable interfaces.

## Decision and scope

Make autonomous hybrid discipline the normal boot policy, with other operating
modes explicitly selectable through serial commands. Firmware owns acquisition,
qualification, operating state, controller decisions, bounded DAC application,
response measurement, recovery and fault inhibition. Host presence is optional.

The basic host connects, records the ordinary evidence stream, and reports what
it can establish. It neither releases individual corrections nor keeps steering
alive through leases. An optional command interface requests instrument mode
transitions through the same serial owner. Autonomous operation is the default,
not the only capability or a separate controller implementation.

Deliver this as one finite firmware/host replacement before another extended
steering attempt. Do not first build the previously proposed mandatory host
instrument-service/decision-worker arrangement and then remove it. Keep useful
transport, parsers, recording, replay and analysis components; delete the old
supervisory lifecycle at cutover.

The scope includes autonomous startup, serial-selectable modes, reference-loss
recovery, independent output transport, an observational host and repeatable
qualification. It excludes controller retuning, predictive holdover, a general
framework, D10 capture implementation and new D9 divider hardware behavior.

## Inputs consolidated and what changes

This proposal incorporates the conversations **TODO? Clarify hybrid steering
authority** and **TODO? Plan extended hybrid steering run**, the prior draft of
this document, and [instrument ownership](INSTRUMENT_OWNERSHIP.md).

The extended-run discussion established useful requirements: operation without
Codex or a reviewer, explicit known recovery, retained unanswered diagnostics,
continuous evidence where resources permit, repeated-transaction verification,
real end-to-end reporting, and deletion of fragile supervisory machinery. Its
reported missing-method failure and stopped lease service demonstrate why host
scientific code must not be essential to instrument continuity. These are
reported failure lessons, not a new verification of the sealed acquisition.

The new direction supersedes three assumptions of that earlier proposal:

- A mandatory host decision worker is unnecessary for autonomous steering.
- Host storage acknowledgements and capture leases cease to release firmware
  corrections in the replacement protocol.
- A recording endpoint ceases to imply disarm or instrument shutdown. A requested
  instrument stop is a separate, explicit operation.

The operator's existing gate remains: no further extended bench attempt until
architectural consolidation is complete and verified. Short physical validation
of the replacement remains a separately authorized step after offline readiness.
Previously frozen campaigns and historical evidence keep their original meaning.

## One owner, with optional host clients

```text
D14 PPS + receiver metadata + D8 oscillator
                    |
       Firmware instrument state machine
       qualification / hybrid controller
       bounded DAC executor / response measurement
                    |
          D8 forwarded to D9

Firmware evidence --------> Optional recorder ----> files / replay / reports
Firmware command interface <--- explicit operator requests via serial owner
```

The timing fabric remains authoritative for capture. Core 1 owns selected
measurement and controller decisions; Core 0 owns GNSS/DAC device service and
physical application. Exact internal handoffs remain necessary. USB is an output
and command channel, never the internal actuator dispatch path.

There is at most one host serial owner. With no host there are zero host owners
and the firmware continues. During recording, commands use the recorder's bounded
command interface; a second tool must not open a competing serial descriptor.
Analysis and notification consumers cannot block the recorder. Heavy or fallible
live analysis runs separately only when requested, with no steering authority.

## Boot and restart policy

Proposed first-version behavior:

1. Start capture, bounded internal queue service and D8-to-D9 hardware forwarding
   without waiting for USB, GNSS qualification or a recorder. Firmware does not
   generate the oscillator arriving on D8. D9 forwards it while available; that
   fact alone does not establish discipline.
2. Begin a new instrument session, publish reset cause where available, load the
   fixed versioned policy/plant identities, and establish a known DAC code.
3. Run the existing bounded GNSS bootstrap and then its runtime receive service.
   Qualify receiver metadata alongside D14 PPS; serial arrival is not timing
   authority. Preserve the existing fixed receiver command restrictions.
4. Acquire fresh accepted D14/D8 evidence and enter frequency acquisition. Enable
   phase contribution only after the existing policy's qualification predicates
   hold, then perform repeated hybrid corrections without host participation.
5. Continue indefinitely within the instrument's fixed bounds, entering and
   leaving only explicitly defined holds and faults.

Operator decision: the first version uses an explicit startup write of the existing setup
code, `0xA84D`, on both cold start and firmware restart, within `0xA800..0xAB00`.
The value must come from one versioned boot-policy field, not a second hard-coded
host constant. This establishes provenance with the current driver's successful
write semantics; device presence alone does not establish applied code.

A warm restart therefore may change an already-steered DAC value. Record that
as a new session and discontinuity; do not claim bumpless restart, retained phase
history or continued lock. Verify this accepted startup behavior before deployment. Retained
code/readback recovery can replace it later only with demonstrated provenance.
No automatic reset loop is a recovery policy, and restart must not be used to
conceal a recurrent integrity fault.

Boot always selects autonomous discipline in this first version. Runtime mode
changes are session-local; there is no new persistent mode store. An operator
hold survives a host disconnect but not a firmware restart. Make this behavior
explicit in status/help. Host attachment must neither reset the board nor issue
startup writes; prove this for the actual serial-open implementation and board.

## Operating mode, controller state and reporting are separate

Proposed names below are semantic interface names, not an implemented wire API.
One instrument state machine and one DAC executor serve every mode.

| Operating mode   | Entry and behavior                                                           | Exit or completion                                             |
| ---------------- | ---------------------------------------------------------------------------- | -------------------------------------------------------------- |
| AUTO_DISCIPLINE  | Boot default; qualify, acquire frequency, then hybrid-track as eligible.     | Explicit mode change or firmware fault inhibition.             |
| OBSERVE_HOLD     | Inhibit new DAC writes; retain known code and continue measurement/output.   | Explicit resume; recoverable reference events do not clear it. |
| FIXED_CODE       | Explicit bounded code request, exact application, then measure at that code. | Explicit new code or mode change; no background hybrid writes. |
| CHARACTERIZE     | Execute a finite, validated stimulus/measurement plan using the same owner.  | Complete or cancel into OBSERVE_HOLD at last confirmed code.   |

OBSERVE_HOLD can be entered with unknown applied code, but must report it as
unknown. FIXED_CODE is deliberate open-loop operation within the characterized
envelope, not a way to bypass actuator integrity faults. Characterization plans
have a bounded number of steps, code range, slew/step limits, dwell/deadline and
explicit cancellation behavior. Freeze the first supported plan shape during
contract work; do not introduce a scripting language or arbitrary callbacks.
Once accepted, a plan has a firmware-owned lifetime and does not need host
keepalives. Losing the recorder degrades its evidence claim, not its execution
identity. A power/reset event ends the plan and follows the declared boot policy.

Within AUTO_DISCIPLINE, distinguish acquiring reference, frequency acquisition,
hybrid tracking, phase-degraded frequency-only operation, and reference hold.
Integrity-fault inhibition applies across all modes. Report requested mode,
effective state, active inhibition reasons and exact pending action separately.
A reference recovery clears only its own reason; it cannot clear an operator
hold, an integrity fault or a conflicting unfinished command.

Serial evidence detail is an independent setting. Initially retain the usual
full stream of measurements, decisions, applications, state and faults, updating
schemas where semantics change. Compact output is a later reporting profile;
selecting it must not select another controller. Future D9 integer division is
also an independent output configuration, not a steering mode. D10 remains an
optional external-event input, isolated from D14/D8 and actuation.

## Serial transitions and internal commit

Provide a small versioned command surface for status, mode selection, bounded
fixed-code application, finite characterization, cancellation/inhibit, explicit
fault-recovery request, and reporting selection when implemented. Unsupported
operations reject explicitly. Read-only attachment does not require any command;
periodic self-description makes a listener useful, while a solicited snapshot
provides an exact command precondition when needed.

Mutating requests bind instrument session, command identity and expected mode or
state generation, with code/transaction identity where relevant. Firmware either
rejects, accepts pending, or reports completed with the resulting state. Acceptance
is not DAC application. Duplicate requests must not repeat an actuator effect;
ambiguous results require discovery, not blind retransmission. Bound command
history and use session/sequence rules to reject old requests after history ages
out. Stale-session commands never affect a restarted instrument.

At a mode change, inhibit creation of conflicting work immediately. If an internal
application has not been released, cancel it exactly. If released, resolve the
bounded executor result before declaring the mode effective. Preserve an applied
correction even if its subsequent scientific response becomes incomplete. A new
mode cannot manufacture a successful response or overwrite unresolved actuator
state. Cancellation has a reserved bounded service path; it cannot retract a
physical write that already occurred. Loss of transport must be reported as an
unconfirmed command, never as successful stop delivery.

Replace the host-durability release with a firmware commit rule: a qualified
proposal binds source span, acceptance epoch, policy, applied code/DAC epoch and
request identity; internal bounded execution confirms or rejects it; the result
reaches all measurement/controller consumers before the first dependent decision.
USB transmission and host file retention are neither prerequisites nor internal
acknowledgements. Preserve enough bounded internal transaction state to complete
this rule even when every external telemetry frame is discarded.

Firmware still enforces absolute code, step, cadence, settling, response and
integrity limits. Remove campaign duration, application-count and cumulative-
movement budgets from ordinary indefinite operation only through an explicit
policy audit. Replace any actual anti-runaway purpose with finite-window or
state-based protection where required. Never turn a lifetime counter limit into
silent rollover or disable a protective predicate merely to run longer.

## Fault and recovery contract

Classify by the affected responsibility, with observable entry and exit rules.
Do not transplant host review holds into a permanent firmware dependency on a
reviewer. Ordinary acquisition and known recovery must work with no human or
model available; an unanswered alert never authorizes an unknown transition.

| Condition                                                | Instrument response                                                     | Recovery or evidence consequence                                   |
| -------------------------------------------------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------ |
| Initial GNSS/PPS acquisition                             | Hold startup code; continue capture, output and status.                 | Fresh reference and receiver qualification admit acquisition.      |
| Temporary GNSS metadata anomaly                          | Hold last confirmed code; preserve otherwise valid measurement history. | Fresh causal metadata qualification; no unnecessary epoch reset.   |
| D14 loss or acceptance discontinuity                     | Hold code; close affected qualified segment; preserve raw observations. | Fresh coherent epoch/support; establish new relative-phase origin. |
| Phase evidence unsuitable                                | Frequency-only operation when independently qualified by policy.        | Restore phase contribution only on its own qualification proof.    |
| Missing/invalid D8 capture                               | Inhibit correction; report unavailable count/output evidence.           | Defined capture requalification or integrity-fault recovery.       |
| USB absent, blocked or disconnected                      | Continue internal capture and control with bounded outbound discard.    | Explicit coverage gaps and current snapshot on later attachment.   |
| Host parser, disk or analysis fault                      | No autonomous control transition merely from host failure.              | Retain available host evidence; report recording/analysis failure. |
| Internal ordering/capture defect or ambiguous DAC result | Inhibit further writes; preserve confirmed facts and uncertainty.       | Latch integrity fault; explicit validated recovery or code repair. |
| Optional sensor, D6 or D10 anomaly                       | Degrade only that diagnostic or external-event evidence.                | Local recovery; never a D14/D8 steering veto.                      |

Reference loss after an established origin must recover, not merely the startup
case repaired previously. Cover each pending phase: before execution cancel an
invalidated proposal; after application retain the actual code and mark an
unmeasurable response incomplete; with an ambiguous application inhibit further
writes until identity is established. No automatic rollback and no repeated
application of the last request.

Separate instrument uptime, recorder duration, qualified segment durations and
unobserved intervals. Never join different acceptance epochs into uninterrupted
qualification. Preserve estimator history when still valid; invalidate only the
state whose supporting evidence was broken. Fixed-code holds are not predictive
holdover. A host verifier finding remains visible for engineering review, but
cannot automatically command hold, reset or abort; an operator may explicitly
request inhibition after reviewing it.

The operator accepts these categories as the starting point for the mapping,
not as blanket long-term approval of every per-fault classification. Prepare the
complete mapping for operator review before adopting it as settled long-term
policy. The review must show each reason, proposed response and recovery predicate.

Audit every existing fault and expiry against this table. The implementation
contract must enumerate reason codes, affected mode/state, pending-phase behavior,
exit predicate and retained evidence. Unknown internal integrity failures default
to inhibited actuation, not automatic resume. This audit is part of the finite
replacement, not a later fault-cleanup project.

## Evidence without a compulsory recorder

Preserve canonical raw records unchanged. Record policy/build/contract identity,
session, reset cause, mode transitions, qualification reasons, selected source
spans, decisions, command receipts, DAC applications/epochs and response outcomes.
Keep clock domains explicit and use exact-domain deltas for decision predicates.

Allocate a bounded internal transaction record independently of the outbound
serial queue. Its failure may be an instrument integrity fault. Outbound congestion
alone is an evidence-delivery problem and must not backpressure that record,
capture service, GNSS service or the DAC result handoff. Bound both serial output
and input parsing work so an attached hostile/noisy or stalled client cannot
starve timing service.

Generate session-scoped sequence identity before possible output loss. Preserve
bounded cumulative loss counters, missing sequence ranges where available, and
sticky fault/transition summaries that survive queue discard within the session.
On attachment and periodically, publish a coherent current snapshot including
applied-code provenance, active mode/state/reasons, pending action and evidence
coverage. Do not claim a bounded summary reconstructs discarded history.

Full replay is supported only for intervals whose required evidence was actually
retained. Hostless operation does not imply an onboard archive. A new session
cannot claim records survived reset without actual persistent storage. Persistent
logging and seamless cross-reset recovery are outside this first delivery.

## The simpler host and long observations

The basic runtime is one recorder process: attach without reset, frame and retain
raw output, expose current observation/freshness, rotate files and close its own
recording cleanly. Reuse the proven transport and raw writer. Parsing failure
preserves raw bytes; derived views report unavailable or contradictory evidence
rather than inventing clean status. Optional analysis runs outside the drainage
path. A small command interface shares the existing serial owner and cannot
become an automatic scientific supervisor.

Disk failure and process death can lose host evidence. Bounded buffering and
explicit recording-health diagnostics must expose that limit. Reattachment
starts a new recording segment, discovers state and never replays old mutations.
Closing the recorder leaves firmware in its current mode.

A 72-hour or seven-day observation is a recorder schedule, not a finite firmware
steering lease. At its endpoint, rotate/close/package the evidence without
changing the instrument. If an experiment requires steering inhibition at an
endpoint, explicitly preload a bounded firmware operation with that endpoint;
notification availability or a host timer must not be its sole enforcement.

Retain independent local monitoring of capture freshness, instrument state,
qualified segments, correction applications/responses, faults, record loss and
storage health. Process existence alone is insufficient. Reporting is optional
for instrument operation, but a promised observation service must be verified.
For the extended observation discussed previously, test material-event reporting
and hourly summaries, including delivery failure and an absent reviewer. Do not
create a chat automation in this proposal or depend on model usage budget. If no
independent authorized notification channel is available, state that limitation
before launch rather than promise immediate chat reports.

## What is retained and what is deleted

Retain hardware capture, accepted-reference selection, the selected hybrid
controller and plant model, bounded DAC guards, useful serializers/parsers, raw
recording, deterministic replay and evidence packaging. Adapt their interfaces
where the ownership change requires it. Keep engineering qualification tools
outside the normal runtime.

Delete from the replacement live path the supervisor inheritance chain
(`adaptive_hybrid_supervisor*`, `adaptive_hybrid_transactions`, and the control
lifecycle in `adaptive_hybrid_transport`), campaign lease/evidence-ACK command
flows, repeated host authority gates, nested scientific command waits, alternative
fallback loops, and mandatory runner/observer/decision-worker process topology.
Extract useful primitives before deletion; this is a responsibility inventory,
not permission to indiscriminately delete modules containing shared parsers.
`live_run`, `run_spec` and `unattended` must lose compulsory control ownership;
retain only demonstrated recording or removable qualification responsibilities.

No compatibility layer keeps the old supervised controller alive indefinitely.
Historical packages use their recorded revisions and remain unchanged. A new
wire-contract version must reject old mutating clients clearly. Old and new
protocol behavior may coexist offline during development, not as competing live
control owners at delivery.

## Finite implementation and acceptance

1. **Freeze the replacement contract.** Enumerate modes, effective states,
   transitions, every fault/expiry, startup code, bounds, internal commit rule,
   serial requests and coverage semantics. Inventory each current host gate:
   move a necessary instrument predicate into firmware, retain independent
   verification offline, or delete obsolete campaign bookkeeping. No safety or
   scientific predicate may disappear accidentally in the move.
2. **Complete firmware ownership end to end.** Reuse the hybrid engine; replace
   host releases with bounded internal application/response progression. Implement
   boot and restart, the four mode semantics, reference requalification and output
   isolation together. Bind one versioned policy/contract to firmware and readers.
3. **Deliver the recording host and delete the old runtime.** Prove basic attach,
   record, command, detach and reattach paths without supervisor imports or leases.
   Publish the before/after dependency and deletion inventory. Update architecture,
   terminology, wire/schema, methodology and known-limitations documentation with
   implemented behavior; prospective statements are not implementation evidence.
4. **Complete the offline release gate.** Build the exact current hardware profile,
   inspect field emission and resources, and exercise actual firmware state/driver
   boundaries with native integration where possible. Rehearse the actual recorder
   and command path over genuine PTY I/O. A host fixture cannot prove firmware
   cross-core behavior or electrical startup. Reuse historical failure evidence
   for relevant consumer checks without reinterpreting its original verdict.
5. **Authorize and run the shortest physical gate, then an extended observation.**
   Freeze the exact bundle; verify boot/restart DAC behavior, hostless repeated
   operation and observational attachment on the rig. Only after those pass,
   undertake the separately authorized finite 72-hour observation, optionally a
   separately specified week. Preserve immutable evidence and repair offline
   consumers by replay when acquisition remains sufficient.

Required acceptance scenarios span the actual complete path:

- Cold boot with no USB; late GNSS; warm firmware restart with retained DAC/GNSS;
  late recorder attachment and actual serial-open behavior.
- Repeated corrections, including the second response and first dependent decision
  after each application; no forced physical correction just to make logs busy.
- D14 and metadata loss before and after origin and in every pending phase; exact
  requalification; no stale request or invented completion across epochs.
- Every mode transition, hold persistence across disconnect, fixed-code bounds,
  characterization completion/cancel, duplicate and stale-session commands.
- USB stalls, absent reader, input flood, telemetry saturation, parser/analysis
  exceptions, disk exhaustion, recorder death and reattachment. The instrument
  must continue qualified control independently of those host failures.
- Capture integrity and DAC ambiguity injection; persistent inhibition with no
  reviewer; explicit recovery cannot clear unrelated faults.
- Counter rollover, sequence exhaustion policy, long cadence/deadline boundaries,
  bounded memory and queues, rotation, notification failure and scheduled recording
  closure. Supplement deterministic boundary tests with an elapsed operational soak.

Record which real components each check exercises. A complete host simulation is
not a physical qualification; a short physical gate is not a duration claim.
Completion requires verified autonomous repeated operation, usable serial-selected
modes, a passive basic recorder, bounded fault behavior, explicit evidence gaps
and removal of the superseded live control structure.

## Operator decisions and remaining design questions — 20 September

The operator resolved the numbered decision list as follows. Acceptance of design
intent does not claim implementation or authorize physical I/O.

1. **Startup code accepted:** explicitly write `0xA84D` on cold start and firmware
   restart. Preserve the stated new-session and discontinuity semantics.
2. **Mode persistence accepted:** boot selects AUTO_DISCIPLINE; runtime mode changes
   survive host disconnect but not firmware restart.
3. **Mode set accepted:** AUTO_DISCIPLINE, OBSERVE_HOLD, FIXED_CODE and CHARACTERIZE.
4. **Characterization proposal accepted:** use a finite bounded plan under the same
   firmware owner. Choose the smallest useful step/dwell plan during implementation;
   no scripting framework. Exact step counts and dwell values are not yet specified.
5. **Characterization exit accepted:** completion/cancellation enters OBSERVE_HOLD
   at the last confirmed code; returning to discipline is explicit.
6. **In-flight transitions accepted:** use immediate inhibition
   of new work, cancellation before executor release, and bounded resolution of
   an already-released write before the new mode becomes effective. Do not wait
   for the full scientific response window merely to stop steering. An incomplete
   response remains incomplete. Ambiguous application inhibits further writes.
7. **Indefinite limits accepted:** retain the existing scientific controller
   limits initially. The current policy has a 21-code maximum step, 1,800-second
   minimum applied cadence, 900-second settling exclusion, 600-second fresh support
   after settling, and `0xA800..0xAB00` absolute bounds. Its 144-application and
   3,024-code lifetime movement caps are finite campaign budgets. Campaign budgets,
   including finite duration, do not apply to ordinary autonomous operation.
   Remove those lifetime stop conditions, preserve cumulative counters as evidence,
   and retain bounded per-action behavior.
   Audit any additional anti-runaway predicate against demonstrated need; do not
   invent an arbitrary rolling quota as a substitute for the old campaign budget.
8. **Reuse existing hold/requalification behavior:** preserve the selected policy's
   known-code hold, capture continuity, frozen correction debt and causal metadata
   recovery. Its metadata rule requires fresh same-receiver evidence followed by
   two complete causally later maintenance windows. Phase loss/epoch change retains
   FLL debt and discards PLL debt. This is not a new predictive holdover model.
   Complete the previously identified post-origin D14/pending-transaction gaps
   using those existing semantics; do not claim the entire recovery path already
   exists just because its constituent rules do.
9. **Fault recovery categories accepted as the mapping starting point:** use
   automatic recovery for known
   qualification disturbances, local-only degradation for optional evidence, and
   latched actuation inhibition for ambiguous DAC results or internal integrity
   contradictions. A host parser/recorder problem cannot itself fault autonomous
   steering. Explicit recovery must prove the affected state coherent; it is not
   a blind clear-fault command. Prepare the complete per-reason mapping for operator
   review before committing to it as long-term policy. Agreement on the categories
   is not blanket approval of all individual fault classifications.
10. **Existing serial contract is the starting point:** reuse its framing, command
    parsing, status/query and acknowledgement conventions, canonical contract and
    generated bindings. Preserve existing commands where their meaning remains
    valid; add only the mode operations and identity fields actually required.
    Existing LEASE, ARM and EVIDENCE semantics must not silently become new mode
    semantics. Retiring their compulsory role requires an explicit versioned
    contract change, not a new parallel command framework or unchanged-wire claim.
11. **Buffer/loss defaults delegated to engineering:** retain current statically
    allocated outbound capacity initially, with nonblocking whole-record discard
    when full. Never truncate an emitted frame to splice in another. Maintain
    independent bounded internal transaction storage for the single outstanding
    actuator operation; reserve command/inhibit service independently of telemetry.
    Use session-scoped sequence identities, cumulative discarded-record counts,
    first/latest lost identity, and sticky fault/current-state summaries. If loss
    ranges cannot be represented exactly, mark coverage unknown rather than merge
    gaps into false completeness. Counters must not silently wrap; use checked
    arithmetic and explicit saturation/exhaustion reporting. Publish the coherent
    snapshot on attachment and through existing periodic status scheduling. No
    unbounded history, automatic persistent logging or queue growth. Final byte
    budgets and service bounds are set by the exact-profile memory/resource audit
    and saturation tests, not guessed capacities in this proposal.
12. **Recording endpoint accepted:** closing a recording leaves the instrument
    operating. A requested timed steering stop belongs to an explicitly bounded
    firmware operation; host or model availability is not its enforcement.
13. **Monitoring proposal accepted:** independent local observation, material-event
    reporting and hourly summaries for the extended observation, with delivery
    failure visible. The actual authorized notification destination remains to be
    selected when preparing that observation. This does not create an automation.
14. **Qualification sequence accepted:** use deterministic offline failure and
    boundary tests, then one short authorized physical integration gate, followed
    by a 72-hour observation. A week is optional rather than an automatic next
    hurdle. The short gate proves physical startup/restart, attachment isolation
    and transaction propagation; the longer observation measures sustained behavior
    and recorded evidence coverage. Neither requires a spontaneous rare fault or
    forced physical correction. Freeze scientific criteria before acquisition.

The operator has now resolved items 6, 7, 9 and 14 as recorded above; item 8's
existing hold/requalification direction is unchanged. The detailed fault mapping
still requires operator review before long-term policy commitment. Remaining
bounded implementation choices follow the accepted direction. Keep
current firmware and campaign obligations intact until the replacement is
implemented and verified; no historic evidence is reclassified by these decisions.
