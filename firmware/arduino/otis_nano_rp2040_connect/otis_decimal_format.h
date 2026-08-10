#ifndef OTIS_DECIMAL_FORMAT_H
#define OTIS_DECIMAL_FORMAT_H

#include <stddef.h>
#include <stdint.h>

// Deterministic fixed-point conversion without printf's floating-point path.
// The Arduino-Pico libc float formatter is not assumed to be cross-core
// reentrant. Timing-core code must use this helper before passing text to the
// ordinary integer/string-only snprintf path on either core.
bool otis_format_fixed(double value, uint8_t decimal_places, char *output,
                       size_t output_size);

#endif
