#include "otis_cx317_snapshot_estimator.h"

#include <string.h>

void otis_cx317_snapshot_estimator_init(OtisCx317SnapshotEstimator *estimator) {
  otis_cx317_snapshot_estimator_reset(estimator);
}

void otis_cx317_snapshot_estimator_reset(OtisCx317SnapshotEstimator *estimator) {
  if (estimator == nullptr) return;
  memset(estimator, 0, sizeof(*estimator));
}

void otis_cx317_snapshot_estimator_ingest(
    OtisCx317SnapshotEstimator *estimator, uint32_t closing_sequence,
    uint32_t interval_count, bool interval_valid,
    OtisCx317SpanEstimate *output) {
  if (estimator == nullptr || output == nullptr) return;
  *output = {};
  output->last_sequence = closing_sequence;
  if (!interval_valid || interval_count == 0u) {
    otis_cx317_snapshot_estimator_reset(estimator);
    return;
  }

  if (estimator->diagnostic_count == 0u)
    estimator->diagnostic_first_sequence = closing_sequence - 1u;
  if (estimator->diagnostic_count < OTIS_CX317_DIAGNOSTIC_SPAN_INTERVALS) {
    estimator->diagnostic_counts[estimator->diagnostic_next] = interval_count;
    estimator->diagnostic_sum += interval_count;
    estimator->diagnostic_count++;
  } else {
    estimator->diagnostic_sum -=
        estimator->diagnostic_counts[estimator->diagnostic_next];
    estimator->diagnostic_counts[estimator->diagnostic_next] = interval_count;
    estimator->diagnostic_sum += interval_count;
    estimator->diagnostic_first_sequence++;
  }
  estimator->diagnostic_next = static_cast<uint16_t>(
      (estimator->diagnostic_next + 1u) % OTIS_CX317_DIAGNOSTIC_SPAN_INTERVALS);
  if (estimator->diagnostic_count == OTIS_CX317_DIAGNOSTIC_SPAN_INTERVALS) {
    output->diagnostic_available = true;
    output->diagnostic_frequency_hz =
        static_cast<double>(estimator->diagnostic_sum) /
        OTIS_CX317_DIAGNOSTIC_SPAN_INTERVALS;
    output->diagnostic_first_sequence = estimator->diagnostic_first_sequence;
  }

  if (estimator->selected_count == 0u)
    estimator->selected_first_sequence = closing_sequence - 1u;
  estimator->selected_sum += interval_count;
  estimator->selected_count++;
  if (estimator->selected_count == OTIS_CX317_SELECTED_SPAN_INTERVALS) {
    output->selected_available = true;
    output->selected_frequency_hz =
        static_cast<double>(estimator->selected_sum) /
        OTIS_CX317_SELECTED_SPAN_INTERVALS;
    output->selected_accumulated_edge_error_counts =
        static_cast<int64_t>(estimator->selected_sum) -
        static_cast<int64_t>(OTIS_CX317_SELECTED_SPAN_INTERVALS) * 10000000ll;
    output->selected_first_sequence = estimator->selected_first_sequence;
    estimator->selected_sum = 0u;
    estimator->selected_count = 0u;
  }
}
