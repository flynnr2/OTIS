#include "otis_active_hybrid_decision_format.h"

#include <stdio.h>

#include "otis_active_hybrid_policy_engine.h"
#include "otis_cx317_active_live.h"
#include "otis_decimal_format.h"

int otis_format_active_hybrid_decision_v1(
    char *output, size_t output_size,
    const OtisCx317ActiveLiveDecision *source,
    const OtisActiveHybridDecision *decision,
    const OtisActiveHybridDecisionRecordContext *context) {
  if (output == nullptr || output_size == 0u || source == nullptr ||
      decision == nullptr || context == nullptr)
    return -1;

  char frequency_error[32] = "";
  char frequency_term[32] = "";
  char phase_term[32] = "";
  char combined_demand[32] = "";
  char raw_delta[32] = "";
  if (!otis_format_fixed(source->frequency_error_hz, 12u, frequency_error,
                         sizeof(frequency_error)) ||
      !otis_format_fixed(decision->frequency_term_hz, 12u, frequency_term,
                         sizeof(frequency_term)) ||
      !otis_format_fixed(decision->phase_term_hz, 12u, phase_term,
                         sizeof(phase_term)) ||
      !otis_format_fixed(decision->combined_demand_hz, 12u, combined_demand,
                         sizeof(combined_demand)) ||
      !otis_format_fixed(decision->raw_combined_delta_codes, 12u, raw_delta,
                         sizeof(raw_delta)))
    return -1;

  return snprintf(
      output, output_size,
      "AHY,1,%lu,%lu,%lu,%s,%s,%s,%lu,%lu,%lu,%s,%s,%ld,%s,%s,%lu,%lu,%lld,%s,%s,%s,%s,%u,%lu,%u,%lu,%s,%s,%s,%s,%s,%s,%ld,%u,%ld,%s,%s,%s,%s,%s,%s,%u,%u,%s,%lu,%lu,%lu,%s,%u,%lu,%s,%s,%s,%s,%s\r\n",
      static_cast<unsigned long>(context->hybrid_record_sequence),
      static_cast<unsigned long>(decision->decision_sequence),
      static_cast<unsigned long>(source->timestamp_s), context->run_identity,
      context->build_identity, context->profile_identity,
      static_cast<unsigned long>(source->capture_session),
      static_cast<unsigned long>(source->source_first_sequence),
      static_cast<unsigned long>(source->source_last_sequence),
      context->frequency_estimator_sha256, frequency_error,
      static_cast<long>(source->accumulated_edge_error_counts),
      source->tight_state == nullptr ? "UNAVAILABLE" : source->tight_state,
      context->phase_estimator_sha256,
      static_cast<unsigned long>(source->phase_epoch),
      static_cast<unsigned long>(source->phase_observation_sequence),
      static_cast<long long>(source->relative_phase_cycles),
      source->phase_continuous ? "true" : "false",
      source->phase_current ? "true" : "false",
      source->phase_step_detected ? "true" : "false",
      source->phase_recorder_published ? "true" : "false",
      source->current_applied_code,
      static_cast<unsigned long>(source->dac_epoch), source->phase_applied_code,
      static_cast<unsigned long>(source->phase_dac_epoch),
      otis_active_hybrid_state_name(decision->state_before),
      otis_active_hybrid_state_name(decision->state_after), frequency_term,
      phase_term, combined_demand, raw_delta,
      static_cast<long>(decision->requested_delta_codes),
      decision->requested_code,
      static_cast<long>(decision->counterfactual_frequency_only_delta_codes),
      decision->phase_materially_influenced ? "true" : "false",
      decision->step_limited ? "true" : "false",
      decision->range_clamped ? "true" : "false",
      decision->cadence_limited ? "true" : "false",
      decision->count_limited ? "true" : "false",
      decision->cumulative_budget_limited ? "true" : "false",
      decision->correction_count_before,
      decision->cumulative_movement_before_codes, context->authority_state,
      static_cast<unsigned long>(context->request_sequence),
      static_cast<unsigned long>(context->acceptance_sequence),
      static_cast<unsigned long>(context->application_sequence),
      context->response_class, source->current_applied_code,
      static_cast<unsigned long>(source->dac_epoch),
      context->downstream_epoch_exact ? "true" : "false", decision->reason,
      context->active_policy_sha256, context->response_policy_sha256,
      context->actionable ? "true" : "false");
}
