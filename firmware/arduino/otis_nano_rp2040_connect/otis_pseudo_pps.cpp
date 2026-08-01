#include "otis_pseudo_pps.h"

#include <string.h>

#include <hardware/clocks.h>
#include <hardware/dma.h>
#include <hardware/gpio.h>
#include <hardware/pio.h>
#include <hardware/pio_instructions.h>
#include <hardware/regs/dma.h>
#include <hardware/regs/pio.h>

#include "otis_board.h"
#include "otis_config.h"
#include "otis_emit.h"
#include "otis_protocol.h"
#include "otis_pseudo_pps.pio.h"
#include "otis_resource_registry.h"

namespace {

constexpr uint32_t kRequiredSystemClockHz = 133000000u;
constexpr uint32_t kPioClockHz = 1000000u;
constexpr uint8_t kCompletionIrqFlag = 7u;
constexpr size_t kPrefillDepth = 8u;  // TX-joined FIFO depth on RP2040.

enum class PendingMarker : uint8_t {
  None = 0,
  Start,
  Completion,
  Abort,
  Underflow,
  ResourceFault,
};

struct GeneratorState {
  PIO pio;
  int sm;
  int program_offset;
  int dma_channel;
  OtisPseudoPpsState state;
  OtisPseudoPpsStep steps[OTIS_PSEUDO_PPS_MAX_STEPS];
  uint32_t dma_words[OTIS_PSEUDO_PPS_MAX_DMA_WORDS];
  uint32_t scheduled_offsets_us[OTIS_PSEUDO_PPS_MAX_STEPS];
  size_t step_count;
  size_t word_count;
  size_t truth_cursor;
  uint32_t truth_seq;
  uint32_t session;
  uint32_t pin_sample_count;
  uint32_t output_high_sample_count;
  uint32_t reference_high_sample_count;
  uint32_t system_clock_hz;
  const char *profile_id;
  PendingMarker pending_marker;
  bool start_marker_emitted;
};

GeneratorState generator = {
    pio0, -1, -1, -1, OtisPseudoPpsState::Disabled, {}, {}, {}, 0u, 0u,
    0u,   0u, 0u, 0u, 0u, 0u, 0u, nullptr, PendingMarker::None, false,
};

void make_output_high_impedance(void) {
  if (generator.sm >= 0) {
    pio_sm_set_enabled(generator.pio, static_cast<uint>(generator.sm), false);
  }
  gpio_init(OTIS_PIN_PSEUDO_PPS_OUTPUT);
  gpio_put(OTIS_PIN_PSEUDO_PPS_OUTPUT, false);
  gpio_set_dir(OTIS_PIN_PSEUDO_PPS_OUTPUT, GPIO_OUT);
  gpio_set_dir(OTIS_PIN_PSEUDO_PPS_OUTPUT, GPIO_IN);
  gpio_disable_pulls(OTIS_PIN_PSEUDO_PPS_OUTPUT);
}

void stop_transport(void) {
  if (generator.dma_channel >= 0 &&
      dma_channel_is_busy(static_cast<uint>(generator.dma_channel))) {
    dma_channel_abort(static_cast<uint>(generator.dma_channel));
  }
  make_output_high_impedance();
}

void set_terminal_state(OtisPseudoPpsState state, PendingMarker marker) {
  stop_transport();
  generator.state = state;
  generator.truth_cursor = generator.step_count;
  generator.pending_marker = marker;
}

const char *marker_event(PendingMarker marker) {
  switch (marker) {
    case PendingMarker::Start:
      return "start";
    case PendingMarker::Completion:
      return "completion";
    case PendingMarker::Abort:
      return "abort";
    case PendingMarker::Underflow:
      return "underflow";
    case PendingMarker::ResourceFault:
      return "resource_fault";
    case PendingMarker::None:
      break;
  }
  return "none";
}

void emit_marker(PendingMarker marker) {
  otis_emit_pseudo_pps_truth(
      generator.truth_seq++, generator.session,
      generator.profile_id == nullptr ? "NONE" : generator.profile_id,
      OTIS_PSEUDO_PPS_PROFILE_VERSION, 0u, marker_event(marker), "marker", 0u,
      0u, 0u,
      marker == PendingMarker::Underflow ||
              marker == PendingMarker::ResourceFault
          ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
          : OTIS_FLAG_NONE);
}

bool prepare_hardware(void) {
  uint sm = static_cast<uint>(generator.sm);
  uint dma_channel = static_cast<uint>(generator.dma_channel);
  pio_sm_set_enabled(generator.pio, sm, false);
  dma_channel_abort(dma_channel);
  pio_sm_clear_fifos(generator.pio, sm);
  pio_sm_restart(generator.pio, sm);
  // pio_sm_restart() clears the SM's internal execution state but deliberately
  // leaves its program counter unchanged. A completed schedule is parked in
  // the terminal halt loop, so every new ARM/START must explicitly return the
  // SM to the program entry before it can consume the next schedule.
  pio_sm_exec(generator.pio, sm,
              pio_encode_jmp(static_cast<uint>(generator.program_offset)));
  pio_sm_clkdiv_restart(generator.pio, sm);
  pio_interrupt_clear(generator.pio, kCompletionIrqFlag);
  generator.pio->fdebug = 1u << (PIO_FDEBUG_TXSTALL_LSB + sm);

  pio_gpio_init(generator.pio, OTIS_PIN_PSEUDO_PPS_OUTPUT);
  pio_sm_set_pins_with_mask(generator.pio, sm, 0u,
                            1u << OTIS_PIN_PSEUDO_PPS_OUTPUT);
  pio_sm_set_consecutive_pindirs(generator.pio, sm,
                                 OTIS_PIN_PSEUDO_PPS_OUTPUT, 1u, true);

  size_t prefill = generator.word_count < kPrefillDepth
                       ? generator.word_count
                       : kPrefillDepth;
  for (size_t index = 0u; index < prefill; ++index) {
    pio_sm_put(generator.pio, sm, generator.dma_words[index]);
  }

  size_t remaining = generator.word_count - prefill;
  if (remaining != 0u) {
    dma_channel_config dma_config = dma_channel_get_default_config(dma_channel);
    channel_config_set_transfer_data_size(&dma_config, DMA_SIZE_32);
    channel_config_set_read_increment(&dma_config, true);
    channel_config_set_write_increment(&dma_config, false);
    channel_config_set_dreq(&dma_config,
                            pio_get_dreq(generator.pio, sm, true));
    channel_config_set_high_priority(&dma_config, true);
    dma_channel_configure(dma_channel, &dma_config, &generator.pio->txf[sm],
                          &generator.dma_words[prefill], remaining, true);
  }

  pio_sm_set_enabled(generator.pio, sm, true);
  return true;
}

}  // namespace

