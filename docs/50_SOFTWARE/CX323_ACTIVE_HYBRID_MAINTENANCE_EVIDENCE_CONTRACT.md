# CX323 Active-Hybrid Maintenance Evidence Contract

## Status and scope

This document freezes `active_hybrid_maintenance_v1`, wire tag `AHM`, for
`CX323_PHASE_PRIORITY_PERSISTENT_MAINTENANCE_V1`. It defines evidence only. An
`AHM` row is non-actionable controller-state evidence and neither grants
authority nor replaces D14 `REF`, D8 `CNT`, `AHY` controller content, `AH2`
exact decision timing, `ACT` transaction evidence, or `AT2` exact transaction
timing.

The exact ordered CSV field contract and row validator are
`ACTIVE_HYBRID_MAINTENANCE_V1_FIELDS` and
`_check_active_hybrid_maintenance_v1` in `host/otis_tools/contracts.py`.
Capture routes `AHM` to this contract through
`host/otis_tools/capture_serial.py`.

## Clock and sequence domain

- `event_timestamp_ticks` is the firmware timestamp at which the recorded
  maintenance transition became committed.
- `time_domain` is exactly `rp2040_timer0_extended`. It is a monotonic extended
  counter and is never reconstructed from whole seconds or host time.
- `maintenance_record_sequence` is non-zero and strictly increasing across one
  policy activation. It does not reset at a capture-session boundary.
- A capture-session transition is explicit in `capture_session`; validators
  restart timestamp progression for the new session but do not weaken record
  ordering.
- A missing, duplicate, backward, or contradictory AHM sequence is a
  maintenance-evidence fault. It is not interpreted as unchanged state.

## Exact ordered CSV schema

```text
record_type,schema_version,maintenance_record_sequence,event,event_timestamp_ticks,time_domain,run_identity,build_identity,profile_identity,policy_id,active_policy_sha256,capture_session,source_first_sequence,source_last_sequence,frequency_estimator_sha256,phase_epoch,phase_observation_sequence,phase_valid,current_applied_code,current_dac_epoch,hybrid_record_sequence,hybrid_timing_record_sequence,decision_sequence,transaction_record_sequence,transaction_timing_record_sequence,transaction_event,request_sequence,application_sequence,actual_applied_code,actual_dac_epoch,downstream_epoch_exact,maintenance_state_before,maintenance_state_after,frontier_relation,interval_sign,persistence_count_before,persistence_count_after,raw_fll_demand_picocodes,raw_pll_demand_picocodes,candidate_total_demand_picocodes,safe_cap_codes,requested_delta_codes,requested_code,committed_fll_debt_before_picocodes,committed_pll_debt_before_picocodes,committed_fll_debt_after_picocodes,committed_pll_debt_after_picocodes,request_pending_before,request_pending_after,response_pending_before,response_pending_after,metadata_hold_before,metadata_hold_after,requalification_window_count_before,requalification_window_count_after,evidence_burst_sequence,evidence_burst_record_ordinal,evidence_burst_record_count,reason,actionable
```

`record_type` is `AHM`, `schema_version` is `1`, `policy_id` is
`CX323_PHASE_PRIORITY_PERSISTENT_MAINTENANCE_V1`, and `actionable` is always
`false`. Boolean text is exactly `true` or `false`. Picocode fields are signed
base-10 integers in units of `1e-12` DAC code; no binary floating-point value
is authoritative controller debt.

## Identity and joins

The run/build/profile/policy identity tuple is repeated on every row. A
decision-bearing AHM join is exact only when all of these agree:

1. `capture_session`, `source_first_sequence`, `source_last_sequence`, and
   `decision_sequence` equal the joined `AHY` row;
2. `hybrid_record_sequence` names that exact `AHY` row;
3. `hybrid_timing_record_sequence` names the unique `AH2` row whose
   `hybrid_record_sequence`, decision, session, source frontier, run, build,
   and profile identity all equal the `AHY` row;
4. the AHM `event_timestamp_ticks` is in the declared extended timer domain
   and is not earlier than the causal event it records;
5. transaction lifecycle events additionally name the exact `ACT` and `AT2`
   rows through `transaction_record_sequence`,
   `transaction_timing_record_sequence`, `transaction_event`,
   `request_sequence`, and, where applicable, `application_sequence`, applied
   code, and DAC epoch.

For `decision`, the source frontier uses the selected 600-second estimator
support `(source_first_sequence, source_last_sequence]`. `frontier_relation`
is one of `first`, `contiguous`, `overlap`, or `gap`; `not_applicable` is used
only where no new estimator frontier is consumed. The selected estimator hash,
phase epoch/observation/validity, current applied code, and current DAC epoch
are part of the causal decision identity.

Transaction lifecycle rows retain the originating AHY/AH2 decision and source
frontier; they do not join a newer decision merely because it is the latest
record. An asynchronous metadata or fail-static transition carries the last
completed AHY/AH2 identity, or all-zero decision/source/join ordinals only when
no decision yet exists in that activation. A partial last-completed identity
is forbidden.

## Events and exact cardinality

