#include "otis_gnss_receiver.h"

#include "otis_config.h"

#include <ctype.h>
#include <stdlib.h>
#include <string.h>

namespace {

bool elapsed_at_least(uint32_t now, uint32_t then, uint32_t interval) {
  return static_cast<uint32_t>(now - then) >= interval;
}

bool field_has_digits(const char *value, size_t required) {
  if (value == nullptr) return false;
  for (size_t index = 0u; index < required; ++index) {
    if (value[index] == '\0' || !isdigit(static_cast<unsigned char>(value[index])))
      return false;
  }
  return true;
}

bool valid_utc_field(const char *value) {
  if (!field_has_digits(value, 6u)) return false;
  return value[6] == '\0' || value[6] == '.';
}

bool valid_date_field(const char *value) {
  return field_has_digits(value, 6u) && value[6] == '\0';
}

void copy_field(char *destination, size_t capacity, const char *source) {
  if (destination == nullptr || capacity == 0u) return;
  size_t length = source == nullptr ? 0u : strlen(source);
  if (length >= capacity) length = capacity - 1u;
  if (length > 0u) memcpy(destination, source, length);
  destination[length] = '\0';
}

int hex_value(char value) {
  if (value >= '0' && value <= '9') return value - '0';
  if (value >= 'A' && value <= 'F') return value - 'A' + 10;
  if (value >= 'a' && value <= 'f') return value - 'a' + 10;
  return -1;
}

void copy_fault_sentence_type(const OtisGnssReceiver *receiver,
                              char destination[4]) {
  destination[0] = '\0';
  if (receiver == nullptr || receiver->line_length < 4u ||
      receiver->line[0] != '$')
    return;
  size_t comma = 1u;
  while (comma < receiver->line_length && receiver->line[comma] != ',' &&
         receiver->line[comma] != '*')
    comma++;
  if (comma < 4u) return;
  const size_t start = comma - 3u;
  for (size_t index = 0u; index < 3u; ++index) {
    const unsigned char byte =
        static_cast<unsigned char>(receiver->line[start + index]);
    destination[index] = isalnum(byte) ? static_cast<char>(byte) : '_';
  }
  destination[3] = '\0';
}

void start_metadata_hold(OtisGnssReceiver *receiver, uint32_t now_ms,
                         uint64_t service_extended_ticks) {
  if (receiver->metadata_hold_active) return;
  receiver->metadata_hold_active = true;
  receiver->metadata_hold_count++;
  receiver->metadata_hold_started_ms = now_ms;
  receiver->metadata_hold_started_ticks = service_extended_ticks;
}

void maybe_finish_metadata_hold(OtisGnssReceiver *receiver, uint32_t now_ms,
                                uint64_t service_extended_ticks) {
  if (!receiver->metadata_hold_active || receiver->disconnected ||
      receiver->rmc_repair_epoch != receiver->parser_fault_epoch ||
      receiver->gga_repair_epoch != receiver->parser_fault_epoch)
    return;
  const uint32_t duration =
      static_cast<uint32_t>(now_ms - receiver->metadata_hold_started_ms);
  receiver->metadata_hold_active = false;
  receiver->metadata_recovery_latency_ms = duration;
  receiver->metadata_hold_cumulative_ms += duration;
  if (duration > receiver->metadata_hold_longest_ms)
    receiver->metadata_hold_longest_ms = duration;
  const uint64_t duration_ticks =
      service_extended_ticks - receiver->metadata_hold_started_ticks;
  receiver->metadata_recovery_latency_ticks = duration_ticks;
  receiver->metadata_hold_cumulative_ticks += duration_ticks;
  if (duration_ticks > receiver->metadata_hold_longest_ticks)
    receiver->metadata_hold_longest_ticks = duration_ticks;
}

void retain_fault_capsule(OtisGnssReceiver *receiver,
                          OtisGnssParserFaultClass fault_class) {
  for (uint8_t index = 0u; index < receiver->fault_capsule_count; ++index) {
    const OtisGnssParserFaultCapsule &existing =
        receiver->fault_capsules[index];
    if (existing.fault_class == fault_class &&
        existing.segment_ordinal == receiver->fault_context.segment_ordinal)
      return;
  }
  if (receiver->fault_capsule_count >= kOtisGnssFaultCapsuleCapacity) {
    receiver->fault_capsule_dropped_count++;
    return;
  }
  OtisGnssParserFaultCapsule &capsule =
      receiver->fault_capsules[receiver->fault_capsule_count++];
  capsule = {};
  capsule.valid = true;
  capsule.segment_ordinal = receiver->fault_context.segment_ordinal;
  capsule.observation_phase = receiver->fault_context.observation_phase;
  capsule.fault_class = fault_class;
  capsule.partial_line_length = receiver->line_length;
  capsule.baud = receiver->fault_context.baud;
  capsule.baud_epoch = receiver->fault_context.baud_epoch;
  capsule.hardware_overrun_delta =
      receiver->fault_context.hardware_overrun_delta;
  capsule.hardware_framing_delta =
      receiver->fault_context.hardware_framing_delta;
  capsule.hardware_parity_delta =
      receiver->fault_context.hardware_parity_delta;
  capsule.hardware_break_delta =
      receiver->fault_context.hardware_break_delta;
  capsule.raw_ring_depth = receiver->fault_context.raw_ring_depth;
  capsule.raw_ring_high_water = receiver->fault_context.raw_ring_high_water;
  capsule.preceding_consumer_gap_ticks =
      receiver->fault_context.preceding_consumer_gap_ticks;
  capsule.last_good_frame_sequence = receiver->last_good_frame_sequence;
  copy_fault_sentence_type(receiver, capsule.sentence_type);
}

void note_parser_fault(OtisGnssReceiver *receiver, uint32_t now_ms,
                       uint64_t service_extended_ticks,
                       OtisGnssParserFaultClass fault_class) {
  receiver->parser_drop_count++;
  receiver->parser_fault_epoch++;
  if (receiver->parser_fault_epoch == 0u) receiver->parser_fault_epoch = 1u;
  start_metadata_hold(receiver, now_ms, service_extended_ticks);
  retain_fault_capsule(receiver, fault_class);
}

void note_good_line_metrics(OtisGnssReceiver *receiver, uint32_t now_ms,
                            uint64_t service_extended_ticks) {
  const uint16_t length = receiver->line_length;
  if (receiver->minimum_line_length == 0u ||
      length < receiver->minimum_line_length)
    receiver->minimum_line_length = length;
  if (length > receiver->maximum_line_length)
    receiver->maximum_line_length = length;
  if (receiver->good_frame_seen) {
    const uint32_t gap =
        static_cast<uint32_t>(now_ms - receiver->last_good_frame_ms);
    if (receiver->minimum_interframe_gap_ms == 0u ||
        gap < receiver->minimum_interframe_gap_ms)
      receiver->minimum_interframe_gap_ms = gap;
    if (gap > receiver->maximum_interframe_gap_ms)
      receiver->maximum_interframe_gap_ms = gap;
    const uint64_t gap_ticks =
        service_extended_ticks - receiver->last_good_frame_ticks;
    if (receiver->minimum_interframe_gap_ticks == 0u ||
        gap_ticks < receiver->minimum_interframe_gap_ticks)
      receiver->minimum_interframe_gap_ticks = gap_ticks;
    if (gap_ticks > receiver->maximum_interframe_gap_ticks)
      receiver->maximum_interframe_gap_ticks = gap_ticks;
  }
  receiver->good_frame_seen = true;
  receiver->last_good_frame_ms = now_ms;
  receiver->last_good_frame_ticks = service_extended_ticks;
  receiver->last_good_frame_sequence++;
  maybe_finish_metadata_hold(receiver, now_ms, service_extended_ticks);
}

bool split_fields(char *body, char **fields, size_t capacity,
                  size_t *field_count) {
  size_t count = 0u;
  char *cursor = body;
  while (cursor != nullptr && count < capacity) {
    fields[count++] = cursor;
    char *comma = strchr(cursor, ',');
    if (comma == nullptr) {
      cursor = nullptr;
    } else {
      *comma = '\0';
      cursor = comma + 1;
    }
  }
  if (cursor != nullptr) return false;
  *field_count = count;
  return true;
}

bool parse_u8(const char *value, uint8_t maximum, uint8_t *result) {
  if (value == nullptr || *value == '\0') return false;
  char *end = nullptr;
  unsigned long parsed = strtoul(value, &end, 10);
  if (end == value || *end != '\0' || parsed > maximum) return false;
  *result = static_cast<uint8_t>(parsed);
  return true;
}

bool parse_u16(const char *value, uint16_t maximum, uint16_t *result) {
  if (value == nullptr || *value == '\0') return false;
  char *end = nullptr;
  unsigned long parsed = strtoul(value, &end, 10);
  if (end == value || *end != '\0' || parsed > maximum) return false;
  *result = static_cast<uint16_t>(parsed);
  return true;
}

void note_recognized_message(OtisGnssReceiver *receiver, uint32_t now_ms) {
  if (receiver->disconnected) {
    receiver->identity_epoch++;
    if (receiver->identity_epoch == 0u) receiver->identity_epoch = 1u;
    receiver->disconnected = false;
  }
  receiver->last_message_ms = now_ms;
}

bool parse_rmc(OtisGnssReceiver *receiver, char **fields, size_t count,
               uint32_t now_ms) {
  if (count < 10u || strlen(fields[0]) < 5u) return false;
  note_recognized_message(receiver, now_ms);
  receiver->rmc_seen = true;
  receiver->rmc_count++;
  receiver->last_rmc_ms = now_ms;
  receiver->rmc_repair_epoch = receiver->parser_fault_epoch;
  receiver->rmc_valid = strlen(fields[2]) == 1u && fields[2][0] == 'A';
  receiver->rmc_utc_available = valid_utc_field(fields[1]);
  receiver->utc_available =
      receiver->rmc_utc_available && receiver->gga_utc_available;
  receiver->date_available = valid_date_field(fields[9]);
  copy_field(receiver->talker, sizeof(receiver->talker), fields[0]);
  copy_field(receiver->utc, sizeof(receiver->utc), fields[1]);
  copy_field(receiver->date, sizeof(receiver->date), fields[9]);
  return true;
}

bool parse_gga(OtisGnssReceiver *receiver, char **fields, size_t count,
               uint32_t now_ms) {
  if (count < 9u || strlen(fields[0]) < 5u) return false;
  uint8_t fix_quality = 0u;
  uint8_t satellites = 0u;
  if (!parse_u8(fields[6], 8u, &fix_quality) ||
      !parse_u8(fields[7], 99u, &satellites))
    return false;
  note_recognized_message(receiver, now_ms);
  receiver->gga_seen = true;
  receiver->gga_count++;
  receiver->last_gga_ms = now_ms;
  receiver->gga_repair_epoch = receiver->parser_fault_epoch;
  receiver->fix_quality = fix_quality;
  receiver->satellites = satellites;
  receiver->gga_utc_available = valid_utc_field(fields[1]);
  receiver->utc_available =
      receiver->rmc_utc_available && receiver->gga_utc_available;
  copy_field(receiver->talker, sizeof(receiver->talker), fields[0]);
  copy_field(receiver->hdop, sizeof(receiver->hdop), fields[8]);
  return true;
}

bool parse_gsa(OtisGnssReceiver *receiver, char **fields, size_t count,
               uint32_t now_ms) {
  if (count < 3u || strlen(fields[0]) < 5u) return false;
  uint8_t fix_dimension = 0u;
  if (!parse_u8(fields[2], 3u, &fix_dimension) || fix_dimension < 1u)
    return false;
  // GSA Mode 2 is the explicit no-fix/2D/3D dimension. It is deliberately
  // kept distinct from GGA fix quality and from the one-pulse-per-second pin.
  receiver->gsa_seen = true;
  receiver->gsa_count++;
  receiver->last_gsa_ms = now_ms;
  receiver->gsa_repair_epoch = receiver->parser_fault_epoch;
  receiver->fix_dimension = fix_dimension;
  return true;
}

void parse_complete_line(OtisGnssReceiver *receiver, uint32_t now_ms,
                         uint64_t service_extended_ticks) {
  receiver->line[receiver->line_length] = '\0';
  if (receiver->line_length < 7u || receiver->line[0] != '$') {
    receiver->truncated_count++;
    note_parser_fault(receiver, now_ms, service_extended_ticks,
                      OtisGnssParserFaultClass::LineShape);
    return;
  }
  char *star = strrchr(receiver->line, '*');
  if (star == nullptr || star != receiver->line + receiver->line_length - 3u) {
    receiver->truncated_count++;
    note_parser_fault(receiver, now_ms, service_extended_ticks,
                      OtisGnssParserFaultClass::LineShape);
    return;
  }
  const int upper = hex_value(star[1]);
  const int lower = hex_value(star[2]);
  if (upper < 0 || lower < 0) {
    receiver->truncated_count++;
    note_parser_fault(receiver, now_ms, service_extended_ticks,
                      OtisGnssParserFaultClass::LineShape);
    return;
  }
  uint8_t checksum = 0u;
  for (char *cursor = receiver->line + 1; cursor < star; ++cursor)
    checksum ^= static_cast<uint8_t>(*cursor);
  const uint8_t expected = static_cast<uint8_t>((upper << 4) | lower);
  if (checksum != expected) {
    receiver->checksum_failure_count++;
    note_parser_fault(receiver, now_ms, service_extended_ticks,
                      OtisGnssParserFaultClass::Checksum);
    return;
  }
  receiver->checksum_valid_count++;
  *star = '\0';
  char *fields[24] = {};
  size_t field_count = 0u;
  if (!split_fields(receiver->line + 1, fields, 24u, &field_count) ||
      field_count == 0u) {
    receiver->truncated_count++;
    note_parser_fault(receiver, now_ms, service_extended_ticks,
                      OtisGnssParserFaultClass::FieldShape);
    return;
  }
  const size_t type_length = strlen(fields[0]);
  const char *type = type_length >= 3u ? fields[0] + type_length - 3u : "";
  bool parsed = true;
  if (strcmp(type, "RMC") == 0) {
    parsed = parse_rmc(receiver, fields, field_count, now_ms);
  } else if (strcmp(type, "GGA") == 0) {
    parsed = parse_gga(receiver, fields, field_count, now_ms);
  } else if (strcmp(type, "GSA") == 0) {
    parsed = parse_gsa(receiver, fields, field_count, now_ms);
  } else {
    return;
  }
  if (!parsed) {
    receiver->truncated_count++;
    note_parser_fault(receiver, now_ms, service_extended_ticks,
                      OtisGnssParserFaultClass::FieldShape);
    return;
  }
  note_good_line_metrics(receiver, now_ms, service_extended_ticks);
}

}  // namespace

