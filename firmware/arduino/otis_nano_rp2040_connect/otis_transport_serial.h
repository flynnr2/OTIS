#ifndef OTIS_TRANSPORT_SERIAL_H
#define OTIS_TRANSPORT_SERIAL_H

#include <stddef.h>
#include <stdint.h>

void otis_transport_begin(uint32_t baud);
size_t otis_transport_write_char(char c);
size_t otis_transport_write_cstr(const char *s);
size_t otis_transport_write_uint32(uint32_t v);
void otis_transport_flush_if_needed(void);
bool otis_transport_ready(void);

#endif
