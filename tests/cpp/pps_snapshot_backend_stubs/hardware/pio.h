#pragma once
#include <stdint.h>
#include <deque>
using uint = unsigned int;
enum pio_interrupt_source_t {
  pis_sm0_rx_fifo_not_empty = 4,
};
struct pio_hw_t {
  uint32_t fdebug;
  uint32_t rxf[4];
  uint32_t ints1;
};
using PIO = pio_hw_t *;
extern pio_hw_t mock_pio;
#define pio0 (&mock_pio)
struct pio_program {
  const uint16_t *instructions;
  uint8_t length;
  int8_t origin;
  uint8_t pio_version;
};
struct pio_sm_config {};
constexpr int pio_x = 1;
constexpr int pio_null = 2;
constexpr int PIO_FIFO_JOIN_RX = 0;
extern std::deque<uint32_t> mock_pio_fifo;
extern bool mock_pio_sm_enabled;
extern bool mock_pio_irq1_source_enabled;
extern uint32_t mock_pio_source_enable_count;
extern uint32_t mock_pio_source_disable_count;
inline bool pio_can_add_program(PIO, const pio_program *) { return true; }
inline int pio_claim_unused_sm(PIO, bool) { return 0; }
inline uint pio_add_program(PIO, const pio_program *) { return 0; }
inline void pio_remove_program(PIO, const pio_program *, uint) {}
inline void pio_sm_unclaim(PIO, uint) {}
inline void pio_gpio_init(PIO, uint) {}
inline void pio_set_input_sync_bypass_with_mask(PIO, uint32_t, uint32_t) {}
inline pio_sm_config pio_get_default_sm_config() { return {}; }
inline void sm_config_set_wrap(pio_sm_config *, uint, uint) {}
inline void sm_config_set_in_pins(pio_sm_config *, uint) {}
inline void sm_config_set_jmp_pin(pio_sm_config *, uint) {}
inline void sm_config_set_in_shift(pio_sm_config *, bool, bool, uint) {}
inline void sm_config_set_fifo_join(pio_sm_config *, int) {}
inline void sm_config_set_clkdiv(pio_sm_config *, float) {}
inline void pio_sm_init(PIO, uint, uint, const pio_sm_config *) {}
inline void pio_sm_set_enabled(PIO, uint, bool enabled) {
  mock_pio_sm_enabled = enabled;
}
inline void pio_sm_clear_fifos(PIO, uint) { mock_pio_fifo.clear(); }
inline void pio_sm_restart(PIO, uint) {}
inline void pio_sm_clkdiv_restart(PIO, uint) {}
inline void pio_sm_exec(PIO, uint, uint16_t) {}
inline uint16_t pio_encode_mov(int, int) { return 0; }
inline uint16_t pio_encode_jmp(uint) { return 0; }
inline bool pio_sm_is_rx_fifo_empty(PIO, uint) {
  return mock_pio_fifo.empty();
}
inline uint32_t pio_sm_get(PIO pio, uint) {
  const uint32_t word = mock_pio_fifo.front();
  mock_pio_fifo.pop_front();
  if (mock_pio_fifo.empty()) pio->ints1 = 0u;
  return word;
}
inline pio_interrupt_source_t
pio_get_rx_fifo_not_empty_interrupt_source(uint sm) {
  return static_cast<pio_interrupt_source_t>(
      static_cast<int>(pis_sm0_rx_fifo_not_empty) + static_cast<int>(sm));
}
inline void pio_set_irq1_source_enabled(
    PIO, pio_interrupt_source_t, bool enabled) {
  mock_pio_irq1_source_enabled = enabled;
  mock_pio.ints1 = enabled && !mock_pio_fifo.empty()
                       ? (1u << static_cast<uint32_t>(pis_sm0_rx_fifo_not_empty))
                       : 0u;
  if (enabled) {
    ++mock_pio_source_enable_count;
  } else {
    ++mock_pio_source_disable_count;
  }
}
inline int pio_get_irq_num(PIO, uint irqn) {
  return 7 + static_cast<int>(irqn);
}
