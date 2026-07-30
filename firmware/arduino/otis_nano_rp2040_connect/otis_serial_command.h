#ifndef OTIS_SERIAL_COMMAND_H
#define OTIS_SERIAL_COMMAND_H

#include <stddef.h>
#include <stdint.h>

constexpr size_t OTIS_SERIAL_COMMAND_BUFFER_SIZE = 64u;
constexpr size_t OTIS_SERIAL_COMMAND_MAX_LENGTH =
    OTIS_SERIAL_COMMAND_BUFFER_SIZE - 1u;

enum class OtisSerialFrameEvent : uint8_t {
  None = 0,
  Complete,
  RejectedTooLong,
};

struct OtisSerialFrameCollector {
  char line[OTIS_SERIAL_COMMAND_BUFFER_SIZE];
  uint8_t length;
  bool discarding;
};

enum class OtisSerialFrameValidation : uint8_t {
  Valid = 0,
  InvalidCharacter,
};

enum class OtisSerialCommandKind : uint8_t {
  Empty = 0,
  Help,
  ConfigQuery,
  DacQuery,
  DacLimitsQuery,
  DacMid,
  DacZero,
  DacSet,
  Fc0Query,
  SweepQuery,
  SweepLoad,
  SweepStart,
  SweepStop,
  SweepStep,
  SweepClear,
  SweepAdd,
  SweepOther,
  Unknown,
};

struct OtisParsedSerialCommand {
  OtisSerialCommandKind kind;
  bool arguments_valid;
  uint16_t code;
  uint32_t dwell_ms;
  char *text_argument;
};

void otis_serial_frame_collector_init(OtisSerialFrameCollector *collector);
OtisSerialFrameEvent otis_serial_frame_collect(
    OtisSerialFrameCollector *collector, char byte);
OtisSerialFrameValidation otis_serial_frame_validate(
    const OtisSerialFrameCollector *collector);
OtisParsedSerialCommand otis_serial_command_parse(char *line);

#endif
