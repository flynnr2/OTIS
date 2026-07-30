#ifndef OTIS_TRANSPORT_SERIAL_H
#define OTIS_TRANSPORT_SERIAL_H

#include <stddef.h>
#include <stdint.h>

bool otis_transport_begin(uint32_t baud);
size_t otis_transport_write_char(char c);
size_t otis_transport_write_cstr(const char *s);
size_t otis_transport_write_bytes(const uint8_t *data, size_t length);
size_t otis_transport_write_uint32(uint32_t v);
size_t otis_transport_available_for_write(void);
void otis_transport_flush_if_needed(void);
bool otis_transport_ready(void);

#endif
