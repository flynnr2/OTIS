#include "otis_gnss_receiver.h"

#include "otis_config.h"

#include <Adafruit_GNSS.h>

#include <ctype.h>
#include <stdlib.h>
#include <string.h>

namespace {

bool elapsed_at_least(uint32_t now, uint32_t then, uint32_t interval) {
  return static_cast<uint32_t>(now - then) >= interval;
}

void copy_field(char *destination, size_t capacity, const char *source) {
  if (destination == nullptr || capacity == 0u) return;
  size_t length = source == nullptr ? 0u : strlen(source);
  if (length >= capacity) length = capacity - 1u;
  if (length > 0u) memcpy(destination, source, length);
  destination[length] = '\0';
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
    if (existing.fault_class == fault_class) return;
  }
  if (receiver->fault_capsule_count >= kOtisGnssFaultCapsuleCapacity) {
    receiver->fault_capsule_dropped_count++;
    return;
  }
  OtisGnssParserFaultCapsule &capsule =
      receiver->fault_capsules[receiver->fault_capsule_count++];
  capsule = {};
  capsule.valid = true;
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

// Adafruit owns NMEA validation and standard GNSS decoding. OTIS owns
// qualification epochs and raw field text; no library transport or cached fix
// is allowed to refresh another sentence's evidence.
nmea_span_t navigation_field(nmea_span_t fields, uint8_t index) {
  nmea_span_t field = {nullptr, 0u};
  for (uint8_t i = 0u; i < index; ++i)
    field = Adafruit_NMEA::nextField(fields);
  return field;
}

void copy_span(char *destination, size_t capacity, nmea_span_t field) {
  const size_t length = field.length < capacity - 1u ? field.length : capacity - 1u;
  if (length) memcpy(destination, field.data, length);
  destination[length] = '\0';
}

bool navigation_u8(nmea_span_t field, uint8_t maximum, uint8_t *value) {
  const nmea_decimal_t decoded = Adafruit_NMEA::parseDecimal(field);
  if (decoded.status != NMEA_NUMBER_VALID || decoded.decimalPlaces != 0u ||
      decoded.coefficient < 0 || decoded.coefficient > maximum)
    return false;
  *value = static_cast<uint8_t>(decoded.coefficient);
  return true;
}

void parse_complete_line(OtisGnssReceiver *receiver, uint32_t now_ms,
                   uint64_t service_extended_ticks) {
  receiver->line[receiver->line_length] = '\0';
  const nmea_sentence_t sentence =
      Adafruit_NMEA::validate(receiver->line, receiver->line_length);
  if (sentence.status != NMEA_FRAME_VALID || receiver->line[0] != '$') {
    const bool checksum = sentence.status == NMEA_FRAME_BAD_CHECKSUM;
    if (checksum) receiver->checksum_failure_count++;
    else receiver->truncated_count++;
    note_parser_fault(receiver, now_ms, service_extended_ticks,
                      checksum ? OtisGnssParserFaultClass::Checksum
                               : OtisGnssParserFaultClass::LineShape);
    return;
  }
  receiver->checksum_valid_count++;
  if (sentence.address.length != 5u || sentence.address.data[0] == 'P') return;
  const nmea_span_t type = {sentence.address.data + 2, 3u};
  const bool rmc = memcmp(type.data, "RMC", 3u) == 0;
  const bool gga = memcmp(type.data, "GGA", 3u) == 0;
  const bool gsa = memcmp(type.data, "GSA", 3u) == 0;
  if (!rmc && !gga && !gsa) return;

  const gnss_position_t position = Adafruit_GNSS::parsePosition(sentence);
  bool valid = gsa
      ? Adafruit_GNSS::validateNavigation(type, sentence.fields).status ==
            GNSS_SENTENCE_VALID
      : position.validation.status == GNSS_SENTENCE_VALID;
  uint8_t satellites = 0u, dimension = 0u;
  if (gga)
    valid = valid && position.fixQualityStatus == NMEA_NUMBER_VALID &&
            position.fixQuality <= 8u &&
            navigation_u8(navigation_field(sentence.fields, 7u), 99u, &satellites);
  if (gsa)
    valid = valid && navigation_u8(navigation_field(sentence.fields, 2u), 3u,
                                   &dimension) && dimension >= 1u;
  if (!valid) {
    receiver->truncated_count++;
    note_parser_fault(receiver, now_ms, service_extended_ticks,
                      OtisGnssParserFaultClass::FieldShape);
    return;
  }

  if (rmc) {
    note_recognized_message(receiver, now_ms);
    receiver->rmc_seen = true;
    receiver->rmc_count++;
    receiver->last_rmc_ms = now_ms;
    receiver->rmc_repair_epoch = receiver->parser_fault_epoch;
    receiver->rmc_valid = position.fixStatus == NMEA_NUMBER_VALID && position.fix;
    receiver->rmc_utc_available = position.time.status == NMEA_NUMBER_VALID;
    receiver->date_available = position.date.status == NMEA_NUMBER_VALID;
    copy_span(receiver->utc, sizeof(receiver->utc), navigation_field(sentence.fields, 1u));
    copy_span(receiver->date, sizeof(receiver->date), navigation_field(sentence.fields, 9u));
  } else if (gga) {
    note_recognized_message(receiver, now_ms);
    receiver->gga_seen = true;
    receiver->gga_count++;
    receiver->last_gga_ms = now_ms;
    receiver->gga_repair_epoch = receiver->parser_fault_epoch;
    receiver->fix_quality = position.fixQuality;
    receiver->satellites = satellites;
    receiver->gga_utc_available = position.time.status == NMEA_NUMBER_VALID;
    copy_span(receiver->hdop, sizeof(receiver->hdop), navigation_field(sentence.fields, 8u));
  } else {
    receiver->gsa_seen = true;
    receiver->gsa_count++;
    receiver->last_gsa_ms = now_ms;
    receiver->gsa_repair_epoch = receiver->parser_fault_epoch;
    receiver->fix_dimension = dimension;
  }
  if (rmc || gga) {
    copy_span(receiver->talker, sizeof(receiver->talker), sentence.address);
    receiver->utc_available = receiver->rmc_utc_available && receiver->gga_utc_available;
  }
  note_good_line_metrics(receiver, now_ms, service_extended_ticks);
}

}  // namespace

