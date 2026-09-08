#ifndef OTIS_MONOTONIC_US_EXTENSION_H
#define OTIS_MONOTONIC_US_EXTENSION_H

#include <stdint.h>

struct OtisMonotonicUsExtension {
  uint64_t raw_us;
  uint64_t extended_us;
  uint32_t capture_session;
  bool available;
};

void otis_monotonic_us_extension_init(OtisMonotonicUsExtension *extension);

bool otis_monotonic_us_extension_seed(
    OtisMonotonicUsExtension *extension, uint64_t extended_us,
    uint32_t capture_session);

bool otis_monotonic_us_extension_advance_boundary(
    OtisMonotonicUsExtension *extension, uint64_t raw_us,
    uint32_t capture_session, uint64_t *extended_us);

bool otis_monotonic_us_extension_project_nearest(
    const OtisMonotonicUsExtension *extension, uint64_t raw_us,
    uint32_t capture_session, uint64_t maximum_distance_us,
    uint64_t *extended_us);

#endif
