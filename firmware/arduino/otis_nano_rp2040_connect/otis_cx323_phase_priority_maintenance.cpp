#include "otis_cx323_phase_priority_maintenance.h"

#include <stddef.h>
#include <string.h>

namespace {

constexpr int64_t kPicocodesPerCode = 1000000000000ll;
constexpr int64_t kMaximumDebtPicocodes = 500000000000ll;
constexpr uint64_t kCaptureTicksPerSecond = 16000000ull;
constexpr uint64_t kConversionDenominator = 4680182727ull;
constexpr uint64_t kPlantGainNumerator = 173340101ull;
constexpr uint64_t kLegacyGainNumerator = 7211256926616129ull;
constexpr uint64_t kLegacyGainDenominator = 2500000000000ull;
constexpr OtisCx323Wide kConversionNumerator(
    33u, 16257445567584796672ull, false);
constexpr OtisCx323Wide kMaximumAbsoluteCentreUnits(18u, 36u, false);

struct LegacyLimitedDelta {
  int32_t delta;
  bool step_limited;
  bool range_clamped;
};

struct DecisionProjection {
  int32_t counterfactual_frequency_only_delta_codes = 0;
  bool phase_materially_influenced = false;
  bool step_limited = false;
  bool range_clamped = false;
  bool cadence_limited = false;
  bool count_limited = false;
  bool cumulative_budget_limited = false;
};

bool checked_add(OtisCx323Wide left, OtisCx323Wide right,
                 OtisCx323Wide *result) {
  return otis_cx323_wide_checked_add(left, right, result);
}

bool checked_multiply(OtisCx323Wide left, OtisCx323Wide right,
                      OtisCx323Wide *result) {
  return otis_cx323_wide_checked_multiply(left, right, result);
}

bool rounded_unsigned_ratio(OtisCx323Wide numerator,
                            OtisCx323Wide denominator,
                            OtisCx323Wide *rounded) {
  OtisCx323Wide quotient;
  OtisCx323Wide remainder;
  OtisCx323Wide half;
  OtisCx323Wide half_remainder;
  if (rounded == nullptr || numerator < 0 || denominator <= 0 ||
      !otis_cx323_wide_divide(numerator, denominator, &quotient, &remainder) ||
      !otis_cx323_wide_divide(denominator, OtisCx323Wide(2), &half,
                              &half_remainder))
    return false;
  if (half_remainder != 0 && !checked_add(half, OtisCx323Wide(1), &half))
    return false;
  if (remainder >= half)
    return checked_add(quotient, OtisCx323Wide(1), rounded);
  *rounded = quotient;
  return true;
}

bool identity_equal(const OtisCx323Identity &left,
                    const OtisCx323Identity &right) {
  return left.capture_session == right.capture_session &&
         left.applied_code == right.applied_code &&
         left.dac_epoch == right.dac_epoch &&
         left.phase_epoch == right.phase_epoch &&
         left.phase_valid == right.phase_valid &&
         left.selected_estimator_identity == right.selected_estimator_identity;
}

OtisCx323Identity identity_of(const OtisCx323Observation &observation) {
  return {
      observation.capture_session,
      observation.applied_code,
      observation.dac_epoch,
      observation.phase_epoch,
      observation.phase_valid,
      observation.selected_estimator_identity,
  };
}

void clear_pending_snapshot(OtisCx323Engine *engine) {
  engine->pending_decision_sequence = 0;
  engine->pending_requested_delta_codes = 0;
  engine->pending_requested_code = engine->applied_code;
  engine->pending_raw_combined_picocodes = 0;
  engine->pending_raw_fll_picocodes = 0;
  engine->pending_raw_pll_picocodes = 0;
  engine->pending_maintenance_request = false;
  engine->pending_observation_timestamp_s = 0;
  engine->pending_observation_timestamp_ticks = 0;
  engine->pending_counterfactual_frequency_only_delta_codes = 0;
  engine->pending_phase_materially_influenced = false;
  engine->pending_step_limited = false;
  engine->pending_range_clamped = false;
  engine->pending_cadence_limited = false;
  engine->pending_count_limited = false;
  engine->pending_cumulative_budget_limited = false;
}

void reset_maintenance(OtisCx323Engine *engine, bool preserve_debt) {
  if (!preserve_debt) engine->debt = {0, 0};
  engine->persistence_sign = 0;
  engine->persistence_count = 0;
  engine->persistence_identity_available = false;
  engine->persistence_identity = {};
  engine->last_closing_frontier_available = false;
  engine->last_closing_frontier = 0;
}

void fail_static(OtisCx323Engine *engine, const char *reason) {
  engine->fail_static_reason = reason;
  engine->last_reason = reason;
  engine->request_pending = false;
  engine->response_pending = false;
  clear_pending_snapshot(engine);
}

void clear_requalification_state(OtisCx323Engine *engine) {
  engine->metadata_requalified = false;
  engine->requalification_frontier_available = false;
  engine->requalification_frontier = 0;
  engine->requalification_window_count = 0;
  engine->requalification_last_closing_frontier_available = false;
  engine->requalification_last_closing_frontier = 0;
  engine->requalification_identity_available = false;
  engine->requalification_identity = {};
}

const char *advance_metadata_requalification(
    OtisCx323Engine *engine, const OtisCx323Observation &observation,
    const OtisCx323Identity &identity) {
  if (!engine->metadata_hold || !engine->metadata_requalified) return nullptr;
  if (!engine->requalification_frontier_available) {
    fail_static(engine, "metadata_requalification_frontier_missing");
    return engine->fail_static_reason;
  }
  if (observation.source_first_sequence < engine->requalification_frontier)
    return "metadata_requalification_frontier_hold";
  if (engine->requalification_last_closing_frontier_available &&
      observation.source_first_sequence <
          engine->requalification_last_closing_frontier)
    return "metadata_requalification_overlap_hold";
  const bool contiguous =
      engine->requalification_last_closing_frontier_available &&
      observation.source_first_sequence ==
          engine->requalification_last_closing_frontier &&
      engine->requalification_identity_available &&
      identity_equal(identity, engine->requalification_identity);
  engine->requalification_window_count =
      contiguous && engine->requalification_window_count < 2
          ? static_cast<uint8_t>(engine->requalification_window_count + 1)
          : static_cast<uint8_t>(1);
  engine->requalification_last_closing_frontier =
      observation.source_last_sequence;
  engine->requalification_last_closing_frontier_available = true;
  engine->requalification_identity = identity;
  engine->requalification_identity_available = true;
  if (engine->requalification_window_count < 2)
    return "metadata_requalification_window_hold";
  engine->metadata_hold = false;
  engine->metadata_requalified = false;
  engine->requalification_frontier_available = false;
  engine->requalification_frontier = 0;
  engine->requalification_last_closing_frontier_available = false;
  engine->requalification_last_closing_frontier = 0;
  engine->requalification_identity_available = false;
  engine->requalification_identity = {};
  return nullptr;
}

int8_t strict_sign(OtisCx323Wide lower, OtisCx323Wide upper) {
  return lower > 0 ? 1 : (upper < 0 ? -1 : 0);
}

bool phase_centre_units(int64_t relative_phase_cycles,
                        OtisCx323Wide *phase_centre) {
  if (phase_centre == nullptr) return false;
  OtisCx323Wide negated;
  if (!otis_cx323_wide_negate(OtisCx323Wide(relative_phase_cycles), &negated))
    return false;
  *phase_centre = negated < -36 ? -36 : (negated > 36 ? 36 : negated);
  return true;
}

bool centre_units(const OtisCx323Observation &observation,
                  OtisCx323Wide *frequency_centre,
                  OtisCx323Wide *phase_centre,
                  OtisCx323Wide *combined_centre) {
  if (frequency_centre == nullptr || phase_centre == nullptr ||
      combined_centre == nullptr)
    return false;
  if (!checked_multiply(OtisCx323Wide(-36),
                        OtisCx323Wide(
                            observation.accumulated_edge_error_counts),
                        frequency_centre))
    return false;
  if (!phase_centre_units(observation.relative_phase_cycles, phase_centre))
    return false;
  return checked_add(*frequency_centre, *phase_centre, combined_centre);
}

bool legacy_delta(OtisCx323Wide centre, const OtisCx323Engine &engine,
                  LegacyLimitedDelta *result) {
  if (result == nullptr) return false;
  OtisCx323Wide numerator = 0;
  OtisCx323Wide legacy_gain;
  if (!otis_cx323_wide_from_u64(kLegacyGainNumerator, &legacy_gain) ||
      !checked_multiply(centre, legacy_gain, &numerator))
    return false;
  OtisCx323Wide denominator;
  if (!otis_cx323_wide_from_u64(21600ull * kLegacyGainDenominator,
                                &denominator))
    return false;
  OtisCx323Wide rounded = 0;
  if (!otis_cx323_round_ratio(numerator, denominator, &rounded)) return false;
  const OtisCx323Wide limited = rounded < -engine.policy.maximum_step_codes
                                    ? OtisCx323Wide(
                                          -engine.policy.maximum_step_codes)
                                : (rounded > engine.policy.maximum_step_codes
                                       ? OtisCx323Wide(
                                             engine.policy.maximum_step_codes)
                                       : rounded);
  int64_t limited_i64 = 0;
  if (!otis_cx323_wide_to_i64(limited, &limited_i64)) return false;
  const int64_t requested_unclamped =
      static_cast<int64_t>(engine.applied_code) + limited_i64;
  const int32_t requested =
      requested_unclamped < engine.policy.minimum_code
          ? engine.policy.minimum_code
          : (requested_unclamped > engine.policy.maximum_code
                 ? engine.policy.maximum_code
                 : static_cast<int32_t>(requested_unclamped));
  result->delta = requested - engine.applied_code;
  result->step_limited = limited != rounded;
  result->range_clamped = requested_unclamped != requested;
  return true;
}

bool legacy_deltas(const OtisCx323Observation &observation,
                   const OtisCx323Engine &engine, bool phase_enabled,
                   LegacyLimitedDelta *combined_delta,
                   LegacyLimitedDelta *frequency_delta,
                   OtisCx323Wide *phase_centre) {
  OtisCx323Wide frequency = 0;
  OtisCx323Wide phase = 0;
  OtisCx323Wide combined = 0;
  if (!centre_units(observation, &frequency, &phase, &combined)) return false;
  if (!phase_enabled) {
    phase = 0;
    combined = frequency;
  }
  if (phase_centre != nullptr) *phase_centre = phase;
  return legacy_delta(combined, engine, combined_delta) &&
         legacy_delta(frequency, engine, frequency_delta);
}

int32_t no_zero_cross_cap(const OtisCx323Engine &engine,
                          OtisCx323Wide centre, int32_t code) {
  OtisCx323Wide lower;
  OtisCx323Wide upper;
  if (!otis_cx323_wide_checked_subtract(centre, OtisCx323Wide(18), &lower) ||
      !checked_add(centre, OtisCx323Wide(18), &upper))
    return 0;
  const int8_t sign = strict_sign(lower, upper);
  if (sign == 0) return 0;
  OtisCx323Wide nearest = lower;
  if (sign < 0 && !otis_cx323_wide_negate(upper, &nearest)) return 0;
  OtisCx323Wide numerator;
  if (!checked_multiply(nearest, OtisCx323Wide(kPicocodesPerCode),
                        &numerator))
    return 0;
  OtisCx323Wide quotient;
  OtisCx323Wide remainder;
  const OtisCx323Wide denominator(
      static_cast<int64_t>(21600ull * kPlantGainNumerator));
  if (!otis_cx323_wide_divide(numerator, denominator, &quotient, &remainder))
    return 0;
  uint64_t raw_cap = 0;
  int32_t cap = engine.policy.maximum_step_codes;
  if (quotient <= engine.policy.maximum_step_codes) {
    if (!otis_cx323_wide_to_u64(quotient, &raw_cap)) return 0;
    cap = static_cast<int32_t>(raw_cap);
  }
  const uint32_t remaining =
      engine.cumulative_movement_codes >=
              engine.policy.maximum_cumulative_movement_codes
          ? 0
          : engine.policy.maximum_cumulative_movement_codes -
                engine.cumulative_movement_codes;
  if (remaining < static_cast<uint32_t>(cap))
    cap = static_cast<int32_t>(remaining);
  const int32_t range_headroom = sign > 0 ? engine.policy.maximum_code - code
                                          : code - engine.policy.minimum_code;
  if (range_headroom < cap) cap = range_headroom;
  return cap < 0 ? 0 : cap;
}

void make_decision(const OtisCx323Engine &engine, const char *reason,
                   OtisCx323Decision *decision, int32_t delta = 0,
                   int32_t cap = 0, OtisCx323Wide raw = 0,
                   OtisCx323Wide fll = 0, OtisCx323Wide pll = 0,
                   bool maintenance_request = false,
                   DecisionProjection projection = {}) {
  *decision = {
      engine.decision_sequence,
      reason,
      delta,
      engine.applied_code + delta,
      cap,
      engine.persistence_count,
      raw,
      fll,
      pll,
      engine.debt.fll_picocodes + engine.debt.pll_picocodes,
      maintenance_request,
      engine.current_timestamp_ticks,
      projection.counterfactual_frequency_only_delta_codes,
      projection.phase_materially_influenced,
      projection.step_limited,
      projection.range_clamped,
      projection.cadence_limited,
      projection.count_limited,
      projection.cumulative_budget_limited,
  };
}

const char *chatter_reason(const OtisCx323Engine &engine, int32_t delta) {
  const int8_t direction = delta > 0 ? 1 : -1;
  if (engine.direction_count >= 3) {
    int reversals = 0;
    int8_t previous = engine.direction_history[0];
    for (uint8_t index = 1; index < 3; ++index) {
      if (previous != engine.direction_history[index]) ++reversals;
      previous = engine.direction_history[index];
    }
    if (previous != direction) ++reversals;
    if (reversals == 3) return "prospective_repeated_alternation";
  }
  const uint32_t movement =
      static_cast<uint32_t>(delta < 0 ? -delta : delta);
  const uint64_t path =
      static_cast<uint64_t>(engine.cumulative_movement_codes) + movement;
  const int64_t net_signed =
      static_cast<int64_t>(engine.applied_code) + delta -
      static_cast<int64_t>(engine.chatter_origin_code);
  const uint64_t net =
      static_cast<uint64_t>(net_signed < 0 ? -net_signed : net_signed);
  if (path >= 42 && 4 * net <= path)
    return "prospective_low_efficiency_path";
  return nullptr;
}

void remember_direction(OtisCx323Engine *engine, int32_t delta) {
  const int8_t direction = delta > 0 ? 1 : -1;
  if (engine->direction_count < 3) {
    engine->direction_history[engine->direction_count++] = direction;
    return;
  }
  engine->direction_history[0] = engine->direction_history[1];
  engine->direction_history[1] = engine->direction_history[2];
  engine->direction_history[2] = direction;
}

bool cadence_held(const OtisCx323Engine &engine,
                  const OtisCx323Observation &observation,
                  bool *timestamp_backward) {
  *timestamp_backward = false;
  if (!observation.cadence_eligible) return true;
  if (!engine.last_application_available) return false;
  if (observation.timestamp_ticks < engine.last_application_ticks) {
    *timestamp_backward = true;
    return true;
  }
  return observation.timestamp_ticks - engine.last_application_ticks <
         engine.policy.minimum_cadence_s * kCaptureTicksPerSecond;
}

bool propose_or_hold(OtisCx323Engine *engine,
                     const OtisCx323Observation &observation,
                     OtisCx323Decision *decision, int32_t delta,
                     const char *ready_reason, int32_t cap,
                     OtisCx323Wide raw, OtisCx323Wide fll,
                     OtisCx323Wide pll, bool enforce_phase_direction,
                     bool maintenance_request, bool cadence_already_checked,
                     DecisionProjection projection) {
  bool backward = false;
  if (!cadence_already_checked && cadence_held(*engine, observation, &backward)) {
    if (backward) {
      fail_static(engine, "observation_timestamp_backward");
      make_decision(*engine, engine->last_reason, decision);
      return true;
    }
    engine->last_reason = "cadence_hold";
    projection.cadence_limited = true;
    make_decision(*engine, engine->last_reason, decision, 0, cap, raw, fll,
                  pll, false, projection);
    return true;
  }
  if (delta != 0 && enforce_phase_direction && pll != 0 &&
      ((delta > 0) != (pll > 0))) {
    engine->last_reason = "phase_direction_coherence_hold";
    make_decision(*engine, engine->last_reason, decision, 0, cap, raw, fll,
                  pll, false, projection);
    return true;
  }
  if (delta == 0) {
    engine->last_reason = "zero_rounded_or_range_hold";
    make_decision(*engine, engine->last_reason, decision, 0, cap, raw, fll,
                  pll, false, projection);
    return true;
  }
  if (engine->application_count >= engine->policy.maximum_applications) {
    engine->last_reason = "global_application_budget_hold";
    projection.count_limited = true;
    make_decision(*engine, engine->last_reason, decision, 0, cap, raw, fll,
                  pll, false, projection);
    return true;
  }
  const uint32_t movement =
      static_cast<uint32_t>(delta < 0 ? -delta : delta);
  if (engine->cumulative_movement_codes >
          engine->policy.maximum_cumulative_movement_codes ||
      movement > engine->policy.maximum_cumulative_movement_codes -
                     engine->cumulative_movement_codes) {
    engine->last_reason = "global_cumulative_movement_budget_hold";
    projection.cumulative_budget_limited = true;
    make_decision(*engine, engine->last_reason, decision, 0, cap, raw, fll,
                  pll, false, projection);
    return true;
  }
  const char *chatter = chatter_reason(*engine, delta);
  if (chatter != nullptr) {
    fail_static(engine, chatter);
    make_decision(*engine, chatter, decision, 0, cap, raw, fll, pll, false,
                  projection);
    return true;
  }
  engine->request_pending = true;
  engine->last_reason = ready_reason;
  make_decision(*engine, ready_reason, decision, delta, cap, raw, fll, pll,
                maintenance_request, projection);
  engine->pending_decision_sequence = decision->decision_sequence;
  engine->pending_requested_delta_codes = decision->requested_delta_codes;
  engine->pending_requested_code = decision->requested_code;
  engine->pending_raw_combined_picocodes = raw;
  engine->pending_raw_fll_picocodes = fll;
  engine->pending_raw_pll_picocodes = pll;
  engine->pending_maintenance_request = maintenance_request;
  engine->pending_observation_timestamp_s = observation.timestamp_s;
  engine->pending_observation_timestamp_ticks = observation.timestamp_ticks;
  engine->pending_counterfactual_frequency_only_delta_codes =
      decision->counterfactual_frequency_only_delta_codes;
  engine->pending_phase_materially_influenced =
      decision->phase_materially_influenced;
  engine->pending_step_limited = decision->step_limited;
  engine->pending_range_clamped = decision->range_clamped;
  engine->pending_cadence_limited = decision->cadence_limited;
  engine->pending_count_limited = decision->count_limited;
  engine->pending_cumulative_budget_limited =
      decision->cumulative_budget_limited;
  return true;
}

bool legacy_request(OtisCx323Engine *engine,
                    const OtisCx323Observation &observation,
                    OtisCx323Decision *decision, int32_t delta,
                    const char *reason, OtisCx323Wide phase_term,
                    bool reset_debt, bool enforce_phase_direction,
                    DecisionProjection projection) {
  reset_maintenance(engine, !reset_debt);
  return propose_or_hold(engine, observation, decision, delta, reason,
                         engine->policy.maximum_step_codes, 0, 0,
                         phase_term, enforce_phase_direction, false, false,
                         projection);
}

// Compute round(residual_magnitude*weight/total_weight) without ever forming
// the possibly 167-bit product.  The loop is bounded by the 39-bit debt cap.
bool weighted_residual(uint64_t residual_magnitude, OtisCx323Wide weight,
                       OtisCx323Wide total_weight, uint64_t *rounded) {
  if (rounded == nullptr || total_weight == 0 || weight < 0 ||
      weight > total_weight)
    return false;
  uint64_t quotient = 0;
  OtisCx323Wide remainder;
  int highest_bit = -1;
  for (int bit = 63; bit >= 0; --bit) {
    if ((residual_magnitude >> bit) != 0) {
      highest_bit = bit;
      break;
    }
  }
  for (int bit = highest_bit; bit >= 0; --bit) {
    if (quotient > UINT64_MAX / 2u) return false;
    quotient <<= 1u;
    if (!checked_add(remainder, remainder, &remainder)) return false;
    if (((residual_magnitude >> bit) & 1u) != 0u &&
        !checked_add(remainder, weight, &remainder))
      return false;
    while (remainder >= total_weight) {
      if (!otis_cx323_wide_checked_subtract(remainder, total_weight,
                                            &remainder))
        return false;
      ++quotient;
    }
  }
  OtisCx323Wide half_ceiling;
  OtisCx323Wide half_remainder;
  if (!otis_cx323_wide_divide(total_weight, OtisCx323Wide(2),
                              &half_ceiling, &half_remainder))
    return false;
  if (half_remainder != 0 &&
      !checked_add(half_ceiling, OtisCx323Wide(1), &half_ceiling))
    return false;
  if (remainder >= half_ceiling) ++quotient;
  *rounded = quotient;
  return true;
}

}  // namespace

