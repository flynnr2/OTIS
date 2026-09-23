#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "reference_selection_fixture.h"

#define OTIS_BUILD_IMAGE_ID "adaptive_hybrid_regulation"

// Exercise the production live producer. The stubs below retain the exact
// selected-EST -> CTL boundary presented to the host record consumer.
#include "../../firmware/arduino/otis_nano_rp2040_connect/otis_frequency_regulation_live.cpp"

constexpr size_t kCapturedRecordCapacity = 8u;
OtisEvidenceFrameMessage selected_estimates[kCapturedRecordCapacity] = {};
OtisEvidenceFrameMessage controls[kCapturedRecordCapacity] = {};
size_t selected_estimate_count = 0u;
size_t control_count = 0u;
size_t critical_count = 0u;

bool otis_dual_core_publish_evidence(const OtisEvidenceFrameMessage *message) {
  assert(message != nullptr);
  if (strncmp(message->data, "EST,3,", 6u) == 0 &&
      strstr(message->data,
             ",est:frequency_regulation:pps_gated_frequency:") != nullptr) {
    assert(selected_estimate_count < kCapturedRecordCapacity);
    selected_estimates[selected_estimate_count++] = *message;
    printf("%s", message->data);
  } else if (strncmp(message->data, "CTL,1,", 6u) == 0) {
    assert(control_count < kCapturedRecordCapacity);
    controls[control_count++] = *message;
    printf("%s", message->data);
  }
  return true;
}

bool otis_dual_core_timing_owner_active(void) { return true; }

bool otis_dual_core_publish_critical(const OtisCriticalRecordMessage *message) {
  assert(message != nullptr);
  ++critical_count;
  return true;
}

void otis_dual_core_note_timing_estimate(uint32_t) {}
void otis_dual_core_note_timing_progress(OtisTimingProgressPhase, uint64_t) {}
bool otis_dual_core_publish_phase_preview(const OtisPhasePreviewRecordMessage *) {
  return true;
}
bool otis_dual_core_fail_static(void) { return false; }
void otis_dual_core_latch_fault(OtisPartitionFault) {}
void otis_adaptive_hybrid_regulation_live_on_decision_at_ticks(
    const OtisAdaptiveHybridRegulationLiveDecision *, uint64_t,
    OtisAdaptiveHybridRegulationLiveOutcome *outcome) {
  if (outcome != nullptr) *outcome = {};
}

void start_trace(ReferenceSelectionFixture *trace, uint32_t capture_session,
                 uint64_t opening_ticks,
                 const OtisRegulationStaticCodeState *code) {
  assert(trace != nullptr);
  trace->raw.capture_session = capture_session;
  trace->extended_ticks = opening_ticks;
  trace->raw.reference_timestamp_ticks = uint32_t(opening_ticks);
  trace->acquire();
  assert(trace->selection.disposition ==
         OtisReferenceAcceptanceDisposition::TrackingEstablished);
  OtisAdaptiveHybridRegulationLiveOutcome outcome = {};
  otis_frequency_regulation_live_on_reference_selection(
      &trace->selection, trace->extended_ticks,
      uint32_t(trace->extended_ticks / 1000000ull),
      trace->extended_ticks + 100u, code, &outcome);
}

void advance_and_consume(ReferenceSelectionFixture *trace,
                         const OtisRegulationStaticCodeState *code) {
  assert(trace != nullptr);
  trace->advance();
  assert(trace->selection.disposition ==
         OtisReferenceAcceptanceDisposition::AcceptedSpan);
  OtisAdaptiveHybridRegulationLiveOutcome outcome = {};
  otis_frequency_regulation_live_on_reference_selection(
      &trace->selection, trace->extended_ticks,
      uint32_t(trace->extended_ticks / 1000000ull),
      trace->extended_ticks + 100u, code, &outcome);
}

void produce_selected_decision(ReferenceSelectionFixture *trace,
                               const OtisRegulationStaticCodeState *code,
                               bool verify_warmup_silence) {
  const size_t selected_before = selected_estimate_count;
  const size_t controls_before = control_count;
  const size_t critical_before = critical_count;
  advance_and_consume(trace, code);
  if (verify_warmup_silence) {
    assert(warmup_boundary_seen);
    assert(selected_estimate_count == selected_before);
    assert(control_count == controls_before);
    assert(critical_count == critical_before);
  }
  for (uint32_t index = 1u;
       index < OTIS_FREQUENCY_ESTIMATOR_SPAN_INTERVALS; ++index)
    advance_and_consume(trace, code);
  assert(selected_estimate_count == selected_before + 1u);
  assert(control_count == controls_before + 1u);
}

