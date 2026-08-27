# Operational semantics and implementation map

## Status and scope

These are frozen architecture requirements and an implementation map derived
from the retained interfaces, exact transaction paths and architecture review.
They are independent of the provisional decision to retain the unchanged CX322
request calculation. The historical packages do not reconstruct metadata-hold
duration or lost opportunities; those values remain unavailable. This
programme does not implement these semantics in firmware or the live supervisor
while the GNSS baud soak is active. Pure offline reference transitions and
deterministic host tests exercise the request-ownership, low-efficiency,
shadow-containment and D10-isolation rules without claiming a cross-core or
physical integration boundary.

D14 remains the sole authoritative PPS/reference input, D8 remains the sole
authoritative oscillator/count input, and D10 remains an optional external
event input with zero steering authority. GNSS serial metadata qualifies the
receiver that supplies D14; it does not replace D14 timing evidence.

## Required state model

| State | Measurement behavior | New actuation | Exit rule |
|---|---|---|---|
| `ACTIVE` | Preserve normal D14/D8 capture, estimation and response evidence. | Permitted only through existing authority, cadence and transaction gates. | A declared degradation enters its specific bounded state. |
| `GNSS_METADATA_HOLD` | Continue canonical D14/D8 capture and estimator/phase history. Record metadata as stale, missing, malformed or unqualified; do not recast measurement as failed. | Inhibited at the last confirmed applied code. Committed candidate debt and persistence are frozen, not advanced. | Fresh qualified metadata from the same receiver, followed by one complete causally later D14/D8 observation with exact session/code/DAC identity. |
| `PHASE_DEGRADED_FLL` | Continue valid D14/D8 frequency measurement. Phase-local evidence is unavailable or starts a new explicit epoch. | Existing FLL only. PLL-origin debt is discarded and cannot reactivate. | Fresh phase qualification creates a new phase epoch and follows the normal first-phase transaction rules. |
| `LOW_EFFICIENCY_INHIBIT` | Continue measurement and evidence. Preserve the component-attribution ledger. | Automatic actuation inhibited; last confirmed code retained. | Explicit operator reauthorization under a future frozen programme. It is not an automatic terminal or silent reset. |
| `ACTUATOR_PROVENANCE_FAIL_STATIC` | Continue evidence where safe, but mark application identity unknown or contradictory. | None. Debt is non-actionable. | Only an explicit recovery that re-establishes the applied code, DAC epoch, session and transaction outcome. |
| `ABORTED` / terminal fault | Preserve the terminal evidence and bounded abort-delivery record. | None. | New run authority is required. |

`GNSS_METADATA_HOLD` must not erase otherwise valid estimator history, phase
history, applied-code identity, or canonical D14/D8 observations. A metadata
hold is not a clean, zero, unchanged, or failed measurement.

## Transaction-aware metadata-loss ordering

1. **No request created.** Consume or withdraw any unused live arm, record the
   exact arm identity, inhibit new requests, and enter `GNSS_METADATA_HOLD`.
2. **Private request created on Core 1 but not durably released.** Core 1 is the
   only owner and withdraws it locally. Record the request/nonce/decision and a
   `private_unreleased_withdrawn` outcome before entering the hold.
3. **Request durably released to Core 0 but not accepted.** Core 0 is the sole
   outcome owner. It must emit one exact accepted, rejected, or bounded-expiry
   outcome. Core 1 must neither withdraw nor replace it. Rejection/expiry leaves
   committed debt unchanged and then enters the hold.
4. **Acceptance wins.** Complete the exact accepted transaction, observe the
   confirmed applied code and DAC epoch through the first dependent consumer,
   commit the application residual once, retain the required response, and then
   remain held. Metadata loss must not race an accepted application.
5. **Application complete and response pending.** Continue the D14/D8 response
   observation if its measurement inputs remain valid. Record its class and
   identity, but do not rearm control. Requalification requires fresh metadata
   and a later complete D14/D8 observation.
6. **No authoritative outcome before the bounded deadline.** Enter
   `ACTUATOR_PROVENANCE_FAIL_STATIC`; never infer rejection, application, or an
   unchanged DAC code from silence.

Acceptance, application, first-consumer propagation, and response completion
are separate evidence transitions. An acknowledgement at one boundary cannot
stand in for downstream propagation.

