#include "otis_gnss_receiver.h"

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

void note_parser_fault(OtisGnssReceiver *receiver) {
  receiver->parser_drop_count++;
  receiver->parser_fault_epoch++;
  if (receiver->parser_fault_epoch == 0u) receiver->parser_fault_epoch = 1u;
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

void parse_complete_line(OtisGnssReceiver *receiver, uint32_t now_ms) {
  receiver->line[receiver->line_length] = '\0';
  if (receiver->line_length < 7u || receiver->line[0] != '$') {
    receiver->truncated_count++;
    note_parser_fault(receiver);
    return;
  }
  char *star = strrchr(receiver->line, '*');
  if (star == nullptr || star != receiver->line + receiver->line_length - 3u) {
    receiver->truncated_count++;
    note_parser_fault(receiver);
    return;
  }
  const int upper = hex_value(star[1]);
  const int lower = hex_value(star[2]);
  if (upper < 0 || lower < 0) {
    receiver->truncated_count++;
    note_parser_fault(receiver);
    return;
  }
  uint8_t checksum = 0u;
  for (char *cursor = receiver->line + 1; cursor < star; ++cursor)
    checksum ^= static_cast<uint8_t>(*cursor);
  const uint8_t expected = static_cast<uint8_t>((upper << 4) | lower);
  if (checksum != expected) {
    receiver->checksum_failure_count++;
    note_parser_fault(receiver);
    return;
  }
  receiver->checksum_valid_count++;
  *star = '\0';
  char *fields[24] = {};
  size_t field_count = 0u;
  if (!split_fields(receiver->line + 1, fields, 24u, &field_count) ||
      field_count == 0u) {
    receiver->truncated_count++;
    note_parser_fault(receiver);
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
    note_parser_fault(receiver);
  }
}

}  // namespace

namespace {

constexpr uint32_t kGnssCandidateBauds[] = {
    115200u, 9600u, 57600u, 38400u, 19200u, 14400u, 4800u,
};
constexpr size_t kGnssCandidateBaudCount =
    sizeof(kGnssCandidateBauds) / sizeof(kGnssCandidateBauds[0]);
constexpr char kGnssIdentityQuery[] = "$PMTK605*31\r\n";
constexpr char kGnssTargetBaudCommand[] = "$PMTK251,115200*1F\r\n";
constexpr char kGnssOutputQuery[] = "$PMTK414*33\r\n";
constexpr char kGnssOutputConfiguration[] =
    "$PMTK314,0,1,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0*29\r\n";
constexpr uint8_t kGnssExpectedOutputConfiguration[] = {
    0u, 1u, 0u, 1u, 1u, 0u, 0u, 0u, 0u, 0u,
    0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u,
};

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
                       OtisGnssLinkActionKind action) {
  link->state = state;
  link->pending_action = action;
  link->action_pending = true;
  link->action_in_progress = false;
}

void select_candidate(OtisGnssLink *link, uint32_t now_ms) {
  link->candidate_baud = candidate_baud(link->candidate_index);
  link->pending_baud = link->candidate_baud;
  link->state_started_ms = now_ms;
  reset_link_line(link);
  queue_link_action(link, OtisGnssLinkState::SelectCandidateBaud,
                    OtisGnssLinkActionKind::SetUartBaud);
}

void advance_candidate(OtisGnssLink *link, uint32_t now_ms) {
  link->candidate_rejection_count++;
  link->candidate_index++;
  if (link->candidate_index >= kGnssCandidateBaudCount) {
    link->candidate_index = 0u;
    link->discovery_cycle++;
  }
  select_candidate(link, now_ms);
}

void restart_discovery(OtisGnssLink *link, uint32_t now_ms,
                       bool link_was_lost) {
  if (link_was_lost) link->link_loss_count++;
  link->configuration_confirmed = false;
  link->receiver_identity_available = false;
  link->confirmed_baud = 0u;
  link->candidate_index = 0u;
  link->discovery_cycle++;
  link->discovery_started_ms = now_ms;
  select_candidate(link, now_ms);
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
  if (field_count != sizeof(kGnssExpectedOutputConfiguration) + 1u)
    return false;
  for (size_t index = 0u;
       index < sizeof(kGnssExpectedOutputConfiguration); ++index) {
    uint8_t parsed = 0u;
    if (!parse_u8(fields[index + 1u], 5u, &parsed) ||
        parsed != kGnssExpectedOutputConfiguration[index])
      return false;
  }
  return true;
}

