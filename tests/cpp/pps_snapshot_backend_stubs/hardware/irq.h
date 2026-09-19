#pragma once
#include <stdint.h>
using uint = unsigned int;
using irq_handler_t = void (*)();
#define PICO_SHARED_IRQ_HANDLER_DEFAULT_ORDER_PRIORITY 0x80u
extern irq_handler_t mock_shared_irq_handler;
extern irq_handler_t mock_exclusive_irq_handler;
extern uint mock_shared_irq_number;
extern bool mock_irq_enabled;
inline irq_handler_t irq_get_exclusive_handler(uint) {
  return mock_exclusive_irq_handler;
}
inline void irq_add_shared_handler(uint number, irq_handler_t handler, uint8_t) {
  mock_shared_irq_number = number;
  mock_shared_irq_handler = handler;
}
inline void irq_set_enabled(uint, bool enabled) { mock_irq_enabled = enabled; }
