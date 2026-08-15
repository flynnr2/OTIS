#include "otis_phase_preview_transport.h"

#include <stddef.h>
#include <stdint.h>

#include "otis_config.h"
#include "otis_phase_preview_format.h"
#include "otis_dual_core_partition.h"
#include "otis_transport_serial.h"

namespace {

constexpr size_t kFrameCapacity = 2048u;
constexpr size_t kTransportChunkLimit = 192u;

OtisPhasePreviewRecordMessage active_message = {};
char frame[kFrameCapacity] = {};
size_t frame_length = 0u;
size_t frame_sent = 0u;
uint8_t record_phase = 0u;
bool message_active = false;

bool format_current_phase(void) {
  frame_length = 0u;
  frame_sent = 0u;
  if (record_phase == 0u)
    return otis_phase_preview_format_rph(&active_message, frame, sizeof(frame),
                                 &frame_length);
  if (record_phase == 1u)
    return otis_phase_preview_format_phe(&active_message, frame, sizeof(frame),
                                 &frame_length);
  if (record_phase == 2u)
    return otis_phase_preview_format_hpr(&active_message, frame, sizeof(frame),
                                 &frame_length);
  return false;
}

}  // namespace

void otis_phase_preview_transport_emit_headers(void) {
#if OTIS_ENABLE_PHASE_FREQUENCY_PREVIEW
  otis_transport_write_cstr(otis_phase_preview_rph_header());
  otis_transport_write_cstr(otis_phase_preview_phe_header());
  otis_transport_write_cstr(otis_phase_preview_hpr_header());
#endif
}

bool otis_phase_preview_transport_busy(void) {
#if OTIS_ENABLE_PHASE_FREQUENCY_PREVIEW
  if (message_active) return true;
  OtisDualCoreQueueStats stats = {};
  otis_dual_core_get_stats(&stats);
  return stats.phase_preview_depth != 0u;
#else
  return false;
#endif
}

bool otis_phase_preview_transport_frame_active(void) {
#if OTIS_ENABLE_PHASE_FREQUENCY_PREVIEW
  return message_active;
#else
  return false;
#endif
}

bool otis_phase_preview_transport_abandon_active_frame(void) {
#if OTIS_ENABLE_PHASE_FREQUENCY_PREVIEW
  const bool abandoned = message_active;
  active_message = {};
  frame_length = 0u;
  frame_sent = 0u;
  record_phase = 0u;
  message_active = false;
  return abandoned;
#else
  return false;
#endif
}

void otis_phase_preview_transport_service(void) {
#if OTIS_ENABLE_PHASE_FREQUENCY_PREVIEW
  if (!message_active) {
    if (!otis_dual_core_take_phase_preview(&active_message)) return;
    record_phase = 0u;
    message_active = true;
    if (!format_current_phase()) {
      otis_dual_core_latch_fault(OtisPartitionFault::PhasePreviewFault);
      active_message = {};
      message_active = false;
      return;
    }
  }
  const size_t available = otis_transport_available_for_write();
  if (available == 0u) return;
  const size_t remaining = frame_length - frame_sent;
  size_t chunk = remaining < available ? remaining : available;
  if (chunk > kTransportChunkLimit) chunk = kTransportChunkLimit;
  frame_sent += otis_transport_write_bytes(
      reinterpret_cast<const uint8_t *>(frame) + frame_sent, chunk);
  if (frame_sent != frame_length) return;

  ++record_phase;
  frame_length = 0u;
  frame_sent = 0u;
  if (record_phase < 3u) {
    if (!format_current_phase()) {
      otis_dual_core_latch_fault(OtisPartitionFault::PhasePreviewFault);
      active_message = {};
      message_active = false;
    }
    return;
  }
  active_message = {};
  record_phase = 0u;
  message_active = false;
#endif
}
