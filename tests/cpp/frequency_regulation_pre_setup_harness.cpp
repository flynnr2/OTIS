#include <assert.h>
#include <string.h>

#define OTIS_BUILD_IMAGE_ID "adaptive_hybrid_regulation"

// Include the production live adapter so this harness exercises the exact
// static-code-to-controller-input boundary. Dead-section elimination removes
// unrelated hardware and transport paths.
#include "../../firmware/arduino/otis_nano_rp2040_connect/otis_frequency_regulation_live.cpp"

OtisEvidenceFrameMessage captured_control = {};
OtisAdaptiveHybridRegulationLiveDecision captured_active_decision = {};
uint64_t captured_active_decision_ticks = 0u;
uint32_t captured_active_decision_count = 0u;

bool otis_dual_core_publish_evidence(const OtisEvidenceFrameMessage *message) {
  if (message == nullptr) return false;
  captured_control = *message;
  return true;
}

bool otis_dual_core_timing_owner_active(void) { return false; }

bool otis_dual_core_publish_critical(const OtisCriticalRecordMessage *) {
  return false;
}

void otis_dual_core_note_timing_estimate(uint32_t) {}

void otis_dual_core_note_timing_progress(OtisTimingProgressPhase, uint64_t) {}

bool otis_phase_preview_live_get_active_snapshot(
    OtisPhasePreviewActiveSnapshot *snapshot) {
  if (snapshot != nullptr) *snapshot = {};
  return false;
}

void otis_adaptive_hybrid_regulation_live_on_decision_at_ticks(
    const OtisAdaptiveHybridRegulationLiveDecision *decision,
    uint64_t decision_timestamp_ticks,
    OtisAdaptiveHybridRegulationLiveOutcome *outcome) {
  assert(decision != nullptr);
  captured_active_decision = *decision;
  captured_active_decision_ticks = decision_timestamp_ticks;
  captured_active_decision_count++;
  if (outcome != nullptr) *outcome = {};
}

