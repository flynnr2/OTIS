#include "otis_transport_serial.h"

#include <Arduino.h>

void otis_transport_begin(uint32_t baud) {
  Serial.begin(baud);
}

size_t otis_transport_write_char(char c) {
  return Serial.print(c);
}

size_t otis_transport_write_cstr(const char *s) {
  return Serial.print(s);
}

size_t otis_transport_write_uint32(uint32_t v) {
  return Serial.print(v);
}

void otis_transport_flush_if_needed(void) {
  // Future output-budgeting hook: serial backpressure detection can decide
  // whether flushing is safe once capture-first loop service is enforced.
}

bool otis_transport_ready(void) {
  return Serial;
}