namespace {

#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION
constexpr uint32_t kGnssCandidateBauds[] = {
    9600u, 19200u, 38400u, 57600u, 115200u,
};
constexpr char kGnssTargetBaud9600Command[] = "$PMTK251,9600*17\r\n";
constexpr char kGnssTargetBaud19200Command[] = "$PMTK251,19200*22\r\n";
constexpr char kGnssTargetBaud38400Command[] = "$PMTK251,38400*27\r\n";
constexpr char kGnssTargetBaud57600Command[] = "$PMTK251,57600*2C\r\n";
constexpr char kGnssTargetBaud115200Command[] = "$PMTK251,115200*1F\r\n";
#elif OTIS_GNSS_UART_BAUD == 9600u
constexpr uint32_t kGnssCandidateBauds[] = {
    9600u, 115200u, 57600u, 38400u, 19200u, 14400u, 4800u,
};
constexpr char kGnssTargetBaudCommand[] = "$PMTK251,9600*17\r\n";
#else
constexpr uint32_t kGnssCandidateBauds[] = {
    115200u, 9600u, 57600u, 38400u, 19200u, 14400u, 4800u,
};
constexpr uint32_t kGnssOperationalBootstrapBauds[] = {
    9600u, 19200u, 38400u, 57600u, 14400u, 4800u, 115200u,
};
constexpr size_t kGnssOperationalBootstrapBaudCount =
    sizeof(kGnssOperationalBootstrapBauds) /
    sizeof(kGnssOperationalBootstrapBauds[0]);
constexpr char kGnssTargetBaudCommand[] = "$PMTK251,115200*1F\r\n";
#endif
constexpr size_t kGnssCandidateBaudCount =
    sizeof(kGnssCandidateBauds) / sizeof(kGnssCandidateBauds[0]);
constexpr char kGnssIdentityQuery[] = "$PMTK605*31\r\n";
constexpr char kGnssOutputQuery[] = "$PMTK414*33\r\n";
constexpr char kGnssOutputConfiguration[] =
    "$PMTK314,0,1,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0*29\r\n";
constexpr uint8_t kGnssExpectedOutputConfiguration[] = {
    0u, 1u, 0u, 1u, 1u, 0u, 0u, 0u, 0u, 0u,
    0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u,
};
constexpr size_t kGnssObservedExtendedOutputConfigurationFields = 22u;
constexpr uint32_t kGnssOutputRmcMask = 1u << 0u;
constexpr uint32_t kGnssOutputGgaMask = 1u << 1u;
constexpr uint32_t kGnssOutputGsaMask = 1u << 2u;
constexpr uint32_t kGnssOutputGllMask = 1u << 3u;
constexpr uint32_t kGnssOutputVtgMask = 1u << 4u;
constexpr uint32_t kGnssOutputGsvMask = 1u << 5u;
constexpr uint32_t kGnssOutputZdaMask = 1u << 6u;
constexpr uint32_t kGnssOutputOtherMask = 1u << 31u;
constexpr uint32_t kGnssRequiredOutputMask =
    kGnssOutputRmcMask | kGnssOutputGgaMask | kGnssOutputGsaMask;
#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION && \
    OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD
constexpr char kGnssObservedIdentityMarker[] = "NMEA_CADENCE_OBSERVED";
constexpr char kGnssObservedExtendedOutputSignature[] =
    "0101100000000000000000";
#endif

const char *fixed_target_baud_command(uint32_t baud, size_t *length) {
  if (length == nullptr) return nullptr;
#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION
  switch (baud) {
    case 9600u:
      *length = sizeof(kGnssTargetBaud9600Command) - 1u;
      return kGnssTargetBaud9600Command;
    case 19200u:
      *length = sizeof(kGnssTargetBaud19200Command) - 1u;
      return kGnssTargetBaud19200Command;
    case 38400u:
      *length = sizeof(kGnssTargetBaud38400Command) - 1u;
      return kGnssTargetBaud38400Command;
    case 57600u:
      *length = sizeof(kGnssTargetBaud57600Command) - 1u;
      return kGnssTargetBaud57600Command;
    case 115200u:
      *length = sizeof(kGnssTargetBaud115200Command) - 1u;
      return kGnssTargetBaud115200Command;
    default:
      *length = 0u;
      return nullptr;
  }
#else
  if (baud != OTIS_GNSS_UART_BAUD) {
    *length = 0u;
    return nullptr;
  }
  *length = sizeof(kGnssTargetBaudCommand) - 1u;
  return kGnssTargetBaudCommand;
#endif
}

void reset_link_line(OtisGnssLink *link) {
  link->line_length = 0u;
  link->collecting = false;
  link->discarding_oversize = false;
}

uint32_t candidate_baud(uint8_t index) {
  return index < kGnssCandidateBaudCount ? kGnssCandidateBauds[index]
                                         : kGnssCandidateBauds[0];
}

void queue_link_action(OtisGnssLink *link, OtisGnssLinkState state,
                       OtisGnssLinkActionKind action);

#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION && \
    OTIS_GNSS_DISCOVERY_STARTUP_BAUD_HINT != 0u
void select_startup_hint(OtisGnssLink *link, uint32_t now_ms) {
  link->startup_hint_active = true;
  link->startup_hint_attempted = true;
  link->startup_hint_baud = OTIS_GNSS_DISCOVERY_STARTUP_BAUD_HINT;
  link->startup_hint_identity_outcome =
      OtisGnssStartupHintIdentityOutcome::Pending;
  link->candidate_baud = link->startup_hint_baud;
  link->discovery_output_repair_active = false;
  link->output_observed_sentence_mask = 0u;
  link->output_unexpected_sentence_mask = 0u;
  link->pending_baud = link->candidate_baud;
#if OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD
  link->output_observed_sentence_mask = 0u;
  link->output_unexpected_sentence_mask = 0u;
#endif
  link->state_started_ms = now_ms;
  reset_link_line(link);
  queue_link_action(link, OtisGnssLinkState::SelectCandidateBaud,
                    OtisGnssLinkActionKind::SetUartBaud);
}
#endif

void queue_link_action(OtisGnssLink *link, OtisGnssLinkState state,
                       OtisGnssLinkActionKind action) {
  link->state = state;
  link->pending_action = action;
  link->action_pending = true;
  link->action_in_progress = false;
}

void select_candidate(OtisGnssLink *link, uint32_t now_ms) {
  link->candidate_baud = candidate_baud(link->candidate_index);
  link->discovery_output_repair_active = false;
  link->output_observed_sentence_mask = 0u;
  link->output_unexpected_sentence_mask = 0u;
  link->pending_baud = link->candidate_baud;
#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION && \
    OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD
  link->output_observed_sentence_mask = 0u;
  link->output_unexpected_sentence_mask = 0u;
#endif
  link->state_started_ms = now_ms;
  reset_link_line(link);
  queue_link_action(link, OtisGnssLinkState::SelectCandidateBaud,
                    OtisGnssLinkActionKind::SetUartBaud);
}

void restart_discovery(OtisGnssLink *link, uint32_t now_ms,
                       bool link_was_lost);

void advance_candidate(OtisGnssLink *link, uint32_t now_ms) {
  link->candidate_rejection_count++;
  if (link->startup_hint_active) {
    link->startup_hint_active = false;
    link->startup_fallback_entered = true;
    link->startup_hint_identity_outcome =
        OtisGnssStartupHintIdentityOutcome::TimedOut;
    link->candidate_index = 0u;
    select_candidate(link, now_ms);
    return;
  }
  link->candidate_index++;
  if (link->candidate_index >= kGnssCandidateBaudCount) {
    if (link->characterization_recovery_scan) {
      link->candidate_index = 0u;
      link->discovery_cycle++;
      link->characterization_recovery_scan_exhausted = true;
      link->action_pending = false;
      link->action_in_progress = false;
      link->pending_action = OtisGnssLinkActionKind::None;
      return;
    }
    link->candidate_index = 0u;
    link->discovery_cycle++;
  }
  select_candidate(link, now_ms);
}

void fail_validation_or_restart(OtisGnssLink *link, uint32_t now_ms) {
  link->nmea_observation_active = false;
  link->discovery_output_repair_active = false;
  if (link->startup_hint_active || link->startup_hint_attachment_active) {
    link->startup_hint_active = false;
    link->startup_hint_attachment_active = false;
    link->startup_fallback_entered = true;
    if (link->startup_hint_identity_outcome ==
        OtisGnssStartupHintIdentityOutcome::Pending)
      link->startup_hint_identity_outcome =
          OtisGnssStartupHintIdentityOutcome::TransmitFailed;
  }
  if (link->characterization_targeting) {
    link->characterization_target_failed = true;
    link->action_pending = false;
    link->action_in_progress = false;
    link->pending_action = OtisGnssLinkActionKind::None;
    return;
  }
  restart_discovery(link, now_ms, false);
}

void restart_discovery(OtisGnssLink *link, uint32_t now_ms,
                       bool link_was_lost) {
  if (link_was_lost) link->link_loss_count++;
  link->configuration_confirmed = false;
  link->output_configuration_command_acknowledged = false;
  link->output_confirmation_method = OtisGnssOutputConfirmationMethod::None;
  link->nmea_observation_active = false;
  link->discovery_output_repair_active = false;
  link->receiver_identity_available = false;
  link->confirmed_baud = 0u;
  link->candidate_index = 0u;
  link->discovery_cycle++;
  link->discovery_started_ms = now_ms;
#if !OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION && \
    OTIS_GNSS_UART_BAUD == 115200u
  // Operational 115200 profiles never scan.  Startup has already sent the
  // fixed promotion packet at 9600; recovery stays at the required rate and
  // requalifies the receiver there.
  link->candidate_baud = link->policy.target_baud;
  link->pending_baud = link->policy.target_baud;
  link->state_started_ms = now_ms;
  reset_link_line(link);
  queue_link_action(link, OtisGnssLinkState::SelectTargetBaud,
                    OtisGnssLinkActionKind::SetUartBaud);
#else
  select_candidate(link, now_ms);
#endif
}

void queue_identity_query(OtisGnssLink *link, bool at_target) {
  queue_link_action(
      link,
      at_target ? OtisGnssLinkState::TransmitTargetIdentityQuery
                : OtisGnssLinkState::TransmitIdentityQuery,
      OtisGnssLinkActionKind::TransmitIdentityQuery);
}

void queue_output_query(OtisGnssLink *link, bool verification) {
  queue_link_action(
      link,
      verification ? OtisGnssLinkState::TransmitOutputVerificationQuery
                   : OtisGnssLinkState::TransmitOutputQuery,
      OtisGnssLinkActionKind::TransmitOutputQuery);
}

void begin_output_observation(OtisGnssLink *link, uint32_t now_ms) {
  link->state = OtisGnssLinkState::ObserveConfiguredOutput;
  link->state_started_ms = now_ms;
  link->output_observed_sentence_mask = 0u;
  link->output_unexpected_sentence_mask = 0u;
  link->action_pending = false;
  link->action_in_progress = false;
  link->pending_action = OtisGnssLinkActionKind::None;
}

void copy_release_identity(OtisGnssLink *link, const char *release) {
  if (release == nullptr || *release == '\0') {
    link->receiver_release[0] = '\0';
    link->receiver_identity_available = false;
    return;
  }
  size_t output = 0u;
  while (release[output] != '\0' &&
         output < sizeof(link->receiver_release) - 1u) {
    const unsigned char byte = static_cast<unsigned char>(release[output]);
    link->receiver_release[output] =
        (isalnum(byte) || byte == '_' || byte == '-' || byte == '.')
            ? static_cast<char>(byte)
            : '_';
    output++;
  }
  link->receiver_release[output] = '\0';
  link->receiver_identity_available = output > 0u;
}

bool output_configuration_matches(char **fields, size_t field_count) {
  const size_t data_fields = field_count > 0u ? field_count - 1u : 0u;
  if (data_fields != sizeof(kGnssExpectedOutputConfiguration) &&
      data_fields != kGnssObservedExtendedOutputConfigurationFields)
    return false;
  for (size_t index = 0u;
       index < sizeof(kGnssExpectedOutputConfiguration); ++index) {
    uint8_t parsed = 0u;
    if (!parse_u8(fields[index + 1u], 5u, &parsed) ||
        parsed != kGnssExpectedOutputConfiguration[index])
      return false;
  }
  // The physical PA1616S used by OTIS reports three additional fields beyond
  // the 19-field MT3339 A11 form. They are accepted only as an exact disabled
  // extension; any nonzero or malformed extension remains a mismatch.
  for (size_t index = sizeof(kGnssExpectedOutputConfiguration);
       index < data_fields; ++index) {
    uint8_t parsed = 0u;
    if (!parse_u8(fields[index + 1u], 5u, &parsed) || parsed != 0u)
      return false;
  }
  return true;
}

void record_output_configuration(OtisGnssLink *link, char **fields,
                                 size_t field_count) {
  const size_t data_fields = field_count > 0u ? field_count - 1u : 0u;
  link->output_configuration_field_count = static_cast<uint8_t>(
      data_fields > UINT8_MAX ? UINT8_MAX : data_fields);
  size_t output = 0u;
  for (size_t index = 0u;
       index < data_fields &&
       output < sizeof(link->output_configuration_signature) - 1u;
       ++index) {
    const char *field = fields[index + 1u];
    link->output_configuration_signature[output++] =
        field != nullptr && field[0] >= '0' && field[0] <= '5' &&
                field[1] == '\0'
            ? field[0]
            : '?';
  }
  link->output_configuration_signature[output] = '\0';
}

uint32_t output_sentence_mask(const char *packet_type) {
  if (packet_type == nullptr) return 0u;
  const size_t length = strlen(packet_type);
  if (length < 5u || strncmp(packet_type, "PMTK", 4u) == 0) return 0u;
  const char *suffix = packet_type + length - 3u;
  if (strcmp(suffix, "RMC") == 0) return kGnssOutputRmcMask;
  if (strcmp(suffix, "GGA") == 0) return kGnssOutputGgaMask;
  if (strcmp(suffix, "GSA") == 0) return kGnssOutputGsaMask;
  if (strcmp(suffix, "GLL") == 0) return kGnssOutputGllMask;
  if (strcmp(suffix, "VTG") == 0) return kGnssOutputVtgMask;
  if (strcmp(suffix, "GSV") == 0) return kGnssOutputGsvMask;
  if (strcmp(suffix, "ZDA") == 0) return kGnssOutputZdaMask;
  return kGnssOutputOtherMask;
}

void note_observed_output_sentence(OtisGnssLink *link,
                                   const char *packet_type) {
  const bool configured_output_observation =
      link->state == OtisGnssLinkState::ObserveConfiguredOutput;
#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION && \
    OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD
  const bool retained_baud_discovery_observation =
      link->state == OtisGnssLinkState::PassiveListen ||
      link->state == OtisGnssLinkState::AwaitIdentityResponse ||
      link->state == OtisGnssLinkState::AwaitTargetIdentityResponse ||
      (link->discovery_output_repair_active &&
       link->state == OtisGnssLinkState::AwaitOutputConfigurationAck);
#else
  constexpr bool retained_baud_discovery_observation = false;
#endif
  if (!configured_output_observation &&
      !retained_baud_discovery_observation)
    return;
  const uint32_t mask = output_sentence_mask(packet_type);
  if (mask == 0u) return;
  link->output_observed_sentence_mask |= mask;
  if ((mask & ~kGnssRequiredOutputMask) != 0u)
    link->output_unexpected_sentence_mask |= mask;
}

void establish_online_link(OtisGnssLink *link, uint32_t now_ms,
                           OtisGnssOutputConfirmationMethod method) {
  link->state = OtisGnssLinkState::Online;
  link->state_started_ms = now_ms;
  link->confirmed_baud = link->policy.target_baud;
  link->configuration_confirmed = true;
  link->output_confirmation_method = method;
  link->action_pending = false;
  link->action_in_progress = false;
  link->pending_action = OtisGnssLinkActionKind::None;
  link->startup_hint_attachment_active = false;
  link->nmea_observation_active = false;
  link->discovery_output_repair_active = false;
}

#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION && \
    OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD
bool nmea_identity_fallback_ready(const OtisGnssLink *link) {
  return (link->output_observed_sentence_mask & kGnssRequiredOutputMask) ==
             kGnssRequiredOutputMask &&
         link->output_unexpected_sentence_mask == 0u;
}

void begin_nmea_identity_fallback(OtisGnssLink *link, uint32_t now_ms,
                                  bool candidate_response) {
  if (candidate_response) {
    if (link->startup_hint_active) {
      link->startup_hint_active = false;
      link->startup_hint_attachment_active = true;
      link->startup_hint_identity_outcome =
          OtisGnssStartupHintIdentityOutcome::Confirmed;
      link->initial_discovery_outcome =
          OtisGnssInitialDiscoveryOutcome::HintConfirmed;
    } else {
      link->initial_discovery_outcome =
          OtisGnssInitialDiscoveryOutcome::FallbackConfirmed;
    }
    link->initial_discovery_identity_baud = link->candidate_baud;
    link->policy.target_baud = link->candidate_baud;
  }
  link->identity_response_count++;
  link->last_identity_response_baud = link->candidate_baud;
  if (!link->receiver_identity_available ||
      link->receiver_release[0] == '\0')
    copy_release_identity(link, kGnssObservedIdentityMarker);
  link->output_configuration_signature[0] = '\0';
  link->nmea_observation_active = true;
  link->discovery_output_repair_active = false;
  begin_output_observation(link, now_ms);
}
#endif

void note_identity_response(OtisGnssLink *link, char **fields,
                            size_t field_count, uint32_t now_ms) {
  if (field_count < 2u) return;
  const bool candidate_response =
      link->state == OtisGnssLinkState::AwaitIdentityResponse;
  const bool target_response =
      link->state == OtisGnssLinkState::AwaitTargetIdentityResponse;
  if (!candidate_response && !target_response) return;
  link->identity_response_count++;
#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION && \
    OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD
  const bool preserve_observed_identity =
      link->characterization_targeting &&
      strcmp(link->receiver_release, kGnssObservedIdentityMarker) == 0;
  if (!preserve_observed_identity) copy_release_identity(link, fields[1]);
#else
  copy_release_identity(link, fields[1]);
#endif
  if (!link->receiver_identity_available) return;
  link->last_identity_response_baud = link->candidate_baud;

#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION && \
    OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD
  const bool identity_confirms_retained_startup = candidate_response;
#endif
  if (candidate_response &&
      link->initial_discovery_outcome ==
          OtisGnssInitialDiscoveryOutcome::Pending) {
    link->initial_discovery_identity_baud = link->candidate_baud;
    if (link->startup_hint_active) {
      link->startup_hint_active = false;
      link->startup_hint_identity_outcome =
          OtisGnssStartupHintIdentityOutcome::Confirmed;
      link->initial_discovery_outcome =
          OtisGnssInitialDiscoveryOutcome::HintConfirmed;
    } else {
      link->initial_discovery_outcome =
          OtisGnssInitialDiscoveryOutcome::FallbackConfirmed;
    }
  }

#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION && \
    OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD
  // Continuation attachment preserves the freshly discovered receiver rate,
  // whether discovery succeeds at the initial hint or during the fallback
  // scan. A fresh PMTK705 authorizes only an output query here: no PMTK251 is
  // emitted, and Online still requires exact output confirmation. Fresh
  // RMC/GGA/GSA remains a separate host attachment gate.
  if (identity_confirms_retained_startup) {
    link->startup_hint_attachment_active = true;
    link->policy.target_baud = link->candidate_baud;
    link->confirmed_baud = link->candidate_baud;
    link->state_started_ms = now_ms;
    queue_output_query(link, false);
    return;
  }
#endif

  if (candidate_response && link->characterization_recovery_scan) {
    link->policy.target_baud = link->candidate_baud;
    link->confirmed_baud = link->candidate_baud;
    link->state_started_ms = now_ms;
    queue_output_query(link, false);
    return;
  }

  if (candidate_response && link->candidate_baud != link->policy.target_baud) {
    queue_link_action(link, OtisGnssLinkState::TransmitTargetBaud,
                      OtisGnssLinkActionKind::TransmitTargetBaud);
    return;
  }
  link->confirmed_baud = link->policy.target_baud;
  link->state_started_ms = now_ms;
  queue_output_query(link, false);
}

void note_output_response(OtisGnssLink *link, char **fields,
                          size_t field_count, uint32_t now_ms) {
  const bool initial = link->state == OtisGnssLinkState::AwaitOutputResponse;
  const bool verification =
      link->state == OtisGnssLinkState::AwaitOutputVerificationResponse;
  if (!initial && !verification) return;
  link->output_response_count++;
  record_output_configuration(link, fields, field_count);
  if (output_configuration_matches(fields, field_count)) {
    establish_online_link(link, now_ms,
                          OtisGnssOutputConfirmationMethod::Pmtk514Exact);
    return;
  }
  if (initial) {
    queue_link_action(link,
                      OtisGnssLinkState::TransmitOutputConfiguration,
                      OtisGnssLinkActionKind::TransmitOutputConfiguration);
    return;
  }
  link->configuration_failure_count++;
  fail_validation_or_restart(link, now_ms);
}

void note_command_ack(OtisGnssLink *link, char **fields, size_t field_count,
                      uint32_t now_ms) {
  if (field_count != 3u) return;
  uint16_t packet_type = 0u;
  uint8_t flag = 0u;
  if (!parse_u16(fields[1], 999u, &packet_type) ||
      !parse_u8(fields[2], 3u, &flag))
    return;
  link->last_command_ack_packet_type = packet_type;
  link->last_command_ack_flag = flag;

  if ((link->state == OtisGnssLinkState::AwaitOutputResponse ||
       link->state == OtisGnssLinkState::AwaitOutputVerificationResponse) &&
      packet_type == 414u && flag == 1u) {
    if (link->state == OtisGnssLinkState::AwaitOutputResponse) {
      queue_link_action(link,
                        OtisGnssLinkState::TransmitOutputConfiguration,
                        OtisGnssLinkActionKind::TransmitOutputConfiguration);
    } else if (link->output_configuration_command_acknowledged) {
      begin_output_observation(link, now_ms);
    }
    return;
  }

  if (link->state != OtisGnssLinkState::AwaitOutputConfigurationAck ||
      packet_type != 314u)
    return;
  if (flag == 3u) {
    link->output_configuration_command_acknowledged = true;
    link->output_configuration_ack_count++;
#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION && \
    OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD
    if (link->discovery_output_repair_active) {
      begin_nmea_identity_fallback(link, now_ms, true);
      return;
    }
#endif
    queue_output_query(link, true);
    return;
  }
  link->configuration_failure_count++;
  fail_validation_or_restart(link, now_ms);
}

void process_link_line(OtisGnssLink *link, uint32_t now_ms) {
  link->line[link->line_length] = '\0';
  if (link->line_length < 7u || link->line[0] != '$') return;
  char *star = strrchr(link->line, '*');
  if (star == nullptr || star != link->line + link->line_length - 3u) return;
  const int upper = hex_value(star[1]);
  const int lower = hex_value(star[2]);
  if (upper < 0 || lower < 0) return;
  uint8_t checksum = 0u;
  for (char *cursor = link->line + 1; cursor < star; ++cursor)
    checksum ^= static_cast<uint8_t>(*cursor);
  if (checksum != static_cast<uint8_t>((upper << 4) | lower)) {
    link->checksum_failure_count++;
    return;
  }

  link->checksum_valid_count++;
  link->valid_frame_seen = true;
  link->last_valid_frame_ms = now_ms;
  *star = '\0';
  char *fields[24] = {};
  size_t field_count = 0u;
  if (!split_fields(link->line + 1, fields, 24u, &field_count) ||
      field_count == 0u)
    return;

  note_observed_output_sentence(link, fields[0]);

  if (strcmp(fields[0], "PMTK705") == 0) {
    note_identity_response(link, fields, field_count, now_ms);
  } else if (strcmp(fields[0], "PMTK514") == 0) {
    note_output_response(link, fields, field_count, now_ms);
  } else if (strcmp(fields[0], "PMTK001") == 0) {
    note_command_ack(link, fields, field_count, now_ms);
  }

  if (link->state == OtisGnssLinkState::PassiveListen)
    queue_identity_query(link, false);
}

}  // namespace