int main() {
  OtisFrequencyRegulationEngine engine = {};
  otis_frequency_regulation_engine_init(&engine, 0u);

  const OtisRegulationStaticCodeState no_setup_code = {};
  const OtisFrequencyRegulationInput no_setup_input = controller_input(
      2400u, 0.01, true, true, true, true, &no_setup_code);
  assert(!no_setup_input.actuator_context_established);
  assert(!no_setup_input.applied_code_available);
  assert(!no_setup_input.model_applicable);
  OtisFrequencyRegulationDecision no_setup_decision = {};
  otis_frequency_regulation_engine_evaluate(
      &engine, &no_setup_input, &no_setup_decision);
  assert(no_setup_decision.state ==
         OtisFrequencyRegulationState::SetupInhibit);
  assert(strcmp(otis_regulation_preview_state_name(no_setup_decision.state),
                "SAFE_OBSERVE") == 0);
  assert(strcmp(no_setup_decision.reason,
                "static_dac_code_unavailable_no_control_authority") == 0);
  assert(!no_setup_decision.preview_available);
  assert(!no_setup_decision.control_ready);
  assert(!no_setup_decision.actuation_enabled);
  assert(!no_setup_decision.actuation_authorized);
  assert(!no_setup_decision.actionable);
  emit_control(no_setup_decision, &no_setup_code, 2400000000ull, 1u);
  assert(captured_control.length == strlen(captured_control.data));
  printf("%s", captured_control.data);

  OtisFrequencyRegulationDecision repeated_no_setup_decision = {};
  otis_frequency_regulation_engine_evaluate(
      &engine, &no_setup_input, &repeated_no_setup_decision);
  assert(repeated_no_setup_decision.state ==
         OtisFrequencyRegulationState::SetupInhibit);
  assert(!repeated_no_setup_decision.state_transition);
  emit_control(
      repeated_no_setup_decision, &no_setup_code, 2401000000ull, 2u);
  assert(captured_control.length == strlen(captured_control.data));
  printf("%s", captured_control.data);

  // A code without an exact applied epoch is contradictory, not authority.
  const OtisRegulationStaticCodeState unbound_code = {
      true, true, true, 0xA900u};
  const OtisFrequencyRegulationInput unbound_input = controller_input(
      2400u, 0.01, true, true, true, true, &unbound_code);
  OtisFrequencyRegulationDecision unbound_decision = {};
  otis_frequency_regulation_engine_init(&engine, 0u);
  otis_frequency_regulation_engine_evaluate(
      &engine, &unbound_input, &unbound_decision);
  assert(unbound_decision.state == OtisFrequencyRegulationState::Fault);
  assert(strcmp(unbound_decision.reason,
                "pre_setup_static_code_context_inconsistent") == 0);

  // Once an exact actuator context exists, contradictory or missing static
  // state remains a genuine fault; the pre-setup exemption cannot mask it.
  current_dac_epoch = 1u;
  const OtisFrequencyRegulationInput missing_input = controller_input(
      2400u, 0.01, true, true, true, true, &no_setup_code);
  assert(missing_input.actuator_context_established);
  OtisFrequencyRegulationDecision missing_decision = {};
  otis_frequency_regulation_engine_init(&engine, 0u);
  otis_frequency_regulation_engine_evaluate(
      &engine, &missing_input, &missing_decision);
  assert(missing_decision.state == OtisFrequencyRegulationState::Fault);
  assert(strcmp(missing_decision.reason, "static_dac_code_unavailable") == 0);

  // A latched genuine fault cannot be demoted by later unestablished input.
  current_dac_epoch = 0u;
  OtisFrequencyRegulationDecision latched_fault = {};
  otis_frequency_regulation_engine_evaluate(
      &engine, &no_setup_input, &latched_fault);
  assert(latched_fault.state == OtisFrequencyRegulationState::Fault);
  assert(strcmp(latched_fault.reason, "static_dac_code_unavailable") == 0);

  current_dac_epoch = 1u;
  const OtisRegulationStaticCodeState mismatched_code = {
      true, false, true, 0xA900u};
  const OtisFrequencyRegulationInput mismatch_input = controller_input(
      2400u, 0.01, true, true, true, true, &mismatched_code);
  assert(mismatch_input.actuator_context_established);
  OtisFrequencyRegulationDecision mismatch_decision = {};
  otis_frequency_regulation_engine_init(&engine, 0u);
  otis_frequency_regulation_engine_evaluate(
      &engine, &mismatch_input, &mismatch_decision);
  assert(mismatch_decision.state == OtisFrequencyRegulationState::Fault);
  assert(strcmp(mismatch_decision.reason, "requested_applied_mismatch") == 0);

  // Regression for the attempt-3 firmware fault: the selected D14 boundary
  // occurred 122 us before the next whole second, while foreground uptime had
  // already advanced.  The active decision must project seconds from the same
  // extended capture timestamp supplied to its exact-domain consumer.
  assert(otis_frequency_regulation_live_begin(0u));
  current_dac_epoch = 5u;
  current_applied_code = 0xA844u;
  warmup_boundary_seen = true;
  settling_until_s = 0u;
  exact_settling_deadline_available = false;
  constexpr uint64_t kFaultBoundaryTicks = 58841999878ull;
  constexpr uint64_t kPriorBoundaryTicks = kFaultBoundaryTicks - 1000000ull;
  assert(otis_monotonic_us_extension_seed(
      &timer_extension, kPriorBoundaryTicks, 1u));
  previous_boundary_available = true;
  previous_boundary_session = 1u;
  previous_boundary_extended_ticks = kPriorBoundaryTicks;
  estimator.selected_count = OTIS_FREQUENCY_ESTIMATOR_SPAN_INTERVALS - 1u;
  estimator.selected_sum =
      static_cast<uint64_t>(OTIS_FREQUENCY_ESTIMATOR_SPAN_INTERVALS - 1u) *
      10000000ull;
  estimator.selected_first_sequence = 58240u;
  const OtisPpsCountBoundaryObservation fault_boundary = {
      1u,
      58840u,
      59840u,
      kFaultBoundaryTicks % OTIS_RP2040_MONOTONIC_US32_MODULUS,
      0u,
      10000000u,
      0u,
      0u,
  };
  const OtisRegulationStaticCodeState exact_code = {
      true, true, true, 0xA844u};
  OtisAdaptiveHybridRegulationLiveOutcome active_outcome = {};
  otis_frequency_regulation_live_on_boundary(
      &fault_boundary, 10000000u, true,
      // Deliberately one second later than the captured boundary projection.
      58842u, &exact_code, &active_outcome);
  assert(captured_active_decision_count == 1u);
  assert(captured_active_decision_ticks == kFaultBoundaryTicks);
  assert(captured_active_decision.timestamp_s == 58841u);
  assert(captured_active_decision.timestamp_s ==
         captured_active_decision_ticks / 1000000ull);
  return 0;
}