## Phase loss and low-efficiency attribution

Phase loss uses the same outstanding-transaction ordering. Once that
transaction has resolved, discard PLL-origin debt, preserve valid FLL-origin
debt, enter `PHASE_DEGRADED_FLL`, and start a new phase epoch on later
requalification. A matching numeric phase value must not rejoin the old epoch.

Low efficiency is attributed from the request that was actually applied:

- if the combined integer request differs from the exact frequency-only request,
  the application is phase-material;
- a phase-material low-efficiency episode disables the PLL contribution and
  falls back to existing FLL behavior after the outstanding transaction and
  response rules complete;
- a repeated low-efficiency episode on the FLL-only path enters
  `LOW_EFFICIENCY_INHIBIT` without declaring D14/D8 measurement failed;
- direction reversal, path, net movement, response class and recovery remain
  recorded under the named exposure denominators.

Optional shadow estimators and D10 evidence fail locally. Their absence,
invalidity, overflow, stall or rejection cannot veto D14/D8 measurement or
control unless shared capture is demonstrably compromised; that case is a
platform-isolation defect.

## Required telemetry

Every record that can influence authority or replay must bind the run/build/
profile/policy identities, capture session, source frontier, applied code and
DAC epoch. Add or separate these fields rather than overloading a generic
health flag:

| Area | Required fields |
|---|---|
| Measurement and metadata | `d14_d8_measurement_healthy`, `gnss_metadata_qualified`, `gnss_metadata_reason`, `gnss_metadata_sequence`, `gnss_metadata_age_s` |
| Hold and recovery | `control_degraded_state`, `hold_enter_source_sequence`, `hold_last_confirmed_code`, `hold_last_confirmed_dac_epoch`, `metadata_requalification_sequence`, `post_requalification_observation_sequence` |
| Request ownership | `request_release_state`, `request_owner`, `request_sequence`, `decision_sequence`, `authorization_sequence`, `nonce`, `request_outcome`, `request_outcome_sequence`, `request_outcome_deadline_domain` |
| Application propagation | `accepted_code`, `applied_code`, `dac_epoch`, `application_sequence`, `first_dependent_consumer_sequence`, `downstream_epoch_exact` |
| Response and rearm | `response_measurement_healthy`, `response_source_first_sequence`, `response_source_last_sequence`, `response_class`, `control_rearm_eligible`, `rearm_inhibit_reason` |
| Tagged debt | exact total/FLL/PLL numerators and denominators, evidence and phase frontiers, plant-gain/policy/estimator identities, committed/pending status, freeze/discard/back-calculation reason |
| Efficiency attribution | `frequency_only_delta_codes`, `combined_delta_codes`, `phase_materially_influenced`, named exposure duration, path, net movement, reversal count, component-local outcome |

Clock and deadline fields must declare their counter domain and legal rollover.
Missing or late values remain unknown; they are never serialized as a clean
zero.

## Concrete implementation map

