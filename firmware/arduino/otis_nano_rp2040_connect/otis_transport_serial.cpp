#include "otis_transport_serial.h"

#include <Arduino.h>

namespace {
uint64_t written_bytes = 0u;

size_t note_written(size_t count) {
  written_bytes += count;
  return count;
}
}  // namespace

bool otis_transport_begin(uint32_t baud) {
  Serial.begin(baud);
  return true;
}

size_t otis_transport_write_char(char c) {
  return note_written(Serial.print(c));
}

size_t otis_transport_write_cstr(const char *s) {
  return note_written(Serial.print(s));
}

size_t otis_transport_write_bytes(const uint8_t *data, size_t length) {
  return note_written(Serial.write(data, length));
}

size_t otis_transport_write_uint32(uint32_t v) {
  return note_written(Serial.print(v));
}

size_t otis_transport_available_for_write(void) {
  if (!Serial) {
    return 0u;
  }
  int available = Serial.availableForWrite();
  return available > 0 ? (size_t)available : 0u;
}

void otis_transport_flush_if_needed(void) {
  // Future output-budgeting hook: serial backpressure detection can decide
  // whether flushing is safe once capture-first loop service is enforced.
}

bool otis_transport_ready(void) {
  return Serial;
}

uint64_t otis_transport_written_bytes(void) { return written_bytes; }
