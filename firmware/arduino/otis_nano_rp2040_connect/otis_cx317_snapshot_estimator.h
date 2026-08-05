#ifndef OTIS_CX317_SNAPSHOT_ESTIMATOR_H
#define OTIS_CX317_SNAPSHOT_ESTIMATOR_H

#include <stdint.h>

#include "otis_config.h"

constexpr uint16_t OTIS_CX317_DIAGNOSTIC_SPAN_INTERVALS = 60u;
constexpr uint16_t OTIS_CX317_SELECTED_SPAN_INTERVALS =
    OTIS_CX317_SELECTED_SPAN_INTERVALS_CONFIG;

struct OtisCx317SpanEstimate {
  bool diagnostic_available;
  bool selected_available;
  double diagnostic_frequency_hz;
  double selected_frequency_hz;
  uint32_t diagnostic_first_sequence;
  uint32_t selected_first_sequence;
  uint32_t last_sequence;
};

struct OtisCx317SnapshotEstimator {
  uint32_t diagnostic_counts[OTIS_CX317_DIAGNOSTIC_SPAN_INTERVALS];
  uint16_t diagnostic_next;
  uint16_t diagnostic_count;
  uint64_t diagnostic_sum;
  uint64_t selected_sum;
  uint16_t selected_count;
  uint32_t diagnostic_first_sequence;
  uint32_t selected_first_sequence;
};

void otis_cx317_snapshot_estimator_init(OtisCx317SnapshotEstimator *estimator);
void otis_cx317_snapshot_estimator_reset(OtisCx317SnapshotEstimator *estimator);
void otis_cx317_snapshot_estimator_ingest(
    OtisCx317SnapshotEstimator *estimator, uint32_t closing_sequence,
    uint32_t interval_count, bool interval_valid,
    OtisCx317SpanEstimate *output);

#endif
