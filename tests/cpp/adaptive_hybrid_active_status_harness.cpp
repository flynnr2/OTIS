#include <assert.h>
#include <stdio.h>
#include <string.h>

#define OTIS_BUILD_IMAGE_ID "adaptive_hybrid_regulation"

// Include the production translation unit so this harness exercises the real
// adaptive hybrid status getter and its complete post-branch assignment surface.  Dead
// section elimination removes unrelated live hardware paths from the host
// executable; the few dependencies reached by the getter are linked by the
// Python driver or stubbed below.
#include "../../firmware/arduino/otis_nano_rp2040_connect/otis_adaptive_hybrid_regulation_live.cpp"

void otis_status_emit(OtisStatusEmitContext *context, const char *component,
                      const char *key, const char *value,
                      const char *severity, uint32_t flags) {
  assert(context != nullptr);
  assert(context->sink != nullptr);
  context->sink(context->sink_context, component, key, value, severity,
                flags);
}

bool otis_dual_core_fail_static(void) { return false; }
void otis_dual_core_latch_fault(OtisPartitionFault) {}
OtisEvidenceFrameMessage captured_evidence = {};
bool accept_evidence = true;
OtisEvidenceFrameMessage captured_burst[OTIS_EVIDENCE_QUEUE_DEPTH] = {};
uint32_t captured_burst_count = 0u;
uint32_t expected_burst_count = 0u;
bool otis_dual_core_publish_evidence(const OtisEvidenceFrameMessage *message) {
  if (message == nullptr || !accept_evidence) return false;
  captured_evidence = *message;
  return true;
}
bool otis_dual_core_begin_evidence_burst(uint32_t message_count) {
  if (!accept_evidence || message_count == 0u ||
      message_count > OTIS_EVIDENCE_QUEUE_DEPTH)
    return false;
  captured_burst_count = 0u;
  expected_burst_count = message_count;
  return true;
}
bool otis_dual_core_append_evidence_burst(
    const OtisEvidenceFrameMessage *message) {
  if (!accept_evidence || message == nullptr ||
      captured_burst_count >= expected_burst_count)
    return false;
  captured_burst[captured_burst_count++] = *message;
  return true;
}
bool otis_dual_core_commit_evidence_burst(void) {
  return accept_evidence && captured_burst_count == expected_burst_count;
}
void otis_dual_core_cancel_evidence_burst(void) {
  captured_burst_count = 0u;
  expected_burst_count = 0u;
}
bool otis_dual_core_evidence_can_publish(uint32_t message_count) {
  return accept_evidence && message_count <= OTIS_EVIDENCE_QUEUE_DEPTH;
}
void otis_dual_core_note_timing_progress(OtisTimingProgressPhase, uint64_t) {}

