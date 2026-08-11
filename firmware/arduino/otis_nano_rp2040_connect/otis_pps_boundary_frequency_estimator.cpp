#include "otis_pps_boundary_frequency_estimator.h"

#include <math.h>
#include <string.h>

namespace {

struct Mapping {
  bool available;
  double seconds;
  uint16_t before_index;
  uint16_t after_index;
};

Mapping map_tick(const OtisPpsBoundaryFrequencyEstimator *estimator,
                 uint64_t ticks) {
  Mapping mapping = {};
  if (estimator->point_count < 2u) return mapping;
  for (uint16_t index = 0u; index + 1u < estimator->point_count; ++index) {
    const OtisPpsBoundarySupportPoint &before = estimator->points[index];
    const OtisPpsBoundarySupportPoint &after = estimator->points[index + 1u];
    if (before.ticks <= ticks && ticks <= after.ticks) {
      const uint64_t tick_span = after.ticks - before.ticks;
      const double second_span =
          after.reference_seconds - before.reference_seconds;
      if (tick_span == 0u || !isfinite(second_span) || second_span <= 0.0)
        return mapping;
      mapping.available = true;
      mapping.seconds =
          before.reference_seconds +
          (double)(ticks - before.ticks) * second_span / (double)tick_span;
      mapping.before_index = index;
      mapping.after_index = (uint16_t)(index + 1u);
      return mapping;
    }
  }
  return mapping;
}

void append_point(OtisPpsBoundaryFrequencyEstimator *estimator, uint64_t ticks,
                  double seconds, uint32_t seq) {
  if (estimator->point_count == OTIS_PPS_BOUNDARY_SUPPORT_CAPACITY) {
    memmove(
        &estimator->points[0], &estimator->points[1],
        sizeof(estimator->points[0]) *
            (OTIS_PPS_BOUNDARY_SUPPORT_CAPACITY - 1u));
    estimator->point_count--;
    if (estimator->support_overwrite_count < UINT32_MAX)
      estimator->support_overwrite_count++;
    estimator->last_reference_issue =
        OTIS_OBSERVE_ONLY_DISCIPLINE_REFERENCE_ISSUE_SUPPORT_OVERWRITTEN;
  }
  OtisPpsBoundarySupportPoint &point = estimator->points[estimator->point_count++];
  point.ticks = ticks;
  point.reference_seconds = seconds;
  point.seq = seq;
}

OtisPpsBoundaryFrequencyResult unavailable(OtisPpsBoundaryFrequencyReason reason,
                                     bool retryable) {
  OtisPpsBoundaryFrequencyResult result = {};
  result.reason = reason;
  result.retryable_after_next_reference = retryable;
  return result;
}

}  // namespace

void otis_pps_boundary_frequency_estimator_init(
    OtisPpsBoundaryFrequencyEstimator *estimator) {
  memset(estimator, 0, sizeof(*estimator));
}

bool otis_pps_boundary_frequency_estimator_on_reference(
    OtisPpsBoundaryFrequencyEstimator *estimator, uint32_t seq, uint64_t ticks,
    uint32_t flags, uint32_t invalid_flag_mask, uint64_t minimum_interval_ticks,
    uint64_t maximum_interval_ticks, double nominal_interval_s) {
  estimator->last_reference_issue = OTIS_OBSERVE_ONLY_DISCIPLINE_REFERENCE_ISSUE_NONE;
  const bool clean = (flags & invalid_flag_mask) == 0u;
  if (!estimator->candidate_available) {
    estimator->candidate_available = true;
    estimator->candidate_clean = clean;
    estimator->candidate_ticks = ticks;
    estimator->candidate_seq = seq;
    if (!clean) {
      estimator->last_reference_issue = OTIS_OBSERVE_ONLY_DISCIPLINE_REFERENCE_ISSUE_FLAGGED;
      estimator->invalid_flag_count++;
    }
    return false;
  }

  const bool sequence_valid = seq > estimator->candidate_seq;
  const uint64_t interval_ticks =
      ticks > estimator->candidate_ticks ? ticks - estimator->candidate_ticks
                                         : 0u;
  const bool interval_valid =
      interval_ticks >= minimum_interval_ticks &&
      interval_ticks <= maximum_interval_ticks;
  const bool accepted = estimator->candidate_clean && clean &&
                        sequence_valid && interval_valid;
  if (!accepted) {
    estimator->point_count = 0u;
    if (!estimator->candidate_clean || !clean) {
      estimator->last_reference_issue = OTIS_OBSERVE_ONLY_DISCIPLINE_REFERENCE_ISSUE_FLAGGED;
      if (estimator->invalid_flag_count < UINT32_MAX)
        estimator->invalid_flag_count++;
    } else if (!sequence_valid) {
      estimator->last_reference_issue = OTIS_OBSERVE_ONLY_DISCIPLINE_REFERENCE_ISSUE_SEQUENCE;
      if (estimator->sequence_discontinuity_count < UINT32_MAX)
        estimator->sequence_discontinuity_count++;
    } else {
      estimator->last_reference_issue = OTIS_OBSERVE_ONLY_DISCIPLINE_REFERENCE_ISSUE_INTERVAL;
      if (estimator->invalid_interval_count < UINT32_MAX)
        estimator->invalid_interval_count++;
    }
  } else {
    if (estimator->point_count == 0u)
      append_point(estimator, estimator->candidate_ticks, 0.0,
                   estimator->candidate_seq);
    const double next_seconds =
        estimator->points[estimator->point_count - 1u].reference_seconds +
        nominal_interval_s;
    append_point(estimator, ticks, next_seconds, seq);
  }

  estimator->candidate_available = true;
  estimator->candidate_clean = clean;
  estimator->candidate_ticks = ticks;
  estimator->candidate_seq = seq;
  return accepted;
}

