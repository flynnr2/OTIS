#include <cassert>
#include <cstdint>

#include "otis_dual_core_partition.h"
#include "otis_phase_preview_live.h"

namespace {

uint32_t published_previews = 0u;
OtisPhasePreviewRecordMessage last_phase_record = {};

}  // namespace

bool otis_dual_core_publish_phase_preview(
    const OtisPhasePreviewRecordMessage *message) {
  assert(message != nullptr);
  last_phase_record = *message;
  ++published_previews;
  return true;
}

void otis_dual_core_note_timing_progress(OtisTimingProgressPhase phase,
                                         uint64_t now_ticks) {
  (void)phase;
  (void)now_ticks;
}

void otis_dual_core_latch_fault(OtisPartitionFault fault) { (void)fault; }

bool otis_dual_core_fail_static(void) { return false; }

int main() {
  assert(otis_phase_preview_live_begin());

  OtisPhasePreviewLiveStatus status = {};
  otis_phase_preview_live_get_status(&status);
  assert(status.initialized);
  assert(!status.applied_code_bound);
  assert(status.published_records == 0u);

  OtisPpsCountBoundaryObservation pre_setup = {};
  otis_phase_preview_live_on_boundary(&pre_setup, 0u, 10000000u, true,
                                      true, false);
  otis_phase_preview_live_get_status(&status);
  assert(!status.applied_code_bound);
  assert(status.published_records == 0u);
  assert(published_previews == 0u);

  assert(!otis_phase_preview_live_update_applied_code(0xA84Du, 0u));
  assert(!otis_phase_preview_live_update_applied_code(0xA7FFu, 1u));
  assert(otis_phase_preview_live_update_applied_code(0xA84Du, 1u));
  otis_phase_preview_live_get_status(&status);
  assert(status.initialized);
  assert(status.applied_code_bound);
  assert(status.applied_code == 0xA84Du);
  assert(status.dac_epoch == 1u);

  assert(otis_phase_preview_live_update_applied_code(0xA84Du, 1u));
  assert(!otis_phase_preview_live_update_applied_code(0xA850u, 1u));
  assert(otis_phase_preview_live_update_applied_code(0xA850u, 2u));
  otis_phase_preview_live_get_status(&status);
  assert(status.applied_code_bound);
  assert(status.applied_code == 0xA850u);
  assert(status.dac_epoch == 2u);

  OtisPpsCountBoundaryObservation observation = {};
  observation.session = 1u;
  observation.cumulative_down_counter = 0xF0000000u;
  for (uint32_t sequence = 1u; sequence <= 601u; ++sequence) {
    observation.sequence = sequence;
    observation.reference_sequence = sequence;
    observation.pps_timestamp_ticks =
        static_cast<uint32_t>(sequence * 1000000ull);
    if (sequence > 1u)
      observation.cumulative_down_counter -= 10000000u;
    otis_phase_preview_live_on_boundary(&observation, 0u, 10000000u, true,
                                        true, false);
  }
  assert(published_previews == 601u);
  assert(last_phase_record.phase_epoch == 1u);
  assert(last_phase_record.observation_sequence == 600u);
  assert(last_phase_record.relative_phase_cycles == 0);
  assert(last_phase_record.frequency_available);
  assert(last_phase_record.frequency_observation_event);
  assert(last_phase_record.frequency_error_hz == 0.0);

  OtisPhasePreviewActiveSnapshot active = {};
  assert(otis_phase_preview_live_get_active_snapshot(&active));
  assert(active.recorder_published);
  assert(active.phase_continuous);
  assert(active.phase_current);
  assert(active.phase_epoch == 1u);
  assert(active.observation_sequence == 600u);
  assert(active.applied_code == 0xA850u);
  assert(active.dac_epoch == 2u);

  assert(otis_phase_preview_live_update_applied_code(0xA84Fu, 3u));
  observation.sequence = 602u;
  observation.reference_sequence = 602u;
  observation.pps_timestamp_ticks =
      static_cast<uint32_t>(602ull * 1000000ull);
  observation.cumulative_down_counter -= 10000000u;
  otis_phase_preview_live_on_boundary(&observation, 0u, 10000000u, true,
                                      true, false);
  assert(last_phase_record.phase_epoch == 1u);
  assert(last_phase_record.observation_sequence == 601u);
  assert(!last_phase_record.frequency_available);
  assert(otis_phase_preview_live_get_active_snapshot(&active));
  assert(active.applied_code == 0xA84Fu);
  assert(active.dac_epoch == 3u);

  observation.sequence = 603u;
  observation.reference_sequence = 603u;
  observation.pps_timestamp_ticks =
      static_cast<uint32_t>(603ull * 1000000ull);
  observation.cumulative_down_counter -= 10000000u;
  otis_phase_preview_live_on_boundary(&observation, 0u, 10000000u, true,
                                      true, true);
  assert(last_phase_record.phase_epoch == 1u);
  assert(otis_phase_preview_live_get_active_snapshot(&active));
  assert(active.phase_step_detected);

  return 0;
}