namespace {

uint32_t emitted_status_sequence = 1u;

void emit_transport_limited_status(void *, const char *component,
                                   const char *key, const char *value,
                                   const char *severity, uint32_t flags) {
  OtisTelemetryMessage transported = {};
  snprintf(transported.component, sizeof(transported.component), "%s",
           component);
  snprintf(transported.key, sizeof(transported.key), "%s", key);
  snprintf(transported.value, sizeof(transported.value), "%s", value);
  snprintf(transported.severity, sizeof(transported.severity), "%s",
           severity);
  printf("STS,1,%lu,1,rp2040_monotonic_us32,%s,%s,%s,%s,%lu\n",
         static_cast<unsigned long>(emitted_status_sequence++),
         transported.component, transported.key, transported.value,
         transported.severity, static_cast<unsigned long>(flags));
}

uint32_t csv_field_count(const char *record) {
  assert(record != nullptr && *record != '\0');
  uint32_t count = 1u;
  for (const char *cursor = record; *cursor != '\0' && *cursor != '\r'; ++cursor) {
    if (*cursor == ',') ++count;
  }
  return count;
}

void bind_common_application_state() {
  transaction = {};
  transaction_bound = true;
  manual_start_confirmed = true;
  transaction.state = OtisRegulationState::AwaitingResponse;
  transaction.reason = "applied_history_reset_response_required";
  transaction.applied_code = 43086u;
  transaction.correction_count = 1u;
  transaction.cumulative_movement_codes = 1u;
  transaction.dac_epoch = 2u;

  adaptive_hybrid_engine = {};
  adaptive_hybrid_engine_ready = true;
  adaptive_hybrid_engine.applied_code = 43086;
  adaptive_hybrid_engine.dac_epoch = 2u;
  adaptive_hybrid_engine.application_count = 1u;
  adaptive_hybrid_engine.cumulative_movement_codes = 1u;
  adaptive_hybrid_engine.response_pending = true;
  adaptive_hybrid_engine.last_reason = "application_and_first_consumer_committed";

  adaptive_hybrid_phase_nonzero_application_count = 1u;
  adaptive_hybrid_phase_material_application_count = 1u;
  adaptive_hybrid_frequency_only_application_count = 0u;
  last_adaptive_hybrid_origin_valid = true;
  last_adaptive_hybrid_observation = {};
  last_adaptive_hybrid_observation.phase_valid = true;

  // Adaptive hybrid owns the selected controller status independently; an
  // inactive auxiliary engine must not overwrite its projection.
  hybrid_engine = {};
  hybrid_engine_ready = false;
}

void assert_common_application_status(
    const OtisAdaptiveHybridRegulationLiveStatus &status) {
  assert(status.applied_code == 43086u);
  assert(status.correction_count == 1u);
  assert(status.cumulative_movement_codes == 1u);
  assert(status.dac_epoch == 2u);
  assert(status.phase_nonzero_application_count == 1u);
  assert(status.phase_material_application_count == 1u);
  assert(status.frequency_only_application_count == 0u);
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
  transaction.request.source_acceptance_epoch = 3u;
  transaction.request.source_opening_accepted_boundary_ordinal = 100u;
  transaction.request.source_closing_accepted_boundary_ordinal = 700u;
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
  pending_adaptive_hybrid_observation.source_acceptance_epoch = 3u;
  pending_adaptive_hybrid_observation.source_opening_accepted_boundary_ordinal = 100u;
  pending_adaptive_hybrid_observation.source_closing_accepted_boundary_ordinal = 700u;
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
      10u, 10u, 7u, 3u, 100u, 700u, 3u, 700u, true};
  pending_adaptive_hybrid_decision_valid = true;
  pending_adaptive_hybrid_origin_valid = true;

  latest_health = {};
  latest_health.session_id = 7u;
  latest_health.acceptance_epoch = 3u;
  latest_health.accepted_boundary_ordinal = 700u;
  latest_health.accepted_anchor_current = true;
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
  evidence_request_sequence = 0u;
  evidence_phase = EvidencePhase::None;
  transaction_record_sequence = 10u;
  hybrid_record_sequence = 10u;
  adaptive_hybrid_maintenance_record_sequence = 20u;
  adaptive_hybrid_evidence_burst_sequence = 20u;
  adaptive_hybrid_collecting_evidence_burst = false;
  frame = {};
  otis_dependent_response_identity_reset(&dependent_response_identity);
}

