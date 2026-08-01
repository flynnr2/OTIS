#include <assert.h>
#include <stdint.h>
#include <string.h>

#include "otis_pseudo_pps_schedule.h"

int main() {
  assert(otis_pseudo_pps_profile_count() == 16u);
  for (size_t profile_index = 0u;
       profile_index < otis_pseudo_pps_profile_count(); ++profile_index) {
    const OtisPseudoPpsProfile *profile =
        otis_pseudo_pps_profile_at(profile_index);
    assert(profile != nullptr);
    assert(profile->version == 1u);

    OtisPseudoPpsStep steps[OTIS_PSEUDO_PPS_MAX_STEPS] = {};
    uint32_t words[OTIS_PSEUDO_PPS_MAX_DMA_WORDS] = {};
    size_t step_count = 0u;
    size_t word_count = 0u;
    assert(otis_pseudo_pps_compile_profile(
        profile->id, steps, OTIS_PSEUDO_PPS_MAX_STEPS, &step_count));
    assert(step_count > 0u && step_count <= OTIS_PSEUDO_PPS_MAX_STEPS);
    assert(otis_pseudo_pps_encode_schedule(
        steps, step_count, words, OTIS_PSEUDO_PPS_MAX_DMA_WORDS,
        &word_count));
    assert(word_count >= 3u && word_count <= OTIS_PSEUDO_PPS_MAX_DMA_WORDS);
    assert(words[word_count - 1u] == 0u);

    uint64_t intended_offset = 0u;
    uint64_t reconstructed_rise = 0u;
    uint32_t previous_width = 0u;
    size_t word_index = 0u;
    bool first = true;
    for (size_t step_index = 0u; step_index < step_count; ++step_index) {
      const OtisPseudoPpsStep &step = steps[step_index];
      intended_offset += step.delay_us;
      assert(step.delay_us > 0u);
      assert(step.intended_class != nullptr);
      if (!step.emits_pulse) {
        assert(step.pulse_width_us == 0u);
        continue;
      }
      uint32_t encoded_width = words[word_index++] + 3u;
      uint32_t low_count = words[word_index++];
      if (first) {
        reconstructed_rise = static_cast<uint64_t>(low_count) + 8u;
      } else {
        reconstructed_rise +=
            static_cast<uint64_t>(previous_width) + low_count + 7u;
      }
      assert(reconstructed_rise == intended_offset);
      assert(encoded_width == step.pulse_width_us);
      previous_width = encoded_width;
      first = false;
    }
    assert(word_index + 1u == word_count);
  }

  OtisPseudoPpsStep tiny[1] = {};
  size_t count = 99u;
  assert(!otis_pseudo_pps_compile_profile("CLEAN_NOMINAL", tiny, 1u,
                                          &count));
  assert(!otis_pseudo_pps_compile_profile("NOT_A_PROFILE", tiny, 1u,
                                          &count));

  OtisPseudoPpsStep soak[OTIS_PSEUDO_PPS_MAX_STEPS] = {};
  assert(otis_pseudo_pps_compile_profile(
      "CLEAN_SOAK_10M", soak, OTIS_PSEUDO_PPS_MAX_STEPS, &count));
  assert(count == 600u);
  for (size_t index = 0u; index < count; ++index) {
    assert(strcmp(soak[index].intended_class, "clean") == 0);
    assert(soak[index].emits_pulse);
  }

  OtisPseudoPpsStep clean[OTIS_PSEUDO_PPS_MAX_STEPS] = {};
  assert(otis_pseudo_pps_compile_profile(
      "CLEAN_NOMINAL", clean, OTIS_PSEUDO_PPS_MAX_STEPS, &count));
  uint32_t too_small[2] = {};
  size_t word_count = 0u;
  assert(!otis_pseudo_pps_encode_schedule(clean, count, too_small, 2u,
                                          &word_count));

  OtisPseudoPpsStep composite[OTIS_PSEUDO_PPS_MAX_STEPS] = {};
  assert(otis_pseudo_pps_compile_profile(
      "COMPOSITE", composite, OTIS_PSEUDO_PPS_MAX_STEPS, &count));
  assert(count == 79u);
  for (size_t index = 0u; index < 30u; ++index) {
    assert(strcmp(composite[index].intended_class, "clean") == 0);
  }
  assert(strcmp(composite[30].intended_class, "short_interval") == 0);
  assert(strcmp(composite[41].intended_class, "omission") == 0);
  assert(!composite[41].emits_pulse);
  assert(strcmp(composite[42].intended_class, "recovery") == 0);
  assert(strcmp(composite[43].intended_class, "double_primary") == 0);
  assert(strcmp(composite[44].intended_class, "double_secondary") == 0);
  assert(strcmp(composite[45].intended_class, "bounce_primary") == 0);
  return 0;
}
