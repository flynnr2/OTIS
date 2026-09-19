#pragma once
#include "otis_reference_record.h"
#include "otis_reference_acceptance_policy.generated.h"
void native_fifo_begin();
void native_fifo_rearm();
OtisPpsHardwareSnapshot native_fifo_capture(uint32_t count, uint64_t service_ticks);

// Actual backend ISR + production record mapping + common acceptance kernel.
struct FifoReferenceSelectionFixture {
  OtisReferenceAcceptance selector{OTIS_REFERENCE_ACCEPTANCE_POLICY};
  OtisReferenceAcceptanceObservation raw{};
  uint64_t extended_ticks = 10000000u;
  OtisReferenceAcceptanceOutcome selection{};
  FifoReferenceSelectionFixture() { native_fifo_begin(); raw.cumulative_down_counter=UINT32_MAX; }
  const OtisReferenceAcceptanceOutcome &observe() {
    auto snapshot=native_fifo_capture(raw.cumulative_down_counter, extended_ticks);
    raw=otis_reference_candidate(otis_reference_boundary(snapshot), snapshot.status);
    selection=selector.observe(raw);
    return selection;
  }
  const OtisReferenceAcceptanceOutcome &advance(uint32_t ticks=1000000u, uint32_t edges=10000000u) {
    extended_ticks+=ticks; raw.cumulative_down_counter-=edges; return observe();
  }
  const OtisReferenceAcceptanceOutcome &acquire() {
    observe();
    for(uint32_t i=0;i<OTIS_REFERENCE_ACCEPTANCE_POLICY.acquisition_intervals;++i) advance();
    return selection;
  }
};
