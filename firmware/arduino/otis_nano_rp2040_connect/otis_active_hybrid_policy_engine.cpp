#include "otis_active_hybrid_policy_engine.h"

#include <math.h>
#include <stddef.h>
#include <string.h>

namespace {

constexpr double kPhaseBiasCapHz = 1.0 / 600.0;
constexpr double kPhasePullInS = 21600.0;
constexpr double kIntegratorGainCodesPerHzPerDecision = 2884.5027706464516;
constexpr int32_t kMaximumStepCodes = 21;
constexpr uint16_t kMinimumCode = 0xA800u;
constexpr uint16_t kMaximumCode = 0xAB00u;
constexpr uint16_t kStartCode = 0xA83Cu;
constexpr uint32_t kMinimumCadenceS = 1800u;
constexpr uint32_t kPhaseQualificationResidenceS = 1800u;
constexpr uint16_t kMaximumApplications = 4u;
constexpr uint16_t kMaximumCumulativeMovementCodes = 84u;

double clamp_double(double value, double lower, double upper) {
  return value < lower ? lower : (value > upper ? upper : value);
}

int32_t round_half_away(double value) {
  return value >= 0.0 ? static_cast<int32_t>(floor(value + 0.5))
                      : static_cast<int32_t>(ceil(value - 0.5));
}

void fault(OtisActiveHybridEngine *engine, const char *reason) {
  engine->state = OtisActiveHybridState::FailStatic;
  engine->reason = reason;
  engine->fault_reason = reason;
  engine->transaction_outstanding = false;
}

bool tight_inside(const OtisActiveHybridObservation *observation) {
  return observation->tight_state != nullptr &&
         strcmp(observation->tight_state, "TIGHT_INSIDE") == 0;
}

bool phase_exact(const OtisActiveHybridObservation *observation) {
  return observation->phase_continuous && observation->phase_current &&
         !observation->phase_step_detected &&
         observation->phase_consumers_exact && observation->phase_epoch > 0u &&
         observation->phase_observation_sequence > 0u &&
         observation->phase_dac_epoch == observation->dac_epoch &&
         observation->phase_applied_code == observation->applied_code;
}

void limited_delta(double demand_hz, uint16_t current_code, double *raw,
                   int32_t *delta, bool *step_limited,
                   bool *range_clamped) {
  *raw = kIntegratorGainCodesPerHzPerDecision * demand_hz;
  const double limited =
      clamp_double(*raw, -static_cast<double>(kMaximumStepCodes),
                   static_cast<double>(kMaximumStepCodes));
  *step_limited = fabs(*raw - limited) > 1e-12;
  const int32_t rounded = round_half_away(limited);
  const int32_t unclamped = static_cast<int32_t>(current_code) + rounded;
  const int32_t requested =
      unclamped < kMinimumCode
          ? kMinimumCode
          : (unclamped > kMaximumCode ? kMaximumCode : unclamped);
  *range_clamped = requested != unclamped;
  *delta = requested - static_cast<int32_t>(current_code);
}

const char *chatter_reason(const OtisActiveHybridEngine *engine,
                           int32_t delta) {
  const int8_t direction = delta > 0 ? 1 : -1;
  if (engine->direction_count >= 3u) {
    const uint8_t begin = static_cast<uint8_t>(engine->direction_count - 3u);
    int reversals = 0;
    int8_t previous = engine->direction_history[begin];
    for (uint8_t index = static_cast<uint8_t>(begin + 1u);
         index < engine->direction_count; ++index) {
      reversals += previous != engine->direction_history[index];
      previous = engine->direction_history[index];
    }
    reversals += previous != direction;
    if (reversals == 3) return "prospective_repeated_alternation";
  }
  const uint16_t movement =
      static_cast<uint16_t>(delta < 0 ? -delta : delta);
  const uint16_t path =
      static_cast<uint16_t>(engine->cumulative_movement_codes + movement);
  const int32_t net = static_cast<int32_t>(engine->applied_code) + delta -
                      static_cast<int32_t>(kStartCode);
  if (path >= 42u && abs(net) <= 0.25 * path)
    return "prospective_low_efficiency_path";
  return nullptr;
}

}  // namespace

