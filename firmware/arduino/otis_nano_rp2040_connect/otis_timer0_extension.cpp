#include "otis_timer0_extension.h"

#include "otis_timebase_math.h"

namespace {

constexpr uint64_t kTimer0ModulusTicks = (1ull << 32) * 16ull;

}  // namespace

void otis_timer0_extension_init(OtisTimer0Extension *extension) {
  if (extension == nullptr) return;
  *extension = {};
}

bool otis_timer0_extension_seed(
    OtisTimer0Extension *extension, uint64_t extended_ticks,
    uint32_t capture_session) {
  if (extension == nullptr || capture_session == 0u) return false;
  extension->raw_ticks = extended_ticks % kTimer0ModulusTicks;
  extension->extended_ticks = extended_ticks;
  extension->capture_session = capture_session;
  extension->available = true;
  return true;
}

bool otis_timer0_extension_advance_boundary(
    OtisTimer0Extension *extension, uint64_t raw_ticks,
    uint32_t capture_session, uint64_t *extended_ticks) {
  if (extension == nullptr || extended_ticks == nullptr ||
      capture_session == 0u)
    return false;
  const uint64_t normalized_raw_ticks = raw_ticks % kTimer0ModulusTicks;
  if (!extension->available ||
      extension->capture_session != capture_session) {
    if (!otis_timer0_extension_seed(
            extension, normalized_raw_ticks, capture_session))
      return false;
    *extended_ticks = normalized_raw_ticks;
    return true;
  }
  const uint64_t delta = otis_timer0_interval_ticks(
      extension->raw_ticks, normalized_raw_ticks);
  extension->raw_ticks = normalized_raw_ticks;
  extension->extended_ticks += delta;
  *extended_ticks = extension->extended_ticks;
  return true;
}

bool otis_timer0_extension_project_nearest(
    const OtisTimer0Extension *extension, uint64_t raw_ticks,
    uint32_t capture_session, uint64_t maximum_distance_ticks,
    uint64_t *extended_ticks) {
  if (extension == nullptr || extended_ticks == nullptr ||
      !extension->available || capture_session == 0u ||
      extension->capture_session != capture_session)
    return false;
  return otis_timer0_project_nearest_ticks(
      extension->raw_ticks, extension->extended_ticks,
      raw_ticks % kTimer0ModulusTicks, maximum_distance_ticks,
      extended_ticks);
}