bool otis_pseudo_pps_begin(void) {
#if !OTIS_ENABLE_PSEUDO_PPS_GENERATOR
  generator.state = OtisPseudoPpsState::Disabled;
  make_output_high_impedance();
  return true;
#else
  if (generator.state != OtisPseudoPpsState::Disabled) {
    return false;
  }
  generator.system_clock_hz = clock_get_hz(clk_sys);
  generator.pio = pio0;
  if (generator.system_clock_hz != kRequiredSystemClockHz ||
      !pio_can_add_program(generator.pio, &otis_pseudo_pps_program)) {
    generator.state = OtisPseudoPpsState::ResourceFault;
    generator.pending_marker = PendingMarker::ResourceFault;
    make_output_high_impedance();
    return false;
  }

  generator.sm = pio_claim_unused_sm(generator.pio, false);
  if (generator.sm < 0) {
    generator.state = OtisPseudoPpsState::ResourceFault;
    generator.pending_marker = PendingMarker::ResourceFault;
    return false;
  }
  generator.program_offset = static_cast<int>(
      pio_add_program(generator.pio, &otis_pseudo_pps_program));
  generator.dma_channel = dma_claim_unused_channel(false);
  if (generator.dma_channel < 0) {
    pio_remove_program(generator.pio, &otis_pseudo_pps_program,
                       static_cast<uint>(generator.program_offset));
    pio_sm_unclaim(generator.pio, static_cast<uint>(generator.sm));
    generator.sm = -1;
    generator.program_offset = -1;
    generator.state = OtisPseudoPpsState::ResourceFault;
    generator.pending_marker = PendingMarker::ResourceFault;
    return false;
  }

  bool ownership_bound =
      otis_resource_registry_bind_pio_state_machine(
          OTIS_OWNER_PSEUDO_PPS, 0u, static_cast<uint8_t>(generator.sm)) &&
      otis_resource_registry_bind_pio_program(
          OTIS_OWNER_PSEUDO_PPS, 0u,
          static_cast<uint8_t>(generator.program_offset),
          static_cast<uint8_t>(otis_pseudo_pps_program.length)) &&
      otis_resource_registry_bind_dma_channel(
          OTIS_OWNER_PSEUDO_PPS,
          static_cast<uint8_t>(generator.dma_channel));
  if (!ownership_bound) {
    generator.state = OtisPseudoPpsState::ResourceFault;
    generator.pending_marker = PendingMarker::ResourceFault;
    stop_transport();
    return false;
  }

  pio_sm_config config = otis_pseudo_pps_program_get_default_config(
      static_cast<uint>(generator.program_offset));
  sm_config_set_set_pins(&config, OTIS_PIN_PSEUDO_PPS_OUTPUT, 1u);
  sm_config_set_out_shift(&config, true, false, 32u);
  sm_config_set_fifo_join(&config, PIO_FIFO_JOIN_TX);
  sm_config_set_clkdiv(
      &config, static_cast<float>(generator.system_clock_hz) / kPioClockHz);
  pio_sm_init(generator.pio, static_cast<uint>(generator.sm),
              static_cast<uint>(generator.program_offset), &config);
  make_output_high_impedance();
  generator.state = OtisPseudoPpsState::Idle;
  return true;
#endif
}

