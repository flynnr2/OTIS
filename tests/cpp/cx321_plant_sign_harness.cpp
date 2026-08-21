#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "otis_cx321_plant_sign.h"
#include "otis_timebase_math.h"

namespace {

constexpr uint64_t kSecond = OTIS_CX321_TIMER0_TICKS_PER_SECOND;

OtisCx321PlantSignEstimate window(
    OtisCx321PlantSignAccumulator *accumulator, uint64_t first_open,
    uint32_t first_closing_sequence, int32_t error_counts,
    uint64_t interval_ticks = kSecond) {
  OtisCx321PlantSignEstimate result = {};
  for (uint16_t index = 0u; index < 1500u; ++index) {
    const uint64_t open =
        first_open + static_cast<uint64_t>(index) * interval_ticks;
    const uint64_t close = open + interval_ticks;
    const int64_t adjusted = index == 0u ? error_counts : 0;
    const uint32_t count = static_cast<uint32_t>(
        static_cast<int64_t>(OTIS_CX321_NOMINAL_COUNT_PER_INTERVAL) + adjusted);
    const bool produced = otis_cx321_plant_sign_accumulator_on_interval(
        accumulator, open, close, first_closing_sequence + index, count,
        accumulator->dac_epoch, accumulator->capture_session, true, &result);
    assert(produced == (index == 1499u));
  }
  assert(result.valid);
  assert(result.signed_error_counts == error_counts);
  return result;
}

OtisCx321PlantSignEngine qualified_engine(
    int32_t response_counts,
    uint64_t acknowledgement_delay_ticks = kSecond + 123u,
    uint64_t interval_ticks = kSecond) {
  const uint64_t setup_ticks = 100u * kSecond;
  OtisCx321PlantSignAccumulator pre = {};
  otis_cx321_plant_sign_accumulator_init(&pre, setup_ticks, 1u, 1u);
  const uint64_t aligned_open = setup_ticks + 900u * kSecond;
  const auto pre1 = window(&pre, aligned_open, 1001u, 2, interval_ticks);
  const auto pre2 = window(
      &pre, aligned_open + 1500u * interval_ticks, 2501u, 2,
      interval_ticks);

  OtisCx321PlantSignEngine engine = {};
  otis_cx321_plant_sign_engine_init(&engine);
  OtisCx321PlantSignDecision decision = {};
  assert(!otis_cx321_plant_sign_engine_on_pre_estimate(
      &engine, &pre1, 0xA83Cu, 1u, 0u, true, true, &decision));
  assert(otis_cx321_plant_sign_engine_on_pre_estimate(
      &engine, &pre2, 0xA83Cu, 1u, 0u, true, true, &decision));
  assert(decision.request_ready);
  assert(decision.requested_delta_codes == -21);
  assert(decision.requested_code == 0xA827u);

  const uint64_t application_ticks = 5000u * kSecond;
  assert(otis_cx321_plant_sign_engine_note_application(
      &engine, 7u, 1u, 0xA827u, 2u, application_ticks, true));
  OtisCx321PlantSignAccumulator post = {};
  otis_cx321_plant_sign_accumulator_init(&post, application_ticks, 2u, 1u);
  const int32_t post_error = 2 + response_counts;
  const auto post_result = window(
      &post, application_ticks + 901u * kSecond, 7001u, post_error,
      interval_ticks);
  OtisCx321PlantSignResponse response = {};
  const bool passed = otis_cx321_plant_sign_engine_on_response(
      &engine, &post_result, true, true, &response);
  assert(passed == (response_counts <= -3 && response_counts >= -14));
  if (passed) {
    assert(response.response_counts == response_counts);
    const bool acknowledged =
        otis_cx321_plant_sign_engine_acknowledge_response(
        &engine, 7u, 1u, 2u, post_result.last_sequence, response_counts,
        post_result.close_ticks + acknowledgement_delay_ticks, true);
    assert(acknowledged ==
           (acknowledgement_delay_ticks <= 30u * kSecond));
  }
  return engine;
}

OtisActiveHybridObservation natural_observation(uint32_t timestamp_s,
                                                uint16_t code,
                                                uint32_t dac_epoch) {
  return {
      timestamp_s, 1u, timestamp_s - 599u, timestamp_s, dac_epoch, code,
      0.0, 0, "TIGHT_INSIDE", 1u, 1u, -24, dac_epoch, code,
      true, true, false, true, true, true, false, false,
  };
}

OtisCx321PlantSignEngine second_pre_gate(bool sequence_contiguous,
                                         bool totals_equal,
                                         bool natural_tight_inside,
                                         int32_t second_error = 2) {
  const uint64_t setup_ticks = 100u * kSecond;
  OtisCx321PlantSignAccumulator accumulator = {};
  otis_cx321_plant_sign_accumulator_init(
      &accumulator, setup_ticks, 1u, 1u);
  const uint64_t aligned_open = setup_ticks + 900u * kSecond;
  const auto first = window(&accumulator, aligned_open, 1001u, 2);
  auto second = window(
      &accumulator, aligned_open + 1500u * kSecond, 2501u,
      second_error);
  if (!sequence_contiguous) {
    second.first_sequence++;
    second.last_sequence++;
  }
  if (!totals_equal) {
    second.total_count++;
    second.signed_error_counts++;
  }
  OtisCx321PlantSignEngine engine = {};
  otis_cx321_plant_sign_engine_init(&engine);
  OtisCx321PlantSignDecision decision = {};
  assert(!otis_cx321_plant_sign_engine_on_pre_estimate(
      &engine, &first, 0xA83Cu, 1u, 0u, true, true, &decision));
  assert(!otis_cx321_plant_sign_engine_on_pre_estimate(
      &engine, &second, 0xA83Cu, 1u, 0u, natural_tight_inside, true,
      &decision));
  return engine;
}

}  // namespace

