#include "otis_active_hybrid_policy_engine.h"

#include "otis_config.h"

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
constexpr uint64_t kTimer0TicksPerSecond = 16000000ull;
constexpr uint64_t kMinimumCadenceTicks =
    static_cast<uint64_t>(kMinimumCadenceS) * kTimer0TicksPerSecond;
constexpr uint64_t kPhaseQualificationResidenceTicks =
    static_cast<uint64_t>(kPhaseQualificationResidenceS) *
    kTimer0TicksPerSecond;
constexpr uint16_t kMaximumAutomaticApplications =
    OTIS_ACTIVE_HYBRID_MAX_AUTOMATIC_APPLICATIONS;
constexpr uint16_t kMaximumCumulativeMovementCodes = 84u;
constexpr uint64_t kNaturalReversalWindowTicks =
    43200ull * kTimer0TicksPerSecond;
constexpr uint64_t kChallengeLatestTicks =
    50400ull * kTimer0TicksPerSecond;
constexpr int32_t kChallengeStepCodes = 21;

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
      static_cast<uint16_t>(engine->natural_cumulative_movement_codes + movement);
  const int32_t net = static_cast<int32_t>(engine->applied_code) + delta -
                      static_cast<int32_t>(engine->natural_chatter_origin_code);
  if (path >= 42u && abs(net) <= 0.25 * path)
    return "prospective_low_efficiency_path";
  return nullptr;
}

uint16_t automatic_application_count(const OtisActiveHybridEngine *engine) {
  return OTIS_ACTIVE_HYBRID_ENABLE_REVERSAL_CHALLENGE
             ? engine->automatic_application_count
             : engine->correction_count;
}

}  // namespace

void otis_active_hybrid_engine_init(OtisActiveHybridEngine *engine,
                                    uint32_t setup_application_s) {
  if (engine == nullptr) return;
  *engine = {};
  engine->state = OtisActiveHybridState::FrequencyAcquire;
  engine->reason = "initialized_frequency_acquire";
  engine->applied_code = kStartCode;
  engine->natural_chatter_origin_code = kStartCode;
  engine->dac_epoch = 1u;
  engine->last_application_available = true;
  engine->last_application_s = setup_application_s;
}

void otis_active_hybrid_engine_init_at_ticks(
    OtisActiveHybridEngine *engine, uint64_t setup_application_ticks) {
  if (engine == nullptr || setup_application_ticks == 0u) return;
  otis_active_hybrid_engine_init(
      engine, static_cast<uint32_t>(setup_application_ticks /
                                    kTimer0TicksPerSecond));
  engine->exact_tick_timing_required = true;
  engine->last_application_ticks = setup_application_ticks;
}

bool otis_active_hybrid_engine_rebase_after_plant_sign(
    OtisActiveHybridEngine *engine, uint16_t applied_code, uint32_t dac_epoch,
    uint16_t global_correction_count,
    uint16_t global_cumulative_movement_codes,
    uint64_t identification_application_ticks,
    uint64_t response_acknowledgement_ticks) {
  if (engine == nullptr || applied_code < kMinimumCode ||
      applied_code > kMaximumCode || dac_epoch == 0u ||
      global_correction_count != 1u ||
      global_cumulative_movement_codes != 21u ||
      identification_application_ticks == 0u ||
      response_acknowledgement_ticks < identification_application_ticks) {
    if (engine != nullptr) fault(engine, "invalid_plant_sign_handoff");
    return false;
  }
  *engine = {};
  engine->state = OtisActiveHybridState::PhaseQualify;
  engine->reason = "plant_sign_acknowledged_phase_qualification_started";
  engine->applied_code = applied_code;
  engine->dac_epoch = dac_epoch;
  engine->correction_count = global_correction_count;
  engine->automatic_application_count = global_correction_count;
  engine->cumulative_movement_codes = global_cumulative_movement_codes;
  engine->natural_chatter_origin_code = applied_code;
  engine->natural_cumulative_movement_codes = 0u;
  engine->last_application_available = true;
  engine->last_application_s = static_cast<uint32_t>(
      identification_application_ticks / kTimer0TicksPerSecond);
  engine->exact_tick_timing_required = true;
  engine->last_application_ticks = identification_application_ticks;
  engine->phase_qualification_started = true;
  engine->phase_qualification_started_s = static_cast<uint32_t>(
      response_acknowledgement_ticks / kTimer0TicksPerSecond);
  engine->phase_qualification_started_ticks =
      response_acknowledgement_ticks;
  return true;
}

