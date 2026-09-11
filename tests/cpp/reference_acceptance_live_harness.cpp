#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "otis_reference_acceptance_live.h"
#include "otis_reference_acceptance_policy.generated.h"
#include "otis_reference_acceptance_format.h"

int main() {
  using D = OtisReferenceAcceptanceDisposition;
  using R = OtisReferenceAcceptanceReason;
  OtisReferenceAcceptanceLive owner(OTIS_REFERENCE_ACCEPTANCE_POLICY);
  uint64_t ticks = 0xffff0000ull;
  OtisReferenceAcceptanceObservation raw = {7u, 0xfffffff0u, 700u, uint32_t(ticks), 0xfffffff0u, 0u, 16u};
  auto deliver = [&](uint32_t delta, uint32_t edges, uint64_t lag = 200u) {
    if (delta) { ticks += delta; raw.snapshot_sequence++; raw.reference_sequence++; raw.cumulative_down_counter -= edges; }
    raw.reference_timestamp_ticks = uint32_t(ticks);
    return owner.observe(raw, ticks, ticks + lag, 60000000ull);
  };
  assert(deliver(0u, 0u).disposition == D::Seeded);
  for (unsigned i = 0; i < 8; ++i) assert(!deliver(1000000u, 10000000u).has_span);
  assert(owner.status().tracking && owner.status().accepted_boundary_ordinal == 0u);
  const uint32_t epoch = owner.status().acceptance_epoch;
  const uint32_t opening_raw = raw.snapshot_sequence;
  for (unsigned i = 1; i <= 600; ++i) {
    if (i == 250u) {
      const auto original_anchor = owner.status();
      const auto excluded = deliver(246294u, 2462937u);
      assert(excluded.disposition == D::EarlyExcluded);
      assert(owner.status().anchor_current);
      assert(owner.status().anchor_snapshot_sequence == original_anchor.anchor_snapshot_sequence);
      const auto span = deliver(753707u, 7537063u);
      assert(span.has_span && span.counted_edges == 10000000u);
      assert(span.excluded_candidate_count == 1u);
      char text[512]; uint16_t length = 0u;
      assert(otis_reference_acceptance_format_span(span, OTIS_REFERENCE_ACCEPTANCE_POLICY_SHA256, text, sizeof(text), &length));
      assert(length > 0u); fputs(text, stdout);
    } else {
      assert(deliver(1000000u, 10000000u).has_span);
    }
  }
  assert(owner.status().accepted_boundary_ordinal == 600u);
  assert(raw.snapshot_sequence - opening_raw == 601u);
  assert(owner.status().acceptance_epoch == epoch);
  // CPU overdue holds new authority but an already captured in-window edge
  // delivered later remains in the same acceptance epoch.
  owner.service(ticks + 1001251u);
  assert(!owner.status().anchor_current && owner.status().tracking);
  const auto delayed = deliver(1000000u, 10000000u, 3000u);
  assert(delayed.has_span && delayed.acceptance_epoch == epoch);
  assert(owner.status().anchor_current);
  // An excluded candidate does not extend expiry or clear an overdue latch.
  owner.service(ticks + 1001251u);
  assert(deliver(250000u, 2500000u, 800000u).disposition == D::EarlyExcluded);
  assert(!owner.status().anchor_current);
  owner.service(ticks + (uint64_t(1) << 32));
  assert(!owner.status().anchor_current);
  // Long silence cannot resurrect the old anchor through a small u32 residue.
  ticks += (uint64_t(1) << 32);
  const auto ambiguous = deliver(750000u, 7500000u);
  assert(ambiguous.disposition == D::QualificationLost);
  assert(ambiguous.reason == R::ObservationAgeAmbiguous);
  assert(strcmp(owner.status().last_loss_reason, "observation_age_ambiguous") == 0);
  assert(!owner.status().tracking && !owner.status().anchor_current);
  assert(deliver(1000000u, 10000000u).disposition == D::Seeded);
  for (unsigned i = 0; i < 8; ++i) assert(!deliver(1000000u, 10000000u).has_span);
  assert(owner.status().acceptance_epoch != epoch);
  assert(deliver(1000000u, 10000000u).accepted_boundary_ordinal == 1u);
  assert(strcmp(owner.status().last_loss_reason, "observation_age_ambiguous") == 0);
  // A physical association defect withdraws model continuity immediately.
  owner.invalidate(R::CaptureIntegrity);
  assert(strcmp(owner.status().last_loss_reason, "capture_integrity") == 0);
  assert(!owner.status().tracking && !owner.status().anchor_current);
  return 0;
}