void otis_gnss_link_reset(OtisGnssLink *link,
                          const OtisGnssLinkPolicy *policy,
                          uint32_t now_ms) {
  if (link == nullptr || policy == nullptr) return;
  *link = {};
  link->service_initialized = true;
  link->policy = *policy;
  link->discovery_cycle = 1u;
  link->discovery_started_ms = now_ms;
#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION
#if OTIS_GNSS_DISCOVERY_STARTUP_BAUD_HINT != 0u
  select_startup_hint(link, now_ms);
#else
  select_candidate(link, now_ms);
#endif
#elif OTIS_GNSS_UART_BAUD == 115200u
  // Fixed operational bootstrap: transmit the same set-115200 packet once at
  // every supported retained rate, then stay at 115200.  No response-driven
  // discovery or fallback is involved.
  link->candidate_index = 0u;
  link->candidate_baud = kGnssOperationalBootstrapBauds[0];
  link->pending_baud = link->candidate_baud;
  link->state_started_ms = now_ms;
  reset_link_line(link);
  queue_link_action(link, OtisGnssLinkState::SelectCandidateBaud,
                    OtisGnssLinkActionKind::SetUartBaud);
#else
  select_candidate(link, now_ms);
#endif
}

void otis_gnss_link_tick(OtisGnssLink *link, uint32_t now_ms) {
  if (link == nullptr || !link->service_initialized || link->action_pending ||
      link->action_in_progress)
    return;
  switch (link->state) {
    case OtisGnssLinkState::PassiveListen:
      if (elapsed_at_least(now_ms, link->state_started_ms,
                           link->policy.passive_dwell_ms))
        queue_identity_query(link, false);
      break;
    case OtisGnssLinkState::AwaitIdentityResponse:
      if (elapsed_at_least(now_ms, link->state_started_ms,
                           link->policy.response_timeout_ms)) {
#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION && \
    OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD
        if (nmea_identity_fallback_ready(link)) {
          // Some installed receivers continue the exact configured NMEA
          // cadence but do not answer PMTK605/PMTK414. Bind that evidence to
          // the selected retained baud explicitly, then require a fresh full
          // observation window before configuration is confirmed.
          begin_nmea_identity_fallback(link, now_ms, true);
          break;
        }
        // A receiver can retain its baud while losing its configured output,
        // and a power-up receiver can be silent under an unexpected cadence.
        // Apply the one frozen output command at this candidate before moving
        // on; no PMTK251 baud change is emitted until UART decoding is proven.
        link->discovery_output_repair_active = true;
        link->output_observed_sentence_mask = 0u;
        link->output_unexpected_sentence_mask = 0u;
        queue_link_action(link,
                          OtisGnssLinkState::TransmitOutputConfiguration,
                          OtisGnssLinkActionKind::TransmitOutputConfiguration);
        break;
#endif
        advance_candidate(link, now_ms);
      }
      break;
    case OtisGnssLinkState::AwaitTargetIdentityResponse:
      if (elapsed_at_least(now_ms, link->state_started_ms,
                           link->policy.response_timeout_ms)) {
#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION && \
    OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD
        if (nmea_identity_fallback_ready(link)) {
          begin_nmea_identity_fallback(link, now_ms, false);
          break;
        }
#endif
        link->configuration_failure_count++;
        if (link->characterization_targeting &&
            !elapsed_at_least(now_ms,
                              link->characterization_target_started_ms,
                              10000u)) {
          queue_identity_query(link, true);
        } else {
          fail_validation_or_restart(link, now_ms);
        }
      }
      break;
    case OtisGnssLinkState::AwaitOutputConfigurationAck:
      if (elapsed_at_least(now_ms, link->state_started_ms,
                           link->policy.response_timeout_ms)) {
#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION && \
    OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD
        if (link->discovery_output_repair_active) {
          if (nmea_identity_fallback_ready(link)) {
            begin_nmea_identity_fallback(link, now_ms, true);
          } else {
            link->discovery_output_repair_active = false;
            advance_candidate(link, now_ms);
          }
          break;
        }
#endif
        link->configuration_failure_count++;
        fail_validation_or_restart(link, now_ms);
      }
      break;
    case OtisGnssLinkState::AwaitOutputResponse:
      if (elapsed_at_least(now_ms, link->state_started_ms,
                           link->policy.response_timeout_ms)) {
        link->output_query_timeout_count++;
        queue_link_action(link,
                          OtisGnssLinkState::TransmitOutputConfiguration,
                          OtisGnssLinkActionKind::TransmitOutputConfiguration);
      }
      break;
    case OtisGnssLinkState::AwaitOutputVerificationResponse:
      if (elapsed_at_least(now_ms, link->state_started_ms,
                           link->policy.response_timeout_ms)) {
        link->output_query_timeout_count++;
        if (link->output_configuration_command_acknowledged) {
          begin_output_observation(link, now_ms);
        } else {
          link->configuration_failure_count++;
          fail_validation_or_restart(link, now_ms);
        }
      }
      break;
    case OtisGnssLinkState::ObserveConfiguredOutput:
      if (link->output_unexpected_sentence_mask != 0u) {
        link->configuration_failure_count++;
        fail_validation_or_restart(link, now_ms);
      } else if (elapsed_at_least(now_ms, link->state_started_ms,
                                  link->policy.output_observation_ms)) {
        if ((link->output_observed_sentence_mask & kGnssRequiredOutputMask) ==
            kGnssRequiredOutputMask) {
          link->output_observation_success_count++;
#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION && \
    OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD
          if (link->nmea_observation_active) {
            copy_field(link->output_configuration_signature,
                       sizeof(link->output_configuration_signature),
                       kGnssObservedExtendedOutputSignature);
            establish_online_link(
                link, now_ms,
                OtisGnssOutputConfirmationMethod::
                    RetainedBaudNmeaObservedExact);
            break;
          }
#endif
          establish_online_link(
              link, now_ms,
              OtisGnssOutputConfirmationMethod::Pmtk314AckObservedExact);
        } else {
          link->configuration_failure_count++;
          fail_validation_or_restart(link, now_ms);
        }
      }
      break;
    case OtisGnssLinkState::Online:
      if (link->valid_frame_seen &&
          elapsed_at_least(now_ms, link->last_valid_frame_ms,
                           link->policy.link_loss_ms))
        restart_discovery(link, now_ms, true);
      break;
    default:
      break;
  }
}

void otis_gnss_link_feed(OtisGnssLink *link, char byte, uint32_t now_ms) {
  if (link == nullptr || !link->service_initialized) return;
  if (byte == '$') {
    link->collecting = true;
    link->discarding_oversize = false;
    link->line_length = 0u;
    link->line[link->line_length++] = byte;
    return;
  }
  if (byte == '\r') return;
  if (byte == '\n') {
    if (link->discarding_oversize) {
      reset_link_line(link);
      return;
    }
    if (link->collecting) process_link_line(link, now_ms);
    reset_link_line(link);
    return;
  }
  if (!link->collecting || link->discarding_oversize) return;
  if (link->line_length >= kOtisGnssDiscoveryMaximumLineBytes - 1u) {
    link->oversize_count++;
    link->discarding_oversize = true;
    link->collecting = false;
    link->line_length = 0u;
    return;
  }
  link->line[link->line_length++] = byte;
}

void otis_gnss_link_note_collector_loss(OtisGnssLink *link) {
  if (link == nullptr || !link->service_initialized) return;
  link->raw_acquisition_loss_count++;
  reset_link_line(link);
}

void otis_gnss_link_note_baud_epoch_boundary(OtisGnssLink *link) {
  if (link == nullptr || !link->service_initialized) return;
  reset_link_line(link);
  if (link->state == OtisGnssLinkState::AwaitTargetBaudEpochBoundary) {
#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION && \
    OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD
    link->output_observed_sentence_mask = 0u;
    link->output_unexpected_sentence_mask = 0u;
#endif
    queue_identity_query(link, true);
  }
}

