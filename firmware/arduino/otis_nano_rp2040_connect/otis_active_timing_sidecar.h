#ifndef OTIS_ACTIVE_TIMING_SIDECAR_H
#define OTIS_ACTIVE_TIMING_SIDECAR_H

#include <stddef.h>
#include <stdint.h>

struct OtisActiveTransactionTimingV2 {
  uint32_t timing_record_sequence;
  uint32_t transaction_record_sequence;
  const char *event;
  uint64_t event_timestamp_ticks;
  const char *run_identity;
  const char *build_identity;
  const char *profile_identity;
  uint32_t session_id;
  uint32_t request_sequence;
  uint32_t decision_sequence;
  uint32_t source_first_sequence;
  uint32_t source_last_sequence;
  uint32_t authorization_sequence;
  uint32_t nonce;
  uint16_t accepted_code;
  uint16_t applied_code;
  uint32_t application_sequence;
  uint32_t dac_epoch;
  const char *reason;
};

struct OtisActiveHybridTimingV2 {
  uint32_t timing_record_sequence;
  uint32_t hybrid_record_sequence;
  uint32_t decision_sequence;
  uint64_t decision_timestamp_ticks;
  const char *run_identity;
  const char *build_identity;
  const char *profile_identity;
  uint32_t capture_session;
  uint32_t source_first_sequence;
  uint32_t source_last_sequence;
  const char *reason;
};

const char *otis_active_transaction_timing_v2_csv_header(void);
const char *otis_active_hybrid_timing_v2_csv_header(void);

int otis_format_active_transaction_timing_v2(
    char *output, size_t output_size,
    const OtisActiveTransactionTimingV2 *record);
int otis_format_active_hybrid_timing_v2(
    char *output, size_t output_size,
    const OtisActiveHybridTimingV2 *record);

#endif
