#include <assert.h>
#include <stdint.h>

#include "otis_dual_core_receiver_gate.h"
#include "otis_oscillator_snapshot_estimator.h"
#include "otis_selected_phase_frequency_preview_engine.h"

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

OtisSelectedPhaseFrequencyPreviewInput boundary(uint32_t sequence,
                                                uint32_t counter,
                                                bool raw_interval_valid) {
  return {
      7u,
      sequence,
      counter,
      sequence,
      static_cast<uint64_t>(sequence) * 1000000ull,
      static_cast<uint64_t>(sequence) * 1000000ull,
      0u,
      kMeasuredD8Edges,
      3u,
      raw_interval_valid,
      raw_interval_valid,
      false,
  };
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

  uint32_t counter = 0xf0000000u;
  OtisSelectedPhaseFrequencyPreviewOutput phase_output = {};
  OtisRegulationSpanEstimate oscillator_output = {};
  bool selected_support_observed = false;
  bool receiver_control_qualified_during_hold = true;

  for (uint32_t sequence = 1u; sequence <= 601u; ++sequence) {
    const bool metadata_qualified = sequence <= 200u || sequence > 400u;
    const bool raw_d14_d8_interval_valid = true;
    if (sequence > 1u) counter -= kMeasuredD8Edges;

    // This is the production receiver-control gate. During the metadata
    // hold, each current boundary is independently ineligible for control.
    const uint64_t boundary_ticks = static_cast<uint64_t>(sequence) * 1000000ull;
    const OtisReceiverQualificationMessage boundary_receiver =
        qualified_receiver(boundary_ticks, metadata_qualified ? 0u : 101u);
    const bool receiver_control_qualified =
        otis_dual_core_receiver_qualified_for_control_at(
            &boundary_receiver, boundary_ticks, kMetadataLimitMs);
    if (!metadata_qualified)
      receiver_control_qualified_during_hold &= receiver_control_qualified;
    const OtisSelectedPhaseFrequencyPreviewInput input =
        boundary(sequence, counter, raw_d14_d8_interval_valid);
    assert(otis_selected_phase_frequency_preview_process(&phase, &input,
                                                          &phase_output));
    if (sequence > 1u) {
      otis_oscillator_snapshot_estimator_ingest(
          &oscillator, sequence, kMeasuredD8Edges, raw_d14_d8_interval_valid,
          &oscillator_output);
      selected_support_observed |= oscillator_output.selected_available;
    }
  }

  assert(!receiver_control_qualified_during_hold);
  assert(phase_output.phase_state == OtisReferenceRelativePhaseState::Qualified);
  assert(phase_output.phase_epoch == 1u);
  assert(phase_output.observation_sequence == 600u);
  assert(phase_output.relative_phase_cycles == 600);
  assert(phase_output.frequency_available);
  assert(phase_output.frequency_error_hz == 1.0);
  assert(selected_support_observed);
  assert(oscillator_output.selected_available);
  assert(oscillator_output.selected_first_sequence == 1u);
  assert(oscillator_output.last_sequence == 601u);
  assert(oscillator_output.selected_frequency_hz ==
         static_cast<double>(kMeasuredD8Edges));
  assert(oscillator_output.selected_accumulated_edge_error_counts == 600);

  // A real D14/D8 fault still invalidates both preview histories.
  counter -= kMeasuredD8Edges;
  OtisSelectedPhaseFrequencyPreviewInput raw_fault =
      boundary(602u, counter, false);
  assert(otis_selected_phase_frequency_preview_process(&phase, &raw_fault,
                                                        &phase_output));
  assert(phase_output.phase_state == OtisReferenceRelativePhaseState::Invalid);
  otis_oscillator_snapshot_estimator_ingest(&oscillator, 602u,
                                            kMeasuredD8Edges, false,
                                            &oscillator_output);
  assert(!oscillator_output.selected_available);
  assert(oscillator.selected_count == 0u);

  counter -= kMeasuredD8Edges;
  const OtisSelectedPhaseFrequencyPreviewInput after_fault =
      boundary(603u, counter, true);
  assert(otis_selected_phase_frequency_preview_process(&phase, &after_fault,
                                                        &phase_output));
  assert(phase_output.phase_state == OtisReferenceRelativePhaseState::EpochOpen);
  assert(phase_output.phase_epoch == 2u);
  assert(phase_output.observation_sequence == 0u);
  return 0;
}