void otis_active_hybrid_engine_init(OtisActiveHybridEngine *engine,
                                    uint32_t setup_application_s) {
  if (engine == nullptr) return;
  *engine = {};
  engine->state = OtisActiveHybridState::FrequencyAcquire;
  engine->reason = "initialized_frequency_acquire";
  engine->applied_code = kStartCode;
  engine->dac_epoch = 1u;
  engine->last_application_available = true;
  engine->last_application_s = setup_application_s;
}

bool otis_active_hybrid_engine_decide(
    OtisActiveHybridEngine *engine,
    const OtisActiveHybridObservation *observation,
    OtisActiveHybridDecision *decision) {
  if (engine == nullptr || observation == nullptr || decision == nullptr ||
      !isfinite(observation->frequency_error_hz))
    return false;
  *decision = {};
  decision->decision_sequence = ++engine->decision_sequence;
  decision->timestamp_s = observation->timestamp_s;
  decision->state_before = engine->state;
  decision->frequency_term_hz = -observation->frequency_error_hz;
  decision->requested_code = observation->applied_code;
  decision->correction_count_before = engine->correction_count;
  decision->cumulative_movement_before_codes =
      engine->cumulative_movement_codes;
  const bool phase_is_exact = phase_exact(observation);
  bool progressive_release_transition = false;
  const char *reason = engine->reason;

  if (engine->state == OtisActiveHybridState::FailStatic) {
    reason = engine->fault_reason == nullptr ? "fail_static_latched"
                                             : engine->fault_reason;
  } else if (!observation->identity_exact ||
             !observation->common_health_clean) {
    fault(engine, "measurement_authority_or_common_health_fault");
    reason = engine->reason;
  } else if (observation->applied_code != engine->applied_code ||
             observation->dac_epoch != engine->dac_epoch) {
    fault(engine, "actual_applied_code_or_dac_epoch_ambiguous");
    reason = engine->reason;
  } else if (observation->outstanding_request !=
             engine->transaction_outstanding) {
    fault(engine, "transaction_outstanding_identity_mismatch");
    reason = engine->reason;
  } else if (engine->transaction_outstanding &&
             engine->outstanding_phase_material && !phase_is_exact) {
    fault(engine, "phase_invalid_during_transaction_or_response_horizon");
    reason = engine->reason;
  } else if (engine->transaction_outstanding ||
             observation->outstanding_response) {
    reason = "request_or_response_checkpoint_outstanding";
  } else {
    bool phase_qualified = phase_is_exact;
    if (phase_qualified) {
      if (!engine->phase_identity_available) {
        engine->phase_identity_available = true;
        engine->phase_session = observation->capture_session;
        engine->phase_epoch = observation->phase_epoch;
      } else if (engine->phase_session != observation->capture_session ||
                 engine->phase_epoch != observation->phase_epoch) {
        phase_qualified = false;
      }
    }
    if (!phase_qualified &&
        (engine->state == OtisActiveHybridState::PhaseQualify ||
         engine->state == OtisActiveHybridState::FirstPhaseTransaction ||
         engine->state == OtisActiveHybridState::HybridTracking)) {
      engine->state = OtisActiveHybridState::PhaseDegradedFrequencyOnly;
      engine->reason = "phase_evidence_invalid_at_clean_boundary";
      reason = engine->reason;
    }

    if (engine->state == OtisActiveHybridState::FirstPhaseTransaction) {
      if (engine->first_checkpoint_response_passed &&
          tight_inside(observation)) {
        engine->state = OtisActiveHybridState::HybridTracking;
        engine->reason =
            "first_phase_checkpoint_passed_and_tight_reacquired";
        reason = engine->reason;
        progressive_release_transition = true;
      } else {
        reason = "first_phase_checkpoint_or_tight_reacquisition_pending";
      }
    } else if (engine->state == OtisActiveHybridState::FrequencyAcquire &&
               tight_inside(observation)) {
      engine->state = OtisActiveHybridState::PhaseQualify;
      engine->phase_qualification_started = true;
      engine->phase_qualification_started_s = observation->timestamp_s;
      engine->reason = "two_fresh_tight_estimates_enter_phase_qualification";
      reason = engine->reason;
    } else if (engine->state == OtisActiveHybridState::PhaseQualify) {
      if (!tight_inside(observation)) {
        engine->state = OtisActiveHybridState::FrequencyAcquire;
        engine->phase_qualification_started = false;
        engine->reason = "tight_frequency_residence_lost";
        reason = engine->reason;
      } else if (phase_qualified) {
        engine->reason = "phase_qualified_first_transaction_eligible";
        reason = engine->reason;
      }
    }

    const bool phase_authorized =
        phase_qualified && tight_inside(observation) &&
        (engine->state == OtisActiveHybridState::PhaseQualify ||
         engine->state == OtisActiveHybridState::HybridTracking) &&
        strcmp(reason, "two_fresh_tight_estimates_enter_phase_qualification") !=
            0 &&
        !progressive_release_transition &&
        (engine->state == OtisActiveHybridState::HybridTracking ||
         (engine->phase_qualification_started &&
          observation->timestamp_s - engine->phase_qualification_started_s >=
              kPhaseQualificationResidenceS));
    const bool frequency_authorized =
        !tight_inside(observation) &&
        (engine->state == OtisActiveHybridState::FrequencyAcquire ||
         engine->state ==
             OtisActiveHybridState::PhaseDegradedFrequencyOnly);
    if (phase_authorized) {
      decision->phase_term_hz = clamp_double(
          -static_cast<double>(observation->relative_phase_cycles) /
              kPhasePullInS,
          -kPhaseBiasCapHz, kPhaseBiasCapHz);
      decision->combined_demand_hz =
          decision->frequency_term_hz + decision->phase_term_hz;
    } else if (frequency_authorized) {
      decision->combined_demand_hz = decision->frequency_term_hz;
    }

    if (phase_authorized || frequency_authorized) {
      if (engine->last_application_available &&
          observation->timestamp_s - engine->last_application_s <
              kMinimumCadenceS) {
        decision->cadence_limited = true;
        reason = "minimum_applied_cadence_hold";
      } else {
        limited_delta(
            decision->combined_demand_hz, observation->applied_code,
            &decision->raw_combined_delta_codes,
            &decision->requested_delta_codes, &decision->step_limited,
            &decision->range_clamped);
        double ignored_raw = 0.0;
        bool ignored_step = false;
        bool ignored_range = false;
        limited_delta(decision->frequency_term_hz, observation->applied_code,
                      &ignored_raw,
                      &decision->counterfactual_frequency_only_delta_codes,
                      &ignored_step, &ignored_range);
        int32_t &counterfactual =
            decision->counterfactual_frequency_only_delta_codes;
        const uint16_t counterfactual_movement = static_cast<uint16_t>(
            counterfactual < 0 ? -counterfactual : counterfactual);
        if (counterfactual != 0 &&
            (engine->correction_count + 1u > kMaximumApplications ||
             engine->cumulative_movement_codes + counterfactual_movement >
                 kMaximumCumulativeMovementCodes ||
             chatter_reason(engine, counterfactual) != nullptr)) {
          counterfactual = 0;
        }
        int32_t &delta = decision->requested_delta_codes;
        if (delta != 0 && phase_authorized &&
            delta * decision->phase_term_hz < 0.0) {
          delta = 0;
          reason = "phase_direction_coherence_hold";
        } else if (delta == 0) {
          reason = "zero_rounded_or_range_hold";
        } else if (engine->correction_count + 1u > kMaximumApplications) {
          decision->count_limited = true;
          delta = 0;
          reason = "global_application_budget_hold";
        } else if (engine->cumulative_movement_codes +
                       static_cast<uint16_t>(delta < 0 ? -delta : delta) >
                   kMaximumCumulativeMovementCodes) {
          decision->cumulative_budget_limited = true;
          delta = 0;
          reason = "global_cumulative_movement_budget_hold";
        } else {
          const char *chatter = chatter_reason(engine, delta);
          if (chatter != nullptr) {
            fault(engine, chatter);
            delta = 0;
            reason = engine->reason;
          } else if (phase_authorized &&
                     delta !=
                         decision->counterfactual_frequency_only_delta_codes) {
            reason = "phase_material_request_ready";
          } else if (phase_authorized) {
            reason = "combined_nonmaterial_request_ready";
          } else {
            reason = "frequency_acquisition_request_ready";
          }
        }
      }
    }
  }

  decision->phase_materially_influenced =
      decision->phase_term_hz != 0.0 &&
      decision->requested_delta_codes !=
          decision->counterfactual_frequency_only_delta_codes;
  decision->requested_code = static_cast<uint16_t>(
      static_cast<int32_t>(observation->applied_code) +
      decision->requested_delta_codes);
  decision->state_after = engine->state;
  decision->reason = reason;
  return true;
}

