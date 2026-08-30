#include "otis_active_timing_sidecar.h"

#include <stdio.h>

namespace {

constexpr char kActiveTransactionTimingV2Header[] =
    "record_type,schema_version,timing_record_sequence,transaction_record_sequence,event,event_timestamp_ticks,time_domain,run_identity,build_identity,profile_identity,session_id,request_sequence,decision_sequence,source_first_sequence,source_last_sequence,authorization_sequence,nonce,accepted_code,applied_code,application_sequence,dac_epoch,reason";
constexpr char kActiveHybridTimingV2Header[] =
    "record_type,schema_version,timing_record_sequence,hybrid_record_sequence,decision_sequence,decision_timestamp_ticks,time_domain,run_identity,build_identity,profile_identity,capture_session,source_first_sequence,source_last_sequence,reason";
constexpr char kExtendedTimer0Domain[] = "rp2040_timer0_extended";

bool text_present(const char *value) {
  return value != nullptr && value[0] != '\0';
}

}  // namespace

const char *otis_active_transaction_timing_v2_csv_header(void) {
  return kActiveTransactionTimingV2Header;
}

const char *otis_active_hybrid_timing_v2_csv_header(void) {
  return kActiveHybridTimingV2Header;
}

int otis_format_active_transaction_timing_v2(
    char *output, size_t output_size,
    const OtisActiveTransactionTimingV2 *record) {
  if (output == nullptr || output_size == 0u || record == nullptr ||
      record->timing_record_sequence == 0u ||
      record->transaction_record_sequence == 0u ||
      !text_present(record->event) || !text_present(record->run_identity) ||
      !text_present(record->build_identity) ||
      !text_present(record->profile_identity) || !text_present(record->reason))
    return -1;
  return snprintf(
      output, output_size,
      "AT2,2,%lu,%lu,%s,%llu,%s,%s,%s,%s,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%u,%u,%lu,%lu,%s\r\n",
      static_cast<unsigned long>(record->timing_record_sequence),
      static_cast<unsigned long>(record->transaction_record_sequence),
      record->event,
      static_cast<unsigned long long>(record->event_timestamp_ticks),
      kExtendedTimer0Domain, record->run_identity, record->build_identity,
      record->profile_identity, static_cast<unsigned long>(record->session_id),
      static_cast<unsigned long>(record->request_sequence),
      static_cast<unsigned long>(record->decision_sequence),
      static_cast<unsigned long>(record->source_first_sequence),
      static_cast<unsigned long>(record->source_last_sequence),
      static_cast<unsigned long>(record->authorization_sequence),
      static_cast<unsigned long>(record->nonce), record->accepted_code,
      record->applied_code,
      static_cast<unsigned long>(record->application_sequence),
      static_cast<unsigned long>(record->dac_epoch), record->reason);
}

int otis_format_active_hybrid_timing_v2(
    char *output, size_t output_size,
    const OtisActiveHybridTimingV2 *record) {
  if (output == nullptr || output_size == 0u || record == nullptr ||
      record->timing_record_sequence == 0u ||
      record->hybrid_record_sequence == 0u ||
      record->decision_sequence == 0u || !text_present(record->run_identity) ||
      !text_present(record->build_identity) ||
      !text_present(record->profile_identity) || !text_present(record->reason))
    return -1;
  return snprintf(
      output, output_size,
      "AH2,2,%lu,%lu,%lu,%llu,%s,%s,%s,%s,%lu,%lu,%lu,%s\r\n",
      static_cast<unsigned long>(record->timing_record_sequence),
      static_cast<unsigned long>(record->hybrid_record_sequence),
      static_cast<unsigned long>(record->decision_sequence),
      static_cast<unsigned long long>(record->decision_timestamp_ticks),
      kExtendedTimer0Domain, record->run_identity, record->build_identity,
      record->profile_identity,
      static_cast<unsigned long>(record->capture_session),
      static_cast<unsigned long>(record->source_first_sequence),
      static_cast<unsigned long>(record->source_last_sequence), record->reason);
}
