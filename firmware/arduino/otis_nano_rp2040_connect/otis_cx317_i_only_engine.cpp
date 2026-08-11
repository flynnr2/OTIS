#include "otis_cx317_i_only_engine.h"

#include <math.h>

#include "otis_config.h"

namespace {

// CX317_POST_CAMPAIGN_FREQUENCY_CONTROL_POLICY_V1. Each numerical value is
// bound to the sealed Campaign A/B result used by Stage 6. This engine remains
// structurally observe-only: kActiveLiveUpdateCodes is exactly zero.
#if OTIS_CX317_ACTIVE_CAMPAIGN == \
    OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_REHEARSAL
constexpr uint32_t kStartupWarmupS = OTIS_CX317_STARTUP_WARMUP_S;
constexpr uint32_t kEstimatorSpanS =
    OTIS_CX317_SELECTED_SPAN_INTERVALS_CONFIG;
constexpr uint32_t kFullHistoryResetS = OTIS_CX317_FULL_HISTORY_RESET_S;
constexpr uint32_t kRecoveryFreshSupportS =
    OTIS_CX317_RECOVERY_FRESH_SUPPORT_S;
constexpr uint32_t kDecisionCadenceS = OTIS_CX317_DECISION_CADENCE_S;
#else
constexpr uint32_t kStartupWarmupS = 1800u;
constexpr uint32_t kEstimatorSpanS = 600u;
constexpr uint32_t kFullHistoryResetS = 1500u;
constexpr uint32_t kRecoveryFreshSupportS = 600u;
constexpr uint32_t kDecisionCadenceS = 1800u;
#endif
#if !OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW
constexpr double kErrorDeadbandHz = 0.006249995628992717;
#endif
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

void fill_common(const OtisCx317IOnlyEngine &engine,
                 OtisCx317PreviewState previous,
                 const OtisCx317PreviewInput &input,
                 OtisCx317PreviewDecision *decision) {
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
#if OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW
  decision->tight_deadband_decision_available =
      engine.tight_deadband_decision_available;
  if (engine.tight_deadband_decision_available)
    decision->tight_deadband = engine.tight_deadband_decision;
#endif
}

const char *fault_reason(const OtisCx317PreviewInput &input) {
  if (!input.reference_valid) return "reference_invalid";
  if (!input.estimator_valid) return "estimator_invalid_or_snapshot_gap";
  if (!input.count_valid) return "count_invalid";
  if (!input.applied_code_matches) return "requested_applied_mismatch";
  if (!input.i2c_ok) return "i2c_failure";
  if (input.current_code < kDacMinimumCode ||
      input.current_code > kDacMaximumCode)
    return "current_code_outside_clamp";
  return nullptr;
}

}  // namespace

void otis_cx317_i_only_engine_init(OtisCx317IOnlyEngine *engine,
                                   uint32_t startup_s) {
  if (engine == nullptr) return;
  *engine = {};
  engine->state = OtisCx317PreviewState::WarmupInhibit;
  engine->startup_s = startup_s;
  engine->inhibit_until_s = startup_s + kStartupWarmupS;
  engine->reason = "startup_warmup";
#if OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW
  otis_cx318_stage5_tight_deadband_init(&engine->tight_deadband);
  engine->tight_deadband_decision_available = false;
#endif
}

void otis_cx317_i_only_engine_note_dac_epoch(OtisCx317IOnlyEngine *engine,
                                             uint32_t timestamp_s) {
  if (engine == nullptr || engine->state == OtisCx317PreviewState::Aborted)
    return;
  engine->state = OtisCx317PreviewState::SettlingInhibit;
  engine->reason = "dac_epoch_full_history_reset";
  engine->inhibit_until_s = timestamp_s + kFullHistoryResetS;
  engine->integrator_codes = 0.0;
#if OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW
  // The setup stimulus and each automatic application start a new local DAC
  // epoch.  Preserve the 1800 s applied cadence independently of the shorter
  // 900+600 s measurement-history reset.  Do not pre-reset the tight-band
  // machine here: the first fresh observation in the new epoch must perform
  // and report the identity transition itself so captured TDB evidence remains
  // exactly replayable from the wire history.
  engine->last_decision_s = timestamp_s;
  engine->have_last_decision = true;
  engine->tight_deadband_decision_available = false;
#else
  engine->have_last_decision = false;
#endif
}

