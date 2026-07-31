#include <cstring>
#include <iostream>
#include <string>

#include "otis_phase4_observe_preview.h"
#include "otis_protocol.h"
#include "otis_transport_serial.h"

namespace {

std::string output;
uint32_t capture_drops = 0u;
size_t transport_capacity = 4096u;
bool resource_registry_ok = true;

}  // namespace

uint32_t otis_capture_ring_dropped_count(void) { return capture_drops; }
bool otis_resource_registry_valid(void) { return resource_registry_ok; }
bool otis_resource_registry_complete(void) { return resource_registry_ok; }

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

size_t otis_transport_available_for_write(void) { return transport_capacity; }
bool otis_transport_begin(uint32_t) { return true; }
void otis_transport_flush_if_needed(void) {}
bool otis_transport_ready(void) { return true; }

void otis_status_emit_init(OtisStatusEmitContext *, uint32_t *) {}
void otis_status_emit(OtisStatusEmitContext *, const char *, const char *,
                      const char *, const char *, uint32_t) {}
void otis_status_emit_u32(OtisStatusEmitContext *, const char *, const char *,
                          uint32_t, const char *, uint32_t) {}

int main(int argc, char **argv) {
  constexpr uint64_t kTickHz = 16000000ull;
  constexpr uint32_t kGateSeconds = 300u;
  constexpr uint64_t kNominalGateEdges = 3000000300ull;
  const std::string scenario = argc > 1 ? argv[1] : "nominal";
  int64_t final_gate_delta_ticks = 0;
  if (scenario == "gate_plus_1us") final_gate_delta_ticks = 16;
  if (scenario == "gate_minus_1us") final_gate_delta_ticks = -16;
  if (scenario == "gate_plus_1ms") final_gate_delta_ticks = 16000;
  if (scenario == "gate_minus_1ms") final_gate_delta_ticks = -16000;
  if (scenario == "gate_egregious") {
    final_gate_delta_ticks = (int64_t)kTickHz / 2;
  }
  OtisRuntimeState runtime = {};
  if (scenario == "resource_failure") resource_registry_ok = false;
  runtime.sequences.estimate_seq = 1u;
  runtime.sequences.control_seq = 1u;
  OtisPhase4LiveDacState dac = {true, 0xA950u};
  otis_phase4_observe_preview_begin(0u);
  otis_phase4_observe_preview_on_dac_applied(dac.applied_code, 0u);
  if (scenario == "temperature_stale") {
    otis_phase4_observe_preview_on_temperature(true, 29.0f, 0u);
  }
  otis_phase4_observe_preview_emit_headers();
  otis_phase4_observe_preview_poll(2u * kTickHz, &runtime, &dac);
  do {
    otis_phase4_observe_preview_service_transport();
  } while (otis_phase4_observe_preview_transport_busy());
  if (scenario == "resource_failure") resource_registry_ok = true;
  otis_phase4_observe_preview_on_reference(
      1u, 2u * kTickHz, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED, &runtime, &dac);
  do {
    otis_phase4_observe_preview_service_transport();
  } while (otis_phase4_observe_preview_transport_busy());
  if (scenario == "output_backpressure") transport_capacity = 0u;

  uint32_t reference_seq = 1u;
  uint32_t last_reference_second = 2u;
  for (uint32_t count_seq = 1u; count_seq <= 5u; ++count_seq) {
    const uint32_t close_second =
        2u + count_seq * kGateSeconds;
    for (uint32_t second = last_reference_second + 1u;
         second <= close_second; ++second) {
      otis_phase4_observe_preview_on_reference(
          ++reference_seq, (uint64_t)second * kTickHz,
          OTIS_FLAG_TIMESTAMP_RECONSTRUCTED, &runtime, &dac);
    }
    last_reference_second = close_second;
    runtime.tcxo.last_gate_open_ticks =
        (uint64_t)(close_second - kGateSeconds) * kTickHz;
    runtime.tcxo.last_gate_close_ticks =
        (uint64_t)close_second * kTickHz;
    runtime.tcxo.last_counted_edges = kNominalGateEdges;
    runtime.tcxo.last_window_flags = OTIS_FLAG_TIMESTAMP_RECONSTRUCTED;
    if (scenario != "temperature_missing" &&
        scenario != "temperature_stale") {
      const float temperature =
          scenario == "temperature_outside" ? 31.0f : 29.0f;
      otis_phase4_observe_preview_on_temperature(
          true, temperature, runtime.tcxo.last_gate_close_ticks);
    }
    otis_phase4_observe_preview_on_count(count_seq, &runtime, &dac);
    if (scenario != "output_backpressure") {
      do {
        otis_phase4_observe_preview_service_transport();
      } while (otis_phase4_observe_preview_transport_busy());
      // The first service may complete a whole frame, leaving busy false.
      otis_phase4_observe_preview_service_transport();
    }
    if (count_seq == 2u &&
        (scenario == "settling_boundary" ||
         scenario == "settling_straddling")) {
      const uint64_t change_ticks =
          scenario == "settling_boundary"
              ? 602u * kTickHz + kTickHz / 2u
              : 603u * kTickHz;
      dac.applied_code = 0xA951u;
      otis_phase4_observe_preview_on_dac_applied(
          dac.applied_code, change_ticks);
    }
  }
  if (scenario == "output_backpressure") {
    transport_capacity = 4096u;
    for (uint32_t index = 0u; index < 1000u; ++index)
      otis_phase4_observe_preview_service_transport();
  }

  // Non-PPS-aligned count: the adapter must retain it until the next REF
  // supplies the following bracket for the close boundary.
  for (uint32_t second = last_reference_second + 1u;
       second <= 1802u; ++second) {
    otis_phase4_observe_preview_on_reference(
        ++reference_seq, (uint64_t)second * kTickHz,
        OTIS_FLAG_TIMESTAMP_RECONSTRUCTED, &runtime, &dac);
  }
  runtime.tcxo.last_gate_open_ticks =
      1502u * kTickHz + kTickHz / 2u;
  runtime.tcxo.last_gate_close_ticks =
      (uint64_t)((int64_t)runtime.tcxo.last_gate_open_ticks +
                 (int64_t)kGateSeconds * (int64_t)kTickHz +
                 final_gate_delta_ticks);
  runtime.tcxo.last_counted_edges =
      (uint64_t)((int64_t)3000000400ull +
                 final_gate_delta_ticks * 5 / 8);
  runtime.tcxo.last_window_flags = OTIS_FLAG_TIMESTAMP_RECONSTRUCTED;
  if (scenario == "temperature_loss") {
    otis_phase4_observe_preview_on_temperature(
        false, 0.0f, runtime.tcxo.last_gate_close_ticks);
  } else if (scenario != "temperature_missing" &&
             scenario != "temperature_stale") {
    const float temperature =
        scenario == "temperature_outside" ? 31.0f : 29.0f;
    otis_phase4_observe_preview_on_temperature(
        true, temperature, runtime.tcxo.last_gate_close_ticks);
  }
  otis_phase4_observe_preview_on_count(6u, &runtime, &dac);
  otis_phase4_observe_preview_on_reference(
      ++reference_seq, 1803u * kTickHz,
      OTIS_FLAG_TIMESTAMP_RECONSTRUCTED, &runtime, &dac);
  do {
    otis_phase4_observe_preview_service_transport();
  } while (otis_phase4_observe_preview_transport_busy());
  otis_phase4_observe_preview_service_transport();
  if (scenario == "output_backpressure") {
    otis_phase4_observe_preview_poll(1805u * kTickHz, &runtime, &dac);
    for (uint32_t index = 0u; index < 1000u; ++index)
      otis_phase4_observe_preview_service_transport();
  }

  std::cout << output;
  return 0;
}
