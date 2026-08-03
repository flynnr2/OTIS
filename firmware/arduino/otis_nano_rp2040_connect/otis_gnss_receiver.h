#ifndef OTIS_GNSS_RECEIVER_H
#define OTIS_GNSS_RECEIVER_H

#include <stddef.h>
#include <stdint.h>

constexpr size_t kOtisGnssMaximumLineBytes = 96u;

struct OtisGnssReceiver {
  char line[kOtisGnssMaximumLineBytes];
  uint8_t line_length;
  bool collecting;
  bool discarding_oversize;
  bool initialized;
  bool rx_only;
  bool disconnected;
  bool rmc_seen;
  bool gga_seen;
  bool rmc_valid;
  bool rmc_utc_available;
  bool gga_utc_available;
  bool utc_available;
  bool date_available;
  uint8_t fix_quality;
  uint8_t satellites;
  char talker[3];
  char utc[11];
  char date[7];
  char hdop[9];
  uint32_t identity_epoch;
  uint32_t parser_fault_epoch;
  uint32_t rmc_repair_epoch;
  uint32_t gga_repair_epoch;
  uint32_t last_message_ms;
  uint32_t last_rmc_ms;
  uint32_t last_gga_ms;
  uint32_t checksum_valid_count;
  uint32_t checksum_failure_count;
  uint32_t parser_drop_count;
  uint32_t truncated_count;
  uint32_t oversize_count;
  uint32_t rmc_count;
  uint32_t gga_count;
};

struct OtisGnssReceiverSnapshot {
  bool initialized;
  bool rx_only;
  bool disconnected;
  bool rmc_seen;
  bool gga_seen;
  bool rmc_valid;
  bool utc_available;
  bool date_available;
  bool metadata_fresh;
  bool checksum_requalified;
  bool identity_stable;
  bool control_eligible;
  uint8_t fix_quality;
  uint8_t satellites;
  char talker[3];
  char utc[11];
  char date[7];
  char hdop[9];
  uint32_t identity_epoch;
  uint32_t metadata_age_ms;
  uint32_t checksum_valid_count;
  uint32_t checksum_failure_count;
  uint32_t parser_drop_count;
  uint32_t truncated_count;
  uint32_t oversize_count;
  uint32_t rmc_count;
  uint32_t gga_count;
};

void otis_gnss_receiver_reset(OtisGnssReceiver *receiver, uint32_t now_ms);
void otis_gnss_receiver_feed(OtisGnssReceiver *receiver, char byte,
                             uint32_t now_ms);
void otis_gnss_receiver_note_time(OtisGnssReceiver *receiver, uint32_t now_ms,
                                  uint32_t reconnect_gap_ms);
void otis_gnss_receiver_snapshot(const OtisGnssReceiver *receiver,
                                 uint32_t now_ms, uint32_t maximum_age_ms,
                                 OtisGnssReceiverSnapshot *snapshot);

#if !defined(OTIS_GNSS_HOST_TEST)
bool otis_gnss_receiver_begin(void);
void otis_gnss_receiver_service(uint32_t now_ms);
void otis_gnss_receiver_get_snapshot(uint32_t now_ms,
                                     OtisGnssReceiverSnapshot *snapshot);
#endif

#endif
