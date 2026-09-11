#ifndef OTIS_OSCILLATOR_SNAPSHOT_ESTIMATOR_H
#define OTIS_OSCILLATOR_SNAPSHOT_ESTIMATOR_H

#include <stdint.h>

#include "otis_config.h"
#include "otis_reference_acceptance.h"

constexpr uint16_t OTIS_REGULATION_DIAGNOSTIC_SPAN_INTERVALS = 60u;
constexpr uint16_t OTIS_FREQUENCY_ESTIMATOR_SPAN_INTERVALS =
    OTIS_FREQUENCY_ESTIMATOR_SPAN_INTERVALS_CONFIG;

struct OtisRegulationSpanEstimate {
  bool diagnostic_available;
  bool selected_available;
  double diagnostic_frequency_hz;
  double selected_frequency_hz;
  int64_t selected_accumulated_edge_error_counts;
  uint32_t diagnostic_first_sequence;
  uint32_t selected_first_sequence;
  uint32_t last_sequence;
  uint32_t diagnostic_first_reference_sequence;
  uint32_t selected_first_reference_sequence;
  uint32_t last_reference_sequence;
  uint32_t capture_session;
  uint32_t acceptance_epoch;
  uint32_t diagnostic_opening_accepted_boundary_ordinal;
  uint32_t selected_opening_accepted_boundary_ordinal;
  uint32_t closing_accepted_boundary_ordinal;
  bool source_continuous;
};

struct OtisOscillatorSnapshotEstimator {
  uint32_t diagnostic_counts[OTIS_REGULATION_DIAGNOSTIC_SPAN_INTERVALS];
  uint32_t diagnostic_opening_snapshots[OTIS_REGULATION_DIAGNOSTIC_SPAN_INTERVALS];
  uint32_t diagnostic_opening_references[OTIS_REGULATION_DIAGNOSTIC_SPAN_INTERVALS];
  uint16_t diagnostic_next;
  uint16_t diagnostic_count;
  uint64_t diagnostic_sum;
  uint64_t selected_sum;
  uint16_t selected_count;
  uint32_t selected_first_sequence;
  uint32_t selected_first_reference_sequence;
  uint32_t selected_opening_accepted_boundary_ordinal;
  bool have_previous;
  uint32_t acceptance_epoch;
  uint32_t accepted_boundary_ordinal;
  OtisReferenceAcceptanceObservation previous;
};

void otis_oscillator_snapshot_estimator_init(OtisOscillatorSnapshotEstimator *estimator);
void otis_oscillator_snapshot_estimator_reset(OtisOscillatorSnapshotEstimator *estimator);
void otis_oscillator_snapshot_estimator_ingest(
    OtisOscillatorSnapshotEstimator *estimator,
    const OtisReferenceAcceptanceOutcome *selection,
    OtisRegulationSpanEstimate *output);

#endif
