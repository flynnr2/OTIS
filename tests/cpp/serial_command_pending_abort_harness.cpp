// Execute the actual .ino collector/service function against a blocked output
// seam, with the real frame collector, validator and command parser.
#include <cassert>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include "otis_serial_command.h"
#include "otis_protocol.h"

struct SerialFixture {
  std::string input;
  size_t cursor = 0;
  unsigned reads = 0;
  int available() const { return static_cast<int>(input.size() - cursor); }
  int read() { ++reads; return static_cast<unsigned char>(input[cursor++]); }
} Serial;
OtisSerialFrameCollector serial_command_collector{};
bool deferred_serial_command_ready = false;
char deferred_serial_command[OTIS_SERIAL_COMMAND_BUFFER_SIZE]{};
OtisSerialFrameEvent deferred_serial_error = OtisSerialFrameEvent::None;
bool deferred_serial_invalid = false;
bool deferred_abort_result_ready = false;
bool deferred_abort_queued = false;
enum class OtisRunControlKind { Abort };
static unsigned aborts = 0;
static std::vector<OtisSerialCommandKind> executed;
static std::vector<std::string> emitted;
static bool allow_output = false;
static const std::string partial_status = "STS,1,7,123,rp2040_";
static std::string wire = partial_status;

bool queue_dual_core_active_control(OtisRunControlKind kind) {
  assert(kind == OtisRunControlKind::Abort); ++aborts; return true;
}
void emit_status(const char *component, const char *key, const char *value,
                 const char *, uint32_t) {
  assert(allow_output);  // No acknowledgement may split the pending STS row.
  emitted.push_back(std::string(component) + ":" + key + ":" + value);
  wire += emitted.back() + "\r\n";
}
void emit_status_u32(const char *component, const char *key, uint32_t value,
                    const char *severity, uint32_t flags) {
  emit_status(component, key, std::to_string(value).c_str(), severity, flags);
}
void execute_serial_command(const OtisParsedSerialCommand &command) {
  assert(allow_output);
  executed.push_back(command.kind);
}
#include "serial_command_service.inc"

static void service(bool output) {
  allow_output = output;
  const unsigned before = Serial.reads;
  service_serial_commands(output);
  assert(Serial.reads - before <= 32);
}

static void drain_blocked_input() {
  for (unsigned attempts = 0; Serial.available() && attempts < 128; ++attempts)
    service(false);
  assert(Serial.available() == 0);
}

int main() {
  otis_serial_frame_collector_init(&serial_command_collector);
  Serial.input = "COUNT?\nHELP\nACTIVE ABORT\nDUALCORE?\nACTIVE ABORT\n";
  drain_blocked_input();
  assert(aborts == 2);
  assert(deferred_serial_command_ready);
  assert(std::string(deferred_serial_command) == "COUNT?");
  assert(executed.empty() && emitted.empty());
  assert(wire == partial_status);
  // Completing the retained output row permits acknowledgements and exactly
  // one execution of the original command. Extra normal commands are counted.
  wire += "complete\r\n";
  for (unsigned i = 0; i != 6; ++i) service(true);
  assert(executed == std::vector<OtisSerialCommandKind>{OtisSerialCommandKind::CountQuery});
  assert(!deferred_serial_command_ready);
  assert(emitted.size() == 2);
  assert(emitted[0] == "adaptive_hybrid_regulation:abort_firmware_received:queued_to_core1");
  assert(emitted[1] == "command:deferred_commands_rejected:2");

  // A malformed or oversized line cannot hide an abort suffix as a command,
  // and must not block a later correctly framed abort behind the retained one.
  Serial.input = "CONFIG?\n" + std::string(200, 'X') + "ACTIVE ABORT\n";
  Serial.input += std::string("HELP\0ACTIVE ABORT\n", 18) + "ACTIVE ABORT\n";
  Serial.cursor = 0;
  drain_blocked_input();
  assert(aborts == 3);
  assert(std::string(deferred_serial_command) == "CONFIG?");
  for (unsigned i = 0; i != 8; ++i) service(true);
  assert(executed.size() == 2 && executed.back() == OtisSerialCommandKind::ConfigQuery);
  assert(aborts == 3);
}
