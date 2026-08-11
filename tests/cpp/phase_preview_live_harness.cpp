#include <assert.h>
#include <string.h>

#include "otis_phase_preview_live.h"
#include "otis_dual_core_partition.h"

int main() {
  otis_dual_core_partition_reset();
  otis_dual_core_set_timing_owner_active(true);
  assert(otis_phase_preview_live_begin(0xA950u, 0u));

  OtisPpsCountBoundaryObservation first = {};
  first.session = 7u;
  first.sequence = 1u;
  first.reference_sequence = 101u;
  first.pps_timestamp_ticks = 16000000ull;
  first.cumulative_down_counter = 0xF0000000u;
  otis_phase_preview_live_on_boundary(&first, 0u, 0u, false, true, false);
  OtisPhasePreviewRecordMessage record = {};
  assert(otis_dual_core_take_phase_preview(&record));
  assert(record.preview_sequence == 1u);
  assert(record.phase_epoch == 1u);
  assert(record.observation_sequence == 0u);
  assert(record.capture_session == 7u);
  assert(record.opening_snapshot_sequence == 1u);
  assert(record.closing_snapshot_sequence == 1u);
  assert(strcmp(record.phase_qualification_state, "epoch_open") == 0);
  assert(strcmp(record.phase_reason, "reset") == 0);
  assert(record.actual_applied_code == 0xA950u);

  OtisPpsCountBoundaryObservation second = first;
  second.sequence = 2u;
  second.reference_sequence = 102u;
  second.pps_timestamp_ticks += 16000000ull;
  second.cumulative_down_counter -= 10000001u;
  otis_phase_preview_live_on_boundary(&second, 0u, 10000001u, true, true,
                                      false);
  assert(otis_dual_core_take_phase_preview(&record));
  assert(record.preview_sequence == 2u);
  assert(record.observation_sequence == 1u);
  assert(record.opening_snapshot_sequence == 1u);
  assert(record.closing_snapshot_sequence == 2u);
  assert(record.interval_available);
  assert(record.interval_edges == 10000001u);
  assert(record.edge_error_cycles == 1);
  assert(record.relative_phase_cycles == 1);
  assert(strcmp(record.phase_qualification_state, "qualified") == 0);
  assert(record.phase_reason[0] == '\0');
  assert(!record.raw_frequency_available);
  assert(!record.modeled_frequency_available);
  assert(record.frequency_estimate_age_s == 0.0);
  assert(!record.counterfactual_decision);

  OtisPpsCountBoundaryObservation rolling = second;
  for (uint32_t sequence = 3u; sequence <= 601u; ++sequence) {
    rolling.sequence = sequence;
    rolling.reference_sequence = 100u + sequence;
    rolling.pps_timestamp_ticks += 16000000ull;
    rolling.cumulative_down_counter -= 10000000u;
    otis_phase_preview_live_on_boundary(&rolling, 0u, 10000000u, true, true,
                                        false);
    assert(otis_dual_core_take_phase_preview(&record));
  }
  assert(record.observation_sequence == 600u);
  assert(record.raw_frequency_available);
  assert(record.modeled_frequency_available);
  assert(record.frequency_observation_event);
  assert(record.frequency_estimate_age_s == 0.0);

  rolling.sequence = 602u;
  rolling.reference_sequence = 702u;
  rolling.pps_timestamp_ticks += 16000000ull;
  rolling.cumulative_down_counter -= 10000000u;
  otis_phase_preview_live_on_boundary(&rolling, 0u, 10000000u, true, true,
                                      false);
  assert(otis_dual_core_take_phase_preview(&record));
  assert(record.raw_frequency_available);
  assert(record.modeled_frequency_available);
  assert(!record.frequency_observation_event);
  assert(record.frequency_estimate_age_s == 1.0);

  // Core 0 may only publish a confirmed, characterized code with a forward
  // epoch.  Core 1 must consume the pair as one boundary-time context.
  assert(!otis_phase_preview_live_update_applied_code(0xA7FFu, 1u));
  assert(!otis_phase_preview_live_update_applied_code(0xA951u, 0u));
  assert(otis_phase_preview_live_update_applied_code(0xA951u, 1u));
  assert(otis_phase_preview_live_update_applied_code(0xA951u, 1u));
  assert(!otis_phase_preview_live_update_applied_code(0xA952u, 0u));

  rolling.sequence = 603u;
  rolling.reference_sequence = 703u;
  rolling.pps_timestamp_ticks += 16000000ull;
  rolling.cumulative_down_counter -= 10000000u;
  otis_phase_preview_live_on_boundary(&rolling, 0u, 10000000u, true, true,
                                      false);
  assert(otis_dual_core_take_phase_preview(&record));
  assert(record.dac_epoch == 1u);
  assert(record.actual_applied_code == 0xA951u);
  assert(!record.modeled_frequency_available);
  assert(strcmp(record.decision_reason, "dac_epoch_bumpless_reseed") == 0);

  OtisPhasePreviewLiveStatus status = {};
  otis_phase_preview_live_get_status(&status);
  assert(status.initialized);
  assert(status.static_code_bound);
  assert(status.static_code == 0xA950u);
  assert(status.applied_code_bound);
  assert(status.applied_code == 0xA951u);
  assert(status.dac_epoch == 1u);
  assert(status.published_records == 603u);
  assert(status.last_phase_epoch == 1u);
  assert(status.last_observation_sequence == 602u);
  return 0;
}