bool otis_gnss_link_take_action(OtisGnssLink *link,
                                OtisGnssLinkAction *action) {
  if (link == nullptr || action == nullptr || !link->action_pending ||
      link->action_in_progress)
    return false;
  *action = {};
  action->kind = link->pending_action;
  switch (action->kind) {
    case OtisGnssLinkActionKind::SetUartBaud:
      action->baud = link->pending_baud;
      break;
    case OtisGnssLinkActionKind::TransmitIdentityQuery:
      action->bytes = kGnssIdentityQuery;
      action->length = sizeof(kGnssIdentityQuery) - 1u;
      break;
    case OtisGnssLinkActionKind::TransmitTargetBaud:
      action->bytes = fixed_target_baud_command(link->policy.target_baud,
                                                &action->length);
      if (action->bytes == nullptr || action->length == 0u) return false;
      break;
    case OtisGnssLinkActionKind::TransmitOutputQuery:
      action->bytes = kGnssOutputQuery;
      action->length = sizeof(kGnssOutputQuery) - 1u;
      break;
    case OtisGnssLinkActionKind::TransmitOutputConfiguration:
      action->bytes = kGnssOutputConfiguration;
      action->length = sizeof(kGnssOutputConfiguration) - 1u;
      break;
    default:
      return false;
  }
  link->action_pending = false;
  link->action_in_progress = true;
  return true;
}

void otis_gnss_link_complete_action(OtisGnssLink *link, bool success,
                                    uint32_t now_ms) {
  if (link == nullptr || !link->action_in_progress) return;
  const OtisGnssLinkActionKind action = link->pending_action;
  link->action_in_progress = false;
  link->pending_action = OtisGnssLinkActionKind::None;
  if (!success) {
    if (action != OtisGnssLinkActionKind::SetUartBaud)
      link->transmit_failure_count++;
    fail_validation_or_restart(link, now_ms);
    return;
  }

  switch (link->state) {
    case OtisGnssLinkState::SelectCandidateBaud:
      reset_link_line(link);
#if !OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION && \
    OTIS_GNSS_UART_BAUD == 115200u
      queue_link_action(link, OtisGnssLinkState::TransmitTargetBaud,
                        OtisGnssLinkActionKind::TransmitTargetBaud);
#else
      link->state = OtisGnssLinkState::PassiveListen;
      link->state_started_ms = now_ms;
#endif
      break;
    case OtisGnssLinkState::TransmitIdentityQuery:
      link->state = OtisGnssLinkState::AwaitIdentityResponse;
      link->state_started_ms = now_ms;
      break;
    case OtisGnssLinkState::TransmitTargetBaud:
#if !OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION && \
    OTIS_GNSS_UART_BAUD == 115200u
      if (link->candidate_index + 1u <
          kGnssOperationalBootstrapBaudCount) {
        link->candidate_index++;
        link->candidate_baud =
            kGnssOperationalBootstrapBauds[link->candidate_index];
        link->pending_baud = link->candidate_baud;
        queue_link_action(link, OtisGnssLinkState::SelectCandidateBaud,
                          OtisGnssLinkActionKind::SetUartBaud);
        break;
      }
#endif
      link->pending_baud = link->policy.target_baud;
      queue_link_action(link, OtisGnssLinkState::SelectTargetBaud,
                        OtisGnssLinkActionKind::SetUartBaud);
      break;
    case OtisGnssLinkState::SelectTargetBaud:
      link->candidate_baud = link->policy.target_baud;
      reset_link_line(link);
#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION
      link->state = OtisGnssLinkState::AwaitTargetBaudEpochBoundary;
      link->state_started_ms = now_ms;
#else
      queue_identity_query(link, true);
#endif
      break;
    case OtisGnssLinkState::TransmitTargetIdentityQuery:
      link->state = OtisGnssLinkState::AwaitTargetIdentityResponse;
      link->state_started_ms = now_ms;
      break;
    case OtisGnssLinkState::TransmitOutputQuery:
      link->state = OtisGnssLinkState::AwaitOutputResponse;
      link->state_started_ms = now_ms;
      break;
    case OtisGnssLinkState::TransmitOutputConfiguration:
      link->state = OtisGnssLinkState::AwaitOutputConfigurationAck;
      link->state_started_ms = now_ms;
      break;
    case OtisGnssLinkState::TransmitOutputVerificationQuery:
      link->state = OtisGnssLinkState::AwaitOutputVerificationResponse;
      link->state_started_ms = now_ms;
      break;
    default:
      fail_validation_or_restart(link, now_ms);
      break;
  }
}

bool otis_gnss_link_online(const OtisGnssLink *link) {
  return link != nullptr && link->service_initialized &&
         link->state == OtisGnssLinkState::Online &&
         link->configuration_confirmed &&
         link->confirmed_baud == link->policy.target_baud;
}

bool otis_gnss_link_runtime_rx_only(const OtisGnssLink *link) {
  return otis_gnss_link_online(link) && !link->action_pending &&
         !link->action_in_progress;
}

bool otis_gnss_link_discovery_degraded(const OtisGnssLink *link,
                                       uint32_t now_ms) {
  return link != nullptr && link->service_initialized &&
         !otis_gnss_link_online(link) &&
         elapsed_at_least(now_ms, link->discovery_started_ms,
                          link->policy.degraded_after_ms);
}

const char *otis_gnss_link_state_name(const OtisGnssLink *link,
                                      uint32_t now_ms) {
  if (link == nullptr || !link->service_initialized) return "disabled";
  if (otis_gnss_link_online(link)) return "online";
  if (link->link_loss_count > 0u) return "lost";
  if (otis_gnss_link_discovery_degraded(link, now_ms)) return "degraded";
  if (link->state >= OtisGnssLinkState::TransmitTargetBaud)
    return "validating";
  return "discovering";
}

const char *otis_gnss_link_phase_name(const OtisGnssLink *link) {
  if (link == nullptr || !link->service_initialized) return "disabled";
  switch (link->state) {
    case OtisGnssLinkState::SelectCandidateBaud:
      return "select_candidate_baud";
    case OtisGnssLinkState::PassiveListen:
      return "passive_listen";
    case OtisGnssLinkState::TransmitIdentityQuery:
      return "transmit_identity_query";
    case OtisGnssLinkState::AwaitIdentityResponse:
      return "await_identity_response";
    case OtisGnssLinkState::TransmitTargetBaud:
      return "transmit_target_baud";
    case OtisGnssLinkState::SelectTargetBaud:
      return "select_target_baud";
    case OtisGnssLinkState::TransmitTargetIdentityQuery:
      return "transmit_target_identity_query";
    case OtisGnssLinkState::AwaitTargetIdentityResponse:
      return "await_target_identity_response";
    case OtisGnssLinkState::TransmitOutputQuery:
      return "transmit_output_query";
    case OtisGnssLinkState::AwaitOutputResponse:
      return "await_output_response";
    case OtisGnssLinkState::TransmitOutputConfiguration:
      return "transmit_output_configuration";
    case OtisGnssLinkState::AwaitOutputConfigurationAck:
      return "await_output_configuration_ack";
    case OtisGnssLinkState::TransmitOutputVerificationQuery:
      return "transmit_output_verification_query";
    case OtisGnssLinkState::AwaitOutputVerificationResponse:
      return "await_output_verification_response";
    case OtisGnssLinkState::ObserveConfiguredOutput:
      return "observe_configured_output";
    case OtisGnssLinkState::Online:
      return "online";
    case OtisGnssLinkState::AwaitTargetBaudEpochBoundary:
      return "await_target_baud_epoch_boundary";
  }
  return "unknown";
}

const char *otis_gnss_output_confirmation_method_name(
    const OtisGnssLink *link) {
  if (link == nullptr) return "none";
  switch (link->output_confirmation_method) {
    case OtisGnssOutputConfirmationMethod::Pmtk514Exact:
      return "pmtk514_exact";
    case OtisGnssOutputConfirmationMethod::Pmtk314AckObservedExact:
      return "pmtk314_ack_observed_exact";
    case OtisGnssOutputConfirmationMethod::RetainedBaudNmeaObservedExact:
      return "retained_baud_nmea_observed_exact";
    case OtisGnssOutputConfirmationMethod::None:
      return "none";
  }
  return "unknown";
}

const char *otis_gnss_startup_hint_identity_outcome_name(
    OtisGnssStartupHintIdentityOutcome outcome) {
  switch (outcome) {
    case OtisGnssStartupHintIdentityOutcome::NotAttempted:
      return "not_attempted";
    case OtisGnssStartupHintIdentityOutcome::Pending:
      return "pending";
    case OtisGnssStartupHintIdentityOutcome::Confirmed:
      return "confirmed";
    case OtisGnssStartupHintIdentityOutcome::TimedOut:
      return "timed_out";
    case OtisGnssStartupHintIdentityOutcome::TransmitFailed:
      return "transmit_failed";
  }
  return "unknown";
}

const char *otis_gnss_initial_discovery_outcome_name(
    OtisGnssInitialDiscoveryOutcome outcome) {
  switch (outcome) {
    case OtisGnssInitialDiscoveryOutcome::Pending:
      return "pending";
    case OtisGnssInitialDiscoveryOutcome::HintConfirmed:
      return "hint_confirmed";
    case OtisGnssInitialDiscoveryOutcome::FallbackConfirmed:
      return "fallback_confirmed";
  }
  return "unknown";
}

void otis_gnss_receiver_reset(OtisGnssReceiver *receiver, uint32_t now_ms) {
  if (receiver == nullptr) return;
  *receiver = {};
  receiver->initialized = true;
  receiver->rx_only = true;
  receiver->identity_epoch = 1u;
  receiver->last_message_ms = now_ms;
}

void otis_gnss_receiver_set_fault_context(
    OtisGnssReceiver *receiver,
    const OtisGnssParserFaultContext *context) {
  if (receiver == nullptr || context == nullptr) return;
  receiver->fault_context = *context;
}

void otis_gnss_receiver_note_collector_loss(
    OtisGnssReceiver *receiver, uint32_t now_ms,
    OtisGnssParserFaultClass fault_class) {
  otis_gnss_receiver_note_collector_loss_at_ticks(
      receiver, now_ms,
      static_cast<uint64_t>(now_ms) *
          (kOtisGnssRp2040Timer0TicksPerSecond / 1000u),
      fault_class);
}

void otis_gnss_receiver_note_collector_loss_at_ticks(
    OtisGnssReceiver *receiver, uint32_t now_ms,
    uint64_t service_extended_ticks,
    OtisGnssParserFaultClass fault_class) {
  if (receiver == nullptr || !receiver->initialized) return;
  receiver->raw_acquisition_loss_count++;
  note_parser_fault(receiver, now_ms, service_extended_ticks, fault_class);
  receiver->collecting = false;
  receiver->discarding_oversize = false;
  receiver->line_length = 0u;
}

void otis_gnss_receiver_feed(OtisGnssReceiver *receiver, char byte,
                             uint32_t now_ms) {
  otis_gnss_receiver_feed_at_ticks(
      receiver, byte, now_ms,
      static_cast<uint64_t>(now_ms) *
          (kOtisGnssRp2040Timer0TicksPerSecond / 1000u));
}

void otis_gnss_receiver_feed_at_ticks(OtisGnssReceiver *receiver, char byte,
                                      uint32_t now_ms,
                                      uint64_t service_extended_ticks) {
  if (receiver == nullptr || !receiver->initialized) return;
  if (byte == '$') {
    if (receiver->collecting && receiver->line_length > 0u) {
      receiver->truncated_count++;
      note_parser_fault(receiver, now_ms, service_extended_ticks,
                        OtisGnssParserFaultClass::DelimiterBeforeNewline);
    }
    receiver->collecting = true;
    receiver->discarding_oversize = false;
    receiver->line_length = 0u;
    receiver->line[receiver->line_length++] = byte;
    return;
  }
  if (byte == '\r') return;
  if (byte == '\n') {
    if (receiver->discarding_oversize) {
      receiver->discarding_oversize = false;
      receiver->collecting = false;
      receiver->line_length = 0u;
      return;
    }
    if (receiver->collecting)
      parse_complete_line(receiver, now_ms, service_extended_ticks);
    receiver->collecting = false;
    receiver->line_length = 0u;
    return;
  }
  if (!receiver->collecting || receiver->discarding_oversize) return;
  if (receiver->line_length >= kOtisGnssMaximumLineBytes - 1u) {
    receiver->oversize_count++;
    note_parser_fault(receiver, now_ms, service_extended_ticks,
                      OtisGnssParserFaultClass::Oversize);
    receiver->discarding_oversize = true;
    receiver->collecting = false;
    receiver->line_length = 0u;
    return;
  }
  receiver->line[receiver->line_length++] = byte;
}

void otis_gnss_receiver_note_time(OtisGnssReceiver *receiver, uint32_t now_ms,
                                  uint32_t reconnect_gap_ms) {
  otis_gnss_receiver_note_time_at_ticks(
      receiver, now_ms,
      static_cast<uint64_t>(now_ms) *
          (kOtisGnssRp2040Timer0TicksPerSecond / 1000u),
      reconnect_gap_ms);
}

void otis_gnss_receiver_note_time_at_ticks(
    OtisGnssReceiver *receiver, uint32_t now_ms,
    uint64_t service_extended_ticks, uint32_t reconnect_gap_ms) {
  if (receiver == nullptr || !receiver->initialized ||
      (!receiver->rmc_seen && !receiver->gga_seen))
    return;
  if (elapsed_at_least(now_ms, receiver->last_message_ms, reconnect_gap_ms))
    if (!receiver->disconnected) {
      receiver->disconnected = true;
      start_metadata_hold(receiver, now_ms, service_extended_ticks);
    }
}

