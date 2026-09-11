#include <cassert>
#include <cstdint>
#include <cstdio>

#include "otis_dual_core_partition.h"
#include "otis_phase_preview_live.h"
#include "otis_phase_preview_format.h"
#include "reference_selection_fixture.h"

namespace {

uint32_t published_previews = 0u;
OtisPhasePreviewRecordMessage last_phase_record = {};

}  // namespace

bool otis_dual_core_publish_phase_preview(
    const OtisPhasePreviewRecordMessage *message) {
  assert(message != nullptr);
  last_phase_record = *message;
  char frame[2048];
  size_t length = 0;
  assert(otis_phase_preview_format_rph(message, frame, sizeof(frame), &length));
  std::printf("%s", frame);
  assert(otis_phase_preview_format_phe(message, frame, sizeof(frame), &length));
  std::printf("%s", frame);
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

  ReferenceSelectionFixture trace;
  trace.acquire();
  otis_phase_preview_live_on_reference_selection(&trace.selection, trace.extended_ticks, false);
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

  // Setup bound after acquisition: the actual first opening is preserved,
  // and the first accepted span contributes immediately.
  const auto initial_opening = trace.raw;
  trace.advance(1000000u, 10000001u);
  otis_phase_preview_live_on_reference_selection(&trace.selection, trace.extended_ticks, false);
  assert(last_phase_record.observation_sequence == 1u);
  assert(last_phase_record.opening_snapshot_sequence == initial_opening.snapshot_sequence);
  assert(last_phase_record.opening_reference_sequence == initial_opening.reference_sequence);
  assert(last_phase_record.relative_phase_cycles == 1);
  const uint32_t before_early = published_previews;
  trace.advance(246294u, 2462937u);
  otis_phase_preview_live_on_reference_selection(&trace.selection, trace.extended_ticks, false);
  assert(published_previews == before_early);
  trace.advance(753707u, 7537063u);
  otis_phase_preview_live_on_reference_selection(&trace.selection, trace.extended_ticks, false);
  for (uint32_t span = 2u; span < 600u; ++span) {
    trace.advance();
    otis_phase_preview_live_on_reference_selection(&trace.selection, trace.extended_ticks, false);
  }
  assert(published_previews == 600u);
  assert(last_phase_record.phase_epoch == 1u);
  assert(last_phase_record.observation_sequence == 600u);
  assert(last_phase_record.relative_phase_cycles == 1);
  assert(last_phase_record.frequency_available);
  assert(last_phase_record.frequency_observation_event);
  assert(last_phase_record.frequency_error_hz == 1.0 / 600.0);
  assert(last_phase_record.acceptance_epoch == 1u);
  assert(last_phase_record.accepted_boundary_ordinal == 600u);

  OtisPhasePreviewActiveSnapshot active = {};
  assert(otis_phase_preview_live_get_active_snapshot(&active));
  assert(active.recorder_published && active.phase_continuous && active.phase_current);
  assert(active.phase_epoch == 1u && active.observation_sequence == 600u);
  assert(active.acceptance_epoch == 1u && active.accepted_boundary_ordinal == 600u);
  assert(active.applied_code == 0xA850u && active.dac_epoch == 2u);

  assert(otis_phase_preview_live_update_applied_code(0xA84Fu, 3u));
  trace.advance();
  otis_phase_preview_live_on_reference_selection(&trace.selection, trace.extended_ticks, false);
  assert(last_phase_record.phase_epoch == 1u);
  assert(last_phase_record.observation_sequence == 601u);
  assert(last_phase_record.relative_phase_cycles == 1);
  assert(!last_phase_record.frequency_available);
  assert(otis_phase_preview_live_get_active_snapshot(&active));
  assert(active.applied_code == 0xA84Fu && active.dac_epoch == 3u);
  trace.advance();
  otis_phase_preview_live_on_reference_selection(&trace.selection, trace.extended_ticks, true);
  assert(last_phase_record.phase_epoch == 1u);
  assert(otis_phase_preview_live_get_active_snapshot(&active));
  assert(active.phase_step_detected);

  // A real raw gap terminates the epoch. Eight fresh intervals establish
  // only the new anchor; no acquisition interval contributes phase.
  ++trace.raw.snapshot_sequence;
  trace.advance();
  otis_phase_preview_live_on_reference_selection(&trace.selection, trace.extended_ticks, false);
  assert(!last_phase_record.phase_accepted);
  assert(otis_phase_preview_live_get_active_snapshot(&active));
  assert(!active.phase_current && !active.phase_continuous);
  trace.advance();
  for (uint32_t i = 0; i < OTIS_REFERENCE_ACCEPTANCE_POLICY.acquisition_intervals; ++i) {
    trace.advance();
    otis_phase_preview_live_on_reference_selection(&trace.selection, trace.extended_ticks, false);
  }
  assert(last_phase_record.phase_epoch == 2u);
  assert(last_phase_record.observation_sequence == 0u);
  assert(last_phase_record.relative_phase_cycles == 0);
  trace.advance();
  otis_phase_preview_live_on_reference_selection(&trace.selection, trace.extended_ticks, false);
  assert(last_phase_record.observation_sequence == 1u);
  return 0;
}