OtisCx323Policy otis_cx323_default_policy() {
  return {
      21,
      43008,
      43776,
      1800,
      144,
      3024,
      43085,
  };
}

bool otis_cx323_round_ratio(OtisCx323Wide numerator,
                            OtisCx323Wide denominator,
                            OtisCx323Wide *rounded) {
  if (rounded == nullptr || denominator <= 0) return false;
  OtisCx323Wide magnitude;
  OtisCx323Wide result;
  if (!otis_cx323_wide_absolute(numerator, &magnitude) ||
      !rounded_unsigned_ratio(magnitude, denominator, &result))
    return false;
  return numerator < 0 ? otis_cx323_wide_negate(result, rounded)
                       : (*rounded = result, true);
}

bool otis_cx323_centre_to_picocodes(OtisCx323Wide centre_units,
                                    OtisCx323Wide *picocodes) {
  if (picocodes == nullptr ||
      !otis_cx323_wide_valid(centre_units))
    return false;
  OtisCx323Wide input;
  if (!otis_cx323_wide_absolute(centre_units, &input) ||
      input > kMaximumAbsoluteCentreUnits)
    return false;
  const OtisCx323Wide denominator(
      static_cast<int64_t>(kConversionDenominator));
  OtisCx323Wide quotient;
  OtisCx323Wide remainder;
  OtisCx323Wide quotient_term;
  OtisCx323Wide remainder_numerator;
  OtisCx323Wide remainder_term;
  OtisCx323Wide result;
  if (!otis_cx323_wide_divide(input, denominator, &quotient, &remainder) ||
      !checked_multiply(quotient, kConversionNumerator, &quotient_term) ||
      !checked_multiply(remainder, kConversionNumerator,
                        &remainder_numerator) ||
      !rounded_unsigned_ratio(remainder_numerator, denominator,
                              &remainder_term) ||
      !checked_add(quotient_term, remainder_term, &result))
    return false;
  return centre_units < 0 ? otis_cx323_wide_negate(result, picocodes)
                          : (*picocodes = result, true);
}

