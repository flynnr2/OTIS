#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "otis_cx321_plant_sign.h"
#include "otis_cx321_plant_sign_format.h"
#include "otis_timer0_extension.h"

namespace {

constexpr uint64_t kSecond = 16000000ull;
constexpr uint64_t kModulus = (1ull << 32) * 16ull;
constexpr uint32_t kSession = 41u;

uint64_t raw(uint64_t extended_ticks) {
  return extended_ticks % kModulus;
}

OtisCx321PlantSignFormatRecord format_record(
    uint32_t sequence, const char *event, uint64_t event_ticks,
    uint64_t setup_ticks, const OtisCx321PlantSignEstimate *estimate,
    const OtisCx321PlantSignEngine &engine) {
  static constexpr char kDigest[] =
      "0000000000000000000000000000000000000000000000000000000000000001";
  OtisCx321PlantSignFormatRecord record = {};
  record.record_sequence = sequence;
  record.event = event;
  record.event_ticks = event_ticks;
  record.run_identity = "cx321:extension";
  record.build_identity = "fixture:fixture";
  record.profile_identity = "cx321_active_hybrid";
  record.capture_session = kSession;
  record.policy_sha256 = kDigest;
  record.plant_sign_gate_sha256 = kDigest;
  record.identification_estimator_sha256 = kDigest;
  record.identification_estimator_config_sha256 = kDigest;
  record.natural_frequency_estimator_sha256 = kDigest;
  record.setup_application_ticks = setup_ticks;
  record.setup_applied_code = 0xA83Cu;
  record.state_before = "PLANT_SIGN_QUALIFY";
  record.state_after = "PLANT_SIGN_QUALIFY";
  record.reason = event;
  record.have_estimate = estimate != nullptr;
  if (estimate != nullptr) record.estimate = *estimate;
  record.tight_state = "TIGHT_INSIDE";
  record.decision = engine.pending_decision;
  record.request_sequence = 7u;
  record.acceptance_sequence = 7u;
  record.application_sequence = 1u;
  record.accepted_code = engine.applied_code;
  record.applied_code = engine.applied_code;
  record.application_ticks = engine.application_ticks;
  record.dac_epoch = engine.applied_dac_epoch;
  record.response = engine.pending_response;
  record.acknowledged_response_record_sequence = 5u;
  record.host_replay_exact = true;
  record.replay_attestation_sha256 = kDigest;
  record.global_correction_count = 1u;
  record.global_cumulative_movement_codes = 21u;
  record.global_last_application_ticks = engine.application_ticks;
  record.natural_chatter_origin_code = engine.applied_code;
  record.attested = engine.attested;
  return record;
}

uint64_t formatted_event_ticks(
    const OtisCx321PlantSignFormatRecord &record) {
  char output[2048];
  uint16_t length = 0u;
  assert(otis_cx321_plant_sign_format_record(
      &record, output, sizeof(output), &length));
  assert(length > 2u);
  const char *start = output;
  for (uint8_t field = 0u; field < 4u; ++field) {
    start = strchr(start, ',');
    assert(start != nullptr);
    ++start;
  }
  char *end = nullptr;
  const uint64_t parsed = strtoull(start, &end, 10);
  assert(end != start && *end == ',');
  return parsed;
}

}  // namespace

