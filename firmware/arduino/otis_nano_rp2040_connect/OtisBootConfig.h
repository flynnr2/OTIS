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
  ResetEntry,
  EarlyInit,
  ClocksInit,
  GpioInit,
  CaptureInit,
  TimerInit,
  PpsInputInit,
  RingBuffersInit,
  SerialInit,
  ProtocolBanner,
  RunMode,
  Fatal,
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
};

#endif