void stale_accepted_source_after_requalification_has_zero_authority() {
  transaction = {};
  transaction_bound = true;
  manual_start_confirmed = true;
  const OtisRegulationBinding binding = expected_binding(7u);
  otis_regulation_transaction_init(&transaction, &binding);

  latest_health = {};
  latest_health.session_id = 7u;
  latest_health.acceptance_epoch = 4u;
  latest_health.accepted_boundary_ordinal = 1300u;
  latest_health.accepted_anchor_current = true;
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
  latest_health.applied_code = OTIS_ADAPTIVE_HYBRID_START_CODE;
  latest_health.abort_path_live = true;
  have_health = true;
  have_capture_lease = true;
  last_capture_lease_s = 5000u;
  evidence_phase = EvidencePhase::None;
  evidence_request_sequence = 0u;

  const OtisAdaptiveHybridPolicy policy = otis_adaptive_hybrid_default_policy();
  assert(otis_adaptive_hybrid_engine_init(
      &adaptive_hybrid_engine, &policy, OTIS_ADAPTIVE_HYBRID_START_CODE, 1u));
  adaptive_hybrid_engine_ready = true;
  const OtisRegulationEligibility ready = eligibility(5000u);
  const OtisRegulationArmRequest arm = {binding, 21u, 22u, 5060u};
  assert(otis_regulation_arm(&transaction, &arm, &ready, 5000u));

  OtisAdaptiveHybridRegulationLiveDecision stale = {};
  stale.decision_sequence = 21u;
  stale.timestamp_s = 5000u;
  stale.current_applied_code = OTIS_ADAPTIVE_HYBRID_START_CODE;
  stale.frequency_error_hz = 0.001;
  stale.measurement_valid = true;
  stale.model_applicable = true;
  stale.preview_available = true;
  stale.capture_session = 7u;
  // This span was selected before requalification.  Its capture session and
  // raw interval are plausible, but its accepted-reference epoch is stale.
  stale.source_acceptance_epoch = 3u;
  stale.source_opening_accepted_boundary_ordinal = 100u;
  stale.source_closing_accepted_boundary_ordinal = 700u;
  stale.accumulated_edge_error_counts = 1;
  stale.tight_state = "OUTSIDE";
  stale.dac_epoch = 1u;
  stale.phase_epoch = 1u;
  stale.phase_observation_sequence = 700u;
  stale.phase_dac_epoch = 1u;
  stale.phase_applied_code = OTIS_ADAPTIVE_HYBRID_START_CODE;
  stale.phase_continuous = true;
  stale.phase_current = true;
  stale.phase_recorder_published = true;

  OtisAdaptiveHybridRegulationLiveOutcome outcome = {};
  otis_adaptive_hybrid_regulation_live_on_decision_at_ticks(
      &stale, 5000000000ull, &outcome);
  assert(!outcome.faulted);
  assert(!outcome.request_created);
  assert(!pending_actionable_request_valid);
  assert(transaction.state == OtisRegulationState::Disarmed);
  assert(strcmp(transaction.reason, "zero_delta_disarmed_without_request") == 0);
}

}  // namespace

