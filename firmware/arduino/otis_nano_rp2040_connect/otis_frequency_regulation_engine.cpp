#include "otis_frequency_regulation_engine.h"

#include <math.h>

#include "otis_config.h"

namespace {

// Selected frequency-regulation policy. The pure engine proposes corrections;
// physical authority remains in the bounded adaptive-hybrid transaction path.
constexpr uint32_t kStartupWarmupS = OTIS_ADAPTIVE_HYBRID_STARTUP_WARMUP_S;
constexpr uint32_t kEstimatorSpanS =
    OTIS_FREQUENCY_ESTIMATOR_SPAN_INTERVALS_CONFIG;
constexpr uint32_t kFullHistoryResetS = OTIS_ADAPTIVE_HYBRID_FULL_HISTORY_RESET_S;
constexpr uint32_t kRecoveryFreshSupportS =
    OTIS_ADAPTIVE_HYBRID_RECOVERY_FRESH_SUPPORT_S;
constexpr uint32_t kDecisionCadenceS = OTIS_ADAPTIVE_HYBRID_DECISION_CADENCE_S;
constexpr double kIntegratorGainCodesPerHz = 2884.5027706464516;
constexpr int32_t kIntegratorLimitCodes = 21;
constexpr uint16_t kDacMinimumCode = 0xA800u;
constexpr uint16_t kDacMaximumCode = 0xAB00u;
constexpr int32_t kActiveLiveUpdateCodes = 0;

int32_t round_half_away_from_zero(double value) {
  return value >= 0.0 ? static_cast<int32_t>(floor(value + 0.5))
                      : static_cast<int32_t>(ceil(value - 0.5));
}

double clip_integrator(double value) {
  if (value > static_cast<double>(kIntegratorLimitCodes))
    return static_cast<double>(kIntegratorLimitCodes);
  if (value < -static_cast<double>(kIntegratorLimitCodes))
    return -static_cast<double>(kIntegratorLimitCodes);
  return value;
}

void fill_common(const OtisFrequencyRegulationEngine &engine,
                 OtisFrequencyRegulationState previous,
                 const OtisFrequencyRegulationInput &input,
                 OtisFrequencyRegulationDecision *decision) {
  *decision = {};
  decision->state = engine.state;
  decision->previous_state = previous;
  decision->reason = engine.reason;
  decision->timestamp_s = input.timestamp_s;
  decision->current_code = input.current_code;
  decision->frequency_error_hz = input.frequency_error_hz;
  decision->frequency_available = input.frequency_available;
  decision->integrator_codes = engine.integrator_codes;
  decision->state_transition = previous != engine.state;
  decision->preview_only = true;
  decision->control_ready = false;
  decision->actuation_enabled = false;
  decision->actuation_authorized = false;
  decision->actionable = false;
  decision->active_update_codes = kActiveLiveUpdateCodes;
  decision->tight_deadband_decision_available =
      engine.tight_deadband_decision_available;
  if (engine.tight_deadband_decision_available)
    decision->tight_deadband = engine.tight_deadband_decision;
}

const char *recoverable_quality_reason(const OtisFrequencyRegulationInput &input) {
  if (!input.reference_valid) return "reference_invalid";
  if (!input.estimator_valid) return "estimator_invalid_or_snapshot_gap";
  if (!input.count_valid) return "count_invalid";
  return nullptr;
}

const char *fault_reason(const OtisFrequencyRegulationInput &input) {
  if (!input.applied_code_available) return "static_dac_code_unavailable";
  if (!input.applied_code_matches) return "requested_applied_mismatch";
  if (!input.i2c_ok) return "i2c_failure";
  if (input.current_code < kDacMinimumCode ||
      input.current_code > kDacMaximumCode)
    return "current_code_outside_clamp";
  return nullptr;
}

}  // namespace