bool otis_active_hybrid_engine_note_application(
    OtisActiveHybridEngine *engine,
    const OtisActiveHybridDecision *decision,
    uint16_t applied_code, uint32_t dac_epoch,
    bool downstream_consumers_exact) {
  if (engine == nullptr || decision == nullptr ||
      engine->state == OtisActiveHybridState::FailStatic ||
      engine->transaction_outstanding ||
      decision->requested_delta_codes == 0) {
    if (engine != nullptr) fault(engine, "invalid_or_overlapping_application");
    return false;
  }
  if (applied_code != decision->requested_code ||
      dac_epoch != engine->dac_epoch + 1u || !downstream_consumers_exact) {
    fault(engine, "application_or_downstream_epoch_mismatch");
    return false;
  }
  engine->applied_code = applied_code;
  engine->dac_epoch = dac_epoch;
  engine->correction_count++;
  const uint16_t movement = static_cast<uint16_t>(
      decision->requested_delta_codes < 0 ? -decision->requested_delta_codes
                                          : decision->requested_delta_codes);
  engine->cumulative_movement_codes = static_cast<uint16_t>(
      engine->cumulative_movement_codes + movement);
  engine->last_application_available = true;
  engine->last_application_s = decision->timestamp_s;
  engine->transaction_outstanding = true;
  engine->outstanding_phase_material =
      decision->phase_materially_influenced;
  if (engine->direction_count < 4u)
    engine->direction_history[engine->direction_count++] =
        decision->requested_delta_codes > 0 ? 1 : -1;
  if (decision->phase_term_hz != 0.0)
    engine->phase_nonzero_application_count++;
  if (decision->phase_materially_influenced) {
    engine->phase_material_application_count++;
    if (engine->phase_material_application_count == 1u) {
      engine->state = OtisActiveHybridState::FirstPhaseTransaction;
      engine->first_checkpoint_response_passed = false;
      engine->reason = "first_phase_application_checkpoint_required";
    }
  } else {
    engine->frequency_only_application_count++;
    engine->reason = "application_confirmed_response_required";
  }
  return true;
}

