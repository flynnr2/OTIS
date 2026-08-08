#ifndef OTIS_CX317_DUAL_CORE_STATE_H
#define OTIS_CX317_DUAL_CORE_STATE_H

#include "otis_cx317_preview_live.h"
#include "otis_dual_core_contract.h"

// Core 1 receives both periodic Core 0 DAC snapshots and transaction-specific
// actuator acknowledgements on the same FIFO.  A successful applied
// acknowledgement is newer than every periodic snapshot ahead of it and must
// advance the cached state before the next active-continuity health check.
inline bool otis_cx317_dual_core_static_state_on_periodic(
    OtisCx317StaticCodeState *state,
    const OtisAppliedDacStateMessage *message) {
  if (state == nullptr || message == nullptr) return false;
  const bool changed = state->available && message->requested_applied_match &&
                       state->applied_code != message->applied_code;
  state->available = message->requested_applied_match;
  state->requested_applied_match = message->requested_applied_match;
  state->i2c_ok = message->initialized && message->i2c_ok;
  state->applied_code = message->applied_code;
  return changed;
}

inline bool otis_cx317_dual_core_static_state_on_applied_ack(
    OtisCx317StaticCodeState *state,
    const OtisCrossCoreActuatorAck *acknowledgement,
    bool transaction_acknowledged) {
  if (state == nullptr || acknowledgement == nullptr ||
      !transaction_acknowledged ||
      acknowledgement->kind != OtisActuatorAckKind::Applied ||
      !acknowledgement->i2c_ok || acknowledgement->clamped ||
      acknowledgement->ambiguous ||
      acknowledgement->requested_code != acknowledgement->accepted_code ||
      acknowledgement->requested_code != acknowledgement->applied_code)
    return false;
  state->available = true;
  state->requested_applied_match = true;
  state->i2c_ok = true;
  state->applied_code = acknowledgement->applied_code;
  return true;
}

#endif