void otis_frequency_regulation_engine_init(OtisFrequencyRegulationEngine *engine,
                                   uint32_t startup_s) {
  if (engine == nullptr) return;
  *engine = {};
  engine->state = OtisFrequencyRegulationState::WarmupInhibit;
  engine->startup_s = startup_s;
  engine->inhibit_until_s = startup_s + kStartupWarmupS;
  engine->reason = "startup_warmup";
  otis_integer_count_tight_deadband_init(&engine->tight_deadband);
  engine->tight_deadband_decision_available = false;
}

void otis_frequency_regulation_engine_note_dac_epoch(OtisFrequencyRegulationEngine *engine,
                                             uint32_t timestamp_s) {
  if (engine == nullptr || engine->state == OtisFrequencyRegulationState::Aborted)
    return;
  engine->state = OtisFrequencyRegulationState::SettlingInhibit;
  engine->reason = "dac_epoch_full_history_reset";
  engine->inhibit_until_s = timestamp_s + kFullHistoryResetS;
  engine->integrator_codes = 0.0;
  // The setup stimulus and each automatic application start a new local DAC
  // epoch.  Preserve the 1800 s applied cadence independently of the shorter
  // 900+600 s measurement-history reset.  Do not pre-reset the tight-band
  // machine here: the first fresh observation in the new epoch must perform
  // and report the identity transition itself so captured TDB evidence remains
  // exactly replayable from the wire history.
  engine->last_decision_s = timestamp_s;
  engine->have_last_decision = true;
  engine->tight_deadband_decision_available = false;
}