void otis_gnss_receiver_snapshot(const OtisGnssReceiver *receiver,
                                 uint32_t now_ms, uint32_t maximum_age_ms,
                                 OtisGnssReceiverSnapshot *snapshot) {
  if (receiver == nullptr || snapshot == nullptr) return;
  *snapshot = {};
  snapshot->initialized = receiver->initialized;
  snapshot->rx_only = receiver->rx_only;
  snapshot->disconnected = receiver->disconnected;
  snapshot->rmc_seen = receiver->rmc_seen;
  snapshot->gga_seen = receiver->gga_seen;
  snapshot->gsa_seen = receiver->gsa_seen;
  snapshot->rmc_valid = receiver->rmc_valid;
  snapshot->utc_available = receiver->utc_available;
  snapshot->date_available = receiver->date_available;
  snapshot->fix_quality = receiver->fix_quality;
  snapshot->fix_dimension = receiver->fix_dimension;
  snapshot->satellites = receiver->satellites;
  copy_field(snapshot->talker, sizeof(snapshot->talker), receiver->talker);
  copy_field(snapshot->utc, sizeof(snapshot->utc), receiver->utc);
  copy_field(snapshot->date, sizeof(snapshot->date), receiver->date);
  copy_field(snapshot->hdop, sizeof(snapshot->hdop), receiver->hdop);
  snapshot->identity_epoch = receiver->identity_epoch;
  snapshot->checksum_valid_count = receiver->checksum_valid_count;
  snapshot->checksum_failure_count = receiver->checksum_failure_count;
  snapshot->parser_drop_count = receiver->parser_drop_count;
  snapshot->truncated_count = receiver->truncated_count;
  snapshot->oversize_count = receiver->oversize_count;
  snapshot->rmc_count = receiver->rmc_count;
  snapshot->gga_count = receiver->gga_count;
  snapshot->gsa_count = receiver->gsa_count;
  snapshot->raw_acquisition_loss_count =
      receiver->raw_acquisition_loss_count;
  snapshot->last_good_frame_sequence = receiver->last_good_frame_sequence;
  snapshot->minimum_line_length = receiver->minimum_line_length;
  snapshot->maximum_line_length = receiver->maximum_line_length;
  snapshot->minimum_interframe_gap_ms =
      receiver->minimum_interframe_gap_ms;
  snapshot->maximum_interframe_gap_ms =
      receiver->maximum_interframe_gap_ms;
  snapshot->metadata_hold_count = receiver->metadata_hold_count;
  snapshot->metadata_hold_cumulative_ms =
      receiver->metadata_hold_cumulative_ms;
  snapshot->metadata_hold_longest_ms = receiver->metadata_hold_longest_ms;
  snapshot->metadata_recovery_latency_ms =
      receiver->metadata_recovery_latency_ms;
  snapshot->minimum_interframe_gap_ticks =
      receiver->minimum_interframe_gap_ticks;
  snapshot->maximum_interframe_gap_ticks =
      receiver->maximum_interframe_gap_ticks;
  snapshot->metadata_hold_cumulative_ticks =
      receiver->metadata_hold_cumulative_ticks;
  snapshot->metadata_hold_longest_ticks =
      receiver->metadata_hold_longest_ticks;
  snapshot->metadata_recovery_latency_ticks =
      receiver->metadata_recovery_latency_ticks;
  if (receiver->metadata_hold_active) {
    const uint32_t active_duration =
        static_cast<uint32_t>(now_ms - receiver->metadata_hold_started_ms);
    snapshot->metadata_hold_cumulative_ms += active_duration;
    if (active_duration > snapshot->metadata_hold_longest_ms)
      snapshot->metadata_hold_longest_ms = active_duration;
    // Host-test callers use the exact 16 MHz projection of now_ms. Live
    // callers finish active-duration accounting from the service extension.
    const uint64_t snapshot_ticks =
        static_cast<uint64_t>(now_ms) *
        (kOtisGnssRp2040Timer0TicksPerSecond / 1000u);
    if (snapshot_ticks >= receiver->metadata_hold_started_ticks) {
      const uint64_t active_ticks =
          snapshot_ticks - receiver->metadata_hold_started_ticks;
      snapshot->metadata_hold_cumulative_ticks += active_ticks;
      if (active_ticks > snapshot->metadata_hold_longest_ticks)
        snapshot->metadata_hold_longest_ticks = active_ticks;
    }
  }
  snapshot->fault_capsule_count = receiver->fault_capsule_count;
  snapshot->fault_capsule_dropped_count =
      receiver->fault_capsule_dropped_count;
  for (uint8_t index = 0u; index < receiver->fault_capsule_count; ++index)
    snapshot->fault_capsules[index] = receiver->fault_capsules[index];
  if (receiver->fault_capsule_count != 0u)
    snapshot->latest_fault_capsule =
        receiver->fault_capsules[receiver->fault_capsule_count - 1u];

  const bool rmc_fresh = receiver->rmc_seen &&
                         !elapsed_at_least(now_ms, receiver->last_rmc_ms,
                                           maximum_age_ms + 1u);
  const bool gga_fresh = receiver->gga_seen &&
                         !elapsed_at_least(now_ms, receiver->last_gga_ms,
                                           maximum_age_ms + 1u);
  snapshot->gsa_fresh =
      receiver->gsa_seen &&
      !elapsed_at_least(now_ms, receiver->last_gsa_ms, maximum_age_ms + 1u);
  snapshot->gsa_3d = snapshot->gsa_fresh && receiver->fix_dimension == 3u;
  snapshot->gsa_checksum_requalified =
      receiver->gsa_seen &&
      receiver->gsa_repair_epoch == receiver->parser_fault_epoch;
  snapshot->metadata_fresh = rmc_fresh && gga_fresh && !receiver->disconnected;
  snapshot->checksum_requalified =
      receiver->rmc_repair_epoch == receiver->parser_fault_epoch &&
      receiver->gga_repair_epoch == receiver->parser_fault_epoch;
  // An outage longer than the reconnect gap starts a new receiver identity
  // epoch. The active programme must explicitly begin a fresh run before that
  // identity can become authoritative; ordinary short fix loss can recover
  // after fresh checksum-valid RMC and GGA messages.
  snapshot->identity_stable = receiver->identity_epoch == 1u;
  if (receiver->rmc_seen || receiver->gga_seen) {
    const uint32_t rmc_age = receiver->rmc_seen
                                 ? static_cast<uint32_t>(now_ms - receiver->last_rmc_ms)
                                 : UINT32_MAX;
    const uint32_t gga_age = receiver->gga_seen
                                 ? static_cast<uint32_t>(now_ms - receiver->last_gga_ms)
                                 : UINT32_MAX;
    snapshot->metadata_age_ms = rmc_age > gga_age ? rmc_age : gga_age;
  } else {
    snapshot->metadata_age_ms = UINT32_MAX;
  }
  snapshot->control_eligible =
      snapshot->initialized && snapshot->rx_only &&
      snapshot->metadata_fresh && snapshot->checksum_requalified &&
      snapshot->rmc_valid && snapshot->fix_quality > 0u &&
      snapshot->satellites > 0u && snapshot->utc_available &&
      snapshot->date_available && snapshot->identity_stable;
}

namespace {

#if OTIS_GNSS_BAUD_CHARACTERIZATION_RESUME
constexpr uint32_t kCharacterizationScheduleBauds[] = {
    115200u, 9600u,
};
#elif OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD
constexpr uint32_t kCharacterizationScheduleBauds[] = {
    57600u, 38400u, 19200u, 9600u, 115200u, 9600u,
};
#else
constexpr uint32_t kCharacterizationScheduleBauds[] = {
    9600u, 19200u, 38400u, 57600u, 115200u, 57600u,
    38400u, 19200u, 9600u, 115200u, 9600u,
};
#endif

bool characterization_baud_allowed(uint32_t baud) {
  return baud == 9600u || baud == 19200u || baud == 38400u ||
         baud == 57600u || baud == 115200u;
}

bool parse_decimal_u32_token(const char *token, uint32_t *value) {
  if (token == nullptr || value == nullptr || *token == '\0') return false;
  uint32_t parsed = 0u;
  for (const char *cursor = token; *cursor != '\0'; ++cursor) {
    if (*cursor < '0' || *cursor > '9') return false;
    const uint32_t digit = static_cast<uint32_t>(*cursor - '0');
    if (parsed > (UINT32_MAX - digit) / 10u) return false;
    parsed = parsed * 10u + digit;
  }
  *value = parsed;
  return true;
}

bool parse_segment_token(const char *token, uint8_t *ordinal) {
  if (token == nullptr || ordinal == nullptr || strlen(token) != 3u ||
      token[0] != 'S' || token[1] < '0' || token[1] > '9' ||
      token[2] < '0' || token[2] > '9')
    return false;
  const uint8_t parsed = static_cast<uint8_t>(
      static_cast<uint8_t>(token[1] - '0') * 10u +
      static_cast<uint8_t>(token[2] - '0'));
  if (parsed < 1u || parsed > 11u) return false;
  *ordinal = parsed;
  return true;
}

bool split_exact_space_tokens(const char *text, char *storage,
                              size_t storage_capacity, char **tokens,
                              size_t expected_count) {
  if (text == nullptr || storage == nullptr || tokens == nullptr ||
      expected_count == 0u)
    return false;
  const size_t length = strlen(text);
  if (length == 0u || length >= storage_capacity || text[0] == ' ' ||
      text[length - 1u] == ' ')
    return false;
  memcpy(storage, text, length + 1u);
  size_t count = 0u;
  char *cursor = storage;
  while (*cursor != '\0') {
    if (count >= expected_count) return false;
    tokens[count++] = cursor;
    while (*cursor != '\0' && *cursor != ' ') {
      if (*cursor == '\t' || static_cast<unsigned char>(*cursor) < 0x20u)
        return false;
      cursor++;
    }
    if (*cursor == '\0') break;
    *cursor++ = '\0';
    if (*cursor == '\0' || *cursor == ' ') return false;
  }
  return count == expected_count;
}

}  // namespace

bool otis_gnss_parse_baud_transition_request(
    const char *arguments, OtisGnssBaudTransitionRequest *request) {
  if (request == nullptr) return false;
  *request = {};
  char storage[160] = {};
  char *tokens[6] = {};
  if (!split_exact_space_tokens(arguments, storage, sizeof(storage), tokens,
                                6u) ||
      strcmp(tokens[0], kOtisGnssBaudCharacterizationProgrammeId) != 0 ||
      !parse_decimal_u32_token(tokens[1], &request->request_sequence) ||
      request->request_sequence == 0u ||
      !parse_segment_token(tokens[2], &request->segment_ordinal) ||
      !parse_decimal_u32_token(tokens[3], &request->source_baud) ||
      !parse_decimal_u32_token(tokens[4], &request->source_baud_epoch) ||
      request->source_baud_epoch == 0u ||
      !parse_decimal_u32_token(tokens[5], &request->target_baud) ||
      !characterization_baud_allowed(request->source_baud) ||
      !characterization_baud_allowed(request->target_baud))
    return false;
  return request->target_baud ==
         kCharacterizationScheduleBauds[request->segment_ordinal - 1u];
}

bool otis_gnss_parse_status_challenge_request(
    const char *arguments, OtisGnssStatusChallengeRequest *request) {
  if (request == nullptr) return false;
  *request = {};
  char storage[144] = {};
  char *tokens[4] = {};
  return split_exact_space_tokens(arguments, storage, sizeof(storage), tokens,
                                  4u) &&
         strcmp(tokens[0], kOtisGnssBaudCharacterizationProgrammeId) == 0 &&
         parse_decimal_u32_token(tokens[1], &request->challenge_sequence) &&
         request->challenge_sequence != 0u &&
         parse_segment_token(tokens[2], &request->segment_ordinal) &&
         parse_decimal_u32_token(tokens[3], &request->baud_epoch) &&
         request->baud_epoch != 0u;
}

bool otis_gnss_completed_peak_prepare_next(
    OtisGnssCompletedPeakRetention *retention,
    uint32_t current_challenge_sequence,
    uint32_t requested_challenge_sequence) {
  if (retention == nullptr ||
      requested_challenge_sequence != current_challenge_sequence + 1u)
    return false;
  if (!retention->available) return true;
  if (retention->challenge_sequence != current_challenge_sequence)
    return false;
  *retention = {};
  return true;
}

bool otis_gnss_completed_peak_publish(
    OtisGnssCompletedPeakRetention *retention,
    uint32_t completed_challenge_sequence) {
  if (retention == nullptr || completed_challenge_sequence == 0u ||
      retention->available)
    return false;
  retention->available = true;
  retention->challenge_sequence = completed_challenge_sequence;
  return true;
}

const char *otis_gnss_observation_phase_name(OtisGnssObservationPhase phase) {
  switch (phase) {
    case OtisGnssObservationPhase::Discovery:
      return "discovery";
    case OtisGnssObservationPhase::PlannedTransition:
      return "planned_transition";
    case OtisGnssObservationPhase::Recovery:
      return "recovery";
    case OtisGnssObservationPhase::OrdinaryOnline:
      return "ordinary_online";
    case OtisGnssObservationPhase::PeakLoad:
      return "peak_load";
  }
  return "unknown";
}

const char *otis_gnss_transition_state_name(OtisGnssTransitionState state) {
  switch (state) {
    case OtisGnssTransitionState::Idle:
      return "idle";
    case OtisGnssTransitionState::Targeting:
      return "targeting";
    case OtisGnssTransitionState::AwaitFreshMetadata:
      return "await_fresh_metadata";
    case OtisGnssTransitionState::Complete:
      return "complete";
    case OtisGnssTransitionState::RecoveryScanning:
      return "recovery_scanning";
    case OtisGnssTransitionState::Recovered:
      return "recovered";
    case OtisGnssTransitionState::Unrecoverable:
      return "unrecoverable";
    case OtisGnssTransitionState::PlatformFault:
      return "platform_fault";
  }
  return "unknown";
}

const char *otis_gnss_request_disposition_name(
    OtisGnssRequestDisposition disposition) {
  switch (disposition) {
    case OtisGnssRequestDisposition::Accepted:
      return "accepted";
    case OtisGnssRequestDisposition::Duplicate:
      return "duplicate";
    case OtisGnssRequestDisposition::RejectedDisabled:
      return "rejected_disabled";
    case OtisGnssRequestDisposition::RejectedParse:
      return "rejected_parse";
    case OtisGnssRequestDisposition::RejectedIdentity:
      return "rejected_identity";
    case OtisGnssRequestDisposition::RejectedBusy:
      return "rejected_busy";
    case OtisGnssRequestDisposition::RejectedStale:
      return "rejected_stale";
    case OtisGnssRequestDisposition::RejectedSkipped:
      return "rejected_skipped";
    case OtisGnssRequestDisposition::RejectedContradictory:
      return "rejected_contradictory";
    case OtisGnssRequestDisposition::RejectedSource:
      return "rejected_source";
    case OtisGnssRequestDisposition::RejectedTarget:
      return "rejected_target";
    case OtisGnssRequestDisposition::RejectedPhase:
      return "rejected_phase";
  }
  return "unknown";
}

const char *otis_gnss_parser_fault_class_name(
    OtisGnssParserFaultClass fault_class) {
  switch (fault_class) {
    case OtisGnssParserFaultClass::None:
      return "none";
    case OtisGnssParserFaultClass::RawAcquisitionLoss:
      return "raw_acquisition_loss";
    case OtisGnssParserFaultClass::DelimiterBeforeNewline:
      return "delimiter_before_newline";
    case OtisGnssParserFaultClass::LineShape:
      return "line_shape";
    case OtisGnssParserFaultClass::Checksum:
      return "checksum";
    case OtisGnssParserFaultClass::FieldShape:
      return "field_shape";
    case OtisGnssParserFaultClass::Oversize:
      return "oversize";
  }
  return "unknown";
}

#if !defined(OTIS_GNSS_HOST_TEST)

#include <Arduino.h>
#include <hardware/gpio.h>
#include <hardware/irq.h>
#include <hardware/regs/uart.h>
#include <hardware/structs/timer.h>
#include <hardware/uart.h>
#include <pico/platform.h>

