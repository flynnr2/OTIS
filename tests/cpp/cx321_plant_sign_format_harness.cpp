#include <assert.h>
#include <stdint.h>
#include <stdio.h>

#include "otis_cx321_plant_sign_format.h"

namespace {

constexpr uint64_t kSecond = OTIS_CX321_TIMER0_TICKS_PER_SECOND;
constexpr char kPolicy[] =
    "0000000000000000000000000000000000000000000000000000000000000001";
constexpr char kGate[] =
    "0000000000000000000000000000000000000000000000000000000000000002";
constexpr char kIdEstimator[] =
    "0000000000000000000000000000000000000000000000000000000000000003";
constexpr char kIdConfig[] =
    "0000000000000000000000000000000000000000000000000000000000000004";
constexpr char kNatural[] =
    "0000000000000000000000000000000000000000000000000000000000000005";

OtisCx321PlantSignFormatRecord base(uint32_t sequence, const char *event,
                                    uint64_t ticks, const char *attestation) {
  OtisCx321PlantSignFormatRecord record = {};
  record.record_sequence = sequence;
  record.event = event;
  record.event_ticks = ticks;
  record.run_identity = "cx321:test";
  record.build_identity =
      "0000000000000000000000000000000000000000000000000000000000000001:0000000000000000000000000000000000000000000000000000000000000002";
  record.profile_identity = "cx321_bounded_active_hybrid_plant_sign_v2";
  record.capture_session = 41u;
  record.policy_sha256 = kPolicy;
  record.plant_sign_gate_sha256 = kGate;
  record.identification_estimator_sha256 = kIdEstimator;
  record.identification_estimator_config_sha256 = kIdConfig;
  record.natural_frequency_estimator_sha256 = kNatural;
  record.setup_application_ticks = kSecond;
  record.setup_applied_code = 0xA83Cu;
  record.state_before = "PLANT_SIGN_QUALIFY";
  record.state_after = "PLANT_SIGN_QUALIFY";
  record.reason = event;
  record.tight_state = "TIGHT_INSIDE";
  record.decision = {1u, 2, -21, 0xA83Cu, 0xA827u, 2401u, 3901u, 1u, true};
  record.request_sequence = 7u;
  record.acceptance_sequence = 7u;
  record.application_sequence = 1u;
  record.accepted_code = 0xA827u;
  record.applied_code = 0xA827u;
  record.application_ticks = 3902u * kSecond;
  record.dac_epoch = 2u;
  record.response.request_sequence = 7u;
  record.response.application_sequence = 1u;
  record.response.dac_epoch = 2u;
  record.response.source_last_sequence = 6302u;
  record.response.response_close_ticks = 6302u * kSecond;
  record.response.pre_total_count = 15000000002ll;
  record.response.post_total_count = 14999999997ll;
  record.response.response_counts = -5;
  record.response.sign_pass = true;
  record.response.magnitude_pass = true;
  record.response.exact_evidence_pass = true;
  record.response.tight_reentry_pass = true;
  record.response.passed = true;
  record.acknowledged_response_record_sequence = 5u;
  record.host_replay_exact = true;
  record.replay_attestation_sha256 = attestation;
  record.global_correction_count = 1u;
  record.global_cumulative_movement_codes = 21u;
  record.global_last_application_ticks = record.application_ticks;
  record.natural_chatter_origin_code = 0xA827u;
  record.natural_cumulative_movement_codes = 0u;
  record.natural_direction_count = 0u;
  record.attested = true;
  return record;
}

void set_window(OtisCx321PlantSignFormatRecord *record, uint32_t first,
                uint64_t open_s, int64_t total, uint32_t epoch) {
  record->have_estimate = true;
  record->estimate.total_count = static_cast<uint64_t>(total);
  record->estimate.signed_error_counts = total - 15000000000ll;
  record->estimate.open_ticks = open_s * kSecond;
  record->estimate.close_ticks = (open_s + 1500u) * kSecond;
  record->estimate.first_sequence = first;
  record->estimate.last_sequence = first + 1500u;
  record->estimate.capture_session = 41u;
  record->estimate.dac_epoch = epoch;
  record->estimate.accepted_intervals = 1500u;
  record->estimate.valid = true;
  record->event_ticks = record->estimate.close_ticks;
}

void emit(const OtisCx321PlantSignFormatRecord &record) {
  // Match the live active-evidence frame capacity so this regression proves
  // the full 60-field PSQ line fits the actual Core 1 -> Core 0 transport.
  char output[1536];
  uint16_t length = 0u;
  assert(otis_cx321_plant_sign_format_record(
      &record, output, sizeof(output), &length));
  assert(length > 2u);
  fputs(output, stdout);
}

}  // namespace

int main(int argc, char **argv) {
  const char *attestation = argc == 2 ? argv[1] : kPolicy;
  puts(otis_cx321_plant_sign_csv_header());
  auto pre1 = base(1u, "pre1", 0u, attestation);
  set_window(&pre1, 901u, 901u, 15000000002ll, 1u);
  pre1.state_before = "FREQUENCY_ACQUIRE";
  pre1.state_after = "FREQUENCY_ACQUIRE";
  pre1.reason = "first_pre_identification_window_accepted";
  pre1.reason = "first_pre_identification_window_accepted";
  emit(pre1);
  auto pre2 = base(2u, "pre2", 0u, attestation);
  set_window(&pre2, 2401u, 2401u, 15000000002ll, 1u);
  pre2.state_before = "FREQUENCY_ACQUIRE";
  pre2.reason = "identification_request_ready";
  pre2.reason = "identification_request_ready";
  emit(pre2);
  auto request = base(3u, "request", 3901u * kSecond, attestation);
  request.reason = "identification_request_created";
  request.reason = "identification_request_created";
  emit(request);
  auto application = base(4u, "application", 3902u * kSecond, attestation);
  application.reason = "identification_applied_response_pending";
  application.reason = "identification_applied_response_pending";
  emit(application);
  auto response = base(5u, "response", 0u, attestation);
  set_window(&response, 4802u, 4802u, 14999999997ll, 2u);
  response.response.source_last_sequence = response.estimate.last_sequence;
  response.state_after = "PLANT_SIGN_RESPONSE_ACK_PENDING";
  response.reason = "identification_response_exact_ack_pending";
  response.reason = "identification_response_exact_ack_pending";
  emit(response);
  auto acknowledgement =
      base(6u, "response_ack", 6303u * kSecond, attestation);
  acknowledgement.state_before = "PLANT_SIGN_RESPONSE_ACK_PENDING";
  acknowledgement.state_after = "PHASE_QUALIFY";
  acknowledgement.reason = "identification_response_acknowledged";
  acknowledgement.reason = "identification_response_acknowledged";
  emit(acknowledgement);
  auto handoff = base(7u, "handoff", 6304u * kSecond, attestation);
  handoff.state_before = "PHASE_QUALIFY";
  handoff.state_after = "PHASE_QUALIFY";
  handoff.reason = "plant_sign_first_natural_consumer_handoff_exact";
  handoff.reason = "plant_sign_first_natural_consumer_handoff_exact";
  emit(handoff);
  return 0;
}
