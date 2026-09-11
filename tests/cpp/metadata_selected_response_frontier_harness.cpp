#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "../../firmware/arduino/otis_nano_rp2040_connect/otis_adaptive_hybrid_regulation_live.cpp"
#include "../../firmware/arduino/otis_nano_rp2040_connect/otis_phase_preview_live.h"

void prepare_delayed_selected_response(uint64_t captured_ticks);
void produce_delayed_selected_response(
    uint64_t captured_ticks, uint64_t operational_ticks,
    OtisAdaptiveHybridRegulationLiveOutcome *outcome);

bool otis_phase_preview_live_get_active_snapshot(OtisPhasePreviewActiveSnapshot *snapshot) {
  *snapshot = {};
  snapshot->phase_epoch = 3u;
  snapshot->observation_sequence = 1300u;
  snapshot->dac_epoch = 2u;
  snapshot->applied_code = 43086u;
  snapshot->phase_continuous = true;
  snapshot->phase_current = true;
  snapshot->recorder_published = true;
  return true;
}

void bind_response_commit_state() {
  transaction = {};
  transaction_bound = true;
  transaction.expected_binding = expected_binding(7u);
  transaction.state = OtisRegulationState::AwaitingResponse;
  transaction.reason = "applied_history_reset_response_required";
  transaction.request.request_sequence = 9u;
  transaction.request.authorization_sequence = 3u;
  transaction.request.nonce = 5u;
  transaction.request.session_id = 7u;
  transaction.request.decision_sequence = 10u;
  transaction.request.source_first_sequence = 100u;
  transaction.request.source_last_sequence = 700u;
  transaction.request.timestamp_s = 4400u;
  transaction.request.current_applied_code = 43085u;
  transaction.request.requested_delta_codes = 1;
  transaction.request.requested_code = 43086u;
  transaction.request.pre_error_hz = 0.0002;
  transaction.request.correction_ordinal = 1u;
  transaction.request.cumulative_after_codes = 1u;
  transaction.request.actionable = true;
  transaction.accepted.request_sequence = 9u;
  transaction.accepted.authorization_sequence = 3u;
  transaction.accepted.nonce = 5u;
  transaction.accepted.accepted_code = 43086u;
  transaction.accepted.accepted_timestamp_s = 4400u;
  transaction.accepted.actionable = true;
  transaction.applied.request_sequence = 9u;
  transaction.applied.authorization_sequence = 3u;
  transaction.applied.nonce = 5u;
  transaction.applied.requested_code = 43086u;
  transaction.applied.accepted_code = 43086u;
  transaction.applied.applied_code = 43086u;
  transaction.applied.application_sequence = 4u;
  transaction.applied.application_timestamp_s = 4400u;
  transaction.applied.i2c_ok = true;
  transaction.applied_code = 43086u;
  transaction.correction_count = 1u;
  transaction.cumulative_movement_codes = 1u;
  transaction.dac_epoch = 2u;
  transaction.have_last_application = true;
  transaction.have_request = true;
  transaction.have_acceptance = true;
  transaction.have_application = true;

  const OtisAdaptiveHybridPolicy policy = otis_adaptive_hybrid_default_policy();
  assert(otis_adaptive_hybrid_engine_init(
      &adaptive_hybrid_engine, &policy, 43086, 2u));
  adaptive_hybrid_engine.decision_sequence = 10u;
  adaptive_hybrid_engine.application_count = 1u;
  adaptive_hybrid_engine.cumulative_movement_codes = 1u;
  adaptive_hybrid_engine.response_pending = true;
  adaptive_hybrid_engine.last_application_available = true;
  adaptive_hybrid_engine.last_application_s = 4400u;
  adaptive_hybrid_engine.last_application_ticks = 4400000000ull;
  adaptive_hybrid_engine.last_reason =
      "application_and_first_consumer_committed";
  adaptive_hybrid_engine_ready = true;

  pending_adaptive_hybrid_observation = {};
  pending_adaptive_hybrid_observation.timestamp_s = 4400u;
  pending_adaptive_hybrid_observation.timestamp_ticks = 4400000000ull;
  pending_adaptive_hybrid_observation.capture_session = 7u;
  pending_adaptive_hybrid_observation.source_first_sequence = 100u;
  pending_adaptive_hybrid_observation.source_last_sequence = 700u;
  pending_adaptive_hybrid_observation.dac_epoch = 1u;
  pending_adaptive_hybrid_observation.applied_code = 43085;
  pending_adaptive_hybrid_observation.phase_epoch = 3u;
  pending_adaptive_hybrid_observation.phase_valid = true;
  pending_adaptive_hybrid_decision = {};
  pending_adaptive_hybrid_decision.decision_sequence = 10u;
  pending_adaptive_hybrid_decision.decision_timestamp_ticks = 4400000000ull;
  pending_adaptive_hybrid_decision.requested_delta_codes = 1;
  pending_adaptive_hybrid_decision.requested_code = 43086;
  pending_adaptive_hybrid_decision.safe_cap_codes = 1;
  pending_adaptive_hybrid_decision.reason = "outside_tight_ordinary_request_ready";
  pending_adaptive_hybrid_hybrid_join = {
      10u, 10u, 7u, 100u, 700u, 3u, 700u, true};
  pending_adaptive_hybrid_decision_valid = true;
  pending_adaptive_hybrid_origin_valid = true;

  latest_health = {};
  latest_health.session_id = 7u;
  latest_health.gnss_metadata_valid = true;
  latest_health.gnss_identity_stable = true;
  latest_health.gnss_3d_evidence = true;
  latest_health.raw_pps_valid = true;
  latest_health.reference_integrity_valid = true;
  latest_health.count_valid = true;
  latest_health.estimator_valid = true;
  latest_health.model_applicable = true;
  latest_health.temperature_valid = true;
  latest_health.applied_code_confirmed = true;
  latest_health.applied_code = 43086u;
  latest_health.abort_path_live = true;
  have_health = true;
  have_capture_lease = true;
  last_capture_lease_s = 5000u;
  evidence_phase = EvidencePhase::None;
  transaction_record_sequence = 10u;
  hybrid_record_sequence = 10u;
  adaptive_hybrid_maintenance_record_sequence = 20u;
  adaptive_hybrid_evidence_burst_sequence = 20u;
  adaptive_hybrid_collecting_evidence_burst = false;
  frame = {};
  otis_dependent_response_identity_reset(&dependent_response_identity);
}


