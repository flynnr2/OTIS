#include <assert.h>
#include <stdint.h>

#include "otis_dual_core_receiver_gate.h"
#include "otis_oscillator_snapshot_estimator.h"
#include "otis_selected_phase_frequency_preview_engine.h"
#include "reference_selection_fixture.h"

namespace {

constexpr uint32_t kNominalD8Edges = 10000000u;
constexpr uint32_t kMeasuredD8Edges = kNominalD8Edges + 1u;
constexpr uint32_t kMetadataLimitMs = 100u;

OtisReceiverQualificationMessage qualified_receiver(uint64_t published_ticks,
                                                     uint32_t metadata_age_ms) {
  OtisReceiverQualificationMessage receiver = {};
  receiver.published_ticks = published_ticks;
  receiver.metadata_age_ms = metadata_age_ms;
  receiver.control_eligible = true;
  receiver.identity_stable = true;
  receiver.gsa_checksum_requalified = true;
  receiver.gsa_3d = true;
  return receiver;
}

}  // namespace

int main() {
  // Receiver metadata is a control qualification.  Its causal age includes
  // both receiver-observed age and the Core 0->Core 1 publication delay.
  OtisReceiverQualificationMessage receiver =
      qualified_receiver(1000000u, 60u);
  assert(!otis_dual_core_receiver_qualified_for_control_at(
      &receiver, 1050000u, kMetadataLimitMs));
  assert(otis_dual_core_receiver_qualified_for_control_at(
      &receiver, 1040000u, kMetadataLimitMs));

  // The same full causal-age comparison must remain correct across the raw
  // rp2040_monotonic_us32 rollover.
  receiver = qualified_receiver(0xffff0000u, 20u);
  assert(otis_dual_core_receiver_qualified_for_control_at(
      &receiver, 0x00003880u, kMetadataLimitMs));
  assert(!otis_dual_core_receiver_qualified_for_control_at(
      &receiver, 0x00003c68u, kMetadataLimitMs));

  OtisSelectedPhaseFrequencyPreviewEngine phase = {};
  OtisOscillatorSnapshotEstimator oscillator = {};
  assert(otis_selected_phase_frequency_preview_init(&phase));
  otis_oscillator_snapshot_estimator_init(&oscillator);

  ReferenceSelectionFixture trace;
  trace.raw.snapshot_sequence = UINT32_MAX - 300u;
  trace.raw.reference_sequence = UINT32_MAX - 100u;
  trace.extended_ticks = (1ull << 32) - 8500000u;
  trace.raw.reference_timestamp_ticks = uint32_t(trace.extended_ticks);
  trace.acquire();
  OtisSelectedPhaseFrequencyPreviewOutput phase_output = {};
  OtisRegulationSpanEstimate oscillator_output = {};
  auto ingest = [&]() {
    const OtisSelectedPhaseFrequencyPreviewInput input = {&trace.selection, trace.extended_ticks, 3u, false};
    assert(otis_selected_phase_frequency_preview_process(&phase, &input, &phase_output));
    otis_oscillator_snapshot_estimator_ingest(&oscillator, &trace.selection, &oscillator_output);
  };
  ingest();
  const auto first_raw = trace.raw;
  bool receiver_control_qualified_during_hold = true;
  uint32_t raw_opening_snapshots[601] = {};
  uint32_t raw_opening_references[601] = {};
  for (uint32_t span = 1u; span <= 600u; ++span) {
    const bool metadata_qualified = span <= 200u || span > 400u;
    raw_opening_snapshots[span] = trace.raw.snapshot_sequence;
    raw_opening_references[span] = trace.raw.reference_sequence;
    if (span == 300u) {
      trace.advance(246294u, 2462937u);
      ingest();
      assert(!phase_output.record_available);
      assert(oscillator.selected_count == 299u);
      trace.advance(753707u, 7537064u);
    } else {
      trace.advance(1000000u, kMeasuredD8Edges);
    }
    const OtisReceiverQualificationMessage current_receiver =
        qualified_receiver(trace.raw.reference_timestamp_ticks, metadata_qualified ? 0u : 101u);
    const bool receiver_control_qualified = otis_dual_core_receiver_qualified_for_control_at(
        &current_receiver, trace.raw.reference_timestamp_ticks, kMetadataLimitMs);
    if (!metadata_qualified) receiver_control_qualified_during_hold &= receiver_control_qualified;
    ingest();
    if (span >= 60u) {
      assert(oscillator_output.diagnostic_first_sequence == raw_opening_snapshots[span - 59u]);
      assert(oscillator_output.diagnostic_first_reference_sequence == raw_opening_references[span - 59u]);
    }
  }
  assert(!receiver_control_qualified_during_hold);
  assert(phase_output.phase_state == OtisReferenceRelativePhaseState::Qualified);
  assert(phase_output.phase_epoch == 1u && phase_output.observation_sequence == 600u);
  assert(phase_output.relative_phase_cycles == 600);
  assert(phase_output.frequency_available && phase_output.frequency_error_hz == 1.0);
  assert(oscillator_output.selected_available);
  assert(oscillator_output.selected_first_sequence == first_raw.snapshot_sequence);
  assert(oscillator_output.selected_first_reference_sequence == first_raw.reference_sequence);
  assert(oscillator_output.last_sequence == trace.raw.snapshot_sequence);
  assert(oscillator_output.last_reference_sequence == trace.raw.reference_sequence);
  assert(oscillator_output.acceptance_epoch == 1u);
  assert(oscillator_output.selected_opening_accepted_boundary_ordinal == 0u);
  assert(oscillator_output.closing_accepted_boundary_ordinal == 600u);
  assert(oscillator_output.selected_frequency_hz == double(kMeasuredD8Edges));
  assert(oscillator_output.selected_accumulated_edge_error_counts == 600);
  // The diagnostic opening also follows actual raw endpoints after the split.
  assert(oscillator_output.diagnostic_first_sequence == trace.raw.snapshot_sequence - 60u);
  assert(oscillator_output.diagnostic_first_reference_sequence == trace.raw.reference_sequence - 60u);
  ++trace.raw.snapshot_sequence;
  trace.advance();
  ingest();
  assert(phase_output.phase_state == OtisReferenceRelativePhaseState::Invalid);
  assert(!oscillator_output.selected_available && oscillator.selected_count == 0u);
  trace.advance();
  ingest();
  for (uint32_t i = 0; i < OTIS_REFERENCE_ACCEPTANCE_POLICY.acquisition_intervals; ++i) {
    trace.advance();
    ingest();
  }
  assert(phase_output.phase_state == OtisReferenceRelativePhaseState::EpochOpen);
  assert(phase_output.phase_epoch == 2u && phase_output.observation_sequence == 0u);
  assert(oscillator.selected_count == 0u);
  trace.advance();
  ingest();
  assert(phase_output.observation_sequence == 1u && oscillator.selected_count == 1u);
  trace.advance();
  ++trace.selection.accepted_boundary_ordinal;
  ingest();
  assert(!oscillator_output.source_continuous && oscillator.selected_count == 0u);
  assert(phase_output.phase_state == OtisReferenceRelativePhaseState::Invalid);
  return 0;
}