namespace {

bool decide_impl(
    OtisActiveHybridEngine *engine,
    const OtisActiveHybridObservation *observation,
    bool observation_ticks_available, uint64_t observation_ticks,
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
  bool deliberate_challenge_decision = false;
  const char *reason = engine->reason;

  if (engine->state == OtisActiveHybridState::FailStatic) {
    reason = engine->fault_reason == nullptr ? "fail_static_latched"
                                             : engine->fault_reason;
  } else if (engine->exact_tick_timing_required &&
             (!observation_ticks_available ||
              observation_ticks < engine->last_application_ticks ||
              (engine->phase_qualification_started &&
               observation_ticks <
                   engine->phase_qualification_started_ticks))) {
    fault(engine, "exact_tick_timing_missing_or_backward");
    reason = engine->reason;
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
    if (OTIS_ACTIVE_HYBRID_ENABLE_REVERSAL_CHALLENGE &&
        observation_ticks_available && !engine->qualified_origin_available) {
      engine->qualified_origin_available = true;
      engine->qualified_origin_ticks = observation_ticks;
    }
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
            engine->first_checkpoint_observation_only
                ? "first_phase_observation_recorded_and_tight_reacquired"
                : "first_phase_checkpoint_passed_and_tight_reacquired";
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
      if (engine->exact_tick_timing_required)
        engine->phase_qualification_started_ticks = observation_ticks;
      engine->reason = "two_fresh_tight_estimates_enter_phase_qualification";
      reason = engine->reason;
    } else if (engine->state == OtisActiveHybridState::PhaseQualify) {
      if (!tight_inside(observation)) {
        engine->state = OtisActiveHybridState::FrequencyAcquire;
        engine->phase_qualification_started = false;
        engine->phase_qualification_started_ticks = 0u;
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
          (engine->exact_tick_timing_required
               ? observation_ticks -
                         engine->phase_qualification_started_ticks >=
                     kPhaseQualificationResidenceTicks
               : observation->timestamp_s -
                         engine->phase_qualification_started_s >=
                     kPhaseQualificationResidenceS)));
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
      const bool cadence_pending =
          engine->last_application_available &&
          (engine->exact_tick_timing_required
               ? observation_ticks - engine->last_application_ticks <
                     kMinimumCadenceTicks
               : observation->timestamp_s - engine->last_application_s <
                     kMinimumCadenceS);
      if (cadence_pending) {
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
            (automatic_application_count(engine) + 1u >
                 kMaximumAutomaticApplications ||
             engine->cumulative_movement_codes + counterfactual_movement >
                 kMaximumCumulativeMovementCodes ||
             chatter_reason(engine, counterfactual) != nullptr)) {
          counterfactual = 0;
        }
        int32_t &delta = decision->requested_delta_codes;
        const int8_t natural_direction = delta > 0 ? 1 : (delta < 0 ? -1 : 0);
        const bool natural_reversal_ready =
            natural_direction != 0 && engine->natural_direction_available &&
            natural_direction != engine->natural_initial_direction;
        const uint64_t qualified_elapsed_ticks =
            engine->qualified_origin_available &&
                    observation_ticks >= engine->qualified_origin_ticks
                ? observation_ticks - engine->qualified_origin_ticks
                : 0u;
        const bool challenge_due =
            OTIS_ACTIVE_HYBRID_ENABLE_REVERSAL_CHALLENGE &&
            engine->qualified_origin_available &&
            qualified_elapsed_ticks >= kNaturalReversalWindowTicks &&
            qualified_elapsed_ticks <= kChallengeLatestTicks &&
            !engine->natural_reversal_observed &&
            !engine->deliberate_challenge_applied &&
            !engine->deliberate_challenge_cancelled &&
            !engine->deliberate_challenge_unexercised &&
            !natural_reversal_ready;
        if (challenge_due) {
          const int8_t challenge_direction =
              engine->natural_direction_available
                  ? engine->natural_initial_direction
                  : -1;
          const int32_t challenge_code =
              static_cast<int32_t>(observation->applied_code) +
              challenge_direction * kChallengeStepCodes;
          if (challenge_code < kMinimumCode || challenge_code > kMaximumCode ||
              engine->cumulative_movement_codes + kChallengeStepCodes >
                  kMaximumCumulativeMovementCodes) {
            engine->deliberate_challenge_unexercised = true;
            delta = 0;
            reason = "deliberate_reversal_challenge_budget_or_range_unavailable";
          } else {
            delta = challenge_direction * kChallengeStepCodes;
            decision->requested_code = static_cast<uint16_t>(challenge_code);
            decision->raw_combined_delta_codes =
                static_cast<double>(delta);
            decision->step_limited = false;
            decision->range_clamped = false;
            deliberate_challenge_decision = true;
            reason = "deliberate_reversal_challenge_request_ready";
          }
        } else if (delta != 0 && phase_authorized &&
            delta * decision->phase_term_hz < 0.0) {
          delta = 0;
          reason = "phase_direction_coherence_hold";
        } else if (delta == 0) {
          reason = "zero_rounded_or_range_hold";
        } else if (automatic_application_count(engine) + 1u >
                   kMaximumAutomaticApplications) {
          decision->count_limited = true;
          delta = 0;
          reason = "global_application_budget_hold";
        } else if (engine->cumulative_movement_codes +
                       static_cast<uint16_t>(delta < 0 ? -delta : delta) >
                   kMaximumCumulativeMovementCodes) {
          decision->cumulative_budget_limited = true;
          delta = 0;
          reason = "global_cumulative_movement_budget_hold";
        } else if (!deliberate_challenge_decision) {
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
        if (delta != 0 && !deliberate_challenge_decision &&
            engine->deliberate_challenge_applied &&
            (delta > 0 ? 1 : -1) ==
                -engine->deliberate_challenge_direction) {
          reason = "deliberate_reversal_challenge_recovery_request_ready";
        }
      }
    }
    if (OTIS_ACTIVE_HYBRID_ENABLE_REVERSAL_CHALLENGE &&
        engine->qualified_origin_available && observation_ticks_available &&
        observation_ticks - engine->qualified_origin_ticks >
            kChallengeLatestTicks &&
        !engine->natural_reversal_observed &&
        !engine->deliberate_challenge_applied &&
        !engine->deliberate_challenge_cancelled) {
      engine->deliberate_challenge_unexercised = true;
    }
  }

  decision->phase_materially_influenced =
      !deliberate_challenge_decision && decision->phase_term_hz != 0.0 &&
      decision->requested_delta_codes !=
          decision->counterfactual_frequency_only_delta_codes;
  decision->requested_code = static_cast<uint16_t>(
      static_cast<int32_t>(observation->applied_code) +
      decision->requested_delta_codes);
  decision->state_after = engine->state;
  decision->reason = reason;
  return true;
}