bool otis_cx323_engine_init(OtisCx323Engine *engine,
                            const OtisCx323Policy *policy,
                            int32_t setup_applied_code,
                            uint64_t setup_dac_epoch) {
  if (engine == nullptr || policy == nullptr ||
      policy->maximum_step_codes <= 0 ||
      policy->minimum_code >= policy->maximum_code ||
      policy->minimum_cadence_s == 0 ||
      policy->minimum_cadence_s > UINT64_MAX / kCaptureTicksPerSecond ||
      policy->maximum_applications == 0 ||
      policy->maximum_cumulative_movement_codes == 0 ||
      setup_applied_code < policy->minimum_code ||
      setup_applied_code > policy->maximum_code || setup_dac_epoch == 0)
    return false;
  *engine = {};
  engine->policy = *policy;
  engine->applied_code = setup_applied_code;
  engine->dac_epoch = setup_dac_epoch;
  engine->chatter_origin_code = setup_applied_code;
  engine->last_reason = "initialized";
  clear_pending_snapshot(engine);
  return true;
}

bool otis_cx323_engine_bind_exact_setup_application(
    OtisCx323Engine *engine, uint64_t setup_application_ticks) {
  if (engine == nullptr || setup_application_ticks == 0u ||
      engine->last_application_available || engine->request_pending ||
      engine->response_pending || engine->application_count != 0u ||
      engine->dac_epoch == 0u)
    return false;
  const uint64_t setup_application_s =
      setup_application_ticks / kCaptureTicksPerSecond;
  engine->last_application_s = setup_application_s;
  engine->last_application_ticks = setup_application_ticks;
  engine->last_application_available = true;
  return true;
}

