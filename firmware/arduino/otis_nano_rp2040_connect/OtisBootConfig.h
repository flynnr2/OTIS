#ifndef OTIS_BOOT_CONFIG_H
#define OTIS_BOOT_CONFIG_H

#include <stdint.h>

constexpr uint32_t kOtisBootInitialDelayMs = 1500u;
constexpr uint32_t kOtisSerialBaud = 115200u;

#ifndef OTIS_SERIAL_WAIT_MS
#define OTIS_SERIAL_WAIT_MS 250u
#endif

constexpr uint32_t kOtisSerialWaitMs = OTIS_SERIAL_WAIT_MS;

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
};

#endif