void establish_online_link(OtisGnssLink *link, uint32_t now_ms) {
  link->state = OtisGnssLinkState::Online;
  link->state_started_ms = now_ms;
  link->confirmed_baud = link->policy.target_baud;
  link->configuration_confirmed = true;
  link->action_pending = false;
  link->action_in_progress = false;
  link->pending_action = OtisGnssLinkActionKind::None;
}

void note_identity_response(OtisGnssLink *link, char **fields,
                            size_t field_count, uint32_t now_ms) {
  if (field_count < 2u) return;
  const bool candidate_response =
      link->state == OtisGnssLinkState::AwaitIdentityResponse;
  const bool target_response =
      link->state == OtisGnssLinkState::AwaitTargetIdentityResponse;
  if (!candidate_response && !target_response) return;
  link->identity_response_count++;
  copy_release_identity(link, fields[1]);
  if (!link->receiver_identity_available) return;

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
  if (output_configuration_matches(fields, field_count)) {
    establish_online_link(link, now_ms);
    return;
  }
  if (initial) {
    queue_link_action(link,
                      OtisGnssLinkState::TransmitOutputConfiguration,
                      OtisGnssLinkActionKind::TransmitOutputConfiguration);
    return;
  }
  link->configuration_failure_count++;
  restart_discovery(link, now_ms, false);
}

