#include <stdint.h>
#include <limits.h>

#include <iostream>
#include <string>

#include "otis_emit.h"

namespace {

std::string output;

}  // namespace

bool otis_transport_begin(uint32_t) { return true; }

size_t otis_transport_write_char(char value) {
  output.push_back(value);
  return 1u;
}

size_t otis_transport_write_cstr(const char *value) {
  if (value == nullptr) {
    return 0u;
  }
  output += value;
  return std::char_traits<char>::length(value);
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

size_t otis_transport_available_for_write(void) {
  return 1024u;
}

void otis_transport_flush_if_needed(void) {}

bool otis_transport_ready(void) {
  return true;
}

void emit_boundaries() {
  otis_emit_raw_event("EVT", 0u, 0u, "R", 0u, "rp2040_monotonic_us32", 0u);
  otis_emit_raw_event("REF", UINT32_MAX, 1u, "F", UINT64_MAX,
                      "rp2040_monotonic_us32", UINT32_MAX);
  otis_emit_count_observation(0u, 2u, 0u, 0u, "rp2040_monotonic_us32", 0u,
                              "R", "gpclk0_external_edges", 0u);
  otis_emit_count_observation(UINT32_MAX, UINT32_MAX, UINT64_MAX, UINT64_MAX,
                              "rp2040_monotonic_us32", UINT64_MAX, "B",
                              "gpclk0_external_edges", UINT32_MAX);
  otis_emit_health(UINT32_MAX, UINT64_MAX, "rp2040_monotonic_us32", "wire",
                   "boundary", "maximum", "INFO", UINT32_MAX);
  otis_emit_dac_step(0u, 0u, INT32_MIN, 0u, 0u, false, "", "", 0u,
                     "minimum", 0u);
  otis_emit_dac_step(UINT32_MAX, UINT32_MAX, INT32_MAX, UINT16_MAX, UINT16_MAX,
                     true, "1.25", "-1.25", UINT32_MAX, "maximum",
                     UINT32_MAX);
  otis_emit_environment(0u, 0u, "rp2040_monotonic_us32", "sht4x",
                        "vcocxo_near", "-1.25", "", "", 0u);
  otis_emit_environment(UINT32_MAX, UINT64_MAX, "rp2040_monotonic_us32",
                        "bmp280", "pressure_reference", "1.25", "",
                        "1.25", UINT32_MAX);
  otis_emit_pps_snapshot(0u, 0u, 0u, 0u, 0u, 0u, 0u, "pio_fifo_irq");
  otis_emit_pps_snapshot(UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX,
                         UINT64_MAX, UINT32_MAX, UINT32_MAX, "pio_fifo_irq");
  otis_emit_forwarded_monitor_snapshot(0u, 0u, 0u, 0u, 0u, 0u, 0u,
                                       "pio_dma", 3u);
  otis_emit_forwarded_monitor_snapshot(
      UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT64_MAX,
      UINT32_MAX, "pio_dma", UINT32_MAX);
}

int main(int argc, char **argv) {
  if (argc == 2 && std::string(argv[1]) == "boundaries") {
    emit_boundaries();
    std::cout << output;
    return 0;
  }
  otis_emit_health(7u, 9u, "domain", "command", "unknown",
                   "bad,\"line\r\n%tail", "WARN", 0u);
  std::cout << output;
  return 0;
}
