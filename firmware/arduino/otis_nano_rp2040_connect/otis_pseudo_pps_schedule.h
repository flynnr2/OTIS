#ifndef OTIS_PSEUDO_PPS_SCHEDULE_H
#define OTIS_PSEUDO_PPS_SCHEDULE_H

#include <stddef.h>
#include <stdint.h>

constexpr uint16_t OTIS_PSEUDO_PPS_PROFILE_VERSION = 1u;
constexpr size_t OTIS_PSEUDO_PPS_MAX_STEPS = 96u;
constexpr uint32_t OTIS_PSEUDO_PPS_NOMINAL_INTERVAL_US = 1000000u;
constexpr uint32_t OTIS_PSEUDO_PPS_NOMINAL_WIDTH_US = 100000u;
constexpr size_t OTIS_PSEUDO_PPS_MAX_DMA_WORDS =
    OTIS_PSEUDO_PPS_MAX_STEPS * 2u + 1u;

struct OtisPseudoPpsStep {
  uint32_t delay_us;
  uint32_t pulse_width_us;
  const char *intended_class;
  bool emits_pulse;
};

struct OtisPseudoPpsProfile {
  const char *id;
  uint16_t version;
};

size_t otis_pseudo_pps_profile_count(void);
const OtisPseudoPpsProfile *otis_pseudo_pps_profile_at(size_t index);
bool otis_pseudo_pps_compile_profile(const char *profile_id,
                                     OtisPseudoPpsStep *steps,
                                     size_t capacity,
                                     size_t *step_count);
bool otis_pseudo_pps_encode_schedule(const OtisPseudoPpsStep *steps,
                                     size_t step_count,
                                     uint32_t *words,
                                     size_t word_capacity,
                                     size_t *word_count);

#endif