#include "otis_board.h"
#include "otis_timebase_math.h"
namespace {
OtisGnssReceiver live_receiver = {};
OtisGnssLink live_link = {};
OtisGnssUartRxRing live_uart_rx_ring = {};
bool live_receiver_started = false;
bool live_uart_initialized = false;
bool live_uart_irq_installed = false;
uint32_t live_pmtk605_peripheral_complete_count = 0u;
uint64_t live_pmtk605_last_peripheral_complete_ticks = 0u;
bool live_pmtk605_last_peripheral_complete_ticks_available = false;

struct LiveGnssCharacterization {
  OtisGnssObservationPhase observation_phase;
  OtisGnssTransitionState transition_state;
  OtisGnssRequestDisposition last_request_disposition;
  OtisGnssBaudTransitionRequest request;
  bool request_available;
  uint32_t baud_epoch;
  uint32_t accepted_ms;
  bool target_epoch_opened;
  bool recovery_epoch_opened;
  uint32_t recovery_started_ms;
  uint32_t identity_response_baseline;
  uint32_t rmc_baseline;
  uint32_t gga_baseline;
  uint32_t gsa_baseline;
  uint32_t recovered_baud;
  uint32_t evidence_frontier;
  bool target_command_transmit_complete;
  bool target_identity_confirmed;
  bool target_output_confirmed;
  uint32_t target_command_transmit_elapsed_ms;
  uint32_t target_identity_elapsed_ms;
  uint32_t target_output_elapsed_ms;
  uint32_t transition_complete_elapsed_ms;
  uint32_t recovery_started_elapsed_ms;
  uint32_t recovery_terminal_elapsed_ms;
  bool first_dependent_snapshot;
  bool platform_fault;
  uint32_t accepted_count;
  uint32_t duplicate_count;
  uint32_t rejected_count;
  uint32_t completed_count;
  uint32_t recovered_count;
  uint32_t unrecoverable_count;
  OtisGnssUartRxStats phase_uart_baseline;
  char receiver_release_at_accept[kOtisGnssReleaseMaximumBytes];
  char output_signature_at_accept[kOtisGnssOutputSignatureMaximumBytes];
  bool status_challenge_active;
  bool status_challenge_phase_snapshot_pending;
  OtisGnssStatusChallengeRequest status_challenge;
  uint32_t status_challenge_completed_count;
  OtisGnssRequestDisposition last_status_request_disposition;
  OtisGnssStatusChallengeRequest last_status_request;
  OtisGnssCompletedPeakRetention completed_peak_retention;
  OtisGnssUartRxStats completed_peak_uart;
};

LiveGnssCharacterization live_characterization = {};
uint64_t live_service_timer0_raw_ticks = 0u;
uint64_t live_service_timer0_extended_ticks = 0u;
bool live_service_timer0_extension_available = false;

struct LiveGnssTransmit {
  bool active;
  const char *bytes;
  size_t length;
  size_t index;
  uint32_t started_ms;
};

LiveGnssTransmit live_transmit = {};

bool same_transition_request(const OtisGnssBaudTransitionRequest &first,
                             const OtisGnssBaudTransitionRequest &second) {
  return first.request_sequence == second.request_sequence &&
         first.segment_ordinal == second.segment_ordinal &&
         first.source_baud == second.source_baud &&
         first.source_baud_epoch == second.source_baud_epoch &&
         first.target_baud == second.target_baud;
}

void format_segment_id(uint8_t ordinal,
                       char output[kOtisGnssSegmentIdMaximumBytes]) {
  if (ordinal < 1u || ordinal > 11u) {
    memcpy(output, "none", kOtisGnssSegmentIdMaximumBytes);
    return;
  }
  output[0] = 'S';
  output[1] = static_cast<char>('0' + ordinal / 10u);
  output[2] = static_cast<char>('0' + ordinal % 10u);
  output[3] = '\0';
}

void close_collectors_for_planned_transition() {
  reset_link_line(&live_link);
  live_receiver.collecting = false;
  live_receiver.discarding_oversize = false;
  live_receiver.line_length = 0u;
}

void set_characterization_platform_fault() {
  live_characterization.platform_fault = true;
  live_characterization.transition_state = OtisGnssTransitionState::PlatformFault;
}

void capture_characterization_phase_uart_baseline() {
  const bool uart_irq_enabled = irq_is_enabled(UART0_IRQ);
  if (uart_irq_enabled) irq_set_enabled(UART0_IRQ, false);
  otis_gnss_uart_rx_ring_reset_phase_window(&live_uart_rx_ring);
  otis_gnss_uart_rx_ring_snapshot(&live_uart_rx_ring,
                                  &live_characterization.phase_uart_baseline);
  if (uart_irq_enabled) irq_set_enabled(UART0_IRQ, true);
}

void begin_characterization_recovery(uint32_t now_ms) {
  live_characterization.transition_state =
      OtisGnssTransitionState::RecoveryScanning;
  live_characterization.observation_phase = OtisGnssObservationPhase::Recovery;
  live_characterization.recovery_started_ms = now_ms;
  live_characterization.recovery_started_elapsed_ms =
      static_cast<uint32_t>(now_ms - live_characterization.accepted_ms);
  live_characterization.recovery_epoch_opened = false;
  live_characterization.identity_response_baseline =
      live_link.identity_response_count;
  live_characterization.rmc_baseline = live_receiver.rmc_count;
  live_characterization.gga_baseline = live_receiver.gga_count;
  live_characterization.gsa_baseline = live_receiver.gsa_count;
  live_link.characterization_targeting = false;
  live_link.characterization_target_failed = false;
  live_link.characterization_recovery_scan = true;
  live_link.characterization_recovery_scan_exhausted = false;
  capture_characterization_phase_uart_baseline();
  restart_discovery(&live_link, now_ms, false);
}

bool characterization_metadata_frontier_ready() {
  return live_receiver.rmc_count > live_characterization.rmc_baseline &&
         live_receiver.gga_count > live_characterization.gga_baseline &&
         static_cast<uint32_t>(live_receiver.gsa_count -
                               live_characterization.gsa_baseline) >= 2u &&
         live_receiver.rmc_repair_epoch == live_receiver.parser_fault_epoch &&
         live_receiver.gga_repair_epoch == live_receiver.parser_fault_epoch &&
         live_receiver.gsa_repair_epoch == live_receiver.parser_fault_epoch;
}

bool retained_startup_attachment_metadata_ready(uint32_t now_ms) {
  OtisGnssReceiverSnapshot metadata = {};
  otis_gnss_receiver_snapshot(&live_receiver, now_ms,
                              OTIS_GNSS_METADATA_MAX_AGE_MS, &metadata);
  return metadata.metadata_fresh && metadata.checksum_requalified &&
         metadata.gsa_fresh && metadata.gsa_checksum_requalified;
}

bool characterization_identity_unchanged() {
  return strcmp(live_characterization.receiver_release_at_accept,
                live_link.receiver_release) == 0 &&
         strcmp(live_characterization.output_signature_at_accept,
                live_link.output_configuration_signature) == 0;
}

void service_characterization_transaction(uint32_t now_ms) {
#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION
  if (live_characterization.platform_fault ||
      !live_characterization.request_available)
    return;

  if (live_characterization.transition_state ==
      OtisGnssTransitionState::Targeting) {
    if (!live_characterization.target_epoch_opened &&
        live_link.candidate_baud == live_characterization.request.target_baud &&
        (live_link.state == OtisGnssLinkState::TransmitTargetIdentityQuery ||
         live_link.state == OtisGnssLinkState::AwaitTargetIdentityResponse ||
         live_link.state >= OtisGnssLinkState::TransmitOutputQuery)) {
      live_characterization.baud_epoch++;
      if (live_characterization.baud_epoch == 0u)
        live_characterization.baud_epoch = 1u;
      live_characterization.target_epoch_opened = true;
    }
    const bool target_identity_confirmed =
        live_link.identity_response_count >
            live_characterization.identity_response_baseline &&
        live_link.last_identity_response_baud ==
            live_characterization.request.target_baud;
    if (target_identity_confirmed &&
        !live_characterization.target_identity_confirmed) {
      live_characterization.target_identity_confirmed = true;
      live_characterization.target_identity_elapsed_ms =
          static_cast<uint32_t>(now_ms - live_characterization.accepted_ms);
    }
    const bool target_identity_and_output_confirmed =
        target_identity_confirmed && otis_gnss_link_online(&live_link) &&
        live_link.configuration_confirmed &&
        live_link.confirmed_baud == live_characterization.request.target_baud;
    if (live_link.characterization_target_failed ||
        (!target_identity_and_output_confirmed &&
         elapsed_at_least(now_ms, live_characterization.accepted_ms,
                          10000u)) ||
        elapsed_at_least(now_ms, live_characterization.accepted_ms, 30000u)) {
      begin_characterization_recovery(now_ms);
      return;
    }
    if (otis_gnss_link_online(&live_link) &&
        live_link.confirmed_baud ==
            live_characterization.request.target_baud) {
      if (!live_characterization.target_output_confirmed) {
        live_characterization.target_output_confirmed = true;
        live_characterization.target_output_elapsed_ms =
            static_cast<uint32_t>(now_ms - live_characterization.accepted_ms);
      }
      if (!characterization_identity_unchanged()) {
        set_characterization_platform_fault();
        return;
      }
      live_characterization.transition_state =
          OtisGnssTransitionState::AwaitFreshMetadata;
    }
  }

  if (live_characterization.transition_state ==
      OtisGnssTransitionState::AwaitFreshMetadata) {
    if (!otis_gnss_link_online(&live_link) ||
        elapsed_at_least(now_ms, live_characterization.accepted_ms,
                         30000u)) {
      begin_characterization_recovery(now_ms);
      return;
    }
    if (characterization_metadata_frontier_ready()) {
      live_characterization.transition_state =
          OtisGnssTransitionState::Complete;
      live_characterization.observation_phase =
          OtisGnssObservationPhase::OrdinaryOnline;
      live_characterization.completed_count++;
      live_characterization.evidence_frontier =
          live_receiver.last_good_frame_sequence;
      live_characterization.transition_complete_elapsed_ms =
          static_cast<uint32_t>(now_ms - live_characterization.accepted_ms);
      live_characterization.first_dependent_snapshot = false;
      live_link.characterization_targeting = false;
      capture_characterization_phase_uart_baseline();
    }
  }

  if (live_characterization.transition_state ==
      OtisGnssTransitionState::RecoveryScanning) {
    if (!live_characterization.recovery_epoch_opened &&
        live_link.identity_response_count >
            live_characterization.identity_response_baseline) {
      live_characterization.baud_epoch++;
      if (live_characterization.baud_epoch == 0u)
        live_characterization.baud_epoch = 1u;
      live_characterization.recovery_epoch_opened = true;
      live_characterization.recovered_baud =
          live_link.last_identity_response_baud;
    }
    if (live_link.characterization_recovery_scan_exhausted ||
        elapsed_at_least(now_ms, live_characterization.recovery_started_ms,
                         15000u) ||
        elapsed_at_least(now_ms, live_characterization.accepted_ms, 60000u)) {
      live_characterization.transition_state =
          OtisGnssTransitionState::Unrecoverable;
      live_characterization.unrecoverable_count++;
      live_characterization.recovery_terminal_elapsed_ms =
          static_cast<uint32_t>(now_ms - live_characterization.accepted_ms);
      return;
    }
    if (otis_gnss_link_online(&live_link)) {
      if (!characterization_identity_unchanged()) {
        set_characterization_platform_fault();
        return;
      }
      live_characterization.recovered_baud = live_link.confirmed_baud;
      if (characterization_metadata_frontier_ready()) {
        live_characterization.transition_state =
            OtisGnssTransitionState::Recovered;
        live_characterization.observation_phase =
            OtisGnssObservationPhase::OrdinaryOnline;
        live_characterization.recovered_count++;
        live_characterization.evidence_frontier =
            live_receiver.last_good_frame_sequence;
        live_characterization.recovery_terminal_elapsed_ms =
            static_cast<uint32_t>(now_ms - live_characterization.accepted_ms);
        live_characterization.first_dependent_snapshot = false;
        live_link.characterization_recovery_scan = false;
        capture_characterization_phase_uart_baseline();
      }
    }
  }

  // The completion value is request-causal; after it is established, retain
  // the same monotonic receiver-frame domain and advance it only while the
  // canonical metadata path is freshly checksum-requalified. This permits
  // exact online-duration accumulation without weakening the first dependent
  // transition snapshot.
  if ((live_characterization.transition_state ==
           OtisGnssTransitionState::Complete ||
       live_characterization.transition_state ==
           OtisGnssTransitionState::Recovered) &&
      characterization_metadata_frontier_ready() &&
      live_receiver.last_good_frame_sequence >
          live_characterization.evidence_frontier) {
    live_characterization.evidence_frontier =
        live_receiver.last_good_frame_sequence;
  }
#else
  (void)now_ms;
#endif
}

static inline uint32_t live_timer0_ticks_from_register() {
  return static_cast<uint32_t>(timer_hw->timerawl *
                               OTIS_RP2040_TIMER0_TICKS_PER_US);
}

uint64_t update_live_service_timer0_extension() {
  const uint64_t raw_ticks =
      static_cast<uint64_t>(timer_hw->timerawl) *
      OTIS_RP2040_TIMER0_TICKS_PER_US;
  if (!live_service_timer0_extension_available) {
    live_service_timer0_raw_ticks = raw_ticks;
    live_service_timer0_extended_ticks = raw_ticks;
    live_service_timer0_extension_available = true;
  } else {
    live_service_timer0_extended_ticks += otis_timer0_interval_ticks(
        live_service_timer0_raw_ticks, raw_ticks);
    live_service_timer0_raw_ticks = raw_ticks;
  }
  return live_service_timer0_extended_ticks;
}

void __not_in_flash_func(otis_gnss_uart0_rx_isr)() {
  const uint32_t entry_ticks = live_timer0_ticks_from_register();
  uint32_t drained = 0u;
  uart_hw_t *const hardware = uart_get_hw(uart0);
  while ((hardware->fr & UART_UARTFR_RXFE_BITS) == 0u) {
    const uint32_t data = hardware->dr;
    const OtisGnssUartObservation observation =
        otis_gnss_uart_observation_from_dr(data);
    otis_gnss_uart_rx_ring_push_from_isr(&live_uart_rx_ring, observation);
    drained++;
  }
  const uint32_t exit_ticks = live_timer0_ticks_from_register();
  otis_gnss_uart_rx_ring_note_interrupt_from_isr(
      &live_uart_rx_ring, entry_ticks, exit_ticks, drained);
}

void configure_live_uart(uint32_t baud, bool opening_target_epoch) {
  if (live_uart_initialized) {
    uart_set_irq_enables(uart0, false, false);
    irq_set_enabled(UART0_IRQ, false);
    uart_deinit(uart0);
  }
  uart_init(uart0, baud);
  uart_set_format(uart0, 8u, 1u, UART_PARITY_NONE);
  uart_set_hw_flow(uart0, false, false);
  uart_set_fifo_enabled(uart0, true);
  gpio_set_function(OTIS_PIN_GNSS_RX, GPIO_FUNC_UART);
  gpio_disable_pulls(OTIS_PIN_GNSS_RX);
  gpio_set_function(OTIS_PIN_GNSS_TX, GPIO_FUNC_UART);
  gpio_disable_pulls(OTIS_PIN_GNSS_TX);
  if (!live_uart_irq_installed) {
    irq_set_exclusive_handler(UART0_IRQ, otis_gnss_uart0_rx_isr);
    irq_set_priority(UART0_IRQ, PICO_LOWEST_IRQ_PRIORITY);
    live_uart_irq_installed = true;
  }
  if (opening_target_epoch)
    otis_gnss_uart_rx_ring_mark_baud_epoch(&live_uart_rx_ring);
  uart_set_irq_enables(uart0, true, false);
  irq_set_enabled(UART0_IRQ, true);
  live_uart_initialized = true;
}

void service_live_uart_rx_ring(uint32_t now_ms) {
  const uint32_t entry_ticks = live_timer0_ticks_from_register();
  otis_gnss_uart_rx_ring_note_consumer_start(&live_uart_rx_ring, entry_ticks);

  OtisGnssUartRxStats uart_stats = {};
  otis_gnss_uart_rx_ring_snapshot(&live_uart_rx_ring, &uart_stats);
  const OtisGnssParserFaultContext context = {
      static_cast<uint8_t>(live_characterization.request_available
                               ? live_characterization.request.segment_ordinal
                               : 0u),
      live_characterization.observation_phase,
      live_link.confirmed_baud != 0u ? live_link.confirmed_baud
                                     : live_link.candidate_baud,
      live_characterization.baud_epoch,
      static_cast<uint32_t>(
          uart_stats.hardware_overrun_count -
          live_characterization.phase_uart_baseline.hardware_overrun_count),
      static_cast<uint32_t>(
          uart_stats.hardware_framing_count -
          live_characterization.phase_uart_baseline.hardware_framing_count),
      static_cast<uint32_t>(
          uart_stats.hardware_parity_count -
          live_characterization.phase_uart_baseline.hardware_parity_count),
      static_cast<uint32_t>(
          uart_stats.hardware_break_count -
          live_characterization.phase_uart_baseline.hardware_break_count),
      uart_stats.ring_current_depth,
      uart_stats.phase_window_ring_high_water,
      uart_stats.last_consumer_service_gap_ticks,
  };
  otis_gnss_receiver_set_fault_context(&live_receiver, &context);

  uint32_t drained = 0u;
  bool time_budget_hit = false;
  OtisGnssUartObservation observation;
  while (drained < kOtisGnssUartRxConsumerByteBudget &&
         otis_gnss_uart_rx_ring_pop(&live_uart_rx_ring, &observation)) {
    const bool metadata_path_open =
        otis_gnss_link_online(&live_link) ||
        live_link.state == OtisGnssLinkState::ObserveConfiguredOutput;
    if ((observation.flags & kOtisGnssUartObservationLossBefore) != 0u) {
      otis_gnss_link_note_collector_loss(&live_link);
      if (metadata_path_open)
        otis_gnss_receiver_note_collector_loss_at_ticks(
            &live_receiver, now_ms, live_service_timer0_extended_ticks,
            OtisGnssParserFaultClass::RawAcquisitionLoss);
    }
    if ((observation.flags &
         kOtisGnssUartObservationBaudEpochBefore) != 0u) {
      close_collectors_for_planned_transition();
      otis_gnss_link_note_baud_epoch_boundary(&live_link);
    }
    const char byte = static_cast<char>(observation.byte);
    otis_gnss_link_feed(&live_link, byte, now_ms);
    if (metadata_path_open)
      otis_gnss_receiver_feed_at_ticks(
          &live_receiver, byte, now_ms, live_service_timer0_extended_ticks);
    drained++;
    if (static_cast<uint32_t>(live_timer0_ticks_from_register() -
                              entry_ticks) >=
        kOtisGnssUartRxConsumerTickBudget) {
      time_budget_hit = true;
      break;
    }
  }
  const bool byte_budget_hit =
      drained == kOtisGnssUartRxConsumerByteBudget;
  otis_gnss_uart_rx_ring_note_consumer_complete(
      &live_uart_rx_ring, drained, byte_budget_hit, time_budget_hit);
}

void complete_live_transmit_if_drained(uint32_t now_ms) {
  if (!live_transmit.active || live_transmit.index != live_transmit.length ||
      (uart_get_hw(uart0)->fr & UART_UARTFR_BUSY_BITS) != 0u)
    return;
  const bool target_baud_command_completed =
      live_link.pending_action == OtisGnssLinkActionKind::TransmitTargetBaud;
  const bool identity_query_completed =
      live_link.pending_action == OtisGnssLinkActionKind::TransmitIdentityQuery;
  if (identity_query_completed) {
    live_pmtk605_peripheral_complete_count++;
    live_pmtk605_last_peripheral_complete_ticks =
        live_service_timer0_extended_ticks;
    live_pmtk605_last_peripheral_complete_ticks_available =
        live_service_timer0_extension_available;
  }
  live_transmit = {};
  otis_gnss_link_complete_action(&live_link, true, now_ms);
#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION
  if (target_baud_command_completed &&
      live_characterization.request_available) {
    live_characterization.target_command_transmit_complete = true;
    live_characterization.target_command_transmit_elapsed_ms =
        static_cast<uint32_t>(now_ms - live_characterization.accepted_ms);
  }
#endif
}

void progress_live_transmit(uint32_t now_ms) {
  if (!live_transmit.active) return;
  if (elapsed_at_least(now_ms, live_transmit.started_ms,
                       OTIS_GNSS_UART_TX_TIMEOUT_MS)) {
    live_transmit = {};
    otis_gnss_link_complete_action(&live_link, false, now_ms);
    return;
  }

  uint8_t remaining = OTIS_GNSS_SERVICE_TX_BYTE_BUDGET;
  while (remaining-- > 0u && live_transmit.index < live_transmit.length &&
         uart_is_writable(uart0)) {
    uart_get_hw(uart0)->dr = static_cast<uint32_t>(
        static_cast<uint8_t>(live_transmit.bytes[live_transmit.index++]));
  }
  complete_live_transmit_if_drained(now_ms);
}

void begin_pending_link_action(uint32_t now_ms) {
  if (live_transmit.active) return;
  OtisGnssLinkAction action;
  if (!otis_gnss_link_take_action(&live_link, &action)) return;
  if (action.kind == OtisGnssLinkActionKind::SetUartBaud) {
    const bool opening_target_epoch =
        live_link.state == OtisGnssLinkState::SelectTargetBaud &&
        live_characterization.request_available;
    configure_live_uart(action.baud, opening_target_epoch);
    if (opening_target_epoch) {
#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION
      live_characterization.baud_epoch++;
      if (live_characterization.baud_epoch == 0u)
        live_characterization.baud_epoch = 1u;
      live_characterization.target_epoch_opened = true;
#endif
    }
    otis_gnss_link_complete_action(&live_link, true, now_ms);
    return;
  }
  if (action.bytes == nullptr || action.length == 0u) {
    otis_gnss_link_complete_action(&live_link, false, now_ms);
    return;
  }
  live_transmit.active = true;
  live_transmit.bytes = action.bytes;
  live_transmit.length = action.length;
  live_transmit.index = 0u;
  live_transmit.started_ms = now_ms;
  progress_live_transmit(now_ms);
}
}

