#include "otis_resource_registry.h"

#include <string.h>

#include "otis_board.h"
#include "otis_config.h"

namespace {

constexpr uint8_t kMaxResourceClaims = 32u;
constexpr uint8_t kRp2040Instance = 0u;
constexpr uint8_t kPio0Instance = 0u;
constexpr uint8_t kI2c0Instance = 0u;
constexpr uint16_t kPioProgramLength = 5u;

enum ClockResource : uint16_t {
  kClockSystem = 0u,
  kClockGpin0 = 1u,
  kClockFrequencyCounter0 = 2u,
  kClockGpout0 = 3u,
  kClockGpout3 = 4u,
};

struct RegistryState {
  OtisResourceClaim claims[kMaxResourceClaims];
  uint8_t claim_count;
  uint8_t conflict_count;
  uint8_t binding_failure_count;
  bool initialized;
  bool valid;
};

RegistryState registry = {};

void note_binding_failure(void) {
  registry.binding_failure_count++;
  registry.valid = false;
}

bool add_claim(const OtisResourceClaim &claim) {
  if (registry.claim_count >= kMaxResourceClaims) {
    note_binding_failure();
    return false;
  }

  bool unique = true;
  for (uint8_t i = 0; i < registry.claim_count; ++i) {
    if (otis_resource_claims_conflict(registry.claims[i], claim)) {
      registry.conflict_count++;
      registry.valid = false;
      unique = false;
    }
  }
  registry.claims[registry.claim_count++] = claim;
  return unique;
}

bool add_bound_claim(OtisResourceType type, uint8_t instance, uint16_t index,
                     const char *owner, const char *role) {
  return add_claim({type, instance, index, 1u, owner, role, true});
}

bool add_dynamic_claim(OtisResourceType type, uint8_t instance, uint16_t span,
                       const char *owner, const char *role) {
  return add_claim({type, instance, kOtisResourceDynamicIndex, span, owner, role,
                    false});
}

void add_pio_owner(const char *owner, const char *role) {
  add_dynamic_claim(OtisResourceType::PioStateMachine, kPio0Instance, 1u, owner,
                    role);
  add_dynamic_claim(OtisResourceType::PioInstructionMemory, kPio0Instance,
                    kPioProgramLength, owner, role);
}

void add_edge_capture_owner(uint16_t gpio, const char *role) {
  add_bound_claim(OtisResourceType::Gpio, kRp2040Instance, gpio,
                  OTIS_OWNER_EDGE_CAPTURE, role);
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_PIO_FIFO
  add_pio_owner(OTIS_OWNER_EDGE_CAPTURE, "sparse_edge_queue");
#else
  add_bound_claim(OtisResourceType::GpioIrq, kRp2040Instance, gpio,
                  OTIS_OWNER_EDGE_CAPTURE, role);
#endif
}

void add_pps_witness_owner(void) {
#if OTIS_ENABLE_PPS_DUAL_OBSERVER
  add_bound_claim(OtisResourceType::Gpio, kRp2040Instance,
                  OTIS_PIN_GENERIC_EVENT, OTIS_OWNER_PPS_WITNESS,
                  "diagnostic_pps_input");
  add_bound_claim(OtisResourceType::GpioIrq, kRp2040Instance,
                  OTIS_PIN_GENERIC_EVENT, OTIS_OWNER_PPS_WITNESS,
                  "diagnostic_pps_rising");
#endif
}

void add_count_observation_owner(void) {
  add_bound_claim(OtisResourceType::Gpio, kRp2040Instance,
                  OTIS_PIN_OSC_OBSERVATION, OTIS_OWNER_COUNT_OBSERVATION,
                  "raw_oscillator_input");

#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_FC0_GPIN0
  add_bound_claim(OtisResourceType::Clock, kRp2040Instance, kClockGpin0,
                  OTIS_OWNER_COUNT_OBSERVATION, "gpio20_gpin0");
  add_bound_claim(OtisResourceType::Clock, kRp2040Instance,
                  kClockFrequencyCounter0, OTIS_OWNER_COUNT_OBSERVATION,
                  "frequency_counter_0");
#elif OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_GPIO_IRQ
  add_bound_claim(OtisResourceType::GpioIrq, kRp2040Instance,
                  OTIS_PIN_OSC_OBSERVATION, OTIS_OWNER_COUNT_OBSERVATION,
                  "divided_oscillator_rising");
#elif OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE || \
    OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
  add_pio_owner(OTIS_OWNER_COUNT_OBSERVATION, "oscillator_edge_counter");
#endif
}

void add_h1_i2c_owner(void) {
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE &&             \
    (OTIS_ENABLE_DAC_AD5693R ||                                           \
     (OTIS_ENABLE_ENV_SENSORS &&                                         \
      (OTIS_ENABLE_ENV_SHT4X || OTIS_ENABLE_ENV_BMP280)))
  add_bound_claim(OtisResourceType::I2cController, kI2c0Instance, 0u,
                  OTIS_OWNER_I2C_BUS, "shared_instrument_bus");
  add_bound_claim(OtisResourceType::Gpio, kRp2040Instance, PIN_WIRE0_SDA,
                  OTIS_OWNER_I2C_BUS, "i2c0_sda");
  add_bound_claim(OtisResourceType::Gpio, kRp2040Instance, PIN_WIRE0_SCL,
                  OTIS_OWNER_I2C_BUS, "i2c0_scl");
#if OTIS_ENABLE_DAC_AD5693R
  add_bound_claim(OtisResourceType::I2cAddress, kI2c0Instance,
                  OTIS_DAC_AD5693R_I2C_ADDRESS, OTIS_OWNER_DAC,
                  "ad5693r_address");
#endif
#if OTIS_ENABLE_ENV_SENSORS && OTIS_ENABLE_ENV_SHT4X
  add_bound_claim(OtisResourceType::I2cAddress, kI2c0Instance,
                  OTIS_ENV_SHT4X_I2C_ADDRESS, OTIS_OWNER_ENV_SHT4X,
                  "sht4x_address");
#endif
#if OTIS_ENABLE_ENV_SENSORS && OTIS_ENABLE_ENV_BMP280
  add_bound_claim(OtisResourceType::I2cAddress, kI2c0Instance,
                  OTIS_ENV_BMP280_I2C_ADDRESS, OTIS_OWNER_ENV_BMP280,
                  "bmp280_address");
#endif
#endif
}

bool bind_dynamic_claim(OtisResourceType type, const char *owner,
                        uint8_t instance, uint16_t index, uint16_t span) {
  if (!registry.initialized || owner == nullptr || span == 0u) {
    note_binding_failure();
    return false;
  }

  uint8_t target = kMaxResourceClaims;
  for (uint8_t i = 0; i < registry.claim_count; ++i) {
    OtisResourceClaim &claim = registry.claims[i];
    if (claim.type == type && claim.instance == instance && !claim.bound &&
        strcmp(claim.owner, owner) == 0) {
      target = i;
      break;
    }
  }

  if (target == kMaxResourceClaims ||
      registry.claims[target].span != span) {
    note_binding_failure();
    return false;
  }

  OtisResourceClaim candidate = registry.claims[target];
  candidate.index = index;
  candidate.bound = true;
  for (uint8_t i = 0; i < registry.claim_count; ++i) {
    if (i != target &&
        otis_resource_claims_conflict(registry.claims[i], candidate)) {
      registry.conflict_count++;
      registry.valid = false;
      return false;
    }
  }

  registry.claims[target] = candidate;
  return true;
}

}  // namespace

