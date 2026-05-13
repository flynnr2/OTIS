#ifndef OTIS_BOOT_CONFIG_H
#define OTIS_BOOT_CONFIG_H

#include <stdint.h>

constexpr uint32_t kOtisBootInitialDelayMs = 1500u;
constexpr uint32_t kOtisSerialBaud = 115200u;

#ifndef OTIS_SERIAL_WAIT_MS
#define OTIS_SERIAL_WAIT_MS 250u
#endif

#ifndef OTIS_SAFE_MODE_FAILURE_THRESHOLD
#define OTIS_SAFE_MODE_FAILURE_THRESHOLD 3u
#endif

#ifndef OTIS_FORCE_BOOT_FAIL_BEFORE_CLOCKS
#define OTIS_FORCE_BOOT_FAIL_BEFORE_CLOCKS 0
#endif

#ifndef OTIS_FORCE_BOOT_FAIL_BEFORE_CAPTURE
#define OTIS_FORCE_BOOT_FAIL_BEFORE_CAPTURE 0
#endif

#ifndef OTIS_FORCE_BOOT_FAIL_BEFORE_RUN_MODE
#define OTIS_FORCE_BOOT_FAIL_BEFORE_RUN_MODE 0
#endif

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
