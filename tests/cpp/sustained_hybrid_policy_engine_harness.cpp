#include <assert.h>
#include <string.h>

#include "otis_active_hybrid_policy_engine.h"

namespace {

constexpr uint64_t kHz = 16000000ull;

OtisActiveHybridObservation observation(uint32_t timestamp_s, uint16_t code,
                                        uint32_t dac_epoch,
                                        int64_t phase_cycles,
                                        uint32_t phase_sequence) {
  return {
      timestamp_s,
      1u,
      timestamp_s > 599u ? timestamp_s - 599u : 1u,
      timestamp_s,
      dac_epoch,
      code,
      0.0,
      0,
      "TIGHT_INSIDE",
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

void apply_and_respond(OtisActiveHybridEngine *engine,
                       const OtisActiveHybridDecision *decision,
                       uint64_t ticks) {
  assert(decision->requested_delta_codes != 0);
  assert(otis_active_hybrid_engine_note_application_at_ticks(
      engine, decision, decision->requested_code, engine->dac_epoch + 1u,
      ticks, true));
  assert(otis_active_hybrid_engine_note_response(
      engine, true, false, true, true, true, true));
}

}  // namespace

int main() {
  OtisActiveHybridEngine engine;
  otis_active_hybrid_engine_init_at_ticks(&engine, 1u * kHz);
  OtisActiveHybridDecision decision;

  auto input = observation(601u, 0xA83Cu, 1u, -24, 1u);
  assert(otis_active_hybrid_engine_decide_at_ticks(
      &engine, &input, 601u * kHz, &decision));
  assert(engine.qualified_origin_available);
  assert(decision.requested_delta_codes == 0);

  input = observation(2401u, 0xA83Cu, 1u, -24, 2u);
  assert(otis_active_hybrid_engine_decide_at_ticks(
      &engine, &input, 2401u * kHz, &decision));
  assert(decision.requested_delta_codes > 0);
  apply_and_respond(&engine, &decision, 2401u * kHz);
  assert(engine.correction_count == 1u);
  assert(engine.automatic_application_count == 1u);

  input = observation(4201u, engine.applied_code, engine.dac_epoch, -20, 3u);
  assert(otis_active_hybrid_engine_decide_at_ticks(
      &engine, &input, 4201u * kHz, &decision));
  assert(decision.requested_delta_codes == 0);
  input.phase_observation_sequence = 4u;
  assert(otis_active_hybrid_engine_decide_at_ticks(
      &engine, &input, 4801u * kHz, &decision));
  assert(decision.requested_delta_codes > 0);
  apply_and_respond(&engine, &decision, 4801u * kHz);
  assert(engine.automatic_application_count == 2u);

  const uint64_t challenge_ticks = engine.qualified_origin_ticks + 43200u * kHz;
  input = observation(static_cast<uint32_t>(challenge_ticks / kHz),
                      engine.applied_code, engine.dac_epoch, -12, 5u);
  assert(otis_active_hybrid_engine_decide_at_ticks(
      &engine, &input, challenge_ticks, &decision));
  assert(strcmp(decision.reason,
                "deliberate_reversal_challenge_request_ready") == 0);
  assert(decision.requested_delta_codes == 21);
  apply_and_respond(&engine, &decision, challenge_ticks);
  assert(engine.deliberate_challenge_applied);
  assert(engine.correction_count == 3u);
  assert(engine.automatic_application_count == 2u);

  const uint64_t recovery_ticks = challenge_ticks + 1800u * kHz;
  input = observation(static_cast<uint32_t>(recovery_ticks / kHz),
                      engine.applied_code, engine.dac_epoch, 1000, 6u);
  assert(otis_active_hybrid_engine_decide_at_ticks(
      &engine, &input, recovery_ticks, &decision));
  assert(strcmp(decision.reason,
                "deliberate_reversal_challenge_recovery_request_ready") == 0);
  assert(decision.requested_delta_codes < 0);
  apply_and_respond(&engine, &decision, recovery_ticks);
  assert(engine.deliberate_challenge_recovery_applied);
  assert(engine.natural_reversal_observed);
  assert(engine.correction_count == 4u);
  assert(engine.automatic_application_count == 3u);
  assert(engine.cumulative_movement_codes <= 84u);

  // The longer programme must compare chatter against the latest natural
  // applications, not a frozen copy of the first four.
  OtisActiveHybridEngine history;
  otis_active_hybrid_engine_init_at_ticks(&history, 1u * kHz);
  input = observation(601u, 0xA83Cu, 1u, -24, 1u);
  assert(otis_active_hybrid_engine_decide_at_ticks(
      &history, &input, 601u * kHz, &decision));
  input = observation(2401u, history.applied_code, history.dac_epoch, -24, 2u);
  assert(otis_active_hybrid_engine_decide_at_ticks(
      &history, &input, 2401u * kHz, &decision));
  apply_and_respond(&history, &decision, 2401u * kHz);
  input = observation(3001u, history.applied_code, history.dac_epoch, -24, 3u);
  assert(otis_active_hybrid_engine_decide_at_ticks(
      &history, &input, 3001u * kHz, &decision));
  assert(decision.requested_delta_codes == 0);
  for (uint32_t index = 0; index < 4u; ++index) {
    const uint32_t timestamp_s = 4201u + index * 1800u;
    const int64_t phase = index == 3u ? 24 : -24;
    input = observation(timestamp_s, history.applied_code, history.dac_epoch,
                        phase, 4u + index);
    assert(otis_active_hybrid_engine_decide_at_ticks(
        &history, &input, static_cast<uint64_t>(timestamp_s) * kHz,
        &decision));
    apply_and_respond(&history, &decision,
                      static_cast<uint64_t>(timestamp_s) * kHz);
  }
  assert(history.direction_count == 4u);
  assert(history.direction_history[0] == 1);
  assert(history.direction_history[1] == 1);
  assert(history.direction_history[2] == 1);
  assert(history.direction_history[3] == -1);
  return 0;
}