bool otis_resource_registry_begin(void) {
  if (registry.initialized) {
    return registry.valid;
  }

  registry.claim_count = 0u;
  registry.conflict_count = 0u;
  registry.binding_failure_count = 0u;
  registry.valid = true;
  registry.initialized = true;

  add_bound_claim(OtisResourceType::Timer, kRp2040Instance, 0u,
                  OTIS_OWNER_ARDUINO_TIMEBASE,
                  "micros_millis_reconstructed_capture");
  add_bound_claim(OtisResourceType::Clock, kRp2040Instance, kClockSystem,
                  OTIS_OWNER_ARDUINO_CLOCK_TREE,
                  "cpu_usb_pio_dma_clock_tree");

  add_bound_claim(OtisResourceType::Gpio, kRp2040Instance,
                  OTIS_PIN_INTERNAL_CLOCK_VISIBILITY,
                  OTIS_OWNER_CLOCK_VISIBILITY, "reserved_gpout0_pin");
  add_bound_claim(OtisResourceType::Clock, kRp2040Instance, kClockGpout0,
                  OTIS_OWNER_CLOCK_VISIBILITY, "reserved_internal_visibility");
  add_bound_claim(OtisResourceType::Gpio, kRp2040Instance,
                  OTIS_PIN_SECONDARY_DIAGNOSTIC_CLOCK,
                  OTIS_OWNER_DIAGNOSTIC_CLOCK, "reserved_gpout3_pin");
  add_bound_claim(OtisResourceType::Clock, kRp2040Instance, kClockGpout3,
                  OTIS_OWNER_DIAGNOSTIC_CLOCK,
                  "reserved_secondary_diagnostic");

#if OTIS_ENABLE_STATUS_LED && defined(LED_BUILTIN)
  add_bound_claim(OtisResourceType::Gpio, kRp2040Instance, LED_BUILTIN,
                  OTIS_OWNER_STATUS_LED, "status_output");
#endif

#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPIO_LOOPBACK
  add_bound_claim(OtisResourceType::Gpio, kRp2040Instance,
                  OTIS_PIN_GPIO_LOOPBACK_OUTPUT, OTIS_OWNER_LOOPBACK_OUTPUT,
                  "loopback_output");
  add_edge_capture_owner(OTIS_PIN_GENERIC_EVENT, "generic_event_input");
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPS_PPS
  add_edge_capture_owner(OTIS_PIN_PPS_REFERENCE, "pps_reference_input");
  add_pps_witness_owner();
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
  add_edge_capture_owner(OTIS_PIN_PPS_REFERENCE,
                         "pps_reference_and_count_boundary_irq");
#else
  add_edge_capture_owner(OTIS_PIN_PPS_REFERENCE, "pps_reference_input");
#endif
  add_pps_witness_owner();
  add_count_observation_owner();
#endif

  add_h1_i2c_owner();
  return registry.valid;
}

