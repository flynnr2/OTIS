#include <stdio.h>
#include <assert.h>
#include <string.h>
#include <utility>

#include "otis_active_hybrid_policy_engine.h"

namespace {

OtisActiveHybridObservation observation(
    uint32_t timestamp_s, uint16_t code = 0xA83Cu,
    uint32_t dac_epoch = 1u, double frequency_error_hz = 0.0,
    const char *tight_state = "TIGHT_INSIDE", int64_t phase_cycles = -24,
    uint32_t phase_sequence = 1u) {
  return {
      timestamp_s,
      1u,
      timestamp_s > 599u ? timestamp_s - 599u : 1u,
      timestamp_s == 0u ? 1u : timestamp_s,
      dac_epoch,
      code,
      frequency_error_hz,
      0,
      tight_state,
      1u,
      phase_sequence,
      phase_cycles,
      dac_epoch,
      code,
      true,
      true,
      false,
      true,
      true,
      true,
      false,
      false,
  };
}

void emit(const char *scenario, uint32_t step,
          const OtisActiveHybridDecision &decision) {
  printf(
      "%s,%lu,%s,%s,%s,%.17g,%.17g,%.17g,%.17g,%ld,%u,%ld,%u,%u,%u,%u,%u,%u,%u,%u\n",
      scenario, static_cast<unsigned long>(step),
      otis_active_hybrid_state_name(decision.state_before),
      otis_active_hybrid_state_name(decision.state_after), decision.reason,
      decision.frequency_term_hz, decision.phase_term_hz,
      decision.combined_demand_hz, decision.raw_combined_delta_codes,
      static_cast<long>(decision.requested_delta_codes),
      decision.requested_code,
      static_cast<long>(decision.counterfactual_frequency_only_delta_codes),
      decision.phase_materially_influenced, decision.step_limited,
      decision.range_clamped, decision.cadence_limited,
      decision.count_limited, decision.cumulative_budget_limited,
      decision.correction_count_before,
      decision.cumulative_movement_before_codes);
}

void decide_and_emit(const char *scenario, uint32_t step,
                     OtisActiveHybridEngine *engine,
                     OtisActiveHybridObservation *input,
                     OtisActiveHybridDecision *decision) {
  if (!otis_active_hybrid_engine_decide(engine, input, decision)) return;
  emit(scenario, step, *decision);
}

void simple_phase_case(const char *name, int64_t phase_cycles) {
  OtisActiveHybridEngine engine;
  otis_active_hybrid_engine_init(&engine, 0u);
  OtisActiveHybridDecision decision;
  auto first = observation(1800u);
  decide_and_emit(name, 1u, &engine, &first, &decision);
  auto second = observation(3600u, 0xA83Cu, 1u, 0.0, "TIGHT_INSIDE",
                            phase_cycles, 2u);
  decide_and_emit(name, 2u, &engine, &second, &decision);
}

}  // namespace

