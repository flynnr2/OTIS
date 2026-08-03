#include <cstring>
#include <iostream>
#include <string>

#include "otis_cx317_preview_live.h"
#include "otis_transport_serial.h"

namespace {
std::string output;
}

size_t otis_transport_write_char(char value) {
  output.push_back(value);
  return 1u;
}
size_t otis_transport_write_cstr(const char *value) {
  output += value;
  return std::strlen(value);
}
size_t otis_transport_write_bytes(const uint8_t *data, size_t length) {
  output.append(reinterpret_cast<const char *>(data), length);
  return length;
}
size_t otis_transport_write_uint32(uint32_t value) {
  const std::string text = std::to_string(value);
  output += text;
  return text.size();
}
size_t otis_transport_available_for_write(void) { return 4096u; }
bool otis_transport_begin(uint32_t) { return true; }
void otis_transport_flush_if_needed(void) {}
bool otis_transport_ready(void) { return true; }
void otis_status_emit_init(OtisStatusEmitContext *, uint32_t *) {}
void otis_status_emit(OtisStatusEmitContext *, const char *, const char *,
                      const char *, const char *, uint32_t) {}
void otis_status_emit_u32(OtisStatusEmitContext *, const char *, const char *,
                          uint32_t, const char *, uint32_t) {}

int main() {
  constexpr uint64_t kTicksPerSecond = 16000000ull;
  otis_cx317_preview_live_begin(0u);
  otis_cx317_preview_live_emit_headers();
  otis_cx317_preview_live_on_temperature(true, 29.0f, 0u);
  otis_cx317_preview_live_on_dac_applied(0xA950u, 0u);
  const OtisCx317StaticCodeState code = {true, true, true, 0xA950u};
  uint32_t counter = 0xffffffffu;
  for (uint32_t second = 1u; second <= 2400u; ++second) {
    counter -= 10000000u;
    const OtisPpsCountBoundaryObservation observation = {
        1u, second, second, second * kTicksPerSecond, counter, 10000000u, 0u, 0u,
    };
    otis_cx317_preview_live_on_boundary(
        &observation, 10000000u, true, second, &code, nullptr);
    for (uint8_t drain = 0u; drain < 16u; ++drain) {
      otis_cx317_preview_live_service_transport();
    }
  }
  std::cout << output;
  return 0;
}
