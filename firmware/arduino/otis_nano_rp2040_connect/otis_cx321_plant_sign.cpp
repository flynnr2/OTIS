#include "otis_cx321_plant_sign.h"

#include <limits.h>
#include <stddef.h>
#include <string.h>

namespace {

constexpr uint16_t kSetupCode = 0xA83Cu;
constexpr uint16_t kMinimumCode = 0xA800u;
constexpr uint16_t kMaximumCode = 0xAB00u;
constexpr int32_t kIdentificationStepCodes = 21;
constexpr uint64_t kResponseAcknowledgementLimitTicks =
    30ull * OTIS_CX321_TIMER0_TICKS_PER_SECOND;

void clear_partial(OtisCx321PlantSignAccumulator *accumulator) {
  accumulator->total_count = 0u;
  accumulator->open_ticks = 0u;
  accumulator->close_ticks = 0u;
  accumulator->first_sequence = 0u;
  accumulator->last_sequence = 0u;
  accumulator->accepted_intervals = 0u;
}

void fail(OtisCx321PlantSignEngine *engine, const char *reason) {
  engine->state = OtisCx321PlantSignState::FailStatic;
  engine->reason = reason;
  engine->attested = false;
}

uint64_t absolute_i64(int64_t value) {
  return value < 0 ? static_cast<uint64_t>(-(value + 1)) + 1u
                   : static_cast<uint64_t>(value);
}

bool estimate_is_exact(const OtisCx321PlantSignEstimate &estimate) {
  constexpr uint64_t kNominalTotal =
      static_cast<uint64_t>(OTIS_CX321_PLANT_SIGN_SPAN_INTERVALS) *
      OTIS_CX321_NOMINAL_COUNT_PER_INTERVAL;
  return estimate.valid &&
         estimate.accepted_intervals == OTIS_CX321_PLANT_SIGN_SPAN_INTERVALS &&
         estimate.last_sequence >= estimate.first_sequence &&
         estimate.last_sequence - estimate.first_sequence ==
             OTIS_CX321_PLANT_SIGN_SPAN_INTERVALS &&
         estimate.close_ticks > estimate.open_ticks &&
         estimate.total_count <= static_cast<uint64_t>(INT64_MAX) &&
         static_cast<int64_t>(estimate.total_count) -
                 static_cast<int64_t>(kNominalTotal) ==
             estimate.signed_error_counts;
}

}  // namespace

void otis_cx321_plant_sign_accumulator_init(
    OtisCx321PlantSignAccumulator *accumulator, uint64_t application_ticks,
    uint32_t dac_epoch, uint32_t capture_session) {
  if (accumulator == nullptr) return;
  *accumulator = {};
  accumulator->application_ticks = application_ticks;
  accumulator->dac_epoch = dac_epoch;
  accumulator->capture_session = capture_session;
  accumulator->configured =
      application_ticks > 0u &&
      application_ticks <= UINT64_MAX - OTIS_CX321_SETTLING_EXCLUSION_TICKS &&
      dac_epoch > 0u && capture_session > 0u;
}

void otis_cx321_plant_sign_accumulator_invalidate(
    OtisCx321PlantSignAccumulator *accumulator) {
  if (accumulator == nullptr) return;
  clear_partial(accumulator);
}