int main() {
  puts("scenario,step,state_before,state_after,reason,frequency_term_hz,phase_term_hz,combined_demand_hz,raw_combined_delta_codes,requested_delta_codes,requested_code,counterfactual_frequency_only_delta_codes,phase_materially_influenced,step_limited,range_clamped,cadence_limited,count_limited,cumulative_budget_limited,correction_count_before,cumulative_movement_before_codes");

  simple_phase_case("phase_positive", -24);
  simple_phase_case("phase_negative", 24);
  simple_phase_case("phase_small_zero", -1);
  simple_phase_case("phase_cap", -1000);

  for (const auto &item : {
           std::pair<const char *, int64_t>{"phase_frequency_material", -24},
           std::pair<const char *, int64_t>{"phase_frequency_nonmaterial", -1},
       }) {
    OtisActiveHybridEngine engine;
    otis_active_hybrid_engine_init(&engine, 0u);
    OtisActiveHybridDecision decision;
    auto input = observation(1800u);
    decide_and_emit(item.first, 1u, &engine, &input, &decision);
    input = observation(3600u, 0xA83Cu, 1u, -0.001, "TIGHT_INSIDE",
                        item.second, 2u);
    decide_and_emit(item.first, 2u, &engine, &input, &decision);
  }

  {
    OtisActiveHybridEngine engine;
    otis_active_hybrid_engine_init(&engine, 0u);
    OtisActiveHybridDecision decision;
    auto input = observation(1800u, 0xA83Cu, 1u, 0.01, "OUTSIDE");
    decide_and_emit("frequency_negative", 1u, &engine, &input, &decision);
  }
  {
    OtisActiveHybridEngine engine;
    otis_active_hybrid_engine_init(&engine, 0u);
    OtisActiveHybridDecision decision;
    auto input = observation(1800u, 0xA83Cu, 1u, -0.01, "OUTSIDE");
    decide_and_emit("frequency_positive", 1u, &engine, &input, &decision);
  }
  {
    OtisActiveHybridEngine engine;
    otis_active_hybrid_engine_init(&engine, 611u);
    OtisActiveHybridDecision decision;
    auto input = observation(2400u, 0xA83Cu, 1u, 0.01, "OUTSIDE");
    decide_and_emit("setup_cadence_611", 1u, &engine, &input, &decision);
    input = observation(2411u, 0xA83Cu, 1u, 0.01, "OUTSIDE", -24, 2u);
    decide_and_emit("setup_cadence_611", 2u, &engine, &input, &decision);
  }
  {
    OtisActiveHybridEngine engine;
    otis_active_hybrid_engine_init(&engine, 0u);
    OtisActiveHybridDecision decision;
    auto input = observation(1800u);
    decide_and_emit("progressive", 1u, &engine, &input, &decision);
    input = observation(3600u, 0xA83Cu, 1u, 0.0, "TIGHT_INSIDE", -24, 2u);
    decide_and_emit("progressive", 2u, &engine, &input, &decision);
    otis_active_hybrid_engine_note_application(
        &engine, &decision, decision.requested_code, 2u, true);
    input = observation(4200u, decision.requested_code, 2u, 0.0,
                        "TIGHT_INSIDE", -23, 3u);
    input.outstanding_request = true;
    decide_and_emit("progressive", 3u, &engine, &input, &decision);
    otis_active_hybrid_engine_note_response(
        &engine, true, true, true, true, true);
    input = observation(5400u, engine.applied_code, 2u, 0.0,
                        "TIGHT_INSIDE", -22, 4u);
    decide_and_emit("progressive", 4u, &engine, &input, &decision);
    input = observation(6000u, engine.applied_code, 2u, 0.0,
                        "TIGHT_INSIDE", -21, 5u);
    decide_and_emit("progressive", 5u, &engine, &input, &decision);
  }
  {
    OtisActiveHybridEngine engine;
    otis_active_hybrid_engine_init(&engine, 0u);
    OtisActiveHybridDecision decision;
    auto input = observation(1800u);
    assert(otis_active_hybrid_engine_decide(&engine, &input, &decision));
    input = observation(3600u, 0xA83Cu, 1u, 0.0, "TIGHT_INSIDE", -24,
                        2u);
    assert(otis_active_hybrid_engine_decide(&engine, &input, &decision));
    assert(otis_active_hybrid_engine_note_application(
        &engine, &decision, decision.requested_code, 2u, true));
    assert(otis_active_hybrid_engine_note_response(
        &engine, true, false, true, true, true, true));
    input = observation(5400u, engine.applied_code, 2u, 0.0,
                        "TIGHT_INSIDE", -22, 3u);
    assert(otis_active_hybrid_engine_decide(&engine, &input, &decision));
    assert(engine.state == OtisActiveHybridState::HybridTracking);
    assert(strcmp(engine.reason,
                  "first_phase_observation_recorded_and_tight_reacquired") ==
           0);
  }
  {
    OtisActiveHybridEngine engine;
    otis_active_hybrid_engine_init(&engine, 0u);
    engine.last_application_available = true;
    engine.last_application_s = 1000u;
    OtisActiveHybridDecision decision;
    auto input = observation(2000u, 0xA83Cu, 1u, 0.01, "OUTSIDE");
    decide_and_emit("cadence", 1u, &engine, &input, &decision);
  }
  {
    OtisActiveHybridEngine engine;
    otis_active_hybrid_engine_init(&engine, 0u);
    engine.correction_count = 4u;
    OtisActiveHybridDecision decision;
    auto input = observation(1800u, 0xA83Cu, 1u, 0.01, "OUTSIDE");
    decide_and_emit("count", 1u, &engine, &input, &decision);
  }
  {
    OtisActiveHybridEngine engine;
    otis_active_hybrid_engine_init(&engine, 0u);
    engine.cumulative_movement_codes = 80u;
    OtisActiveHybridDecision decision;
    auto input = observation(1800u, 0xA83Cu, 1u, 0.01, "OUTSIDE");
    decide_and_emit("cumulative", 1u, &engine, &input, &decision);
  }
  {
    OtisActiveHybridEngine engine;
    otis_active_hybrid_engine_init(&engine, 0u);
    engine.applied_code = 0xAB00u;
    OtisActiveHybridDecision decision;
    auto input = observation(1800u, 0xAB00u, 1u, -0.01, "OUTSIDE");
    input.phase_applied_code = 0xAB00u;
    decide_and_emit("range", 1u, &engine, &input, &decision);
  }
  {
    OtisActiveHybridEngine engine;
    otis_active_hybrid_engine_init(&engine, 0u);
    OtisActiveHybridDecision decision;
    auto input = observation(1800u);
    decide_and_emit("direction_hold", 1u, &engine, &input, &decision);
    input = observation(3600u, 0xA83Cu, 1u, 0.003,
                        "TIGHT_INSIDE", -24, 2u);
    decide_and_emit("direction_hold", 2u, &engine, &input, &decision);
  }
  {
    OtisActiveHybridEngine engine;
    otis_active_hybrid_engine_init(&engine, 0u);
    engine.direction_history[0] = 1;
    engine.direction_history[1] = -1;
    engine.direction_history[2] = 1;
    engine.direction_count = 3u;
    OtisActiveHybridDecision decision;
    auto input = observation(1800u, 0xA83Cu, 1u, 0.01, "OUTSIDE");
    decide_and_emit("alternation", 1u, &engine, &input, &decision);
  }
  {
    OtisActiveHybridEngine engine;
    otis_active_hybrid_engine_init(&engine, 0u);
    OtisActiveHybridDecision decision;
    auto input = observation(1800u);
    decide_and_emit("phase_degrade", 1u, &engine, &input, &decision);
    input = observation(3600u, 0xA83Cu, 1u, 0.0, "TIGHT_INSIDE", -24, 2u);
    input.phase_continuous = false;
    decide_and_emit("phase_degrade", 2u, &engine, &input, &decision);
  }
  {
    OtisActiveHybridEngine engine;
    otis_active_hybrid_engine_init(&engine, 0u);
    OtisActiveHybridDecision decision;
    auto input = observation(1800u);
    decide_and_emit("identity_fault", 1u, &engine, &input, &decision);
    input = observation(3600u);
    input.identity_exact = false;
    decide_and_emit("identity_fault", 2u, &engine, &input, &decision);
  }
  {
    OtisActiveHybridEngine engine;
    otis_active_hybrid_engine_init(&engine, 0u);
    OtisActiveHybridDecision decision;
    auto input = observation(1800u, 0xA83Cu, 2u);
    decide_and_emit("epoch_fault", 1u, &engine, &input, &decision);
  }
  {
    constexpr uint64_t kTicksPerSecond = 16000000ull;
    constexpr uint64_t kSetupTicks = 611ull * kTicksPerSecond + 12345ull;
    OtisActiveHybridEngine engine;
    otis_active_hybrid_engine_init_at_ticks(&engine, kSetupTicks);
    assert(engine.exact_tick_timing_required);
    assert(engine.last_application_ticks == kSetupTicks);
    OtisActiveHybridDecision decision;
    auto input = observation(2411u, 0xA83Cu, 1u, 0.01, "OUTSIDE");
    assert(otis_active_hybrid_engine_decide_at_ticks(
        &engine, &input, kSetupTicks + 1800ull * kTicksPerSecond - 1ull,
        &decision));
    assert(decision.cadence_limited);
    assert(otis_active_hybrid_engine_decide_at_ticks(
        &engine, &input, kSetupTicks + 1800ull * kTicksPerSecond,
        &decision));
    assert(!decision.cadence_limited);
  }
  {
    constexpr uint64_t kTicksPerSecond = 16000000ull;
    constexpr uint64_t kSetupTicks = 613ull * kTicksPerSecond + 12345ull;
    constexpr uint64_t kPhaseEntryTicks =
        3001ull * kTicksPerSecond + 45678ull;
    constexpr uint64_t kPhaseResidenceTicks = 1800ull * kTicksPerSecond;
    OtisActiveHybridEngine engine;
    otis_active_hybrid_engine_init_at_ticks(&engine, kSetupTicks);
    OtisActiveHybridDecision decision;
    auto input = observation(3001u, 0xA83Cu, 1u, 0.001, "TIGHT_INSIDE",
                             1, 1u);
    assert(otis_active_hybrid_engine_decide_at_ticks(
        &engine, &input, kPhaseEntryTicks, &decision));
    assert(engine.phase_qualification_started_ticks == kPhaseEntryTicks);
    assert(decision.requested_delta_codes == 0);
    input = observation(4801u, 0xA83Cu, 1u, 0.001, "TIGHT_INSIDE", 1,
                        2u);
    assert(otis_active_hybrid_engine_decide_at_ticks(
        &engine, &input, kPhaseEntryTicks + kPhaseResidenceTicks - 1u,
        &decision));
    assert(decision.requested_delta_codes == 0);
    assert(otis_active_hybrid_engine_decide_at_ticks(
        &engine, &input, kPhaseEntryTicks + kPhaseResidenceTicks, &decision));
    assert(decision.requested_delta_codes != 0);
  }
  return 0;
}
