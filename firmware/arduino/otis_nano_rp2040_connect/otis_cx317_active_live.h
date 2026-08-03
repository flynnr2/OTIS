#ifndef OTIS_CX317_ACTIVE_LIVE_H
#define OTIS_CX317_ACTIVE_LIVE_H

#include <stdint.h>

#include "otis_cx317_active_transaction.h"
#include "otis_status_emit.h"

struct OtisCx317ActiveLiveHealth {
  uint32_t session_id;
  bool gnss_metadata_valid;
  bool gnss_identity_stable;
  bool gnss_3d_evidence;
  bool raw_pps_valid;
  bool count_valid;
  bool estimator_valid;
  bool model_applicable;
  bool temperature_valid;
  bool applied_code_confirmed;
  uint16_t applied_code;
  bool abort_path_live;
  uint16_t selected_interval_count;
};

struct OtisCx317ActiveLiveDecision {
  uint32_t decision_sequence;
  uint32_t source_first_sequence;
  uint32_t source_last_sequence;
  uint32_t timestamp_s;
  uint16_t current_applied_code;
  int32_t requested_delta_codes;
  uint16_t requested_code;
  double frequency_error_hz;
  bool preview_available;
};

struct OtisCx317ActiveLiveOutcome {
  bool request_created;
  bool application_attempted;
  bool applied;
  bool response_recorded;
  bool faulted;
  uint16_t requested_code;
  uint16_t applied_code;
  uint32_t request_sequence;
  OtisCx317ResponseClass response_class;
  const char *reason;
};

bool otis_cx317_active_live_begin(void);
void otis_cx317_active_live_emit_headers(void);
void otis_cx317_active_live_update_health(
    const OtisCx317ActiveLiveHealth *health, uint32_t now_s);
void otis_cx317_active_live_service(uint32_t now_s);
bool otis_cx317_active_live_capture_lease(uint32_t lease_sequence,
                                         uint32_t now_s);
bool otis_cx317_active_live_arm(uint32_t authorization_sequence,
                               uint32_t nonce, uint32_t expires_s,
                               uint32_t now_s);
void otis_cx317_active_live_abort(const char *reason);
bool otis_cx317_active_live_acknowledge_evidence(uint32_t request_sequence,
                                                 uint32_t phase_sequence,
                                                 uint32_t now_s);
bool otis_cx317_active_live_manual_start_allowed(uint16_t requested_code);
void otis_cx317_active_live_note_manual_start(uint16_t requested_code,
                                              bool i2c_ok,
                                              uint32_t now_s);
void otis_cx317_active_live_on_decision(
    const OtisCx317ActiveLiveDecision *decision,
    OtisCx317ActiveLiveOutcome *outcome);
bool otis_cx317_active_live_take_application_outcome(
    OtisCx317ActiveLiveOutcome *outcome);
bool otis_cx317_active_live_complete_application_evidence(
    uint32_t request_sequence, bool estimator_history_reset, uint32_t now_s);
bool otis_cx317_active_live_transport_busy(void);
void otis_cx317_active_live_service_transport(void);
void otis_cx317_active_live_emit_status(OtisStatusEmitContext *context,
                                        uint32_t now_s);
const char *otis_cx317_active_live_run_identity(void);
uint16_t otis_cx317_active_live_start_code(void);

#endif
