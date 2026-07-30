#include "otis_phase4_engine.h"

#include <math.h>
#include <string.h>

namespace {

bool qualified_state(OtisPhase4State state) {
  return state == OTIS_PHASE4_ACQUIRE_PREVIEW ||
         state == OTIS_PHASE4_SETTLE_PREVIEW ||
         state == OTIS_PHASE4_LOCKED_PREVIEW ||
         state == OTIS_PHASE4_HOLDOVER_PREVIEW ||
         state == OTIS_PHASE4_RECOVER_PREVIEW;
}

int32_t round_half_away_from_zero(double value) {
  return value >= 0.0 ? (int32_t)floor(value + 0.5)
                      : (int32_t)ceil(value - 0.5);
}

uint32_t model_reasons(const OtisPhase4ModelInput &model) {
  uint32_t reasons = OTIS_PHASE4_REASON_NONE;
  if (!model.available) {
    return OTIS_PHASE4_REASON_MODEL_UNAVAILABLE;
  }
  if (!model.valid) reasons |= OTIS_PHASE4_REASON_MODEL_INVALID;
  if (!model.version_4) reasons |= OTIS_PHASE4_REASON_MODEL_VERSION;
  if (!model.topology_match) reasons |= OTIS_PHASE4_REASON_MODEL_TOPOLOGY;
  if (!model.backend_match) reasons |= OTIS_PHASE4_REASON_MODEL_BACKEND;
  if (!model.estimator_method_match)
    reasons |= OTIS_PHASE4_REASON_MODEL_ESTIMATOR_METHOD;
  if (!model.input_in_applicability)
    reasons |= OTIS_PHASE4_REASON_MODEL_INPUT_RANGE;
  if (model.excluded_input)
    reasons |= OTIS_PHASE4_REASON_MODEL_EXCLUDED_INPUT;
  if (!model.gain_available || !isfinite(model.hz_per_code) ||
      model.hz_per_code == 0.0)
    reasons |= OTIS_PHASE4_REASON_MODEL_GAIN;
  if (!model.dac_available) reasons |= OTIS_PHASE4_REASON_DAC_UNAVAILABLE;
  return reasons;
}

}  // namespace

void otis_phase4_engine_init(OtisPhase4Engine *engine,
                             const OtisPhase4EngineConfig *config) {
  memset(engine, 0, sizeof(*engine));
  engine->config = *config;
  engine->state = OTIS_PHASE4_BOOT;
}

