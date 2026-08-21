#include "otis_cx321_plant_sign_format.h"

#include <stdio.h>
#include <string.h>

namespace {

constexpr char kHeader[] =
    "record_type,schema_version,qualification_record_sequence,event,event_timestamp_ticks,run_identity,build_identity,profile_identity,capture_session,policy_sha256,plant_sign_gate_sha256,identification_estimator_sha256,identification_estimator_config_sha256,natural_frequency_estimator_sha256,setup_application_sequence,setup_application_timestamp_ticks,setup_applied_code,setup_dac_epoch,state_before,state_after,total_count,signed_error_counts,open_ticks,close_ticks,source_first_sequence,source_last_sequence,accepted_intervals,dac_epoch,tight_state,pre_error_counts,current_code,request_sequence,acceptance_sequence,application_sequence,requested_delta_codes,requested_code,accepted_code,applied_code,application_timestamp_ticks,pre_total_count,post_total_count,response_counts,response_source_last_sequence,sign_pass,magnitude_pass,exact_evidence_pass,tight_reentry_pass,passed,acknowledged_response_record_sequence,host_replay_exact,replay_attestation_sha256,global_correction_count,global_cumulative_movement_codes,global_last_application_timestamp_ticks,natural_chatter_origin_code,natural_cumulative_movement_codes,natural_direction_count,attested,reason,actionable";

}  // namespace

const char *otis_cx321_plant_sign_csv_header(void) { return kHeader; }

bool otis_cx321_plant_sign_format_record(
    const OtisCx321PlantSignFormatRecord *record, char *output,
    size_t output_capacity, uint16_t *output_length) {
  if (output_length != nullptr) *output_length = 0u;
  if (record == nullptr || output == nullptr || output_length == nullptr ||
      output_capacity < 3u || record->event == nullptr ||
      record->state_before == nullptr || record->state_after == nullptr ||
      record->reason == nullptr)
    return false;
  size_t length = 0u;
  uint16_t fields = 0u;
  const auto append = [&](const char *value) {
    const char *text = value == nullptr ? "" : value;
    const size_t text_length = strlen(text);
    const size_t required = text_length + (fields == 0u ? 0u : 1u);
    if (length + required + 2u >= output_capacity) return false;
    if (fields != 0u) output[length++] = ',';
    memcpy(output + length, text, text_length);
    length += text_length;
    fields++;
    return true;
  };
  char number[32];
  const auto u64 = [&](uint64_t value) {
    snprintf(number, sizeof(number), "%llu",
             static_cast<unsigned long long>(value));
    return append(number);
  };
  const auto i64 = [&](int64_t value) {
    snprintf(number, sizeof(number), "%lld", static_cast<long long>(value));
    return append(number);
  };
  const auto u32 = [&](uint32_t value) {
    snprintf(number, sizeof(number), "%lu", static_cast<unsigned long>(value));
    return append(number);
  };
  const auto i32 = [&](int32_t value) {
    snprintf(number, sizeof(number), "%ld", static_cast<long>(value));
    return append(number);
  };
  const auto boolean = [&](bool value) { return append(value ? "true" : "false"); };
  const bool window = strcmp(record->event, "pre1") == 0 ||
                      strcmp(record->event, "pre2") == 0 ||
                      strcmp(record->event, "response") == 0;
  const bool request = strcmp(record->event, "request") == 0;
  const bool application = strcmp(record->event, "application") == 0;
  const bool response = strcmp(record->event, "response") == 0;
  const bool acknowledgement = strcmp(record->event, "response_ack") == 0;
  const bool handoff = strcmp(record->event, "handoff") == 0;
  const bool application_tuple = application || response || acknowledgement || handoff;
  const bool acknowledgement_tuple = acknowledgement || handoff;
  bool ok =
      append("PSQ") && append("1") && u32(record->record_sequence) &&
      append(record->event) && u64(record->event_ticks) &&
      append(record->run_identity) && append(record->build_identity) &&
      append(record->profile_identity) && u32(record->capture_session) &&
      append(record->policy_sha256) && append(record->plant_sign_gate_sha256) &&
      append(record->identification_estimator_sha256) &&
      append(record->identification_estimator_config_sha256) &&
      append(record->natural_frequency_estimator_sha256) && append("1") &&
      u64(record->setup_application_ticks) && u32(record->setup_applied_code) &&
      append("1") && append(record->state_before) && append(record->state_after);
#define BLANK() ok = ok && append("")
#define U64(value) ok = ok && u64(value)
#define I64(value) ok = ok && i64(value)
#define U32(value) ok = ok && u32(value)
#define I32(value) ok = ok && i32(value)
#define BOOL(value) ok = ok && boolean(value)
  if (window && record->have_estimate) {
    U64(record->estimate.total_count); I64(record->estimate.signed_error_counts);
    U64(record->estimate.open_ticks); U64(record->estimate.close_ticks);
    U32(record->estimate.first_sequence); U32(record->estimate.last_sequence);
    U32(record->estimate.accepted_intervals); U32(record->estimate.dac_epoch);
    ok = ok && append(record->tight_state);
  } else {
    for (uint8_t index = 0u; index < 7u; ++index) BLANK();
    if (application_tuple) U32(record->dac_epoch); else BLANK();
    BLANK();
  }
  if (request) {
    I64(record->decision.pre_error_counts); U32(record->decision.current_code);
    U32(record->request_sequence);
  } else {
    BLANK(); BLANK();
    if (application_tuple) U32(record->request_sequence); else BLANK();
  }
  if (application_tuple) {
    U32(record->acceptance_sequence); U32(record->application_sequence);
  } else { BLANK(); BLANK(); }
  if (request || application_tuple) {
    I32(record->decision.requested_delta_codes);
    U32(record->decision.requested_code);
  } else { BLANK(); BLANK(); }
  if (application_tuple) {
    U32(record->accepted_code); U32(record->applied_code);
    U64(record->application_ticks);
  } else { BLANK(); BLANK(); BLANK(); }
  if (response) {
    I64(record->response.pre_total_count); I64(record->response.post_total_count);
  } else { BLANK(); BLANK(); }
  if (response || acknowledgement_tuple) {
    I64(record->response.response_counts); U32(record->response.source_last_sequence);
  } else { BLANK(); BLANK(); }
  if (response) {
    BOOL(record->response.sign_pass); BOOL(record->response.magnitude_pass);
    BOOL(record->response.exact_evidence_pass);
    BOOL(record->response.tight_reentry_pass); BOOL(record->response.passed);
  } else { for (uint8_t index = 0u; index < 5u; ++index) BLANK(); }
  if (acknowledgement_tuple) {
    U32(record->acknowledged_response_record_sequence);
    BOOL(record->host_replay_exact); ok = ok && append(record->replay_attestation_sha256);
  } else { BLANK(); BLANK(); BLANK(); }
  if (handoff) {
    U32(record->global_correction_count); U32(record->global_cumulative_movement_codes);
    U64(record->global_last_application_ticks); U32(record->natural_chatter_origin_code);
    U32(record->natural_cumulative_movement_codes); U32(record->natural_direction_count);
    BOOL(record->attested);
  } else { for (uint8_t index = 0u; index < 7u; ++index) BLANK(); }
  ok = ok && append(record->reason) && append("false");
#undef BLANK
#undef U64
#undef I64
#undef U32
#undef I32
#undef BOOL
  if (!ok || fields != 60u || length + 2u >= output_capacity) return false;
  output[length++] = '\r'; output[length++] = '\n'; output[length] = '\0';
  *output_length = static_cast<uint16_t>(length);
  return true;
}