bool otis_cx321_plant_sign_accumulator_on_interval(
    OtisCx321PlantSignAccumulator *accumulator, uint64_t open_ticks,
    uint64_t close_ticks, uint32_t closing_sequence, uint32_t interval_count,
    uint32_t dac_epoch, uint32_t capture_session, bool interval_valid,
    OtisCx321PlantSignEstimate *estimate) {
  if (estimate != nullptr) *estimate = {};
  if (accumulator == nullptr || estimate == nullptr ||
      !accumulator->configured)
    return false;
  const uint64_t deadline =
      accumulator->application_ticks + OTIS_CX321_SETTLING_EXCLUSION_TICKS;
  if (dac_epoch != accumulator->dac_epoch ||
      capture_session != accumulator->capture_session || !interval_valid ||
      closing_sequence == 0u || interval_count == 0u ||
      close_ticks <= open_ticks) {
    clear_partial(accumulator);
    return false;
  }
  if (open_ticks < deadline) {
    clear_partial(accumulator);
    return false;
  }
  if (accumulator->accepted_intervals > 0u &&
      (closing_sequence != accumulator->last_sequence + 1u ||
       open_ticks != accumulator->close_ticks)) {
    clear_partial(accumulator);
    return false;
  }
  if (accumulator->accepted_intervals == 0u) {
    accumulator->open_ticks = open_ticks;
    // Evidence names the two boundary sequences that enclose the 1,500
    // accepted intervals, so last - first is exactly 1,500.
    accumulator->first_sequence = closing_sequence - 1u;
  }
  accumulator->total_count += interval_count;
  accumulator->close_ticks = close_ticks;
  accumulator->last_sequence = closing_sequence;
  accumulator->accepted_intervals++;
  if (accumulator->accepted_intervals !=
      OTIS_CX321_PLANT_SIGN_SPAN_INTERVALS)
    return false;

  estimate->total_count = accumulator->total_count;
  estimate->signed_error_counts =
      static_cast<int64_t>(accumulator->total_count) -
      static_cast<int64_t>(OTIS_CX321_PLANT_SIGN_SPAN_INTERVALS) *
          static_cast<int64_t>(OTIS_CX321_NOMINAL_COUNT_PER_INTERVAL);
  estimate->open_ticks = accumulator->open_ticks;
  estimate->close_ticks = accumulator->close_ticks;
  estimate->first_sequence = accumulator->first_sequence;
  estimate->last_sequence = accumulator->last_sequence;
  estimate->capture_session = accumulator->capture_session;
  estimate->dac_epoch = accumulator->dac_epoch;
  estimate->accepted_intervals = accumulator->accepted_intervals;
  estimate->valid = true;
  clear_partial(accumulator);
  return true;
}

void otis_cx321_plant_sign_engine_init(OtisCx321PlantSignEngine *engine) {
  if (engine == nullptr) return;
  *engine = {};
  engine->state = OtisCx321PlantSignState::FrequencyAcquire;
  engine->reason = "awaiting_two_exact_pre_identification_windows";
}

bool otis_cx321_plant_sign_engine_on_pre_estimate(
    OtisCx321PlantSignEngine *engine,
    const OtisCx321PlantSignEstimate *estimate, uint16_t current_code,
    uint32_t current_dac_epoch, uint16_t global_correction_count,
    bool natural_tight_inside, bool common_evidence_exact,
    OtisCx321PlantSignDecision *decision) {
  if (decision != nullptr) *decision = {};
  if (engine == nullptr || estimate == nullptr || decision == nullptr ||
      engine->state != OtisCx321PlantSignState::FrequencyAcquire ||
      engine->pre_window_count >= 2u)
    return false;
  const uint64_t error = absolute_i64(estimate->signed_error_counts);
  const bool identity_exact =
      estimate_is_exact(*estimate) &&
      current_code == kSetupCode && current_dac_epoch == 1u &&
      estimate->dac_epoch == current_dac_epoch &&
      estimate->capture_session > 0u && global_correction_count == 0u &&
      common_evidence_exact;
  if (!identity_exact) {
    fail(engine, "pre_identification_evidence_or_authority_inexact");
    return false;
  }
  if (engine->pre_window_count == 1u) {
    const OtisCx321PlantSignEstimate &first = engine->pre_windows[0];
    if (estimate->capture_session != first.capture_session ||
        estimate->dac_epoch != first.dac_epoch) {
      fail(engine, "pre_identification_identity_changed");
      return false;
    }
    if (estimate->first_sequence != first.last_sequence ||
        estimate->open_ticks != first.close_ticks) {
      fail(engine, "second_pre_window_capture_continuity_inexact");
      return false;
    }
  }
  if (error < 1u || error > 5u) {
    engine->state = OtisCx321PlantSignState::NotExercised;
    engine->reason = "pre_identification_scientific_entry_band_not_satisfied";
    return false;
  }
  if (engine->pre_window_count == 1u) {
    const OtisCx321PlantSignEstimate &first = engine->pre_windows[0];
    if (estimate->total_count != first.total_count || !natural_tight_inside) {
      engine->state = OtisCx321PlantSignState::NotExercised;
      engine->reason = "second_pre_window_not_equal_and_tight";
      return false;
    }
  }
  engine->pre_windows[engine->pre_window_count++] = *estimate;
  if (engine->pre_window_count != 2u) {
    engine->reason = "first_pre_identification_window_accepted";
    return false;
  }
  const int32_t delta = estimate->signed_error_counts > 0
                            ? -kIdentificationStepCodes
                            : kIdentificationStepCodes;
  const int32_t code = static_cast<int32_t>(current_code) + delta;
  if (code < kMinimumCode || code > kMaximumCode) {
    fail(engine, "identification_request_outside_frozen_range");
    return false;
  }
  *decision = {
      ++engine->decision_sequence,
      estimate->signed_error_counts,
      delta,
      current_code,
      static_cast<uint16_t>(code),
      estimate->first_sequence,
      estimate->last_sequence,
      current_dac_epoch,
      true,
  };
  engine->pending_decision = *decision;
  engine->state = OtisCx321PlantSignState::PlantSignQualify;
  engine->reason = "identification_request_ready";
  return true;
}