bool otis_pseudo_pps_arm(const char *profile_id) {
#if !OTIS_ENABLE_PSEUDO_PPS_GENERATOR
  (void)profile_id;
  return false;
#else
  if (generator.state == OtisPseudoPpsState::Running ||
      generator.state == OtisPseudoPpsState::ResourceFault ||
      generator.state == OtisPseudoPpsState::UnderflowFault) {
    return false;
  }
  const OtisPseudoPpsProfile *profile = nullptr;
  for (size_t index = 0u; index < otis_pseudo_pps_profile_count(); ++index) {
    const OtisPseudoPpsProfile *candidate = otis_pseudo_pps_profile_at(index);
    if (candidate != nullptr && strcmp(candidate->id, profile_id) == 0) {
      profile = candidate;
      break;
    }
  }
  if (profile == nullptr) {
    return false;
  }
  size_t step_count = 0u;
  size_t word_count = 0u;
  if (!otis_pseudo_pps_compile_profile(
          profile->id, generator.steps, OTIS_PSEUDO_PPS_MAX_STEPS,
          &step_count) ||
      !otis_pseudo_pps_encode_schedule(
          generator.steps, step_count, generator.dma_words,
          OTIS_PSEUDO_PPS_MAX_DMA_WORDS, &word_count)) {
    return false;
  }

  uint64_t offset = 0u;
  for (size_t index = 0u; index < step_count; ++index) {
    offset += generator.steps[index].delay_us;
    if (offset > UINT32_MAX) {
      return false;
    }
    generator.scheduled_offsets_us[index] = static_cast<uint32_t>(offset);
  }
  stop_transport();
  generator.profile_id = profile->id;
  generator.step_count = step_count;
  generator.word_count = word_count;
  generator.truth_cursor = 0u;
  generator.pin_sample_count = 0u;
  generator.output_high_sample_count = 0u;
  generator.reference_high_sample_count = 0u;
  generator.pending_marker = PendingMarker::None;
  generator.start_marker_emitted = false;
  generator.state = OtisPseudoPpsState::Armed;
  return true;
#endif
}

bool otis_pseudo_pps_start(void) {
#if !OTIS_ENABLE_PSEUDO_PPS_GENERATOR
  return false;
#else
  if (generator.state != OtisPseudoPpsState::Armed) {
    return false;
  }
  generator.session++;
  generator.truth_cursor = 0u;
  generator.pending_marker = PendingMarker::Start;
  generator.start_marker_emitted = false;
  if (!prepare_hardware()) {
    set_terminal_state(OtisPseudoPpsState::ResourceFault,
                       PendingMarker::ResourceFault);
    return false;
  }
  generator.state = OtisPseudoPpsState::Running;
  return true;
#endif
}

bool otis_pseudo_pps_stop(void) {
#if !OTIS_ENABLE_PSEUDO_PPS_GENERATOR
  return false;
#else
  if (generator.state != OtisPseudoPpsState::Running &&
      generator.state != OtisPseudoPpsState::Armed) {
    return false;
  }
  set_terminal_state(OtisPseudoPpsState::Aborted, PendingMarker::Abort);
  return true;
#endif
}

void otis_pseudo_pps_latch_resource_fault(void) {
#if OTIS_ENABLE_PSEUDO_PPS_GENERATOR
  stop_transport();
  generator.state = OtisPseudoPpsState::ResourceFault;
  generator.pending_marker = PendingMarker::ResourceFault;
#endif
}

