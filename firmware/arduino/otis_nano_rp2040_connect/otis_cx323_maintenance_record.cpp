#include "otis_cx323_maintenance_record.h"

#include <limits.h>
#include <stddef.h>
#include <string.h>

namespace {

constexpr int64_t kMaximumDebtPicocodes = 500000000000LL;
constexpr int32_t kMinimumWireCode = 0xA800;
constexpr int32_t kMaximumWireCode = 0xAB00;

bool valid_csv_atom(const char *text) {
  if (text == nullptr || *text == '\0') return false;
  for (const char *cursor = text; *cursor != '\0'; ++cursor) {
    if (*cursor == ',' || *cursor == '\r' || *cursor == '\n') return false;
  }
  return true;
}

bool valid_sha256(const char *text) {
  if (text == nullptr) return false;
  for (size_t index = 0u; index < 64u; ++index) {
    const char value = text[index];
    if (!((value >= '0' && value <= '9') ||
          (value >= 'a' && value <= 'f')))
      return false;
  }
  return text[64] == '\0';
}

bool same_text(const char *left, const char *right) {
  return left != nullptr && right != nullptr && strcmp(left, right) == 0;
}

bool policy_equal(const OtisCx323Policy &left,
                  const OtisCx323Policy &right) {
  return left.maximum_step_codes == right.maximum_step_codes &&
         left.minimum_code == right.minimum_code &&
         left.maximum_code == right.maximum_code &&
         left.minimum_cadence_s == right.minimum_cadence_s &&
         left.maximum_applications == right.maximum_applications &&
         left.maximum_cumulative_movement_codes ==
             right.maximum_cumulative_movement_codes &&
         left.setup_code == right.setup_code;
}

bool debt_bounded(const OtisCx323Debt &debt) {
  if (debt.fll_picocodes < -kMaximumDebtPicocodes ||
      debt.fll_picocodes > kMaximumDebtPicocodes ||
      debt.pll_picocodes < -kMaximumDebtPicocodes ||
      debt.pll_picocodes > kMaximumDebtPicocodes)
    return false;
  const int64_t total = debt.fll_picocodes + debt.pll_picocodes;
  return total >= -kMaximumDebtPicocodes &&
         total <= kMaximumDebtPicocodes;
}

bool valid_engine(const OtisCx323Engine &engine) {
  if (engine.policy.maximum_step_codes <= 0 ||
      engine.policy.maximum_step_codes > 21 ||
      engine.policy.minimum_code < kMinimumWireCode ||
      engine.policy.maximum_code > kMaximumWireCode ||
      engine.policy.minimum_code >= engine.policy.maximum_code ||
      engine.policy.minimum_cadence_s == 0u ||
      engine.policy.maximum_applications == 0u ||
      engine.policy.maximum_cumulative_movement_codes == 0u ||
      engine.applied_code < engine.policy.minimum_code ||
      engine.applied_code > engine.policy.maximum_code ||
      engine.dac_epoch == 0u || engine.persistence_sign < -1 ||
      engine.persistence_sign > 1 || engine.persistence_count > 2u ||
      engine.requalification_window_count > 2u ||
      !debt_bounded(engine.debt) ||
      engine.application_count > engine.policy.maximum_applications ||
      engine.cumulative_movement_codes >
          engine.policy.maximum_cumulative_movement_codes ||
      (engine.request_pending && engine.response_pending) ||
      (engine.metadata_requalified && !engine.metadata_hold) ||
      (engine.metadata_requalified &&
       !engine.requalification_frontier_available))
    return false;
  if (engine.request_pending) {
    if (engine.pending_decision_sequence == 0u ||
        engine.pending_requested_delta_codes == 0 ||
        engine.pending_requested_code !=
            engine.applied_code + engine.pending_requested_delta_codes)
      return false;
  } else if (engine.pending_decision_sequence != 0u ||
             engine.pending_requested_delta_codes != 0 ||
             engine.pending_maintenance_request ||
             engine.pending_observation_timestamp_s != 0u) {
    return false;
  }
  return true;
}

OtisCx323MaintenanceState state_of(const OtisCx323Engine &engine) {
  if (engine.fail_static_reason != nullptr)
    return OtisCx323MaintenanceState::FailStatic;
  if (engine.metadata_hold)
    return OtisCx323MaintenanceState::MetadataHold;
  if (engine.response_pending)
    return OtisCx323MaintenanceState::ResponsePending;
  if (engine.request_pending)
    return OtisCx323MaintenanceState::RequestPending;
  if (engine.persistence_count != 0u)
    return OtisCx323MaintenanceState::PersistenceHold;
  return OtisCx323MaintenanceState::Ready;
}

bool same_code_debt_and_budgets(const OtisCx323Engine &before,
                                const OtisCx323Engine &after) {
  return before.applied_code == after.applied_code &&
         before.dac_epoch == after.dac_epoch &&
         before.application_count == after.application_count &&
         before.cumulative_movement_codes ==
             after.cumulative_movement_codes &&
         before.debt.fll_picocodes == after.debt.fll_picocodes &&
         before.debt.pll_picocodes == after.debt.pll_picocodes;
}

bool complete_origin(const OtisCx323MaintenanceBuildInput &input) {
  const bool observation = input.originating_observation != nullptr;
  const bool decision = input.originating_decision != nullptr;
  const bool hybrid = input.hybrid_join != nullptr;
  return observation && decision && hybrid;
}

bool empty_origin(const OtisCx323MaintenanceBuildInput &input) {
  return input.originating_observation == nullptr &&
         input.originating_decision == nullptr && input.hybrid_join == nullptr;
}

bool exact_hybrid_join(const OtisCx323MaintenanceBuildInput &input) {
  if (!complete_origin(input)) return false;
  const OtisCx323Observation &observation = *input.originating_observation;
  const OtisCx323Decision &decision = *input.originating_decision;
  const OtisCx323MaintenanceHybridJoin &join = *input.hybrid_join;
  if (join.hybrid_record_sequence == 0u ||
      join.hybrid_timing_record_sequence == 0u ||
      join.decision_sequence == 0u || join.capture_session == 0u ||
      join.source_first_sequence == 0u ||
      join.source_last_sequence <= join.source_first_sequence ||
      join.phase_observation_sequence == 0u)
    return false;
  return join.decision_sequence == decision.decision_sequence &&
         join.capture_session == observation.capture_session &&
         join.source_first_sequence == observation.source_first_sequence &&
         join.source_last_sequence == observation.source_last_sequence &&
         join.phase_epoch == observation.phase_epoch &&
         join.phase_valid == observation.phase_valid;
}

bool exact_transaction_join(const OtisCx323MaintenanceBuildInput &input,
                            OtisCx323MaintenanceTransactionEvent event) {
  if (!exact_hybrid_join(input) || input.transaction_join == nullptr)
    return false;
  const OtisCx323MaintenanceTransactionJoin &join =
      *input.transaction_join;
  const OtisCx323Observation &observation = *input.originating_observation;
  const OtisCx323Decision &decision = *input.originating_decision;
  if (join.transaction_record_sequence == 0u ||
      join.transaction_timing_record_sequence == 0u ||
      join.request_sequence == 0u || join.transaction_event != event ||
      join.decision_sequence != decision.decision_sequence ||
      join.capture_session != observation.capture_session ||
      join.source_first_sequence != observation.source_first_sequence ||
      join.source_last_sequence != observation.source_last_sequence)
    return false;

  const bool any_application = join.application_sequence != 0u ||
                               join.actual_applied_code != 0u ||
                               join.actual_dac_epoch != 0u;
  const bool complete_application = join.application_sequence != 0u &&
                                    join.actual_applied_code != 0u &&
                                    join.actual_dac_epoch != 0u;
  if (any_application != complete_application) return false;
  if ((event == OtisCx323MaintenanceTransactionEvent::RequestCreated ||
       event == OtisCx323MaintenanceTransactionEvent::RequestWithdrawn) &&
      (any_application || join.downstream_epoch_exact))
    return false;
  if (event == OtisCx323MaintenanceTransactionEvent::Application &&
      (!complete_application || !join.downstream_epoch_exact))
    return false;
  if (event == OtisCx323MaintenanceTransactionEvent::ApplicationFault &&
      join.downstream_epoch_exact)
    return false;
  return true;
}

bool decision_matches_pending(const OtisCx323Engine &engine,
                              const OtisCx323Observation &observation,
                              const OtisCx323Decision &decision) {
  return engine.request_pending && !engine.response_pending &&
         engine.pending_decision_sequence == decision.decision_sequence &&
         engine.pending_requested_delta_codes ==
             decision.requested_delta_codes &&
         engine.pending_requested_code == decision.requested_code &&
         engine.pending_raw_combined_picocodes ==
             decision.raw_combined_picocodes &&
         engine.pending_raw_fll_picocodes == decision.raw_fll_picocodes &&
         engine.pending_raw_pll_picocodes == decision.raw_pll_picocodes &&
         engine.pending_maintenance_request == decision.maintenance_request &&
         engine.pending_observation_timestamp_s == observation.timestamp_s &&
         engine.pending_observation_timestamp_ticks ==
             observation.timestamp_ticks &&
         decision.decision_timestamp_ticks == observation.timestamp_ticks &&
         engine.pending_counterfactual_frequency_only_delta_codes ==
             decision.counterfactual_frequency_only_delta_codes &&
         engine.pending_phase_materially_influenced ==
             decision.phase_materially_influenced &&
         engine.pending_step_limited == decision.step_limited &&
         engine.pending_range_clamped == decision.range_clamped &&
         engine.pending_cadence_limited == decision.cadence_limited &&
         engine.pending_count_limited == decision.count_limited &&
         engine.pending_cumulative_budget_limited ==
             decision.cumulative_budget_limited;
}

bool decision_reconstructable(const OtisCx323MaintenanceBuildInput &input,
                              OtisCx323Wide *candidate_total) {
  if (candidate_total == nullptr || !exact_hybrid_join(input)) return false;
  const OtisCx323Observation &observation = *input.originating_observation;
  const OtisCx323Decision &decision = *input.originating_decision;
  const int64_t requested = static_cast<int64_t>(observation.applied_code) +
                            decision.requested_delta_codes;
  if (observation.source_first_sequence == 0u ||
      observation.source_last_sequence <= observation.source_first_sequence ||
      observation.capture_session == 0u || observation.dac_epoch == 0u ||
      observation.timestamp_s != observation.timestamp_ticks / 16000000ull ||
      observation.applied_code < kMinimumWireCode ||
      observation.applied_code > kMaximumWireCode ||
      decision.decision_sequence == 0u ||
      decision.decision_timestamp_ticks != observation.timestamp_ticks ||
      decision.requested_delta_codes < -21 ||
      decision.requested_delta_codes > 21 || decision.safe_cap_codes < 0 ||
      decision.safe_cap_codes > 21 || requested < kMinimumWireCode ||
      requested > kMaximumWireCode ||
      decision.requested_code != static_cast<int32_t>(requested) ||
      (decision.requested_delta_codes != 0 &&
       (decision.safe_cap_codes == 0 ||
        (decision.requested_delta_codes > decision.safe_cap_codes) ||
        (decision.requested_delta_codes < -decision.safe_cap_codes))) ||
      !valid_csv_atom(decision.reason) ||
      !otis_cx323_wide_valid(decision.raw_combined_picocodes) ||
      !otis_cx323_wide_valid(decision.raw_fll_picocodes) ||
      !otis_cx323_wide_valid(decision.raw_pll_picocodes))
    return false;
  OtisCx323Wide candidate;
  if (!otis_cx323_wide_checked_add(
          decision.raw_combined_picocodes,
          OtisCx323Wide(decision.committed_debt_picocodes), &candidate))
    return false;
  *candidate_total = candidate;
  return true;
}

OtisCx323FrontierRelation frontier_relation(
    const OtisCx323Engine &before,
    const OtisCx323Observation &observation) {
  bool available = before.last_closing_frontier_available;
  uint64_t closing = before.last_closing_frontier;
  if (before.metadata_requalified) {
    available = before.requalification_last_closing_frontier_available;
    closing = before.requalification_last_closing_frontier;
  }
  if (!available) return OtisCx323FrontierRelation::First;
  if (observation.source_first_sequence < closing)
    return OtisCx323FrontierRelation::Overlap;
  if (observation.source_first_sequence == closing)
    return OtisCx323FrontierRelation::Contiguous;
  return OtisCx323FrontierRelation::Gap;
}

bool interval_sign(const OtisCx323Observation &observation, int8_t *sign) {
  if (sign == nullptr) return false;
  if (!observation.phase_valid) {
    *sign = 0;
    return true;
  }
  OtisCx323Wide frequency;
  OtisCx323Wide phase;
  OtisCx323Wide combined;
  OtisCx323Wide negated_phase;
  OtisCx323Wide lower;
  OtisCx323Wide upper;
  if (!otis_cx323_wide_checked_multiply(
          OtisCx323Wide(-36),
          OtisCx323Wide(observation.accumulated_edge_error_counts),
          &frequency) ||
      !otis_cx323_wide_negate(
          OtisCx323Wide(observation.relative_phase_cycles), &negated_phase))
    return false;
  if (negated_phase < OtisCx323Wide(-36))
    phase = OtisCx323Wide(-36);
  else if (negated_phase > OtisCx323Wide(36))
    phase = OtisCx323Wide(36);
  else
    phase = negated_phase;
  if (!otis_cx323_wide_checked_add(frequency, phase, &combined) ||
      !otis_cx323_wide_checked_subtract(combined, OtisCx323Wide(18),
                                        &lower) ||
      !otis_cx323_wide_checked_add(combined, OtisCx323Wide(18), &upper))
    return false;
  *sign = lower > OtisCx323Wide(0)
              ? 1
              : (upper < OtisCx323Wide(0) ? -1 : 0);
  return true;
}

bool next_u64(uint64_t before, uint64_t after) {
  return before != UINT64_MAX && after == before + 1u;
}

uint32_t absolute_delta(int32_t value) {
  return value < 0 ? static_cast<uint32_t>(0u) -
                         static_cast<uint32_t>(value)
                   : static_cast<uint32_t>(value);
}

bool valid_transition(const OtisCx323MaintenanceBuildInput &input) {
  const OtisCx323Engine &before = *input.engine_before;
  const OtisCx323Engine &after = *input.engine_after;
  if (!valid_engine(before) || !valid_engine(after) ||
      !policy_equal(before.policy, after.policy) ||
      !same_text(input.reason, after.last_reason))
    return false;

  switch (input.event) {
    case OtisCx323MaintenanceEvent::PolicyActivation:
      return empty_origin(input) && input.transaction_join == nullptr &&
             !before.request_pending && !before.response_pending &&
             !after.request_pending && !after.response_pending &&
             after.fail_static_reason == nullptr && !after.metadata_hold &&
             after.persistence_count == 0u &&
             after.requalification_window_count == 0u &&
             after.debt.fll_picocodes == 0 &&
             after.debt.pll_picocodes == 0;

    case OtisCx323MaintenanceEvent::Decision: {
      if (!complete_origin(input) ||
          !next_u64(before.decision_sequence, after.decision_sequence) ||
          input.originating_decision->decision_sequence !=
              after.decision_sequence ||
          input.originating_observation->applied_code != before.applied_code ||
          input.originating_observation->dac_epoch != before.dac_epoch ||
          before.applied_code != after.applied_code ||
          before.dac_epoch != after.dac_epoch ||
          before.application_count != after.application_count ||
          before.cumulative_movement_codes !=
              after.cumulative_movement_codes ||
          !same_text(input.originating_decision->reason, input.reason))
        return false;
      const bool request_created =
          !before.request_pending && after.request_pending;
      if (request_created) {
        return decision_matches_pending(
                   after, *input.originating_observation,
                   *input.originating_decision) &&
               exact_transaction_join(
                   input,
                   OtisCx323MaintenanceTransactionEvent::RequestCreated);
      }
      return input.transaction_join == nullptr;
    }

    case OtisCx323MaintenanceEvent::RequestRejectedOrExpired:
      return exact_transaction_join(
                 input,
                 OtisCx323MaintenanceTransactionEvent::RequestWithdrawn) &&
             decision_matches_pending(
                 before, *input.originating_observation,
                 *input.originating_decision) &&
             before.request_pending && !before.response_pending &&
             !after.request_pending && !after.response_pending &&
             same_code_debt_and_budgets(before, after) &&
             before.decision_sequence == after.decision_sequence;

    case OtisCx323MaintenanceEvent::ApplicationFirstConsumer: {
      if (!exact_transaction_join(
              input, OtisCx323MaintenanceTransactionEvent::Application) ||
          !decision_matches_pending(before, *input.originating_observation,
                                    *input.originating_decision) ||
          !before.request_pending || before.response_pending ||
          after.request_pending || !after.response_pending ||
          before.decision_sequence != after.decision_sequence ||
          before.application_count == UINT32_MAX ||
          after.application_count != before.application_count + 1u)
        return false;
      const OtisCx323MaintenanceTransactionJoin &join =
          *input.transaction_join;
      const uint32_t movement =
          absolute_delta(input.originating_decision->requested_delta_codes);
      return join.actual_applied_code ==
                 static_cast<uint32_t>(after.applied_code) &&
             join.actual_applied_code == static_cast<uint32_t>(
                                                 input.originating_decision
                                                     ->requested_code) &&
             join.actual_dac_epoch == after.dac_epoch &&
             before.dac_epoch != UINT64_MAX &&
             after.dac_epoch == before.dac_epoch + 1u &&
             before.cumulative_movement_codes <= UINT32_MAX - movement &&
             after.cumulative_movement_codes ==
                 before.cumulative_movement_codes + movement &&
             after.persistence_count == 0u;
    }

    case OtisCx323MaintenanceEvent::ResponseComplete:
      return exact_transaction_join(
                 input, OtisCx323MaintenanceTransactionEvent::Response) &&
             before.response_pending && !after.response_pending &&
             !before.request_pending && !after.request_pending &&
             same_code_debt_and_budgets(before, after) &&
             before.decision_sequence == after.decision_sequence;

    case OtisCx323MaintenanceEvent::GnssMetadataHoldEnter:
      return (empty_origin(input) || exact_hybrid_join(input)) &&
             input.transaction_join == nullptr && !before.metadata_hold &&
             after.metadata_hold && !after.metadata_requalified &&
             !after.request_pending && after.persistence_count == 0u &&
             same_code_debt_and_budgets(before, after) &&
             before.decision_sequence == after.decision_sequence;

    case OtisCx323MaintenanceEvent::GnssMetadataRequalified:
      return (empty_origin(input) || exact_hybrid_join(input)) &&
             input.transaction_join == nullptr && before.metadata_hold &&
             after.metadata_hold && !before.metadata_requalified &&
             after.metadata_requalified &&
             after.requalification_frontier_available &&
             after.requalification_window_count == 0u &&
             !after.request_pending && !after.response_pending &&
             after.persistence_count == 0u &&
             same_code_debt_and_budgets(before, after) &&
             before.decision_sequence == after.decision_sequence;

    case OtisCx323MaintenanceEvent::FailStatic: {
      if (before.fail_static_reason != nullptr ||
          after.fail_static_reason == nullptr ||
          !same_text(input.reason, after.fail_static_reason) ||
          !same_code_debt_and_budgets(before, after))
        return false;
      if (input.transaction_join == nullptr)
        return empty_origin(input) || exact_hybrid_join(input);
      return exact_transaction_join(
          input, OtisCx323MaintenanceTransactionEvent::ApplicationFault);
    }
  }
  return false;
}

}  // namespace