OtisPpsBoundaryFrequencyResult otis_pps_boundary_frequency_estimator_estimate(
    const OtisPpsBoundaryFrequencyEstimator *estimator, uint64_t gate_open_ticks,
    uint64_t gate_close_ticks, uint64_t counted_edges, double domain_hz,
    double maximum_reference_gap_s) {
  if (gate_close_ticks <= gate_open_ticks)
    return unavailable(OTIS_PPS_BOUNDARY_FREQUENCY_INVALID_COUNT_WINDOW, false);
  if (counted_edges == 0u)
    return unavailable(OTIS_PPS_BOUNDARY_FREQUENCY_COUNT_ZERO, false);

  const Mapping open = map_tick(estimator, gate_open_ticks);
  const Mapping close = map_tick(estimator, gate_close_ticks);
  if (!open.available && close.available &&
      (estimator->invalid_interval_count > 0u ||
       estimator->invalid_flag_count > 0u ||
       estimator->sequence_discontinuity_count > 0u))
    return unavailable(OTIS_PPS_BOUNDARY_FREQUENCY_DIFFERENT_SEGMENTS, false);
  if (!open.available)
    return unavailable(OTIS_PPS_BOUNDARY_FREQUENCY_MISSING_START_SUPPORT, false);
  if (!close.available) {
    const bool retryable =
        estimator->point_count >= 2u &&
        gate_close_ticks > estimator->points[estimator->point_count - 1u].ticks;
    return unavailable(OTIS_PPS_BOUNDARY_FREQUENCY_MISSING_END_SUPPORT, retryable);
  }

  const double gate_seconds = close.seconds - open.seconds;
  if (!isfinite(gate_seconds) || gate_seconds <= 0.0)
    return unavailable(OTIS_PPS_BOUNDARY_FREQUENCY_NON_POSITIVE_DURATION, false);

  double max_gap_s = 0.0;
  uint16_t support_count = 1u;
  for (uint16_t index = open.before_index; index < close.after_index; ++index) {
    const OtisPpsBoundarySupportPoint &before = estimator->points[index];
    const OtisPpsBoundarySupportPoint &after = estimator->points[index + 1u];
    const double gap_s = (double)(after.ticks - before.ticks) / domain_hz;
    if (!isfinite(gap_s) || gap_s <= 0.0 ||
        gap_s > maximum_reference_gap_s)
      return unavailable(OTIS_PPS_BOUNDARY_FREQUENCY_REFERENCE_GAP, false);
    if (gap_s > max_gap_s) max_gap_s = gap_s;
    support_count++;
  }

  const double frequency_hz = (double)counted_edges / gate_seconds;
  if (!isfinite(frequency_hz) || frequency_hz <= 0.0)
    return unavailable(OTIS_PPS_BOUNDARY_FREQUENCY_INVALID_RESULT, false);

  OtisPpsBoundaryFrequencyResult result = {};
  result.valid = true;
  result.reason = OTIS_PPS_BOUNDARY_FREQUENCY_OK;
  result.gate_seconds = gate_seconds;
  result.frequency_hz = frequency_hz;
  result.before_open_ticks = estimator->points[open.before_index].ticks;
  result.after_open_ticks = estimator->points[open.after_index].ticks;
  result.before_close_ticks = estimator->points[close.before_index].ticks;
  result.after_close_ticks = estimator->points[close.after_index].ticks;
  result.before_open_seq = estimator->points[open.before_index].seq;
  result.after_open_seq = estimator->points[open.after_index].seq;
  result.before_close_seq = estimator->points[close.before_index].seq;
  result.after_close_seq = estimator->points[close.after_index].seq;
  result.support_count = support_count;
  result.max_reference_gap_s = max_gap_s;
  return result;
}

const char *otis_pps_boundary_frequency_reason_name(OtisPpsBoundaryFrequencyReason reason) {
  switch (reason) {
    case OTIS_PPS_BOUNDARY_FREQUENCY_OK: return "boundary_pps_support_valid";
    case OTIS_PPS_BOUNDARY_FREQUENCY_INVALID_COUNT_WINDOW:
      return "invalid_count_window";
    case OTIS_PPS_BOUNDARY_FREQUENCY_COUNT_ZERO: return "count_zero";
    case OTIS_PPS_BOUNDARY_FREQUENCY_MISSING_START_SUPPORT:
      return "missing_pps_before_or_after_count_window_start";
    case OTIS_PPS_BOUNDARY_FREQUENCY_MISSING_END_SUPPORT:
      return "missing_pps_before_or_after_count_window_end";
    case OTIS_PPS_BOUNDARY_FREQUENCY_DIFFERENT_SEGMENTS:
      return "count_window_crosses_invalid_pps_segment";
    case OTIS_PPS_BOUNDARY_FREQUENCY_NON_POSITIVE_DURATION:
      return "non_positive_reference_duration";
    case OTIS_PPS_BOUNDARY_FREQUENCY_REFERENCE_GAP:
      return "reference_support_gap_exceeded";
    case OTIS_PPS_BOUNDARY_FREQUENCY_INVALID_RESULT:
      return "invalid_frequency_result";
  }
  return "boundary_pps_support_unavailable";
}