bool otis_cx323_engine_decide(OtisCx323Engine *engine,
                              const OtisCx323Observation *observation,
                              OtisCx323Decision *decision) {
  if (engine == nullptr || observation == nullptr || decision == nullptr)
    return false;
  ++engine->decision_sequence;
  engine->current_timestamp_s = observation->timestamp_s;
  engine->current_timestamp_ticks = observation->timestamp_ticks;
  if (engine->fail_static_reason != nullptr) {
    make_decision(*engine, engine->fail_static_reason, decision);
    return true;
  }
  if (observation->timestamp_s !=
      observation->timestamp_ticks / kCaptureTicksPerSecond) {
    fail_static(engine, "observation_timestamp_domain_mismatch");
    make_decision(*engine, engine->last_reason, decision);
    return true;
  }
  if (observation->source_last_sequence <=
      observation->source_first_sequence) {
    fail_static(engine, "invalid_selected_window_frontier");
    make_decision(*engine, engine->last_reason, decision);
    return true;
  }
  if (engine->request_pending) {
    engine->last_reason = "request_pending_hold";
    make_decision(*engine, engine->last_reason, decision);
    return true;
  }
  if (engine->response_pending) {
    engine->last_reason = "response_pending_hold";
    make_decision(*engine, engine->last_reason, decision);
    return true;
  }
  if (!observation->metadata_qualified) {
    if (!engine->metadata_hold || engine->metadata_requalified) {
      engine->metadata_hold = true;
      clear_requalification_state(engine);
      reset_maintenance(engine, true);
    }
    engine->last_reason = "metadata_hold";
    make_decision(*engine, engine->last_reason, decision);
    return true;
  }
  if (engine->metadata_hold && !engine->metadata_requalified) {
    engine->last_reason = "metadata_hold";
    make_decision(*engine, engine->last_reason, decision);
    return true;
  }
  if (observation->applied_code != engine->applied_code ||
      observation->dac_epoch != engine->dac_epoch) {
    fail_static(engine,
                "unknown_or_contradictory_application_or_DAC_epoch");
    make_decision(*engine, engine->last_reason, decision);
    return true;
  }
  const OtisCx323Identity identity = identity_of(*observation);
  if (engine->persistence_identity_available &&
      !identity_equal(identity, engine->persistence_identity)) {
    const OtisCx323Identity old = engine->persistence_identity;
    if (identity.capture_session != old.capture_session ||
        identity.selected_estimator_identity !=
            old.selected_estimator_identity) {
      reset_maintenance(engine, false);
    } else if (identity.applied_code != old.applied_code ||
               identity.dac_epoch != old.dac_epoch) {
      fail_static(engine,
                  "unknown_or_contradictory_application_or_DAC_epoch");
      make_decision(*engine, engine->last_reason, decision);
      return true;
    } else if (identity.phase_epoch != old.phase_epoch ||
               identity.phase_valid != old.phase_valid) {
      engine->debt.pll_picocodes = 0;
      reset_maintenance(engine, true);
    }
  }
  if (!observation->authority_valid) {
    reset_maintenance(engine, true);
    engine->last_reason = "reference_invalidity_or_authority_hold";
    make_decision(*engine, engine->last_reason, decision);
    return true;
  }
  if (!observation->settled) {
    reset_maintenance(engine, true);
    engine->last_reason = "settling_hold";
    make_decision(*engine, engine->last_reason, decision);
    return true;
  }
  const char *metadata_requalification_hold =
      advance_metadata_requalification(engine, *observation, identity);
  if (engine->fail_static_reason != nullptr) {
    make_decision(*engine, engine->fail_static_reason, decision);
    return true;
  }
  if (metadata_requalification_hold != nullptr &&
      (strcmp(metadata_requalification_hold,
              "metadata_requalification_frontier_hold") == 0 ||
       strcmp(metadata_requalification_hold,
              "metadata_requalification_overlap_hold") == 0)) {
    engine->last_reason = metadata_requalification_hold;
    make_decision(*engine, engine->last_reason, decision);
    return true;
  }

  LegacyLimitedDelta combined_legacy = {};
  LegacyLimitedDelta frequency_legacy = {};
  OtisCx323Wide phase_centre = 0;
  if (!observation->phase_valid) {
    engine->debt.pll_picocodes = 0;
    reset_maintenance(engine, true);
    if (!legacy_deltas(*observation, *engine, false, &combined_legacy,
                       &frequency_legacy, &phase_centre)) {
      fail_static(engine, "maintenance_arithmetic_overflow");
      make_decision(*engine, engine->last_reason, decision);
      return true;
    }
    const DecisionProjection projection = {
        frequency_legacy.delta,
        false,
        combined_legacy.step_limited,
        combined_legacy.range_clamped,
    };
    if (metadata_requalification_hold != nullptr) {
      engine->last_reason = metadata_requalification_hold;
      make_decision(*engine, engine->last_reason, decision, 0, 0, 0, 0, 0,
                    false, projection);
      return true;
    }
    return legacy_request(
        engine, *observation, decision, frequency_legacy.delta,
        "phase_degraded_frequency_only_request_ready", 0, false, false,
        projection);
  }

  if (!legacy_deltas(*observation, *engine, true, &combined_legacy,
                     &frequency_legacy, &phase_centre)) {
    fail_static(engine, "maintenance_arithmetic_overflow");
    make_decision(*engine, engine->last_reason, decision);
    return true;
  }
  const bool phase_material =
      combined_legacy.delta != frequency_legacy.delta;
  const DecisionProjection projection = {
      frequency_legacy.delta,
      phase_material,
      combined_legacy.step_limited,
      combined_legacy.range_clamped,
  };
  if (!observation->tight_inside) {
    if (metadata_requalification_hold != nullptr) {
      reset_maintenance(engine, false);
      engine->last_reason = metadata_requalification_hold;
      make_decision(*engine, engine->last_reason, decision, 0, 0, 0, 0, 0,
                    false, projection);
      return true;
    }
    return legacy_request(engine, *observation, decision,
                          combined_legacy.delta,
                          "outside_tight_legacy_request_ready", phase_centre,
                          true, true, projection);
  }
  if (phase_material) {
    if (metadata_requalification_hold != nullptr) {
      reset_maintenance(engine, false);
      engine->last_reason = metadata_requalification_hold;
      make_decision(*engine, engine->last_reason, decision, 0, 0, 0, 0, 0,
                    false, projection);
      return true;
    }
    return legacy_request(engine, *observation, decision,
                          combined_legacy.delta,
                          "phase_material_legacy_request_ready", phase_centre,
                          true, true, projection);
  }

  OtisCx323Wide frequency_centre = 0;
  OtisCx323Wide combined_centre = 0;
  if (!centre_units(*observation, &frequency_centre, &phase_centre,
                    &combined_centre)) {
    fail_static(engine, "maintenance_arithmetic_overflow");
    make_decision(*engine, engine->last_reason, decision);
    return true;
  }
  OtisCx323Wide lower;
  OtisCx323Wide upper;
  if (!otis_cx323_wide_checked_subtract(combined_centre, OtisCx323Wide(18),
                                        &lower) ||
      !checked_add(combined_centre, OtisCx323Wide(18), &upper)) {
    fail_static(engine, "maintenance_arithmetic_overflow");
    make_decision(*engine, engine->last_reason, decision);
    return true;
  }
  const int8_t sign = strict_sign(lower, upper);

  if (engine->last_closing_frontier_available) {
    if (observation->source_first_sequence <
        engine->last_closing_frontier) {
      engine->last_reason = "source_overlap_hold";
      make_decision(*engine, engine->last_reason, decision, 0, 0, 0, 0, 0,
                    false, projection);
      return true;
    }
    if (observation->source_first_sequence >
        engine->last_closing_frontier) {
      if (sign == 0 || (engine->persistence_count != 0 &&
                        sign != engine->persistence_sign))
        reset_maintenance(engine, false);
      engine->persistence_count = sign == 0 ? 0 : 1;
      engine->persistence_sign = sign;
      engine->persistence_identity = identity;
      engine->persistence_identity_available = sign != 0;
      engine->last_closing_frontier = observation->source_last_sequence;
      engine->last_closing_frontier_available = sign != 0;
      engine->last_reason = sign == 0 ? "zero_containing_interval"
                                      : "source_gap_persistence_restart";
      make_decision(*engine, engine->last_reason, decision, 0, 0, 0, 0, 0,
                    false, projection);
      return true;
    }
  }
  if (sign == 0) {
    reset_maintenance(engine, false);
    engine->last_reason = "zero_containing_interval";
    make_decision(*engine, engine->last_reason, decision, 0, 0, 0, 0, 0,
                  false, projection);
    return true;
  }
  if (engine->persistence_count != 0 && sign != engine->persistence_sign)
    reset_maintenance(engine, false);
  const bool same = engine->persistence_count != 0 &&
                    engine->persistence_identity_available &&
                    identity_equal(identity, engine->persistence_identity) &&
                    sign == engine->persistence_sign;
  engine->persistence_count =
      same ? (engine->persistence_count < 2
                  ? static_cast<uint8_t>(engine->persistence_count + 1)
                  : static_cast<uint8_t>(2))
           : static_cast<uint8_t>(1);
  engine->persistence_sign = sign;
  engine->persistence_identity = identity;
  engine->persistence_identity_available = true;
  engine->last_closing_frontier = observation->source_last_sequence;
  engine->last_closing_frontier_available = true;
  const int32_t cap =
      no_zero_cross_cap(*engine, combined_centre, observation->applied_code);
  if (metadata_requalification_hold != nullptr) {
    engine->last_reason = metadata_requalification_hold;
    make_decision(*engine, engine->last_reason, decision, 0, cap, 0, 0, 0,
                  false, projection);
    return true;
  }
  bool backward = false;
  if (cadence_held(*engine, *observation, &backward)) {
    if (backward) {
      fail_static(engine, "observation_timestamp_backward");
      make_decision(*engine, engine->last_reason, decision);
      return true;
    }
    engine->last_reason = "cadence_hold";
    DecisionProjection cadence_projection = projection;
    cadence_projection.cadence_limited = true;
    make_decision(*engine, engine->last_reason, decision, 0, cap, 0, 0, 0,
                  false, cadence_projection);
    return true;
  }
  if (engine->persistence_count < 2) {
    engine->last_reason = "persistence_first_interval_hold";
    make_decision(*engine, engine->last_reason, decision, 0, cap, 0, 0, 0,
                  false, projection);
    return true;
  }

  OtisCx323Wide raw = 0;
  OtisCx323Wide fll = 0;
  if (!otis_cx323_centre_to_picocodes(combined_centre, &raw) ||
      !otis_cx323_centre_to_picocodes(frequency_centre, &fll)) {
    fail_static(engine, "maintenance_arithmetic_overflow");
    make_decision(*engine, engine->last_reason, decision);
    return true;
  }
  OtisCx323Wide pll;
  if (!otis_cx323_wide_checked_subtract(raw, fll, &pll)) {
    fail_static(engine, "maintenance_arithmetic_overflow");
    make_decision(*engine, engine->last_reason, decision);
    return true;
  }
  OtisCx323Wide total = 0;
  if (!checked_add(raw, engine->debt.fll_picocodes, &total) ||
      !checked_add(total, engine->debt.pll_picocodes, &total)) {
    fail_static(engine, "maintenance_arithmetic_overflow");
    make_decision(*engine, engine->last_reason, decision);
    return true;
  }
  OtisCx323Wide rounded = 0;
  if (!otis_cx323_round_ratio(total, kPicocodesPerCode, &rounded)) {
    fail_static(engine, "maintenance_arithmetic_overflow");
    make_decision(*engine, engine->last_reason, decision);
    return true;
  }
  int32_t delta = 0;
  if (rounded < -cap) {
    delta = -cap;
  } else if (rounded > cap) {
    delta = cap;
  } else {
    int64_t rounded_i64 = 0;
    if (!otis_cx323_wide_to_i64(rounded, &rounded_i64)) {
      fail_static(engine, "maintenance_arithmetic_overflow");
      make_decision(*engine, engine->last_reason, decision);
      return true;
    }
    delta = static_cast<int32_t>(rounded_i64);
  }
  return propose_or_hold(engine, *observation, decision, delta,
                         "maintenance_request_ready", cap, raw, fll, pll,
                         true, true, true, projection);
}