int main() {
  const OtisRegulationStaticCodeState unknown_code = {};
  const OtisRegulationStaticCodeState valid_code = {
      true, true, true, 0xA844u};
  const OtisRegulationStaticCodeState mismatched_code = {
      true, false, true, 0xA844u};

  // Startup may update the internal preview state, but there is no selected
  // estimator record to bind yet. The first native host-visible decision is
  // emitted only when the selected estimator completes.
  assert(otis_frequency_regulation_live_begin(0u));
  ReferenceSelectionFixture startup;
  start_trace(&startup, 7u, 2000000000ull, &unknown_code);
  produce_selected_decision(&startup, &unknown_code, true);
  assert(controller.state == OtisFrequencyRegulationState::SetupInhibit);

  // An accepted selector outcome can still fail the estimator's exact
  // producer-to-consumer continuity check. Preserve the same internal reset
  // and controller evaluation without publishing an unbacked preview.
  const size_t estimator_gap_selected_before = selected_estimate_count;
  const size_t estimator_gap_controls_before = control_count;
  const size_t estimator_gap_critical_before = critical_count;
  OtisReferenceAcceptanceOutcome estimator_gap = startup.advance();
  assert(estimator_gap.disposition ==
         OtisReferenceAcceptanceDisposition::AcceptedSpan);
  ++estimator_gap.opening.snapshot_sequence;
  OtisAdaptiveHybridRegulationLiveOutcome estimator_gap_outcome = {};
  otis_frequency_regulation_live_on_reference_selection(
      &estimator_gap, startup.extended_ticks,
      uint32_t(startup.extended_ticks / 1000000ull),
      startup.extended_ticks + 100u, &unknown_code,
      &estimator_gap_outcome);
  assert(estimator.selected_count == 0u);
  assert(!selected_estimator_valid && !selected_model_applicable);
  assert(controller.state == OtisFrequencyRegulationState::SetupInhibit);
  assert(selected_estimate_count == estimator_gap_selected_before);
  assert(control_count == estimator_gap_controls_before);
  assert(critical_count == estimator_gap_critical_before);

  // A selector discontinuity with unknown actuator provenance still resets the
  // estimator and evaluates the controller. It produces neither an orphan CTL
  // nor a preview-only critical transition.
  const size_t discontinuity_selected_before = selected_estimate_count;
  const size_t discontinuity_controls_before = control_count;
  const size_t discontinuity_critical_before = critical_count;
  startup.selection = startup.selector.invalidate(
      OtisReferenceAcceptanceReason::CaptureIntegrity);
  OtisAdaptiveHybridRegulationLiveOutcome outcome = {};
  otis_frequency_regulation_live_on_reference_selection(
      &startup.selection, startup.extended_ticks,
      uint32_t(startup.extended_ticks / 1000000ull),
      startup.extended_ticks + 100u, &unknown_code, &outcome);
  assert(estimator.selected_count == 0u);
  assert(!selected_estimator_valid && !selected_model_applicable);
  assert(controller.state == OtisFrequencyRegulationState::SetupInhibit);
  assert(strcmp(controller.reason,
                "static_dac_code_unavailable_no_control_authority") == 0);
  assert(selected_estimate_count == discontinuity_selected_before);
  assert(control_count == discontinuity_controls_before);
  assert(critical_count == discontinuity_critical_before);

  // Fresh support in a new capture/acceptance epoch recovers ordinary
  // selected-EST -> CTL publication without inventing a record at the gap.
  ReferenceSelectionFixture unknown_recovery;
  start_trace(&unknown_recovery, 8u, 2700000000ull, &unknown_code);
  produce_selected_decision(&unknown_recovery, &unknown_code, false);

  // With established, valid DAC/model provenance, capture invalidation remains
  // a recoverable controller qualification transition. The same state effects
  // occur without publishing a CTL that lacks selected-estimator provenance.
  assert(otis_frequency_regulation_live_begin(0u));
  current_dac_epoch = 1u;
  current_applied_code = valid_code.applied_code;
  warmup_boundary_seen = true;
  settling_until_s = 0u;
  exact_settling_deadline_available = false;
  controller.state = OtisFrequencyRegulationState::Tracking;
  controller.reason = "preview_available";
  ReferenceSelectionFixture established;
  start_trace(&established, 9u, 2000000000ull, &valid_code);
  produce_selected_decision(&established, &valid_code, false);

  const size_t fault_selected_before = selected_estimate_count;
  const size_t fault_controls_before = control_count;
  const size_t fault_critical_before = critical_count;
  otis_frequency_regulation_live_on_capture_fault(
      "synthetic_capture_fault", 2608u, &valid_code);
  assert(estimator.selected_count == 0u);
  assert(!selected_estimator_valid && !selected_model_applicable);
  assert(controller.state == OtisFrequencyRegulationState::Qualifying);
  assert(strcmp(controller.reason, "reference_invalid") == 0);
  assert(!controller.tight_deadband_decision_available);
  assert(selected_estimate_count == fault_selected_before);
  assert(control_count == fault_controls_before);
  assert(critical_count == fault_critical_before);

  ReferenceSelectionFixture valid_recovery;
  start_trace(&valid_recovery, 10u, 2700000000ull, &valid_code);
  produce_selected_decision(&valid_recovery, &valid_code, false);

  // Invalid established actuator provenance still latches the same internal
  // controller fault while remaining absent from CTL: no selected EST exists
  // to support a host-visible preview decision at this instant.
  const size_t invalid_selected_before = selected_estimate_count;
  const size_t invalid_controls_before = control_count;
  const size_t invalid_critical_before = critical_count;
  otis_frequency_regulation_live_on_capture_fault(
      "synthetic_capture_fault", 3400u, &mismatched_code);
  assert(controller.state == OtisFrequencyRegulationState::Fault);
  assert(strcmp(controller.reason, "requested_applied_mismatch") == 0);
  assert(estimator.selected_count == 0u);
  assert(!selected_estimator_valid && !selected_model_applicable);
  assert(selected_estimate_count == invalid_selected_before);
  assert(control_count == invalid_controls_before);
  assert(critical_count == invalid_critical_before);
  return 0;
}