namespace {

constexpr uint32_t kGnssOperationalBootstrapBauds[] = {
    9600u, 115200u,
};
constexpr size_t kGnssOperationalBootstrapBaudCount =
    sizeof(kGnssOperationalBootstrapBauds) /
    sizeof(kGnssOperationalBootstrapBauds[0]);
constexpr char kGnssTargetBaudCommand[] = "$PMTK251,115200*1F\r\n";
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

const char *fixed_target_baud_command(uint32_t baud, size_t *length) {
  if (length == nullptr) return nullptr;
  if (baud != OTIS_GNSS_UART_BAUD) {
    *length = 0u;
    return nullptr;
  }
  *length = sizeof(kGnssTargetBaudCommand) - 1u;
  return kGnssTargetBaudCommand;
}

void reset_link_line(OtisGnssLink *link) {
  link->line_length = 0u;
  link->collecting = false;
  link->discarding_oversize = false;
}

void queue_link_action(OtisGnssLink *link, OtisGnssLinkState state,
                       OtisGnssLinkActionKind action);

void queue_link_action(OtisGnssLink *link, OtisGnssLinkState state,
                       OtisGnssLinkActionKind action) {
  link->state = state;
  link->pending_action = action;
  link->action_pending = true;
  link->action_in_progress = false;
}

void restart_discovery(OtisGnssLink *link, uint32_t now_ms,
                       bool link_was_lost);

void fail_validation_or_restart(OtisGnssLink *link, uint32_t now_ms) {
  restart_discovery(link, now_ms, false);
}

void fail_operational_bootstrap(OtisGnssLink *link) {
  link->operational_bootstrap_failed = true;
  link->operational_bootstrap_complete = false;
  link->state = OtisGnssLinkState::OperationalBootstrapFailed;
  link->action_pending = false;
  link->action_in_progress = false;
  link->pending_action = OtisGnssLinkActionKind::None;
  reset_link_line(link);
}

void restart_discovery(OtisGnssLink *link, uint32_t now_ms,
                       bool link_was_lost) {
  if (link_was_lost) link->link_loss_count++;
  link->configuration_confirmed = false;
  link->output_configuration_command_acknowledged = false;
  link->output_confirmation_method = OtisGnssOutputConfirmationMethod::None;
  link->receiver_identity_available = false;
  link->confirmed_baud = 0u;
  link->candidate_index = 0u;
  link->discovery_cycle++;
  link->discovery_started_ms = now_ms;
  // The finite write-only promotion is a boot transaction and is never
  // repeated. Later qualification failures remain at 115200, listen through a
  // full passive interval, and request fresh identity/configuration evidence.
  if (!link->operational_bootstrap_complete) {
    fail_operational_bootstrap(link);
    return;
  }
  link->candidate_baud = link->policy.target_baud;
  link->state_started_ms = now_ms;
  reset_link_line(link);
  link->state = OtisGnssLinkState::PassiveListen;
}

void queue_identity_query(OtisGnssLink *link) {
  queue_link_action(link, OtisGnssLinkState::TransmitTargetIdentityQuery,
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
  if (!configured_output_observation) return;
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
}

void note_identity_response(OtisGnssLink *link, char **fields,
                            size_t field_count, uint32_t now_ms) {
  if (field_count < 2u) return;
  if (link->state != OtisGnssLinkState::AwaitTargetIdentityResponse) return;
  link->identity_response_count++;
  copy_release_identity(link, fields[1]);
  if (!link->receiver_identity_available) return;
  link->last_identity_response_baud = link->candidate_baud;
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
    queue_output_query(link, true);
    return;
  }
  link->configuration_failure_count++;
  fail_validation_or_restart(link, now_ms);
}

void process_link_line(OtisGnssLink *link, uint32_t now_ms) {
  link->line[link->line_length] = '\0';
  const nmea_sentence_t sentence =
      Adafruit_NMEA::validate(link->line, link->line_length);
  if (sentence.status != NMEA_FRAME_VALID || link->line[0] != '$') {
    if (sentence.status == NMEA_FRAME_BAD_CHECKSUM) link->checksum_failure_count++;
    return;
  }
  char *star = strrchr(link->line, '*');

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

  if (link->state == OtisGnssLinkState::PassiveListen) {
    queue_identity_query(link);
  }
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
  // Fixed operational bootstrap: cover reset-default 9600 and retained-
  // operational 115200 with the same set-115200 packet and an explicit
  // receiver-side settle after each packet, then stay at 115200. No
  // response-driven discovery, learning, fallback, or post-boot promotion
  // retry is involved.
  link->candidate_index = 0u;
  link->candidate_baud = kGnssOperationalBootstrapBauds[0];
  link->pending_baud = link->candidate_baud;
  link->state_started_ms = now_ms;
  reset_link_line(link);
  queue_link_action(link, OtisGnssLinkState::SelectCandidateBaud,
                    OtisGnssLinkActionKind::SetUartBaud);
}

bool otis_gnss_link_tick_may_advance_with_rx_backlog(
    const OtisGnssLink *link) {
  return link != nullptr &&
         link->state == OtisGnssLinkState::OperationalBootstrapSettle;
}

void otis_gnss_link_tick(OtisGnssLink *link, uint32_t now_ms) {
  if (link == nullptr || !link->service_initialized || link->action_pending ||
      link->action_in_progress)
    return;
  switch (link->state) {
    case OtisGnssLinkState::PassiveListen:
      if (elapsed_at_least(now_ms, link->state_started_ms,
                           link->policy.passive_dwell_ms))
        queue_identity_query(link);
      break;
    case OtisGnssLinkState::OperationalBootstrapSettle:
      if (elapsed_at_least(now_ms, link->state_started_ms,
                           OTIS_GNSS_OPERATIONAL_PROMOTION_SETTLE_MS)) {
        if (link->candidate_index + 1u <
            kGnssOperationalBootstrapBaudCount) {
          link->candidate_index++;
          link->candidate_baud =
              kGnssOperationalBootstrapBauds[link->candidate_index];
          link->pending_baud = link->candidate_baud;
          queue_link_action(link, OtisGnssLinkState::SelectCandidateBaud,
                            OtisGnssLinkActionKind::SetUartBaud);
        } else {
          link->operational_bootstrap_complete = true;
          link->candidate_baud = link->policy.target_baud;
          reset_link_line(link);
          queue_identity_query(link);
        }
      }
      break;
    case OtisGnssLinkState::OperationalBootstrapFailed:
      break;
    case OtisGnssLinkState::AwaitTargetIdentityResponse:
      if (elapsed_at_least(now_ms, link->state_started_ms,
                           link->policy.response_timeout_ms)) {
        link->configuration_failure_count++;
        fail_validation_or_restart(link, now_ms);
      }
      break;
    case OtisGnssLinkState::AwaitOutputConfigurationAck:
      if (elapsed_at_least(now_ms, link->state_started_ms,
                           link->policy.response_timeout_ms)) {
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
  link->valid_frame_seen = false;
  link->last_valid_frame_ms = 0u;
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
      link->target_baud_command_attempt_count++;
      if (!link->operational_bootstrap_complete) {
        link->operational_bootstrap_attempt_count++;
      } else {
        link->post_bootstrap_target_baud_command_attempt_count++;
      }
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
    if (!link->operational_bootstrap_complete &&
        (link->state == OtisGnssLinkState::SelectCandidateBaud ||
         link->state == OtisGnssLinkState::TransmitTargetBaud)) {
      fail_operational_bootstrap(link);
      return;
    }
    fail_validation_or_restart(link, now_ms);
    return;
  }

  switch (link->state) {
    case OtisGnssLinkState::SelectCandidateBaud:
      reset_link_line(link);
      queue_link_action(link, OtisGnssLinkState::TransmitTargetBaud,
                        OtisGnssLinkActionKind::TransmitTargetBaud);
      break;
    case OtisGnssLinkState::TransmitTargetBaud:
      link->operational_bootstrap_peripheral_complete_count++;
      if (link->operational_bootstrap_peripheral_complete_count == 1u) {
        link->operational_bootstrap_first_completed_baud =
            link->candidate_baud;
      } else if (link->operational_bootstrap_peripheral_complete_count == 2u) {
        link->operational_bootstrap_second_completed_baud =
            link->candidate_baud;
      }
      link->operational_bootstrap_completed_rate_mask |=
          static_cast<uint32_t>(1u << link->candidate_index);
      link->state = OtisGnssLinkState::OperationalBootstrapSettle;
      link->state_started_ms = now_ms;
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
  if (link->state == OtisGnssLinkState::OperationalBootstrapFailed)
    return "failed";
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
    case OtisGnssLinkState::TransmitTargetBaud:
      return "transmit_target_baud";
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
    case OtisGnssLinkState::OperationalBootstrapSettle:
      return "operational_bootstrap_settle";
    case OtisGnssLinkState::OperationalBootstrapFailed:
      return "operational_bootstrap_failed";
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
    case OtisGnssOutputConfirmationMethod::None:
      return "none";
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
          (kOtisGnssRp2040MonotonicUsPerSecond / 1000u),
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
          (kOtisGnssRp2040MonotonicUsPerSecond / 1000u));
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
          (kOtisGnssRp2040MonotonicUsPerSecond / 1000u),
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
    // Host-test callers convert now_ms into native microseconds. Live callers
    // finish active-duration accounting from the service extension.
    const uint64_t snapshot_ticks =
        static_cast<uint64_t>(now_ms) *
        (kOtisGnssRp2040MonotonicUsPerSecond / 1000u);
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
uint32_t live_uart_baud = 0u;
uint32_t live_uart_baud_epoch = 0u;
uint32_t live_post_bootstrap_baud_change_count = 0u;
uint32_t live_operational_bootstrap_rx_discarded_count = 0u;
uint32_t live_pmtk605_peripheral_complete_count = 0u;
uint64_t live_pmtk605_last_peripheral_complete_ticks = 0u;
bool live_pmtk605_last_peripheral_complete_ticks_available = false;

uint64_t live_service_raw_us = 0u;
uint64_t live_service_extended_us = 0u;
bool live_service_extension_available = false;

struct LiveGnssTransmit {
  bool active;
  const char *bytes;
  size_t length;
  size_t index;
  uint32_t started_ms;
};

LiveGnssTransmit live_transmit = {};

void close_collectors_for_planned_transition() {
  reset_link_line(&live_link);
  live_receiver.collecting = false;
  live_receiver.discarding_oversize = false;
  live_receiver.line_length = 0u;
}

static inline uint32_t live_monotonic_us32_from_register() {
  return timer_hw->timerawl;
}

uint64_t update_live_service_monotonic_us_extension() {
  const uint64_t raw_ticks = static_cast<uint64_t>(timer_hw->timerawl);
  if (!live_service_extension_available) {
    live_service_raw_us = raw_ticks;
    live_service_extended_us = raw_ticks;
    live_service_extension_available = true;
  } else {
    live_service_extended_us += otis_monotonic_us32_interval(
        live_service_raw_us, raw_ticks);
    live_service_raw_us = raw_ticks;
  }
  return live_service_extended_us;
}

void __not_in_flash_func(drain_live_uart0_fifo_to_ring)(
    bool record_interrupt_statistics) {
  const uint32_t entry_ticks = live_monotonic_us32_from_register();
  uint32_t drained = 0u;
  uart_hw_t *const hardware = uart_get_hw(uart0);
  while ((hardware->fr & UART_UARTFR_RXFE_BITS) == 0u) {
    const uint32_t data = hardware->dr;
    const OtisGnssUartObservation observation =
        otis_gnss_uart_observation_from_dr(data);
    otis_gnss_uart_rx_ring_push_from_isr(&live_uart_rx_ring, observation);
    drained++;
  }
  const uint32_t exit_ticks = live_monotonic_us32_from_register();
  if (record_interrupt_statistics)
    otis_gnss_uart_rx_ring_note_interrupt_from_isr(
        &live_uart_rx_ring, entry_ticks, exit_ticks, drained);
}

void __not_in_flash_func(otis_gnss_uart0_rx_isr)() {
  drain_live_uart0_fifo_to_ring(true);
}

bool live_uart0_rx_byte_available(void *context) {
  uart_hw_t *const hardware = static_cast<uart_hw_t *>(context);
  return (hardware->fr & UART_UARTFR_RXFE_BITS) == 0u;
}

void live_uart0_discard_rx_byte(void *context) {
  uart_hw_t *const hardware = static_cast<uart_hw_t *>(context);
  (void)hardware->dr;
}

bool prepare_live_uart_baud_change() {
  if (!live_uart_initialized) return true;
  uart_set_irq_enables(uart0, false, false);
  irq_set_enabled(UART0_IRQ, false);
  if (!live_link.operational_bootstrap_complete) {
    // Bytes received while deliberately listening at the non-matching member
    // of the fixed 9600/115200 pair are not qualification evidence. Discard
    // the bounded old-epoch frontier explicitly so continuous wrong-baud noise
    // cannot postpone the planned transition indefinitely.
    live_operational_bootstrap_rx_discarded_count +=
        otis_gnss_uart_rx_ring_discard_all(&live_uart_rx_ring);
    uart_hw_t *const hardware = uart_get_hw(uart0);
    live_operational_bootstrap_rx_discarded_count +=
        otis_gnss_uart_rx_bounded_hardware_discard(
            live_uart0_rx_byte_available, live_uart0_discard_rx_byte,
            hardware, kOtisGnssUartRxTransitionHardwareDiscardBudget);
    return true;
  }
  // This is a synchronous handoff drain with UART0 IRQ excluded, not an RX
  // interrupt. Preserve its bytes without fabricating interrupt statistics.
  drain_live_uart0_fifo_to_ring(false);
  if (otis_gnss_uart_rx_ring_depth(&live_uart_rx_ring) != 0u) {
    uart_set_irq_enables(uart0, true, false);
    irq_set_enabled(UART0_IRQ, true);
    return false;
  }
  return true;
}

void configure_live_uart(uint32_t baud, bool opening_baud_epoch) {
  if (live_uart_initialized) {
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
  if (opening_baud_epoch) {
    otis_gnss_uart_rx_ring_mark_baud_epoch(&live_uart_rx_ring);
    live_uart_baud_epoch++;
    if (live_uart_baud_epoch == 0u) live_uart_baud_epoch = 1u;
  }
  uart_set_irq_enables(uart0, true, false);
  irq_set_enabled(UART0_IRQ, true);
  live_uart_initialized = true;
  live_uart_baud = baud;
}

void service_live_uart_rx_ring(uint32_t now_ms) {
  const uint32_t entry_ticks = live_monotonic_us32_from_register();
  otis_gnss_uart_rx_ring_note_consumer_start(&live_uart_rx_ring, entry_ticks);

  OtisGnssUartRxStats uart_stats = {};
  otis_gnss_uart_rx_ring_snapshot(&live_uart_rx_ring, &uart_stats);
  const OtisGnssParserFaultContext context = {
      live_link.confirmed_baud != 0u ? live_link.confirmed_baud
                                     : live_link.candidate_baud,
      live_uart_baud_epoch,
      uart_stats.hardware_overrun_count,
      uart_stats.hardware_framing_count,
      uart_stats.hardware_parity_count,
      uart_stats.hardware_break_count,
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
            &live_receiver, now_ms, live_service_extended_us,
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
          &live_receiver, byte, now_ms, live_service_extended_us);
    drained++;
    if (static_cast<uint32_t>(live_monotonic_us32_from_register() -
                              entry_ticks) >=
        kOtisGnssUartRxConsumerBudgetUs) {
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
        live_service_extended_us;
    live_pmtk605_last_peripheral_complete_ticks_available =
        live_service_extension_available;
  }
  live_transmit = {};
  otis_gnss_link_complete_action(&live_link, true, now_ms);
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
  if (live_link.action_pending &&
      live_link.pending_action == OtisGnssLinkActionKind::SetUartBaud &&
      (!live_uart_initialized || live_link.pending_baud != live_uart_baud) &&
      !prepare_live_uart_baud_change())
    return;
  OtisGnssLinkAction action;
  if (!otis_gnss_link_take_action(&live_link, &action)) return;
  if (action.kind == OtisGnssLinkActionKind::SetUartBaud) {
    const bool baud_changed =
        !live_uart_initialized || action.baud != live_uart_baud;
    if (!baud_changed) {
      otis_gnss_link_complete_action(&live_link, true, now_ms);
      return;
    }
    if (live_link.operational_bootstrap_complete)
      live_post_bootstrap_baud_change_count++;
    configure_live_uart(action.baud, true);
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
  // Start only the bounded state machine here. The fixed operational bootstrap
  // identity validation, and configuration proceed incrementally so GNSS
  // cannot delay the timing-core boot handoff.
  live_receiver_started = false;
  live_uart_initialized = false;
  live_uart_irq_installed = false;
  live_uart_baud = 0u;
  live_uart_baud_epoch = 0u;
  live_post_bootstrap_baud_change_count = 0u;
  live_operational_bootstrap_rx_discarded_count = 0u;
  live_transmit = {};
  live_service_raw_us = 0u;
  live_service_extended_us = 0u;
  live_service_extension_available = false;
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
}

void otis_gnss_receiver_service(uint32_t now_ms) {
  // The UART ring, parser, link state, and transmitter are mutable Core 0
  // state. Keep the ownership invariant at the service boundary as well as at
  // its call sites so a future indirect Core 1 call cannot race them.
  if (get_core_num() != 0u) return;
  if (!live_receiver_started) return;
  update_live_service_monotonic_us_extension();
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
      &live_receiver, now_ms, live_service_extended_us,
      OTIS_GNSS_RECONNECT_GAP_MS);
  // Ordinary response deadlines cannot advance past bytes already accepted by
  // the ISR for the current candidate. The fixed operational settle is the
  // sole exception: old-epoch bytes are deliberately non-qualification
  // evidence and cannot postpone its finite baud transition.
  if (otis_gnss_uart_rx_ring_depth(&live_uart_rx_ring) == 0u ||
      otis_gnss_link_tick_may_advance_with_rx_backlog(&live_link))
    otis_gnss_link_tick(&live_link, now_ms);
  begin_pending_link_action(now_ms);
}

void otis_gnss_receiver_get_snapshot(uint32_t now_ms,
                                     OtisGnssReceiverSnapshot *snapshot) {
  otis_gnss_receiver_snapshot(&live_receiver, now_ms,
                              OTIS_GNSS_METADATA_MAX_AGE_MS, snapshot);
  if (live_receiver.metadata_hold_active &&
      live_service_extension_available &&
      live_service_extended_us >=
          live_receiver.metadata_hold_started_ticks) {
    const uint64_t active_ticks =
        live_service_extended_us -
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
  snapshot->operational_bootstrap_complete =
      live_link.operational_bootstrap_complete;
  snapshot->operational_bootstrap_failed =
      live_link.operational_bootstrap_failed;
  snapshot->operational_bootstrap_attempt_count =
      live_link.operational_bootstrap_attempt_count;
  snapshot->target_baud_command_attempt_count =
      live_link.target_baud_command_attempt_count;
  snapshot->post_bootstrap_target_baud_command_attempt_count =
      live_link.post_bootstrap_target_baud_command_attempt_count;
  snapshot->operational_bootstrap_peripheral_complete_count =
      live_link.operational_bootstrap_peripheral_complete_count;
  snapshot->operational_bootstrap_completed_rate_mask =
      live_link.operational_bootstrap_completed_rate_mask;
  snapshot->operational_bootstrap_first_completed_baud =
      live_link.operational_bootstrap_first_completed_baud;
  snapshot->operational_bootstrap_second_completed_baud =
      live_link.operational_bootstrap_second_completed_baud;
  snapshot->local_uart_baud = live_uart_baud;
  snapshot->local_uart_baud_epoch = live_uart_baud_epoch;
  snapshot->post_bootstrap_baud_change_count =
      live_post_bootstrap_baud_change_count;
  snapshot->operational_bootstrap_rx_discarded_count =
      live_operational_bootstrap_rx_discarded_count;
  snapshot->link_last_valid_frame_age_ms =
      live_link.valid_frame_seen
          ? static_cast<uint32_t>(now_ms - live_link.last_valid_frame_ms)
          : UINT32_MAX;
  snapshot->link_checksum_valid_count = live_link.checksum_valid_count;
  snapshot->link_checksum_failure_count = live_link.checksum_failure_count;
  snapshot->link_oversize_count = live_link.oversize_count;
  snapshot->configuration_failure_count =
      live_link.configuration_failure_count;
  snapshot->transmit_failure_count = live_link.transmit_failure_count;
  snapshot->link_loss_count = live_link.link_loss_count;
  snapshot->link_raw_acquisition_loss_count =
      live_link.raw_acquisition_loss_count;
  snapshot->identity_response_count = live_link.identity_response_count;
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
}

#endif