int main() {
  static_assert(OTIS_REGULATION_STATUS_FIELD_COUNT == 49u);
  static_assert(OTIS_REGULATION_STATUS_TELEMETRY_BURST == 52u);
  static_assert(OTIS_TIMING_HEALTH_TELEMETRY_BURST == 143u);
  static_assert(OTIS_MAXIMUM_CONCURRENT_TELEMETRY_BURST == 195u);
  static_assert(OTIS_TELEMETRY_QUEUE_DEPTH == 196u);
  initialized = true;
  transaction_bound = true;
  const OtisRegulationBinding pre_setup_binding = expected_binding(7u);
  otis_regulation_transaction_init(&transaction, &pre_setup_binding);
  transaction_record_sequence = 0u;
  manual_start_confirmed = false;
  frame = {};

  // The selected D14/D8 decision producer remains live before setup, but its
  // active-control consumer must be a zero-authority no-op.  Exercise the
  // production adapter and then its first decision-bearing status consumer.
  OtisAdaptiveHybridRegulationLiveDecision pre_setup_decision = {};
  pre_setup_decision.decision_sequence = 1u;
  pre_setup_decision.timestamp_s = 600u;
  pre_setup_decision.capture_session = 7u;
  pre_setup_decision.source_acceptance_epoch = 3u;
  pre_setup_decision.source_opening_accepted_boundary_ordinal = 1u;
  pre_setup_decision.source_closing_accepted_boundary_ordinal = 600u;
  pre_setup_decision.measurement_valid = true;
  pre_setup_decision.preview_available = true;
  OtisAdaptiveHybridRegulationLiveOutcome pre_setup_outcome = {};
  otis_adaptive_hybrid_regulation_live_on_decision_at_ticks(
      &pre_setup_decision, 600000000ull, &pre_setup_outcome);
  assert(!pre_setup_outcome.request_created);
  assert(!pre_setup_outcome.application_attempted);
  assert(!pre_setup_outcome.applied);
  assert(!pre_setup_outcome.response_recorded);
  assert(!pre_setup_outcome.faulted);
  assert(strcmp(pre_setup_outcome.reason,
                "manual_start_not_confirmed_no_control_authority") == 0);
  assert(transaction.state == OtisRegulationState::Disarmed);
  assert(strcmp(transaction.reason, "initialized_disarmed") == 0);
  assert(!transaction.have_arm);
  assert(!transaction.have_request);
  assert(!transaction.have_acceptance);
  assert(!transaction.have_application);
  assert(transaction.correction_count == 0u);
  assert(transaction.cumulative_movement_codes == 0u);
  assert(transaction.dac_epoch == 0u);
  assert(transaction_record_sequence == 0u);
  assert(evidence_phase == EvidencePhase::None);
  assert(!adaptive_hybrid_engine_ready);

  OtisAdaptiveHybridRegulationLiveStatus pre_setup_status = {};
  otis_adaptive_hybrid_regulation_live_get_status(&pre_setup_status, 600u);
  assert(strcmp(pre_setup_status.state, "DISARMED") == 0);
  assert(strcmp(pre_setup_status.reason, "initialized_disarmed") == 0);
  assert(strcmp(pre_setup_status.hybrid_state, "SETUP_PENDING") == 0);
  assert(strcmp(pre_setup_status.hybrid_reason,
                "setup_consumers_pending") == 0);
  assert(!pre_setup_status.manual_start_confirmed);
  assert(!pre_setup_status.confirmed_applied_code_known);
  assert(!pre_setup_status.fail_static);
  assert(pre_setup_status.correction_count == 0u);
  assert(pre_setup_status.cumulative_movement_codes == 0u);
  assert(pre_setup_status.dac_epoch == 0u);
  OtisStatusEmitContext pre_setup_status_context = {};
  pre_setup_status_context.sink = emit_transport_limited_status;
  otis_adaptive_hybrid_regulation_live_emit_status(
      &pre_setup_status_context, 600u);

  // The exemption is deliberately narrow: partial authority state before
  // setup still fails closed instead of being silently treated as inhibited.
  transaction.have_arm = true;
  OtisAdaptiveHybridRegulationLiveOutcome inconsistent_pre_setup = {};
  otis_adaptive_hybrid_regulation_live_on_decision_at_ticks(
      &pre_setup_decision, 600000000ull, &inconsistent_pre_setup);
  assert(inconsistent_pre_setup.faulted);
  assert(strcmp(inconsistent_pre_setup.reason,
                "pre_setup_control_state_inconsistent") == 0);
  otis_regulation_transaction_init(&transaction, &pre_setup_binding);

  assert(!otis_adaptive_hybrid_regulation_live_note_manual_start_exact(
      OTIS_ADAPTIVE_HYBRID_START_CODE, 1u, true, 4294u, 0u, 7u));
  transaction = {};
  transaction.state = OtisRegulationState::Disarmed;
  transaction.expected_binding.session_id = 7u;
  transaction_record_sequence = 0u;
  manual_start_confirmed = false;
  frame = {};
  const uint64_t exact_setup_ticks = 4294967297000ull;
  assert(otis_adaptive_hybrid_regulation_live_note_manual_start_exact(
      OTIS_ADAPTIVE_HYBRID_START_CODE, 1u, true,
      static_cast<uint32_t>(exact_setup_ticks / 1000000ull),
      exact_setup_ticks, 7u));
  assert(manual_start_confirmed);
  assert(transaction_record_sequence == 1u);
  assert(strstr(captured_evidence.data,
                "ACT,3,1,manual_start,4294967297000,"
                "rp2040_monotonic_us64,") != nullptr);
  assert(captured_evidence.length == strlen(captured_evidence.data));
  assert(csv_field_count(captured_evidence.data) == 50u);
  assert(!otis_adaptive_hybrid_regulation_live_note_manual_start_exact(
      OTIS_ADAPTIVE_HYBRID_START_CODE, 1u, true,
      static_cast<uint32_t>(exact_setup_ticks / 1000000ull),
      exact_setup_ticks, 7u));
  assert(transaction_record_sequence == 1u);

  OtisAdaptiveHybridRegulationLiveDecision dependent_source = {};
  dependent_source.timestamp_s = 5000u;
  dependent_source.capture_session = 7u;
  dependent_source.source_acceptance_epoch = 3u;
  dependent_source.source_opening_accepted_boundary_ordinal = 100u;
  dependent_source.source_closing_accepted_boundary_ordinal = 700u;
  dependent_source.tight_state = "OUTSIDE";
  dependent_source.phase_recorder_published = true;
  dependent_source.current_applied_code = OTIS_ADAPTIVE_HYBRID_START_CODE;
  dependent_source.dac_epoch = 2u;
  dependent_source.phase_applied_code = OTIS_ADAPTIVE_HYBRID_START_CODE;
  dependent_source.phase_dac_epoch = 2u;
  OtisActiveHybridDecision dependent_decision = {};
  dependent_decision.decision_sequence = 10u;
  dependent_decision.timestamp_s = 5000u;
  dependent_decision.state_before = OtisActiveHybridState::HybridTracking;
  dependent_decision.state_after = OtisActiveHybridState::HybridTracking;
  dependent_decision.reason = "dependent_response_consumed";
  dependent_decision.requested_code = OTIS_ADAPTIVE_HYBRID_START_CODE;
  dependent_decision.counterfactual_frequency_only_delta_codes = 0;
  hybrid_record_sequence = 0u;
  frame = {};
  otis_dependent_response_identity_reset(&dependent_response_identity);
  assert(otis_dependent_response_identity_retain(
      &dependent_response_identity, 9u, 4u,
      "healthy_indeterminate_near_resolution"));
  accept_evidence = false;
  assert(!queue_active_hybrid_decision(dependent_source, dependent_decision,
                                       5000000000ull));
  assert(dependent_response_identity.pending);
  accept_evidence = true;
  assert(queue_active_hybrid_decision(dependent_source, dependent_decision,
                                      5000000000ull));
  assert(!dependent_response_identity.pending);
  assert(strstr(captured_evidence.data,
                ",9,9,4,healthy_indeterminate_near_resolution,") != nullptr);
  assert(csv_field_count(captured_evidence.data) == 59u);
  dependent_decision.decision_sequence = 11u;
  dependent_decision.timestamp_s = 5600u;
  dependent_source.timestamp_s = 5600u;
  assert(queue_active_hybrid_decision(dependent_source, dependent_decision,
                                      5600000000ull));
  assert(strstr(captured_evidence.data, ",0,0,0,unavailable,") != nullptr);

  // Enter through the real decision producer and response burst commit. The
  // committed ACT/AHM response burst retains its exact identity for the first
  // subsequent AHY; it does not rely on direct holder setup.
  bind_response_commit_state();
  OtisAdaptiveHybridRegulationLiveDecision response_source = {};
  response_source.timestamp_s = 5000u;
  response_source.current_applied_code = 43086u;
  response_source.frequency_error_hz = 0.0002;
  response_source.measurement_valid = true;
  response_source.model_applicable = true;
  response_source.preview_available = true;
  response_source.capture_session = 7u;
  response_source.source_acceptance_epoch = 3u;
  response_source.source_opening_accepted_boundary_ordinal = 700u;
  response_source.source_closing_accepted_boundary_ordinal = 1300u;
  response_source.tight_state = "TIGHT_INSIDE";
  response_source.dac_epoch = 2u;
  response_source.phase_epoch = 3u;
  response_source.phase_observation_sequence = 1300u;
  response_source.phase_dac_epoch = 2u;
  response_source.phase_applied_code = 43086u;
  response_source.phase_continuous = true;
  response_source.phase_current = true;
  response_source.phase_recorder_published = true;
  latest_health.accepted_boundary_ordinal = 1300u;
  OtisAdaptiveHybridRegulationLiveOutcome response_outcome = {};
  otis_adaptive_hybrid_regulation_live_on_decision_at_ticks(
      &response_source, 5000000000ull, &response_outcome);
  assert(!response_outcome.faulted);
  assert(response_outcome.response_recorded);
  assert(response_outcome.response_class ==
         OtisRegulationResponseClass::HealthyIndeterminateNearResolution);
  assert(captured_burst_count == 2u);
  assert(strncmp(captured_burst[0].data, "ACT,3,11,response,5000000000,", 29u) == 0);
  assert(strncmp(captured_burst[1].data, "AHM,2,22,response_complete,", 27u) == 0);
  assert(csv_field_count(captured_burst[0].data) == 50u);
  assert(csv_field_count(captured_burst[1].data) == 60u);
  assert(dependent_response_identity.pending);
  assert(dependent_response_identity.request_sequence == 9u);
  assert(dependent_response_identity.application_sequence == 4u);
  dependent_source.timestamp_s = 5600u;
  dependent_source.current_applied_code = 43086u;
  dependent_source.dac_epoch = 2u;
  dependent_source.phase_applied_code = 43086u;
  dependent_decision.decision_sequence = 12u;
  dependent_decision.timestamp_s = 5600u;
  dependent_decision.requested_code = 43086u;
  assert(queue_active_hybrid_decision(dependent_source, dependent_decision,
                                      5600000000ull));
  assert(!dependent_response_identity.pending);
  assert(strstr(captured_evidence.data,
                ",9,9,4,healthy_indeterminate_near_resolution,") != nullptr);
  assert(csv_field_count(captured_evidence.data) == 59u);

  stale_accepted_source_after_requalification_has_zero_authority();

  bind_common_application_state();

  OtisAdaptiveHybridRegulationLiveStatus pending = {};
  otis_adaptive_hybrid_regulation_live_get_status(&pending, 11110u);
  assert(strcmp(pending.state, "AWAITING_RESPONSE") == 0);
  assert(strcmp(pending.hybrid_state, "FIRST_PHASE_TRANSACTION") == 0);
  assert(strcmp(pending.hybrid_reason,
                "application_and_first_consumer_committed") == 0);
  assert(!pending.first_phase_checkpoint_passed);
  assert_common_application_status(pending);

  transaction.state = OtisRegulationState::Disarmed;
  transaction.reason = "healthy_evidence_below_empirical_detection_floor";
  adaptive_hybrid_engine.response_pending = false;
  adaptive_hybrid_engine.last_reason = "response_completed";
  evidence_phase = EvidencePhase::Response;
  evidence_request_sequence = 1u;

  // Response completion precedes the host's evidence release. The completed
  // generation preserves the controller checkpoint while immutable response
  // evidence remains pending.
  OtisAdaptiveHybridRegulationLiveStatus response_evidence_pending = {};
  otis_adaptive_hybrid_regulation_live_get_status(&response_evidence_pending, 11111u);
  assert(strcmp(response_evidence_pending.state, "DISARMED") == 0);
  assert(strcmp(response_evidence_pending.evidence_state,
                "response_pending") == 0);
  assert(response_evidence_pending.evidence_pending);
  assert(response_evidence_pending.evidence_request_sequence == 1u);
  assert(strcmp(response_evidence_pending.hybrid_state,
                "HYBRID_TRACKING") == 0);
  assert(strcmp(response_evidence_pending.hybrid_reason,
                "response_completed") == 0);
  assert(response_evidence_pending.first_phase_checkpoint_passed);
  assert_common_application_status(response_evidence_pending);

  evidence_phase = EvidencePhase::None;
  evidence_request_sequence = 0u;
  OtisAdaptiveHybridRegulationLiveStatus complete = {};
  otis_adaptive_hybrid_regulation_live_get_status(&complete, 11112u);
  assert(strcmp(complete.evidence_state, "evidence_clear") == 0);
  assert(!complete.evidence_pending);
  assert(complete.evidence_request_sequence == 0u);
  assert(strcmp(complete.hybrid_state, "HYBRID_TRACKING") == 0);
  assert(complete.first_phase_checkpoint_passed);
  assert_common_application_status(complete);

  // Exercise the production status emitter through the real cross-core
  // component width.  The Python driver consumes these rows with the live
  // host reducer, covering the firmware-to-host contract that protects the
  // live supervisor handoff.
  OtisStatusEmitContext status_context = {};
  status_context.sink = emit_transport_limited_status;
  otis_adaptive_hybrid_regulation_live_emit_status(&status_context, 11112u);
  return 0;
}