| Current site | Current coupling or gap | Required bounded change after the soak |
|---|---|---|
| `host/otis_tools/active_hybrid_live_supervisor.py:934` | Loss of `setup_gnss_eligible` is grouped with D14/D8/capture loss and raises a run-ending error. | Route metadata-only loss to the transaction-aware hold. Retain terminal behavior for authoritative reference, partition, lease, identity, abort-path or source-session faults. Supervise freshness and the exact post-requalification observation. |
| `firmware/arduino/otis_nano_rp2040_connect/otis_cx317_active_live.cpp:379` | `reference_path_healthy()` combines GNSS metadata/3D evidence with D14/D8 validity. | Split measurement health, receiver-metadata qualification and rearm eligibility. Keep canonical D14/D8 service alive in metadata hold. |
| `firmware/arduino/otis_nano_rp2040_connect/otis_cx317_active_live.cpp:1395` | `common_health_clean` combines metadata and measurement before the hybrid decision. | Emit a hold/degraded decision without feeding stale metadata into new authority; preserve the measurement observation separately. |
| `firmware/arduino/otis_nano_rp2040_connect/otis_cx317_active_transaction.cpp:185` | General eligibility includes metadata and measurement in one predicate. | Keep this strict for new actuation, but expose the exact failed dimension and transition to the correct hold rather than treating every loss as a terminal. |
| `firmware/arduino/otis_nano_rp2040_connect/otis_cx317_active_transaction.cpp:211` | Response measurement validity requires GNSS metadata. | Define D14/D8 response-measurement validity separately from control rearm. Permit retained response evidence during metadata hold; keep rearm inhibited. |
| `firmware/arduino/otis_nano_rp2040_connect/otis_cx317_active_transaction.cpp:233` | Existing `ReferenceHold` preserves an applied transaction but represents combined reference loss and rejects request/acceptance transitional states. | Refine it into the declared metadata/measurement dimensions and implement the private-versus-released ownership rules without an ownerless interval. |
| `firmware/arduino/otis_nano_rp2040_connect/otis_cx317_active_live.cpp:1127` | A non-accepted/non-applied Core 0 acknowledgement falls into a combined fault. | Add exact rejected/expired outcomes for released but unaccepted requests; keep accepted requests on the sole completion path and fail static on ambiguous identity. |
| `firmware/arduino/otis_nano_rp2040_connect/otis_active_hybrid_policy_engine.cpp:105` and `host/otis_tools/active_hybrid_policy.py:565` | Low efficiency maps to a prospective terminal reason. | Attribute it to phase-material versus FLL-only applications; use PLL-to-FLL fallback first, then a nonterminal automatic-actuation inhibit for repeated FLL-local inefficiency. Preserve exact host/firmware replay parity. |
| AHY/ACT/health schemas and replay/analyzer readers | No dedicated metadata-hold transaction chronology or tagged-debt fields. | Version schemas; update serializer, parser, replay, supervisor, analyzer, sealing and source guards together. Keep historical readers bound to historical revisions. |

No implementation site above is authorized for modification by this offline
programme.

## Fault-injection and handoff matrix

| Injection or boundary | Required observation | Forbidden result |
|---|---|---|
| Metadata loss before a request | Arm withdrawal, hold entry, unchanged confirmed code, continued D14/D8 records | New request, estimator reset, run terminal solely from metadata loss |
| Loss after private creation but before release | Exact local withdrawal and no Core 0 receipt | Duplicate withdrawal/expiry owners or a ghost application |
| Loss after durable release before acceptance | One Core 0 accepted/rejected/expired outcome with exact identity | Core 1 reuse or cancellation of the released identity |
| Acceptance concurrent with hold entry | Application and first-consumer propagation complete once, then hold | Hold erases accepted request, duplicate apply, or inferred unchanged code |
| Metadata loss while response pending | D14/D8 response retained and rearm inhibited | Response discarded solely for missing metadata or new request armed |
| Metadata recovery with stale snapshot | Remain held until a complete causally later D14/D8 observation | Requalification from age alone or a pre-loss frontier |
| Phase discontinuity with no transaction | PLL debt discarded, new phase epoch, FLL fallback | Old PLL debt reactivated after numeric reconvergence |
| Phase loss with transaction outstanding | Resolve transaction first, then component discard/fallback | Application ownership transfer or silent request loss |
| Phase-material low efficiency | Exact component attribution and PLL-to-FLL fallback | Whole-run failure or unbounded compensating debt |
| Repeated FLL-local low efficiency | `LOW_EFFICIENCY_INHIBIT`, last confirmed code, continued measurement | Automatic retry loop or measurement terminal |
| Rejected or expired request | Pending proposal discarded; committed debt unchanged | Debt commit from an unapplied proposal |
| Unknown/contradictory application identity | Actuator-provenance fail-static and non-actionable debt | Assumed application or continued automatic actuation |
| Step/range endpoint | Outward component back-calculated before residual commit | Hidden unbounded integrator |
| D10 overflow/noise/absence | D10-local degradation only | D14/D8 validity or steering veto |
| Shadow stall/corruption/rejection | Shadow-local failure and zero authority | Backpressure, abort, or canonical-state mutation |
| Serial obstruction during abort | Independent abort submission and bounded delivery record while sole owner drains | Capture owner exits before abort sent/failure evidence |

The eventual implementation must exercise both sides of every handoff and the
first dependent consumer. Unit-only coherence is insufficient for cross-core
or physical propagation; retain the live pre-actuation identity gate for that
remaining boundary.