void otis_phase4_engine_evaluate(OtisPhase4Engine *engine,
                                 const OtisPhase4Observation *observation,
                                 OtisPhase4Decision *decision) {
  memset(decision, 0, sizeof(*decision));
  decision->previous_state = engine->state;
  decision->preview_only = true;
  decision->actuation_authorized = false;
  decision->actionable = false;

  const bool observation_valid =
      observation->reference_validity == OTIS_PHASE4_VALID &&
      observation->count_validity == OTIS_PHASE4_VALID &&
      observation->diagnostic_health != OTIS_PHASE4_DIAGNOSTIC_FAULT &&
      observation->reference_continuity && observation->count_continuity &&
      (!observation->new_count ||
       observation->frequency_observation_available);
  if (observation->new_count && observation_valid &&
      observation->frequency_observation_available &&
      isfinite(observation->frequency_observation_hz)) {
    engine->samples[engine->sample_next] =
        observation->frequency_observation_hz;
    engine->sample_next =
        (uint8_t)((engine->sample_next + 1u) % engine->config.estimator_window);
    if (engine->sample_count < engine->config.estimator_window)
      engine->sample_count++;
  }

  double mean = 0.0;
  for (uint8_t i = 0; i < engine->sample_count; ++i)
    mean += engine->samples[i];
  if (engine->sample_count > 0u) mean /= engine->sample_count;
  double variance = 0.0;
  for (uint8_t i = 0; i < engine->sample_count; ++i) {
    const double delta = engine->samples[i] - mean;
    variance += delta * delta;
  }
  if (engine->sample_count > 0u) variance /= engine->sample_count;
  const double dispersion =
      engine->sample_count > 0u ? sqrt(variance) : 0.0;

  decision->accepted_sample_count = engine->sample_count;
  decision->estimate_available = engine->sample_count > 0u;
  decision->frequency_estimate_hz = mean;
  decision->frequency_error_hz = mean - engine->config.nominal_frequency_hz;
  decision->dispersion_hz = dispersion;

  uint32_t eligibility_reasons = observation->observation_reason_mask;
  if (engine->sample_count < engine->config.minimum_estimator_samples)
    eligibility_reasons |= OTIS_PHASE4_REASON_ESTIMATOR_UNDERQUALIFIED;
  if (engine->sample_count > 0u &&
      dispersion > engine->config.maximum_dispersion_hz)
    eligibility_reasons |= OTIS_PHASE4_REASON_ESTIMATOR_DISPERSION;

  if (engine->sample_count == 0u) {
    decision->confidence = OTIS_PHASE4_CONFIDENCE_UNAVAILABLE;
  } else if (engine->sample_count < engine->config.minimum_estimator_samples ||
             dispersion > engine->config.maximum_dispersion_hz) {
    decision->confidence = OTIS_PHASE4_CONFIDENCE_LOW;
  } else if (!observation_valid) {
    decision->confidence = OTIS_PHASE4_CONFIDENCE_MEDIUM;
  } else {
    decision->confidence = OTIS_PHASE4_CONFIDENCE_HIGH;
  }

  if (observation->elapsed_s < engine->config.startup_inhibit_s) {
    engine->clean_windows = 0u;
  } else if (observation->new_count) {
    if (!observation_valid) {
      engine->clean_windows = 0u;
    } else if (engine->clean_windows < UINT8_MAX) {
      engine->clean_windows++;
    }
  }
  if (engine->state == OTIS_PHASE4_HOLDOVER_PREVIEW ||
      engine->state == OTIS_PHASE4_RECOVER_PREVIEW) {
    if (!observation->new_count || !observation_valid) {
      engine->recovery_windows = 0u;
    } else if (engine->recovery_windows < UINT8_MAX) {
      engine->recovery_windows++;
    }
  } else {
    engine->recovery_windows = 0u;
  }

  OtisPhase4State next = engine->state;
  OtisPhase4TransitionReason transition = OTIS_PHASE4_TRANSITION_QUALIFYING;
  if (engine->fault_latched) {
    next = OTIS_PHASE4_FAULT;
    transition = OTIS_PHASE4_TRANSITION_FAULT_LATCHED;
  } else if (observation->elapsed_s < engine->config.startup_inhibit_s) {
    next = OTIS_PHASE4_WARMUP_INHIBIT;
    transition = OTIS_PHASE4_TRANSITION_STARTUP_INHIBIT;
  } else if (qualified_state(engine->state) &&
             observation->count_validity != OTIS_PHASE4_VALID) {
    next = OTIS_PHASE4_FAULT;
    transition = OTIS_PHASE4_TRANSITION_POST_QUALIFICATION_FAULT;
    engine->fault_latched = true;
  } else if (qualified_state(engine->state) &&
             observation->reference_validity != OTIS_PHASE4_VALID) {
    next = OTIS_PHASE4_HOLDOVER_PREVIEW;
    transition = OTIS_PHASE4_TRANSITION_REFERENCE_HOLDOVER;
  } else if (engine->state == OTIS_PHASE4_HOLDOVER_PREVIEW &&
             observation_valid) {
    next = OTIS_PHASE4_RECOVER_PREVIEW;
    transition = OTIS_PHASE4_TRANSITION_REFERENCE_RETURN;
  } else if (engine->state == OTIS_PHASE4_RECOVER_PREVIEW) {
    if (!observation_valid) {
      next = OTIS_PHASE4_HOLDOVER_PREVIEW;
      transition = OTIS_PHASE4_TRANSITION_RECOVERY_INTERRUPTED;
    } else if (engine->recovery_windows <
               engine->config.recovery_clean_window_requirement) {
      next = OTIS_PHASE4_RECOVER_PREVIEW;
      transition = OTIS_PHASE4_TRANSITION_RECOVERY_QUALIFYING;
    } else {
      next = OTIS_PHASE4_ACQUIRE_PREVIEW;
      transition = OTIS_PHASE4_TRANSITION_RECOVERY_QUALIFIED;
    }
  } else if (!observation_valid ||
             engine->clean_windows < engine->config.clean_window_requirement ||
             decision->confidence != OTIS_PHASE4_CONFIDENCE_HIGH) {
    next = OTIS_PHASE4_QUALIFYING;
    transition = OTIS_PHASE4_TRANSITION_QUALIFYING;
  } else {
    next = OTIS_PHASE4_ACQUIRE_PREVIEW;
    transition = OTIS_PHASE4_TRANSITION_STARTUP_QUALIFIED;
  }
  engine->state = next;
  decision->state = next;
  decision->transition_reason = transition;
  decision->state_transition = next != decision->previous_state;

  if (next == OTIS_PHASE4_WARMUP_INHIBIT)
    eligibility_reasons |= OTIS_PHASE4_REASON_STARTUP_INHIBIT;
  if (next == OTIS_PHASE4_QUALIFYING ||
      next == OTIS_PHASE4_RECOVER_PREVIEW)
    eligibility_reasons |= OTIS_PHASE4_REASON_CLEAN_WINDOW_INCOMPLETE;
  if (next == OTIS_PHASE4_HOLDOVER_PREVIEW)
    eligibility_reasons |= OTIS_PHASE4_REASON_REFERENCE_HOLDOVER;
  if (next == OTIS_PHASE4_FAULT)
    eligibility_reasons |= OTIS_PHASE4_REASON_POST_QUALIFICATION_FAULT;
  if (observation->diagnostic_health != OTIS_PHASE4_DIAGNOSTIC_HEALTHY)
    eligibility_reasons |= OTIS_PHASE4_REASON_DIAGNOSTIC_NOT_HEALTHY;

  decision->estimator_eligible =
      observation_valid &&
      observation->reference_authority_qualified &&
      decision->confidence == OTIS_PHASE4_CONFIDENCE_HIGH &&
      observation->diagnostic_health == OTIS_PHASE4_DIAGNOSTIC_HEALTHY &&
      next == OTIS_PHASE4_ACQUIRE_PREVIEW &&
      !(eligibility_reasons &
        (OTIS_PHASE4_REASON_ESTIMATOR_UNDERQUALIFIED |
         OTIS_PHASE4_REASON_ESTIMATOR_DISPERSION));
  decision->eligibility_reason_mask =
      decision->estimator_eligible ? OTIS_PHASE4_REASON_NONE
                                   : eligibility_reasons;
  decision->model_reason_mask = model_reasons(observation->model);
  decision->model_applicable =
      decision->model_reason_mask == OTIS_PHASE4_REASON_NONE;
  decision->preview_eligible =
      decision->estimator_eligible && decision->model_applicable &&
      decision->estimate_available;
  if (!decision->preview_eligible) return;

  decision->raw_delta_codes =
      -decision->frequency_error_hz / observation->model.hz_per_code;
  const int32_t rounded = round_half_away_from_zero(decision->raw_delta_codes);
  const int32_t maximum_step =
      (int32_t)observation->model.maximum_preview_step_codes;
  int32_t step = rounded;
  if (step > maximum_step) step = maximum_step;
  if (step < -maximum_step) step = -maximum_step;
  decision->step_limited = step != rounded;
  int32_t proposed = (int32_t)observation->model.current_dac_code + step;
  if (proposed < (int32_t)observation->model.candidate_min_code) {
    proposed = observation->model.candidate_min_code;
    decision->range_clamped = true;
  }
  if (proposed > (int32_t)observation->model.candidate_max_code) {
    proposed = observation->model.candidate_max_code;
    decision->range_clamped = true;
  }
  decision->limited_delta_codes =
      proposed - (int32_t)observation->model.current_dac_code;
  decision->proposed_dac_code = (uint16_t)proposed;
  decision->preview_available = true;
}

