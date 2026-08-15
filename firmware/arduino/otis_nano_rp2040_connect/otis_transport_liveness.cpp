#include "otis_transport_liveness.h"

void otis_transport_liveness_reset(OtisTransportLiveness *liveness,
                                   uint32_t now_ms,
                                   uint64_t written_bytes) {
  if (liveness == nullptr) return;
  *liveness = {};
  liveness->state = OtisTransportLivenessState::Ready;
  liveness->obstruction_started_ms = now_ms;
  liveness->last_progress_ms = now_ms;
  liveness->last_written_bytes = written_bytes;
}

bool otis_transport_liveness_observe(OtisTransportLiveness *liveness,
                                     uint32_t now_ms,
                                     bool frame_pending,
                                     uint64_t written_bytes) {
  if (liveness == nullptr) return false;
  if (liveness->state == OtisTransportLivenessState::Faulted) return false;
  if (!frame_pending) {
    if (liveness->state == OtisTransportLivenessState::FrameObstructed &&
        liveness->completed_obstructions != UINT32_MAX)
      liveness->completed_obstructions++;
    liveness->state = OtisTransportLivenessState::Ready;
    liveness->obstruction_started_ms = now_ms;
    liveness->last_progress_ms = now_ms;
    liveness->last_written_bytes = written_bytes;
    return true;
  }
  if (liveness->state == OtisTransportLivenessState::Ready) {
    liveness->state = OtisTransportLivenessState::FrameObstructed;
    liveness->obstruction_started_ms = now_ms;
    liveness->last_progress_ms = now_ms;
    liveness->last_written_bytes = written_bytes;
    return true;
  }
  if (written_bytes != liveness->last_written_bytes) {
    liveness->last_written_bytes = written_bytes;
    liveness->last_progress_ms = now_ms;
  }
  // Bound total Core 0 consumer absence, not merely the interval between
  // bytes.  A peer that accepts one occasional byte cannot keep a partial
  // frame (and its queue ownership) alive indefinitely.
  if (static_cast<uint32_t>(now_ms - liveness->obstruction_started_ms) >=
      OTIS_MAXIMUM_SUPPORTED_TX_OBSTRUCTION_MS) {
    liveness->state = OtisTransportLivenessState::Faulted;
    return false;
  }
  return true;
}

bool otis_transport_liveness_note_carrier_absent(
    OtisTransportLiveness *liveness, uint32_t now_ms,
    uint64_t written_bytes) {
  if (liveness == nullptr ||
      liveness->state == OtisTransportLivenessState::Faulted)
    return false;
  otis_transport_liveness_reset(liveness, now_ms, written_bytes);
  return true;
}

bool otis_transport_liveness_faulted(
    const OtisTransportLiveness *liveness) {
  return liveness != nullptr &&
         liveness->state == OtisTransportLivenessState::Faulted;
}
