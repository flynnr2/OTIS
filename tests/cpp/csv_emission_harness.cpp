#include <stdint.h>

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

int main() {
  otis_emit_health(7u, 9u, "domain", "command", "unknown",
                   "bad,\"line\r\n%tail", "WARN", 0u);
  std::cout << output;
  return 0;
}