int main() {
  {
    constexpr uint64_t modulus = (1ull << 32) * 16ull;
    constexpr uint64_t second = 16000000ull;
    uint64_t projected = 0u;
    assert(otis_timer0_project_nearest_ticks(
        100u * second, modulus + 100u * second, 99u * second,
        60u * second, &projected));
    assert(projected == modulus + 99u * second);
    assert(otis_timer0_project_nearest_ticks(
        modulus - second / 2u, modulus - second / 2u, second / 2u,
        60u * second, &projected));
    assert(projected == modulus + second / 2u);
    assert(otis_timer0_project_nearest_ticks(
        second / 2u, modulus + second / 2u, modulus - second / 2u,
        60u * second, &projected));
    assert(projected == modulus - second / 2u);
    assert(!otis_timer0_project_nearest_ticks(
        100u * second, modulus + 100u * second, 161u * second,
        60u * second, &projected));
  }
  {
    auto engine = qualified_engine(-5);
    assert(engine.state == OtisCx321PlantSignState::PhaseQualify);
    assert(engine.attested);
    OtisActiveHybridEngine natural = {};
    assert(otis_cx321_plant_sign_engine_rebase_natural_controller(
        &engine, &natural));
    assert(natural.state == OtisActiveHybridState::PhaseQualify);
    assert(natural.correction_count == 1u);
    assert(natural.cumulative_movement_codes == 21u);
    assert(natural.natural_chatter_origin_code == 0xA827u);
    assert(natural.natural_cumulative_movement_codes == 0u);
    assert(natural.direction_count == 0u);
    assert(natural.exact_tick_timing_required);
    assert(natural.last_application_ticks == 5000u * kSecond);
    assert(natural.phase_qualification_started_ticks ==
           engine.response_acknowledgement_ticks);

    const uint64_t first_natural_boundary =
        engine.response_acknowledgement_ticks + 1800u * kSecond;
    auto observation = natural_observation(
        static_cast<uint32_t>(first_natural_boundary / kSecond),
        0xA827u, 2u);
    OtisActiveHybridDecision decision = {};
    assert(otis_active_hybrid_engine_decide_at_ticks(
        &natural, &observation, first_natural_boundary - 1u, &decision));
    assert(decision.requested_delta_codes == 0);
    assert(otis_active_hybrid_engine_decide_at_ticks(
        &natural, &observation, first_natural_boundary, &decision));
    assert(decision.requested_delta_codes != 0);
    assert(decision.correction_count_before == 1u);
    assert(decision.cumulative_movement_before_codes == 21u);
    assert(otis_active_hybrid_engine_note_application_at_ticks(
        &natural, &decision, decision.requested_code, 3u,
        first_natural_boundary + 200u, true));
    assert(natural.correction_count == 2u);
    assert(natural.cumulative_movement_codes > 21u);
    assert(natural.natural_cumulative_movement_codes > 0u);
    assert(natural.direction_count == 1u);

    assert(otis_active_hybrid_engine_note_response(
        &natural, true, true, true, true, true));
    const uint64_t second_natural_boundary =
        natural.last_application_ticks + 1800u * kSecond;
    observation = natural_observation(
        static_cast<uint32_t>(second_natural_boundary / kSecond),
        natural.applied_code, natural.dac_epoch);
    // First observation releases the mandatory checkpoint only.
    assert(otis_active_hybrid_engine_decide_at_ticks(
        &natural, &observation, second_natural_boundary - 1u, &decision));
    assert(decision.requested_delta_codes == 0);
    // At the same early tick HybridTracking is active, but exact cadence holds.
    assert(otis_active_hybrid_engine_decide_at_ticks(
        &natural, &observation, second_natural_boundary - 1u, &decision));
    assert(decision.cadence_limited);
    assert(decision.requested_delta_codes == 0);
    assert(otis_active_hybrid_engine_decide_at_ticks(
        &natural, &observation, second_natural_boundary, &decision));
    assert(!decision.cadence_limited);
    assert(decision.requested_delta_codes != 0);
  }
  {
    auto below = qualified_engine(-2);
    assert(below.state == OtisCx321PlantSignState::FailStatic);
  }
  {
    auto excess = qualified_engine(-15);
    assert(excess.state == OtisCx321PlantSignState::FailStatic);
  }
  {
    auto wrong = qualified_engine(5);
    assert(wrong.state == OtisCx321PlantSignState::FailStatic);
  }
  {
    auto late = qualified_engine(-5, 30u * kSecond + 1u);
    assert(late.state == OtisCx321PlantSignState::FailStatic);
    assert(late.reason != nullptr);
  }
  {
    auto non_nominal_timer_span = qualified_engine(
        -5, kSecond + 123u, kSecond + 1u);
    assert(non_nominal_timer_span.state ==
           OtisCx321PlantSignState::PhaseQualify);
  }
  {
    const auto discontinuous = second_pre_gate(false, true, true);
    assert(discontinuous.state == OtisCx321PlantSignState::FailStatic);
    assert(strcmp(discontinuous.reason,
                  "second_pre_window_capture_continuity_inexact") == 0);
  }
  {
    const auto discontinuous_and_out_of_band =
        second_pre_gate(false, true, true, 6);
    assert(discontinuous_and_out_of_band.state ==
           OtisCx321PlantSignState::FailStatic);
    assert(strcmp(discontinuous_and_out_of_band.reason,
                  "second_pre_window_capture_continuity_inexact") == 0);
  }
  {
    const auto unequal = second_pre_gate(true, false, true);
    assert(unequal.state == OtisCx321PlantSignState::NotExercised);
    assert(strcmp(unequal.reason,
                  "second_pre_window_not_equal_and_tight") == 0);
  }
  {
    const auto not_tight = second_pre_gate(true, true, false);
    assert(not_tight.state == OtisCx321PlantSignState::NotExercised);
    assert(strcmp(not_tight.reason,
                  "second_pre_window_not_equal_and_tight") == 0);
  }
  {
    OtisCx321PlantSignEngine engine = {};
    otis_cx321_plant_sign_engine_init(&engine);
    OtisCx321PlantSignEstimate estimate = {};
    estimate.total_count = 15000000002ull;
    estimate.signed_error_counts = 2;
    estimate.open_ticks = 1000u * kSecond;
    estimate.close_ticks = 2500u * kSecond;
    estimate.first_sequence = 1000u;
    estimate.last_sequence = 2500u;
    estimate.capture_session = 1u;
    estimate.dac_epoch = 2u;
    estimate.accepted_intervals = 1500u;
    estimate.valid = true;
    OtisCx321PlantSignDecision decision = {};
    assert(!otis_cx321_plant_sign_engine_on_pre_estimate(
        &engine, &estimate, 0xA83Cu, 2u, 0u, true, true, &decision));
    assert(engine.state == OtisCx321PlantSignState::FailStatic);
  }
  {
    OtisCx321PlantSignEngine engine = {};
    otis_cx321_plant_sign_engine_init(&engine);
    OtisCx321PlantSignEstimate estimate = {};
    estimate.total_count = 15000000006ull;
    estimate.signed_error_counts = 6;
    estimate.open_ticks = 1000u * kSecond;
    estimate.close_ticks = 2500u * kSecond;
    estimate.first_sequence = 1000u;
    estimate.last_sequence = 2500u;
    estimate.capture_session = 1u;
    estimate.dac_epoch = 1u;
    estimate.accepted_intervals = 1500u;
    estimate.valid = true;
    OtisCx321PlantSignDecision decision = {};
    assert(!otis_cx321_plant_sign_engine_on_pre_estimate(
        &engine, &estimate, 0xA83Cu, 1u, 0u, true, true, &decision));
    assert(engine.state == OtisCx321PlantSignState::NotExercised);
  }
  puts("cx321_plant_sign_harness_passed");
  return 0;
}
