#ifndef OTIS_TRANSPORT_SERIAL_H
#define OTIS_TRANSPORT_SERIAL_H

#include <stddef.h>
#include <stdint.h>

bool otis_transport_begin(uint32_t baud);
size_t otis_transport_write_char(char c);
size_t otis_transport_write_cstr(const char *s);
size_t otis_transport_write_bytes(const uint8_t *data, size_t length);
// Optional row admission on the pinned bare-metal Arduino-Pico USB backend.
// One nonblocking USB-mutex attempt and one FIFO copy; reserve 64 bytes for
// canonical traffic. False drops the row without retry, wait, or fault.
// True means the entire row entered the CDC FIFO, not physical transmission.
// Call only from the sole foreground output owner between canonical frames.
// Startup/configuration (Serial.begin/end) must not race this function.
// USB task reset processing shares the mutex; physical disconnect can still
// discard accepted bytes later. No completion/delivery guarantee is implied.
bool otis_transport_try_write_diagnostic(const uint8_t *data, size_t length);
size_t otis_transport_write_uint32(uint32_t v);
size_t otis_transport_available_for_write(void);
void otis_transport_flush_if_needed(void);
bool otis_transport_ready(void);
uint64_t otis_transport_written_bytes(void);

#endif
