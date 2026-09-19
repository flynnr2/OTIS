#ifndef OTIS_REFERENCE_RECORD_H
#define OTIS_REFERENCE_RECORD_H

#include "otis_pps_snapshot_backend.h"
#include "otis_pps_count_boundary.h"
#include "otis_protocol.h"
#include "otis_reference_acceptance.h"

// The only production mapping from a captured word into the common selector.
// Both presentation ordinals name the same word. No lookup or timestamp match.
inline OtisPpsCountBoundaryObservation otis_reference_boundary(
    const OtisPpsHardwareSnapshot &snapshot) {
  return {snapshot.session, snapshot.sequence, snapshot.sequence,
      snapshot.service_ticks, snapshot.cumulative_down_counter, 0u,
      OTIS_FLAG_TIMESTAMP_RECONSTRUCTED,
      snapshot.status == 0u ? OTIS_PPS_APERTURE_NONE :
          (snapshot.status & ~(OTIS_PPS_SNAPSHOT_STATUS_TIMESTAMP_AMBIGUOUS |
                               OTIS_PPS_SNAPSHOT_STATUS_TIMESTAMP_UNBOUNDED)) != 0u
              ? OTIS_PPS_APERTURE_COUNTER_SNAPSHOT_INVALID
              : OTIS_PPS_APERTURE_BOUNDARY_CAPTURE_UNAVAILABLE,
      snapshot.timestamp_uncertainty_ticks};
}

inline OtisReferenceAcceptanceObservation otis_reference_candidate(
    const OtisPpsCountBoundaryObservation &boundary, uint32_t snapshot_status) {
  return {boundary.session, boundary.sequence, boundary.reference_sequence,
      uint32_t(boundary.pps_timestamp_ticks), boundary.cumulative_down_counter,
      snapshot_status, boundary.capture_flags, boundary.timestamp_uncertainty_ticks};
}
#endif
