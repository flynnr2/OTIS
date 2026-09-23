#include "otis_serial_command.h"

#include <ctype.h>
#include <string.h>

#include "otis_firmware_host_contract.generated.h"

namespace {

char *trim_command(char *text) {
  while (*text != '\0' && isspace((unsigned char)*text)) {
    ++text;
  }
  char *end = text + strlen(text);
  while (end > text && isspace((unsigned char)*(end - 1))) {
    --end;
    *end = '\0';
  }
  return text;
}

}  // namespace

void otis_serial_frame_collector_init(OtisSerialFrameCollector *collector) {
  if (collector == nullptr) {
    return;
  }
  collector->line[0] = '\0';
  collector->length = 0u;
  collector->discarding = false;
}

OtisSerialFrameEvent otis_serial_frame_collect(
    OtisSerialFrameCollector *collector, char byte) {
  if (collector == nullptr) {
    return OtisSerialFrameEvent::None;
  }

  const bool delimiter = byte == '\r' || byte == '\n';
  if (collector->discarding) {
    if (!delimiter) {
      return OtisSerialFrameEvent::None;
    }
    collector->discarding = false;
    collector->length = 0u;
    collector->line[0] = '\0';
    return OtisSerialFrameEvent::RejectedTooLong;
  }

  if (delimiter) {
    if (collector->length == 0u) {
      return OtisSerialFrameEvent::None;
    }
    collector->line[collector->length] = '\0';
    return OtisSerialFrameEvent::Complete;
  }

  if (collector->length < OTIS_SERIAL_COMMAND_MAX_LENGTH) {
    collector->line[collector->length++] = byte;
    return OtisSerialFrameEvent::None;
  }

  collector->length = 0u;
  collector->line[0] = '\0';
  collector->discarding = true;
  return OtisSerialFrameEvent::None;
}

OtisSerialFrameValidation otis_serial_frame_validate(
    const OtisSerialFrameCollector *collector) {
  if (collector == nullptr || collector->discarding ||
      collector->length > OTIS_SERIAL_COMMAND_MAX_LENGTH) {
    return OtisSerialFrameValidation::InvalidCharacter;
  }
  for (uint8_t index = 0u; index < collector->length; ++index) {
    const unsigned char byte = (unsigned char)collector->line[index];
    if (byte != '\t' && (byte < 0x20u || byte > 0x7Eu)) {
      return OtisSerialFrameValidation::InvalidCharacter;
    }
  }
  return OtisSerialFrameValidation::Valid;
}

OtisParsedSerialCommand otis_serial_command_parse(char *line) {
  OtisParsedSerialCommand parsed = {
      OtisSerialCommandKind::Empty,
      true,
      nullptr,
  };
  if (line == nullptr) {
    return parsed;
  }

  char *command = trim_command(line);
  for (char *cursor = command; *cursor != '\0'; ++cursor) {
    *cursor = (char)toupper((unsigned char)*cursor);
  }
  if (*command == '\0') {
    return parsed;
  }

  if (strcmp(command, "HELP") == 0) {
    parsed.kind = OtisSerialCommandKind::Help;
  } else if (strcmp(command, "CONFIG?") == 0) {
    parsed.kind = OtisSerialCommandKind::ConfigQuery;
  } else if (strcmp(command, "DUALCORE?") == 0) {
    parsed.kind = OtisSerialCommandKind::DualCoreQuery;
  } else if (strcmp(command, "DAC?") == 0) {
    parsed.kind = OtisSerialCommandKind::DacQuery;
  } else if (strcmp(command, "DAC LIMITS?") == 0) {
    parsed.kind = OtisSerialCommandKind::DacLimitsQuery;
  } else if (strcmp(command, "COUNT?") == 0) {
    parsed.kind = OtisSerialCommandKind::CountQuery;
  } else if (strcmp(command, "ACTIVE?") == 0) {
    parsed.kind = OtisSerialCommandKind::ActiveQuery;
  } else if (strncmp(command, OTIS_COMMAND_ACTIVE_SNAPSHOT_PREFIX " ",
                     OTIS_COMMAND_ACTIVE_SNAPSHOT_PREFIX_LENGTH + 1u) == 0) {
    parsed.kind = OtisSerialCommandKind::ActiveSnapshot;
    parsed.text_argument = trim_command(
        command + OTIS_COMMAND_ACTIVE_SNAPSHOT_PREFIX_LENGTH + 1u);
    parsed.arguments_valid = parsed.text_argument[0] != '\0';
  } else if (strncmp(command, "ACTIVE MODE ", 12u) == 0) {
    parsed.kind = OtisSerialCommandKind::ActiveMode;
    parsed.text_argument = trim_command(command + 12u);
    parsed.arguments_valid = parsed.text_argument[0] != '\0';
  } else {
    parsed.kind = OtisSerialCommandKind::Unknown;
  }
  return parsed;
}

bool otis_serial_command_parse_nonzero_decimal_u32_fields(
    const char *text, uint32_t *values, uint8_t count) {
  if (text == nullptr || values == nullptr || count == 0u) return false;
  const char *cursor = text;
  for (uint8_t index = 0u; index < count; ++index) {
    while (*cursor != '\0' && isspace((unsigned char)*cursor)) ++cursor;
    if (*cursor < '1' || *cursor > '9') return false;
    uint32_t value = 0u;
    do {
      const uint32_t digit = (uint32_t)(*cursor - '0');
      if (value > (UINT32_MAX - digit) / 10u) return false;
      value = value * 10u + digit;
      ++cursor;
    } while (*cursor >= '0' && *cursor <= '9');
    if (*cursor != '\0' && !isspace((unsigned char)*cursor)) return false;
    values[index] = value;
  }
  while (*cursor != '\0' && isspace((unsigned char)*cursor)) ++cursor;
  return *cursor == '\0';
}

bool otis_serial_command_parse_decimal_u32_fields(const char *text, uint32_t *values, uint8_t count) {
  if (!text || !values || !count) return false;
  for (uint8_t i=0; i<count; ++i) {
    while (*text && isspace((unsigned char)*text)) ++text;
    if (*text < '0' || *text > '9') return false;
    uint32_t value=0;
    do { const uint32_t d=*text-'0'; if (value>(UINT32_MAX-d)/10u) return false;
      value=value*10u+d; ++text;
    } while (*text>='0' && *text<='9');
    if (*text && !isspace((unsigned char)*text)) return false;
    values[i]=value;
  }
  while (*text && isspace((unsigned char)*text)) ++text;
  return !*text;
}
bool otis_serial_command_parse_decimal_u64_fields(const char *text, uint64_t *values, uint8_t count) {
  if (!text || !values || !count) return false;
  for (uint8_t i=0; i<count; ++i) {
    while (*text && isspace((unsigned char)*text)) ++text;
    if (*text < '0' || *text > '9') return false;
    uint64_t value=0;
    do { const uint32_t d=*text-'0'; if (value>(UINT64_MAX-d)/10u) return false;
      value=value*10u+d; ++text;
    } while (*text>='0' && *text<='9');
    if (*text && !isspace((unsigned char)*text)) return false;
    values[i]=value;
  }
  while (*text && isspace((unsigned char)*text)) ++text;
  return !*text;
}