int main() {
  constexpr uint64_t captured_ticks = 4999999000ull;
  constexpr uint64_t metadata_event_ticks = 5000000100ull;
  constexpr uint64_t operational_ticks = 5000000200ull;
  otis_dual_core_partition_reset();
  prepare_delayed_selected_response(captured_ticks);
  initialized = true;
  transaction_bound = true;
  manual_start_confirmed = true;
  bind_response_commit_state();
  last_adaptive_hybrid_observation = pending_adaptive_hybrid_observation;
  last_adaptive_hybrid_decision = pending_adaptive_hybrid_decision;
  last_adaptive_hybrid_hybrid_join = pending_adaptive_hybrid_hybrid_join;
  last_adaptive_hybrid_origin_valid = true;
  latest_health.gnss_metadata_sequence = 42u;
  latest_health.d14_d8_observation_sequence = 1300u;
  latest_health.gnss_metadata_valid = false;
  // Timestamped metadata hold is consumed before a delayed selected boundary.
  // No Core 0 consumer runs until the entire real producer frontier completes.
  const OtisAdaptiveHybridRegulationLiveHealth health = latest_health;
  otis_adaptive_hybrid_regulation_live_update_health_at_ticks(
      &health, 5000u, metadata_event_ticks % (1ull << 32));
  assert(gnss_metadata_hold_active);
  assert(adaptive_hybrid_engine.metadata_hold);
  OtisDualCoreQueueStats stats = {};
  otis_dual_core_get_stats(&stats);
  assert(stats.evidence_depth == OTIS_EVIDENCE_METADATA_TRANSITION_COUNT);
  OtisAdaptiveHybridRegulationLiveOutcome outcome = {};
  produce_delayed_selected_response(captured_ticks, operational_ticks, &outcome);
  assert(!outcome.faulted);
  assert(outcome.response_recorded);
  assert(!outcome.request_created);
  assert(!otis_dual_core_fail_static());
  otis_dual_core_get_stats(&stats);
  assert(stats.evidence_depth == OTIS_EVIDENCE_METADATA_RESPONSE_FRONTIER);
  assert(stats.evidence_high_water == OTIS_EVIDENCE_METADATA_RESPONSE_FRONTIER);

  OtisEvidenceFrameMessage record = {};
  uint32_t count = 0u;
  while (otis_dual_core_take_evidence(&record)) {
    ++count;
    printf("%s", record.data);
  }
  assert(count == OTIS_EVIDENCE_METADATA_RESPONSE_FRONTIER);
}
