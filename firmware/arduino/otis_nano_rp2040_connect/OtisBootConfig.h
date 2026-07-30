#ifndef OTIS_BOOT_CONFIG_H
#define OTIS_BOOT_CONFIG_H

#include <stdint.h>

#include "otis_config.h"

constexpr uint32_t kOtisBootInitialDelayMs = OTIS_BOOT_INITIAL_DELAY_MS;
constexpr uint32_t kOtisSerialBaud = OTIS_SERIAL_BAUD;
constexpr uint32_t kOtisSerialWaitMs = OTIS_SERIAL_WAIT_MS;
constexpr uint8_t kOtisSafeModeFailureThreshold =
    OTIS_SAFE_MODE_FAILURE_THRESHOLD;

enum class BootPhase : uint8_t {
  ResetEntry = 0,
  EarlyInit = 1,
  ClocksInit = 2,
  GpioInit = 3,
  CaptureInit = 4,
  TimerInit = 5,
  PpsInputInit = 6,
  RingBuffersInit = 7,
  SerialInit = 8,
  ProtocolBanner = 9,
  RunMode = 10,
  Fatal = 11,
  PeripheralsInit = 12,
  PreviewInit = 13,
  CapabilityAudit = 14,
};

enum class BootFatal : uint8_t {
  None,
  UnsupportedBoard,
  InvalidBootConfig,
  SerialUnavailable,
  CaptureInitFailed,
  TimerInitFailed,
  PpsInputInitFailed,
  ForcedBeforeClocks,
  ForcedBeforeCapture,
  ForcedBeforeRunMode,
  RepeatedBootFailure,
  ResourceOwnershipConflict,
  RequiredCapabilityUnavailable,
};

#endif
