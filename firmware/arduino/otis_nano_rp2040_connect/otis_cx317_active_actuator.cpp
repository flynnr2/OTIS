#include "otis_cx317_active_actuator.h"

#include "otis_config.h"
#include "otis_dac_ad5693r.h"

OtisCx317AppliedAck otis_cx317_active_actuator_apply_once(
    const OtisCx317ActionableRequest *request,
    const OtisCx317AcceptedRequest *accepted, uint16_t application_sequence,
    uint32_t now_s) {
  OtisCx317AppliedAck acknowledgement = {};
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  if (request == nullptr || accepted == nullptr) {
    acknowledgement.ambiguous = true;
    return acknowledgement;
  }
  acknowledgement.request_sequence = request->request_sequence;
  acknowledgement.authorization_sequence = request->authorization_sequence;
  acknowledgement.nonce = request->nonce;
  acknowledgement.requested_code = request->requested_code;
  acknowledgement.accepted_code = accepted->accepted_code;
  acknowledgement.application_sequence = application_sequence;
  acknowledgement.application_timestamp_s = now_s;
  const uint16_t clamped = otis_dac_ad5693r_clamp_code(request->requested_code);
  acknowledgement.clamped = clamped != request->requested_code;
  if (!request->actionable || accepted->actionable ||
      accepted->request_sequence != request->request_sequence ||
      accepted->authorization_sequence != request->authorization_sequence ||
      accepted->nonce != request->nonce ||
      accepted->accepted_code != request->requested_code ||
      acknowledgement.clamped || !otis_dac_ad5693r_is_enabled() ||
      !otis_dac_ad5693r_is_initialized()) {
    return acknowledgement;
  }
  // This is the sole controller-to-DAC call site and it executes at most once
  // for the accepted request. Any failure is acknowledged after one attempt.
  acknowledgement.i2c_ok = otis_dac_ad5693r_set_raw(request->requested_code);
  OtisDacAd5693rStatus status;
  otis_dac_ad5693r_get_status(&status);
  acknowledgement.applied_code = status.last_applied_code;
  acknowledgement.ambiguous =
      acknowledgement.i2c_ok &&
      (!status.applied_code_known || !status.last_write_ok ||
       status.last_requested_code != request->requested_code ||
       status.last_applied_code != request->requested_code);
#else
  (void)request;
  (void)accepted;
  (void)application_sequence;
  (void)now_s;
#endif
  return acknowledgement;
}
