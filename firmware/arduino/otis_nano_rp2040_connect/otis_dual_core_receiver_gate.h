#ifndef OTIS_DUAL_CORE_RECEIVER_GATE_H
#define OTIS_DUAL_CORE_RECEIVER_GATE_H

#include <stdint.h>

#include "otis_dual_core_contract.h"
#include "otis_timebase_math.h"

static inline bool otis_dual_core_receiver_qualified_for_control_at(
    const OtisReceiverQualificationMessage *receiver, uint64_t now_ticks,
    uint32_t maximum_metadata_age_ms) {
  if (receiver == nullptr || receiver->published_ticks == 0u) return false;
  const uint64_t local_age_ticks = otis_timer0_interval_ticks(
      receiver->published_ticks, now_ticks);
  const uint64_t maximum_age_ticks =
      static_cast<uint64_t>(maximum_metadata_age_ms) * 1000ull *
      OTIS_RP2040_TIMER0_TICKS_PER_US;
  return receiver->control_eligible && receiver->identity_stable &&
         receiver->gsa_checksum_requalified && receiver->gsa_3d &&
         receiver->metadata_age_ms <= maximum_metadata_age_ms &&
         local_age_ticks <= maximum_age_ticks;
}

#endif
