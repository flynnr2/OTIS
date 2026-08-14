#ifndef OTIS_CX319_RANGE_MAP_EPOCH_H
#define OTIS_CX319_RANGE_MAP_EPOCH_H

#include <stdint.h>

#include "otis_cx317_preview_live.h"
#include "otis_dual_core_contract.h"

// Accept one exact Core 0 manual-application acknowledgement and advance the
// Part A epoch even when the requested code equals the preceding code. The
// caller must propagate the returned identity to every preview consumer.
inline bool otis_cx319_range_map_accept_manual_application(
    OtisCx317StaticCodeState *state,
    const OtisAppliedDacStateMessage *application, uint32_t *dac_epoch,
    uint16_t *applied_code, uint32_t *applied_epoch) {
  if (state == nullptr || application == nullptr || dac_epoch == nullptr ||
      applied_code == nullptr || applied_epoch == nullptr ||
      !application->initialized || !application->i2c_ok ||
      !application->requested_applied_match ||
      application->requested_code != application->applied_code)
    return false;
  state->available = true;
  state->requested_applied_match = true;
  state->i2c_ok = true;
  state->applied_code = application->applied_code;
  ++(*dac_epoch);
  *applied_code = application->applied_code;
  *applied_epoch = *dac_epoch;
  return true;
}

#endif