bool otis_gnss_receiver_begin(void) {
#if OTIS_ENABLE_GNSS_RECEIVER
  // Start only the bounded state machine here. The fixed operational bootstrap
  // (or characterization discovery), identity validation, and configuration
  // proceed incrementally so GNSS cannot delay the timing-core boot handoff.
  live_receiver_started = false;
  live_uart_initialized = false;
  live_uart_irq_installed = false;
  live_transmit = {};
  live_characterization = {};
  live_characterization.observation_phase =
      OtisGnssObservationPhase::Discovery;
  live_characterization.transition_state = OtisGnssTransitionState::Idle;
  live_characterization.last_request_disposition =
      OtisGnssRequestDisposition::RejectedDisabled;
  live_characterization.baud_epoch = 1u;
  live_service_timer0_raw_ticks = 0u;
  live_service_timer0_extended_ticks = 0u;
  live_service_timer0_extension_available = false;
  live_pmtk605_peripheral_complete_count = 0u;
  live_pmtk605_last_peripheral_complete_ticks = 0u;
  live_pmtk605_last_peripheral_complete_ticks_available = false;
  otis_gnss_uart_rx_ring_reset(&live_uart_rx_ring);
  const uint32_t now_ms = millis();
  const OtisGnssLinkPolicy policy = {
      OTIS_GNSS_UART_BAUD,
      OTIS_GNSS_DISCOVERY_PASSIVE_DWELL_MS,
      OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS,
      OTIS_GNSS_DISCOVERY_DEGRADED_MS,
      OTIS_GNSS_RECONNECT_GAP_MS,
      OTIS_GNSS_OUTPUT_OBSERVATION_MS,
  };
  otis_gnss_receiver_reset(&live_receiver, now_ms);
  otis_gnss_link_reset(&live_link, &policy, now_ms);
  live_receiver_started = true;
  begin_pending_link_action(now_ms);
  return true;
#else
  return false;
#endif
}

void otis_gnss_receiver_service(uint32_t now_ms) {
#if OTIS_ENABLE_GNSS_RECEIVER
  if (!live_receiver_started) return;
  update_live_service_timer0_extension();
  // Commit a physically completed query before parsing bytes already retained
  // from its response.  Otherwise a prompt response can be consumed while the
  // link still says TransmitIdentityQuery and be discarded as non-causal.
  complete_live_transmit_if_drained(now_ms);
  // Consume interrupt-retained observations before service-plane work. The
  // timing fabric remains independent; this only bounds Core 0 parser work.
  service_live_uart_rx_ring(now_ms);
  // Preserve the existing bounded writer after acquisition service.
  progress_live_transmit(now_ms);
  otis_gnss_receiver_note_time_at_ticks(
      &live_receiver, now_ms, live_service_timer0_extended_ticks,
      OTIS_GNSS_RECONNECT_GAP_MS);
  // A wall-clock response deadline cannot advance the link past bytes already
  // accepted by the ISR for the current candidate.  Drain that exact producer
  // frontier first; no retained observation is reset or discarded.
  if (otis_gnss_uart_rx_ring_depth(&live_uart_rx_ring) == 0u)
    otis_gnss_link_tick(&live_link, now_ms);
  service_characterization_transaction(now_ms);
  begin_pending_link_action(now_ms);
#else
  (void)now_ms;
#endif
}

void otis_gnss_receiver_get_snapshot(uint32_t now_ms,
                                     OtisGnssReceiverSnapshot *snapshot) {
#if OTIS_ENABLE_GNSS_RECEIVER
  otis_gnss_receiver_snapshot(&live_receiver, now_ms,
                              OTIS_GNSS_METADATA_MAX_AGE_MS, snapshot);
  if (live_receiver.metadata_hold_active &&
      live_service_timer0_extension_available &&
      live_service_timer0_extended_ticks >=
          live_receiver.metadata_hold_started_ticks) {
    const uint64_t active_ticks =
        live_service_timer0_extended_ticks -
        live_receiver.metadata_hold_started_ticks;
    snapshot->metadata_hold_cumulative_ticks =
        live_receiver.metadata_hold_cumulative_ticks + active_ticks;
    snapshot->metadata_hold_longest_ticks =
        live_receiver.metadata_hold_longest_ticks > active_ticks
            ? live_receiver.metadata_hold_longest_ticks
            : active_ticks;
  }
  snapshot->initialized = live_link.service_initialized;
  snapshot->link_online = otis_gnss_link_online(&live_link);
  snapshot->configuration_confirmed = live_link.configuration_confirmed;
  snapshot->receiver_identity_available =
      live_link.receiver_identity_available;
  snapshot->discovery_degraded =
      otis_gnss_link_discovery_degraded(&live_link, now_ms);
  snapshot->rx_only = otis_gnss_link_runtime_rx_only(&live_link);
  snapshot->link_state = live_link.state;
  copy_field(snapshot->link_health_state,
             sizeof(snapshot->link_health_state),
             otis_gnss_link_state_name(&live_link, now_ms));
  copy_field(snapshot->link_phase, sizeof(snapshot->link_phase),
             otis_gnss_link_phase_name(&live_link));
  copy_field(snapshot->output_confirmation_method,
             sizeof(snapshot->output_confirmation_method),
             otis_gnss_output_confirmation_method_name(&live_link));
  copy_field(snapshot->receiver_release,
             sizeof(snapshot->receiver_release), live_link.receiver_release);
  copy_field(snapshot->output_configuration_signature,
             sizeof(snapshot->output_configuration_signature),
             live_link.output_configuration_signature);
  snapshot->candidate_baud = live_link.candidate_baud;
  snapshot->confirmed_baud = live_link.confirmed_baud;
  snapshot->last_identity_response_baud =
      live_link.last_identity_response_baud;
  snapshot->discovery_cycle = live_link.discovery_cycle;
  snapshot->link_last_valid_frame_age_ms =
      live_link.valid_frame_seen
          ? static_cast<uint32_t>(now_ms - live_link.last_valid_frame_ms)
          : UINT32_MAX;
  snapshot->link_checksum_valid_count = live_link.checksum_valid_count;
  snapshot->link_checksum_failure_count = live_link.checksum_failure_count;
  snapshot->link_oversize_count = live_link.oversize_count;
  snapshot->candidate_rejection_count = live_link.candidate_rejection_count;
  snapshot->configuration_failure_count =
      live_link.configuration_failure_count;
  snapshot->transmit_failure_count = live_link.transmit_failure_count;
  snapshot->link_loss_count = live_link.link_loss_count;
  snapshot->link_raw_acquisition_loss_count =
      live_link.raw_acquisition_loss_count;
  snapshot->identity_response_count = live_link.identity_response_count;
  snapshot->startup_hint_attempted = live_link.startup_hint_attempted;
  snapshot->startup_hint_baud = live_link.startup_hint_baud;
  snapshot->startup_hint_identity_outcome =
      live_link.startup_hint_identity_outcome;
  snapshot->startup_fallback_entered = live_link.startup_fallback_entered;
  snapshot->initial_discovery_identity_baud =
      live_link.initial_discovery_identity_baud;
  snapshot->initial_discovery_outcome =
      live_link.initial_discovery_outcome;
  snapshot->pmtk605_peripheral_complete_count =
      live_pmtk605_peripheral_complete_count;
  snapshot->pmtk605_last_peripheral_complete_ticks =
      live_pmtk605_last_peripheral_complete_ticks;
  snapshot->pmtk605_last_peripheral_complete_ticks_available =
      live_pmtk605_last_peripheral_complete_ticks_available;
  snapshot->output_response_count = live_link.output_response_count;
  snapshot->output_query_timeout_count = live_link.output_query_timeout_count;
  snapshot->output_configuration_ack_count =
      live_link.output_configuration_ack_count;
  snapshot->output_observation_success_count =
      live_link.output_observation_success_count;
  snapshot->output_observed_sentence_mask =
      live_link.output_observed_sentence_mask;
  snapshot->output_unexpected_sentence_mask =
      live_link.output_unexpected_sentence_mask;
  snapshot->last_command_ack_packet_type =
      live_link.last_command_ack_packet_type;
  snapshot->last_command_ack_flag = live_link.last_command_ack_flag;
  snapshot->output_configuration_field_count =
      live_link.output_configuration_field_count;
  snapshot->disconnected = snapshot->disconnected ||
                           (live_link.link_loss_count > 0u &&
                            !snapshot->link_online);
  snapshot->control_eligible = snapshot->control_eligible &&
                               snapshot->link_online &&
                               snapshot->configuration_confirmed &&
                               snapshot->rx_only;
  const bool uart_irq_enabled = irq_is_enabled(UART0_IRQ);
  if (uart_irq_enabled) irq_set_enabled(UART0_IRQ, false);
  otis_gnss_uart_rx_ring_snapshot(&live_uart_rx_ring, &snapshot->uart_rx);
  if (uart_irq_enabled) irq_set_enabled(UART0_IRQ, true);
#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION
  if ((live_characterization.transition_state ==
           OtisGnssTransitionState::Complete ||
       live_characterization.transition_state ==
           OtisGnssTransitionState::Recovered) &&
      !live_characterization.first_dependent_snapshot) {
    live_characterization.first_dependent_snapshot = true;
  }
  snapshot->observation_phase = live_characterization.observation_phase;
  snapshot->transition_state = live_characterization.transition_state;
  snapshot->last_request_disposition =
      live_characterization.last_request_disposition;
  snapshot->segment_ordinal = live_characterization.request_available
                                  ? live_characterization.request.segment_ordinal
                                  : 0u;
  format_segment_id(snapshot->segment_ordinal, snapshot->segment_id);
  snapshot->baud_epoch = live_characterization.baud_epoch;
  snapshot->transition_request_sequence =
      live_characterization.request.request_sequence;
  snapshot->transition_source_baud =
      live_characterization.request.source_baud;
  snapshot->transition_source_baud_epoch =
      live_characterization.request.source_baud_epoch;
  snapshot->transition_target_baud =
      live_characterization.request.target_baud;
  snapshot->transition_recovered_baud =
      live_characterization.recovered_baud;
  snapshot->transition_accepted_count =
      live_characterization.accepted_count;
  snapshot->transition_duplicate_count =
      live_characterization.duplicate_count;
  snapshot->transition_rejected_count =
      live_characterization.rejected_count;
  snapshot->transition_completed_count =
      live_characterization.completed_count;
  snapshot->transition_recovered_count =
      live_characterization.recovered_count;
  snapshot->transition_unrecoverable_count =
      live_characterization.unrecoverable_count;
  snapshot->transition_evidence_frontier =
      live_characterization.evidence_frontier;
  snapshot->transition_target_command_transmit_complete =
      live_characterization.target_command_transmit_complete;
  snapshot->transition_target_identity_confirmed =
      live_characterization.target_identity_confirmed;
  snapshot->transition_target_output_confirmed =
      live_characterization.target_output_confirmed;
  snapshot->transition_target_command_transmit_elapsed_ms =
      live_characterization.target_command_transmit_elapsed_ms;
  snapshot->transition_target_identity_elapsed_ms =
      live_characterization.target_identity_elapsed_ms;
  snapshot->transition_target_output_elapsed_ms =
      live_characterization.target_output_elapsed_ms;
  snapshot->transition_complete_elapsed_ms =
      live_characterization.transition_complete_elapsed_ms;
  snapshot->transition_recovery_started_elapsed_ms =
      live_characterization.recovery_started_elapsed_ms;
  snapshot->transition_recovery_terminal_elapsed_ms =
      live_characterization.recovery_terminal_elapsed_ms;
  snapshot->transition_first_dependent_snapshot =
      live_characterization.first_dependent_snapshot;
  snapshot->transition_platform_fault =
      live_characterization.platform_fault;
  snapshot->status_challenge_active =
      live_characterization.status_challenge_active;
  snapshot->status_challenge_sequence =
      live_characterization.status_challenge.challenge_sequence;
  snapshot->status_challenge_completed_count =
      live_characterization.status_challenge_completed_count;
  snapshot->last_status_request_disposition =
      live_characterization.last_status_request_disposition;
  snapshot->last_status_request_sequence =
      live_characterization.last_status_request.challenge_sequence;
  snapshot->last_status_request_segment_ordinal =
      live_characterization.last_status_request.segment_ordinal;
  snapshot->last_status_request_baud_epoch =
      live_characterization.last_status_request.baud_epoch;
  snapshot->completed_peak_uart_available =
      live_characterization.completed_peak_retention.available;
  snapshot->completed_peak_challenge_sequence =
      live_characterization.completed_peak_retention.challenge_sequence;
  snapshot->completed_peak_uart =
      live_characterization.completed_peak_uart;
#else
  snapshot->observation_phase = OtisGnssObservationPhase::Discovery;
  snapshot->transition_state = OtisGnssTransitionState::Idle;
  snapshot->last_request_disposition =
      OtisGnssRequestDisposition::RejectedDisabled;
  copy_field(snapshot->segment_id, sizeof(snapshot->segment_id), "none");
#endif
#else
  if (snapshot != nullptr) *snapshot = {};
  (void)now_ms;
#endif
}

