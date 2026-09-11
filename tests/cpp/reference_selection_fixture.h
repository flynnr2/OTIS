#ifndef OTIS_TEST_REFERENCE_SELECTION_FIXTURE_H
#define OTIS_TEST_REFERENCE_SELECTION_FIXTURE_H

#include "otis_reference_acceptance_policy.generated.h"

// Native fixture uses the actual frozen selector and independent raw ordinals.
struct ReferenceSelectionFixture {
  OtisReferenceAcceptance selector{OTIS_REFERENCE_ACCEPTANCE_POLICY};
  OtisReferenceAcceptanceObservation raw{7u, 100u, 1100u, 0u, UINT32_MAX, 0u, 16u};
  uint64_t extended_ticks = 0u;
  OtisReferenceAcceptanceOutcome selection{};

  const OtisReferenceAcceptanceOutcome &observe() {
    selection = selector.observe(raw);
    return selection;
  }
  const OtisReferenceAcceptanceOutcome &advance(uint32_t ticks = 1000000u,
                                               uint32_t edges = 10000000u) {
    extended_ticks += ticks;
    raw.reference_timestamp_ticks = uint32_t(extended_ticks);
    ++raw.snapshot_sequence;
    ++raw.reference_sequence;
    raw.cumulative_down_counter -= edges;
    return observe();
  }
  const OtisReferenceAcceptanceOutcome &acquire() {
    observe();
    for (uint32_t i = 0; i < OTIS_REFERENCE_ACCEPTANCE_POLICY.acquisition_intervals; ++i)
      advance();
    return selection;
  }
};

#endif
