#ifndef OTIS_FORWARDED_CLOCK_MONITOR_INTERVAL_H
#define OTIS_FORWARDED_CLOCK_MONITOR_INTERVAL_H

#include <stdint.h>

// Pure reconstruction for the diagnostic forwarded-clock monitor. This file
// deliberately has no capture, control, or authoritative timing types.
constexpr uint32_t OTIS_FORWARDED_CLOCK_MONITOR_MAX_INTERVAL_COUNT = 12000000u;

struct OtisForwardedClockMonitorIntervalInput {
  uint32_t monitor_session;
  uint32_t monitor_sequence;
  uint32_t cumulative_down_counter;
  uint32_t reference_session;
  uint32_t reference_sequence;
  uint64_t reference_timestamp_ticks;
  uint32_t local_status;
};

enum class OtisForwardedClockMonitorIntervalState : uint8_t {
  Anchor = 0u,
  ValidInterval,
  MonitorSessionChange,
  SnapshotSequenceDuplicate,
  SnapshotSequenceGap,
  ReferenceSessionChange,
  ReferenceSequenceDuplicate,
  ReferenceSequenceGap,
  LocalStatusNonzero,
  AmbiguousCount,
};

struct OtisForwardedClockMonitorIntervalResult {
  OtisForwardedClockMonitorIntervalState state;
  bool interval_valid;
  bool counter_wrap_handled;
  uint32_t interval_count;
  uint32_t opening_monitor_sequence;
  uint32_t closing_monitor_sequence;
  uint32_t opening_reference_sequence;
  uint32_t closing_reference_sequence;
  uint64_t opening_reference_timestamp_ticks;
  uint64_t closing_reference_timestamp_ticks;
};

// Exactly one clean anchor is retained. Any outcome other than ValidInterval
// reanchors the current clean snapshot; a nonzero local status clears it.
struct OtisForwardedClockMonitorIntervalReconstructor {
  bool have_anchor;
  OtisForwardedClockMonitorIntervalInput anchor;
};

static inline void otis_forwarded_clock_monitor_interval_reset(
    OtisForwardedClockMonitorIntervalReconstructor *reconstructor) {
  if (reconstructor == nullptr) return;
  reconstructor->have_anchor = false;
  reconstructor->anchor = {};
}

namespace otis_forwarded_clock_monitor_interval_detail {

enum class SequenceRelation : uint8_t { Continuous, Duplicate, Gap };

static inline SequenceRelation sequence_relation(uint32_t previous,
                                                 uint32_t current) {
  if (current == previous) return SequenceRelation::Duplicate;
  // Unsigned addition makes UINT32_MAX -> 0 a continuous sequence.
  return current == previous + 1u ? SequenceRelation::Continuous
                                  : SequenceRelation::Gap;
}

static inline OtisForwardedClockMonitorIntervalResult result(
    OtisForwardedClockMonitorIntervalState state) {
  return {state, false, false, 0u, 0u, 0u, 0u, 0u, 0u, 0u};
}

}  // namespace otis_forwarded_clock_monitor_interval_detail

static inline OtisForwardedClockMonitorIntervalResult
otis_forwarded_clock_monitor_interval_observe(
    OtisForwardedClockMonitorIntervalReconstructor *reconstructor,
    const OtisForwardedClockMonitorIntervalInput *input) {
  using namespace otis_forwarded_clock_monitor_interval_detail;
  if (reconstructor == nullptr || input == nullptr) {
    return result(OtisForwardedClockMonitorIntervalState::LocalStatusNonzero);
  }
  // A local monitor status is never silently bridged.
  if (input->local_status != 0u) {
    reconstructor->have_anchor = false;
    return result(OtisForwardedClockMonitorIntervalState::LocalStatusNonzero);
  }
  if (!reconstructor->have_anchor) {
    reconstructor->anchor = *input;
    reconstructor->have_anchor = true;
    return result(OtisForwardedClockMonitorIntervalState::Anchor);
  }

  const OtisForwardedClockMonitorIntervalInput previous = reconstructor->anchor;
  const auto reanchor = [&](OtisForwardedClockMonitorIntervalState state) {
    reconstructor->anchor = *input;
    reconstructor->have_anchor = true;
    return result(state);
  };
  if (input->monitor_session != previous.monitor_session) {
    return reanchor(OtisForwardedClockMonitorIntervalState::MonitorSessionChange);
  }
  const SequenceRelation monitor_relation =
      sequence_relation(previous.monitor_sequence, input->monitor_sequence);
  if (monitor_relation == SequenceRelation::Duplicate) {
    return reanchor(OtisForwardedClockMonitorIntervalState::SnapshotSequenceDuplicate);
  }
  if (monitor_relation == SequenceRelation::Gap) {
    return reanchor(OtisForwardedClockMonitorIntervalState::SnapshotSequenceGap);
  }
  if (input->reference_session != previous.reference_session) {
    return reanchor(OtisForwardedClockMonitorIntervalState::ReferenceSessionChange);
  }
  const SequenceRelation reference_relation =
      sequence_relation(previous.reference_sequence, input->reference_sequence);
  if (reference_relation == SequenceRelation::Duplicate) {
    return reanchor(OtisForwardedClockMonitorIntervalState::ReferenceSequenceDuplicate);
  }
  if (reference_relation == SequenceRelation::Gap) {
    return reanchor(OtisForwardedClockMonitorIntervalState::ReferenceSequenceGap);
  }

  // The source counter counts down. Unsigned subtraction reconstructs one
  // uint32_t wrap. More than 12 MHz in one inferred interval is ambiguous.
  const uint32_t interval_count =
      previous.cumulative_down_counter - input->cumulative_down_counter;
  const bool counter_wrapped =
      input->cumulative_down_counter > previous.cumulative_down_counter;
  if (interval_count > OTIS_FORWARDED_CLOCK_MONITOR_MAX_INTERVAL_COUNT) {
    return reanchor(OtisForwardedClockMonitorIntervalState::AmbiguousCount);
  }

  reconstructor->anchor = *input;
  reconstructor->have_anchor = true;
  return {OtisForwardedClockMonitorIntervalState::ValidInterval,
          true,
          counter_wrapped,
          interval_count,
          previous.monitor_sequence,
          input->monitor_sequence,
          previous.reference_sequence,
          input->reference_sequence,
          previous.reference_timestamp_ticks,
          input->reference_timestamp_ticks};
}

#endif
