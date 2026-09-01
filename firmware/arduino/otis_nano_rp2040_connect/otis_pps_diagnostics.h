#ifndef OTIS_PPS_DIAGNOSTICS_H
#define OTIS_PPS_DIAGNOSTICS_H

#include <stdint.h>

#include "otis_timebase_math.h"

// This header contains only state transitions and fixed-size progress markers.
// Callers copy interrupt/DMA progress into it from foreground code. Queue drain,
// telemetry, and control progress deliberately cannot change PPS presence.

enum class OtisPhysicalPpsState : uint8_t {
  NeverSeen,
  Present,
  Missing,
};

enum class OtisPpsDiagnosticsTransition : uint8_t {
  None,
  PhysicalPpsMissing,
  PhysicalPpsRestored,
  PhysicalPpsReminder,
};

enum class OtisPpsProgressSequenceRelation : uint8_t {
  First,
  Continuous,
  Duplicate,
  Gap,
};

struct OtisPpsDiagnosticsConfig {
  uint64_t missing_timeout_ticks;
  // Zero disables reminders. Reminders never increment the outage counter.
  uint64_t missing_reminder_period_ticks;
};

struct OtisPpsProgressMarker {
  bool valid;
  uint32_t session;
  uint32_t sequence;
  uint64_t observed_ticks;
};

struct OtisPpsDiagnostics {
  OtisPpsDiagnosticsConfig config;
  OtisPhysicalPpsState physical_state;
  uint32_t session;
  uint64_t monitoring_started_ticks;
  uint64_t missing_transition_ticks;
  uint64_t restored_transition_ticks;
  uint64_t last_reminder_ticks;

  uint32_t physical_pps_missing_count;
  uint32_t physical_pps_restored_count;
  uint32_t physical_pps_reminder_count;
  uint32_t physical_sequence_gap_count;

  OtisPpsProgressMarker latest_physical_pps;
  OtisPpsProgressMarker latest_snapshot_produced;
  OtisPpsProgressMarker latest_snapshot_drained;
  OtisPpsProgressMarker latest_measurement_reconstructed;
  OtisPpsProgressMarker latest_telemetry_emitted;
  OtisPpsProgressMarker latest_control_observed;

  uint32_t foreground_backlog_depth;
  uint32_t foreground_backlog_capacity;
  uint32_t foreground_backlog_high_water;
  uint32_t foreground_backlog_transition_count;
  uint32_t foreground_backlog_cleared_count;
  uint64_t foreground_backlog_observed_ticks;
  bool foreground_backlog_active;

  uint32_t telemetry_backpressure_transition_count;
  uint32_t telemetry_backpressure_cleared_count;
  uint64_t telemetry_backpressure_observed_ticks;
  bool telemetry_backpressure_active;
};

static inline void otis_pps_diagnostics_increment_saturating(
    uint32_t *counter) {
  if (counter != nullptr && *counter != UINT32_MAX) {
    *counter += 1u;
  }
}

static inline uint64_t otis_pps_diagnostics_elapsed_ticks(
    uint64_t start_ticks, uint64_t end_ticks) {
  // OTIS timer-domain timestamps carry the wrapping 1 MHz micros() value
  // encoded as 16 units per microsecond. Use the repository's single-wrap
  // modulo arithmetic; the 16 MHz encoded scale does not imply 62.5 ns
  // capture resolution.
  return otis_timer0_interval_ticks(start_ticks, end_ticks);
}

static inline OtisPpsProgressSequenceRelation
otis_pps_diagnostics_sequence_relation(bool have_previous, uint32_t previous,
                                       uint32_t current) {
  if (!have_previous) {
    return OtisPpsProgressSequenceRelation::First;
  }
  if (current == previous) {
    return OtisPpsProgressSequenceRelation::Duplicate;
  }
  // Unsigned addition deliberately defines UINT32_MAX -> 0 as continuous.
  if (current == previous + 1u) {
    return OtisPpsProgressSequenceRelation::Continuous;
  }
  return OtisPpsProgressSequenceRelation::Gap;
}

