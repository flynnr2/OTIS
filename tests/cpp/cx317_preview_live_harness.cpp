#include <cassert>
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

int main(int argc, char **argv) {
  const bool recovery_mode = argc == 2 && std::string(argv[1]) == "recovery";
  const bool response_window_mode =
      argc == 2 && std::string(argv[1]) == "response_window";
  const bool fractional_exact_response_window_mode =
      argc == 2 &&
      std::string(argv[1]) == "fractional_exact_response_window";
  constexpr uint64_t kTicksPerSecond = 16000000ull;
  otis_cx317_preview_live_begin(0u);
  otis_cx317_preview_live_emit_headers();
  otis_cx317_preview_live_on_temperature(true, 29.0f, 0u);
  otis_cx317_preview_live_on_dac_applied(0xA82Au, 0u);
  const OtisCx317StaticCodeState code = {true, true, true, 0xA82Au};
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
  if (recovery_mode) {
    otis_cx317_preview_live_on_capture_fault(
        "controlled_metadata_invalidation", 2401u, &code);
    assert(!otis_cx317_preview_live_request_recovery());
    for (uint32_t second = 2401u; second <= 4201u; ++second) {
      counter -= 10000000u;
      const OtisPpsCountBoundaryObservation observation = {
          1u, second, second, second * kTicksPerSecond, counter, 10000000u,
          0u, 0u,
      };
      otis_cx317_preview_live_on_boundary(
          &observation, 10000000u, true, second, &code, nullptr);
      for (uint8_t drain = 0u; drain < 16u; ++drain) {
        otis_cx317_preview_live_service_transport();
      }
    }
    assert(!otis_cx317_preview_live_request_recovery());
    std::cerr << "recovery_fixture_pass\n";
  }
  if (response_window_mode) {
    constexpr uint32_t kApplicationTimestampS = 2401u;
    otis_cx317_preview_live_on_dac_applied_epoch(
        0xA82Bu, 2u, kApplicationTimestampS);
    const OtisCx317StaticCodeState response_code = {
        true, true, true, 0xA82Bu};
    for (uint32_t second = kApplicationTimestampS; second <= 3901u;
         ++second) {
      counter -= 10000000u;
      const OtisPpsCountBoundaryObservation observation = {
          1u, second, second, second * kTicksPerSecond, counter, 10000000u,
          0u, 0u,
      };
      otis_cx317_preview_live_on_boundary(
          &observation, 10000000u, true, second, &response_code, nullptr);
      for (uint8_t drain = 0u; drain < 16u; ++drain) {
        otis_cx317_preview_live_service_transport();
      }
    }
  }
  if (fractional_exact_response_window_mode) {
    constexpr uint32_t kApplicationTimestampS = 2401u;
    constexpr uint64_t kApplicationTimestampTicks =
        kApplicationTimestampS * kTicksPerSecond + kTicksPerSecond / 2u;
    counter -= 10000000u;
    const OtisPpsCountBoundaryObservation pre_application_boundary = {
        1u, kApplicationTimestampS, kApplicationTimestampS,
        kApplicationTimestampS * kTicksPerSecond, counter, 10000000u,
        0u, 0u,
    };
    otis_cx317_preview_live_on_boundary(
        &pre_application_boundary, 10000000u, true,
        kApplicationTimestampS, &code, nullptr);
    otis_cx317_preview_live_on_dac_applied_epoch_exact(
        0xA82Bu, 2u, kApplicationTimestampS, kApplicationTimestampTicks, 1u);
    const OtisCx317StaticCodeState response_code = {
        true, true, true, 0xA82Bu};
    for (uint32_t second = kApplicationTimestampS + 1u; second <= 3902u;
         ++second) {
      counter -= 10000000u;
      const OtisPpsCountBoundaryObservation observation = {
          1u, second, second, second * kTicksPerSecond, counter, 10000000u,
          0u, 0u,
      };
      otis_cx317_preview_live_on_boundary(
          &observation, 10000000u, true, second, &response_code, nullptr);
      for (uint8_t drain = 0u; drain < 16u; ++drain) {
        otis_cx317_preview_live_service_transport();
      }
    }
  }
  std::cout << output;
  return 0;
}