bool note_application_impl(
    OtisActiveHybridEngine *engine,
    const OtisActiveHybridDecision *decision,
    uint16_t applied_code, uint32_t dac_epoch,
    bool application_ticks_available, uint64_t application_ticks,
    bool downstream_consumers_exact) {
  if (engine == nullptr || decision == nullptr ||
      engine->state == OtisActiveHybridState::FailStatic ||
      engine->transaction_outstanding ||
      decision->requested_delta_codes == 0 ||
      (engine != nullptr && engine->exact_tick_timing_required &&
       (!application_ticks_available || application_ticks == 0u ||
        application_ticks < engine->last_application_ticks))) {
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
  const bool deliberate_challenge =
      decision->reason != nullptr &&
      strcmp(decision->reason,
             "deliberate_reversal_challenge_request_ready") == 0;
  engine->correction_count++;
  const uint16_t movement = static_cast<uint16_t>(
      decision->requested_delta_codes < 0 ? -decision->requested_delta_codes
                                          : decision->requested_delta_codes);
  engine->cumulative_movement_codes = static_cast<uint16_t>(
      engine->cumulative_movement_codes + movement);
  if (!deliberate_challenge) {
    engine->automatic_application_count++;
    engine->natural_cumulative_movement_codes = static_cast<uint16_t>(
        engine->natural_cumulative_movement_codes + movement);
  }
  engine->last_application_available = true;
  if (engine->exact_tick_timing_required) {
    engine->last_application_ticks = application_ticks;
    engine->last_application_s = static_cast<uint32_t>(
        application_ticks / kTimer0TicksPerSecond);
  } else {
    engine->last_application_s = decision->timestamp_s;
  }
  engine->transaction_outstanding = true;
  engine->outstanding_deliberate_challenge = deliberate_challenge;
  engine->outstanding_phase_material =
      deliberate_challenge || decision->phase_materially_influenced;
  const int8_t direction = decision->requested_delta_codes > 0 ? 1 : -1;
  if (deliberate_challenge) {
    engine->deliberate_challenge_applied = true;
    engine->deliberate_challenge_direction = direction;
    engine->deliberate_challenge_code = applied_code;
    engine->deliberate_challenge_dac_epoch = dac_epoch;
    engine->deliberate_challenge_application_ticks =
        engine->exact_tick_timing_required ? application_ticks : 0u;
    engine->reason = "deliberate_reversal_challenge_applied_response_required";
  } else {
    if (!engine->natural_direction_available) {
      engine->natural_direction_available = true;
      engine->natural_initial_direction = direction;
    } else if (direction != engine->natural_initial_direction) {
      engine->natural_reversal_observed = true;
      if (!engine->deliberate_challenge_applied)
        engine->deliberate_challenge_cancelled = true;
    }
    if (engine->deliberate_challenge_applied &&
        direction == -engine->deliberate_challenge_direction)
      engine->deliberate_challenge_recovery_applied = true;
    if (engine->direction_count < 4u) {
      engine->direction_history[engine->direction_count++] = direction;
    } else {
      engine->direction_history[0] = engine->direction_history[1];
      engine->direction_history[1] = engine->direction_history[2];
      engine->direction_history[2] = engine->direction_history[3];
      engine->direction_history[3] = direction;
    }
  }
  if (!deliberate_challenge && decision->phase_term_hz != 0.0)
    engine->phase_nonzero_application_count++;
  if (!deliberate_challenge && decision->phase_materially_influenced) {
    engine->phase_material_application_count++;
    if (engine->phase_material_application_count == 1u) {
      engine->state = OtisActiveHybridState::FirstPhaseTransaction;
      engine->first_checkpoint_response_passed = false;
      engine->first_checkpoint_observation_only = false;
      engine->reason = "first_phase_application_checkpoint_required";
    }
  } else if (!deliberate_challenge) {
    engine->frequency_only_application_count++;
    engine->reason = "application_confirmed_response_required";
  }
  return true;
}

}  // namespace

