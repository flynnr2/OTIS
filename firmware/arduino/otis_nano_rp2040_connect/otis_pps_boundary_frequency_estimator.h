#ifndef OTIS_PPS_BOUNDARY_FREQUENCY_ESTIMATOR_H
#define OTIS_PPS_BOUNDARY_FREQUENCY_ESTIMATOR_H

#include <stdint.h>

// A 300 s H1 gate needs at most 302 bracketing PPS points.  The fixed capacity
// leaves explicit margin without dynamic allocation.
#define OTIS_PPS_BOUNDARY_SUPPORT_CAPACITY 384u

enum OtisPpsBoundaryFrequencyReason : uint8_t {
  OTIS_PPS_BOUNDARY_FREQUENCY_OK = 0,
  OTIS_PPS_BOUNDARY_FREQUENCY_INVALID_COUNT_WINDOW,
  OTIS_PPS_BOUNDARY_FREQUENCY_COUNT_ZERO,
  OTIS_PPS_BOUNDARY_FREQUENCY_MISSING_START_SUPPORT,
  OTIS_PPS_BOUNDARY_FREQUENCY_MISSING_END_SUPPORT,
  OTIS_PPS_BOUNDARY_FREQUENCY_DIFFERENT_SEGMENTS,
  OTIS_PPS_BOUNDARY_FREQUENCY_NON_POSITIVE_DURATION,
  OTIS_PPS_BOUNDARY_FREQUENCY_REFERENCE_GAP,
  OTIS_PPS_BOUNDARY_FREQUENCY_INVALID_RESULT,
};

enum OtisPpsBoundaryReferenceIssue : uint8_t {
  OTIS_OBSERVE_ONLY_DISCIPLINE_REFERENCE_ISSUE_NONE = 0,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REFERENCE_ISSUE_FLAGGED,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REFERENCE_ISSUE_INTERVAL,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REFERENCE_ISSUE_SEQUENCE,
  OTIS_OBSERVE_ONLY_DISCIPLINE_REFERENCE_ISSUE_SUPPORT_OVERWRITTEN,
};

struct OtisPpsBoundarySupportPoint {
  uint64_t ticks;
  double reference_seconds;
  uint32_t seq;
};

struct OtisPpsBoundaryFrequencyResult {
  bool valid;
  bool retryable_after_next_reference;
  OtisPpsBoundaryFrequencyReason reason;
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

struct OtisPpsBoundaryFrequencyEstimator {
  OtisPpsBoundarySupportPoint points[OTIS_PPS_BOUNDARY_SUPPORT_CAPACITY];
  uint16_t point_count;
  bool candidate_available;
  bool candidate_clean;
  uint64_t candidate_ticks;
  uint32_t candidate_seq;
  uint32_t support_overwrite_count;
  uint32_t invalid_interval_count;
  uint32_t invalid_flag_count;
  uint32_t sequence_discontinuity_count;
  OtisPpsBoundaryReferenceIssue last_reference_issue;
};

void otis_pps_boundary_frequency_estimator_init(
    OtisPpsBoundaryFrequencyEstimator *estimator);

bool otis_pps_boundary_frequency_estimator_on_reference(
    OtisPpsBoundaryFrequencyEstimator *estimator, uint32_t seq, uint64_t ticks,
    uint32_t flags, uint32_t invalid_flag_mask, uint64_t minimum_interval_ticks,
    uint64_t maximum_interval_ticks, double nominal_interval_s);

OtisPpsBoundaryFrequencyResult otis_pps_boundary_frequency_estimator_estimate(
    const OtisPpsBoundaryFrequencyEstimator *estimator, uint64_t gate_open_ticks,
    uint64_t gate_close_ticks, uint64_t counted_edges, double domain_hz,
    double maximum_reference_gap_s);

const char *otis_pps_boundary_frequency_reason_name(OtisPpsBoundaryFrequencyReason reason);

#endif