void otis_pseudo_pps_service(void) {
#if OTIS_ENABLE_PSEUDO_PPS_GENERATOR
  if (generator.state == OtisPseudoPpsState::Running) {
    // These CPU samples are diagnostic witnesses only. PIO remains the sole
    // waveform owner and the PPS snapshot backend remains authoritative.
    if (generator.pin_sample_count != UINT32_MAX) {
      generator.pin_sample_count++;
    }
    if (gpio_get(OTIS_PIN_PSEUDO_PPS_OUTPUT) &&
        generator.output_high_sample_count != UINT32_MAX) {
      generator.output_high_sample_count++;
    }
    if (gpio_get(OTIS_PIN_PPS_REFERENCE) &&
        generator.reference_high_sample_count != UINT32_MAX) {
      generator.reference_high_sample_count++;
    }
    uint sm = static_cast<uint>(generator.sm);
    if (pio_interrupt_get(generator.pio, kCompletionIrqFlag)) {
      pio_interrupt_clear(generator.pio, kCompletionIrqFlag);
      stop_transport();
      generator.state = OtisPseudoPpsState::Complete;
      generator.pending_marker = PendingMarker::Completion;
    } else {
      uint32_t txstall =
          (generator.pio->fdebug >> (PIO_FDEBUG_TXSTALL_LSB + sm)) & 1u;
      dma_channel_hw_t *channel =
          dma_channel_hw_addr(static_cast<uint>(generator.dma_channel));
      bool dma_error =
          (channel->ctrl_trig & DMA_CH0_CTRL_TRIG_AHB_ERROR_BITS) != 0u;
      if (txstall != 0u || dma_error) {
        set_terminal_state(OtisPseudoPpsState::UnderflowFault,
                           PendingMarker::Underflow);
      }
    }
  }

  if (generator.pending_marker == PendingMarker::Start) {
    emit_marker(generator.pending_marker);
    generator.pending_marker = PendingMarker::None;
    generator.start_marker_emitted = true;
    return;
  }
  if (generator.start_marker_emitted &&
      generator.truth_cursor < generator.step_count &&
      (generator.state == OtisPseudoPpsState::Running ||
       generator.state == OtisPseudoPpsState::Complete)) {
    size_t index = generator.truth_cursor++;
    const OtisPseudoPpsStep &step = generator.steps[index];
    otis_emit_pseudo_pps_truth(
        generator.truth_seq++, generator.session, generator.profile_id,
        OTIS_PSEUDO_PPS_PROFILE_VERSION, static_cast<uint32_t>(index + 1u),
        "schedule", step.intended_class, generator.scheduled_offsets_us[index],
        step.delay_us, step.pulse_width_us, OTIS_FLAG_NONE);
    return;
  }
  if (generator.pending_marker != PendingMarker::None) {
    emit_marker(generator.pending_marker);
    generator.pending_marker = PendingMarker::None;
  }
#endif
}

void otis_pseudo_pps_get_status(OtisPseudoPpsStatus *status) {
  if (status == nullptr) {
    return;
  }
  *status = {
      generator.state,
      generator.profile_id == nullptr ? "NONE" : generator.profile_id,
      OTIS_PSEUDO_PPS_PROFILE_VERSION,
      static_cast<uint16_t>(generator.step_count),
      static_cast<uint16_t>(generator.truth_cursor),
      generator.session,
      generator.pin_sample_count,
      generator.output_high_sample_count,
      generator.reference_high_sample_count,
      generator.system_clock_hz,
      kPioClockHz,
      static_cast<int8_t>(generator.sm),
      static_cast<int8_t>(generator.dma_channel),
  };
}

const char *otis_pseudo_pps_state_name(OtisPseudoPpsState state) {
  switch (state) {
    case OtisPseudoPpsState::Disabled:
      return "disabled";
    case OtisPseudoPpsState::Idle:
      return "idle";
    case OtisPseudoPpsState::Armed:
      return "armed";
    case OtisPseudoPpsState::Running:
      return "running";
    case OtisPseudoPpsState::Complete:
      return "complete";
    case OtisPseudoPpsState::Aborted:
      return "aborted";
    case OtisPseudoPpsState::ResourceFault:
      return "resource_fault";
    case OtisPseudoPpsState::UnderflowFault:
      return "underflow_fault";
  }
  return "unknown";
}