bool otis_cx321_plant_sign_engine_note_application(
    OtisCx321PlantSignEngine *engine, uint32_t request_sequence,
    uint32_t application_sequence, uint16_t applied_code,
    uint32_t applied_dac_epoch, uint64_t application_ticks,
    bool application_identity_exact) {
  if (engine == nullptr ||
      engine->state != OtisCx321PlantSignState::PlantSignQualify ||
      !engine->pending_decision.request_ready || request_sequence == 0u ||
      application_sequence != 1u || application_ticks == 0u ||
      applied_code != engine->pending_decision.requested_code ||
      applied_dac_epoch != engine->pending_decision.dac_epoch + 1u ||
      !application_identity_exact) {
    if (engine != nullptr) fail(engine, "identification_application_inexact");
    return false;
  }
  engine->request_sequence = request_sequence;
  engine->application_sequence = application_sequence;
  engine->applied_code = applied_code;
  engine->applied_dac_epoch = applied_dac_epoch;
  engine->capture_session = engine->pre_windows[1].capture_session;
  engine->application_ticks = application_ticks;
  engine->reason = "identification_applied_response_pending";
  return true;
}

bool otis_cx321_plant_sign_engine_on_response(
    OtisCx321PlantSignEngine *engine,
    const OtisCx321PlantSignEstimate *post_estimate,
    bool common_evidence_exact, bool tight_reentry,
    OtisCx321PlantSignResponse *response) {
  if (response != nullptr) *response = {};
  if (engine == nullptr || post_estimate == nullptr || response == nullptr ||
      engine->state != OtisCx321PlantSignState::PlantSignQualify ||
      engine->application_ticks == 0u || engine->pre_window_count != 2u)
    return false;
  const int64_t pre =
      static_cast<int64_t>(engine->pre_windows[1].total_count);
  const int64_t post = static_cast<int64_t>(post_estimate->total_count);
  const int64_t delta = post - pre;
  const uint64_t magnitude = absolute_i64(delta);
  response->request_sequence = engine->request_sequence;
  response->application_sequence = engine->application_sequence;
  response->dac_epoch = engine->applied_dac_epoch;
  response->source_last_sequence = post_estimate->last_sequence;
  response->response_close_ticks = post_estimate->close_ticks;
  response->pre_total_count = pre;
  response->post_total_count = post;
  response->response_counts = delta;
  response->sign_pass =
      delta * engine->pending_decision.requested_delta_codes > 0;
  response->magnitude_pass = magnitude >= 3u && magnitude <= 14u;
  response->exact_evidence_pass =
      common_evidence_exact && estimate_is_exact(*post_estimate) &&
      post_estimate->dac_epoch == engine->applied_dac_epoch &&
      post_estimate->capture_session == engine->capture_session &&
      post_estimate->open_ticks >=
          engine->application_ticks + OTIS_CX321_SETTLING_EXCLUSION_TICKS;
  response->tight_reentry_pass = tight_reentry;
  response->passed = response->sign_pass && response->magnitude_pass &&
                     response->exact_evidence_pass &&
                     response->tight_reentry_pass;
  engine->pending_response = *response;
  if (!response->exact_evidence_pass) {
    fail(engine, "identification_response_evidence_inexact");
    return false;
  }
  if (!response->passed) {
    fail(engine, "identification_response_failed");
    return false;
  }
  engine->state = OtisCx321PlantSignState::ResponseAckPending;
  engine->reason = "identification_response_exact_ack_pending";
  return true;
}