bool otis_resource_registry_valid(void) {
  return registry.initialized && registry.valid;
}

bool otis_resource_registry_complete(void) {
  if (!otis_resource_registry_valid()) {
    return false;
  }
  for (uint8_t i = 0; i < registry.claim_count; ++i) {
    if (!registry.claims[i].bound) {
      return false;
    }
  }
  return true;
}

uint8_t otis_resource_registry_claim_count(void) {
  return registry.claim_count;
}

uint8_t otis_resource_registry_claim_count(OtisResourceType type) {
  uint8_t count = 0u;
  for (uint8_t i = 0; i < registry.claim_count; ++i) {
    if (registry.claims[i].type == type) {
      count++;
    }
  }
  return count;
}

uint8_t otis_resource_registry_conflict_count(void) {
  return registry.conflict_count;
}

uint8_t otis_resource_registry_binding_failure_count(void) {
  return registry.binding_failure_count;
}

const OtisResourceClaim *otis_resource_registry_claim_at(uint8_t index) {
  if (index >= registry.claim_count) {
    return nullptr;
  }
  return &registry.claims[index];
}

const char *otis_resource_type_name(OtisResourceType type) {
  switch (type) {
    case OtisResourceType::Gpio:
      return "gpio";
    case OtisResourceType::GpioIrq:
      return "gpio_irq";
    case OtisResourceType::PioStateMachine:
      return "pio_sm";
    case OtisResourceType::PioInstructionMemory:
      return "pio_imem";
    case OtisResourceType::DmaChannel:
      return "dma";
    case OtisResourceType::Timer:
      return "timer";
    case OtisResourceType::Clock:
      return "clock";
    case OtisResourceType::I2cController:
      return "i2c_controller";
    case OtisResourceType::I2cAddress:
      return "i2c_address";
  }
  return "unknown";
}

bool otis_resource_registry_bind_pio_state_machine(const char *owner,
                                                   uint8_t pio_block,
                                                   uint8_t state_machine) {
  return bind_dynamic_claim(OtisResourceType::PioStateMachine, owner, pio_block,
                            state_machine, 1u);
}

bool otis_resource_registry_bind_pio_program(const char *owner,
                                             uint8_t pio_block,
                                             uint8_t offset,
                                             uint8_t length) {
  return bind_dynamic_claim(OtisResourceType::PioInstructionMemory, owner,
                            pio_block, offset, length);
}