| Event | Cardinality and required transition |
|---|---|
| `policy_activation` | Exactly one first AHM row per activation. `POLICY_INACTIVE -> READY`; both committed debt tags reset to zero; no AHY/AH2 or ACT/AT2 join. |
| `decision` | Exactly one for every CX323 active-hybrid decision, including legacy-path, hold, reset, persistence, zero-request, and request-producing decisions. It joins exactly one AHY and one AH2. A newly created request also joins exactly one `ACT/AT2 request_created`. |
| `request_rejected_or_expired` | Exactly one for each true-to-false unaccepted request transition. It joins the originating AHY/AH2 and `ACT/AT2 request_withdrawn`; response remains not pending and committed debt is unchanged. Rejection is not an application fault. |
| `application_first_consumer` | Exactly one only after accepted code, actual application code/sequence/DAC epoch, and the first dependent consumer are all exact. It joins the originating AHY/AH2 and `ACT/AT2 application`, clears request pending, sets response pending, resets persistence, and is the only event that may replace debt with bounded back-calculated FLL/PLL tags. |
| `response_complete` | Exactly one for each fresh exact response completion. It joins the originating AHY/AH2 and `ACT/AT2 response`, clears response pending, and preserves committed debt bit-for-bit. |
| `gnss_metadata_hold_enter` | Exactly one on each false-to-true recoverable metadata-hold transition. It preserves the last confirmed code and both debt tags, clears maintenance persistence, permits continuing D14/D8 capture, and issues no request. |
| `gnss_metadata_requalified` | Exactly one after fresh same-receiver metadata causally requalifies the receiver. Metadata hold remains asserted and the post-requalification maintenance-window count is zero. Subsequent `decision` rows prove window counts `0 -> 1` and `1 -> 2`; only the second complete causally later window may clear the hold and restore request eligibility. |
| `fail_static` | Exactly one on each transition into latched `FAIL_STATIC`. Unknown, partial, or contradictory application/code/epoch/first-consumer evidence freezes debt and last confirmed code. Repeated snapshots are not substitute events; a later policy activation is the only new activation boundary. |

Missing required events, multiple events for one causal transition, impossible
ordering, or inconsistent identities fail the maintenance-evidence gate. An
acknowledgement alone never satisfies `application_first_consumer`.

## State, persistence, demand, and debt

`maintenance_state_before` and `maintenance_state_after` are one of
`POLICY_INACTIVE`, `READY`, `PERSISTENCE_HOLD`, `REQUEST_PENDING`,
`RESPONSE_PENDING`, `METADATA_HOLD`, or `FAIL_STATIC`. The corresponding
pending/hold booleans are recorded before and after every event.

`interval_sign` is `-1`, `0`, or `1`. Persistence counts are in `0..2`. A
contiguous, same-identity, same-sign decision may advance the count; overlap
holds it unchanged; a gap restarts at one; zero-containing/opposite evidence,
legacy phase-material/outside-tight paths, and frozen identity reset boundaries
apply the selected policy's reset rules. Metadata requalification counts are
in `0..2` and are independent of ordinary maintenance persistence.

The raw FLL and PLL picocode demands, their candidate total after committed
tagged debt, no-zero-cross safe cap, integer request, and current/requested code
make the request reconstructable. `requested_code` equals
`current_applied_code + requested_delta_codes`; the delta and cap are bounded
to 21 codes and non-zero DAC codes remain within `0xA800..0xAB00`.

Before/after committed FLL and PLL debt fields are always integers. The
absolute value of each tag sum is at most `500000000000` picocodes. Holds,
request rejection/expiry, response completion, metadata transitions, and
fail-static preserve the committed sum. Phase invalidity or epoch change may
discard only PLL-origin debt. Policy activation resets both tags. Only an
`application_first_consumer` event may commit replacement back-calculated tags.

## Atomic evidence bursts

Every AHM row identifies one firmware evidence burst through
`evidence_burst_sequence`, `evidence_burst_record_ordinal`, and the exact
`evidence_burst_record_count`. All are non-zero and ordinal is at most count.

Before emitting the first record in a decision-bearing burst, the producer
must atomically admit capacity for the complete burst. It must not emit a
partial prefix:

- a non-request `decision` burst contains at least AHY, AH2, and AHM;
- a request-producing `decision` burst contains at least AHY, AH2, ACT, AT2,
  and AHM;
- rejection/expiry, application/first-consumer, and response bursts contain at
  least ACT, AT2, and AHM;
- any additional diagnostic or status record is included in the declared exact
  count before admission.

Capture and analyzers require every declared ordinal exactly once. Queue
pressure that cannot admit the complete burst must preserve controller state,
emit no partial decision transition, and surface the existing bounded evidence
fault path. The CSV row proves the declared burst identity; native queue tests
and operational-path rehearsal must separately prove producer admission and
cross-core delivery.

## GNSS and authority separation

GNSS serial metadata qualifies the receiver supplying D14 but is never timing
authority. A recoverable anomaly enters `METADATA_HOLD`, preserves the last
confirmed DAC code and committed debt, continues canonical D14/D8 capture, and
is not a run terminal. D9 and D6 remain zero-authority evidence and never enter
AHM eligibility or joins. D10 is outside this contract.

## Required verifier behavior

The CX323 analyzer must reject:

- missing, duplicate, reordered, or identity-inconsistent AHM rows;
- incomplete AHY/AH2 or ACT/AT2 joins;
- a request transition without its transaction join;
- debt change before exact application and first-consumer propagation;
- response completion, rejection/expiry, metadata hold/requalification, or
  fail-static transitions that violate the event table;
- an absent or partial declared evidence burst;
- whole-second or host-time substitution for the exact counter domain.

Such rejection is `cx323_d9_d6_72h_maintenance_evidence_fault` unless a more
specific existing authority, transaction, or identity terminal has already
been established. It does not retroactively alter canonical D14/D8 evidence.