bool otis_active_hybrid_engine_decide(
    OtisActiveHybridEngine *engine,
    const OtisActiveHybridObservation *observation,
    OtisActiveHybridDecision *decision) {
  return decide_impl(engine, observation, false, 0u, decision);
}

bool otis_active_hybrid_engine_decide_at_ticks(
    OtisActiveHybridEngine *engine,
    const OtisActiveHybridObservation *observation,
    uint64_t observation_ticks, OtisActiveHybridDecision *decision) {
  return decide_impl(engine, observation, true, observation_ticks, decision);
}

bool otis_active_hybrid_engine_note_application(
    OtisActiveHybridEngine *engine,
    const OtisActiveHybridDecision *decision,
    uint16_t applied_code, uint32_t dac_epoch,
    bool downstream_consumers_exact) {
  return note_application_impl(engine, decision, applied_code, dac_epoch,
                               false, 0u, downstream_consumers_exact);
}

bool otis_active_hybrid_engine_note_application_at_ticks(
    OtisActiveHybridEngine *engine,
    const OtisActiveHybridDecision *decision,
    uint16_t applied_code, uint32_t dac_epoch, uint64_t application_ticks,
    bool downstream_consumers_exact) {
  return note_application_impl(engine, decision, applied_code, dac_epoch,
                               true, application_ticks,
                               downstream_consumers_exact);
}

bool otis_active_hybrid_engine_note_response(
    OtisActiveHybridEngine *engine,
    bool healthy_classification, bool predicted_sign_observed,
    bool exact_replay, bool support_fresh, bool applied_epoch_exact,
    bool observation_only) {
  if (engine == nullptr || !engine->transaction_outstanding) {
    if (engine != nullptr) fault(engine, "response_without_outstanding_application");
    return false;
  }
  const bool was_phase_material = engine->outstanding_phase_material;
  const bool was_deliberate_challenge =
      engine->outstanding_deliberate_challenge;
  engine->transaction_outstanding = false;
  engine->outstanding_phase_material = false;
  engine->outstanding_deliberate_challenge = false;
  if (!(healthy_classification &&
        (observation_only || predicted_sign_observed) &&
        exact_replay && support_fresh && applied_epoch_exact)) {
    fault(engine, "hybrid_response_wrong_or_checkpoint_evidence_invalid");
    return false;
  }
  if (was_deliberate_challenge) {
    engine->reason = "deliberate_reversal_challenge_response_observation_recorded";
  } else if (was_phase_material && engine->phase_material_application_count == 1u) {
    engine->first_checkpoint_response_passed = true;
    engine->first_checkpoint_observation_only = observation_only;
    engine->reason = observation_only
                         ? "first_phase_observation_recorded_tight_reacquisition_required"
                         : "first_phase_response_passed_tight_reacquisition_required";
  } else {
    engine->reason = observation_only ? "response_observation_recorded"
                                      : "response_passed";
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
