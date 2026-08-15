#ifndef OTIS_TRANSPORT_LIVENESS_H
#define OTIS_TRANSPORT_LIVENESS_H

#include <stdint.h>

// The carrier is part of the supported instrument. This is the maximum
// temporary interval for which one device-TX frame may remain pending,
// deliberately shorter than the smallest non-droppable observation/preview
// queue horizon. Intermittent byte progress does not extend the interval.
constexpr uint32_t OTIS_MAXIMUM_SUPPORTED_TX_OBSTRUCTION_MS = 2000u;

enum class OtisTransportLivenessState : uint8_t {
  Ready,
  FrameObstructed,
  Faulted,
};

struct OtisTransportLiveness {
  OtisTransportLivenessState state;
  uint32_t obstruction_started_ms;
  uint32_t last_progress_ms;
  uint64_t last_written_bytes;
  uint32_t completed_obstructions;
};

void otis_transport_liveness_reset(OtisTransportLiveness *liveness,
                                   uint32_t now_ms,
                                   uint64_t written_bytes);
bool otis_transport_liveness_observe(OtisTransportLiveness *liveness,
                                     uint32_t now_ms,
                                     bool frame_pending,
                                     uint64_t written_bytes);
// A missing USB carrier is an owner handoff boundary, not evidence of an
// obstructed present carrier. It may clear an in-progress obstruction before
// its deadline, but it must never recover an already faulted transport.
bool otis_transport_liveness_note_carrier_absent(
    OtisTransportLiveness *liveness, uint32_t now_ms,
    uint64_t written_bytes);
bool otis_transport_liveness_faulted(
    const OtisTransportLiveness *liveness);

#endif
