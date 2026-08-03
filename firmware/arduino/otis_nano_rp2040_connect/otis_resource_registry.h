#ifndef OTIS_RESOURCE_REGISTRY_H
#define OTIS_RESOURCE_REGISTRY_H

#include <stdint.h>

#define OTIS_OWNER_ARDUINO_CLOCK_TREE "arduino_clock_tree"
#define OTIS_OWNER_ARDUINO_TIMEBASE "arduino_timebase"
#define OTIS_OWNER_CLOCK_VISIBILITY "clock_visibility"
#define OTIS_OWNER_DIAGNOSTIC_CLOCK "diagnostic_clock"
#define OTIS_OWNER_STATUS_LED "status_led"
#define OTIS_OWNER_EDGE_CAPTURE "edge_capture"
#define OTIS_OWNER_PPS_WITNESS "pps_witness"
#define OTIS_OWNER_LOOPBACK_OUTPUT "loopback_output"
#define OTIS_OWNER_COUNT_OBSERVATION "count_observation"
#define OTIS_OWNER_PSEUDO_PPS "pseudo_pps_generator"
#define OTIS_OWNER_I2C_BUS "i2c_bus"
#define OTIS_OWNER_DAC "dac_ad5693r"
#define OTIS_OWNER_ENV_SHT4X "environment_sht4x"
#define OTIS_OWNER_ENV_BMP280 "environment_bmp280"
#define OTIS_OWNER_GNSS_RECEIVER "gnss_receiver"

enum class OtisResourceType : uint8_t {
  Gpio,
  GpioIrq,
  PioStateMachine,
  PioInstructionMemory,
  PioIrqFlag,
  DmaChannel,
  Timer,
  Clock,
  I2cController,
  I2cAddress,
  UartController,
};

constexpr uint16_t kOtisResourceDynamicIndex = UINT16_MAX;

struct OtisResourceClaim {
  OtisResourceType type;
  uint8_t instance;
  uint16_t index;
  uint16_t span;
  const char *owner;
  const char *role;
  bool bound;
};

// This comparison is deliberately independent of Arduino/Pico SDK headers so
// the exact collision semantics can be covered by host regression tests.
static inline bool otis_resource_claims_conflict(
    const OtisResourceClaim &first, const OtisResourceClaim &second) {
  if (!first.bound || !second.bound || first.type != second.type ||
      first.instance != second.instance) {
    return false;
  }

  if (first.type != OtisResourceType::PioInstructionMemory) {
    return first.index == second.index;
  }

  uint32_t first_end = static_cast<uint32_t>(first.index) + first.span;
  uint32_t second_end = static_cast<uint32_t>(second.index) + second.span;
  return static_cast<uint32_t>(first.index) < second_end &&
         static_cast<uint32_t>(second.index) < first_end;
}

bool otis_resource_registry_begin(void);
bool otis_resource_registry_valid(void);
bool otis_resource_registry_complete(void);
uint8_t otis_resource_registry_claim_count(void);
uint8_t otis_resource_registry_claim_count(OtisResourceType type);
uint8_t otis_resource_registry_conflict_count(void);
uint8_t otis_resource_registry_binding_failure_count(void);
const OtisResourceClaim *otis_resource_registry_claim_at(uint8_t index);
const char *otis_resource_type_name(OtisResourceType type);

bool otis_resource_registry_bind_pio_state_machine(const char *owner,
                                                   uint8_t pio_block,
                                                   uint8_t state_machine);
bool otis_resource_registry_bind_pio_program(const char *owner,
                                             uint8_t pio_block,
                                             uint8_t offset,
                                             uint8_t length);
bool otis_resource_registry_bind_dma_channel(const char *owner,
                                             uint8_t channel);

#endif
