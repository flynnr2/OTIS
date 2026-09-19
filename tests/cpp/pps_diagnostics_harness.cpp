#include <assert.h>
#include <stdint.h>

#include "otis_pps_diagnostics.h"

namespace {

constexpr uint64_t kTicksPerSecond = 1000000ull;
constexpr uint64_t kMonotonicUs32Modulus = 1ull << 32;

OtisPpsDiagnosticsConfig config(void) {
  return {
      5ull * kTicksPerSecond / 2ull,
      kTicksPerSecond,
  };
}

void test_never_seen_stale_and_resumed(void) {
  OtisPpsDiagnostics diagnostics;
  otis_pps_diagnostics_begin(&diagnostics, config(), 7u, 0u);
  assert(diagnostics.capture_service_state ==
         OtisPpsCaptureServiceState::NeverSeen);

  assert(otis_pps_diagnostics_poll(&diagnostics, 2u * kTicksPerSecond) ==
         OtisPpsDiagnosticsTransition::None);
  assert(otis_pps_diagnostics_poll(&diagnostics, 3u * kTicksPerSecond) ==
         OtisPpsDiagnosticsTransition::CaptureServiceStale);
  assert(diagnostics.capture_service_stale_count == 1u);

  assert(otis_pps_diagnostics_poll(&diagnostics,
                                   3u * kTicksPerSecond + 1u) ==
         OtisPpsDiagnosticsTransition::None);
  assert(otis_pps_diagnostics_poll(&diagnostics, 4u * kTicksPerSecond) ==
         OtisPpsDiagnosticsTransition::CaptureServiceReminder);
  assert(diagnostics.capture_service_stale_count == 1u);
  assert(diagnostics.capture_service_reminder_count == 1u);

  assert(otis_pps_diagnostics_note_capture_service(
             &diagnostics, 0u, 4u * kTicksPerSecond + 10u) ==
         OtisPpsDiagnosticsTransition::CaptureServiceResumed);
  assert(diagnostics.capture_service_state ==
         OtisPpsCaptureServiceState::Present);
  assert(diagnostics.capture_service_resumed_count == 1u);

  assert(otis_pps_diagnostics_poll(&diagnostics, 8u * kTicksPerSecond) ==
         OtisPpsDiagnosticsTransition::CaptureServiceStale);
  assert(otis_pps_diagnostics_poll(&diagnostics,
                                   8u * kTicksPerSecond + 1u) ==
         OtisPpsDiagnosticsTransition::None);
  assert(diagnostics.capture_service_stale_count == 2u);
  assert(otis_pps_diagnostics_note_capture_service(
             &diagnostics, 1u, 8u * kTicksPerSecond + 10u) ==
         OtisPpsDiagnosticsTransition::CaptureServiceResumed);
  assert(diagnostics.capture_service_resumed_count == 2u);
}

void test_continuing_capture_service_is_independent_of_delayed_drain(void) {
  OtisPpsDiagnostics diagnostics;
  otis_pps_diagnostics_begin(&diagnostics, config(), 3u, 0u);

  for (uint32_t sequence = 0u; sequence < 12u; ++sequence) {
    const uint64_t ticks = (uint64_t)(sequence + 1u) * kTicksPerSecond;
    assert(otis_pps_diagnostics_note_capture_service(
               &diagnostics, sequence, ticks) ==
           OtisPpsDiagnosticsTransition::None);
    otis_pps_diagnostics_note_snapshot_produced(&diagnostics, 3u, sequence,
                                                ticks);
    otis_pps_diagnostics_note_foreground_backlog(
        &diagnostics, sequence + 1u, 128u, ticks + 100u);
    assert(otis_pps_diagnostics_poll(
               &diagnostics, ticks + 2u * kTicksPerSecond) ==
           OtisPpsDiagnosticsTransition::None);
  }

  assert(diagnostics.capture_service_state ==
         OtisPpsCaptureServiceState::Present);
  assert(diagnostics.capture_service_stale_count == 0u);
  assert(diagnostics.latest_snapshot_produced.sequence == 11u);
  assert(!diagnostics.latest_snapshot_drained.valid);
  assert(diagnostics.foreground_backlog_depth == 12u);
  assert(diagnostics.foreground_backlog_high_water == 12u);
  assert(diagnostics.foreground_backlog_transition_count == 1u);
}

void test_drained_and_service_progress_cannot_rearm_an_outage(void) {
  OtisPpsDiagnostics diagnostics;
  otis_pps_diagnostics_begin(&diagnostics, config(), 9u, 0u);
  assert(otis_pps_diagnostics_note_capture_service(
             &diagnostics, 40u, kTicksPerSecond) ==
         OtisPpsDiagnosticsTransition::None);
  assert(otis_pps_diagnostics_poll(&diagnostics, 4u * kTicksPerSecond) ==
         OtisPpsDiagnosticsTransition::CaptureServiceStale);

  otis_pps_diagnostics_note_snapshot_drained(
      &diagnostics, 9u, 38u, 4u * kTicksPerSecond + 1u);
  otis_pps_diagnostics_note_measurement_reconstructed(
      &diagnostics, 9u, 37u, 4u * kTicksPerSecond + 2u);
  otis_pps_diagnostics_note_telemetry_emitted(
      &diagnostics, 9u, 36u, 4u * kTicksPerSecond + 3u);
  otis_pps_diagnostics_note_control_observed(
      &diagnostics, 9u, 35u, 4u * kTicksPerSecond + 4u);
  otis_pps_diagnostics_note_foreground_backlog(
      &diagnostics, 4u, 128u, 4u * kTicksPerSecond + 5u);
  otis_pps_diagnostics_note_telemetry_backpressure(
      &diagnostics, true, 4u * kTicksPerSecond + 6u);

  assert(diagnostics.capture_service_state ==
         OtisPpsCaptureServiceState::Stale);
  assert(diagnostics.capture_service_stale_count == 1u);
  assert(diagnostics.capture_service_resumed_count == 0u);

  // Re-reading the same producer frontier is not resumed service either.
  assert(otis_pps_diagnostics_note_capture_service(
             &diagnostics, 40u, kTicksPerSecond) ==
         OtisPpsDiagnosticsTransition::None);
  assert(diagnostics.capture_service_state ==
         OtisPpsCaptureServiceState::Stale);

  assert(otis_pps_diagnostics_note_capture_service(
             &diagnostics, 41u, 5u * kTicksPerSecond) ==
         OtisPpsDiagnosticsTransition::CaptureServiceResumed);
  assert(diagnostics.capture_service_resumed_count == 1u);
  assert(otis_pps_diagnostics_note_capture_service(
             &diagnostics, 41u, 5u * kTicksPerSecond) ==
         OtisPpsDiagnosticsTransition::None);
  assert(diagnostics.capture_service_resumed_count == 1u);
}

void test_timer_and_capture_sequence_wrap(void) {
  OtisPpsDiagnostics diagnostics;
  const uint64_t started = kMonotonicUs32Modulus - 2u * kTicksPerSecond;
  otis_pps_diagnostics_begin(&diagnostics, config(), 11u, started);

  assert(otis_pps_diagnostics_note_capture_service(
             &diagnostics, UINT32_MAX,
             kMonotonicUs32Modulus - kTicksPerSecond) ==
         OtisPpsDiagnosticsTransition::None);
  assert(otis_pps_diagnostics_poll(&diagnostics, kTicksPerSecond) ==
         OtisPpsDiagnosticsTransition::None);
  assert(otis_pps_diagnostics_poll(&diagnostics, 2u * kTicksPerSecond) ==
         OtisPpsDiagnosticsTransition::CaptureServiceStale);
  assert(diagnostics.capture_service_stale_count == 1u);

  assert(otis_pps_diagnostics_note_capture_service(
             &diagnostics, 0u, 2u * kTicksPerSecond + 1u) ==
         OtisPpsDiagnosticsTransition::CaptureServiceResumed);
  assert(diagnostics.latest_capture_service.sequence == 0u);
  assert(diagnostics.capture_sequence_gap_count == 0u);
}

void test_reset_during_outage_starts_a_new_session(void) {
  OtisPpsDiagnostics diagnostics;
  otis_pps_diagnostics_begin(&diagnostics, config(), 15u, 0u);
  assert(otis_pps_diagnostics_poll(&diagnostics, 3u * kTicksPerSecond) ==
         OtisPpsDiagnosticsTransition::CaptureServiceStale);

  otis_pps_diagnostics_reset(&diagnostics, 16u, 4u * kTicksPerSecond);
  assert(diagnostics.session == 16u);
  assert(diagnostics.capture_service_state ==
         OtisPpsCaptureServiceState::NeverSeen);
  assert(diagnostics.capture_service_stale_count == 0u);
  assert(diagnostics.capture_service_resumed_count == 0u);
  assert(!diagnostics.latest_capture_service.valid);

  otis_pps_diagnostics_note_snapshot_drained(
      &diagnostics, 15u, 99u, 4u * kTicksPerSecond + 1u);
  assert(diagnostics.capture_service_state ==
         OtisPpsCaptureServiceState::NeverSeen);
  assert(otis_pps_diagnostics_note_capture_service(
             &diagnostics, 0u, 5u * kTicksPerSecond) ==
         OtisPpsDiagnosticsTransition::None);
  assert(diagnostics.capture_service_state ==
         OtisPpsCaptureServiceState::Present);
  assert(diagnostics.capture_service_resumed_count == 0u);
}

void test_progress_and_backpressure_markers_remain_distinct(void) {
  OtisPpsDiagnostics diagnostics;
  otis_pps_diagnostics_begin(&diagnostics, config(), 21u, 100u);
  otis_pps_diagnostics_note_capture_service(&diagnostics, 10u, 110u);
  otis_pps_diagnostics_note_snapshot_produced(&diagnostics, 21u, 20u, 120u);
  otis_pps_diagnostics_note_snapshot_drained(&diagnostics, 21u, 19u, 130u);
  otis_pps_diagnostics_note_measurement_reconstructed(&diagnostics, 21u, 18u,
                                                      140u);
  otis_pps_diagnostics_note_telemetry_emitted(&diagnostics, 21u, 17u, 150u);
  otis_pps_diagnostics_note_control_observed(&diagnostics, 21u, 16u, 160u);

  assert(diagnostics.latest_capture_service.sequence == 10u);
  assert(diagnostics.latest_snapshot_produced.sequence == 20u);
  assert(diagnostics.latest_snapshot_drained.sequence == 19u);
  assert(diagnostics.latest_measurement_reconstructed.sequence == 18u);
  assert(diagnostics.latest_telemetry_emitted.sequence == 17u);
  assert(diagnostics.latest_control_observed.sequence == 16u);

  otis_pps_diagnostics_note_foreground_backlog(&diagnostics, 3u, 128u, 170u);
  otis_pps_diagnostics_note_foreground_backlog(&diagnostics, 7u, 128u, 180u);
  otis_pps_diagnostics_note_foreground_backlog(&diagnostics, 0u, 128u, 190u);
  assert(!diagnostics.foreground_backlog_active);
  assert(diagnostics.foreground_backlog_high_water == 7u);
  assert(diagnostics.foreground_backlog_transition_count == 1u);
  assert(diagnostics.foreground_backlog_cleared_count == 1u);

  otis_pps_diagnostics_note_telemetry_backpressure(&diagnostics, true, 200u);
  otis_pps_diagnostics_note_telemetry_backpressure(&diagnostics, true, 210u);
  otis_pps_diagnostics_note_telemetry_backpressure(&diagnostics, false, 220u);
  assert(!diagnostics.telemetry_backpressure_active);
  assert(diagnostics.telemetry_backpressure_transition_count == 1u);
  assert(diagnostics.telemetry_backpressure_cleared_count == 1u);

  assert(diagnostics.capture_service_state ==
         OtisPpsCaptureServiceState::Present);
  assert(diagnostics.capture_service_stale_count == 0u);
  assert(diagnostics.capture_service_resumed_count == 0u);
}

void test_reminders_can_be_disabled(void) {
  OtisPpsDiagnostics diagnostics;
  OtisPpsDiagnosticsConfig no_reminders = config();
  no_reminders.missing_reminder_period_ticks = 0u;
  otis_pps_diagnostics_begin(&diagnostics, no_reminders, 22u, 0u);
  assert(otis_pps_diagnostics_poll(&diagnostics, 3u * kTicksPerSecond) ==
         OtisPpsDiagnosticsTransition::CaptureServiceStale);
  assert(otis_pps_diagnostics_poll(&diagnostics, 30u * kTicksPerSecond) ==
         OtisPpsDiagnosticsTransition::None);
  assert(diagnostics.capture_service_stale_count == 1u);
  assert(diagnostics.capture_service_reminder_count == 0u);
}

}  // namespace

int main(void) {
  test_never_seen_stale_and_resumed();
  test_continuing_capture_service_is_independent_of_delayed_drain();
  test_drained_and_service_progress_cannot_rearm_an_outage();
  test_timer_and_capture_sequence_wrap();
  test_reset_during_outage_starts_a_new_session();
  test_progress_and_backpressure_markers_remain_distinct();
  test_reminders_can_be_disabled();
  return 0;
}
