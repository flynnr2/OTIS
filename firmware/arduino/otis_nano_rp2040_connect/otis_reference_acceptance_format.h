#ifndef OTIS_REFERENCE_ACCEPTANCE_FORMAT_H
#define OTIS_REFERENCE_ACCEPTANCE_FORMAT_H

#include <stddef.h>
#include <stdio.h>
#include "otis_reference_acceptance.h"

// Format the selected span, never a substitute raw observation. All raw CNT
// identities remain in the closing-snapshot ordinal domain.
inline bool otis_reference_acceptance_format_span(
    const OtisReferenceAcceptanceOutcome &span, const char *policy_sha256,
    char *destination, size_t capacity, uint16_t *length) {
  if (destination == nullptr || length == nullptr || policy_sha256 == nullptr ||
      !span.has_span || span.disposition != OtisReferenceAcceptanceDisposition::AcceptedSpan ||
      span.acceptance_epoch == 0u) return false;
  const int used = snprintf(destination, capacity,
      "APS,1,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,rp2040_monotonic_us32,%lu,%lu,%lu,%lu,%lu,1,%s\r\n",
      static_cast<unsigned long>(span.closing.capture_session),
      static_cast<unsigned long>(span.acceptance_epoch),
      static_cast<unsigned long>(span.accepted_boundary_ordinal),
      static_cast<unsigned long>(span.opening.snapshot_sequence),
      static_cast<unsigned long>(span.closing.snapshot_sequence),
      static_cast<unsigned long>(span.opening.reference_sequence),
      static_cast<unsigned long>(span.closing.reference_sequence),
      static_cast<unsigned long>(span.opening.reference_timestamp_ticks),
      static_cast<unsigned long>(span.closing.reference_timestamp_ticks),
      static_cast<unsigned long>(uint32_t(span.opening.snapshot_sequence + 1u)),
      static_cast<unsigned long>(span.closing.snapshot_sequence),
      static_cast<unsigned long>(span.excluded_candidate_count + 1u),
      static_cast<unsigned long>(span.counted_edges),
      static_cast<unsigned long>(span.excluded_candidate_count), policy_sha256);
  if (used <= 0 || static_cast<size_t>(used) >= capacity || used > UINT16_MAX) return false;
  *length = static_cast<uint16_t>(used);
  return true;
}

#endif