static inline void otis_pps_diagnostics_set_progress_marker(
    OtisPpsProgressMarker *marker, uint32_t session, uint32_t sequence,
    uint64_t observed_ticks) {
  if (marker == nullptr) {
    return;
  }
  marker->valid = true;
  marker->session = session;
  marker->sequence = sequence;
  marker->observed_ticks = observed_ticks;
}

static inline void otis_pps_diagnostics_begin(
    OtisPpsDiagnostics *diagnostics,
    const OtisPpsDiagnosticsConfig &config, uint32_t session,
    uint64_t now_ticks) {
  if (diagnostics == nullptr) {
    return;
  }
  *diagnostics = {};
  diagnostics->config = config;
  diagnostics->physical_state = OtisPhysicalPpsState::NeverSeen;
  diagnostics->session = session;
  diagnostics->monitoring_started_ticks = now_ticks;
}

static inline void otis_pps_diagnostics_reset(OtisPpsDiagnostics *diagnostics,
                                              uint32_t session,
                                              uint64_t now_ticks) {
  if (diagnostics == nullptr) {
    return;
  }
  const OtisPpsDiagnosticsConfig config = diagnostics->config;
  otis_pps_diagnostics_begin(diagnostics, config, session, now_ticks);
}

static inline OtisPpsDiagnosticsTransition
otis_pps_diagnostics_note_physical_pps(OtisPpsDiagnostics *diagnostics,
                                       uint32_t producer_sequence,
                                       uint64_t arrival_ticks) {
  if (diagnostics == nullptr) {
    return OtisPpsDiagnosticsTransition::None;
  }

  const OtisPpsProgressSequenceRelation relation =
      otis_pps_diagnostics_sequence_relation(
          diagnostics->latest_physical_pps.valid,
          diagnostics->latest_physical_pps.sequence, producer_sequence);
  if (relation == OtisPpsProgressSequenceRelation::Duplicate) {
    // Re-observing the same producer mailbox is not a physical restoration.
    return OtisPpsDiagnosticsTransition::None;
  }
  if (relation == OtisPpsProgressSequenceRelation::Gap) {
    otis_pps_diagnostics_increment_saturating(
        &diagnostics->physical_sequence_gap_count);
  }

  otis_pps_diagnostics_set_progress_marker(
      &diagnostics->latest_physical_pps, diagnostics->session,
      producer_sequence, arrival_ticks);

  if (diagnostics->physical_state == OtisPhysicalPpsState::Missing) {
    diagnostics->physical_state = OtisPhysicalPpsState::Present;
    diagnostics->restored_transition_ticks = arrival_ticks;
    otis_pps_diagnostics_increment_saturating(
        &diagnostics->physical_pps_restored_count);
    return OtisPpsDiagnosticsTransition::PhysicalPpsRestored;
  }

  diagnostics->physical_state = OtisPhysicalPpsState::Present;
  return OtisPpsDiagnosticsTransition::None;
}

static inline OtisPpsDiagnosticsTransition otis_pps_diagnostics_poll(
    OtisPpsDiagnostics *diagnostics, uint64_t now_ticks) {
  if (diagnostics == nullptr) {
    return OtisPpsDiagnosticsTransition::None;
  }

  if (diagnostics->physical_state != OtisPhysicalPpsState::Missing) {
    const uint64_t anchor_ticks = diagnostics->latest_physical_pps.valid
                                      ? diagnostics->latest_physical_pps
                                            .observed_ticks
                                      : diagnostics->monitoring_started_ticks;
    const uint64_t elapsed_ticks =
        otis_pps_diagnostics_elapsed_ticks(anchor_ticks, now_ticks);
    if (elapsed_ticks > diagnostics->config.missing_timeout_ticks) {
      diagnostics->physical_state = OtisPhysicalPpsState::Missing;
      diagnostics->missing_transition_ticks = now_ticks;
      diagnostics->last_reminder_ticks = now_ticks;
      otis_pps_diagnostics_increment_saturating(
          &diagnostics->physical_pps_missing_count);
      return OtisPpsDiagnosticsTransition::PhysicalPpsMissing;
    }
    return OtisPpsDiagnosticsTransition::None;
  }

  if (diagnostics->config.missing_reminder_period_ticks != 0u &&
      otis_pps_diagnostics_elapsed_ticks(diagnostics->last_reminder_ticks,
                                         now_ticks) >=
          diagnostics->config.missing_reminder_period_ticks) {
    diagnostics->last_reminder_ticks = now_ticks;
    otis_pps_diagnostics_increment_saturating(
        &diagnostics->physical_pps_reminder_count);
    return OtisPpsDiagnosticsTransition::PhysicalPpsReminder;
  }
  return OtisPpsDiagnosticsTransition::None;
}

