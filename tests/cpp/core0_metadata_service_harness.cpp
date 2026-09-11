#include <cassert>
#include <cstdint>
#include "otis_transport_liveness.h"

// Hardware/services are doubles; transport liveness and the entire loop
// dispatcher are production code. No serial owner or physical actuator runs.
struct { struct { bool safe_mode_active; } boot; } runtime_state = {};
OtisTransportLiveness dual_core_transport_liveness = {};
bool dual_core_transport_abort_queued = false;
enum class OtisPartitionFault { TransportObstructed };
enum class OtisRunControlKind { Abort };
static uint32_t clock_ms, receiver_generation, published_generation;
static unsigned metadata_calls, normal_output_calls, discarded, fault_discarded;
static unsigned abandoned, aborts, faults, input_only_calls, boot_calls;
static bool carrier, pending_frame;

uint32_t millis() { return clock_ms; }
void otis_memory_budget_note_current_core() {}
void emit_boot_records_if_serial_ready() { ++boot_calls; }
void otis_gnss_receiver_service(uint32_t now) {
  assert(now == clock_ms);
  ++receiver_generation;
}
void publish_dual_core_service_metadata(uint32_t now) {
  assert(now == clock_ms);
  // Observe invocation ordering: publication must see this loop's fresh
  // receiver state. The publisher's cadence/queue policy remains unchanged.
  assert(receiver_generation == published_generation + 1u);
  published_generation = receiver_generation;
  ++metadata_calls;
}
bool otis_transport_ready() { return carrier; }
uint64_t otis_transport_written_bytes() { return 0u; }
void otis_dual_core_latch_fault(OtisPartitionFault) { ++faults; }
void discard_dual_core_outputs_after_transport_fault() { ++fault_discarded; }
void abandon_dual_core_serial_frames_on_carrier_loss() { ++abandoned; }
void discard_dual_core_outputs_before_first_carrier() { ++discarded; }
void service_serial_commands(bool permit_normal = true) {
  if (!permit_normal) ++input_only_calls;
}
bool service_dual_core_serial_frame_transport() { return pending_frame; }
bool queue_dual_core_active_control(OtisRunControlKind) { ++aborts; return true; }
void service_dual_core_outputs() { ++normal_output_calls; }
void emit_protocol_banner_if_serial_ready() {}
void emit_run_mode_status_if_ready() {}
void emit_resource_ownership_status() {}
void service_environment_sensors() {}
void emit_periodic_status() {}

#include "core0_loop.inc"

int main() {
  // First boot without a carrier: publish internal state, discard external
  // output, and never reach the normal critical-command/actuator dispatcher.
  clock_ms = 1000u;
  loop();
  loop();
  assert(metadata_calls == 2u && discarded == 2u && abandoned == 2u);
  assert(normal_output_calls == 0u && aborts == 0u && faults == 0u);

  // Attached but frame-obstructed also keeps metadata current.
  carrier = true;
  pending_frame = true;
  loop();
  assert(metadata_calls == 3u && normal_output_calls == 0u);
  assert(dual_core_transport_liveness.state ==
         OtisTransportLivenessState::FrameObstructed);
  clock_ms += OTIS_MAXIMUM_SUPPORTED_TX_OBSTRUCTION_MS;
  loop();
  assert(metadata_calls == 4u && fault_discarded == 1u);
  assert(aborts == 1u && faults == 1u && normal_output_calls == 0u);

  // Detaching cannot clear an already latched transport fault or execute a
  // queued actuator command; internal state still reaches the timing core.
  carrier = false;
  loop();
  assert(metadata_calls == 5u && fault_discarded == 2u);
  assert(discarded == 2u && normal_output_calls == 0u);
  assert(dual_core_transport_liveness.state == OtisTransportLivenessState::Faulted);

  // A separately initialized healthy path publishes once, then normal output.
  otis_transport_liveness_reset(&dual_core_transport_liveness, clock_ms, 0u);
  carrier = true;
  pending_frame = false;
  loop();
  assert(metadata_calls == 6u && normal_output_calls == 1u);
  assert(input_only_calls == 5u);
  runtime_state.boot.safe_mode_active = true;
  loop();
  assert(boot_calls == 1u && metadata_calls == 6u);
}
