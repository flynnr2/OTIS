# Autonomous instrument fault mapping — operator review draft

23 September 2026. This is the explicit starting mapping used by the autonomous
implementation candidate. The operator accepted the category approach but
reserved review of the detailed mapping before long-term adoption. Passing
verification does not remove that review step. No physical qualification or
long-term fault-policy approval is claimed here.

## Responsibilities and responses

A hold inhibits new corrections; it does not invalidate canonical observations.
An applied DAC write remains a physical fact even when its response cannot be
measured. D14/D8 measurement continues whenever the actual capture system can
continue. D9 continues forwarding available D8; output presence is not a lock or
accuracy claim. No class grants a host parser, recorder or analyzer automatic
abort, mode-change or reset authority.

| Class | Meaning | Candidate behavior | Exit |
| ----- | ------- | ------------------ | ---- |
| Qualification hold | Required evidence temporarily unavailable | Preserve code and valid history; continue observation | Explicit fresh causal requalification |
| Operator mode | Hold, fixed code or finite characterization selected | One firmware owner executes accepted mode | Explicit mode request, finite completion or declared restart policy |
| Controller hold | Selected controller's own diagnostic rejects further corrections | Retain observations and last code; inhibit selected control | Review; no automatic clearing in this candidate |
| Instrument integrity fault | Capture, command/application identity, internal arithmetic or actuator state cannot be trusted | Inhibit new writes; retain exact pending action and first fault | Review/repair; restart is a new session, not proof of fault resolution |
| Evidence-delivery loss | Optional USB/host output cannot be retained | Continue qualified internal control; record bounded loss summaries | Reader/service recovery; missing historical evidence stays missing |
| Optional evidence fault | D6, D10 or other non-authoritative diagnostic | Degrade that evidence only | Local recovery |

## Qualification and command outcomes

- `reference_hold`: D14 acceptance is unavailable or its epoch changed. Cancel a
  private unexecuted correction. Resolve an already released operation, preserve
  its actual application, and label an unmeasurable response incomplete. Resume
  only from a fresh complete selected span in the current epoch; never join
  qualified durations or relative-phase history across the gap.
- `metadata_hold`: current same-receiver qualification is absent. Preserve D14/D8
  measurement histories and freeze correction debt. Fresh receiver metadata plus
  two causally later contiguous maintenance windows requalifies control, following
  the existing selected engine. An epoch change restarts that recovery support.
- Invalid phase evidence selects the existing frequency-only path when the
  independent frequency evidence qualifies. Phase debt is discarded on a phase
  validity/epoch change; otherwise valid frequency debt is preserved.
- `correction_rejected_before_write`: only an exact no-write acknowledgement with
  `QualificationLost` and unchanged known prior code is recoverable. It discards
  the proposal; subsequent evidence must qualify a new decision. It is not an
  automatic retry of the rejected request.
- Malformed/out-of-range, stale-session, conflicting duplicate or stale-sequence
  commands are rejected without changing mode or code. Exact duplicates return
  a duplicate receipt without repeating the physical effect.
- An operator HOLD clears neither a firmware fault nor a different inhibition.
  A firmware restart writes `0xA84D`, begins a new session and selects AUTO. A host
  disconnect leaves the selected mode in place. These are different operations.

## First-fault reasons in the owner

The following reasons inhibit new writes and remain latched in the candidate.
They are instrument-local findings, not declarations that physical reality or
all retained measurement failed.

| Reason | Evidence or invariant | Review focus |
| ------ | --------------------- | ------------ |
| `startup_identity_invalid` | Missing boot session or timer identity | Initialization order and session generation |
| `instrument_clock_backward` | Service clock regressed in declared extended timer domain | Timer/domain or caller defect |
| `capture_identity_or_integrity` | Capture session changed or hardware capture integrity failed | Capture evidence; repair vs explicit restart |
| `instrument_identity_exhausted` | Request or DAC epoch cannot increment without reuse | New explicit session, never silent rollover |
| `actuator_or_consumer_deadline` | Released operation/consumer confirmation missed its fixed deadline | Exact pending identity and actual application evidence |
| `application_identity_or_deadline` | Application does not match released request or legal event interval | Cross-core ordering and actual DAC state |
| `dac_application_unknown` | Write attempt failed, result contradicts request, or execution was rejected outside the recoverable qualification case | Distinguish last confirmed code from currently established state |
| `application_consumer_identity` | Frequency/phase consumer confirmation mismatches application | Both sides of handoff and first dependent decision |
| `controller_application_commit` | Engine rejected exact application/consumer commit | Pending decision and debt identity |
| `controller_initialization` | Selected policy or initial application could not bind | Boot policy and applied-state provenance |
| `characterization_deadline_overflow` | Finite plan deadline is not representable | Reject rather than wrap or run indefinitely |
| `operating_deadline_overflow` | A timed AUTO request was accepted before a pending write completed, but its effective transition time cannot represent the full requested duration | Retain the exact application and inhibit new writes rather than wrap the stop deadline |
| `decision_clock_or_freshness` | Decision reorders, has invalid time, or exceeds the 60-second source-to-service bound | Capture and operational coordinates separately |
| `controller_decision_invalid` | Selected engine rejected its input/transition | Estimator and engine state, not raw-observation validity |
| `nonfinite_source_error` | A proposed correction lacks finite error evidence | Estimator input/serialization defect |
| `response_accumulator_exhausted` | Existing diagnostic response accumulator would overflow | Explicit classifier/session reset policy after review |
| `internal_write_mailbox` | Sole actuator dispatch mailbox could not accept a released request | Internal ownership or service starvation |

