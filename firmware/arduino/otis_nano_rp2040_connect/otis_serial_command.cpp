#include "otis_serial_command.h"

#include <ctype.h>
#include <stdlib.h>
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

bool parse_u16_code(char *text, uint16_t *out) {
  if (text == nullptr || out == nullptr || *text == '\0') {
    return false;
  }
  char *end = nullptr;
  unsigned long parsed = strtoul(text, &end, 0);
  if (end == text || *trim_command(end) != '\0' || parsed > 0xFFFFul) {
    return false;
  }
  *out = (uint16_t)parsed;
  return true;
}

bool parse_u32_value(char *text, uint32_t *out) {
  if (text == nullptr || out == nullptr || *text == '\0') {
    return false;
  }
  char *end = nullptr;
  unsigned long parsed = strtoul(text, &end, 0);
  if (end == text || *trim_command(end) != '\0') {
    return false;
  }
  *out = (uint32_t)parsed;
  return true;
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
      0u,
      0u,
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
  } else if (strcmp(command, "DUALCORE INVALIDATE_GNSS") == 0) {
    parsed.kind = OtisSerialCommandKind::DualCoreInvalidateGnss;
  } else if (strcmp(command, "DUALCORE RECOVER") == 0) {
    parsed.kind = OtisSerialCommandKind::DualCoreRecover;
  } else if (strncmp(command, "DUALCORE", 8) == 0) {
    parsed.kind = OtisSerialCommandKind::DualCoreOther;
  } else if (strcmp(command, "DAC?") == 0) {
    parsed.kind = OtisSerialCommandKind::DacQuery;
  } else if (strcmp(command, "DAC LIMITS?") == 0) {
    parsed.kind = OtisSerialCommandKind::DacLimitsQuery;
  } else if (strcmp(command, "DAC MID") == 0) {
    parsed.kind = OtisSerialCommandKind::DacMid;
  } else if (strcmp(command, "DAC ZERO") == 0) {
    parsed.kind = OtisSerialCommandKind::DacZero;
  } else if (strncmp(command, "DAC SET ", 8) == 0) {
    parsed.kind = OtisSerialCommandKind::DacSet;
    parsed.arguments_valid = parse_u16_code(command + 8, &parsed.code);
  } else if (strcmp(command, "FC0?") == 0) {
    parsed.kind = OtisSerialCommandKind::Fc0Query;
  } else if (strncmp(command, "Q2 CASE ", 8) == 0) {
    parsed.kind = OtisSerialCommandKind::Q2Case;
    parsed.text_argument = trim_command(command + 8);
    parsed.arguments_valid = parsed.text_argument[0] != '\0';
  } else if (strncmp(command, "Q2", 2) == 0) {
    parsed.kind = OtisSerialCommandKind::Q2Other;
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
  } else if (strncmp(command, "ACTIVE", 6) == 0) {
    parsed.kind = OtisSerialCommandKind::ActiveOther;
  } else if (strcmp(command, "SWEEP?") == 0) {
    parsed.kind = OtisSerialCommandKind::SweepQuery;
  } else if (strncmp(command, "SWEEP LOAD ", 11) == 0) {
    parsed.kind = OtisSerialCommandKind::SweepLoad;
    parsed.text_argument = trim_command(command + 11);
  } else if (strcmp(command, "SWEEP START") == 0) {
    parsed.kind = OtisSerialCommandKind::SweepStart;
  } else if (strcmp(command, "SWEEP STOP") == 0) {
    parsed.kind = OtisSerialCommandKind::SweepStop;
  } else if (strcmp(command, "SWEEP STEP") == 0) {
    parsed.kind = OtisSerialCommandKind::SweepStep;
  } else if (strcmp(command, "SWEEP CLEAR") == 0) {
    parsed.kind = OtisSerialCommandKind::SweepClear;
  } else if (strncmp(command, "SWEEP ADD ", 10) == 0) {
    parsed.kind = OtisSerialCommandKind::SweepAdd;
    char *code_text = trim_command(command + 10);
    char *space = code_text;
    while (*space != '\0' && !isspace((unsigned char)*space)) {
      ++space;
    }
    if (*space == '\0') {
      parsed.arguments_valid = false;
      return parsed;
    }
    *space = '\0';
    char *dwell_text = trim_command(space + 1);
    parsed.arguments_valid =
        parse_u16_code(code_text, &parsed.code) &&
        parse_u32_value(dwell_text, &parsed.dwell_ms) &&
        parsed.dwell_ms != 0u;
  } else if (strncmp(command, "SWEEP", 5) == 0) {
    parsed.kind = OtisSerialCommandKind::SweepOther;
  } else if (strcmp(command, "PPSGEN PROFILES?") == 0) {
    parsed.kind = OtisSerialCommandKind::PpsGenProfilesQuery;
  } else if (strncmp(command, "PPSGEN ARM ", 11) == 0) {
    parsed.kind = OtisSerialCommandKind::PpsGenArm;
    parsed.text_argument = trim_command(command + 11);
    parsed.arguments_valid = parsed.text_argument[0] != '\0';
  } else if (strcmp(command, "PPSGEN START") == 0) {
    parsed.kind = OtisSerialCommandKind::PpsGenStart;
  } else if (strcmp(command, "PPSGEN STOP") == 0) {
    parsed.kind = OtisSerialCommandKind::PpsGenStop;
  } else if (strcmp(command, "PPSGEN?") == 0) {
    parsed.kind = OtisSerialCommandKind::PpsGenQuery;
  } else if (strncmp(command, "PPSGEN", 6) == 0) {
    parsed.kind = OtisSerialCommandKind::PpsGenOther;
  } else {
    parsed.kind = OtisSerialCommandKind::Unknown;
  }
  return parsed;
}