OtisGnssRequestDisposition otis_gnss_receiver_request_baud_transition(
    const char *arguments, uint32_t now_ms) {
#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION
  OtisGnssBaudTransitionRequest request = {};
  if (!otis_gnss_parse_baud_transition_request(arguments, &request)) {
    live_characterization.last_request_disposition =
        OtisGnssRequestDisposition::RejectedParse;
    live_characterization.rejected_count++;
    set_characterization_platform_fault();
    return live_characterization.last_request_disposition;
  }

  if (live_characterization.request_available &&
      request.request_sequence ==
          live_characterization.request.request_sequence) {
    if (same_transition_request(request, live_characterization.request)) {
      live_characterization.last_request_disposition =
          OtisGnssRequestDisposition::Duplicate;
      live_characterization.duplicate_count++;
      return live_characterization.last_request_disposition;
    }
    live_characterization.last_request_disposition =
        OtisGnssRequestDisposition::RejectedContradictory;
    live_characterization.rejected_count++;
    set_characterization_platform_fault();
    return live_characterization.last_request_disposition;
  }

  const uint32_t expected_sequence =
      live_characterization.request_available
          ? live_characterization.request.request_sequence + 1u
          : 1u;
  const uint8_t expected_segment =
      live_characterization.request_available
          ? static_cast<uint8_t>(
                live_characterization.request.segment_ordinal + 1u)
          : 1u;
  if (request.request_sequence < expected_sequence) {
    live_characterization.last_request_disposition =
        OtisGnssRequestDisposition::RejectedStale;
    live_characterization.rejected_count++;
    set_characterization_platform_fault();
    return live_characterization.last_request_disposition;
  }
  if (request.request_sequence > expected_sequence ||
      request.segment_ordinal != expected_segment) {
    live_characterization.last_request_disposition =
        OtisGnssRequestDisposition::RejectedSkipped;
    live_characterization.rejected_count++;
    set_characterization_platform_fault();
    return live_characterization.last_request_disposition;
  }
  if (live_characterization.status_challenge_active ||
      live_characterization.transition_state ==
          OtisGnssTransitionState::Targeting ||
      live_characterization.transition_state ==
          OtisGnssTransitionState::AwaitFreshMetadata ||
      live_characterization.transition_state ==
          OtisGnssTransitionState::RecoveryScanning) {
    live_characterization.last_request_disposition =
        OtisGnssRequestDisposition::RejectedBusy;
    live_characterization.rejected_count++;
    return live_characterization.last_request_disposition;
  }
  if (live_characterization.platform_fault ||
      live_characterization.transition_state ==
          OtisGnssTransitionState::Unrecoverable) {
    live_characterization.last_request_disposition =
        OtisGnssRequestDisposition::RejectedPhase;
    live_characterization.rejected_count++;
    return live_characterization.last_request_disposition;
  }
  if (!otis_gnss_link_online(&live_link) ||
      !live_link.receiver_identity_available ||
      !live_link.configuration_confirmed ||
      live_link.receiver_release[0] == '\0' ||
      live_link.output_configuration_signature[0] == '\0') {
    live_characterization.last_request_disposition =
        OtisGnssRequestDisposition::RejectedIdentity;
    live_characterization.rejected_count++;
    return live_characterization.last_request_disposition;
  }
  if (request.source_baud != live_link.confirmed_baud ||
      request.source_baud_epoch != live_characterization.baud_epoch) {
    live_characterization.last_request_disposition =
        OtisGnssRequestDisposition::RejectedSource;
    live_characterization.rejected_count++;
    set_characterization_platform_fault();
    return live_characterization.last_request_disposition;
  }
#if OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD
  const bool retained_startup_binding =
      request.request_sequence == 1u && request.segment_ordinal == 1u &&
      request.target_baud == live_link.confirmed_baud &&
      live_link.initial_discovery_outcome !=
          OtisGnssInitialDiscoveryOutcome::Pending;
  if (retained_startup_binding &&
      !retained_startup_attachment_metadata_ready(now_ms)) {
    live_characterization.last_request_disposition =
        OtisGnssRequestDisposition::RejectedIdentity;
    live_characterization.rejected_count++;
    return live_characterization.last_request_disposition;
  }
#else
  constexpr bool retained_startup_binding = false;
#endif
  size_t command_length = 0u;
  if (fixed_target_baud_command(request.target_baud, &command_length) ==
          nullptr ||
      command_length == 0u) {
    live_characterization.last_request_disposition =
        OtisGnssRequestDisposition::RejectedTarget;
    live_characterization.rejected_count++;
    set_characterization_platform_fault();
    return live_characterization.last_request_disposition;
  }

  live_characterization.request = request;
  live_characterization.request_available = true;
  live_characterization.accepted_ms = now_ms;
  live_characterization.target_epoch_opened = false;
  live_characterization.recovery_epoch_opened = false;
  live_characterization.recovered_baud = 0u;
  live_characterization.evidence_frontier = 0u;
  live_characterization.target_command_transmit_complete = false;
  live_characterization.target_identity_confirmed = false;
  live_characterization.target_output_confirmed = false;
  live_characterization.target_command_transmit_elapsed_ms = 0u;
  live_characterization.target_identity_elapsed_ms = 0u;
  live_characterization.target_output_elapsed_ms = 0u;
  live_characterization.transition_complete_elapsed_ms = 0u;
  live_characterization.recovery_started_elapsed_ms = 0u;
  live_characterization.recovery_terminal_elapsed_ms = 0u;
  live_characterization.first_dependent_snapshot = false;
  live_characterization.identity_response_baseline =
      live_link.identity_response_count;
  live_characterization.rmc_baseline = live_receiver.rmc_count;
  live_characterization.gga_baseline = live_receiver.gga_count;
  live_characterization.gsa_baseline = live_receiver.gsa_count;
  live_characterization.transition_state = OtisGnssTransitionState::Targeting;
  live_characterization.observation_phase =
      OtisGnssObservationPhase::PlannedTransition;
  live_characterization.last_request_disposition =
      OtisGnssRequestDisposition::Accepted;
  live_characterization.accepted_count++;
  copy_field(live_characterization.receiver_release_at_accept,
             sizeof(live_characterization.receiver_release_at_accept),
             live_link.receiver_release);
  copy_field(live_characterization.output_signature_at_accept,
             sizeof(live_characterization.output_signature_at_accept),
             live_link.output_configuration_signature);
  capture_characterization_phase_uart_baseline();

  if (retained_startup_binding) {
    // This is a run-local request-1 binding to freshly requalified current
    // state, not an inherited transition or baud epoch. Preserve the current
    // UART rate, emit no PMTK251, and require a new metadata frontier before
    // the first dependent snapshot can report completion.
    live_characterization.target_identity_confirmed = true;
    live_characterization.target_output_confirmed = true;
    live_characterization.transition_state =
        OtisGnssTransitionState::AwaitFreshMetadata;
    return live_characterization.last_request_disposition;
  }

  close_collectors_for_planned_transition();
  live_link.policy.target_baud = request.target_baud;
  live_link.configuration_confirmed = false;
  live_link.output_configuration_command_acknowledged = false;
  live_link.output_confirmation_method = OtisGnssOutputConfirmationMethod::None;
  live_link.characterization_targeting = true;
  live_link.characterization_target_failed = false;
  live_link.characterization_target_started_ms = now_ms;
  live_link.characterization_recovery_scan = false;
  live_link.characterization_recovery_scan_exhausted = false;
  queue_link_action(&live_link, OtisGnssLinkState::TransmitTargetBaud,
                    OtisGnssLinkActionKind::TransmitTargetBaud);
  begin_pending_link_action(now_ms);
  return live_characterization.last_request_disposition;
#else
  (void)arguments;
  (void)now_ms;
  return OtisGnssRequestDisposition::RejectedDisabled;
#endif
}

OtisGnssRequestDisposition otis_gnss_receiver_begin_status_challenge(
    const char *arguments, uint32_t now_ms) {
#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION
  OtisGnssStatusChallengeRequest request = {};
  const auto retain_disposition = [&](OtisGnssRequestDisposition disposition) {
    live_characterization.last_status_request = request;
    live_characterization.last_status_request_disposition = disposition;
    return disposition;
  };
  if (!otis_gnss_parse_status_challenge_request(arguments, &request)) {
    set_characterization_platform_fault();
    return retain_disposition(OtisGnssRequestDisposition::RejectedParse);
  }
  if (live_characterization.status_challenge.challenge_sequence ==
      request.challenge_sequence) {
    if (live_characterization.status_challenge.segment_ordinal ==
            request.segment_ordinal &&
        live_characterization.status_challenge.baud_epoch ==
            request.baud_epoch)
      return retain_disposition(OtisGnssRequestDisposition::Duplicate);
    set_characterization_platform_fault();
    return retain_disposition(
        OtisGnssRequestDisposition::RejectedContradictory);
  }
  if (request.challenge_sequence !=
      live_characterization.status_challenge.challenge_sequence + 1u) {
    set_characterization_platform_fault();
    return retain_disposition(request.challenge_sequence <
                   live_characterization.status_challenge.challenge_sequence
               ? OtisGnssRequestDisposition::RejectedStale
               : OtisGnssRequestDisposition::RejectedSkipped);
  }
  if (live_characterization.status_challenge_active ||
      (live_characterization.transition_state !=
           OtisGnssTransitionState::Complete &&
       live_characterization.transition_state !=
           OtisGnssTransitionState::Recovered))
    return retain_disposition(OtisGnssRequestDisposition::RejectedBusy);
  if (!live_characterization.request_available ||
      request.segment_ordinal !=
          live_characterization.request.segment_ordinal ||
      request.baud_epoch != live_characterization.baud_epoch)
    {
      set_characterization_platform_fault();
      return retain_disposition(OtisGnssRequestDisposition::RejectedSource);
    }

  OtisGnssReceiverSnapshot metadata = {};
  otis_gnss_receiver_snapshot(&live_receiver, now_ms,
                              OTIS_GNSS_METADATA_MAX_AGE_MS, &metadata);
  if (!otis_gnss_link_online(&live_link) || !metadata.metadata_fresh ||
      !metadata.checksum_requalified || !metadata.gsa_fresh ||
      !metadata.gsa_checksum_requalified)
    return retain_disposition(OtisGnssRequestDisposition::RejectedPhase);

  // The immediately following accepted request is the protocol-level
  // acknowledgement that the host consumed the preceding completed peak.
  // A duplicate request returned above never reaches this mutation.
  if (!otis_gnss_completed_peak_prepare_next(
          &live_characterization.completed_peak_retention,
          live_characterization.status_challenge.challenge_sequence,
          request.challenge_sequence)) {
    set_characterization_platform_fault();
    return retain_disposition(
        OtisGnssRequestDisposition::RejectedContradictory);
  }

  live_characterization.status_challenge = request;
  live_characterization.status_challenge_active = true;
  live_characterization.status_challenge_phase_snapshot_pending = false;
  live_characterization.observation_phase = OtisGnssObservationPhase::PeakLoad;
  capture_characterization_phase_uart_baseline();
  return retain_disposition(OtisGnssRequestDisposition::Accepted);
#else
  (void)arguments;
  (void)now_ms;
  return OtisGnssRequestDisposition::RejectedDisabled;
#endif
}

void otis_gnss_receiver_complete_status_challenge(uint32_t now_ms) {
#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION
  if (!live_characterization.status_challenge_active) return;
  live_characterization.status_challenge_active = false;
  live_characterization.status_challenge_completed_count++;
  live_characterization.status_challenge_phase_snapshot_pending = true;
  (void)now_ms;
#else
  (void)now_ms;
#endif
}

void otis_gnss_receiver_finish_status_snapshot(void) {
#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION
  if (!live_characterization.status_challenge_phase_snapshot_pending) return;
  if (!otis_gnss_completed_peak_publish(
          &live_characterization.completed_peak_retention,
          live_characterization.status_challenge.challenge_sequence)) {
    set_characterization_platform_fault();
    return;
  }
  const bool uart_irq_enabled = irq_is_enabled(UART0_IRQ);
  if (uart_irq_enabled) irq_set_enabled(UART0_IRQ, false);
  otis_gnss_uart_rx_ring_snapshot(
      &live_uart_rx_ring, &live_characterization.completed_peak_uart);
  if (uart_irq_enabled) irq_set_enabled(UART0_IRQ, true);
  live_characterization.status_challenge_phase_snapshot_pending = false;
  live_characterization.observation_phase =
      OtisGnssObservationPhase::OrdinaryOnline;
  capture_characterization_phase_uart_baseline();
#endif
}

#endif