void otis_frequency_regulation_engine_evaluate(
    OtisFrequencyRegulationEngine *engine, const OtisFrequencyRegulationInput *input,
    OtisFrequencyRegulationDecision *decision) {
  if (engine == nullptr || input == nullptr || decision == nullptr) return;
  const OtisFrequencyRegulationState previous = engine->state;

  if (input->operator_abort) {
    engine->state = OtisFrequencyRegulationState::Aborted;
    engine->reason = "operator_abort";
    engine->integrator_codes = 0.0;
    otis_integer_count_tight_deadband_requalify(&engine->tight_deadband);
    engine->tight_deadband_decision_available = false;
    fill_common(*engine, previous, *input, decision);
    return;
  }
  if (engine->state == OtisFrequencyRegulationState::Aborted) {
    fill_common(*engine, previous, *input, decision);
    return;
  }
  if (engine->state == OtisFrequencyRegulationState::Fault) {
    fill_common(*engine, previous, *input, decision);
    return;
  }

  if (!input->actuator_context_established) {
    // Before the deliberate one-shot setup there is no authoritative DAC
    // code against which to evaluate the plant model.  The estimator remains
    // useful evidence, but the preview controller has zero authority and must
    // not manufacture a requested/applied mismatch fault from that absence.
    if (input->applied_code_available || input->applied_code_matches ||
        input->model_applicable || input->current_code != 0u) {
      engine->state = OtisFrequencyRegulationState::Fault;
      engine->reason = "pre_setup_static_code_context_inconsistent";
      engine->integrator_codes = 0.0;
      engine->have_last_decision = false;
      otis_integer_count_tight_deadband_requalify(&engine->tight_deadband);
      engine->tight_deadband_decision_available = false;
      fill_common(*engine, previous, *input, decision);
      return;
    }
    engine->state = OtisFrequencyRegulationState::SetupInhibit;
    engine->reason = "static_dac_code_unavailable_no_control_authority";
    engine->integrator_codes = 0.0;
    engine->have_last_decision = false;
    otis_integer_count_tight_deadband_requalify(&engine->tight_deadband);
    engine->tight_deadband_decision_available = false;
    fill_common(*engine, previous, *input, decision);
    return;
  }

  const char *fault = fault_reason(*input);
  if (fault != nullptr) {
    engine->state = OtisFrequencyRegulationState::Fault;
    engine->reason = fault;
    engine->integrator_codes = 0.0;
    otis_integer_count_tight_deadband_requalify(&engine->tight_deadband);
    engine->tight_deadband_decision_available = false;
    fill_common(*engine, previous, *input, decision);
    return;
  }

  const char *recoverable_quality = recoverable_quality_reason(*input);
  if (recoverable_quality != nullptr) {
    engine->state = OtisFrequencyRegulationState::Qualifying;
    engine->reason = recoverable_quality;
    engine->inhibit_until_s = input->timestamp_s + kRecoveryFreshSupportS;
    engine->integrator_codes = 0.0;
    engine->have_last_decision = false;
    otis_integer_count_tight_deadband_requalify(&engine->tight_deadband);
    engine->tight_deadband_decision_available = false;
    fill_common(*engine, previous, *input, decision);
    return;
  }
  if (!input->model_applicable) {
    engine->state = OtisFrequencyRegulationState::Fault;
    engine->reason = "plant_model_mismatch";
    engine->integrator_codes = 0.0;
    engine->have_last_decision = false;
    otis_integer_count_tight_deadband_requalify(&engine->tight_deadband);
    engine->tight_deadband_decision_available = false;
    fill_common(*engine, previous, *input, decision);
    return;
  }
  if (engine->state == OtisFrequencyRegulationState::OutOfModelHold) {
    engine->state = OtisFrequencyRegulationState::Qualifying;
    engine->reason = "model_reapplicable_fresh_support";
    engine->inhibit_until_s = input->timestamp_s + kRecoveryFreshSupportS;
    engine->integrator_codes = 0.0;
    engine->have_last_decision = false;
    otis_integer_count_tight_deadband_requalify(&engine->tight_deadband);
    engine->tight_deadband_decision_available = false;
    fill_common(*engine, previous, *input, decision);
    return;
  }
  if (input->dac_epoch) {
    engine->state = OtisFrequencyRegulationState::SettlingInhibit;
    engine->reason = "dac_epoch_full_history_reset";
    engine->inhibit_until_s = input->timestamp_s + kFullHistoryResetS;
    engine->integrator_codes = 0.0;
    engine->have_last_decision = false;
    fill_common(*engine, previous, *input, decision);
    return;
  }
  if (input->timestamp_s < engine->startup_s + kStartupWarmupS) {
    engine->state = OtisFrequencyRegulationState::WarmupInhibit;
    engine->reason = "startup_warmup";
    fill_common(*engine, previous, *input, decision);
    return;
  }
  if (input->timestamp_s < engine->inhibit_until_s) {
    fill_common(*engine, previous, *input, decision);
    return;
  }
  if (engine->state == OtisFrequencyRegulationState::WarmupInhibit) {
    engine->state = OtisFrequencyRegulationState::Qualifying;
    engine->reason = "fresh_estimator_support";
    engine->inhibit_until_s = input->timestamp_s + kEstimatorSpanS;
    fill_common(*engine, previous, *input, decision);
    return;
  }
  if (engine->state == OtisFrequencyRegulationState::SettlingInhibit) {
    engine->state = OtisFrequencyRegulationState::Qualifying;
    engine->reason = "dac_epoch_fresh_history_complete";
  }
  if (engine->state == OtisFrequencyRegulationState::Qualifying &&
      input->timestamp_s < engine->inhibit_until_s) {
    fill_common(*engine, previous, *input, decision);
    return;
  }
  if (!input->frequency_available || !isfinite(input->frequency_error_hz) ||
      !input->accumulated_edge_error_counts_available) {
    engine->state = OtisFrequencyRegulationState::Fault;
    engine->reason = "authoritative_integer_edge_error_unavailable";
    engine->integrator_codes = 0.0;
    otis_integer_count_tight_deadband_requalify(&engine->tight_deadband);
    engine->tight_deadband_decision_available = false;
    fill_common(*engine, previous, *input, decision);
    return;
  }
  const OtisIntegerCountDeadbandTightDeadbandInput tight_input = {
      input->accumulated_edge_error_counts,
      input->accumulated_edge_error_counts_available,
      true,
      input->capture_session,
      input->dac_epoch_identity,
  };
  if (!otis_integer_count_tight_deadband_observe(
          &engine->tight_deadband, &tight_input,
          &engine->tight_deadband_decision)) {
    engine->state = OtisFrequencyRegulationState::Fault;
    engine->reason = "tight_deadband_evaluation_failed";
    engine->integrator_codes = 0.0;
    engine->tight_deadband_decision_available = false;
    fill_common(*engine, previous, *input, decision);
    return;
  }
  engine->tight_deadband_decision_available = true;
  if (!engine->tight_deadband_decision.frequency_controller_eligible) {
    engine->state = OtisFrequencyRegulationState::Tracking;
    engine->reason = otis_integer_count_tight_deadband_reason_name(
        engine->tight_deadband_decision.reason);
    engine->integrator_codes = 0.0;
    fill_common(*engine, previous, *input, decision);
    decision->preview_available = true;
    decision->proposed_code = input->current_code;
    return;
  }
  if (engine->have_last_decision &&
      input->timestamp_s - engine->last_decision_s < kDecisionCadenceS) {
    engine->state = OtisFrequencyRegulationState::Tracking;
    engine->reason = "decision_cadence_hold";
    fill_common(*engine, previous, *input, decision);
    return;
  }
  if (!input->frequency_available || !isfinite(input->frequency_error_hz)) {
    engine->state = OtisFrequencyRegulationState::Fault;
    engine->reason = "frequency_error_unavailable";
    engine->integrator_codes = 0.0;
    fill_common(*engine, previous, *input, decision);
    return;
  }

  engine->last_decision_s = input->timestamp_s;
  engine->have_last_decision = true;
  engine->state = OtisFrequencyRegulationState::Tracking;

  const double raw = engine->integrator_codes -
                     kIntegratorGainCodesPerHz * input->frequency_error_hz;
  const double limited = clip_integrator(raw);
  const int32_t rounded = round_half_away_from_zero(limited);
  const int32_t unclamped = static_cast<int32_t>(input->current_code) + rounded;
  int32_t proposed = unclamped;
  if (proposed < static_cast<int32_t>(kDacMinimumCode))
    proposed = kDacMinimumCode;
  if (proposed > static_cast<int32_t>(kDacMaximumCode))
    proposed = kDacMaximumCode;
  const int32_t actual_delta = proposed - input->current_code;
  engine->integrator_codes = static_cast<double>(actual_delta);
  engine->reason = "preview_available";
  fill_common(*engine, previous, *input, decision);
  decision->raw_delta_codes = raw;
  decision->limited_delta_codes = actual_delta;
  decision->proposed_code = static_cast<uint16_t>(proposed);
  decision->step_limited = fabs(raw - limited) > 1e-12;
  decision->range_clamped = proposed != unclamped;
  decision->preview_available = true;
}

const char *otis_regulation_preview_state_name(OtisFrequencyRegulationState state) {
  switch (state) {
    case OtisFrequencyRegulationState::WarmupInhibit:
      return "WARMUP_INHIBIT";
    case OtisFrequencyRegulationState::SetupInhibit:
      return "SAFE_OBSERVE";
    case OtisFrequencyRegulationState::Qualifying:
      return "QUALIFYING";
    case OtisFrequencyRegulationState::SettlingInhibit:
      return "SETTLE_PREVIEW";
    case OtisFrequencyRegulationState::Tracking:
      return "LOCKED_PREVIEW";
    case OtisFrequencyRegulationState::OutOfModelHold:
      return "OUT_OF_MODEL_HOLD";
    case OtisFrequencyRegulationState::Fault:
    case OtisFrequencyRegulationState::Aborted:
      return "FAULT";
  }
  return "FAULT";
}
