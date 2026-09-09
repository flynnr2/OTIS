#include "otis_serial_command.h"

#include <ctype.h>
#include <string.h>

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
  } else if (strncmp(command, "ACTIVE SNAPSHOT ", 16) == 0) {
    parsed.kind = OtisSerialCommandKind::ActiveSnapshot;
    parsed.text_argument = trim_command(command + 16);
    parsed.arguments_valid = parsed.text_argument[0] != '\0';
  } else if (strncmp(command, "ACTIVE SETUP ", 13) == 0) {
    parsed.kind = OtisSerialCommandKind::ActiveSetup;
    parsed.text_argument = trim_command(command + 13);
    parsed.arguments_valid = parsed.text_argument[0] != '\0';
  } else if (strncmp(command, "ACTIVE LEASE ", 13) == 0) {
    parsed.kind = OtisSerialCommandKind::ActiveLease;
    parsed.text_argument = trim_command(command + 13);
    parsed.arguments_valid = parsed.text_argument[0] != '\0';
  } else if (strncmp(command, "ACTIVE ARM ", 11) == 0) {
    parsed.kind = OtisSerialCommandKind::ActiveArm;
    parsed.text_argument = trim_command(command + 11);
    parsed.arguments_valid = parsed.text_argument[0] != '\0';
  } else if (strcmp(command, "ACTIVE ABORT") == 0) {
    parsed.kind = OtisSerialCommandKind::ActiveAbort;
  } else if (strncmp(command, "ACTIVE EVIDENCE ", 16) == 0) {
    parsed.kind = OtisSerialCommandKind::ActiveEvidence;
    parsed.text_argument = trim_command(command + 16);
    parsed.arguments_valid = parsed.text_argument[0] != '\0';
  } else {
    parsed.kind = OtisSerialCommandKind::Unknown;
  }
  return parsed;
}
