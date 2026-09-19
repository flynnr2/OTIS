#pragma once
#include <stdint.h>
extern bool mock_interrupts_disabled;
inline void __dmb() {}
inline uint32_t save_and_disable_interrupts() {
  const uint32_t prior = mock_interrupts_disabled ? 1u : 0u;
  mock_interrupts_disabled = true;
  return prior;
}
inline void restore_interrupts(uint32_t prior) {
  mock_interrupts_disabled = prior != 0u;
}
