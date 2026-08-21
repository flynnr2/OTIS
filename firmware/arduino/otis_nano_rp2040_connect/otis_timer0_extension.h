#ifndef OTIS_TIMER0_EXTENSION_H
#define OTIS_TIMER0_EXTENSION_H

#include <stdint.h>

struct OtisTimer0Extension {
  uint64_t raw_ticks;
  uint64_t extended_ticks;
  uint32_t capture_session;
  bool available;
};

void otis_timer0_extension_init(OtisTimer0Extension *extension);

bool otis_timer0_extension_seed(
    OtisTimer0Extension *extension, uint64_t extended_ticks,
    uint32_t capture_session);

bool otis_timer0_extension_advance_boundary(
    OtisTimer0Extension *extension, uint64_t raw_ticks,
    uint32_t capture_session, uint64_t *extended_ticks);

bool otis_timer0_extension_project_nearest(
    const OtisTimer0Extension *extension, uint64_t raw_ticks,
    uint32_t capture_session, uint64_t maximum_distance_ticks,
    uint64_t *extended_ticks);

#endif