The adapter also latches `fresh_dac_snapshot_contradiction` only when a DAC
snapshot was published at or after the last physical application and contradicts
its known code/driver health. An older queued snapshot cannot overturn a newer
application.

Partition reasons are `boot_handshake_timeout`,
`service_to_timing_queue_exhausted`, `instrument_write_queue_exhausted`,
`evidence_integrity_fault`, `phase_frequency_estimate_processing_fault` and
`instrument_application_mismatch`. These are internal platform/capture/consumer
findings, distinct from optional outbound queue drops. They inhibit writes through
the owner health boundary. An unknown partition enum is reported explicitly.

Executor no-write outcomes are `IdentityInvalid`, `DeadlineExpired`,
`PlatformFault`, `DeviceUnavailable` and `QualificationLost`. Only the last has
the exact recoverable correction path described above. Others inhibit control;
no-write provenance alone is not evidence of physical danger.

## Selected engine diagnostics

Retain existing numerical calculations and their checks. The first implementation
continues to inhibit selected control on `prospective_repeated_alternation` (three
reversals over the latest four proposed/applied directions). This is a controller
review hold, not a capture failure. The operator should specifically review
whether its long-term recovery should be manual, timed, or evidence-driven.

Remove the lifetime `prospective_low_efficiency_path` stop in ordinary operation:
long-term movement away from and back toward the boot code is not, by itself,
a failure. Remove lifetime application-count and cumulative-movement budgets;
retain their counters as evidence. The absolute range, 21-code maximum correction,
1,800-second cadence and settling/fresh-support requirements remain.

Engine reasons `observation_timestamp_domain_mismatch`,
`observation_timestamp_backward`, `invalid_selected_window_frontier`,
`unknown_or_contradictory_application_or_DAC_epoch`,
`metadata_requalification_accepted_boundary_ordinal_missing`,
`maintenance_arithmetic_overflow`, `invalid_request_rejection_transition`,
`invalid_or_unexpected_application`, `application_without_exact_first_consumer`,
`debt_tag_sum_invariant_failure`, `new_policy_activation_with_outstanding_transaction`
and `decision_identity_exhausted` retain inhibition as internal consistency
findings. Ordinary persistence, overlap/gap, cadence, settling, zero/range and
phase-direction-coherence holds remain ordinary controller decisions and clear
only under the engine's existing predicates.

Response classifications such as wrong sign, growing error, excess response or
indeterminate near resolution remain recorded scientific diagnostics under the
selected observational response policy. They do not retroactively invalidate
raw capture or automatically become a host abort.

## Transport and host isolation

Outbound observation, phase, frequency, evidence and status loss is reported
with separate bounded counters; full replay is unavailable over a gap. A receiver
or actuator service-message loss, actuator mailbox violation, or boot handshake
failure is an internal platform defect and retains fail-static behavior. A serial
reader's absence, stall or disconnection is not such a defect.

A host disk failure terminates or degrades recording truthfully. It cannot send
an implicit instrument stop. Reattachment begins a new recording segment and
must discover current firmware state; it does not reconstruct the missing gap.

## Review deliverable

Review this mapping together with the exact candidate source and test results.
Confirm especially repeated-alternation handling, no-write executor rejection
categories, internal service starvation, fresh DAC contradictions, and the
absence of a generic clear-fault command. Changes following review need the
shortest affected deterministic/integration gate; they do not authorize
reinterpretation of previously retained evidence or arbitrary physical retries.
