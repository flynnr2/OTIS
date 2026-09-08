#include "otis_monotonic_us_extension.h"

#include "otis_timebase_math.h"

void otis_monotonic_us_extension_init(OtisMonotonicUsExtension *extension) {
  if (extension == nullptr) return;
  *extension = {};
}

bool otis_monotonic_us_extension_seed(
    OtisMonotonicUsExtension *extension, uint64_t extended_us,
    uint32_t capture_session) {
  if (extension == nullptr || capture_session == 0u) return false;
  extension->raw_us = extended_us % OTIS_RP2040_MONOTONIC_US32_MODULUS;
  extension->extended_us = extended_us;
  extension->capture_session = capture_session;
  extension->available = true;
  return true;
}

bool otis_monotonic_us_extension_advance_boundary(
    OtisMonotonicUsExtension *extension, uint64_t raw_us,
    uint32_t capture_session, uint64_t *extended_us) {
  if (extension == nullptr || extended_us == nullptr ||
      capture_session == 0u)
    return false;
  const uint64_t normalized_raw_us =
      raw_us % OTIS_RP2040_MONOTONIC_US32_MODULUS;
  if (!extension->available ||
      extension->capture_session != capture_session) {
    if (!otis_monotonic_us_extension_seed(
            extension, normalized_raw_us, capture_session))
      return false;
    *extended_us = normalized_raw_us;
    return true;
  }
  const uint64_t delta = otis_monotonic_us32_interval(
      extension->raw_us, normalized_raw_us);
  extension->raw_us = normalized_raw_us;
  extension->extended_us += delta;
  *extended_us = extension->extended_us;
  return true;
}

bool otis_monotonic_us_extension_project_nearest(
    const OtisMonotonicUsExtension *extension, uint64_t raw_us,
    uint32_t capture_session, uint64_t maximum_distance_us,
    uint64_t *extended_us) {
  if (extension == nullptr || extended_us == nullptr ||
      !extension->available || capture_session == 0u ||
      extension->capture_session != capture_session)
    return false;
  return otis_monotonic_us32_project_nearest(
      extension->raw_us, extension->extended_us,
      raw_us % OTIS_RP2040_MONOTONIC_US32_MODULUS, maximum_distance_us,
      extended_us);
}