const char *otis_phase4_state_name(OtisPhase4State state) {
  switch (state) {
    case OTIS_PHASE4_BOOT: return "BOOT";
    case OTIS_PHASE4_WARMUP_INHIBIT: return "WARMUP_INHIBIT";
    case OTIS_PHASE4_QUALIFYING: return "QUALIFYING";
    case OTIS_PHASE4_ACQUIRE_PREVIEW: return "ACQUIRE_PREVIEW";
    case OTIS_PHASE4_SETTLE_PREVIEW: return "SETTLE_PREVIEW";
    case OTIS_PHASE4_LOCKED_PREVIEW: return "LOCKED_PREVIEW";
    case OTIS_PHASE4_HOLDOVER_PREVIEW: return "HOLDOVER_PREVIEW";
    case OTIS_PHASE4_RECOVER_PREVIEW: return "RECOVER_PREVIEW";
    case OTIS_PHASE4_FAULT: return "FAULT";
  }
  return "FAULT";
}

const char *otis_phase4_confidence_name(OtisPhase4Confidence confidence) {
  switch (confidence) {
    case OTIS_PHASE4_CONFIDENCE_UNAVAILABLE: return "unavailable";
    case OTIS_PHASE4_CONFIDENCE_LOW: return "low";
    case OTIS_PHASE4_CONFIDENCE_MEDIUM: return "medium";
    case OTIS_PHASE4_CONFIDENCE_HIGH: return "high";
  }
  return "unavailable";
}

const char *otis_phase4_transition_reason_name(
    OtisPhase4TransitionReason reason) {
  switch (reason) {
    case OTIS_PHASE4_TRANSITION_STARTUP_INHIBIT:
      return "startup_inhibit_active";
    case OTIS_PHASE4_TRANSITION_QUALIFYING:
      return "clean_window_qualification_incomplete";
    case OTIS_PHASE4_TRANSITION_STARTUP_QUALIFIED:
      return "startup_qualification_complete";
    case OTIS_PHASE4_TRANSITION_POST_QUALIFICATION_FAULT:
      return "post_qualification_measurement_fault";
    case OTIS_PHASE4_TRANSITION_FAULT_LATCHED: return "fault_latched";
    case OTIS_PHASE4_TRANSITION_REFERENCE_HOLDOVER:
      return "reference_not_eligible_holdover";
    case OTIS_PHASE4_TRANSITION_REFERENCE_RETURN:
      return "reference_return_requalification";
    case OTIS_PHASE4_TRANSITION_RECOVERY_QUALIFYING:
      return "recovery_clean_window_qualification";
    case OTIS_PHASE4_TRANSITION_RECOVERY_INTERRUPTED:
      return "recovery_interrupted";
    case OTIS_PHASE4_TRANSITION_RECOVERY_QUALIFIED:
      return "recovery_qualified";
  }
  return "clean_window_qualification_incomplete";
}