bool otis_cx323_build_maintenance_record(
    const OtisCx323MaintenanceBuildInput *input,
    OtisCx323MaintenanceRecord *record) {
  if (input == nullptr || record == nullptr || input->engine_before == nullptr ||
      input->engine_after == nullptr ||
      input->maintenance_record_sequence == 0u ||
      input->evidence_burst_sequence == 0u ||
      input->evidence_burst_record_ordinal == 0u ||
      input->evidence_burst_record_count == 0u ||
      input->evidence_burst_record_ordinal >
          input->evidence_burst_record_count ||
      !valid_csv_atom(input->identity.run_identity) ||
      !valid_csv_atom(input->identity.build_identity) ||
      !valid_csv_atom(input->identity.profile_identity) ||
      !valid_sha256(input->identity.active_policy_sha256) ||
      !valid_sha256(input->identity.frequency_estimator_sha256) ||
      !valid_csv_atom(input->reason) || !valid_transition(*input))
    return false;

  const bool has_origin = complete_origin(*input);
  const bool has_decision_payload =
      has_origin &&
      (input->event == OtisCx323MaintenanceEvent::Decision ||
       input->transaction_join != nullptr);
  OtisCx323Wide candidate_total;
  if (has_origin && !decision_reconstructable(*input, &candidate_total))
    return false;
  if (!has_decision_payload) candidate_total = OtisCx323Wide(0);

  const OtisCx323Engine &before = *input->engine_before;
  const OtisCx323Engine &after = *input->engine_after;
  const OtisCx323Observation *observation = input->originating_observation;
  const OtisCx323Decision *decision = input->originating_decision;
  const OtisCx323MaintenanceHybridJoin *hybrid = input->hybrid_join;
  const OtisCx323MaintenanceTransactionJoin *transaction =
      input->transaction_join;

  int8_t sign = 0;
  if (observation != nullptr && !interval_sign(*observation, &sign))
    return false;
  const bool decision_event =
      input->event == OtisCx323MaintenanceEvent::Decision;
  const bool originating_code = has_decision_payload;
  const int32_t current_code =
      originating_code ? observation->applied_code : before.applied_code;
  const uint64_t current_epoch =
      originating_code ? observation->dac_epoch : before.dac_epoch;

  *record = {};
  record->maintenance_record_sequence = input->maintenance_record_sequence;
  record->event = input->event;
  record->event_timestamp_ticks = input->event_timestamp_ticks;
  record->run_identity = input->identity.run_identity;
  record->build_identity = input->identity.build_identity;
  record->profile_identity = input->identity.profile_identity;
  record->active_policy_sha256 = input->identity.active_policy_sha256;
  record->frequency_estimator_sha256 =
      input->identity.frequency_estimator_sha256;
  record->capture_session = observation == nullptr ? 0u : observation->capture_session;
  record->source_first_sequence =
      observation == nullptr ? 0u : observation->source_first_sequence;
  record->source_last_sequence =
      observation == nullptr ? 0u : observation->source_last_sequence;
  record->phase_epoch = observation == nullptr ? 0u : observation->phase_epoch;
  record->phase_observation_sequence =
      hybrid == nullptr ? 0u : hybrid->phase_observation_sequence;
  record->phase_valid = observation != nullptr && observation->phase_valid;
  record->current_applied_code = static_cast<uint32_t>(current_code);
  record->current_dac_epoch = current_epoch;
  record->hybrid_record_sequence =
      hybrid == nullptr ? 0u : hybrid->hybrid_record_sequence;
  record->hybrid_timing_record_sequence =
      hybrid == nullptr ? 0u : hybrid->hybrid_timing_record_sequence;
  record->decision_sequence =
      decision == nullptr ? 0u : decision->decision_sequence;
  record->transaction_record_sequence =
      transaction == nullptr ? 0u : transaction->transaction_record_sequence;
  record->transaction_timing_record_sequence =
      transaction == nullptr ? 0u
                             : transaction->transaction_timing_record_sequence;
  record->transaction_event =
      transaction == nullptr
          ? OtisCx323MaintenanceTransactionEvent::None
          : transaction->transaction_event;
  record->request_sequence =
      transaction == nullptr ? 0u : transaction->request_sequence;
  record->application_sequence =
      transaction == nullptr ? 0u : transaction->application_sequence;
  record->actual_applied_code =
      transaction == nullptr ? 0u : transaction->actual_applied_code;
  record->actual_dac_epoch =
      transaction == nullptr ? 0u : transaction->actual_dac_epoch;
  record->downstream_epoch_exact =
      transaction != nullptr && transaction->downstream_epoch_exact;
  record->maintenance_state_before =
      input->event == OtisCx323MaintenanceEvent::PolicyActivation
          ? OtisCx323MaintenanceState::PolicyInactive
          : state_of(before);
  record->maintenance_state_after = state_of(after);
  record->frontier_relation =
      decision_event
          ? frontier_relation(before, *observation)
          : OtisCx323FrontierRelation::NotApplicable;
  record->interval_sign = sign;
  record->persistence_count_before = before.persistence_count;
  record->persistence_count_after = after.persistence_count;
  record->raw_fll_demand_picocodes =
      !has_decision_payload ? OtisCx323Wide(0)
                          : decision->raw_fll_picocodes;
  record->raw_pll_demand_picocodes =
      !has_decision_payload ? OtisCx323Wide(0)
                          : decision->raw_pll_picocodes;
  record->candidate_total_demand_picocodes = candidate_total;
  record->safe_cap_codes =
      !has_decision_payload
          ? 0u
          : static_cast<uint8_t>(decision->safe_cap_codes);
  record->requested_delta_codes =
      !has_decision_payload ? 0 : decision->requested_delta_codes;
  record->requested_code =
      !has_decision_payload
          ? static_cast<uint32_t>(current_code)
          : static_cast<uint32_t>(decision->requested_code);
  record->committed_fll_debt_before_picocodes = before.debt.fll_picocodes;
  record->committed_pll_debt_before_picocodes = before.debt.pll_picocodes;
  record->committed_fll_debt_after_picocodes = after.debt.fll_picocodes;
  record->committed_pll_debt_after_picocodes = after.debt.pll_picocodes;
  record->request_pending_before = before.request_pending;
  record->request_pending_after = after.request_pending;
  record->response_pending_before = before.response_pending;
  record->response_pending_after = after.response_pending;
  record->metadata_hold_before = before.metadata_hold;
  record->metadata_hold_after = after.metadata_hold;
  record->requalification_window_count_before =
      before.requalification_window_count;
  record->requalification_window_count_after =
      after.requalification_window_count;
  record->requalification_d14_d8_observation_sequence =
      input->event == OtisCx323MaintenanceEvent::GnssMetadataRequalified
          ? after.requalification_frontier
          : 0u;
  record->evidence_burst_sequence = input->evidence_burst_sequence;
  record->evidence_burst_record_ordinal =
      input->evidence_burst_record_ordinal;
  record->evidence_burst_record_count = input->evidence_burst_record_count;
  record->reason = input->reason;
  return true;
}