int main() {
  // Ten seconds after a raw TIMER0 wrap: the real ~6,300 s lifecycle crosses
  // exactly the next single 2^32-us wrap.
  const uint64_t setup_ticks = 10u * kSecond;
  OtisTimer0Extension extension = {};
  otis_timer0_extension_init(&extension);
  assert(otis_timer0_extension_seed(&extension, setup_ticks, kSession));

  OtisCx321PlantSignAccumulator pre_accumulator = {};
  otis_cx321_plant_sign_accumulator_init(
      &pre_accumulator, setup_ticks, 1u, kSession);
  OtisCx321PlantSignEngine engine = {};
  otis_cx321_plant_sign_engine_init(&engine);
  OtisCx321PlantSignEstimate pre_windows[2] = {};
  uint8_t pre_count = 0u;
  uint32_t wraps = 0u;
  uint64_t previous_raw = raw(setup_ticks);
  uint64_t previous_extended = setup_ticks;
  uint64_t formatted_ticks[7] = {};
  uint8_t formatted_count = 0u;
  const auto record_event = [&](const char *event, uint64_t event_ticks,
                                const OtisCx321PlantSignEstimate *estimate) {
    assert(formatted_count < 7u);
    formatted_ticks[formatted_count] = formatted_event_ticks(
        format_record(formatted_count + 1u, event, event_ticks, setup_ticks,
                      estimate, engine));
    formatted_count++;
  };

  for (uint32_t second = 1u; second <= 3900u; ++second) {
    const uint64_t boundary_raw = raw(setup_ticks + second * kSecond);
    if (boundary_raw < previous_raw) wraps++;
    uint64_t boundary_extended = 0u;
    assert(otis_timer0_extension_advance_boundary(
        &extension, boundary_raw, kSession, &boundary_extended));
    assert(boundary_extended == setup_ticks + second * kSecond);
    uint32_t interval_count = OTIS_CX321_NOMINAL_COUNT_PER_INTERVAL;
    if (pre_accumulator.accepted_intervals == 0u &&
        previous_extended >=
            setup_ticks + OTIS_CX321_SETTLING_EXCLUSION_TICKS)
      interval_count += 2u;
    OtisCx321PlantSignEstimate estimate = {};
    if (otis_cx321_plant_sign_accumulator_on_interval(
            &pre_accumulator, previous_extended, boundary_extended,
            second + 100u, interval_count, 1u, kSession, true, &estimate)) {
      assert(pre_count < 2u);
      pre_windows[pre_count++] = estimate;
      OtisCx321PlantSignDecision decision = {};
      const bool ready = otis_cx321_plant_sign_engine_on_pre_estimate(
          &engine, &estimate, 0xA83Cu, 1u, 0u, true, true, &decision);
      const char *event = pre_count == 1u ? "pre1" : "pre2";
      record_event(event, boundary_extended, &estimate);
      if (pre_count == 1u) assert(!ready);
      if (pre_count == 2u) {
        assert(ready);
        record_event("request", boundary_extended, nullptr);
      }
    }
    previous_raw = boundary_raw;
    previous_extended = boundary_extended;
  }
  assert(pre_count == 2u);
  assert(engine.pending_decision.requested_delta_codes == -21);

  const uint64_t application_actual = previous_extended + kSecond / 2u;
  const uint64_t next_boundary_raw = raw(previous_extended + kSecond);
  uint64_t next_boundary_extended = 0u;
  assert(otis_timer0_extension_advance_boundary(
      &extension, next_boundary_raw, kSession, &next_boundary_extended));
  uint64_t application_projected = 0u;
  assert(otis_timer0_extension_project_nearest(
      &extension, raw(application_actual), kSession, 60u * kSecond,
      &application_projected));
  assert(application_projected == application_actual);
  assert(application_projected < next_boundary_extended);
  assert(otis_cx321_plant_sign_engine_note_application(
      &engine, 7u, 1u, 0xA827u, 2u, application_projected, true));
  record_event("application", application_projected, nullptr);

  OtisCx321PlantSignAccumulator post_accumulator = {};
  otis_cx321_plant_sign_accumulator_init(
      &post_accumulator, application_projected, 2u, kSession);
  previous_raw = next_boundary_raw;
  previous_extended = next_boundary_extended;
  OtisCx321PlantSignEstimate post = {};
  bool response_ready = false;
  for (uint32_t second = 3902u; second <= 6302u && !response_ready;
       ++second) {
    const uint64_t boundary_raw = raw(setup_ticks + second * kSecond);
    if (boundary_raw < previous_raw) wraps++;
    uint64_t boundary_extended = 0u;
    assert(otis_timer0_extension_advance_boundary(
        &extension, boundary_raw, kSession, &boundary_extended));
    uint32_t interval_count = OTIS_CX321_NOMINAL_COUNT_PER_INTERVAL;
    if (post_accumulator.accepted_intervals == 0u &&
        previous_extended >=
            application_projected + OTIS_CX321_SETTLING_EXCLUSION_TICKS)
      interval_count -= 3u;
    response_ready = otis_cx321_plant_sign_accumulator_on_interval(
        &post_accumulator, previous_extended, boundary_extended,
        second + 100u, interval_count, 2u, kSession, true, &post);
    previous_raw = boundary_raw;
    previous_extended = boundary_extended;
  }
  assert(response_ready);
  OtisCx321PlantSignResponse response = {};
  assert(otis_cx321_plant_sign_engine_on_response(
      &engine, &post, true, true, &response));
  assert(response.response_counts == -5);
  record_event("response", post.close_ticks, &post);

  const uint64_t acknowledgement_actual = post.close_ticks + kSecond / 2u;
  const uint64_t after_response_boundary_raw = raw(post.close_ticks + kSecond);
  uint64_t after_response_boundary_extended = 0u;
  assert(otis_timer0_extension_advance_boundary(
      &extension, after_response_boundary_raw, kSession,
      &after_response_boundary_extended));
  uint64_t acknowledgement_projected = 0u;
  assert(otis_timer0_extension_project_nearest(
      &extension, raw(acknowledgement_actual), kSession, 60u * kSecond,
      &acknowledgement_projected));
  assert(acknowledgement_projected == acknowledgement_actual);
  assert(acknowledgement_projected < after_response_boundary_extended);
  assert(otis_cx321_plant_sign_engine_acknowledge_response(
      &engine, 7u, 1u, 2u, post.last_sequence, -5,
      acknowledgement_projected, true));
  record_event("response_ack", acknowledgement_projected, nullptr);
  record_event("handoff", after_response_boundary_extended, nullptr);

  assert(wraps == 1u);
  assert(post.close_ticks > kModulus);
  assert(formatted_count == 7u);
  for (uint8_t index = 1u; index < formatted_count; ++index)
    assert(formatted_ticks[index] >= formatted_ticks[index - 1u]);
  uint64_t ambiguous = 0u;
  assert(!otis_timer0_extension_project_nearest(
      &extension, raw(after_response_boundary_extended + 61u * kSecond),
      kSession, 60u * kSecond, &ambiguous));
  puts("cx321_live_extension_harness_passed");
  return 0;
}
