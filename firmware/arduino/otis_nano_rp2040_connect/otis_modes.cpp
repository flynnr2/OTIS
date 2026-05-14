#include "otis_modes.h"

#include "otis_config.h"

const char *otis_bringup_mode_name(void) {
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_SYNTHETIC_USB
  return "SW1_SYNTHETIC_USB";
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPIO_LOOPBACK
  return "SW1_GPIO_LOOPBACK";
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPS_PPS
  return "SW1_GPS_PPS";
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE
  return "SW1_TCXO_OBSERVE";
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  return "H1_OCXO_OBSERVE_OPEN_LOOP";
#endif
}

const char *otis_tcxo_counter_backend_name(void) {
#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_FC0_GPIN0
  return "rp2040_fc0_gpin0";
#elif OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_GPIO_IRQ
  return "gpio_irq_divided_only";
#endif
}

const char *otis_capture_backend_name(void) {
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_IRQ
  return "irq";
#elif OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_PIO_FIFO
  return "pio_fifo";
#endif
}