bool otis_cx321_plant_sign_engine_acknowledge_response(
    OtisCx321PlantSignEngine *engine, uint32_t request_sequence,
    uint32_t application_sequence, uint32_t dac_epoch,
    uint32_t response_source_last_sequence, int64_t response_counts,
    uint64_t response_acknowledgement_ticks, bool host_replay_exact) {
  if (engine == nullptr ||
      engine->state != OtisCx321PlantSignState::ResponseAckPending ||
      !engine->pending_response.passed || !host_replay_exact ||
      request_sequence != engine->pending_response.request_sequence ||
      application_sequence != engine->pending_response.application_sequence ||
      dac_epoch != engine->pending_response.dac_epoch ||
      response_source_last_sequence !=
          engine->pending_response.source_last_sequence ||
      response_counts != engine->pending_response.response_counts ||
      response_acknowledgement_ticks == 0u) {
    if (engine != nullptr) fail(engine, "identification_response_ack_inexact");
    return false;
  }
  if (response_acknowledgement_ticks <
          engine->pending_response.response_close_ticks ||
      response_acknowledgement_ticks -
              engine->pending_response.response_close_ticks >
          kResponseAcknowledgementLimitTicks) {
    fail(engine, "identification_response_ack_late");
    return false;
  }
  engine->response_acknowledgement_ticks = response_acknowledgement_ticks;
  engine->attested = true;
  engine->state = OtisCx321PlantSignState::PhaseQualify;
  engine->reason = "identification_response_acknowledged";
  return true;
}

bool otis_cx321_plant_sign_engine_rebase_natural_controller(
    const OtisCx321PlantSignEngine *plant_sign,
    OtisActiveHybridEngine *natural_controller) {
  if (plant_sign == nullptr || natural_controller == nullptr ||
      plant_sign->state != OtisCx321PlantSignState::PhaseQualify ||
      !plant_sign->attested)
    return false;
  return otis_active_hybrid_engine_rebase_after_plant_sign(
      natural_controller, plant_sign->applied_code,
      plant_sign->applied_dac_epoch, 1u, 21u,
      plant_sign->application_ticks,
      plant_sign->response_acknowledgement_ticks);
}

const char *otis_cx321_plant_sign_state_name(OtisCx321PlantSignState state) {
  switch (state) {
    case OtisCx321PlantSignState::FrequencyAcquire:
      return "FREQUENCY_ACQUIRE";
    case OtisCx321PlantSignState::PlantSignQualify:
      return "PLANT_SIGN_QUALIFY";
    case OtisCx321PlantSignState::ResponseAckPending:
      return "PLANT_SIGN_RESPONSE_ACK_PENDING";
    case OtisCx321PlantSignState::PhaseQualify:
      return "PHASE_QUALIFY";
    case OtisCx321PlantSignState::NotExercised:
      return "PLANT_SIGN_NOT_EXERCISED";
    case OtisCx321PlantSignState::FailStatic:
      return "FAIL_STATIC";
  }
  return "FAIL_STATIC";
}
