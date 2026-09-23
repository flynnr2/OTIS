#include <cassert>
#include <cstdint>
// Compile the actual Core 0 loop; hardware services are explicit doubles.
struct { struct { bool safe_mode_active; } boot; } runtime_state = {};
static uint32_t clock_ms, receiver_generation, published_generation;
static unsigned metadata_calls, executor_calls, normal_output_calls, discarded;
static unsigned abandoned, input_only_calls, boot_calls;
static bool carrier, pending_frame;
uint32_t millis() { return clock_ms; }
void otis_memory_budget_note_current_core() {}
void emit_boot_records_if_serial_ready() { ++boot_calls; }
void otis_gnss_receiver_service(uint32_t now) {assert(now==clock_ms);++receiver_generation;}
void service_instrument_executor() {assert(receiver_generation==executor_calls+1);++executor_calls;}
void publish_dual_core_service_metadata(uint32_t now) {
 assert(now==clock_ms && receiver_generation==published_generation+1 && executor_calls==receiver_generation);
 published_generation=receiver_generation;++metadata_calls;
}
bool otis_transport_ready() {return carrier;}
void abandon_dual_core_serial_frames_on_carrier_loss() {++abandoned;}
void discard_dual_core_outputs_before_first_carrier() {++discarded;}
void service_serial_commands(bool permit_normal=true) {if(!permit_normal)++input_only_calls;}
bool service_dual_core_serial_frame_transport() {return pending_frame;}
void service_dual_core_outputs() {++normal_output_calls;}
void emit_protocol_banner_if_serial_ready() {}
void emit_run_mode_status_if_ready() {}
void emit_resource_ownership_status() {}
void service_environment_sensors() {}
void emit_periodic_status() {}
void service_core0_description() {}
#include "core0_loop.inc"
int main() {
 clock_ms=1000;loop();loop();assert(metadata_calls==2 && executor_calls==2 && discarded==2 && abandoned==2);
 carrier=true;pending_frame=true;loop();clock_ms+=0x80000000;loop();
 assert(metadata_calls==4 && executor_calls==4 && normal_output_calls==0);
 carrier=false;loop();assert(metadata_calls==5 && executor_calls==5 && discarded==3);
 carrier=true;pending_frame=false;loop();assert(metadata_calls==6 && executor_calls==6 && normal_output_calls==1 && input_only_calls==5);
 runtime_state.boot.safe_mode_active=true;loop();assert(boot_calls==1 && metadata_calls==6);
}
