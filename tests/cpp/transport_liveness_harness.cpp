#include <assert.h>
#include <stdint.h>
#include <string.h>

#include "otis_dual_core_partition.h"
#include "otis_serial_command.h"
#include "otis_transport_liveness.h"

namespace {

void zero_capacity_faults_at_the_declared_boundary() {
  OtisTransportLiveness liveness = {};
  otis_transport_liveness_reset(&liveness, 100u, 50u);
  assert(otis_transport_liveness_observe(&liveness, 100u, true, 50u));
  assert(otis_transport_liveness_observe(
      &liveness, 100u + OTIS_MAXIMUM_SUPPORTED_TX_OBSTRUCTION_MS - 1u,
      true, 50u));
  assert(!otis_transport_liveness_observe(
      &liveness, 100u + OTIS_MAXIMUM_SUPPORTED_TX_OBSTRUCTION_MS, true,
      50u));
  assert(otis_transport_liveness_faulted(&liveness));
  assert(!otis_transport_liveness_observe(&liveness, 5000u, false, 100u));
}

void intermittent_progress_and_restore_are_bounded() {
  OtisTransportLiveness liveness = {};
  otis_transport_liveness_reset(&liveness, 0u, 0u);
  assert(otis_transport_liveness_observe(&liveness, 0u, true, 0u));
  assert(otis_transport_liveness_observe(&liveness, 750u, true, 1u));
  assert(otis_transport_liveness_observe(&liveness, 1500u, true, 2u));
  assert(otis_transport_liveness_observe(&liveness, 1900u, false, 2u));
  assert(liveness.state == OtisTransportLivenessState::Ready);
  assert(liveness.completed_obstructions == 1u);

  otis_transport_liveness_reset(&liveness, 3000u, 2u);
  assert(otis_transport_liveness_observe(&liveness, 3000u, true, 2u));
  assert(otis_transport_liveness_observe(&liveness, 4500u, true, 3u));
  assert(!otis_transport_liveness_observe(&liveness, 5000u, true, 4u));
  assert(otis_transport_liveness_faulted(&liveness));
}

void elapsed_comparison_crosses_millis_wrap() {
  OtisTransportLiveness liveness = {};
  const uint32_t start = UINT32_MAX - 500u;
  otis_transport_liveness_reset(&liveness, start, 0u);
  assert(otis_transport_liveness_observe(&liveness, start, true, 0u));
  assert(otis_transport_liveness_observe(&liveness, 999u, true, 0u));
  assert(!otis_transport_liveness_observe(&liveness, 1499u, true, 0u));
}

void explicit_abort_crosses_while_a_tx_frame_is_obstructed() {
  OtisTransportLiveness liveness = {};
  otis_transport_liveness_reset(&liveness, 100u, 41u);
  assert(otis_transport_liveness_observe(&liveness, 100u, true, 41u));

  OtisSerialFrameCollector collector = {};
  otis_serial_frame_collector_init(&collector);
  const char command[] = "ACTIVE ABORT\r";
  OtisSerialFrameEvent event = OtisSerialFrameEvent::None;
  for (size_t index = 0u; index < strlen(command); ++index) {
    event = otis_serial_frame_collect(&collector, command[index]);
    assert(otis_transport_liveness_observe(
        &liveness, 101u + static_cast<uint32_t>(index), true, 41u));
  }
  assert(event == OtisSerialFrameEvent::Complete);
  assert(otis_serial_frame_validate(&collector) ==
         OtisSerialFrameValidation::Valid);
  OtisParsedSerialCommand parsed =
      otis_serial_command_parse(collector.line);
  assert(parsed.kind == OtisSerialCommandKind::ActiveAbort);

  otis_dual_core_partition_reset();
  OtisServiceMessage published = {};
  published.kind = OtisServiceMessageKind::RunControl;
  published.run_control.sequence = 7u;
  published.run_control.kind = OtisRunControlKind::Abort;
  published.run_control.asserted = true;
  assert(otis_dual_core_publish_service(&published));
  OtisServiceMessage received = {};
  assert(otis_dual_core_take_service(&received));
  assert(received.kind == OtisServiceMessageKind::RunControl);
  assert(received.run_control.kind == OtisRunControlKind::Abort);
  assert(received.run_control.sequence == 7u);
  assert(liveness.state == OtisTransportLivenessState::FrameObstructed);
}

}  // namespace

int main() {
  zero_capacity_faults_at_the_declared_boundary();
  intermittent_progress_and_restore_are_bounded();
  elapsed_comparison_crosses_millis_wrap();
  explicit_abort_crosses_while_a_tx_frame_is_obstructed();
  return 0;
}
