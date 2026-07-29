#include <cstring>
#include <iostream>
#include <string>

#include "otis_phase4_observe_preview.h"
#include "otis_protocol.h"
#include "otis_transport_serial.h"

namespace {

std::string output;
uint32_t capture_drops = 0u;

}  // namespace

uint32_t otis_capture_ring_dropped_count(void) { return capture_drops; }

size_t otis_transport_write_char(char c) {
  output.push_back(c);
  return 1u;
}

size_t otis_transport_write_cstr(const char *s) {
  output += s;
  return std::strlen(s);
}

size_t otis_transport_write_bytes(const uint8_t *data, size_t length) {
  output.append((const char *)data, length);
  return length;
}

size_t otis_transport_write_uint32(uint32_t value) {
  std::string text = std::to_string(value);
  output += text;
  return text.size();
}

size_t otis_transport_available_for_write(void) { return 4096u; }
void otis_transport_begin(uint32_t) {}
void otis_transport_flush_if_needed(void) {}
bool otis_transport_ready(void) { return true; }

void otis_status_emit_init(OtisStatusEmitContext *, uint32_t *) {}
void otis_status_emit(OtisStatusEmitContext *, const char *, const char *,
                      const char *, const char *, uint32_t) {}
void otis_status_emit_u32(OtisStatusEmitContext *, const char *, const char *,
                          uint32_t, const char *, uint32_t) {}

int main() {
  OtisRuntimeState runtime = {};
  runtime.sequences.estimate_seq = 1u;
  runtime.sequences.control_seq = 1u;
  OtisPhase4LiveDacState dac = {true, 0xA950u};
  otis_phase4_observe_preview_begin(0u);
  otis_phase4_observe_preview_emit_headers();
  otis_phase4_observe_preview_poll(32000000ull, &runtime, &dac);
  do {
    otis_phase4_observe_preview_service_transport();
  } while (otis_phase4_observe_preview_transport_busy());
  otis_phase4_observe_preview_on_reference(
      1u, 32000000ull, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED, &runtime, &dac);
  do {
    otis_phase4_observe_preview_service_transport();
  } while (otis_phase4_observe_preview_transport_busy());

  for (uint32_t seq = 1u; seq <= 5u; ++seq) {
    const uint64_t close = (uint64_t)(seq + 2u) * 16000000ull;
    otis_phase4_observe_preview_on_reference(
        seq + 1u, close, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED, &runtime, &dac);
    runtime.tcxo.last_gate_open_ticks = close - 16000000ull;
    runtime.tcxo.last_gate_close_ticks = close;
    runtime.tcxo.last_counted_edges = 10000001ull;
    runtime.tcxo.last_window_flags = OTIS_FLAG_TIMESTAMP_RECONSTRUCTED;
    otis_phase4_observe_preview_on_count(seq, &runtime, &dac);
    do {
      otis_phase4_observe_preview_service_transport();
    } while (otis_phase4_observe_preview_transport_busy());
    // The first service may complete a whole frame, leaving busy false.
    otis_phase4_observe_preview_service_transport();
  }
  std::cout << output;
  return 0;
}
