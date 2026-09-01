#include <assert.h>
#include <string.h>

// Include the production translation unit so this harness exercises the real
// CX323 status getter and its complete post-branch assignment surface.  Dead
// section elimination removes unrelated live hardware paths from the host
// executable; the few dependencies reached by the getter are linked by the
// Python driver or stubbed below.
#include "../../firmware/arduino/otis_nano_rp2040_connect/otis_cx317_active_live.cpp"

bool otis_dual_core_fail_static(void) { return false; }

namespace {

void bind_common_application_state() {
  transaction = {};
  transaction_bound = true;
  manual_start_confirmed = true;
  transaction.state = OtisCx317ActiveState::AwaitingResponse;
  transaction.reason = "applied_history_reset_response_required";
  transaction.applied_code = 43086u;
  transaction.correction_count = 1u;
  transaction.cumulative_movement_codes = 1u;
  transaction.dac_epoch = 2u;

  cx323_engine = {};
  cx323_engine_ready = true;
  cx323_engine.applied_code = 43086;
  cx323_engine.dac_epoch = 2u;
  cx323_engine.application_count = 1u;
  cx323_engine.cumulative_movement_codes = 1u;
  cx323_engine.response_pending = true;
  cx323_engine.last_reason = "application_and_first_consumer_committed";

  cx323_phase_nonzero_application_count = 1u;
  cx323_phase_material_application_count = 1u;
  cx323_frequency_only_application_count = 0u;
  last_cx323_origin_valid = true;
  last_cx323_observation = {};
  last_cx323_observation.phase_valid = true;

  // CX323 deliberately leaves the legacy engine inactive.  Attempt 8 was
  // caused by this zero state overwriting the correct CX323 projection.
  hybrid_engine = {};
  hybrid_engine_ready = false;
}

void assert_common_application_status(
    const OtisCx317ActiveLiveStatus &status) {
  assert(status.applied_code == 43086u);
  assert(status.correction_count == 1u);
  assert(status.cumulative_movement_codes == 1u);
  assert(status.dac_epoch == 2u);
  assert(status.automatic_application_count == 1u);
  assert(status.phase_nonzero_application_count == 1u);
  assert(status.phase_material_application_count == 1u);
  assert(status.frequency_only_application_count == 0u);
}

}  // namespace

int main() {
  bind_common_application_state();

  OtisCx317ActiveLiveStatus pending = {};
  otis_cx317_active_live_get_status(&pending, 11110u);
  assert(strcmp(pending.state, "AWAITING_RESPONSE") == 0);
  assert(strcmp(pending.hybrid_state, "FIRST_PHASE_TRANSACTION") == 0);
  assert(strcmp(pending.hybrid_reason,
                "application_and_first_consumer_committed") == 0);
  assert(!pending.first_phase_checkpoint_passed);
  assert_common_application_status(pending);

  transaction.state = OtisCx317ActiveState::Disarmed;
  transaction.reason = "healthy_evidence_below_empirical_detection_floor";
  cx323_engine.response_pending = false;
  cx323_engine.last_reason = "response_completed";
  evidence_phase = EvidencePhase::Response;
  evidence_request_sequence = 1u;

  // Response completion precedes the host's phase-4 evidence release.  This
  // is the exact Attempt 8 generation-2056 shape: controller checkpoint is
  // complete while the immutable response evidence remains pending.
  OtisCx317ActiveLiveStatus response_evidence_pending = {};
  otis_cx317_active_live_get_status(&response_evidence_pending, 11111u);
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
  OtisCx317ActiveLiveStatus complete = {};
  otis_cx317_active_live_get_status(&complete, 11112u);
  assert(strcmp(complete.evidence_state, "evidence_clear") == 0);
  assert(!complete.evidence_pending);
  assert(complete.evidence_request_sequence == 0u);
  assert(strcmp(complete.hybrid_state, "HYBRID_TRACKING") == 0);
  assert(complete.first_phase_checkpoint_passed);
  assert_common_application_status(complete);
  assert(!complete.natural_reversal_observed);
  assert(!complete.deliberate_challenge_applied);
  assert(!complete.deliberate_challenge_cancelled);
  assert(complete.deliberate_challenge_unexercised);
  assert(!complete.deliberate_challenge_recovery_applied);
  assert(complete.deliberate_challenge_direction == 0);
  assert(complete.deliberate_challenge_code == 0u);
  assert(complete.deliberate_challenge_dac_epoch == 0u);
  assert(complete.deliberate_challenge_application_ticks == 0u);
  return 0;
}
