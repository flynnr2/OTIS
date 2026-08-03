#include <iomanip>
#include <iostream>

#include "otis_cx317_snapshot_estimator.h"

int main() {
  OtisCx317SnapshotEstimator estimator;
  otis_cx317_snapshot_estimator_init(&estimator);
  std::cout << "kind,first_sequence,last_sequence,frequency_hz\n";
  for (uint32_t sequence = 1u; sequence <= 1261u; ++sequence) {
    const bool invalid = sequence == 661u;
    const uint32_t count = 10000000u + (sequence % 17u == 0u ? 1u : 0u);
    OtisCx317SpanEstimate output;
    otis_cx317_snapshot_estimator_ingest(
        &estimator, sequence, count, !invalid, &output);
    if (output.diagnostic_available) {
      std::cout << "diagnostic," << output.diagnostic_first_sequence << ','
                << output.last_sequence << ',' << std::setprecision(17)
                << output.diagnostic_frequency_hz << '\n';
    }
    if (output.selected_available) {
      std::cout << "selected," << output.selected_first_sequence << ','
                << output.last_sequence << ',' << std::setprecision(17)
                << output.selected_frequency_hz << '\n';
    }
  }
  return 0;
}