void otis_cx317_i_only_engine_evaluate(
    OtisCx317IOnlyEngine *engine, const OtisCx317PreviewInput *input,
    OtisCx317PreviewDecision *decision) {
  if (engine == nullptr || input == nullptr || decision == nullptr) return;
  const OtisCx317PreviewState previous = engine->state;

  if (input->operator_abort) {
    engine->state = OtisCx317PreviewState::Aborted;
    engine->reason = "operator_abort";
    engine->integrator_codes = 0.0;
#if OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW
    otis_cx318_stage5_tight_deadband_requalify(&engine->tight_deadband);
    engine->tight_deadband_decision_available = false;
#endif
    fill_common(*engine, previous, *input, decision);
    return;
  }
  if (engine->state == OtisCx317PreviewState::Aborted) {
    fill_common(*engine, previous, *input, decision);
    return;
  }

  const char *fault = fault_reason(*input);
  if (fault != nullptr) {
    engine->state = OtisCx317PreviewState::Fault;
    engine->reason = fault;
    engine->integrator_codes = 0.0;
#if OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW
    otis_cx318_stage5_tight_deadband_requalify(&engine->tight_deadband);
    engine->tight_deadband_decision_available = false;
#endif
    fill_common(*engine, previous, *input, decision);
    return;
  }
  if (engine->state == OtisCx317PreviewState::Fault) {
    if (!input->recovery_requested) {
      fill_common(*engine, previous, *input, decision);
      return;
    }
    engine->state = OtisCx317PreviewState::Qualifying;
    engine->reason = "explicit_recovery_fresh_support";
    engine->inhibit_until_s = input->timestamp_s + kRecoveryFreshSupportS;
    engine->integrator_codes = 0.0;
#if OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW
    otis_cx318_stage5_tight_deadband_requalify(&engine->tight_deadband);
    engine->tight_deadband_decision_available = false;
#endif
    fill_common(*engine, previous, *input, decision);
    return;
  }
  if (!input->model_applicable) {
    engine->state = OtisCx317PreviewState::Fault;
    engine->reason = "plant_model_mismatch";
    engine->integrator_codes = 0.0;
    engine->have_last_decision = false;
#if OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW
    otis_cx318_stage5_tight_deadband_requalify(&engine->tight_deadband);
    engine->tight_deadband_decision_available = false;
#endif
    fill_common(*engine, previous, *input, decision);
    return;
  }
  if (engine->state == OtisCx317PreviewState::OutOfModelHold) {
    engine->state = OtisCx317PreviewState::Qualifying;
    engine->reason = "model_reapplicable_fresh_support";
    engine->inhibit_until_s = input->timestamp_s + kRecoveryFreshSupportS;
    engine->integrator_codes = 0.0;
    engine->have_last_decision = false;
#if OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW
    otis_cx318_stage5_tight_deadband_requalify(&engine->tight_deadband);
    engine->tight_deadband_decision_available = false;
#endif
    fill_common(*engine, previous, *input, decision);
    return;
  }
  if (input->dac_epoch) {
    engine->state = OtisCx317PreviewState::SettlingInhibit;
    engine->reason = "dac_epoch_full_history_reset";
    engine->inhibit_until_s = input->timestamp_s + kFullHistoryResetS;
    engine->integrator_codes = 0.0;
    engine->have_last_decision = false;
    fill_common(*engine, previous, *input, decision);
    return;
  }
  if (input->timestamp_s < engine->startup_s + kStartupWarmupS) {
    engine->state = OtisCx317PreviewState::WarmupInhibit;
    engine->reason = "startup_warmup";
    fill_common(*engine, previous, *input, decision);
    return;
  }
  if (input->timestamp_s < engine->inhibit_until_s) {
    fill_common(*engine, previous, *input, decision);
    return;
  }
  if (engine->state == OtisCx317PreviewState::WarmupInhibit) {
    engine->state = OtisCx317PreviewState::Qualifying;
    engine->reason = "fresh_estimator_support";
    engine->inhibit_until_s = input->timestamp_s + kEstimatorSpanS;
    fill_common(*engine, previous, *input, decision);
    return;
  }
  if (engine->state == OtisCx317PreviewState::SettlingInhibit) {
    engine->state = OtisCx317PreviewState::Qualifying;
    engine->reason = "dac_epoch_fresh_history_complete";
  }
  if (engine->state == OtisCx317PreviewState::Qualifying &&
      input->timestamp_s < engine->inhibit_until_s) {
    fill_common(*engine, previous, *input, decision);
    return;
  }
#if OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW
  if (!input->frequency_available || !isfinite(input->frequency_error_hz) ||
      !input->accumulated_edge_error_counts_available) {
    engine->state = OtisCx317PreviewState::Fault;
    engine->reason = "authoritative_integer_edge_error_unavailable";
    engine->integrator_codes = 0.0;
    otis_cx318_stage5_tight_deadband_requalify(&engine->tight_deadband);
    engine->tight_deadband_decision_available = false;
    fill_common(*engine, previous, *input, decision);
    return;
  }
  const OtisCx318Stage5TightDeadbandInput tight_input = {
      input->accumulated_edge_error_counts,
      input->accumulated_edge_error_counts_available,
      true,
      input->capture_session,
      input->dac_epoch_identity,
  };
  if (!otis_cx318_stage5_tight_deadband_observe(
          &engine->tight_deadband, &tight_input,
          &engine->tight_deadband_decision)) {
    engine->state = OtisCx317PreviewState::Fault;
    engine->reason = "tight_deadband_evaluation_failed";
    engine->integrator_codes = 0.0;
    engine->tight_deadband_decision_available = false;
    fill_common(*engine, previous, *input, decision);
    return;
  }
  engine->tight_deadband_decision_available = true;
  if (!engine->tight_deadband_decision.frequency_controller_eligible) {
    engine->state = OtisCx317PreviewState::Tracking;
    engine->reason = otis_cx318_stage5_tight_deadband_reason_name(
        engine->tight_deadband_decision.reason);
    engine->integrator_codes = 0.0;
    fill_common(*engine, previous, *input, decision);
    decision->preview_available = true;
    decision->proposed_code = input->current_code;
    return;
  }
#endif
  if (engine->have_last_decision &&
      input->timestamp_s - engine->last_decision_s < kDecisionCadenceS) {
    engine->state = OtisCx317PreviewState::Tracking;
    engine->reason = "decision_cadence_hold";
    fill_common(*engine, previous, *input, decision);
    return;
  }
  if (!input->frequency_available || !isfinite(input->frequency_error_hz)) {
    engine->state = OtisCx317PreviewState::Fault;
    engine->reason = "frequency_error_unavailable";
    engine->integrator_codes = 0.0;
    fill_common(*engine, previous, *input, decision);
    return;
  }

  engine->last_decision_s = input->timestamp_s;
  engine->have_last_decision = true;
  engine->state = OtisCx317PreviewState::Tracking;
#if !OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW
  if (fabs(input->frequency_error_hz) <= kErrorDeadbandHz) {
    engine->integrator_codes = 0.0;
    engine->reason = "inside_evidence_deadband";
    fill_common(*engine, previous, *input, decision);
    decision->preview_available = true;
    decision->proposed_code = input->current_code;
    return;
  }
#endif

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
  engine->reason = "preview_available_observe_only";
  fill_common(*engine, previous, *input, decision);
  decision->raw_delta_codes = raw;
  decision->limited_delta_codes = actual_delta;
  decision->proposed_code = static_cast<uint16_t>(proposed);
  decision->step_limited = fabs(raw - limited) > 1e-12;
  decision->range_clamped = proposed != unclamped;
  decision->preview_available = true;
}

const char *otis_cx317_preview_state_name(OtisCx317PreviewState state) {
  switch (state) {
    case OtisCx317PreviewState::WarmupInhibit:
      return "WARMUP_INHIBIT";
    case OtisCx317PreviewState::Qualifying:
      return "QUALIFYING";
    case OtisCx317PreviewState::SettlingInhibit:
      return "SETTLE_PREVIEW";
    case OtisCx317PreviewState::Tracking:
      return "LOCKED_PREVIEW";
    case OtisCx317PreviewState::OutOfModelHold:
      return "OUT_OF_MODEL_HOLD";
    case OtisCx317PreviewState::Fault:
    case OtisCx317PreviewState::Aborted:
      return "FAULT";
  }
  return "FAULT";
}