bool otis_cx323_engine_reject_or_expire_request(OtisCx323Engine *engine) {
  if (engine == nullptr || !engine->request_pending ||
      engine->response_pending) {
    if (engine != nullptr)
      fail_static(engine, "invalid_request_rejection_transition");
    return false;
  }
  engine->request_pending = false;
  clear_pending_snapshot(engine);
  engine->last_reason = "request_rejected_or_expired";
  return true;
}

bool otis_cx323_engine_note_application_and_first_consumer(
    OtisCx323Engine *engine, const OtisCx323Decision *decision,
    int32_t actual_applied_code, uint64_t actual_dac_epoch,
    bool first_consumer_exact) {
  if (engine == nullptr || decision == nullptr) return false;
  const bool exact_pending =
      engine->request_pending && !engine->response_pending &&
      decision->decision_sequence == engine->pending_decision_sequence &&
      decision->requested_delta_codes ==
          engine->pending_requested_delta_codes &&
      decision->requested_code == engine->pending_requested_code &&
      decision->raw_combined_picocodes ==
          engine->pending_raw_combined_picocodes &&
      decision->raw_fll_picocodes == engine->pending_raw_fll_picocodes &&
      decision->raw_pll_picocodes == engine->pending_raw_pll_picocodes &&
      decision->maintenance_request == engine->pending_maintenance_request &&
      decision->decision_timestamp_ticks ==
          engine->pending_observation_timestamp_ticks &&
      decision->counterfactual_frequency_only_delta_codes ==
          engine->pending_counterfactual_frequency_only_delta_codes &&
      decision->phase_materially_influenced ==
          engine->pending_phase_materially_influenced &&
      decision->step_limited == engine->pending_step_limited &&
      decision->range_clamped == engine->pending_range_clamped &&
      decision->cadence_limited == engine->pending_cadence_limited &&
      decision->count_limited == engine->pending_count_limited &&
      decision->cumulative_budget_limited ==
          engine->pending_cumulative_budget_limited;
  if (!exact_pending || decision->requested_delta_codes == 0) {
    fail_static(engine, "invalid_or_unexpected_application");
    return false;
  }
  if (!first_consumer_exact ||
      actual_applied_code != engine->pending_requested_code ||
      actual_dac_epoch != engine->dac_epoch + 1) {
    fail_static(engine, "application_without_exact_first_consumer");
    return false;
  }

  int64_t residual = 0;
  if (engine->pending_maintenance_request) {
    OtisCx323Wide total = 0;
    if (!checked_add(engine->pending_raw_combined_picocodes,
                     engine->debt.fll_picocodes, &total) ||
        !checked_add(total, engine->debt.pll_picocodes, &total)) {
      fail_static(engine, "maintenance_arithmetic_overflow");
      return false;
    }
    OtisCx323Wide applied;
    OtisCx323Wide raw_residual;
    if (!checked_multiply(
            OtisCx323Wide(engine->pending_requested_delta_codes),
            OtisCx323Wide(kPicocodesPerCode), &applied) ||
        !otis_cx323_wide_checked_subtract(total, applied, &raw_residual)) {
      fail_static(engine, "maintenance_arithmetic_overflow");
      return false;
    }
    int64_t raw_residual_i64 = 0;
    residual = raw_residual < -kMaximumDebtPicocodes
                   ? -kMaximumDebtPicocodes
                   : (raw_residual > kMaximumDebtPicocodes
                          ? kMaximumDebtPicocodes
                          : (otis_cx323_wide_to_i64(raw_residual,
                                                   &raw_residual_i64)
                                 ? raw_residual_i64
                                 : 0));
    if (raw_residual >= -kMaximumDebtPicocodes &&
        raw_residual <= kMaximumDebtPicocodes &&
        !otis_cx323_wide_to_i64(raw_residual, &raw_residual_i64)) {
      fail_static(engine, "maintenance_arithmetic_overflow");
      return false;
    }

    OtisCx323Wide fll_candidate = 0;
    OtisCx323Wide pll_candidate = 0;
    if (!checked_add(engine->pending_raw_fll_picocodes,
                     engine->debt.fll_picocodes, &fll_candidate) ||
        !checked_add(engine->pending_raw_pll_picocodes,
                     engine->debt.pll_picocodes, &pll_candidate)) {
      fail_static(engine, "maintenance_arithmetic_overflow");
      return false;
    }
    OtisCx323Wide fll_weight;
    OtisCx323Wide pll_weight;
    if (!otis_cx323_wide_absolute(fll_candidate, &fll_weight) ||
        !otis_cx323_wide_absolute(pll_candidate, &pll_weight)) {
      fail_static(engine, "maintenance_arithmetic_overflow");
      return false;
    }
    if (fll_weight == 0 && pll_weight == 0) {
      engine->debt = {residual, 0};
    } else {
      OtisCx323Wide total_weight;
      if (!checked_add(fll_weight, pll_weight, &total_weight)) {
        fail_static(engine, "maintenance_arithmetic_overflow");
        return false;
      }
      uint64_t fll_magnitude = 0;
      const uint64_t residual_magnitude =
          residual < 0 ? static_cast<uint64_t>(0u) -
                             static_cast<uint64_t>(residual)
                       : static_cast<uint64_t>(residual);
      if (!weighted_residual(
              residual_magnitude, fll_weight, total_weight,
              &fll_magnitude) ||
          fll_magnitude > static_cast<uint64_t>(kMaximumDebtPicocodes)) {
        fail_static(engine, "maintenance_arithmetic_overflow");
        return false;
      }
      const int64_t fll_debt = residual < 0
                                   ? -static_cast<int64_t>(fll_magnitude)
                                   : static_cast<int64_t>(fll_magnitude);
      engine->debt = {fll_debt, residual - fll_debt};
    }
  } else {
    engine->debt = {0, 0};
  }
  if (engine->debt.fll_picocodes + engine->debt.pll_picocodes != residual) {
    fail_static(engine, "debt_tag_sum_invariant_failure");
    return false;
  }

  engine->applied_code = actual_applied_code;
  engine->dac_epoch = actual_dac_epoch;
  ++engine->application_count;
  engine->cumulative_movement_codes += static_cast<uint32_t>(
      engine->pending_requested_delta_codes < 0
          ? -engine->pending_requested_delta_codes
          : engine->pending_requested_delta_codes);
  engine->last_application_available = true;
  engine->last_application_s = engine->pending_observation_timestamp_s;
  engine->last_application_ticks = engine->pending_observation_timestamp_ticks;
  remember_direction(engine, engine->pending_requested_delta_codes);
  engine->request_pending = false;
  engine->response_pending = true;
  clear_pending_snapshot(engine);
  reset_maintenance(engine, true);
  engine->last_reason = "application_and_first_consumer_committed";
  return true;
}

