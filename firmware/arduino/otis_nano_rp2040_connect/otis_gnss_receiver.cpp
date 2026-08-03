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
  } else {
    return;
  }
  if (!parsed) {
    receiver->truncated_count++;
    note_parser_fault(receiver);
  }
}

}  // namespace

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
  snapshot->rmc_valid = receiver->rmc_valid;
  snapshot->utc_available = receiver->utc_available;
  snapshot->date_available = receiver->date_available;
  snapshot->fix_quality = receiver->fix_quality;
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

  const bool rmc_fresh = receiver->rmc_seen &&
                         !elapsed_at_least(now_ms, receiver->last_rmc_ms,
                                           maximum_age_ms + 1u);
  const bool gga_fresh = receiver->gga_seen &&
                         !elapsed_at_least(now_ms, receiver->last_gga_ms,
                                           maximum_age_ms + 1u);
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
bool live_receiver_started = false;
}

bool otis_gnss_receiver_begin(void) {
#if OTIS_ENABLE_GNSS_RECEIVER
  // The installed arduino-pico 6.0.0 Nano variant maps Serial1 to UART0,
  // PIN_SERIAL1_RX/D0/GPIO1 and PIN_SERIAL1_TX/D1/GPIO0. Configure only the
  // receive pin for UART. The TX pin remains high-impedance SIO input, and this
  // module exposes no write function.
  live_receiver_started = false;
  uart_init(uart0, OTIS_GNSS_UART_BAUD);
  uart_set_format(uart0, 8u, 1u, UART_PARITY_NONE);
  uart_set_hw_flow(uart0, false, false);
  uart_set_fifo_enabled(uart0, true);
  gpio_init(OTIS_PIN_GNSS_TX_SILENT);
  gpio_set_dir(OTIS_PIN_GNSS_TX_SILENT, GPIO_IN);
  gpio_disable_pulls(OTIS_PIN_GNSS_TX_SILENT);
  gpio_set_function(OTIS_PIN_GNSS_RX, GPIO_FUNC_UART);
  gpio_disable_pulls(OTIS_PIN_GNSS_RX);
  otis_gnss_receiver_reset(&live_receiver, millis());
  live_receiver_started = true;
  return true;
#else
  return false;
#endif
}

void otis_gnss_receiver_service(uint32_t now_ms) {
#if OTIS_ENABLE_GNSS_RECEIVER
  if (!live_receiver_started) return;
  otis_gnss_receiver_note_time(&live_receiver, now_ms,
                               OTIS_GNSS_RECONNECT_GAP_MS);
  uint8_t remaining = OTIS_GNSS_SERVICE_BYTE_BUDGET;
  while (remaining-- > 0u && uart_is_readable(uart0))
    otis_gnss_receiver_feed(&live_receiver,
                            static_cast<char>(uart_getc(uart0)), now_ms);
#else
  (void)now_ms;
#endif
}

void otis_gnss_receiver_get_snapshot(uint32_t now_ms,
                                     OtisGnssReceiverSnapshot *snapshot) {
#if OTIS_ENABLE_GNSS_RECEIVER
  otis_gnss_receiver_snapshot(&live_receiver, now_ms,
                              OTIS_GNSS_METADATA_MAX_AGE_MS, snapshot);
#else
  if (snapshot != nullptr) *snapshot = {};
  (void)now_ms;
#endif
}

#endif