void note_command_ack(OtisGnssLink *link, char **fields, size_t field_count,
                      uint32_t now_ms) {
  if (link->state != OtisGnssLinkState::AwaitOutputConfigurationAck ||
      field_count != 3u || strcmp(fields[1], "314") != 0)
    return;
  if (strcmp(fields[2], "3") == 0) {
    queue_output_query(link, true);
    return;
  }
  link->configuration_failure_count++;
  restart_discovery(link, now_ms, false);
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
  select_candidate(link, now_ms);
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
                           link->policy.response_timeout_ms))
        advance_candidate(link, now_ms);
      break;
    case OtisGnssLinkState::AwaitTargetIdentityResponse:
    case OtisGnssLinkState::AwaitOutputResponse:
    case OtisGnssLinkState::AwaitOutputConfigurationAck:
    case OtisGnssLinkState::AwaitOutputVerificationResponse:
      if (elapsed_at_least(now_ms, link->state_started_ms,
                           link->policy.response_timeout_ms)) {
        link->configuration_failure_count++;
        restart_discovery(link, now_ms, false);
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
      action->bytes = kGnssTargetBaudCommand;
      action->length = sizeof(kGnssTargetBaudCommand) - 1u;
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
    restart_discovery(link, now_ms, false);
    return;
  }

  switch (link->state) {
    case OtisGnssLinkState::SelectCandidateBaud:
      reset_link_line(link);
      link->state = OtisGnssLinkState::PassiveListen;
      link->state_started_ms = now_ms;
      break;
    case OtisGnssLinkState::TransmitIdentityQuery:
      link->state = OtisGnssLinkState::AwaitIdentityResponse;
      link->state_started_ms = now_ms;
      break;
    case OtisGnssLinkState::TransmitTargetBaud:
      link->pending_baud = link->policy.target_baud;
      queue_link_action(link, OtisGnssLinkState::SelectTargetBaud,
                        OtisGnssLinkActionKind::SetUartBaud);
      break;
    case OtisGnssLinkState::SelectTargetBaud:
      link->candidate_baud = link->policy.target_baud;
      reset_link_line(link);
      queue_identity_query(link, true);
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
      restart_discovery(link, now_ms, false);
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

void otis_gnss_receiver_reset(OtisGnssReceiver *receiver, uint32_t now_ms) {
  if (receiver == nullptr) return;
  *receiver = {};
  receiver->initialized = true;
  receiver->rx_only = true;
  receiver->identity_epoch = 1u;
  receiver->last_message_ms = now_ms;
}

void otis_gnss_receiver_feed(OtisGnssReceiver *receiver, char byte,
                             uint32_t now_ms) {
  if (receiver == nullptr || !receiver->initialized) return;
  if (byte == '$') {
    if (receiver->collecting && receiver->line_length > 0u) {
      receiver->truncated_count++;
      note_parser_fault(receiver);
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
    if (receiver->collecting) parse_complete_line(receiver, now_ms);
    receiver->collecting = false;
    receiver->line_length = 0u;
    return;
  }
  if (!receiver->collecting || receiver->discarding_oversize) return;
  if (receiver->line_length >= kOtisGnssMaximumLineBytes - 1u) {
    receiver->oversize_count++;
    note_parser_fault(receiver);
    receiver->discarding_oversize = true;
    receiver->collecting = false;
    receiver->line_length = 0u;
    return;
  }
  receiver->line[receiver->line_length++] = byte;
}

void otis_gnss_receiver_note_time(OtisGnssReceiver *receiver, uint32_t now_ms,
                                  uint32_t reconnect_gap_ms) {
  if (receiver == nullptr || !receiver->initialized ||
      (!receiver->rmc_seen && !receiver->gga_seen))
    return;
  if (elapsed_at_least(now_ms, receiver->last_message_ms, reconnect_gap_ms))
    receiver->disconnected = true;
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

#if !defined(OTIS_GNSS_HOST_TEST)

#include <Arduino.h>
#include <hardware/gpio.h>
#include <hardware/uart.h>

#include "otis_board.h"
#include "otis_config.h"

namespace {
OtisGnssReceiver live_receiver = {};
OtisGnssLink live_link = {};
bool live_receiver_started = false;
bool live_uart_initialized = false;

struct LiveGnssTransmit {
  bool active;
  const char *bytes;
  size_t length;
  size_t index;
  uint32_t started_ms;
};

LiveGnssTransmit live_transmit = {};

void configure_live_uart(uint32_t baud) {
  if (live_uart_initialized) uart_deinit(uart0);
  uart_init(uart0, baud);
  uart_set_format(uart0, 8u, 1u, UART_PARITY_NONE);
  uart_set_hw_flow(uart0, false, false);
  uart_set_fifo_enabled(uart0, true);
  gpio_set_function(OTIS_PIN_GNSS_RX, GPIO_FUNC_UART);
  gpio_disable_pulls(OTIS_PIN_GNSS_RX);
  gpio_set_function(OTIS_PIN_GNSS_TX, GPIO_FUNC_UART);
  gpio_disable_pulls(OTIS_PIN_GNSS_TX);
  live_uart_initialized = true;
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
  if (live_transmit.index == live_transmit.length &&
      (uart_get_hw(uart0)->fr & UART_UARTFR_BUSY_BITS) == 0u) {
    live_transmit = {};
    otis_gnss_link_complete_action(&live_link, true, now_ms);
  }
}

void begin_pending_link_action(uint32_t now_ms) {
  if (live_transmit.active) return;
  OtisGnssLinkAction action;
  if (!otis_gnss_link_take_action(&live_link, &action)) return;
  if (action.kind == OtisGnssLinkActionKind::SetUartBaud) {
    configure_live_uart(action.baud);
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
  // Start only the bounded state machine here. Baud discovery, PMTK identity
  // validation, and configuration proceed incrementally from service calls so
  // GNSS serial acquisition cannot delay the timing-core boot handoff.
  live_receiver_started = false;
  live_uart_initialized = false;
  live_transmit = {};
  const uint32_t now_ms = millis();
  const OtisGnssLinkPolicy policy = {
      OTIS_GNSS_UART_BAUD,
      OTIS_GNSS_DISCOVERY_PASSIVE_DWELL_MS,
      OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS,
      OTIS_GNSS_DISCOVERY_DEGRADED_MS,
      OTIS_GNSS_RECONNECT_GAP_MS,
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
  // Complete any pending UART bytes before reading. A receiver response cannot
  // then race ahead of the state transition which makes that response causal.
  progress_live_transmit(now_ms);
  otis_gnss_receiver_note_time(&live_receiver, now_ms,
                               OTIS_GNSS_RECONNECT_GAP_MS);
  uint8_t remaining = OTIS_GNSS_SERVICE_BYTE_BUDGET;
  while (remaining-- > 0u && uart_is_readable(uart0)) {
    const char byte = static_cast<char>(uart_getc(uart0));
    const bool metadata_path_open = otis_gnss_link_online(&live_link);
    otis_gnss_link_feed(&live_link, byte, now_ms);
    if (metadata_path_open)
      otis_gnss_receiver_feed(&live_receiver, byte, now_ms);
  }
  otis_gnss_link_tick(&live_link, now_ms);
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
  copy_field(snapshot->receiver_release,
             sizeof(snapshot->receiver_release), live_link.receiver_release);
  snapshot->candidate_baud = live_link.candidate_baud;
  snapshot->confirmed_baud = live_link.confirmed_baud;
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
  snapshot->disconnected = snapshot->disconnected ||
                           (live_link.link_loss_count > 0u &&
                            !snapshot->link_online);
  snapshot->control_eligible = snapshot->control_eligible &&
                               snapshot->link_online &&
                               snapshot->configuration_confirmed &&
                               snapshot->rx_only;
#else
  if (snapshot != nullptr) *snapshot = {};
  (void)now_ms;
#endif
}

#endif