bool otis_cx323_engine_complete_response(OtisCx323Engine *engine,
                                         bool fresh_exact) {
  if (engine == nullptr || !engine->response_pending || !fresh_exact)
    return false;
  engine->response_pending = false;
  engine->last_reason = "response_completed";
  return true;
}

bool otis_cx323_engine_enter_metadata_hold(OtisCx323Engine *engine) {
  if (engine == nullptr || engine->request_pending) return false;
  engine->metadata_hold = true;
  clear_requalification_state(engine);
  reset_maintenance(engine, true);
  engine->last_reason = "metadata_hold";
  return true;
}

bool otis_cx323_engine_requalify_metadata(OtisCx323Engine *engine,
                                          uint64_t evidence_frontier) {
  if (engine == nullptr || !engine->metadata_hold ||
      engine->request_pending || engine->response_pending ||
      evidence_frontier == 0)
    return false;
  engine->metadata_requalified = true;
  engine->requalification_frontier_available = true;
  engine->requalification_frontier = evidence_frontier;
  engine->requalification_window_count = 0;
  engine->requalification_last_closing_frontier_available = false;
  engine->requalification_last_closing_frontier = 0;
  engine->requalification_identity_available = false;
  engine->requalification_identity = {};
  reset_maintenance(engine, true);
  engine->last_reason = "metadata_requalified";
  return true;
}

bool otis_cx323_engine_new_policy_activation(OtisCx323Engine *engine) {
  if (engine == nullptr) return false;
  if (engine->request_pending || engine->response_pending) {
    fail_static(engine,
                "new_policy_activation_with_outstanding_transaction");
    return false;
  }
  reset_maintenance(engine, false);
  engine->last_reason = "new_policy_activation";
  return true;
}
