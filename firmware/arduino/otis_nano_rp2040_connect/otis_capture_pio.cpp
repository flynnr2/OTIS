#include "otis_capture_pio.h"

#include <Arduino.h>

#include "otis_config.h"

#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_PIO_FIFO
#include <hardware/pio.h>
#include <hardware/pio_instructions.h>

#include "otis_capture_ring.h"
#include "otis_protocol.h"

namespace {

const uint16_t pio_edge_capture_instructions[] = {
    static_cast<uint16_t>(pio_encode_wait_pin(false, 0)),
    static_cast<uint16_t>(pio_encode_wait_pin(true, 0)),
    static_cast<uint16_t>(pio_encode_set(pio_x, 1)),
    static_cast<uint16_t>(pio_encode_in(pio_x, 32)),
    static_cast<uint16_t>(pio_encode_push(false, false)),
};

const pio_program_t pio_edge_capture_program = {
    .instructions = pio_edge_capture_instructions,
    .length = 5,
    .origin = -1,
};

PIO pio_capture = pio0;
constexpr uint pio_capture_sm = 0;
int pio_capture_program_offset = -1;
uint32_t pio_capture_gpio = 0;
uint32_t pio_capture_channel_id = 0;
bool pio_capture_reference_record = false;
bool pio_capture_initialized = false;
OtisCaptureEmitFn pio_emit_record = nullptr;
uint32_t pio_fifo_drained_event_count = 0;
uint32_t pio_fifo_empty_count = 0;
uint32_t pio_fifo_overflow_drop_count = 0;
uint32_t pio_fifo_max_drain_batch = 0;

uint64_t capture_ticks_now(void) {
  return (uint64_t)micros() * 16ull;
}

void clear_pio_rxstall(void) {
  pio_capture->fdebug = 1u << pio_capture_sm;
}

void poll_pio_overflow(void) {
  uint32_t rxstall = (pio_capture->fdebug >> pio_capture_sm) & 1u;
  if (!rxstall) {
    return;
  }
  pio_fifo_overflow_drop_count++;
  otis_capture_ring_note_drop();
  clear_pio_rxstall();
}

}  // namespace

bool otis_capture_pio_begin(const OtisCaptureBackendConfig &config) {
  pio_capture_gpio = config.gpio;
  pio_capture_channel_id = config.channel_id;
  pio_capture_reference_record = config.reference_record;
  pio_emit_record = config.emit_record;

  pinMode(config.gpio, INPUT_PULLDOWN);
  if (!pio_can_add_program(pio_capture, &pio_edge_capture_program)) {
    return false;
  }

  pio_capture_program_offset =
      pio_add_program(pio_capture, &pio_edge_capture_program);
  pio_sm_config sm_config = pio_get_default_sm_config();
  sm_config_set_in_pins(&sm_config, config.gpio);
  sm_config_set_wrap(&sm_config, pio_capture_program_offset,
                     pio_capture_program_offset +
                         pio_edge_capture_program.length - 1u);
  sm_config_set_in_shift(&sm_config, true, false, 32);
  sm_config_set_fifo_join(&sm_config, PIO_FIFO_JOIN_RX);

  pio_gpio_init(pio_capture, config.gpio);
  gpio_pull_down(config.gpio);
  pio_sm_set_consecutive_pindirs(pio_capture, pio_capture_sm, config.gpio, 1,
                                 false);
  pio_sm_clear_fifos(pio_capture, pio_capture_sm);
  clear_pio_rxstall();
  pio_sm_init(pio_capture, pio_capture_sm,
              static_cast<uint>(pio_capture_program_offset), &sm_config);
  pio_sm_set_enabled(pio_capture, pio_capture_sm, true);
  pio_capture_initialized = true;
  return true;
}

void otis_capture_pio_service(void) {
  if (!pio_capture_initialized) {
    return;
  }

  poll_pio_overflow();

  uint32_t batch = 0;
  while (!pio_sm_is_rx_fifo_empty(pio_capture, pio_capture_sm)) {
    (void)pio_sm_get(pio_capture, pio_capture_sm);
    OtisCapturedEdge record = {
        pio_capture_channel_id,
        pio_capture_reference_record,
        'R',
        capture_ticks_now(),
        OTIS_FLAG_TIMESTAMP_RECONSTRUCTED,
    };
    if (pio_emit_record != nullptr) {
      pio_emit_record(record);
    }
    pio_fifo_drained_event_count++;
    batch++;
  }

  if (batch == 0) {
    pio_fifo_empty_count++;
  } else if (batch > pio_fifo_max_drain_batch) {
    pio_fifo_max_drain_batch = batch;
  }

  poll_pio_overflow();
}

void otis_capture_pio_get_stats(OtisCapturePioStats *out) {
  if (out == nullptr) {
    return;
  }

  out->drained_event_count = pio_fifo_drained_event_count;
  out->empty_count = pio_fifo_empty_count;
  out->overflow_drop_count = pio_fifo_overflow_drop_count;
  out->max_drain_batch = pio_fifo_max_drain_batch;
}

#else

bool otis_capture_pio_begin(const OtisCaptureBackendConfig &config) {
  (void)config;
  return false;
}

void otis_capture_pio_service(void) {
}

void otis_capture_pio_get_stats(OtisCapturePioStats *out) {
  if (out == nullptr) {
    return;
  }

  out->drained_event_count = 0;
  out->empty_count = 0;
  out->overflow_drop_count = 0;
  out->max_drain_batch = 0;
}

#endif