static inline void otis_pps_diagnostics_note_snapshot_produced(
    OtisPpsDiagnostics *diagnostics, uint32_t session, uint32_t sequence,
    uint64_t observed_ticks) {
  if (diagnostics != nullptr) {
    otis_pps_diagnostics_set_progress_marker(
        &diagnostics->latest_snapshot_produced, session, sequence,
        observed_ticks);
  }
}

static inline void otis_pps_diagnostics_note_snapshot_drained(
    OtisPpsDiagnostics *diagnostics, uint32_t session, uint32_t sequence,
    uint64_t observed_ticks) {
  if (diagnostics != nullptr) {
    otis_pps_diagnostics_set_progress_marker(
        &diagnostics->latest_snapshot_drained, session, sequence,
        observed_ticks);
  }
}

static inline void otis_pps_diagnostics_note_measurement_reconstructed(
    OtisPpsDiagnostics *diagnostics, uint32_t session, uint32_t sequence,
    uint64_t observed_ticks) {
  if (diagnostics != nullptr) {
    otis_pps_diagnostics_set_progress_marker(
        &diagnostics->latest_measurement_reconstructed, session, sequence,
        observed_ticks);
  }
}

static inline void otis_pps_diagnostics_note_telemetry_emitted(
    OtisPpsDiagnostics *diagnostics, uint32_t session, uint32_t sequence,
    uint64_t observed_ticks) {
  if (diagnostics != nullptr) {
    otis_pps_diagnostics_set_progress_marker(
        &diagnostics->latest_telemetry_emitted, session, sequence,
        observed_ticks);
  }
}

static inline void otis_pps_diagnostics_note_control_observed(
    OtisPpsDiagnostics *diagnostics, uint32_t session, uint32_t sequence,
    uint64_t observed_ticks) {
  if (diagnostics != nullptr) {
    otis_pps_diagnostics_set_progress_marker(
        &diagnostics->latest_control_observed, session, sequence,
        observed_ticks);
  }
}

static inline void otis_pps_diagnostics_note_foreground_backlog(
    OtisPpsDiagnostics *diagnostics, uint32_t depth, uint32_t capacity,
    uint64_t observed_ticks) {
  if (diagnostics == nullptr) {
    return;
  }
  const bool was_active = diagnostics->foreground_backlog_active;
  const bool active = depth != 0u;
  diagnostics->foreground_backlog_depth = depth;
  diagnostics->foreground_backlog_capacity = capacity;
  diagnostics->foreground_backlog_observed_ticks = observed_ticks;
  diagnostics->foreground_backlog_active = active;
  if (depth > diagnostics->foreground_backlog_high_water) {
    diagnostics->foreground_backlog_high_water = depth;
  }
  if (!was_active && active) {
    otis_pps_diagnostics_increment_saturating(
        &diagnostics->foreground_backlog_transition_count);
  } else if (was_active && !active) {
    otis_pps_diagnostics_increment_saturating(
        &diagnostics->foreground_backlog_cleared_count);
  }
}

static inline void otis_pps_diagnostics_note_telemetry_backpressure(
    OtisPpsDiagnostics *diagnostics, bool active, uint64_t observed_ticks) {
  if (diagnostics == nullptr) {
    return;
  }
  const bool was_active = diagnostics->telemetry_backpressure_active;
  diagnostics->telemetry_backpressure_active = active;
  diagnostics->telemetry_backpressure_observed_ticks = observed_ticks;
  if (!was_active && active) {
    otis_pps_diagnostics_increment_saturating(
        &diagnostics->telemetry_backpressure_transition_count);
  } else if (was_active && !active) {
    otis_pps_diagnostics_increment_saturating(
        &diagnostics->telemetry_backpressure_cleared_count);
  }
}

#endif
