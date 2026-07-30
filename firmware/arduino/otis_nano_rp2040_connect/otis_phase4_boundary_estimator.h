#ifndef OTIS_PHASE4_BOUNDARY_ESTIMATOR_H
#define OTIS_PHASE4_BOUNDARY_ESTIMATOR_H

#include <stdint.h>

// A 300 s H1 gate needs at most 302 bracketing PPS points.  The fixed capacity
// leaves explicit margin without dynamic allocation.
#define OTIS_PHASE4_PPS_SUPPORT_CAPACITY 384u

enum OtisPhase4BoundaryReason : uint8_t {
  OTIS_PHASE4_BOUNDARY_OK = 0,
  OTIS_PHASE4_BOUNDARY_INVALID_COUNT_WINDOW,
  OTIS_PHASE4_BOUNDARY_COUNT_ZERO,
  OTIS_PHASE4_BOUNDARY_MISSING_START_SUPPORT,
  OTIS_PHASE4_BOUNDARY_MISSING_END_SUPPORT,
  OTIS_PHASE4_BOUNDARY_DIFFERENT_SEGMENTS,
  OTIS_PHASE4_BOUNDARY_NON_POSITIVE_DURATION,
  OTIS_PHASE4_BOUNDARY_REFERENCE_GAP,
  OTIS_PHASE4_BOUNDARY_INVALID_RESULT,
};

enum OtisPhase4ReferenceIssue : uint8_t {
  OTIS_PHASE4_REFERENCE_ISSUE_NONE = 0,
  OTIS_PHASE4_REFERENCE_ISSUE_FLAGGED,
  OTIS_PHASE4_REFERENCE_ISSUE_INTERVAL,
  OTIS_PHASE4_REFERENCE_ISSUE_SEQUENCE,
  OTIS_PHASE4_REFERENCE_ISSUE_SUPPORT_OVERWRITTEN,
};

struct OtisPhase4PpsPoint {
  uint64_t ticks;
  double reference_seconds;
  uint32_t seq;
};

struct OtisPhase4BoundaryResult {
  bool valid;
  bool retryable_after_next_reference;
  OtisPhase4BoundaryReason reason;
  double gate_seconds;
  double frequency_hz;
  uint64_t before_open_ticks;
  uint64_t after_open_ticks;
  uint64_t before_close_ticks;
  uint64_t after_close_ticks;
  uint32_t before_open_seq;
  uint32_t after_open_seq;
  uint32_t before_close_seq;
  uint32_t after_close_seq;
  uint16_t support_count;
  double max_reference_gap_s;
};

struct OtisPhase4BoundaryEstimator {
  OtisPhase4PpsPoint points[OTIS_PHASE4_PPS_SUPPORT_CAPACITY];
  uint16_t point_count;
  bool candidate_available;
  bool candidate_clean;
  uint64_t candidate_ticks;
  uint32_t candidate_seq;
  uint32_t support_overwrite_count;
  uint32_t invalid_interval_count;
  uint32_t invalid_flag_count;
  uint32_t sequence_discontinuity_count;
  OtisPhase4ReferenceIssue last_reference_issue;
};

void otis_phase4_boundary_estimator_init(
    OtisPhase4BoundaryEstimator *estimator);

bool otis_phase4_boundary_estimator_on_reference(
    OtisPhase4BoundaryEstimator *estimator, uint32_t seq, uint64_t ticks,
    uint32_t flags, uint32_t invalid_flag_mask, uint64_t minimum_interval_ticks,
    uint64_t maximum_interval_ticks, double nominal_interval_s);

OtisPhase4BoundaryResult otis_phase4_boundary_estimator_estimate(
    const OtisPhase4BoundaryEstimator *estimator, uint64_t gate_open_ticks,
    uint64_t gate_close_ticks, uint64_t counted_edges, double domain_hz,
    double maximum_reference_gap_s);

const char *otis_phase4_boundary_reason_name(OtisPhase4BoundaryReason reason);

#endif