bool otis_active_hybrid_engine_note_response(
    OtisActiveHybridEngine *engine,
    bool healthy_classification, bool predicted_sign_observed,
    bool exact_replay, bool support_fresh, bool applied_epoch_exact) {
  if (engine == nullptr || !engine->transaction_outstanding) {
    if (engine != nullptr) fault(engine, "response_without_outstanding_application");
    return false;
  }
  const bool was_phase_material = engine->outstanding_phase_material;
  engine->transaction_outstanding = false;
  engine->outstanding_phase_material = false;
  if (!(healthy_classification && predicted_sign_observed && exact_replay &&
        support_fresh && applied_epoch_exact)) {
    fault(engine, "hybrid_response_wrong_or_checkpoint_evidence_invalid");
    return false;
  }
  if (was_phase_material && engine->phase_material_application_count == 1u) {
    engine->first_checkpoint_response_passed = true;
    engine->reason =
        "first_phase_response_passed_tight_reacquisition_required";
  } else {
    engine->reason = "response_passed";
  }
  return true;
}

void otis_active_hybrid_engine_degrade_phase(
    OtisActiveHybridEngine *engine, const char *reason) {
  if (engine == nullptr) return;
  if (engine->transaction_outstanding) {
    fault(engine, "phase_invalid_during_transaction_or_response_horizon");
    return;
  }
  if (engine->state != OtisActiveHybridState::FailStatic) {
    engine->state = OtisActiveHybridState::PhaseDegradedFrequencyOnly;
    engine->phase_identity_available = false;
    engine->reason = reason == nullptr ? "phase_channel_degraded" : reason;
  }
}

const char *otis_active_hybrid_state_name(OtisActiveHybridState state) {
  switch (state) {
    case OtisActiveHybridState::FrequencyAcquire:
      return "FREQUENCY_ACQUIRE";
    case OtisActiveHybridState::PhaseQualify:
      return "PHASE_QUALIFY";
    case OtisActiveHybridState::FirstPhaseTransaction:
      return "FIRST_PHASE_TRANSACTION";
    case OtisActiveHybridState::HybridTracking:
      return "HYBRID_TRACKING";
    case OtisActiveHybridState::PhaseDegradedFrequencyOnly:
      return "PHASE_DEGRADED_FREQUENCY_ONLY";
    case OtisActiveHybridState::FailStatic:
      return "FAIL_STATIC";
  }
  return "FAIL_STATIC";
}
