#ifndef OTIS_CX321_PLANT_SIGN_FORMAT_H
#define OTIS_CX321_PLANT_SIGN_FORMAT_H

#include <stddef.h>
#include <stdint.h>

#include "otis_cx321_plant_sign.h"

struct OtisCx321PlantSignFormatRecord {
  uint32_t record_sequence;
  const char *event;
  uint64_t event_ticks;
  const char *run_identity;
  const char *build_identity;
  const char *profile_identity;
  uint32_t capture_session;
  const char *policy_sha256;
  const char *plant_sign_gate_sha256;
  const char *identification_estimator_sha256;
  const char *identification_estimator_config_sha256;
  const char *natural_frequency_estimator_sha256;
  uint64_t setup_application_ticks;
  uint16_t setup_applied_code;
  const char *state_before;
  const char *state_after;
  const char *reason;
  OtisCx321PlantSignEstimate estimate;
  bool have_estimate;
  const char *tight_state;
  OtisCx321PlantSignDecision decision;
  uint32_t request_sequence;
  uint32_t acceptance_sequence;
  uint32_t application_sequence;
  uint16_t accepted_code;
  uint16_t applied_code;
  uint64_t application_ticks;
  uint32_t dac_epoch;
  OtisCx321PlantSignResponse response;
  uint32_t acknowledged_response_record_sequence;
  bool host_replay_exact;
  const char *replay_attestation_sha256;
  uint16_t global_correction_count;
  uint16_t global_cumulative_movement_codes;
  uint64_t global_last_application_ticks;
  uint16_t natural_chatter_origin_code;
  uint16_t natural_cumulative_movement_codes;
  uint8_t natural_direction_count;
  bool attested;
};

const char *otis_cx321_plant_sign_csv_header(void);

bool otis_cx321_plant_sign_format_record(
    const OtisCx321PlantSignFormatRecord *record, char *output,
    size_t output_capacity, uint16_t *output_length);

#endif
